from datetime import time

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from market.models import MarketSchedule


class MarketScheduleTests(TestCase):
    def test_defaults_preserve_existing_market_schedule(self):
        schedule = MarketSchedule()
        schedule.full_clean()
        schedule.save()

        self.assertEqual(schedule.pk, 1)
        self.assertEqual(schedule.opening_time, time(9, 30))
        self.assertEqual(schedule.closing_time, time(16, 0))
        self.assertEqual(schedule.timezone_name, "America/New_York")
        self.assertTrue(all((
            schedule.monday,
            schedule.tuesday,
            schedule.wednesday,
            schedule.thursday,
            schedule.friday,
        )))

    def test_invalid_timezones_are_rejected(self):
        for name in ("Not/A_Timezone", "", "/etc/localtime", "../UTC"):
            with self.subTest(timezone_name=name):
                schedule = MarketSchedule(timezone_name=name)
                with self.assertRaises(ValidationError) as caught:
                    schedule.full_clean()
                self.assertIn(
                    "timezone_name", caught.exception.message_dict
                )

    def test_valid_alternative_timezone_is_accepted(self):
        schedule = MarketSchedule(timezone_name="America/Chicago")
        schedule.full_clean()

    def test_equal_or_overnight_hours_are_rejected(self):
        for closing in (time(9, 30), time(8, 0)):
            with self.subTest(closing_time=closing):
                schedule = MarketSchedule(
                    opening_time=time(9, 30),
                    closing_time=closing,
                )
                with self.assertRaises(ValidationError) as caught:
                    schedule.full_clean()
                self.assertIn(
                    "closing_time", caught.exception.message_dict
                )

    def test_at_least_one_weekday_is_required(self):
        schedule = MarketSchedule(
            monday=False,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
        )
        with self.assertRaises(ValidationError):
            schedule.full_clean()

        schedule.wednesday = True
        schedule.full_clean()

    def test_database_rejects_a_second_schedule_id(self):
        MarketSchedule.objects.create()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketSchedule.objects.create(id=2)

        self.assertEqual(MarketSchedule.objects.count(), 1)

    def test_database_rejects_invalid_hours_without_form_validation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketSchedule.objects.create(
                    opening_time=time(16, 0),
                    closing_time=time(9, 30),
                )

    def test_database_rejects_empty_weekdays_without_form_validation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketSchedule.objects.create(
                    monday=False,
                    tuesday=False,
                    wednesday=False,
                    thursday=False,
                    friday=False,
                )


class MarketScheduleAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="schedule_admin",
            email="schedule@example.com",
            password="schedule-test-only",
        )
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.superuser
        self.model_admin = admin.site._registry[MarketSchedule]

    def test_add_is_allowed_only_before_schedule_exists(self):
        self.assertTrue(
            self.model_admin.has_add_permission(self.request)
        )

        MarketSchedule.objects.create()

        self.assertFalse(
            self.model_admin.has_add_permission(self.request)
        )

    def test_schedule_deletion_is_disabled(self):
        schedule = MarketSchedule.objects.create()

        self.assertFalse(
            self.model_admin.has_delete_permission(
                self.request, schedule
            )
        )

    def test_admin_form_rejects_invalid_configuration(self):
        form_class = self.model_admin.get_form(self.request)
        form = form_class(data={
            "timezone_name": "Invalid/Timezone",
            "opening_time": "16:00:00",
            "closing_time": "09:30:00",
            "monday": True,
        })

        self.assertFalse(form.is_valid())
        self.assertIn("timezone_name", form.errors)
        self.assertIn("closing_time", form.errors)

    def test_staff_without_permission_cannot_add_schedule(self):
        User = get_user_model()
        self.request.user = User.objects.create_user(
            username="schedule_staff",
            is_staff=True,
        )

        self.assertFalse(
            self.model_admin.has_add_permission(self.request)
        )