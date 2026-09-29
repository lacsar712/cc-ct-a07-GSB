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
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=40, unique=True)),
                ("issue_date", models.DateField(db_index=True)),
                (
                    "state",
                    models.CharField(
                        choices=[("valid", "在用"), ("voided", "已作废")],
                        db_index=True,
                        default="valid",
                        max_length=16,
                    ),
                ),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "issued_to",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-issue_date", "code"],
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
        migrations.AddIndex(
            model_name="dailyticket",
            index=models.Index(fields=["issued_to", "issue_date", "state"], name="desk_dailyt_issued_state_idx"),
        ),
    ]
