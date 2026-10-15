import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from backend.catalogue.models import EvidenceSource, ProblemStatement
from backend.workspaces.models import ProjectWorkspace, WorkspaceArtifact
from backend.workspaces.services.ollama import OllamaOfflineError

User = get_user_model()
SOURCE_ID = "20000000-0000-0000-0000-000000000001"


def research_content(source_id=SOURCE_ID):
    return {
        "problem_summary": "The report describes water access needs.",
        "key_claims": [
            {"claim": "Residents need access to safe water.", "support_status": "supported", "evidence_source_ids": [source_id]}
        ],
        "evidence_limitations": [],
        "conflicting_information": [],
        "unknown_or_unsupported_details": ["The number of affected households is unknown."],
        "research_gaps": [{"gap": "Population data is unavailable.", "suggested_next_steps": ["Find a relevant official dataset."]}],
        "interpretations_and_recommendations": [],
        "omitted_evidence_count": 0,
    }


def requirements_content(source_id=SOURCE_ID):
    return {
        "problem_statement": "Improve access to source-linked water information.",
        "objectives": ["Help residents locate verified information."],
        "target_users": [{"name": "Residents", "assumptions": ["Users have internet access."]}],
        "scope": {"in_scope": ["Show source links."], "out_of_scope": ["Build water infrastructure."]},
        "user_stories": [{"id": "US-001", "as_a": "resident", "want": "see water information", "so_that": "I can understand the issue", "evidence_source_ids": [source_id]}],
        "functional_requirements": [{"id": "FR-001", "statement": "Show traceable evidence.", "classification": "evidence_backed", "evidence_source_ids": [source_id], "needs_user_input": False}],
        "non_functional_requirements": [{"id": "NFR-001", "statement": "Make the interface understandable.", "acceptance_condition": None, "classification": "proposed", "evidence_source_ids": [], "needs_user_input": True}],
        "constraints": [],
        "assumptions": [{"statement": "A community representative can review the prototype.", "evidence_source_ids": []}],
        "dependencies": [],
        "risks": [],
        "acceptance_criteria": [{"id": "AC-001", "criterion": "Open evidence from a problem detail page.", "requirement_ids": ["FR-001"], "evidence_source_ids": [source_id], "needs_user_input": False}],
    }


def technology_content():
    option = {
        "name": "Django",
        "role": "Backend",
        "advantages": ["Uses the existing Python backend."],
        "disadvantages": ["Requires Django expertise."],
        "compatibility": [{"requirement_id": "FR-001", "assessment": "good", "reason": "Can expose a REST resource."}],
        "operational_considerations": ["Requires deployment monitoring."],
        "learning_considerations": ["Review project conventions."],
        "evidence_backed_claims": [],
        "unverified_assumptions": ["The team can maintain Python."],
        "missing_information": ["Hosting details are unknown."],
    }
    return {
        "selection_criteria": [{"name": "Requirement fit", "reason": "Compare against reviewed requirements."}],
        "scoring_method": "Qualitative tradeoffs only; no numeric scoring.",
        "options": [option, {**option, "name": "Flask"}],
        "recommendation": {"option": "Django", "reasoning": "The current workspace already uses Python.", "limitations": ["This choice needs user approval."]},
        "insufficient_evidence": True,
    }


def design_content():
    return {
        "selected_technology": "Django",
        "technology_rationale": "This comparison recommendation is user-approved.",
        "architecture_components": [{"name": "Client", "responsibility": "Display project information.", "requirement_ids": ["FR-001"], "evidence_source_ids": [SOURCE_ID]}],
        "architecture_diagram": "flowchart LR\n  Client --> API",
        "data_flow_diagram": "flowchart LR\n  User --> Client --> API",
        "main_flows": ["The user requests a problem and receives evidence links."],
        "api_endpoints": [{"method": "GET", "path": "/api/problems/", "purpose": "List problems.", "authentication": "Session authentication.", "request_shape": "Query string.", "response_shape": "Paginated result."}],
        "database_entities": [{"name": "Problem", "attributes": [{"name": "id", "type": "UUID", "constraints": ["Primary key"]}]}],
        "relationships": [],
        "er_diagram": "erDiagram\n  Problem",
        "security_considerations": ["Check workspace ownership."],
        "privacy_considerations": ["Avoid unrelated data collection."],
        "reliability_considerations": ["Return explicit failures."],
        "failure_handling": ["Show retryable request errors."],
        "tradeoffs": ["Prefer simple read-only endpoints."],
        "unresolved_decisions": ["Confirm deployment topology."],
    }


class WorkspaceArtifactApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="artifact-owner@example.com", password="test-artifact-password"
        )
        self.other = User.objects.create_user(
            email="artifact-other@example.com", password="test-artifact-password"
        )
        self.workspace = ProjectWorkspace.objects.create(
            owner=self.owner,
            name="Water access project",
            description="Explore safe water access.",
        )
        self.problem = ProblemStatement.objects.create(
            external_source_id="artifact:problem:1",
            title="Safe water access",
            description="The community reports access difficulties.",
        )
        self.source = EvidenceSource.objects.create(
            id=uuid.UUID(SOURCE_ID),
            problem=self.problem,
            external_source_id="artifact:source:1",
            source_url="https://example.org/water",
            source_title="Water access report",
            publisher="Public agency",
            relevant_excerpt="Residents report water access difficulties.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def generate_url(self, phase):
        return f"/api/workspaces/{self.workspace.pk}/generate/{phase}/"

    def artifact_url(self, artifact):
        return f"/api/workspaces/{self.workspace.pk}/artifacts/{artifact.pk}/"

    def approve(self, artifact):
        response = self.client.patch(self.artifact_url(artifact), {"status": "approved"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        artifact.refresh_from_db()
        return artifact

    @patch("backend.workspaces.views.generate_research")
    def test_research_generation_persists_provenance_as_a_reviewable_draft(self, generate):
        source_snapshot = {
            "id": SOURCE_ID,
            "external_source_id": self.source.external_source_id,
            "source_url": self.source.source_url,
            "canonical_url": self.source.canonical_url,
            "source_title": self.source.source_title,
            "publisher": self.source.publisher,
            "publication_date": None,
            "retrieved_at": self.source.retrieved_at.isoformat(),
            "relevant_excerpt": self.source.relevant_excerpt,
            "source_type": self.source.source_type,
        }
        generate.return_value = research_content(), [source_snapshot]
        response = self.client.post(
            self.generate_url("research"),
            {"problem_id": str(self.problem.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["kind"], "research")
        self.assertEqual(response.data["version_number"], 1)
        self.assertEqual(response.data["lineage_root_id"], response.data["id"])
        self.assertEqual(response.data["revision_of_id"], None)
        self.assertEqual(response.data["author_id"], self.owner.pk)
        self.assertEqual(response.data["source_snapshot"][0]["source_url"], self.source.source_url)
        self.assertEqual(response.data["source_problem_id"], str(self.problem.pk))
        self.assertEqual(generate.call_args.args[0], self.problem)

    def test_empty_catalogue_evidence_yields_deterministic_gap_without_model_call(self):
        self.problem.evidence_sources.all().delete()
        from backend.workspaces.services.research import insufficient_evidence_synthesis

        content = insufficient_evidence_synthesis(self.problem)
        self.assertEqual(content["key_claims"], [])
        self.assertEqual(content["evidence"], [])

    @patch("backend.workspaces.views.generate_research")
    def test_invalid_citations_are_rejected_without_persisting_artifact(self, generate):
        content = research_content("fabricated-source")
        generate.return_value = content, []
        response = self.client.post(
            self.generate_url("research"),
            {"problem_id": str(self.problem.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            WorkspaceArtifact.objects.filter(workspace=self.workspace).count(), 0
        )

    def test_requirements_generation_requires_approved_research(self):
        response = self.client.post(self.generate_url("requirements"), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Approve a research", str(response.data["detail"]))

    @patch("backend.workspaces.views.generate_research")
    @patch("backend.workspaces.views.generate_requirements")
    @patch("backend.workspaces.views.generate_technology_comparison")
    @patch("backend.workspaces.views.generate_system_design")
    def test_all_phase_generators_use_approved_inputs_and_require_explicit_approval(
        self, design_generator, technology_generator, requirements_generator, research_generator
    ):
        source_snapshot = {
            "id": SOURCE_ID,
            "source_url": self.source.source_url,
            "canonical_url": self.source.canonical_url,
            "source_title": self.source.source_title,
        }
        research_generator.return_value = research_content(), [source_snapshot]
        research_response = self.client.post(
            self.generate_url("research"),
            {"problem_id": str(self.problem.pk)},
            format="json",
        )
        research = WorkspaceArtifact.objects.get(pk=research_response.data["id"])
        self.assertEqual(
            self.client.post(self.generate_url("requirements"), {}, format="json").status_code,
            400,
        )
        self.approve(research)

        requirements_generator.return_value = requirements_content()
        requirements_response = self.client.post(
            self.generate_url("requirements"), {}, format="json"
        )
        self.assertEqual(requirements_response.status_code, 201, requirements_response.data)
        requirements = WorkspaceArtifact.objects.get(pk=requirements_response.data["id"])
        self.assertEqual(requirements.input_artifact_ids, [str(research.pk)])
        self.approve(requirements)

        technology_generator.return_value = technology_content()
        technology_response = self.client.post(
            self.generate_url("technology"),
            {"options": ["Django", "Flask"]},
            format="json",
        )
        self.assertEqual(technology_response.status_code, 201, technology_response.data)
        technology = WorkspaceArtifact.objects.get(pk=technology_response.data["id"])
        self.assertEqual(technology.input_artifact_ids, [str(research.pk), str(requirements.pk)])
        self.assertEqual(
            design_generator.call_count,
            0,
        )
        self.approve(technology)

        design_generator.return_value = design_content()
        design_response = self.client.post(self.generate_url("design"), {}, format="json")
        self.assertEqual(design_response.status_code, 201, design_response.data)
        design = WorkspaceArtifact.objects.get(pk=design_response.data["id"])
        self.assertEqual(
            design.input_artifact_ids,
            [str(research.pk), str(requirements.pk), str(technology.pk)],
        )
        self.assertEqual(design_response.data["content"]["proposal_status"], "proposed")

    @patch("backend.workspaces.views.generate_requirements")
    def test_ollama_failures_are_safe_and_do_not_create_artifacts(self, generate):
        research = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=research_content(),
            source_snapshot=[],
            source_problem_id=self.problem.pk,
        )
        generate.side_effect = OllamaOfflineError("private endpoint")
        response = self.client.post(self.generate_url("requirements"), {}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private endpoint", str(response.data))
        self.assertEqual(
            WorkspaceArtifact.objects.filter(
                workspace=self.workspace,
                kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            ).count(),
            0,
        )
        self.assertEqual(research.status, WorkspaceArtifact.Status.APPROVED)

    def test_approved_artifacts_cannot_be_overwritten_but_can_be_revised(self):
        artifact = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=research_content(),
            source_snapshot=[],
        )
        response = self.client.patch(
            self.artifact_url(artifact),
            {"content": {"problem_summary": "Overwritten"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        revise = self.client.post(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{artifact.pk}/revise/",
            {},
            format="json",
        )
        self.assertEqual(revise.status_code, 201)
        self.assertEqual(revise.data["status"], "draft")
        self.assertEqual(revise.data["content"], artifact.content)
        self.assertEqual(revise.data["version_number"], 2)
        self.assertEqual(revise.data["lineage_root_id"], str(artifact.pk))
        self.assertEqual(revise.data["revision_of_id"], str(artifact.pk))
        self.assertEqual(revise.data["author_id"], self.owner.pk)
        artifact.refresh_from_db()
        self.assertEqual(artifact.status, WorkspaceArtifact.Status.APPROVED)
        self.assertEqual(artifact.version_number, 1)

    def test_regeneration_preserves_prior_content_and_makes_it_read_only(self):
        first_content = research_content()
        second_content = research_content()
        second_content["problem_summary"] = "A separately generated summary."
        with patch(
            "backend.workspaces.views.generate_research",
            side_effect=[
                (first_content, [{"id": SOURCE_ID}]),
                (second_content, [{"id": SOURCE_ID}]),
            ],
        ):
            first = self.client.post(
                self.generate_url("research"),
                {"problem_id": str(self.problem.pk)},
                format="json",
            )
            second = self.client.post(
                self.generate_url("research"),
                {"problem_id": str(self.problem.pk)},
                format="json",
            )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data["version_number"], 2)
        self.assertEqual(second.data["revision_of_id"], first.data["id"])
        self.assertEqual(
            WorkspaceArtifact.objects.get(pk=first.data["id"]).content,
            first_content,
        )
        edit_history = self.client.patch(
            self.artifact_url(WorkspaceArtifact.objects.get(pk=first.data["id"])),
            {"content": first_content},
            format="json",
        )
        self.assertEqual(edit_history.status_code, 400)
        delete_history = self.client.delete(
            self.artifact_url(WorkspaceArtifact.objects.get(pk=first.data["id"]))
        )
        self.assertEqual(delete_history.status_code, 400)
        revision = self.client.post(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{first.data['id']}/revise/",
            {},
            format="json",
        )
        self.assertEqual(revision.status_code, 201, revision.data)
        self.assertEqual(revision.data["version_number"], 3)
        self.assertEqual(revision.data["revision_of_id"], first.data["id"])

    def test_version_history_retrieval_and_comparison_are_lineage_scoped(self):
        source_snapshot = [{
            "id": SOURCE_ID,
            "source_url": self.source.source_url,
            "source_title": self.source.source_title,
        }]
        first = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=research_content(),
            source_snapshot=source_snapshot,
            author=self.owner,
        )
        revision_response = self.client.post(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{first.pk}/revise/",
            {},
            format="json",
        )
        self.assertEqual(revision_response.status_code, 201)
        second_id = revision_response.data["id"]
        changed_content = research_content()
        changed_content["problem_summary"] = "A revised summary."
        edit = self.client.patch(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{second_id}/",
            {"content": changed_content},
            format="json",
        )
        self.assertEqual(edit.status_code, 200, edit.data)

        history_url = f"/api/workspaces/{self.workspace.pk}/artifacts/{second_id}/versions/"
        history = self.client.get(history_url)
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["version_number"] for item in history.data], [1, 2])
        self.assertEqual(history.data[0]["source_snapshot"], source_snapshot)
        self.assertEqual(history.data[0]["status"], WorkspaceArtifact.Status.APPROVED)
        previous = self.client.get(f"{history_url}{first.pk}/")
        self.assertEqual(previous.status_code, 200)
        self.assertEqual(previous.data["content"], research_content())

        comparison = self.client.get(
            f"{history_url}compare/",
            {"left_version": str(first.pk), "right_version": second_id},
        )
        self.assertEqual(comparison.status_code, 200, comparison.data)
        self.assertIn("content.problem_summary", comparison.data["changed_fields"])
        change = next(
            item for item in comparison.data["changes"]
            if item["path"] == "content.problem_summary"
        )
        self.assertEqual(change["before"], research_content()["problem_summary"])
        self.assertEqual(change["after"], "A revised summary.")

        other = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            content=research_content(),
            source_snapshot=[{"id": SOURCE_ID}],
        )
        invalid_comparison = self.client.get(
            f"{history_url}compare/",
            {"left_version": str(first.pk), "right_version": str(other.pk)},
        )
        self.assertEqual(invalid_comparison.status_code, 404)

    def test_approval_applies_only_to_the_selected_version_and_numbers_are_unique(self):
        first = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            content=research_content(),
            source_snapshot=[{"id": SOURCE_ID}],
        )
        self.approve(first)
        revision = self.client.post(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{first.pk}/revise/",
            {},
            format="json",
        )
        self.assertEqual(revision.status_code, 201)
        second = WorkspaceArtifact.objects.get(pk=revision.data["id"])
        self.assertEqual(second.status, WorkspaceArtifact.Status.DRAFT)
        second_approval = self.client.patch(
            self.artifact_url(second),
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(second_approval.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, WorkspaceArtifact.Status.APPROVED)
        self.assertEqual(second.status, WorkspaceArtifact.Status.APPROVED)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkspaceArtifact.objects.create(
                workspace=self.workspace,
                kind=WorkspaceArtifact.Kind.RESEARCH,
                content=research_content(),
                source_snapshot=[],
                lineage_root=first,
                version_number=1,
            )

    def test_version_history_and_mutation_are_hidden_from_other_users(self):
        first = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=research_content(),
            source_snapshot=[],
        )
        created = self.client.post(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{first.pk}/revise/",
            {},
            format="json",
        )
        version_id = created.data["id"]
        self.client.force_authenticate(user=self.other)
        history_url = f"/api/workspaces/{self.workspace.pk}/artifacts/{first.pk}/versions/"
        requests = (
            self.client.get(history_url),
            self.client.get(f"{history_url}{version_id}/"),
            self.client.get(
                f"{history_url}compare/",
                {"left_version": str(first.pk), "right_version": version_id},
            ),
            self.client.patch(
                f"/api/workspaces/{self.workspace.pk}/artifacts/{version_id}/",
                {"status": "approved"},
                format="json",
            ),
        )
        for response in requests:
            self.assertEqual(response.status_code, 404)

    def test_workspace_deletion_cascades_through_version_lineages(self):
        approved = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=research_content(),
            source_snapshot=[],
        )
        WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            content=research_content(),
            source_snapshot=[],
            version_number=2,
            lineage_root=approved,
            revision_of=approved,
        )
        response = self.client.delete(f"/api/workspaces/{self.workspace.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(WorkspaceArtifact.objects.filter(workspace=self.workspace).exists())

    def test_another_user_cannot_access_workspace_artifacts_or_generate(self):
        self.client.force_authenticate(user=self.other)
        urls = (
            f"/api/workspaces/{self.workspace.pk}/artifacts/",
            self.generate_url("research"),
        )
        for url in urls:
            with self.subTest(url=url):
                response = (
                    self.client.post(url, {"problem_id": str(self.problem.pk)}, format="json")
                    if "generate/" in url
                    else self.client.get(url)
                )
                self.assertEqual(response.status_code, 404)

    def test_anonymous_users_cannot_use_generation_or_artifact_api(self):
        self.client.force_authenticate(user=None)
        for response in (
            self.client.get(f"/api/workspaces/{self.workspace.pk}/artifacts/"),
            self.client.post(self.generate_url("research"), {"problem_id": str(self.problem.pk)}, format="json"),
        ):
            self.assertIn(response.status_code, (401, 403))

    def test_owned_artifact_detail_and_draft_deletion_are_scoped(self):
        artifact = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            content=research_content(),
            source_snapshot=[],
        )
        detail = self.client.get(self.artifact_url(artifact))
        self.assertEqual(detail.status_code, 200)
        listing = self.client.get(
            f"/api/workspaces/{self.workspace.pk}/artifacts/"
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["id"] for item in listing.data], [str(artifact.pk)])
        self.assertEqual(self.client.delete(self.artifact_url(artifact)).status_code, 204)

        approved = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=research_content(),
            source_snapshot=[],
        )
        self.assertEqual(self.client.delete(self.artifact_url(approved)).status_code, 400)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(self.artifact_url(approved)).status_code, 404)
        self.assertEqual(
            self.client.post(
                f"/api/workspaces/{self.workspace.pk}/artifacts/{approved.pk}/revise/",
                {},
                format="json",
            ).status_code,
            404,
        )

    def test_invalid_generation_inputs_are_rejected(self):
        missing = self.client.post(self.generate_url("research"), {}, format="json")
        invalid = self.client.post(
            self.generate_url("research"), {"problem_id": "not-a-uuid"}, format="json"
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            self.client.post(
                self.generate_url("technology"),
                {"options": ["only one"]},
                format="json",
            ).status_code,
            400,
        )
