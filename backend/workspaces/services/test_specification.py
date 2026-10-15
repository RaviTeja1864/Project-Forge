import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from backend.workspaces.models import ProjectWorkspace, WorkspaceArtifact

User = get_user_model()
SOURCE_ID = "30000000-0000-0000-0000-000000000001"


def input_content(kind):
    if kind == WorkspaceArtifact.Kind.RESEARCH:
        return {
            "problem_summary": "Residents report limited access to safe water.",
            "key_claims": [
                {
                    "claim": "Residents report limited access to safe water.",
                    "support_status": "supported",
                    "evidence_source_ids": [SOURCE_ID],
                }
            ],
            "evidence_limitations": [],
            "conflicting_information": [],
            "unknown_or_unsupported_details": ["Affected population is unknown."],
            "research_gaps": [{"gap": "Population estimates are unavailable."}],
            "interpretations_and_recommendations": [],
        }
    if kind == WorkspaceArtifact.Kind.REQUIREMENTS:
        return {
            "problem_statement": "Improve access to source-linked water information.",
            "objectives": ["Help residents find relevant information."],
            "target_users": [{"name": "Residents", "assumptions": []}],
            "scope": {"in_scope": ["Show evidence"], "out_of_scope": ["Build infrastructure"]},
            "user_stories": [
                {
                    "id": "US-001",
                    "as_a": "resident",
                    "want": "view source links",
                    "so_that": "I can check the information",
                    "evidence_source_ids": [SOURCE_ID],
                }
            ],
            "functional_requirements": [
                {
                    "id": "FR-001",
                    "statement": "Display evidence links.",
                    "classification": "evidence_backed",
                    "evidence_source_ids": [SOURCE_ID],
                    "needs_user_input": False,
                }
            ],
            "non_functional_requirements": [
                {
                    "id": "NFR-001",
                    "statement": "Keep data private.",
                    "acceptance_condition": None,
                    "classification": "proposed",
                    "evidence_source_ids": [],
                    "needs_user_input": True,
                }
            ],
            "acceptance_criteria": [
                {
                    "id": "AC-001",
                    "criterion": "Open the source link from a problem page.",
                    "requirement_ids": ["FR-001"],
                    "evidence_source_ids": [SOURCE_ID],
                    "needs_user_input": False,
                }
            ],
            "constraints": [{"statement": "No unsupported claims.", "evidence_source_ids": []}],
            "assumptions": [{"statement": "Users can access the service.", "evidence_source_ids": []}],
            "dependencies": [],
            "risks": [{"statement": "Source records may be incomplete.", "evidence_source_ids": []}],
        }
    if kind == WorkspaceArtifact.Kind.TECHNOLOGY:
        option = {
            "name": "Django",
            "role": "Backend",
            "advantages": ["Existing project framework."],
            "disadvantages": ["Requires Python maintenance."],
            "compatibility": [
                {"requirement_id": "FR-001", "assessment": "good", "reason": "Supports API endpoints."}
            ],
            "operational_considerations": ["Monitor service health."],
            "learning_considerations": ["Follow project conventions."],
            "evidence_backed_claims": [],
            "unverified_assumptions": ["Team can maintain Python."],
            "missing_information": ["Hosting is unknown."],
        }
        return {
            "selection_criteria": [{"name": "Requirement fit", "reason": "Compare requirements."}],
            "scoring_method": "Qualitative trade-offs only.",
            "options": [option, {**option, "name": "Flask"}],
            "recommendation": {
                "option": "Django",
                "reasoning": "It is already used in the project.",
                "limitations": ["Confirm maintenance capacity."],
            },
            "insufficient_evidence": True,
        }
    return {
        "selected_technology": "Django",
        "technology_rationale": "Matches the approved comparison decision.",
        "architecture_components": [
            {
                "name": "API",
                "responsibility": "Serve evidence-backed records.",
                "requirement_ids": ["FR-001"],
                "evidence_source_ids": [SOURCE_ID],
            }
        ],
        "architecture_diagram": "flowchart LR\n  Client --> API",
        "data_flow_diagram": "flowchart LR\n  Client --> API",
        "main_flows": ["A user reads an evidence-backed record."],
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/api/problems/",
                "purpose": "List source-backed problems.",
                "authentication": "Session required.",
                "request_shape": "Query parameters.",
                "response_shape": "Paginated problem result.",
            }
        ],
        "database_entities": [
            {
                "name": "Problem",
                "attributes": [
                    {"name": "id", "type": "UUID", "constraints": ["Primary key"]}
                ],
            }
        ],
        "relationships": [],
        "er_diagram": "erDiagram\n  Problem",
        "security_considerations": ["Enforce workspace ownership."],
        "privacy_considerations": ["Do not expose unrelated workspace data."],
        "reliability_considerations": ["Return explicit errors."],
        "failure_handling": ["Show retryable failures."],
        "tradeoffs": ["Prefer a simple API."],
        "unresolved_decisions": ["Confirm deployment topology."],
    }


class WorkspaceSpecificationApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="specification-owner@example.com",
            password="test-password-only",
        )
        self.other = User.objects.create_user(
            email="specification-other@example.com",
            password="test-password-only",
        )
        self.workspace = ProjectWorkspace.objects.create(
            owner=self.owner,
            name="Water information project",
            description="Create an evidence-backed water information service.",
        )
        self.other_workspace = ProjectWorkspace.objects.create(
            owner=self.other,
            name="Private workspace",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.source = {
            "id": SOURCE_ID,
            "external_source_id": "public-record-1",
            "source_url": "https://example.org/water-report",
            "canonical_url": "https://example.org/water-report",
            "source_title": "Water access report",
            "publisher": "Public agency",
            "publication_date": None,
            "retrieved_at": "2026-10-16T00:00:00Z",
            "relevant_excerpt": "Residents report limited access to safe water.",
            "source_type": "report",
        }
        self.inputs = {}
        for kind in (
            WorkspaceArtifact.Kind.RESEARCH,
            WorkspaceArtifact.Kind.REQUIREMENTS,
            WorkspaceArtifact.Kind.TECHNOLOGY,
            WorkspaceArtifact.Kind.DESIGN,
        ):
            input_ids = []
            if kind == WorkspaceArtifact.Kind.REQUIREMENTS:
                input_ids = [str(self.inputs[WorkspaceArtifact.Kind.RESEARCH].pk)]
            elif kind == WorkspaceArtifact.Kind.TECHNOLOGY:
                input_ids = [
                    str(self.inputs[WorkspaceArtifact.Kind.RESEARCH].pk),
                    str(self.inputs[WorkspaceArtifact.Kind.REQUIREMENTS].pk),
                ]
            elif kind == WorkspaceArtifact.Kind.DESIGN:
                input_ids = [
                    str(self.inputs[WorkspaceArtifact.Kind.RESEARCH].pk),
                    str(self.inputs[WorkspaceArtifact.Kind.REQUIREMENTS].pk),
                    str(self.inputs[WorkspaceArtifact.Kind.TECHNOLOGY].pk),
                ]
            artifact = WorkspaceArtifact.objects.create(
                workspace=self.workspace,
                kind=kind,
                status=WorkspaceArtifact.Status.APPROVED,
                content=input_content(kind),
                source_snapshot=[self.source],
                input_artifact_ids=input_ids,
                author=self.owner,
            )
            self.inputs[kind] = artifact

    def url(self, suffix=""):
        return f"/api/workspaces/{self.workspace.pk}/specifications/{suffix}"

    def create_specification(self):
        response = self.client.post(self.url(), {}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_specification_composes_approved_artifacts_and_preserves_exact_provenance(self):
        second_source = {
            **self.source,
            "id": "30000000-0000-0000-0000-000000000002",
            "external_source_id": "public-record-2",
            "source_url": "https://example.org/water-data",
            "canonical_url": "https://example.org/water-data",
            "source_title": "Water access dataset",
        }
        requirements = self.inputs[WorkspaceArtifact.Kind.REQUIREMENTS]
        requirements.source_snapshot = [self.source, second_source]
        requirements.save(update_fields=("source_snapshot",))
        response = self.create_specification()
        self.assertEqual(response.data["kind"], WorkspaceArtifact.Kind.SPECIFICATION)
        self.assertEqual(response.data["status"], WorkspaceArtifact.Status.DRAFT)
        self.assertEqual(response.data["version_number"], 1)
        specification = response.data["content"]
        self.assertEqual(specification["project"]["title"], self.workspace.name)
        self.assertEqual(
            specification["project"]["problem_statement"],
            input_content(WorkspaceArtifact.Kind.REQUIREMENTS)["problem_statement"],
        )
        self.assertEqual(
            specification["research"]["evidence_sources"],
            [self.source, second_source],
        )
        self.assertEqual(
            specification["architecture"]["architecture_diagram"],
            input_content(WorkspaceArtifact.Kind.DESIGN)["architecture_diagram"],
        )
        self.assertEqual(
            specification["input_artifacts"],
            [
                {
                    "kind": artifact.kind,
                    "artifact_id": str(artifact.pk),
                    "version_number": artifact.version_number,
                    "status": WorkspaceArtifact.Status.APPROVED,
                    "lineage_root_id": str(artifact.lineage_root_id),
                }
                for artifact in self.inputs.values()
            ],
        )
        self.assertTrue(specification["generated_at"])
        self.assertEqual(response.data["source_snapshot"], [self.source, second_source])
        self.assertFalse(response.data["is_outdated"])

        history = self.client.get(self.url())
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["id"] for item in history.data], [response.data["id"]])
        detail = self.client.get(self.url(f"{response.data['id']}/"))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["content"], specification)
        input_report = self.client.get(self.url(f"{response.data['id']}/inputs/"))
        self.assertEqual(input_report.status_code, 200)
        self.assertEqual(
            {item["id"] for item in input_report.data["input_artifacts"]},
            {str(item.pk) for item in self.inputs.values()},
        )
        self.assertEqual(input_report.data["validation_findings"], [])

    def test_missing_or_unapproved_required_input_prevents_creation(self):
        design = self.inputs[WorkspaceArtifact.Kind.DESIGN]
        design.delete()
        response = self.client.post(self.url(), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("system design", str(response.data))
        self.assertFalse(
            WorkspaceArtifact.objects.filter(
                workspace=self.workspace,
                kind=WorkspaceArtifact.Kind.SPECIFICATION,
            ).exists()
        )

        design = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.DESIGN,
            status=WorkspaceArtifact.Status.DRAFT,
            content=input_content(WorkspaceArtifact.Kind.DESIGN),
            source_snapshot=[self.source],
        )
        response = self.client.post(self.url(), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("system design", str(response.data))
        self.assertEqual(design.status, WorkspaceArtifact.Status.DRAFT)

    def test_conflicting_technology_decisions_are_preserved_and_flagged(self):
        design = self.inputs[WorkspaceArtifact.Kind.DESIGN]
        design.content["selected_technology"] = "Flask"
        design.save(update_fields=("content",))

        response = self.create_specification()
        content = response.data["content"]
        self.assertEqual(content["technology"]["recommendation"]["option"], "Django")
        self.assertEqual(content["technology"]["design_selected_technology"], "Flask")
        self.assertEqual(content["specification_status"], "review_required")
        conflict = next(
            finding
            for finding in content["validation_findings"]
            if finding["code"] == "technology_decision_conflict"
        )
        self.assertEqual(conflict["severity"], "warning")

    def test_missing_citations_are_reported_and_snapshot_is_not_created(self):
        requirements = self.inputs[WorkspaceArtifact.Kind.REQUIREMENTS]
        requirements.content["functional_requirements"][0]["evidence_source_ids"] = [
            "fabricated-evidence-id"
        ]
        requirements.save(update_fields=("content",))

        response = self.client.post(self.url(), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not present in the approved research source snapshot", str(response.data))
        self.assertFalse(
            WorkspaceArtifact.objects.filter(
                workspace=self.workspace,
                kind=WorkspaceArtifact.Kind.SPECIFICATION,
            ).exists()
        )

    def test_invalid_mermaid_is_rejected_before_snapshot_creation(self):
        design = self.inputs[WorkspaceArtifact.Kind.DESIGN]
        design.content["architecture_diagram"] = "<script>alert(1)</script>"
        design.save(update_fields=("content",))
        response = self.client.post(self.url(), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("permitted Mermaid flowchart syntax", str(response.data))
        self.assertFalse(
            WorkspaceArtifact.objects.filter(
                workspace=self.workspace,
                kind=WorkspaceArtifact.Kind.SPECIFICATION,
            ).exists()
        )

    def test_snapshots_are_immutable_regeneration_is_sequential_and_new_inputs_mark_old_snapshot(self):
        first = self.create_specification()
        old_content = first.data["content"]
        approval = self.client.patch(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{first.data['id']}/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(approval.status_code, 200, approval.data)
        downgrade = self.client.patch(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{first.data['id']}/",
            {"status": "draft"},
            format="json",
        )
        self.assertEqual(downgrade.status_code, 400)

        original = self.inputs[WorkspaceArtifact.Kind.REQUIREMENTS]
        revised_requirements = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=original.kind,
            status=WorkspaceArtifact.Status.APPROVED,
            content={**original.content, "objectives": ["A newly approved objective."]},
            source_snapshot=original.source_snapshot,
            version_number=2,
            lineage_root=original.lineage_root,
            revision_of=original,
            author=self.owner,
        )
        old_detail = self.client.get(self.url(f"{first.data['id']}/"))
        self.assertTrue(old_detail.data["is_outdated"])
        self.assertEqual(old_detail.data["content"], old_content)

        second = self.create_specification()
        self.assertEqual(second.data["version_number"], 2)
        self.assertEqual(second.data["revision_of_id"], first.data["id"])
        self.assertNotEqual(
            second.data["content"]["input_artifacts"],
            old_content["input_artifacts"],
        )
        self.assertEqual(
            second.data["content"]["input_artifacts"][1]["artifact_id"],
            str(revised_requirements.pk),
        )
        self.assertIn(
            "approved_input_lineage_mismatch",
            {
                finding["code"]
                for finding in second.data["content"]["validation_findings"]
            },
        )
        self.assertFalse(second.data["is_outdated"])
        self.assertEqual(
            self.client.get(self.url(f"{first.data['id']}/")).data["content"],
            old_content,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/workspaces/{self.workspace.pk}/artifacts/{first.data['id']}/",
                {"content": {"project": {"title": "Overwrite"}}},
                format="json",
            ).status_code,
            400,
        )

    def test_other_users_cannot_read_generate_or_inspect_specs(self):
        specification = self.create_specification()
        self.client.force_authenticate(user=self.other)
        for response in (
            self.client.get(self.url()),
            self.client.get(self.url(f"{specification.data['id']}/")),
            self.client.get(self.url(f"{specification.data['id']}/inputs/")),
            self.client.post(self.url(), {}, format="json"),
        ):
            self.assertEqual(response.status_code, 404)

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(
            f"/api/workspaces/{self.other_workspace.pk}/specifications/"
        )
        self.assertEqual(response.status_code, 404)

    def test_specification_revision_endpoint_rejects_snapshot_mutation(self):
        specification = self.create_specification()
        response = self.client.post(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{specification.data['id']}/revise/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("generate a new snapshot", str(response.data))

    def test_generation_rejects_unexpected_client_input(self):
        response = self.client.post(self.url(), {"inputs": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_markdown_export_preserves_snapshot_metadata_citations_diagrams_and_utf8(self):
        specification = self.create_specification()
        artifact = WorkspaceArtifact.objects.get(pk=specification.data["id"])
        artifact.content["project"]["title"] = "../Wáter & Evidence"
        artifact.content["research"]["key_claims"][0]["claim"] = "Café users report water needs."
        artifact.save(update_fields=("content",))
        original_content = artifact.content.copy()

        response = self.client.get(self.url(f"{artifact.pk}/export.md"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="water-evidence-v1.md"',
        )
        exported = response.content.decode("utf-8")
        self.assertIn("# ../Wáter & Evidence", exported)
        self.assertIn("DRAFT — NOT APPROVED", exported)
        self.assertIn("Input artifact versions", exported)
        self.assertIn(str(self.inputs[WorkspaceArtifact.Kind.RESEARCH].pk), exported)
        self.assertIn(SOURCE_ID, exported)
        self.assertIn("https://example.org/water-report", exported)
        self.assertIn("```mermaid\nflowchart LR\n  Client --> API\n```", exported)
        self.assertIn("Unresolved information and research gaps", exported)
        artifact.refresh_from_db()
        self.assertEqual(artifact.content, original_content)

    def test_markdown_mermaid_fences_cannot_be_closed_by_stored_diagram_text(self):
        from backend.workspaces.services.specification_export import (
            specification_markdown,
        )

        specification = self.create_specification()
        artifact = WorkspaceArtifact.objects.get(pk=specification.data["id"])
        artifact.content["architecture"]["architecture_diagram"] = (
            "flowchart LR\n  A --> B\n```\n# embedded heading"
        )
        rendered = specification_markdown(artifact, outdated=False)
        self.assertIn(
            "````mermaid\nflowchart LR\n  A --> B\n```\n# embedded heading\n````",
            rendered,
        )

    def test_pdf_export_is_local_readable_and_has_safe_outdated_filename(self):
        specification = self.create_specification()
        artifact = WorkspaceArtifact.objects.get(pk=specification.data["id"])
        artifact.content["project"]["title"] = "../Wáter/仕様"
        artifact.content["research"]["key_claims"][0]["claim"] = "Café users need evidence."
        artifact.save(update_fields=("content",))
        approved = self.client.patch(
            f"/api/workspaces/{self.workspace.pk}/artifacts/{artifact.pk}/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)

        response = self.client.get(self.url(f"{artifact.pk}/export.pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="water-v1.pdf"',
        )
        self.assertTrue(response.content.startswith(b"%PDF-"))
        artifact.refresh_from_db()
        self.assertEqual(
            artifact.content["project"]["title"],
            "../Wáter/仕様",
        )

        newer_research = WorkspaceArtifact.objects.create(
            workspace=self.workspace,
            kind=WorkspaceArtifact.Kind.RESEARCH,
            status=WorkspaceArtifact.Status.APPROVED,
            content=input_content(WorkspaceArtifact.Kind.RESEARCH),
            source_snapshot=[self.source],
            version_number=2,
            lineage_root=self.inputs[WorkspaceArtifact.Kind.RESEARCH].lineage_root,
            revision_of=self.inputs[WorkspaceArtifact.Kind.RESEARCH],
        )
        self.assertEqual(newer_research.version_number, 2)
        outdated_response = self.client.get(self.url(f"{artifact.pk}/export.md"))
        self.assertIn(b"POTENTIALLY OUTDATED", outdated_response.content)

    def test_export_authorization_missing_ids_and_wrong_artifact_types(self):
        specification = self.create_specification()
        self.client.force_authenticate(user=self.other)
        for export_format in ("md", "pdf"):
            response = self.client.get(
                self.url(f"{specification.data['id']}/export.{export_format}")
            )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                self.client.get(
                    f"/api/workspaces/{self.other_workspace.pk}/specifications/"
                    f"{specification.data['id']}/export.{export_format}"
                ).status_code,
                404,
            )

        self.client.force_authenticate(user=None)
        anonymous = self.client.get(
            f"/api/workspaces/{self.workspace.pk}/specifications/"
            f"{specification.data['id']}/export.md"
        )
        self.assertIn(anonymous.status_code, (401, 403))

        self.client.force_authenticate(user=self.owner)
        missing = self.client.get(self.url(f"{uuid.uuid4()}/export.pdf"))
        self.assertEqual(missing.status_code, 404)
        ordinary_artifact = self.inputs[WorkspaceArtifact.Kind.RESEARCH]
        wrong_type = self.client.get(
            f"/api/workspaces/{self.workspace.pk}/specifications/"
            f"{ordinary_artifact.pk}/export.md"
        )
        self.assertEqual(wrong_type.status_code, 404)

    def test_pdf_renderer_includes_utf8_text_and_mermaid_fallback(self):
        from backend.workspaces.services import specification_export
        from backend.workspaces.services.specification_export import specification_pdf

        specification = self.create_specification()
        artifact = WorkspaceArtifact.objects.get(pk=specification.data["id"])
        artifact.content["project"]["title"] = "Café engineering"
        artifact.content["architecture"]["architecture_diagram"] = (
            "flowchart LR\n  Café --> API"
        )
        artifact.save(update_fields=("content",))
        with patch.object(
            specification_export,
            "Paragraph",
            wraps=specification_export.Paragraph,
        ) as paragraph:
            pdf_data = specification_pdf(artifact, outdated=False)
        self.assertTrue(pdf_data.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_data), 1000)
        paragraph_text = [str(call.args[0]) for call in paragraph.call_args_list]
        self.assertTrue(any("Café" in text for text in paragraph_text))
        self.assertTrue(any("Café --&gt; API" in text for text in paragraph_text))
        self.assertTrue(
            any("https://example.org/water-report" in text for text in paragraph_text)
        )

    def test_unsupported_export_format_returns_validation_error(self):
        specification = self.create_specification()
        response = self.client.get(self.url(f"{specification.data['id']}/export.csv"))
        self.assertEqual(response.status_code, 400)

    @patch("backend.workspaces.views.specification_pdf")
    def test_pdf_rendering_failures_return_safe_retryable_error(self, render_pdf):
        from backend.workspaces.services.specification_export import (
            SpecificationExportError,
        )

        specification = self.create_specification()
        render_pdf.side_effect = SpecificationExportError("private renderer diagnostics")
        response = self.client.get(
            self.url(f"{specification.data['id']}/export.pdf")
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.data["detail"],
            "The selected specification could not be rendered. Try again.",
        )
        self.assertNotIn("private renderer diagnostics", str(response.data))
