from datetime import date, datetime
from typing import Optional

from django.http import HttpRequest
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import DailyTicket, OffsetSubmission, TicketVoidRecord, User
from desk.services import (
    TicketError,
    issue_daily_ticket,
    redeem_ticket,
    void_ticket,
)
from django.utils import timezone

api = NinjaAPI(title="数控刀补复核台", version="1.0")


class HealthOut(Schema):
    status: str


class LoginIn(Schema):
    username: str
    password: str


class LoginOut(Schema):
    token: str
    username: str
    role: str
    can_write: bool


class SubmissionIn(Schema):
    tool_code: str
    offset_um: int


class SubmissionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    status: str
    verdict: str
    ticket_id: Optional[int]
    ticket_code: Optional[str]
    created_at: datetime
    reviewed_at: Optional[datetime]


class RedeemIn(Schema):
    tool_code: str
    offset_um: int


class VoidIn(Schema):
    reason: str = ""


class TicketOut(Schema):
    id: int
    code: str
    ticket_date: date
    status: str
    issued_to: str
    issued_at: datetime
    redeemed_at: Optional[datetime]
    voided_at: Optional[datetime]
    void_reason: str
    redeemable: bool


class VoidRecordOut(Schema):
    id: int
    code: str
    ticket_date: date
    voided_by: Optional[str]
    reason: str
    voided_at: datetime


def _to_out(row: OffsetSubmission) -> SubmissionOut:
    ticket = getattr(row, "ticket", None)
    return SubmissionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        status=row.status,
        verdict=row.verdict or "",
        ticket_id=ticket.id if ticket is not None else None,
        ticket_code=ticket.code if ticket is not None else None,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _ticket_to_out(ticket: DailyTicket) -> TicketOut:
    today = timezone.localdate()
    return TicketOut(
        id=ticket.id,
        code=ticket.code,
        ticket_date=ticket.ticket_date,
        status=ticket.status,
        issued_to=ticket.issued_to.username,
        issued_at=ticket.issued_at,
        redeemed_at=ticket.redeemed_at,
        voided_at=ticket.voided_at,
        void_reason=ticket.void_reason or "",
        redeemable=(
            ticket.status == DailyTicket.Status.VALID
            and ticket.ticket_date == today
        ),
    )


def _void_to_out(record: TicketVoidRecord) -> VoidRecordOut:
    return VoidRecordOut(
        id=record.id,
        code=record.code,
        ticket_date=record.ticket_date,
        voided_by=record.voided_by.username if record.voided_by_id else None,
        reason=record.reason or "",
        voided_at=record.voided_at,
    )


def _require_write(user: User) -> None:
    if not user.can_write:
        raise HttpError(403, "当前账号只读，不能进行发券、交单或作废操作")


@api.get("/health", response=HealthOut)
def health(request: HttpRequest):
    return {"status": "ok"}


@api.post("/auth/login", response=LoginOut)
def login(request: HttpRequest, body: LoginIn):
    try:
        user = User.objects.get(username=body.username)
    except User.DoesNotExist:
        raise HttpError(401, "用户名或密码错误")
    if not verify_password(body.password, user.password):
        raise HttpError(401, "用户名或密码错误")
    token = create_access_token(user)
    return {
        "token": token,
        "username": user.username,
        "role": user.role,
        "can_write": user.can_write,
    }


@api.get("/submissions", response=list[SubmissionOut], auth=bearer_auth)
def list_submissions(request: HttpRequest):
    rows = OffsetSubmission.objects.select_related("ticket").all()[:200]
    return [_to_out(r) for r in rows]


@api.get("/submissions/{submission_id}", response=SubmissionOut, auth=bearer_auth)
def get_submission(request: HttpRequest, submission_id: int):
    try:
        row = OffsetSubmission.objects.select_related("ticket").get(pk=submission_id)
    except OffsetSubmission.DoesNotExist:
        raise HttpError(404, "刀补记录不存在")
    return _to_out(row)


@api.post("/submissions", response=SubmissionOut, auth=bearer_auth)
def create_submission(request: HttpRequest, body: SubmissionIn):
    user: User = request.auth
    _require_write(user)
    tool_code = body.tool_code.strip()
    if not tool_code:
        raise HttpError(400, "刀具编号不能为空")
    row = OffsetSubmission.objects.create(
        tool_code=tool_code,
        offset_um=body.offset_um,
        submitted_by=user,
        status=OffsetSubmission.Status.PENDING,
    )
    return _to_out(row)


@api.get("/tickets", response=list[TicketOut], auth=bearer_auth)
def list_tickets(request: HttpRequest, status: Optional[str] = None):
    """分发券区：默认返回全部券，可按 status=valid|redeemed|voided 过滤。"""
    qs = DailyTicket.objects.select_related("issued_to").all()
    if status:
        qs = qs.filter(status=status)
    return [_ticket_to_out(t) for t in qs[:200]]


@api.get("/tickets/voided", response=list[VoidRecordOut], auth=bearer_auth)
def list_voided(request: HttpRequest):
    """作废簿：只读作废留痕。"""
    rows = TicketVoidRecord.objects.select_related("voided_by").all()[:200]
    return [_void_to_out(r) for r in rows]


@api.post("/tickets/issue", response=TicketOut, auth=bearer_auth)
def issue_ticket(request: HttpRequest):
    """领取当日券：每操作员每自然日一张，重复领取幂等返回已有券。"""
    user: User = request.auth
    _require_write(user)
    ticket = issue_daily_ticket(user)
    return _ticket_to_out(ticket)


@api.post("/tickets/{ticket_id}/redeem", response=SubmissionOut, auth=bearer_auth)
def redeem_ticket_endpoint(
    request: HttpRequest, ticket_id: int, body: RedeemIn
):
    """挂当日券交单：入队与核销同一事务；旧券/已用/已作废一律挡回。"""
    user: User = request.auth
    _require_write(user)
    try:
        submission = redeem_ticket(
            ticket_id=ticket_id,
            user=user,
            tool_code=body.tool_code,
            offset_um=body.offset_um,
        )
    except TicketError as exc:
        raise HttpError(409, str(exc))
    return _to_out(submission)


@api.post("/tickets/{ticket_id}/void", response=VoidRecordOut, auth=bearer_auth)
def void_ticket_endpoint(
    request: HttpRequest, ticket_id: int, body: VoidIn
):
    """作废在用券：作废与作废簿记录同一事务落库。"""
    user: User = request.auth
    _require_write(user)
    try:
        record = void_ticket(
            ticket_id=ticket_id,
            user=user,
            reason=(body.reason or "").strip(),
        )
    except TicketError as exc:
        raise HttpError(409, str(exc))
    return _void_to_out(record)
