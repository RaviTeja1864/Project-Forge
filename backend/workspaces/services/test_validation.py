from django.test import SimpleTestCase

from backend.workspaces.services.generation import normalize_comparison_options
from backend.workspaces.services.validation import (
    ArtifactValidationError,
    validate_design,
    validate_requirements,
    validate_technology_comparison,
)

SOURCE_ID = "10000000-0000-0000-0000-000000000001"


def requirements():
    return {
        "problem_statement": "Improve safe water access.",
        "objectives": ["Help residents understand available access points."],
        "target_users": [{"name": "Residents", "assumptions": ["Users can access a phone."]}],
        "scope": {"in_scope": ["Show reported access information."], "out_of_scope": ["Operate water infrastructure."]},
        "user_stories": [
            {"id": "US-001", "as_a": "resident", "want": "find access information", "so_that": "I can plan", "evidence_source_ids": [SOURCE_ID]}
        ],
        "functional_requirements": [
            {"id": "FR-001", "statement": "Present source-linked access information.", "classification": "evidence_backed", "evidence_source_ids": [SOURCE_ID], "needs_user_input": False}
        ],
        "non_functional_requirements": [
            {"id": "NFR-001", "statement": "Use a clear interface.", "acceptance_condition": None, "classification": "proposed", "evidence_source_ids": [], "needs_user_input": True}
        ],
        "constraints": [],
        "assumptions": [{"statement": "A representative user can review the prototype.", "evidence_source_ids": []}],
        "dependencies": [],
        "risks": [],
        "acceptance_criteria": [
            {"id": "AC-001", "criterion": "A user can open the source linked from an access record.", "requirement_ids": ["FR-001"], "evidence_source_ids": [SOURCE_ID], "needs_user_input": False}
        ],
    }


def technology_comparison():
    option = {
        "name": "Django",
        "role": "Backend framework",
        "advantages": ["Uses a Python backend."],
        "disadvantages": ["Requires familiarity with Django."],
        "compatibility": [{"requirement_id": "FR-001", "assessment": "good", "reason": "Can serve source-linked information."}],
        "operational_considerations": ["Requires deployment and monitoring."],
        "learning_considerations": ["Review framework conventions."],
        "evidence_backed_claims": [],
        "unverified_assumptions": ["Local operators can maintain a Python service."],
        "missing_information": ["Hosting constraints are unknown."],
    }
    second = {**option, "name": "Flask", "compatibility": [{**option["compatibility"][0], "assessment": "unknown"}]}
    return {
        "selection_criteria": [{"name": "Requirement fit", "reason": "Compare against the approved requirement set."}],
        "scoring_method": "Qualitative ratings are explained per criterion; no numeric score is used.",
        "options": [option, second],
        "recommendation": {"option": "Django", "reasoning": "The comparison favors the existing Python service context.", "limitations": ["This is not independently verified."]},
        "insufficient_evidence": True,
    }


def design():
    return {
        "selected_technology": "Django",
        "technology_rationale": "Matches the approved comparison recommendation.",
        "architecture_components": [
            {"name": "WebApp", "responsibility": "Present source-linked information.", "requirement_ids": ["FR-001"], "evidence_source_ids": [SOURCE_ID]}
        ],
        "architecture_diagram": "flowchart LR\n  WebApp --> Api",
        "data_flow_diagram": "flowchart LR\n  Resident --> WebApp --> Api",
        "main_flows": ["Residents request information and receive source references."],
        "api_endpoints": [
            {"method": "GET", "path": "/api/problems/", "purpose": "List source-backed problems.", "authentication": "Authenticated session.", "request_shape": "Query parameters.", "response_shape": "Paginated JSON."}
        ],
        "database_entities": [
            {"name": "Workspace", "attributes": [{"name": "id", "type": "UUID", "constraints": ["Primary key"]}]},
            {"name": "Evidence", "attributes": [{"name": "id", "type": "UUID", "constraints": ["Primary key"]}]},
        ],
        "relationships": [{"from_entity": "Workspace", "to_entity": "Evidence", "cardinality": "one-to-many", "description": "Workspace references evidence records."}],
        "er_diagram": "erDiagram\n  Workspace ||--o{ Evidence : contains",
        "security_considerations": ["Require authenticated access."],
        "privacy_considerations": ["Minimize personal data."],
        "reliability_considerations": ["Return explicit service errors."],
        "failure_handling": ["Show retryable failures."],
        "tradeoffs": ["Keep the first design simple."],
        "unresolved_decisions": ["Confirm hosting constraints."],
    }


class ProjectArtifactValidationTests(SimpleTestCase):
    def test_requirements_validate_stable_ids_and_source_references(self):
        result = validate_requirements(requirements(), {SOURCE_ID})
        self.assertEqual(result["functional_requirements"][0]["id"], "FR-001")
        self.assertTrue(result["non_functional_requirements"][0]["needs_user_input"])

    def test_requirements_reject_duplicate_ids_and_invalid_references(self):
        value = requirements()
        value["functional_requirements"].append(dict(value["functional_requirements"][0]))
        with self.assertRaisesRegex(ArtifactValidationError, "unique"):
            validate_requirements(value, {SOURCE_ID})
        value = requirements()
        value["acceptance_criteria"][0]["requirement_ids"] = ["FR-999"]
        with self.assertRaisesRegex(ArtifactValidationError, "existing requirement"):
            validate_requirements(value, {SOURCE_ID})

    def test_requirements_reject_unverified_quantitative_targets_without_user_input(self):
        value = requirements()
        value["non_functional_requirements"][0].update(
            acceptance_condition="Respond within 200 ms.",
            needs_user_input=False,
        )
        with self.assertRaisesRegex(ArtifactValidationError, "quantitative"):
            validate_requirements(value, {SOURCE_ID})

    def test_evidence_backed_requirements_require_known_citations(self):
        value = requirements()
        value["functional_requirements"][0]["evidence_source_ids"] = ["fabricated"]
        with self.assertRaisesRegex(ArtifactValidationError, "outside"):
            validate_requirements(value, {SOURCE_ID})
        value = requirements()
        value["functional_requirements"][0]["evidence_source_ids"] = []
        with self.assertRaisesRegex(ArtifactValidationError, "must cite"):
            validate_requirements(value, {SOURCE_ID})

    def test_incomplete_requirements_are_rejected(self):
        value = requirements()
        value["acceptance_criteria"] = []
        with self.assertRaisesRegex(ArtifactValidationError, "At least one"):
            validate_requirements(value, {SOURCE_ID})

    def test_technology_comparison_preserves_options_and_qualitative_method(self):
        result = validate_technology_comparison(
            technology_comparison(),
            {SOURCE_ID},
            ["Django", "Flask"],
        )
        self.assertEqual(len(result["options"]), 2)
        self.assertTrue(result["insufficient_evidence"])
        self.assertEqual(result["recommendation"]["option"], "Django")

    def test_technology_options_are_user_supplied_unique_and_bounded(self):
        self.assertEqual(normalize_comparison_options([" Django ", "Flask"]), ["Django", "Flask"])
        for value in (["Django"], ["Django", "django"], ["A" * 121, "Flask"]):
            with self.subTest(value=value), self.assertRaises(ArtifactValidationError):
                normalize_comparison_options(value)

    def test_comparison_rejects_fabricated_citations_or_unknown_options(self):
        value = technology_comparison()
        value["options"][0]["evidence_backed_claims"] = [
            {"claim": "Unsupported detail.", "evidence_source_ids": ["invented"]}
        ]
        with self.assertRaisesRegex(ArtifactValidationError, "outside"):
            validate_technology_comparison(value, {SOURCE_ID}, ["Django", "Flask"])
        value = technology_comparison()
        value["options"][0]["name"] = "Other"
        with self.assertRaisesRegex(ArtifactValidationError, "match"):
            validate_technology_comparison(value, {SOURCE_ID}, ["Django", "Flask"])

    def test_design_marks_proposal_and_checks_entity_endpoint_consistency(self):
        result = validate_design(
            design(), {"FR-001"}, {SOURCE_ID}, recommended_technology="Django"
        )
        self.assertEqual(result["proposal_status"], "proposed")
        self.assertEqual(len(result["database_entities"]), 2)
        self.assertEqual(result["api_endpoints"][0]["method"], "GET")

    def test_design_rejects_invalid_mermaid_entities_and_unsafe_paths(self):
        value = design()
        value["er_diagram"] = "erDiagram\n  Workspace ||--o{ Other : contains"
        with self.assertRaisesRegex(ArtifactValidationError, "every declared"):
            validate_design(value, {"FR-001"}, {SOURCE_ID}, recommended_technology="Django")
        value = design()
        value["api_endpoints"][0]["path"] = "https://outside.example/"
        with self.assertRaisesRegex(ArtifactValidationError, "relative path"):
            validate_design(value, {"FR-001"}, {SOURCE_ID}, recommended_technology="Django")

    def test_design_rejects_fabricated_requirement_citations(self):
        value = design()
        value["architecture_components"][0]["requirement_ids"] = ["FR-999"]
        with self.assertRaisesRegex(ArtifactValidationError, "existing requirement"):
            validate_design(value, {"FR-001"}, {SOURCE_ID}, recommended_technology="Django")
