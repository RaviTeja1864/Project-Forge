from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class AuthenticationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registration_creates_and_authenticates_user(self):
        response = self.client.post(
            "/api/auth/register/",
            {"email": "Engineer@Example.com", "password": "a-long-test-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "engineer@example.com")
        self.assertNotIn("password", response.data)
        self.assertTrue(User.objects.get(email="engineer@example.com").check_password("a-long-test-password"))
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_registration_rejects_invalid_email_and_weak_password(self):
        invalid_email = self.client.post(
            "/api/auth/register/",
            {"email": "not-an-email", "password": "a-long-test-password"},
            format="json",
        )
        weak_password = self.client.post(
            "/api/auth/register/",
            {"email": "engineer@example.com", "password": "123"},
            format="json",
        )
        self.assertEqual(invalid_email.status_code, 400)
        self.assertIn("email", invalid_email.data)
        self.assertEqual(weak_password.status_code, 400)
        self.assertIn("password", weak_password.data)

    def test_registration_normalizes_and_rejects_duplicate_email(self):
        payload = {"email": "Engineer@Example.com", "password": "a-long-test-password"}
        self.assertEqual(self.client.post("/api/auth/register/", payload, format="json").status_code, 201)
        duplicate = self.client.post(
            "/api/auth/register/",
            {"email": "ENGINEER@example.com", "password": "another-long-password"},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_login_failure_is_generic_and_success_establishes_session(self):
        User.objects.create_user(email="user@example.com", password="a-long-test-password")
        invalid = self.client.post(
            "/api/auth/login/",
            {"email": "missing@example.com", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.data["non_field_errors"], ["Invalid email or password."])

        valid = self.client.post(
            "/api/auth/login/",
            {"email": "USER@example.com", "password": "a-long-test-password"},
            format="json",
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.data["email"], "user@example.com")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_current_user_requires_authentication(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)

    def test_logout_clears_session(self):
        User.objects.create_user(email="user@example.com", password="a-long-test-password")
        self.assertTrue(self.client.login(email="user@example.com", password="a-long-test-password"))
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)
