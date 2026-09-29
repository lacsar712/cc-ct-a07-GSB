from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MACHINIST = "machinist", "操作员"
        AUDITOR = "auditor", "复核员"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MACHINIST,
    )

    @property
    def can_write(self) -> bool:
        return self.role == self.Role.MACHINIST


class OffsetSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待复核"
        PROCESSING = "processing", "复核中"
        DONE = "done", "已完成"

    class Verdict(models.TextChoices):
        PASS = "合格", "合格"
        FAIL = "超差", "超差"

    tool_code = models.CharField(max_length=32, db_index=True)
    offset_um = models.IntegerField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    verdict = models.CharField(
        max_length=8,
        choices=Verdict.choices,
        blank=True,
        default="",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    ticket = models.OneToOneField(
        "DailyTicket",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submission",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tool_code} {self.offset_um}µm"


class DailyTicket(models.Model):
    """日券：操作员每个自然日至多一张，凭券交单，挂券成功即核销。"""

    class Status(models.TextChoices):
        VALID = "valid", "在用"
        REDEEMED = "redeemed", "已用"
        VOIDED = "voided", "已作废"

    code = models.CharField(max_length=40, unique=True, db_index=True)
    ticket_date = models.DateField(db_index=True)
    issued_to = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.VALID,
        db_index=True,
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redeemed_tickets",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voided_tickets",
    )
    void_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-ticket_date", "-id"]
        constraints = [
            # 每个操作员每个自然日只发一张日券
            models.UniqueConstraint(
                fields=["issued_to", "ticket_date"],
                name="uniq_ticket_per_user_per_day",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.ticket_date}"


class TicketVoidRecord(models.Model):
    """作废簿：券作废留痕，只追加，不改写。"""

    ticket = models.ForeignKey(
        DailyTicket,
        on_delete=models.PROTECT,
        related_name="void_records",
    )
    code = models.CharField(max_length=40, db_index=True)
    ticket_date = models.DateField(db_index=True)
    voided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ticket_void_records",
    )
    reason = models.CharField(max_length=200, blank=True, default="")
    voided_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-voided_at", "-id"]

    def __str__(self) -> str:
        return f"作废 {self.code}"
