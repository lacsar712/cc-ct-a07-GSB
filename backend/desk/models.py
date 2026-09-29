from datetime import date

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


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


class DailyTicket(models.Model):
    """当日券：按自然日发放，每张券当天只能挂单交单一次。

    - valid：当日尚未使用，可挂单；
    - voided：已随交单入队同时作废（或过期），不可再用。
    券与交单一一对应，从结构上杜绝同一张券复用。
    """

    class State(models.TextChoices):
        VALID = "valid", "在用"
        VOIDED = "voided", "已作废"

    code = models.CharField(max_length=40, unique=True, db_index=True)
    issue_date = models.DateField(db_index=True)
    issued_to = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.VALID,
        db_index=True,
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issue_date", "code"]
        indexes = [
            models.Index(fields=["issued_to", "issue_date", "state"]),
        ]

    def __str__(self) -> str:
        return f"{self.code}（{self.issue_date}）"

    @property
    def is_valid_today(self) -> bool:
        return (
            self.state == self.State.VALID
            and self.issue_date == timezone.localdate()
        )


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
    # 每张日券最多对应一笔交单；旧种子数据允许为空。
    ticket = models.OneToOneField(
        DailyTicket,
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
