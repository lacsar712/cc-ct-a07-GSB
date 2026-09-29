from datetime import date, datetime
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.http import HttpRequest
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import DailyTicket, OffsetSubmission, User
from desk.services import (
    TicketError,
    distribute_daily_tickets,
    list_today_tickets,
    list_voided_tickets,
    submit_with_ticket,
)

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
    ticket_code: str
    tool_code: str
    offset_um: int


class SubmissionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    status: str
    verdict: str
    ticket_code: Optional[str]
    created_at: datetime
    reviewed_at: Optional[datetime]


class TicketOut(Schema):
    code: str
    issue_date: date
    state: str
    issued_to: str
    issued_at: datetime
    voided_at: Optional[datetime]
    submission_id: Optional[int]
    valid_today: bool


def _to_out(row: OffsetSubmission) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        status=row.status,
        verdict=row.verdict or "",
        ticket_code=row.ticket.code if row.ticket_id else None,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _ticket_to_out(t: DailyTicket) -> TicketOut:
    submission_id: Optional[int] = None
    if t.state == DailyTicket.State.VOIDED:
        try:
            submission_id = t.submission.id
        except ObjectDoesNotExist:
            submission_id = None
    return TicketOut(
        code=t.code,
        issue_date=t.issue_date,
        state=t.state,
        issued_to=t.issued_to.username,
        issued_at=t.issued_at,
        voided_at=t.voided_at,
        submission_id=submission_id,
        valid_today=t.is_valid_today,
    )


def _require_write(user: User) -> None:
    if not user.can_write:
        raise HttpError(403, "当前账号只读，不能发券或交单")


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
    try:
        row = submit_with_ticket(
            user=user,
            ticket_code=body.ticket_code,
            tool_code=body.tool_code,
            offset_um=body.offset_um,
        )
    except TicketError as e:
        raise HttpError(e.status, e.message)
    except IntegrityError:
        # 并发兜底：OneToOne 唯一约束挡住第二笔同券交单。
        raise HttpError(409, "该券刚被他人挂走入队，本笔挡回")
    return _to_out(row)


@api.get("/tickets/today", response=list[TicketOut], auth=bearer_auth)
def tickets_today(request: HttpRequest):
    """当日券（在用券 + 分发券区）。操作员看自己的券；观察账号可翻看全部。"""
    user: User = request.auth
    if user.can_write:
        rows = list_today_tickets(user)
    else:
        rows = list(
            DailyTicket.objects.filter(issue_date=timezone.localdate()).order_by("code")
        )
    return [_ticket_to_out(t) for t in rows]


@api.get("/tickets/voided", response=list[TicketOut], auth=bearer_auth)
def tickets_voided(request: HttpRequest):
    """作废簿：只读可翻，任何人不能从此处复活券。"""
    user: User = request.auth
    if user.can_write:
        rows = list_voided_tickets(user)
    else:
        rows = list(
            DailyTicket.objects.filter(state=DailyTicket.State.VOIDED).order_by(
                "-voided_at", "-id"
            )[:200]
        )
    return [_ticket_to_out(t) for t in rows]


@api.post("/tickets/distribute", response=list[TicketOut], auth=bearer_auth)
def tickets_distribute(request: HttpRequest):
    """按自然日发放当日券（幂等补齐五张）；只读观察账号禁止发券。"""
    user: User = request.auth
    _require_write(user)
    rows = distribute_daily_tickets(user)
    return [_ticket_to_out(t) for t in rows]
