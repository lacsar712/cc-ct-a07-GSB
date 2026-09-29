from django.core.management.base import BaseCommand
from django.utils import timezone

from desk.auth_utils import hash_password
from desk.models import DailyTicket, OffsetSubmission, User
from desk.services import distribute_daily_tickets


class Command(BaseCommand):
    help = "创建默认账号、种子刀补记录，并按自然日为操作员补齐当日五张券"

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

        # 按自然日幂等补齐当日券（五张）；已发放则不重发、不补发已用张数。
        tickets = distribute_daily_tickets(machinist)

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_offset_desk 完成，当日在用券 {len(tickets)} 张："
                + "、".join(t.code for t in tickets)
            )
        )
