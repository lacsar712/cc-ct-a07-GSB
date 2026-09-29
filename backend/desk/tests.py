from datetime import timedelta

from django.utils import timezone
from ninja.testing import TestClient

from desk.api import api
from desk.auth_utils import create_access_token
from desk.models import DailyTicket, TicketVoidRecord, User
from desk.services import (
    TicketError,
    issue_daily_ticket,
    redeem_ticket,
    void_ticket,
)
from django.test import TestCase


class DailyTicketServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="m1", password="x", role=User.Role.MACHINIST
        )
        self.other = User.objects.create_user(
            username="m2", password="x", role=User.Role.MACHINIST
        )

    def test_issue_once_per_natural_day_is_idempotent(self):
        t1 = issue_daily_ticket(self.user)
        t2 = issue_daily_ticket(self.user)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(DailyTicket.objects.filter(issued_to=self.user).count(), 1)

    def test_redeem_creates_pending_and_consumes_ticket_in_one_go(self):
        ticket = issue_daily_ticket(self.user)
        submission = redeem_ticket(
            ticket_id=ticket.id, user=self.user, tool_code="T05", offset_um=3
        )
        self.assertEqual(submission.status, "pending")
        self.assertEqual(submission.ticket_id, ticket.id)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, DailyTicket.Status.REDEEMED)
        self.assertIsNotNone(ticket.redeemed_at)

    def test_same_ticket_cannot_redeem_twice(self):
        ticket = issue_daily_ticket(self.user)
        redeem_ticket(ticket_id=ticket.id, user=self.user, tool_code="T05", offset_um=3)
        with self.assertRaises(TicketError):
            redeem_ticket(
                ticket_id=ticket.id, user=self.user, tool_code="T06", offset_um=4
            )

    def test_other_user_cannot_redeem_ticket(self):
        ticket = issue_daily_ticket(self.user)
        with self.assertRaises(TicketError):
            redeem_ticket(
                ticket_id=ticket.id, user=self.other, tool_code="T05", offset_um=3
            )

    def test_voided_ticket_redeem_is_blocked(self):
        ticket = issue_daily_ticket(self.user)
        void_ticket(ticket_id=ticket.id, user=self.user, reason="打错")
        with self.assertRaises(TicketError):
            redeem_ticket(
                ticket_id=ticket.id, user=self.user, tool_code="T05", offset_um=3
            )
        self.assertEqual(TicketVoidRecord.objects.count(), 1)

    def test_old_ticket_redeem_is_blocked(self):
        ticket = issue_daily_ticket(self.user)
        DailyTicket.objects.filter(pk=ticket.pk).update(
            ticket_date=timezone.localdate() - timedelta(days=1)
        )
        with self.assertRaises(TicketError):
            redeem_ticket(
                ticket_id=ticket.id, user=self.user, tool_code="T05", offset_um=3
            )

    def test_redeemed_ticket_cannot_be_voided(self):
        ticket = issue_daily_ticket(self.user)
        redeem_ticket(ticket_id=ticket.id, user=self.user, tool_code="T05", offset_um=3)
        with self.assertRaises(TicketError):
            void_ticket(ticket_id=ticket.id, user=self.user)

    def test_void_is_idempotent_guard_no_duplicate_ledger(self):
        ticket = issue_daily_ticket(self.user)
        void_ticket(ticket_id=ticket.id, user=self.user)
        with self.assertRaises(TicketError):
            void_ticket(ticket_id=ticket.id, user=self.user)
        self.assertEqual(TicketVoidRecord.objects.count(), 1)


class AuditorReadOnlyTests(TestCase):
    def setUp(self):
        self.client = TestClient(api)
        self.auditor = User.objects.create_user(
            username="a1", password="x", role=User.Role.AUDITOR
        )
        self.token = create_access_token(self.auditor)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_auditor_can_read_tickets_and_void_book(self):
        self.assertEqual(self.client.get("/tickets", headers=self.headers).status_code, 200)
        self.assertEqual(
            self.client.get("/tickets/voided", headers=self.headers).status_code, 200
        )

    def test_auditor_cannot_issue_or_void(self):
        self.assertEqual(
            self.client.post("/tickets/issue", headers=self.headers).status_code, 403
        )
        machinist = User.objects.create_user(
            username="m9", password="x", role=User.Role.MACHINIST
        )
        ticket = issue_daily_ticket(machinist)
        resp = self.client.post(
            f"/tickets/{ticket.id}/void",
            json={"reason": ""},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, DailyTicket.Status.VALID)
