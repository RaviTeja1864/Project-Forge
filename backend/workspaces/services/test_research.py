import uuid
from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings

from backend.catalogue.models import EvidenceSource, ProblemStatement
from backend.workspaces.services.research import (
    ResearchValidationError,
    collect_research_evidence,
    deduplicate_evidence,
    synthesize_research,
    validate_research_output,
)


def valid_synthesis(source_id):
    return {
        "problem_summary": "Reported water access challenges are described in the supplied report.",
        "key_claims": [
            {
                "claim": "The report describes limited access to safe water.",
                "support_status": "supported",
                "evidence_source_ids": [source_id],
            }
        ],
        "evidence_limitations": [
            {"description": "The report does not estimate prevalence.", "evidence_source_ids": [source_id]}
        ],
        "conflicting_information": [],
        "unknown_or_unsupported_details": ["The total population affected is unknown."],
        "research_gaps": [
            {
                "gap": "Prevalence is not established.",
                "suggested_next_steps": ["Find a credible source with population-level data."],
            }
        ],
        "interpretations_and_recommendations": [
            {
                "kind": "interpretation",
                "text": "Further local validation may be useful.",
                "evidence_source_ids": [],
            }
        ],
    }


class ResearchServiceTests(TestCase):
    def setUp(self):
        self.problem = ProblemStatement.objects.create(
            external_source_id="research:problem:1",
            title="Safe water access in rural communities",
            description="Residents report limited access to safe water.",
            sector="Water",
        )

    def add_source(self, number, url, *, excerpt="Safe water access is limited.", source_date=None):
        return EvidenceSource.objects.create(
            id=uuid.UUID(int=number),
            problem=self.problem,
            external_source_id=f"research:source:{number}",
            source_url=url,
            source_title=f"Water access report {number}",
            publisher="Public agency",
            publication_date=source_date,
            relevant_excerpt=excerpt,
            source_type=EvidenceSource.SourceType.REPORT,
        )

    def test_collects_relevant_sources_with_full_provenance(self):
        source = self.add_source(
            1,
            "https://example.org/water",
            source_date=date(2026, 1, 2),
        )
        unrelated = self.add_source(2, "https://example.org/other", excerpt="Rail network upgrade.")
        evidence = collect_research_evidence(self.problem)
        self.assertEqual([item["id"] for item in evidence.sources], [str(source.pk), str(unrelated.pk)])
        record = evidence.sources[0]
        self.assertEqual(record["source_url"], source.source_url)
        self.assertEqual(record["canonical_url"], source.canonical_url)
        self.assertEqual(record["publisher"], "Public agency")
        self.assertEqual(record["publication_date"], "2026-01-02")
        self.assertEqual(record["retrieved_at"], source.retrieved_at.isoformat())
        self.assertEqual(record["relevant_excerpt"], source.relevant_excerpt)
        self.assertEqual(record["source_type"], "report")

    @patch("backend.workspaces.services.research.generate_json")
    def test_full_source_excerpt_is_snapshotted_but_model_context_is_bounded(self, generate):
        excerpt = "UNIQUEWORD" * 180
        source = self.add_source(1, "https://example.org/long", excerpt=excerpt)
        generate.return_value = valid_synthesis(str(source.pk))
        result = synthesize_research(self.problem)
        self.assertEqual(result["evidence"][0]["relevant_excerpt"], excerpt)
        prompt = generate.call_args.args[0]
        self.assertEqual(prompt.count("UNIQUEWORD"), 120)

    def test_deduplication_uses_stable_ids_and_canonical_urls_only(self):
        records = [
            {"id": "source-1", "canonical_url": "https://example.org/a", "text": "same"},
            {"id": "source-2", "canonical_url": "https://example.org/a", "text": "different"},
            {"id": "source-1", "canonical_url": "https://example.org/b", "text": "same"},
            {"id": "source-3", "canonical_url": "https://example.org/c", "text": "same"},
        ]
        self.assertEqual(
            [item["id"] for item in deduplicate_evidence(records)],
            ["source-1", "source-3"],
        )

    @override_settings(RESEARCH_MAX_SOURCES=1)
    def test_relevant_sources_are_bounded_and_omissions_reported(self):
        relevant = self.add_source(1, "https://example.org/water")
        self.add_source(2, "https://example.org/other", excerpt="Rail network upgrade.")
        evidence = collect_research_evidence(self.problem)
        self.assertEqual([item["id"] for item in evidence.sources], [str(relevant.pk)])
        self.assertEqual(evidence.omitted_count, 1)

    def test_valid_claim_citations_and_conflicting_evidence_are_preserved(self):
        first = self.add_source(1, "https://example.org/first")
        second = self.add_source(2, "https://example.org/second")
        output = valid_synthesis(str(first.pk))
        output["conflicting_information"] = [
            {
                "topic": "Reported service availability",
                "descriptions": [
                    {"summary": "One report says service is limited.", "evidence_source_ids": [str(first.pk)]},
                    {"summary": "Another report reports wider coverage.", "evidence_source_ids": [str(second.pk)]},
                ],
            }
        ]
        result = validate_research_output(
            output,
            [
                {"id": str(first.pk)},
                {"id": str(second.pk)},
            ],
        )
        self.assertEqual(len(result["conflicting_information"][0]["descriptions"]), 2)
        self.assertEqual(
            result["key_claims"][0]["evidence_source_ids"],
            [str(first.pk)],
        )

    def test_supported_claim_without_citations_is_rejected(self):
        output = valid_synthesis(str(self.problem.pk))
        output["key_claims"][0]["evidence_source_ids"] = []
        with self.assertRaisesRegex(ResearchValidationError, "must cite"):
            validate_research_output(output, [{"id": str(self.problem.pk)}])

    def test_fabricated_citations_are_rejected(self):
        output = valid_synthesis("not-supplied")
        with self.assertRaisesRegex(ResearchValidationError, "not present"):
            validate_research_output(output, [{"id": str(self.problem.pk)}])

    def test_empty_evidence_returns_insufficiency_without_calling_model(self):
        with patch("backend.workspaces.services.research.generate_json") as generate:
            result = synthesize_research(self.problem)
        generate.assert_not_called()
        self.assertEqual(result["key_claims"], [])
        self.assertEqual(result["evidence"], [])
        self.assertIn("Insufficient", result["problem_summary"])

    @patch("backend.workspaces.services.research.generate_json")
    def test_synthesis_passes_catalogue_sources_and_validates_model_citations(self, generate):
        source = self.add_source(1, "https://example.org/source")
        generate.return_value = valid_synthesis(str(source.pk))
        result = synthesize_research(self.problem)
        prompt = generate.call_args.args[0]
        self.assertIn(str(source.pk), prompt)
        self.assertIn(source.source_url, prompt)
        self.assertEqual(result["evidence"][0]["id"], str(source.pk))
        self.assertEqual(result["key_claims"][0]["evidence_source_ids"], [str(source.pk)])

    @patch("backend.workspaces.services.research.generate_json")
    def test_malformed_or_unsupported_claim_output_fails_validation(self, generate):
        source = self.add_source(1, "https://example.org/source")
        generate.return_value = {
            **valid_synthesis(str(source.pk)),
            "key_claims": "not a list",
        }
        with self.assertRaises(ResearchValidationError):
            synthesize_research(self.problem)
