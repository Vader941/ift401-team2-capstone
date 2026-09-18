from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class DashboardTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("trading:dashboard"))

        expected_url = f"{reverse('login')}?next={reverse('trading:dashboard')}"
        self.assertRedirects(response, expected_url)

    def test_authenticated_user_can_view_dashboard(self):
        user = get_user_model().objects.create_user(
            username="testuser",
            password="temporary-test-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("trading:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "trading/dashboard.html")
        self.assertContains(response, "Welcome, testuser.")