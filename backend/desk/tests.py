"""日券交单的并发、挡回与权限测试。

必须在真实 PostgreSQL 上运行（select_for_update 行锁）。
使用 TransactionTestCase，让每个跨线程连接看到已提交数据、行锁真实阻塞。
"""

import threading
from datetime import timedelta
from unittest import mock

from django.db import IntegrityError, connection, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone

from desk.auth_utils import create_access_token
from desk.models import DailyTicket, OffsetSubmission, User
from desk.services import TicketError, distribute_daily_tickets, submit_with_ticket


class TicketTestBase(TransactionTestCase):
    def setUp(self):
        self.m1 = User.objects.create_user(
            username="m1", password="pw123456", role=User.Role.MACHINIST
        )
        self.m2 = User.objects.create_user(
            username="m2", password="pw123456", role=User.Role.MACHINIST
        )
        self.auditor = User.objects.create_user(
            username="aud", password="pw123456", role=User.Role.AUDITOR
        )

    def make_ticket(self, owner, day=None, state=DailyTicket.State.VALID):
        day = day or timezone.localdate()
        n = DailyTicket.objects.count() + 1
        return DailyTicket.objects.create(
            code=f"{owner.username.upper()}-{day:%Y%m%d}-{n:03d}",
            issue_date=day,
            issued_to=owner,
            state=state,
        )

    def auth(self, user):
        token = create_access_token(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class AtomicSubmitTests(TicketTestBase):
    def test_valid_ticket_submits_and_voids_in_one_tx(self):
        t = self.make_ticket(self.m1)
        sub = submit_with_ticket(self.m1, t.code, "T01", 5)
        self.assertEqual(sub.status, OffsetSubmission.Status.PENDING)
        self.assertEqual(sub.ticket_id, t.id)
        t.refresh_from_db()
        self.assertEqual(t.state, DailyTicket.State.VOIDED)
        self.assertIsNotNone(t.voided_at)
        # 入队的交单与作废一一对应。
        self.assertEqual(OffsetSubmission.objects.filter(ticket=t).count(), 1)

    def test_voided_ticket_second_submit_blocked(self):
        t = self.make_ticket(self.m1)
        submit_with_ticket(self.m1, t.code, "T01", 5)
        with self.assertRaises(TicketError) as ctx:
            submit_with_ticket(self.m1, t.code, "T02", 6)
        self.assertEqual(ctx.exception.status, 400)
        # 拿作废券再交，只有一笔入队。
        self.assertEqual(OffsetSubmission.objects.filter(ticket=t).count(), 1)

    def test_old_ticket_blocked(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        t = self.make_ticket(self.m1, day=yesterday)
        with self.assertRaises(TicketError):
            submit_with_ticket(self.m1, t.code, "T01", 5)
        self.assertEqual(OffsetSubmission.objects.count(), 0)

    def test_other_owner_ticket_blocked(self):
        t = self.make_ticket(self.m1)
        with self.assertRaises(TicketError) as ctx:
            submit_with_ticket(self.m2, t.code, "T01", 5)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(OffsetSubmission.objects.count(), 0)

    def test_missing_ticket_blocked(self):
        with self.assertRaises(TicketError) as ctx:
            submit_with_ticket(self.m1, "NO-SUCH", "T01", 5)
        self.assertEqual(ctx.exception.status, 404)

    def test_enqueue_and_void_atomic_on_failure(self):
        """故障注入：券作废落库失败时，入队必须一起回滚，券仍可复用前状态（在用）。"""
        t = self.make_ticket(self.m1)
        with mock.patch.object(
            DailyTicket, "save", side_effect=RuntimeError("void save failed")
        ):
            with self.assertRaises(RuntimeError):
                submit_with_ticket(self.m1, t.code, "T01", 5)
        self.assertEqual(OffsetSubmission.objects.filter(ticket=t).count(), 0)
        t.refresh_from_db()
        self.assertEqual(t.state, DailyTicket.State.VALID)
        self.assertIsNone(t.voided_at)


class ConcurrencyTests(TicketTestBase):
    def test_two_operators_same_ticket_only_one_enqueued(self):
        rounds = 12
        outcomes = []
        for r in range(rounds):
            ticket = self.make_ticket(self.m1)
            barrier = threading.Barrier(2)
            box = {}

            def worker(key):
                barrier.wait()
                try:
                    submit_with_ticket(self.m1, ticket.code, f"T{r}", r)
                    box[key] = "ok"
                except TicketError as e:
                    box[key] = f"blocked:{e.status}"
                except IntegrityError:
                    box[key] = "integrity"
                finally:
                    connection.close()

            t1 = threading.Thread(target=worker, args=("a",))
            t2 = threading.Thread(target=worker, args=("b",))
            t1.start()
            t2.start()
            t1.join(timeout=15)
            t2.join(timeout=15)
            outcomes.append((box.get("a"), box.get("b")))

            # 该券恰好一笔入队，券已作废。
            self.assertEqual(
                OffsetSubmission.objects.filter(ticket=ticket).count(),
                1,
                msg=f"round {r} outcomes={box}",
            )
            ticket.refresh_from_db()
            self.assertEqual(ticket.state, DailyTicket.State.VOIDED)

        oks = sum(1 for a, b in outcomes if a == "ok") + sum(
            1 for a, b in outcomes if b == "ok"
        )
        blocked = sum(
            1
            for a, b in outcomes
            for v in (a, b)
            if isinstance(v, str) and (v.startswith("blocked") or v == "integrity")
        )
        # 每张券：恰好一个赢家、一个被挡回。
        self.assertEqual(oks, rounds)
        self.assertEqual(blocked, rounds)


class DistributeTests(TicketTestBase):
    def test_distribute_idempotent_five_per_day(self):
        first = distribute_daily_tickets(self.m1)
        second = distribute_daily_tickets(self.m1)
        self.assertEqual(len(first), 5)
        self.assertEqual(len(second), 5)
        self.assertEqual(
            DailyTicket.objects.filter(
                issued_to=self.m1, issue_date=timezone.localdate()
            ).count(),
            5,
        )

    def test_distribute_concurrent_double_click(self):
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            barrier.wait()
            try:
                distribute_daily_tickets(self.m1)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertEqual(errors, [])
        self.assertEqual(
            DailyTicket.objects.filter(
                issued_to=self.m1, issue_date=timezone.localdate()
            ).count(),
            5,
        )


class ApiPermissionTests(TicketTestBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.ticket = self.make_ticket(self.m1)

    def test_auditor_can_read_tickets_and_void_book(self):
        h = self.auth(self.auditor)
        self.assertEqual(self.client.get("/api/tickets/today", **h).status_code, 200)
        self.assertEqual(self.client.get("/api/tickets/voided", **h).status_code, 200)
        self.assertEqual(self.client.get("/api/submissions", **h).status_code, 200)

    def test_auditor_cannot_distribute(self):
        r = self.client.post("/api/tickets/distribute", **self.auth(self.auditor))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(DailyTicket.objects.count(), 1)  # 未发新券

    def test_auditor_cannot_submit(self):
        h = self.auth(self.auditor)
        r = self.client.post(
            "/api/submissions",
            data={"ticket_code": self.ticket.code, "tool_code": "T1", "offset_um": 5},
            content_type="application/json",
            **h,
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(OffsetSubmission.objects.count(), 0)

    def test_machinist_submit_ok_api_and_reuse_blocked(self):
        h = self.auth(self.m1)
        payload = {"ticket_code": self.ticket.code, "tool_code": "T1", "offset_um": 5}
        r1 = self.client.post(
            "/api/submissions", data=payload, content_type="application/json", **h
        )
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post(
            "/api/submissions", data=payload, content_type="application/json", **h
        )
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(OffsetSubmission.objects.count(), 1)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self.client.get("/api/tickets/today").status_code, 401)
        self.assertEqual(
            self.client.post("/api/tickets/distribute").status_code, 401
        )
