from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from backend.workspaces.models import (
    ImplementationTask,
    ProjectWorkspace,
    WorkspaceArtifact,
    WorkspaceCollaborator,
)

User = get_user_model()


def requirements_content():
    return {
        "functional_requirements": [
            {"id": "FR-001", "statement": "Display source links."},
        ],
        "non_functional_requirements": [
            {"id": "NFR-001", "statement": "Protect private data."},
        ],
        "acceptance_criteria": [
            {
                "id": "AC-001",
                "criterion": "A source link opens from the problem view.",
                "requirement_ids": ["FR-001"],
            },
            {
                "id": "AC-002",
                "criterion": "A second source link opens from the detail view.",
                "requirement_ids": ["FR-001"],
            },
            {
                "id": "AC-003",
                "criterion": "Workspace details are unavailable to unrelated accounts.",
                "requirement_ids": ["NFR-001"],
            },
        ],
    }


class ImplementationPlanningVerificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="implementation-owner@example.com", password="safe-test-password"
        )
        self.collaborator = User.objects.create_user(
            email="implementation-reader@example.com", password="safe-test-password"
        )
        self.other = User.objects.create_user(
            email="implementation-other@example.com", password="safe-test-password"
        )
        self.workspace = ProjectWorkspace.objects.create(
            owner=self.owner,
            name="Implementation project",
        )
        self.requirements = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            status=WorkspaceArtifact.Status.APPROVED,
            content=requirements_content(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def task_plan_url(self):
        return f"/api/workspaces/{self.workspace.pk}/implementation/tasks/generate/"

    def tasks_url(self):
        return f"/api/workspaces/{self.workspace.pk}/implementation/tasks/"

    def requirements_url(self, requirement_id):
        return (
            f"/api/workspaces/{self.workspace.pk}/requirements/"
            f"{self.requirements.pk}/{requirement_id}/"
        )

    def generate_plan(self):
        response = self.client.post(
            self.task_plan_url(),
            {"requirements_artifact_id": str(self.requirements.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def add_evidence(
        self,
        requirement_id,
        *,
        criterion_id="",
        task_id=None,
        result="passed",
        review_basis="manually_reviewed",
        evidence_type="verification_check",
        supersedes_id=None,
    ):
        payload = {
            "requirement_id": requirement_id,
            "acceptance_criterion_id": criterion_id,
            "task_id": task_id,
            "evidence_type": evidence_type,
            "description": "Reviewer recorded a check result.",
            "source_reference": "tests/test_project.py::test_source_link",
            "result": result,
            "review_basis": review_basis,
        }
        if supersedes_id is not None:
            payload["supersedes_id"] = supersedes_id
        response = self.client.post(
            f"{self.requirements_url(requirement_id)}evidence/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def verify(self, requirement_id):
        return self.client.post(
            f"{self.requirements_url(requirement_id)}verification/",
            {},
            format="json",
        )

    def test_plan_maps_each_requirement_and_acceptance_criteria_idempotently(self):
        first = self.generate_plan()
        self.assertEqual(first.data["created_count"], 2)
        self.assertEqual(first.data["existing_count"], 0)
        self.assertEqual(first.data["unmapped_requirements"], [])
        by_requirement = {
            task["source_requirement_id"]: task for task in first.data["tasks"]
        }
        self.assertEqual(by_requirement["FR-001"]["acceptance_criteria_ids"], ["AC-001", "AC-002"])
        self.assertEqual(by_requirement["NFR-001"]["acceptance_criteria_ids"], ["AC-003"])
        self.assertEqual(by_requirement["FR-001"]["source_requirements_version"], 1)

        repeat = self.generate_plan()
        self.assertEqual(repeat.data["created_count"], 0)
        self.assertEqual(repeat.data["existing_count"], 2)
        self.assertEqual(ImplementationTask.objects.count(), 2)

    def test_plan_reports_unmappable_requirement_instead_of_silently_omitting(self):
        content = requirements_content()
        content["functional_requirements"].append({"id": "", "statement": ""})
        self.requirements.content = content
        self.requirements.save(update_fields=("content",))
        result = self.generate_plan()
        self.assertEqual(result.data["created_count"], 2)
        self.assertEqual(len(result.data["unmapped_requirements"]), 1)

    def test_task_edit_status_dependencies_and_cycle_validation(self):
        tasks = self.generate_plan().data["tasks"]
        first, second = tasks
        first_url = f"{self.tasks_url()}{first['id']}/"
        second_url = f"{self.tasks_url()}{second['id']}/"
        edit = self.client.patch(
            first_url,
            {
                "title": "Implement verified source display",
                "status": "in_progress",
                "priority": "high",
            },
            format="json",
        )
        self.assertEqual(edit.status_code, 200, edit.data)
        self.assertEqual(edit.data["status"], "in_progress")
        self.assertEqual(edit.data["priority"], "high")
        provenance_edit = self.client.patch(
            first_url,
            {"source_requirement_id": "NFR-001"},
            format="json",
        )
        self.assertEqual(provenance_edit.status_code, 400)
        self.assertEqual(
            self.client.patch(
                first_url,
                {"dependencies": [first["id"]]},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                first_url,
                {"dependencies": [second["id"]]},
                format="json",
            ).status_code,
            200,
        )
        cycle = self.client.patch(
            second_url,
            {"dependencies": [first["id"]]},
            format="json",
        )
        self.assertEqual(cycle.status_code, 400)
        self.assertIn("cycle", str(cycle.data).lower())
        complete = self.client.patch(
            first_url, {"status": "completed"}, format="json"
        )
        self.assertEqual(complete.status_code, 200)
        invalid_transition = self.client.patch(
            first_url, {"status": "blocked"}, format="json"
        )
        self.assertEqual(invalid_transition.status_code, 400)

    def test_manual_task_creation_requires_approved_same_workspace_requirement(self):
        payload = {
            "source_requirements_artifact_id": str(self.requirements.pk),
            "source_requirement_id": "FR-001",
            "title": "Implement source display",
            "description": "Display source details.",
        }
        response = self.client.post(self.tasks_url(), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["acceptance_criteria_ids"], ["AC-001", "AC-002"])

        other_workspace = ProjectWorkspace.objects.create(
            owner=self.other, name="Other workspace"
        )
        other_artifact = WorkspaceArtifact.objects.create(
            workspace=other_workspace,
            kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            status=WorkspaceArtifact.Status.APPROVED,
            content=requirements_content(),
        )
        payload["source_requirements_artifact_id"] = str(other_artifact.pk)
        denied = self.client.post(self.tasks_url(), payload, format="json")
        self.assertEqual(denied.status_code, 400)
        external_task = ImplementationTask.objects.create(
            workspace=other_workspace,
            source_requirements=other_artifact,
            source_requirement_id="NFR-001",
            title="External dependency",
            description="Not in the current workspace.",
        )
        local_task = ImplementationTask.objects.get(workspace=self.workspace)
        cross_workspace_dependency = self.client.patch(
            f"{self.tasks_url()}{local_task.pk}/",
            {"dependencies": [external_task.pk]},
            format="json",
        )
        self.assertEqual(cross_workspace_dependency.status_code, 400)

    def test_plan_rejects_draft_requirements_version(self):
        draft = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            status=WorkspaceArtifact.Status.DRAFT,
            content=requirements_content(),
        )
        response = self.client.post(
            self.task_plan_url(),
            {"requirements_artifact_id": str(draft.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_evidence_recording_is_provenance_scoped_append_only_and_correctable(self):
        tasks = self.generate_plan().data["tasks"]
        task = next(item for item in tasks if item["source_requirement_id"] == "FR-001")
        recorded = self.add_evidence(
            "FR-001",
            criterion_id="AC-001",
            task_id=task["id"],
            review_basis="self_reported",
            evidence_type="test_result",
        )
        self.assertEqual(recorded["trust_label"], "self-reported claim")
        corrected = self.add_evidence(
            "FR-001",
            criterion_id="AC-001",
            task_id=task["id"],
            result="inconclusive",
            supersedes_id=recorded["id"],
        )
        self.assertEqual(corrected["supersedes_id"], recorded["id"])
        listing = self.client.get(
            f"{self.requirements_url('FR-001')}evidence/"
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 2)
        duplicate_correction = self.client.post(
            f"{self.requirements_url('FR-001')}evidence/",
            {
                "requirement_id": "FR-001",
                "acceptance_criterion_id": "AC-001",
                "task_id": task["id"],
                "evidence_type": "test_result",
                "description": "Duplicate correction claim.",
                "result": "passed",
                "review_basis": "self_reported",
                "supersedes_id": recorded["id"],
            },
            format="json",
        )
        self.assertEqual(duplicate_correction.status_code, 400)
        reference_is_only_recorded = self.client.post(
            f"{self.requirements_url('NFR-001')}evidence/",
            {
                "requirement_id": "NFR-001",
                "acceptance_criterion_id": "AC-003",
                "evidence_type": "repository_path",
                "description": "Claimed path",
                "source_reference": "../../secrets",
                "result": "passed",
                "review_basis": "self_reported",
            },
            format="json",
        )
        self.assertEqual(reference_is_only_recorded.status_code, 201)
        self.assertEqual(reference_is_only_recorded.data["source_reference"], "../../secrets")
        self.assertEqual(
            reference_is_only_recorded.data["trust_label"],
            "self-reported claim",
        )

    def test_verifier_produces_all_four_states_and_preserves_decision_history(self):
        task = self.generate_plan().data["tasks"][0]
        self.client.patch(
            f"{self.tasks_url()}{task['id']}/",
            {"status": "completed"},
            format="json",
        )
        no_evidence = self.verify("FR-001")
        self.assertEqual(no_evidence.status_code, 201)
        self.assertEqual(no_evidence.data["status"], "unverified")

        self.add_evidence("FR-001", criterion_id="AC-001")
        partial = self.verify("FR-001")
        self.assertEqual(partial.data["status"], "partially_implemented")

        self.add_evidence("FR-001", criterion_id="AC-002")
        verified = self.verify("FR-001")
        self.assertEqual(verified.data["status"], "verified")
        self.assertIn("No automated command", verified.data["rationale"])

        missing = self.add_evidence(
            "NFR-001",
            criterion_id="AC-003",
            result="absent",
        )
        self.assertIsNotNone(missing["id"])
        missing_status = self.verify("NFR-001")
        self.assertEqual(missing_status.data["status"], "missing")

        self.add_evidence(
            "NFR-001",
            criterion_id="AC-003",
            result="passed",
            supersedes_id=missing["id"],
        )
        current = self.client.get(
            f"{self.requirements_url('NFR-001')}verification/"
        )
        self.assertEqual(current.data["status"], "unverified")
        self.assertTrue(current.data["is_outdated"])
        history = self.client.get(
            f"{self.requirements_url('NFR-001')}verification/history/"
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data), 1)
        self.assertEqual(history.data[0]["recorded_status"], "missing")

    def test_self_reported_passes_never_become_verified(self):
        self.add_evidence(
            "FR-001",
            criterion_id="AC-001",
            review_basis="self_reported",
        )
        self.add_evidence(
            "FR-001",
            criterion_id="AC-002",
            review_basis="self_reported",
        )
        response = self.verify("FR-001")
        self.assertEqual(response.data["status"], "unverified")

    def test_requirement_revisions_make_tasks_and_verifications_stale(self):
        task = self.generate_plan().data["tasks"][0]
        self.add_evidence("FR-001", criterion_id="AC-001")
        self.add_evidence("FR-001", criterion_id="AC-002")
        prior = self.verify("FR-001")
        self.assertEqual(prior.data["status"], "verified")
        newer = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            status=WorkspaceArtifact.Status.DRAFT,
            content=requirements_content(),
        )
        self.assertEqual(newer.version_number, 1)
        task_detail = self.client.get(f"{self.tasks_url()}{task['id']}/")
        self.assertTrue(task_detail.data["is_outdated"])
        current = self.client.get(
            f"{self.requirements_url('FR-001')}verification/"
        )
        self.assertEqual(current.data["status"], "unverified")
        self.assertTrue(current.data["is_outdated"])

    def test_collaborators_can_read_tasks_and_evidence_but_cannot_modify_or_verify(self):
        tasks = self.generate_plan().data["tasks"]
        self.add_evidence("FR-001", criterion_id="AC-001")
        WorkspaceCollaborator.objects.create(
            workspace=self.workspace,
            user=self.collaborator,
            granted_by=self.owner,
            granted_at=self.workspace.created_at,
        )
        self.client.force_authenticate(user=self.collaborator)
        self.assertEqual(self.client.get(self.tasks_url()).status_code, 200)
        task_url = f"{self.tasks_url()}{tasks[0]['id']}/"
        self.assertEqual(self.client.get(task_url).status_code, 200)
        self.assertEqual(
            self.client.patch(task_url, {"title": "Unauthorized"}, format="json").status_code,
            404,
        )
        evidence_url = f"{self.requirements_url('FR-001')}evidence/"
        self.assertEqual(self.client.get(evidence_url).status_code, 200)
        self.assertEqual(
            self.client.post(
                evidence_url,
                {
                    "requirement_id": "FR-001",
                    "acceptance_criterion_id": "AC-002",
                    "evidence_type": "manual_review",
                    "description": "No.",
                    "result": "passed",
                    "review_basis": "manually_reviewed",
                },
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/workspaces/{self.workspace.pk}/implementation/tasks/generate/",
                {"requirements_artifact_id": str(self.requirements.pk)},
                format="json",
            ).status_code,
            404,
        )
        verify_url = f"{self.requirements_url('FR-001')}verification/"
        self.assertEqual(self.client.get(verify_url).status_code, 200)
        self.assertEqual(self.client.post(verify_url, {}, format="json").status_code, 403)

    def test_unrelated_workspace_ids_are_not_accessible(self):
        self.generate_plan()
        other_workspace = ProjectWorkspace.objects.create(
            owner=self.other, name="Private implementation"
        )
        other_task = ImplementationTask.objects.create(
            workspace=other_workspace,
            source_requirements=WorkspaceArtifact.objects.create(
                workspace=other_workspace,
                kind=WorkspaceArtifact.Kind.REQUIREMENTS,
                status=WorkspaceArtifact.Status.APPROVED,
                content=requirements_content(),
            ),
            source_requirement_id="FR-001",
            title="Private task",
            description="Private",
        )
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(f"{self.tasks_url()}{other_task.pk}/").status_code, 404)
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(
            self.client.get(
                f"/api/workspaces/{self.workspace.pk}/requirements/"
                f"{other_task.source_requirements_id}/FR-001/evidence/"
            ).status_code,
            404,
        )

    def test_workspace_deletion_cascades_planning_records_and_keeps_existing_delete_behavior(self):
        self.generate_plan()
        self.add_evidence("FR-001", criterion_id="AC-001")
        self.verify("FR-001")
        response = self.client.delete(f"/api/workspaces/{self.workspace.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ProjectWorkspace.objects.filter(pk=self.workspace.pk).exists())

    def test_anonymous_users_cannot_view_planning_or_verification(self):
        self.generate_plan()
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self.tasks_url()).status_code, (401, 403))
        self.assertIn(
            self.client.get(
                f"{self.requirements_url('FR-001')}verification/"
            ).status_code,
            (401, 403),
        )
