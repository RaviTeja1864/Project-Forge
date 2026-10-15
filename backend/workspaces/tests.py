import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from backend.workspaces.models import ProjectWorkspace
from backend.workspaces.services.ollama import OllamaOfflineError

User = get_user_model()


class WorkspaceApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="long-password-1")
        self.other = User.objects.create_user(email="other@example.com", password="long-password-2")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def test_create_and_list_only_the_authenticated_users_workspaces(self):
        response = self.client.post(
            "/api/workspaces/",
            {"name": "  Safer streets  ", "description": "  Explore the issue. ", "owner": self.other.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Safer streets")
        self.assertEqual(response.data["description"], "Explore the issue.")
        self.assertEqual(ProjectWorkspace.objects.get().owner, self.owner)
        ProjectWorkspace.objects.create(owner=self.other, name="Private project")
        listing = self.client.get("/api/workspaces/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(listing.data["results"][0]["name"], "Safer streets")

    def test_create_validates_name_and_status(self):
        empty_name = self.client.post("/api/workspaces/", {"name": "   "}, format="json")
        invalid_status = self.client.post(
            "/api/workspaces/",
            {"name": "A project", "status": "invented"},
            format="json",
        )
        self.assertEqual(empty_name.status_code, 400)
        self.assertIn("name", empty_name.data)
        self.assertEqual(invalid_status.status_code, 400)
        self.assertIn("status", invalid_status.data)

    def test_create_enforces_documented_field_lengths(self):
        long_name = self.client.post(
            "/api/workspaces/",
            {"name": "x" * 121},
            format="json",
        )
        long_description = self.client.post(
            "/api/workspaces/",
            {"name": "A project", "description": "x" * 2001},
            format="json",
        )
        self.assertEqual(long_name.status_code, 400)
        self.assertIn("name", long_name.data)
        self.assertEqual(long_description.status_code, 400)
        self.assertIn("description", long_description.data)

    def test_malformed_json_returns_a_validation_error(self):
        response = self.client.generic(
            "POST",
            "/api/workspaces/",
            data=b'{"name":',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.data)

    def test_owner_can_view_update_and_delete(self):
        workspace = ProjectWorkspace.objects.create(owner=self.owner, name="Climate tools")
        detail = f"/api/workspaces/{workspace.pk}/"
        self.assertEqual(self.client.get(detail).status_code, 200)
        updated = self.client.patch(
            detail,
            {"name": "Community heat map", "owner": self.other.pk},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        workspace.refresh_from_db()
        self.assertEqual(workspace.name, "Community heat map")
        self.assertEqual(workspace.owner, self.owner)
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertFalse(ProjectWorkspace.objects.filter(pk=workspace.pk).exists())

    def test_another_user_cannot_view_update_or_delete_workspace(self):
        workspace = ProjectWorkspace.objects.create(owner=self.owner, name="Private")
        self.client.force_authenticate(user=self.other)
        detail = f"/api/workspaces/{workspace.pk}/"
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.patch(detail, {"name": "Stolen"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        workspace.refresh_from_db()
        self.assertEqual(workspace.name, "Private")

    def test_anonymous_user_cannot_list_or_create(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get("/api/workspaces/").status_code, (401, 403))
        self.assertIn(
            self.client.post("/api/workspaces/", {"name": "No user"}, format="json").status_code,
            (401, 403),
        )

    def test_invalid_uuid_returns_not_found(self):
        self.assertEqual(self.client.get("/api/workspaces/not-a-uuid/").status_code, 404)

    def test_database_rejects_empty_name(self):
        for name in ("", "   "):
            with self.subTest(name=repr(name)), self.assertRaises(IntegrityError), transaction.atomic():
                ProjectWorkspace.objects.create(owner=self.owner, name=name)

    def test_database_rejects_unknown_status(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectWorkspace.objects.create(owner=self.owner, name="Invalid state", status="unknown")

    def test_session_authenticated_mutations_require_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(email="owner@example.com", password="long-password-1"))
        workspace = ProjectWorkspace.objects.create(owner=self.owner, name="CSRF test")
        detail = f"/api/workspaces/{workspace.pk}/"

        rejected = client.patch(detail, {"name": "Without token"}, format="json")
        self.assertEqual(rejected.status_code, 403)

        csrf_response = client.get("/api/auth/csrf/")
        self.assertEqual(csrf_response.status_code, 200)
        accepted = client.patch(
            detail,
            {"name": "With token"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_response.data["csrfToken"],
        )
        self.assertEqual(accepted.status_code, 200)

    def test_uuid_primary_key_and_pagination(self):
        workspace = ProjectWorkspace.objects.create(owner=self.owner, name="UUID check")
        self.assertIsInstance(workspace.pk, uuid.UUID)
        for index in range(13):
            ProjectWorkspace.objects.create(owner=self.owner, name=f"Workspace {index}")
        response = self.client.get("/api/workspaces/")
        self.assertEqual(response.data["count"], 14)
        self.assertEqual(len(response.data["results"]), 12)
        self.assertIsNotNone(response.data["next"])

    @patch("backend.workspaces.views.model_status")
    def test_ollama_status_requires_authentication_and_hides_errors(self, model_status):
        model_status.return_value = {
            "available": False,
            "model": "qwen3:4b",
            "state": "model_missing",
        }
        response = self.client.get("/api/workspaces/llm/status/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["available"])

        model_status.side_effect = OllamaOfflineError("private endpoint detail")
        unavailable = self.client.get("/api/workspaces/llm/status/")
        self.assertEqual(unavailable.status_code, 200)
        self.assertEqual(unavailable.data["state"], "offline")
        self.assertNotIn("private endpoint detail", str(unavailable.data))

        self.client.force_authenticate(user=None)
        unauthorized = self.client.get("/api/workspaces/llm/status/")
        self.assertIn(unauthorized.status_code, (401, 403))


class HealthApiTests(TestCase):
    def test_health_reports_application_and_database_readiness(self):
        response = APIClient().get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"status": "ok", "checks": {"application": "ok", "database": "ready"}},
        )

    @patch("backend.config.urls.connections")
    def test_health_reports_unavailable_database_without_exposing_details(self, connections):
        connections.__getitem__.return_value.ensure_connection.side_effect = OperationalError(
            "internal connection details"
        )
        response = APIClient().get("/api/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"status": "not_ready", "checks": {"application": "ok", "database": "unavailable"}},
        )
        self.assertNotIn("internal connection details", str(response.data))
