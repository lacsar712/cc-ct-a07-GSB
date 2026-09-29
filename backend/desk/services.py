from django.conf import settings
from django.db import transaction
from django.utils import timezone

from desk.models import DailyTicket, OffsetSubmission, User

DAILY_TICKET_COUNT = 5


class TicketError(Exception):
    """挂券交单被挡回时抛出，携带 HTTP 状态码与中文原因。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


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


def _ticket_code(username: str, day, seq: int) -> str:
    return f"{username.upper()}-{day:%Y%m%d}-{seq:02d}"


@transaction.atomic
def distribute_daily_tickets(user: User, count: int = DAILY_TICKET_COUNT) -> list[DailyTicket]:
    """按自然日为操作员补齐当日券；幂等，重复分发只补缺口，不会重发。

    锁住用户行，避免并发双击各发一套。
    """
    today = timezone.localdate()
    locked = User.objects.select_for_update().get(pk=user.pk)
    existing = list(
        DailyTicket.objects.filter(issued_to=locked, issue_date=today).order_by("code")
    )
    have = len(existing)
    if have >= count:
        return existing
    for seq in range(have + 1, count + 1):
        DailyTicket.objects.create(
            code=_ticket_code(locked.username, today, seq),
            issue_date=today,
            issued_to=locked,
            state=DailyTicket.State.VALID,
        )
    return list(
        DailyTicket.objects.filter(issued_to=locked, issue_date=today).order_by("code")
    )


def list_today_tickets(user: User) -> list[DailyTicket]:
    today = timezone.localdate()
    return list(
        DailyTicket.objects.filter(issued_to=user, issue_date=today).order_by("code")
    )


def list_voided_tickets(user: User) -> list[DailyTicket]:
    return list(
        DailyTicket.objects.filter(
            issued_to=user,
            state=DailyTicket.State.VOIDED,
        ).order_by("-voided_at", "-id")[:200]
    )


@transaction.atomic
def submit_with_ticket(
    user: User,
    ticket_code: str,
    tool_code: str,
    offset_um: int,
) -> OffsetSubmission:
    """挂当日券交单：校验、入队、券作废必须在同一事务内落库。

    行锁串行化并发：两人同挂一张券，后到者在锁释放后读到的已是作废状态而被挡回；
    加上 OffsetSubmission.ticket 的 OneToOne 唯一约束做结构兜底，
    杜绝「先入队、后作废失败」留下可复用券。
    """
    today = timezone.localdate()
    code = (ticket_code or "").strip()
    if not code:
        raise TicketError("必须挂一张当日券才能交单", 400)

    ticket = (
        DailyTicket.objects.select_for_update()
        .filter(code=code)
        .first()
    )
    if ticket is None:
        raise TicketError("券不存在，交单挡回", 404)
    if ticket.issued_to_id != user.id:
        raise TicketError("该券不属于当前操作员，挂错一律挡回", 403)
    if ticket.issue_date != today:
        raise TicketError("该券不是当日有效券（旧券），一律挡回", 400)
    if ticket.state != DailyTicket.State.VALID:
        raise TicketError("该券已作废，不能重复交单", 400)

    tool = (tool_code or "").strip()
    if not tool:
        raise TicketError("刀具编号不能为空", 400)

    # 入队与券作废在同一事务：任一步失败整体回滚。
    submission = OffsetSubmission.objects.create(
        tool_code=tool,
        offset_um=offset_um,
        submitted_by=user,
        status=OffsetSubmission.Status.PENDING,
        ticket=ticket,
    )
    ticket.state = DailyTicket.State.VOIDED
    ticket.voided_at = timezone.now()
    ticket.save(update_fields=["state", "voided_at"])
    return submission


def void_expired_tickets() -> int:
    """把往日仍处于在用状态的券标记作废（自然日失效，可选维护动作）。"""
    today = timezone.localdate()
    return DailyTicket.objects.filter(
        state=DailyTicket.State.VALID,
        issue_date__lt=today,
    ).update(state=DailyTicket.State.VOIDED, voided_at=timezone.now())
