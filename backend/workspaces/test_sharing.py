from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from backend.workspaces.models import (
    ProjectWorkspace,
    WorkspaceArtifact,
    WorkspaceCollaborator,
)

User = get_user_model()


class WorkspaceSharingApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="sharing-owner@example.com", password="safe-test-password"
        )
        self.collaborator = User.objects.create_user(
            email="sharing-reader@example.com", password="safe-test-password"
        )
        self.other = User.objects.create_user(
            email="sharing-other@example.com", password="safe-test-password"
        )
        self.workspace = ProjectWorkspace.objects.create(
            owner=self.owner,
            name="Shared project",
            description="A private project.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def grant_url(self):
        return f"/api/workspaces/{self.workspace.pk}/collaborators/"

    def artifact_url(self, artifact):
        return f"/api/workspaces/{self.workspace.pk}/artifacts/{artifact.pk}/"

    def make_artifact(self, *, status, kind=WorkspaceArtifact.Kind.RESEARCH, **kwargs):
        content = kwargs.pop("content", {"problem_summary": "Source-backed summary."})
        return WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=kind,
            status=status,
            content=content,
            source_snapshot=[],
            **kwargs,
        )

    def grant(self):
        return WorkspaceCollaborator.objects.create(
            workspace=self.workspace,
            user=self.collaborator,
            granted_by=self.owner,
            granted_at=self.workspace.created_at,
        )

    def test_workspace_is_private_until_an_owner_grants_access(self):
        self.client.force_authenticate(user=self.collaborator)
        self.assertEqual(
            self.client.get(f"/api/workspaces/{self.workspace.pk}/").status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/workspaces/").data["count"], 0)

    def test_owner_can_grant_revoke_and_regrant_existing_account(self):
        granted = self.client.post(
            self.grant_url(),
            {"email": self.collaborator.email},
            format="json",
        )
        self.assertEqual(granted.status_code, 201, granted.data)
        self.assertEqual(granted.data["access_status"], "active")
        duplicate = self.client.post(
            self.grant_url(),
            {"email": self.collaborator.email},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(WorkspaceCollaborator.objects.count(), 1)
        self.assertEqual(len(self.client.get(self.grant_url()).data), 1)

        self.assertEqual(
            self.client.delete(
                f"{self.grant_url()}{granted.data['id']}/"
            ).status_code,
            204,
        )
        grant = WorkspaceCollaborator.objects.get()
        self.assertIsNotNone(grant.revoked_at)
        self.client.force_authenticate(user=self.collaborator)
        self.assertEqual(self.client.get(f"/api/workspaces/{self.workspace.pk}/").status_code, 404)

        self.client.force_authenticate(user=self.owner)
        regranted = self.client.post(
            self.grant_url(), {"email": self.collaborator.email}, format="json"
        )
        self.assertEqual(regranted.status_code, 201)
        self.assertEqual(WorkspaceCollaborator.objects.count(), 2)
        self.assertEqual(
            WorkspaceCollaborator.objects.filter(revoked_at__isnull=True).count(),
            1,
        )

    def test_database_prevents_duplicate_active_grants(self):
        self.grant()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.grant()

    def test_invalid_or_unavailable_grant_targets_are_rejected(self):
        self_share = self.client.post(self.grant_url(), {"email": self.owner.email}, format="json")
        unknown = self.client.post(
            self.grant_url(), {"email": "unavailable@example.com"}, format="json"
        )
        malformed = self.client.post(self.grant_url(), {"email": "not-an-email"}, format="json")
        self.assertEqual(self_share.status_code, 400)
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(WorkspaceCollaborator.objects.count(), 0)
        inactive = User.objects.create_user(
            email="inactive-reader@example.com",
            password="safe-test-password",
            is_active=False,
        )
        inactive_response = self.client.post(
            self.grant_url(), {"email": inactive.email}, format="json"
        )
        self.assertEqual(inactive_response.status_code, 400)

    def test_collaborator_reads_workspace_and_approved_artifacts_only(self):
        approved = self.make_artifact(status=WorkspaceArtifact.Status.APPROVED)
        draft = self.make_artifact(status=WorkspaceArtifact.Status.DRAFT)
        self.grant()
        self.client.force_authenticate(user=self.collaborator)

        detail = self.client.get(f"/api/workspaces/{self.workspace.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["access_role"], "collaborator")
        listed = self.client.get(f"/api/workspaces/{self.workspace.pk}/artifacts/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.data], [str(approved.pk)])
        self.assertEqual(self.client.get(self.artifact_url(approved)).status_code, 200)
        self.assertEqual(self.client.get(self.artifact_url(draft)).status_code, 404)

    def test_collaborator_can_view_approved_specification_and_export_only(self):
        content = {
            "project": {"title": "Approved spec"},
            "input_artifacts": [],
            "generated_at": "2026-01-01T00:00:00Z",
        }
        approved = self.make_artifact(
            status=WorkspaceArtifact.Status.APPROVED,
            kind=WorkspaceArtifact.Kind.SPECIFICATION,
            content=content,
        )
        draft = self.make_artifact(
            status=WorkspaceArtifact.Status.DRAFT,
            kind=WorkspaceArtifact.Kind.SPECIFICATION,
            content=content,
        )
        self.grant()
        self.client.force_authenticate(user=self.collaborator)
        specs_url = f"/api/workspaces/{self.workspace.pk}/specifications/"
        self.assertEqual(
            [item["id"] for item in self.client.get(specs_url).data],
            [str(approved.pk)],
        )
        for export_format in ("md", "pdf"):
            response = self.client.get(
                f"{specs_url}{approved.pk}/export.{export_format}"
            )
            self.assertEqual(response.status_code, 200, export_format)
            self.assertEqual(
                response["Content-Type"].split(";")[0],
                "text/markdown" if export_format == "md" else "application/pdf",
            )
            self.assertEqual(
                self.client.get(
                    f"{specs_url}{draft.pk}/export.{export_format}"
                ).status_code,
                404,
            )
        self.assertEqual(self.client.get(f"{specs_url}{draft.pk}/").status_code, 404)
        self.client.force_authenticate(user=self.other)
        for export_format in ("md", "pdf"):
            self.assertEqual(
                self.client.get(
                    f"{specs_url}{approved.pk}/export.{export_format}"
                ).status_code,
                404,
            )

    def test_collaborator_cannot_mutate_generate_approve_revise_or_share(self):
        draft = self.make_artifact(status=WorkspaceArtifact.Status.DRAFT)
        self.grant()
        self.client.force_authenticate(user=self.collaborator)
        urls_and_requests = [
            (f"/api/workspaces/{self.workspace.pk}/", "patch", {"name": "Changed"}),
            (f"/api/workspaces/{self.workspace.pk}/", "delete", None),
            (self.artifact_url(draft), "patch", {"status": "approved"}),
            (self.artifact_url(draft), "delete", None),
            (
                f"/api/workspaces/{self.workspace.pk}/artifacts/{draft.pk}/revise/",
                "post",
                {},
            ),
            (f"/api/workspaces/{self.workspace.pk}/generate/requirements/", "post", {}),
            (self.grant_url(), "post", {"email": self.other.email}),
            (self.grant_url(), "get", None),
        ]
        for url, method, body in urls_and_requests:
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(
                    url, body, format="json"
                ) if body is not None else getattr(self.client, method)(url)
                self.assertIn(response.status_code, (403, 404))

    def test_collaborator_history_excludes_unapproved_versions_and_other_workspace_ids(self):
        approved = self.make_artifact(status=WorkspaceArtifact.Status.APPROVED)
        draft = self.make_artifact(
            status=WorkspaceArtifact.Status.DRAFT,
            version_number=2,
            lineage_root=approved,
            revision_of=approved,
        )
        unrelated_workspace = ProjectWorkspace.objects.create(
            owner=self.other, name="Unrelated"
        )
        unrelated = WorkspaceArtifact.objects.create(
            workspace=unrelated_workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            content={"problem_summary": "Private."},
        )
        self.grant()
        self.client.force_authenticate(user=self.collaborator)
        history = self.client.get(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{approved.pk}/versions/"
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["id"] for item in history.data], [str(approved.pk)])
        self.assertEqual(
            self.client.get(
                f"/api/workspaces/{self.workspace.pk}/artifacts/{approved.pk}/versions/{draft.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get(self.artifact_url(unrelated)).status_code, 404)

    def test_non_owner_cannot_manage_grants_and_owner_access_is_unchanged(self):
        self.grant()
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(self.grant_url()).status_code, 404)
        self.assertEqual(
            self.client.delete(f"{self.grant_url()}1/").status_code, 404
        )
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            f"/api/workspaces/{self.workspace.pk}/",
            {"name": "Owner updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["access_role"], "owner")
