from django.test import SimpleTestCase
from django.urls import reverse


class AuthenticationPageTests(SimpleTestCase):
    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")
        self.assertContains(response, "Log In")