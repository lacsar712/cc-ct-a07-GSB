import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from desk.models import DailyTicket, OffsetSubmission, TicketVoidRecord, User


class TicketError(Exception):
    """券业务规则被违反（旧券/错挂/已用/已作废等），一律挡回。"""


def evaluate_verdict(offset_um: int) -> str:
    if abs(offset_um) <= settings.OFFSET_TOLERANCE_UM:
        return OffsetSubmission.Verdict.PASS
    return OffsetSubmission.Verdict.FAIL


def apply_verdict(submission: OffsetSubmission) -> None:
    submission.verdict = evaluate_verdict(submission.offset_um)
    submission.status = OffsetSubmission.Status.DONE
    submission.reviewed_at = timezone.now()
    submission.save(
        update_fields=["verdict", "status", "reviewed_at"],
    )


def _today():
    return timezone.localdate()


def issue_daily_ticket(user: User) -> DailyTicket:
    """发出当日券：每个操作员每个自然日至多一张，重复领取幂等返回已有券。"""
    today = _today()
    ticket = DailyTicket.objects.filter(issued_to=user, ticket_date=today).first()
    if ticket is not None:
        return ticket
    code = f"T{today.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    try:
        with transaction.atomic():
            return DailyTicket.objects.create(
                code=code,
                ticket_date=today,
                issued_to=user,
                status=DailyTicket.Status.VALID,
            )
    except IntegrityError:
        # 并发首领：自然日唯一约束兜底，返回已落库的那张
        return DailyTicket.objects.get(issued_to=user, ticket_date=today)


def redeem_ticket(
    *,
    ticket_id: int,
    user: User,
    tool_code: str,
    offset_um: int,
) -> OffsetSubmission:
    """挂券交单。

    入队（建待复核记录）与券核销在同一事务内落库：锁券行 → 校验仍为当日
    在用券 → 建入队记录 → 标记已用。任一步失败整体回滚，不会出现「已入队
    但券仍可复用」。两人并发挂同一张券时，行锁把两笔串行化，第二笔拿到锁
    后看到的已是已用券，挡回。
    """
    tool_code = (tool_code or "").strip()
    if not tool_code:
        raise TicketError("刀具编号不能为空")

    with transaction.atomic():
        ticket = (
            DailyTicket.objects.select_for_update()
            .filter(pk=ticket_id)
            .first()
        )
        if ticket is None:
            raise TicketError("券不存在")

        if ticket.issued_to_id != user.id:
            raise TicketError("这不是本人名下的日券，挂错一律挡回")

        if ticket.ticket_date != _today():
            raise TicketError("旧券不可交单，请领取当日券")

        if ticket.status == DailyTicket.Status.VOIDED:
            raise TicketError("券已作废，不能交单")
        if ticket.status == DailyTicket.Status.REDEEMED:
            raise TicketError("该券已使用，不能重复交单")
        if ticket.status != DailyTicket.Status.VALID:
            raise TicketError("券状态异常，不能交单")

        submission = OffsetSubmission.objects.create(
            tool_code=tool_code,
            offset_um=offset_um,
            submitted_by=user,
            ticket=ticket,
            status=OffsetSubmission.Status.PENDING,
        )
        now = timezone.now()
        ticket.status = DailyTicket.Status.REDEEMED
        ticket.redeemed_at = now
        ticket.redeemed_by = user
        ticket.save(
            update_fields=["status", "redeemed_at", "redeemed_by"],
        )
        return submission


def void_ticket(*, ticket_id: int, user: User, reason: str = "") -> TicketVoidRecord:
    """作废一张在用券：作废状态与作废簿记录同一事务落库，只追加留痕。"""
    with transaction.atomic():
        ticket = (
            DailyTicket.objects.select_for_update()
            .filter(pk=ticket_id)
            .first()
        )
        if ticket is None:
            raise TicketError("券不存在")
        if ticket.status == DailyTicket.Status.REDEEMED:
            raise TicketError("券已随交单使用，不能作废")
        if ticket.status == DailyTicket.Status.VOIDED:
            raise TicketError("券已作废，不能重复作废")
        if ticket.status != DailyTicket.Status.VALID:
            raise TicketError("券状态异常，不能作废")

        now = timezone.now()
        ticket.status = DailyTicket.Status.VOIDED
        ticket.voided_at = now
        ticket.voided_by = user
        ticket.void_reason = reason or ""
        ticket.save(
            update_fields=["status", "voided_at", "voided_by", "void_reason"],
        )
        record = TicketVoidRecord.objects.create(
            ticket=ticket,
            code=ticket.code,
            ticket_date=ticket.ticket_date,
            voided_by=user,
            reason=reason or "",
        )
        return record
