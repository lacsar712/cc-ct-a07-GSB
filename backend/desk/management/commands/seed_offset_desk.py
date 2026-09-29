from django.core.management.base import BaseCommand
from django.utils import timezone

from desk.auth_utils import hash_password
from desk.models import DailyTicket, OffsetSubmission, User


class Command(BaseCommand):
    help = "创建默认账号、种子刀补记录与当日日券"

    def handle(self, *args, **options):
        machinist, _ = User.objects.update_or_create(
            username="machinist",
            defaults={
                "role": User.Role.MACHINIST,
                "password": hash_password("machine123456"),
                "is_active": True,
            },
        )
        User.objects.update_or_create(
            username="auditor",
            defaults={
                "role": User.Role.AUDITOR,
                "password": hash_password("audit123456"),
                "is_active": True,
            },
        )

        now = timezone.now()
        seeds = [
            ("T01", 5, OffsetSubmission.Verdict.PASS),
            ("T09", 20, OffsetSubmission.Verdict.FAIL),
        ]
        for tool_code, offset_um, verdict in seeds:
            OffsetSubmission.objects.update_or_create(
                tool_code=tool_code,
                offset_um=offset_um,
                defaults={
                    "status": OffsetSubmission.Status.DONE,
                    "verdict": verdict,
                    "submitted_by": machinist,
                    "reviewed_at": now,
                },
            )

        # 给操作员备一张当日在用新券，便于直接演示「挂券交单 → 进待复核」。
        # 每个自然日一张；只在当日尚无券时补发，绝不把已用/已作废券复活。
        # 跨天重跑会为新一天再发，昨日券保留为旧券以演示挡回。
        today = timezone.localdate()
        DailyTicket.objects.get_or_create(
            issued_to=machinist,
            ticket_date=today,
            defaults={
                "code": f"T{today.strftime('%Y%m%d')}-SEED0001",
                "status": DailyTicket.Status.VALID,
            },
        )

        self.stdout.write(self.style.SUCCESS("seed_offset_desk 完成"))
