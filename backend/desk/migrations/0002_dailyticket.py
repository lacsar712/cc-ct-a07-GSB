import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("desk", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyTicket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(db_index=True, max_length=40, unique=True)),
                ("ticket_date", models.DateField(db_index=True)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("valid", "在用"),
                            ("redeemed", "已用"),
                            ("voided", "已作废"),
                        ],
                        db_index=True,
                        default="valid",
                        max_length=16,
                    ),
                ),
                ("redeemed_at", models.DateTimeField(blank=True, null=True)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "void_reason",
                    models.CharField(blank=True, default="", max_length=200),
                ),
                (
                    "issued_to",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "redeemed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="redeemed_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "voided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="voided_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-ticket_date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="TicketVoidRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(db_index=True, max_length=40)),
                ("ticket_date", models.DateField(db_index=True)),
                ("reason", models.CharField(blank=True, default="", max_length=200)),
                ("voided_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="void_records",
                        to="desk.dailyticket",
                    ),
                ),
                (
                    "voided_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ticket_void_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-voided_at", "-id"],
            },
        ),
        migrations.AddField(
            model_name="offsetsubmission",
            name="ticket",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="submission",
                to="desk.dailyticket",
            ),
        ),
        migrations.AddConstraint(
            model_name="dailyticket",
            constraint=models.UniqueConstraint(
                fields=("issued_to", "ticket_date"),
                name="uniq_ticket_per_user_per_day",
            ),
        ),
    ]
