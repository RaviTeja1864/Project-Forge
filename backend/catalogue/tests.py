import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.test.utils import captured_stderr
from django.utils import timezone
from rest_framework.test import APIClient

from backend.catalogue.models import (
    EvidenceSource,
    ProblemStatement,
    normalize_source_url,
)
from backend.catalogue.services.reliefweb import (
    SourceIngestionError,
    fetch_reports,
    ingest_reliefweb_reports,
)
from backend.catalogue.services.similarity import (
    find_similar_problems,
    normalize_text,
    score_problems,
)

User = get_user_model()


def reliefweb_record(
    *,
    report_id="12345",
    url="https://reliefweb.int/report/example",
    body="<p>Residents need access to safe drinking water.</p>",
    date_original="2026-02-14",
):
    return {
        "id": report_id,
        "fields": {
            "title": "Water access in Example",
            "url": url,
            "date": {"original": date_original} if date_original else {},
            "body-html": body,
            "source": [{"name": "Example Ministry"}],
            "theme": [{"name": "Water Sanitation Hygiene"}, {"name": "Coordination"}],
        },
    }


class CatalogueModelTests(TestCase):
    def setUp(self):
        self.problem = ProblemStatement.objects.create(
            external_source_id="test:problem:1",
            title="  Water access  ",
            description="People need reliable drinking water.",
        )

    def test_problem_uses_uuid_and_unclassified_difficulty_is_explicit(self):
        self.assertEqual(self.problem.pk.version, 4)
        self.problem.full_clean()
        self.assertEqual(self.problem.title, "Water access")
        self.assertEqual(self.problem.difficulty, ProblemStatement.Difficulty.UNSPECIFIED)

    def test_problem_validation_requires_nonblank_title_and_description(self):
        problem = ProblemStatement(
            external_source_id="test:problem:invalid",
            title="   ",
            description="   ",
        )
        with self.assertRaises(ValidationError) as error:
            problem.full_clean()
        self.assertIn("title", error.exception.message_dict)
        self.assertIn("description", error.exception.message_dict)

    def test_source_preserves_url_and_stores_normalized_duplicate_key(self):
        source = EvidenceSource.objects.create(
            problem=self.problem,
            external_source_id="test:source:1",
            source_url="HTTPS://Example.org/reports/123/#contents",
            source_title=" Example report ",
            publisher="",
            publication_date=None,
            relevant_excerpt="An excerpt copied from the source.",
            source_type=EvidenceSource.SourceType.REPORT,
        )
        self.assertEqual(source.source_url, "HTTPS://Example.org/reports/123/#contents")
        self.assertEqual(source.canonical_url, "https://example.org/reports/123")
        self.assertEqual(source.publisher, "")
        self.assertIsNone(source.publication_date)
        self.assertIsNotNone(source.retrieved_at)

    def test_normalized_url_rejects_credentials_and_relative_urls(self):
        with self.assertRaises(ValidationError):
            normalize_source_url("https://user:password@example.org/source")
        with self.assertRaises(ValidationError):
            normalize_source_url("/relative/path")
        with self.assertRaises(ValidationError):
            normalize_source_url("ftp://example.org/source")
        with self.assertRaises(ValidationError):
            normalize_source_url("https://example.org:not-a-port/source")

    def test_normalized_url_preserves_ipv6_authority(self):
        self.assertEqual(
            normalize_source_url("https://[2001:db8::1]:443/report/"),
            "https://[2001:db8::1]/report",
        )

    def test_database_constraints_reject_duplicate_urls_and_invalid_status(self):
        EvidenceSource.objects.create(
            problem=self.problem,
            external_source_id="test:source:1",
            source_url="https://example.org/report",
            source_title="Report",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            EvidenceSource.objects.create(
                problem=self.problem,
                external_source_id="test:source:2",
                source_url="https://EXAMPLE.org/report/#section",
                source_title="Duplicate URL",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            EvidenceSource.objects.create(
                problem=self.problem,
                external_source_id="test:source:1",
                source_url="https://example.org/another-report",
                source_title="Duplicate identifier",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProblemStatement.objects.create(
                external_source_id="test:problem:bad",
                title="Invalid difficulty",
                description="A description",
                difficulty="invented",
            )

    def test_source_validation_rejects_http_and_empty_titles(self):
        source = EvidenceSource(
            problem=self.problem,
            external_source_id="test:source:invalid",
            source_url="http://example.org/report",
            source_title="  ",
        )
        with self.assertRaises(ValidationError) as error:
            source.full_clean()
        self.assertIn("source_url", error.exception.message_dict)
        self.assertIn("source_title", error.exception.message_dict)


class CatalogueApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="reader@example.com", password="long-test-password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def create_problem(self, number, **overrides):
        fields = {
            "external_source_id": f"test:problem:{number}",
            "title": f"Problem {number}",
            "description": "Description taken from a source.",
            "sector": "Water Sanitation Hygiene",
        }
        fields.update(overrides)
        return ProblemStatement.objects.create(
            **fields,
        )

    def test_lists_published_problems_and_real_source_count(self):
        problem = self.create_problem(1)
        EvidenceSource.objects.create(
            problem=problem,
            external_source_id="test:source:1",
            source_url="https://example.org/report",
            source_title="Original report",
        )
        ProblemStatement.objects.create(
            external_source_id="test:problem:archived",
            title="Archived problem",
            description="An archived description.",
            status=ProblemStatement.Status.ARCHIVED,
        )
        response = self.client.get("/api/problems/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["evidence_source_count"], 1)
        self.assertEqual(response.data["results"][0]["sector"], "Water Sanitation Hygiene")

    def test_problem_and_nested_sources_are_read_only(self):
        problem = self.create_problem(1)
        source = EvidenceSource.objects.create(
            problem=problem,
            external_source_id="test:source:1",
            source_url="https://example.org/report",
            source_title="Original report",
        )
        detail = self.client.get(f"/api/problems/{problem.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["evidence_sources"][0]["id"], str(source.pk))
        listing = self.client.get(f"/api/problems/{problem.pk}/sources/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["results"][0]["source_url"], "https://example.org/report")
        self.assertEqual(
            self.client.get(
                f"/api/problems/{problem.pk}/sources/{source.pk}/"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/problems/{problem.pk}/sources/",
                {"source_url": "https://example.org/not-allowed"},
                format="json",
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(
                "/api/problems/",
                {"title": "User generated", "description": "Not allowed"},
                format="json",
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/problems/{problem.pk}/",
                {"title": "Changed"},
                format="json",
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.delete(f"/api/problems/{problem.pk}/").status_code,
            405,
        )

    def test_source_detail_is_nested_under_its_own_problem(self):
        problem = self.create_problem(1)
        other_problem = self.create_problem(2)
        source = EvidenceSource.objects.create(
            problem=problem,
            external_source_id="test:source:1",
            source_url="https://example.org/report",
            source_title="Original report",
        )
        response = self.client.get(
            f"/api/problems/{other_problem.pk}/sources/{source.pk}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_problem_catalogue_is_authenticated(self):
        self.client.force_authenticate(user=None)
        problem = self.create_problem(1)
        for url in (
            "/api/problems/",
            f"/api/problems/{problem.pk}/",
            f"/api/problems/{problem.pk}/sources/",
            f"/api/problems/{problem.pk}/similar/",
        ):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_problem_list_is_paginated(self):
        for number in range(13):
            self.create_problem(number)
        response = self.client.get("/api/problems/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 13)
        self.assertEqual(len(response.data["results"]), 12)
        self.assertIsNotNone(response.data["next"])

    def test_search_combines_keyword_sector_difficulty_and_inclusive_source_dates(self):
        matching = self.create_problem(
            1,
            title="Rural water resilience",
            difficulty=ProblemStatement.Difficulty.BEGINNER,
        )
        out_of_range = self.create_problem(
            2,
            title="Rural water resilience outside date range",
            difficulty=ProblemStatement.Difficulty.BEGINNER,
        )
        EvidenceSource.objects.create(
            problem=matching,
            external_source_id="test:search:match",
            source_url="https://example.org/search-match",
            source_title="Regional assessment",
            publisher="Community Water Agency",
            publication_date=date(2026, 2, 14),
        )
        EvidenceSource.objects.create(
            problem=out_of_range,
            external_source_id="test:search:outside",
            source_url="https://example.org/search-outside",
            source_title="Regional assessment",
            publisher="Community Water Agency",
            publication_date=date(2026, 2, 15),
        )
        response = self.client.get(
            "/api/problems/?q=COMMUNITY%20WATER%20AGENCY"
            "&sector=Water%20Sanitation%20Hygiene&difficulty=beginner"
            "&source_date_from=2026-02-14&source_date_to=2026-02-14"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(matching.pk))

    def test_keyword_search_is_case_insensitive_across_problem_and_source_fields(self):
        description_match = self.create_problem(
            1,
            title="A community challenge",
            description="Residents report CLEAN WATER shortages.",
        )
        metadata_match = self.create_problem(2, title="A separate challenge")
        EvidenceSource.objects.create(
            problem=metadata_match,
            external_source_id="test:search:metadata",
            source_url="https://example.org/search-metadata",
            source_title="Annual findings",
            publisher="Regional HEALTH Office",
        )
        response = self.client.get("/api/problems/?q=clean%20water")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(description_match.pk))
        source_response = self.client.get("/api/problems/?q=REGIONAL%20health")
        self.assertEqual(source_response.data["count"], 1)
        self.assertEqual(source_response.data["results"][0]["id"], str(metadata_match.pk))

    def test_empty_query_is_ignored_and_filters_with_no_matches_are_empty(self):
        self.create_problem(1)
        response = self.client.get("/api/problems/?q=%20%20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        no_matches = self.client.get("/api/problems/?sector=No%20such%20sector")
        self.assertEqual(no_matches.status_code, 200)
        self.assertEqual(no_matches.data["results"], [])

    def test_invalid_search_parameters_return_validation_errors(self):
        self.create_problem(1)
        invalid_queries = (
            "/api/problems/?difficulty=expert",
            "/api/problems/?source_date_from=not-a-date",
            "/api/problems/?source_date_from=2026-W10-1",
            "/api/problems/?source_date_from=2026-03-02&source_date_to=2026-03-01",
            "/api/problems/?ordering=title%3Bdrop",
            f"/api/problems/?q={'x' * 201}",
        )
        for url in invalid_queries:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 400)

    def test_ordering_is_allowlisted_and_tie_breaking_is_stable(self):
        self.create_problem(1, title="Zulu")
        alpha = self.create_problem(2, title="Alpha")
        response = self.client.get("/api/problems/?ordering=title")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["id"], str(alpha.pk))
        self.assertEqual(
            self.client.get("/api/problems/?ordering=external_source_id").status_code,
            400,
        )

    def test_detail_preserves_source_metadata_and_empty_evidence(self):
        problem = self.create_problem(1)
        response = self.client.get(f"/api/problems/{problem.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["evidence_sources"], [])

        source = EvidenceSource.objects.create(
            problem=problem,
            external_source_id="test:source:metadata",
            source_url="https://example.org/metadata",
            source_title="Evidence report",
            publisher="",
            publication_date=None,
            relevant_excerpt="Quoted material from the publication.",
            source_type=EvidenceSource.SourceType.REPORT,
        )
        detail = self.client.get(f"/api/problems/{problem.pk}/")
        serialized = detail.data["evidence_sources"][0]
        self.assertEqual(serialized["id"], str(source.pk))
        self.assertIsNone(serialized["publication_date"])
        self.assertEqual(serialized["publisher"], "")
        self.assertEqual(serialized["source_url"], "https://example.org/metadata")
        self.assertEqual(serialized["relevant_excerpt"], "Quoted material from the publication.")
        self.assertEqual(serialized["source_type"], "report")

    def test_evidence_sources_have_stable_timestamp_and_uuid_order(self):
        problem = self.create_problem(1)
        later_uuid = EvidenceSource.objects.create(
            id=uuid.UUID(int=2),
            problem=problem,
            external_source_id="test:source:later-uuid",
            source_url="https://example.org/order-2",
            source_title="Later UUID",
        )
        earlier_uuid = EvidenceSource.objects.create(
            id=uuid.UUID(int=1),
            problem=problem,
            external_source_id="test:source:earlier-uuid",
            source_url="https://example.org/order-1",
            source_title="Earlier UUID",
        )
        EvidenceSource.objects.filter(pk__in=(later_uuid.pk, earlier_uuid.pk)).update(
            retrieved_at=timezone.now()
        )
        expected = [str(earlier_uuid.pk), str(later_uuid.pk)]
        detail = self.client.get(f"/api/problems/{problem.pk}/")
        self.assertEqual(
            [item["id"] for item in detail.data["evidence_sources"]],
            expected,
        )
        listing = self.client.get(f"/api/problems/{problem.pk}/sources/")
        self.assertEqual(
            [item["id"] for item in listing.data["results"]],
            expected,
        )

    def test_invalid_problem_or_source_identifiers_return_not_found(self):
        self.assertEqual(self.client.get("/api/problems/not-a-uuid/").status_code, 404)
        problem = self.create_problem(1)
        self.assertEqual(
            self.client.get(
                f"/api/problems/{problem.pk}/sources/{uuid.UUID(int=0)}/"
            ).status_code,
            404,
        )

    def test_similar_problem_endpoint_returns_ranked_read_only_candidates(self):
        origin = self.create_problem(
            1,
            title="Clean drinking water access",
            description="Rural families need safe water services.",
        )
        exact = self.create_problem(
            2,
            title="CLEAN drinking-water access!",
            description="Different detail from a second source.",
        )
        response = self.client.get(f"/api/problems/{origin.pk}/similar/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["problem"]["id"], str(exact.pk))
        self.assertEqual(response.data["results"][0]["problem"]["evidence_source_count"], 0)
        self.assertEqual(response.data["results"][0]["similarity_score"], 1.0)
        self.assertIn(
            "Normalized titles match exactly",
            response.data["results"][0]["matching_signals"],
        )

    def test_similar_endpoint_is_read_only_and_rejects_unknown_problems(self):
        problem = self.create_problem(1)
        self.assertEqual(
            self.client.post(f"/api/problems/{problem.pk}/similar/").status_code,
            405,
        )
        self.assertEqual(
            self.client.get(f"/api/problems/{uuid.UUID(int=0)}/similar/").status_code,
            404,
        )

    def test_nested_evidence_sources_are_paginated(self):
        problem = self.create_problem(1)
        for number in range(13):
            EvidenceSource.objects.create(
                problem=problem,
                external_source_id=f"test:source:{number}",
                source_url=f"https://example.org/reports/{number}",
                source_title=f"Source report {number}",
            )
        response = self.client.get(f"/api/problems/{problem.pk}/sources/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 13)
        self.assertEqual(len(response.data["results"]), 12)
        self.assertIsNotNone(response.data["next"])


class ProblemSimilarityTests(TestCase):
    def create_problem(self, number, title, description, sector="Water"):
        return ProblemStatement.objects.create(
            external_source_id=f"similarity:problem:{number}",
            title=title,
            description=description,
            sector=sector,
        )

    def test_normalization_handles_unicode_case_whitespace_and_punctuation(self):
        self.assertEqual(normalize_text("  Café—WATER,  access! "), "café water access")
        left = SimpleNamespace(title="CLEAN-drinking water", description="Safe water!")
        right = SimpleNamespace(title="clean drinking water", description="SAFE, water")
        self.assertEqual(score_problems(left, right)[0], 1.0)

    def test_changed_wording_gets_a_text_similarity_score_and_signals(self):
        origin = SimpleNamespace(
            title="Clean drinking water access",
            description="Rural families need safe water services.",
        )
        changed = SimpleNamespace(
            title="Access to safe drinking water",
            description="Families in rural areas need reliable water services.",
        )
        score, signals = score_problems(origin, changed)
        self.assertGreaterEqual(score, 0.35)
        self.assertLess(score, 1.0)
        self.assertTrue(signals)

    def test_empty_text_has_no_match_score_or_signals(self):
        empty = SimpleNamespace(title="", description="")
        self.assertEqual(score_problems(empty, empty), (0.0, ()))

    def test_candidates_exclude_self_other_sectors_and_unrelated_reports(self):
        origin = self.create_problem(
            1,
            "Clean drinking water access",
            "Rural families need safe water services.",
        )
        self.create_problem(
            2,
            "Clean drinking water access",
            "Rural families need safe water services.",
            sector="Transport",
        )
        self.create_problem(3, "Urban road congestion", "Freight routes need new bridges.")
        result = find_similar_problems(origin)
        self.assertEqual(result.threshold, 0.35)
        self.assertEqual(result.candidates, ())

    def test_changed_wording_is_ranked_above_an_unrelated_same_sector_report(self):
        origin = self.create_problem(
            1,
            "Clean drinking water access",
            "Rural families need safe water services.",
        )
        changed = self.create_problem(
            2,
            "Access to safe drinking water",
            "Families in rural areas need reliable water services.",
        )
        self.create_problem(3, "Urban road congestion", "Freight routes need new bridges.")
        result = find_similar_problems(origin)
        self.assertEqual([candidate.problem.pk for candidate in result.candidates], [changed.pk])
        self.assertLess(result.candidates[0].score, 1.0)
        self.assertGreaterEqual(result.candidates[0].score, result.threshold)

    def test_candidates_are_ranked_deterministically_and_self_is_excluded(self):
        origin = self.create_problem(
            1,
            "Clean drinking water access",
            "Rural families need safe water services.",
        )
        lower_id = ProblemStatement.objects.create(
            id=uuid.UUID(int=2),
            external_source_id="similarity:problem:2",
            title="CLEAN drinking-water access!",
            description="Different source description.",
            sector="Water",
        )
        higher_id = ProblemStatement.objects.create(
            id=uuid.UUID(int=3),
            external_source_id="similarity:problem:3",
            title="clean drinking water access",
            description="Another source description.",
            sector="Water",
        )
        result = find_similar_problems(origin)
        self.assertEqual(
            [candidate.problem.pk for candidate in result.candidates],
            [lower_id.pk, higher_id.pk],
        )
        self.assertNotIn(origin.pk, [candidate.problem.pk for candidate in result.candidates])


@override_settings(PROBLEM_SOURCE_HTTP_TIMEOUT=3, RELIEFWEB_APPNAME="approved-test-app")
class ReliefWebIngestionTests(TestCase):
    def test_ingestion_preserves_source_provenance_and_known_publication_date(self):
        result = ingest_reliefweb_reports(records=[reliefweb_record()])
        problem = ProblemStatement.objects.get()
        source = EvidenceSource.objects.get()
        self.assertEqual((result.received, result.created, result.updated, result.skipped), (1, 1, 0, 0))
        self.assertEqual(problem.external_source_id, "reliefweb:reports:12345")
        self.assertEqual(problem.title, "Water access in Example")
        self.assertEqual(
            problem.description,
            "Residents need access to safe drinking water.",
        )
        self.assertEqual(problem.sector, "Water Sanitation Hygiene, Coordination")
        self.assertEqual(problem.difficulty, ProblemStatement.Difficulty.UNSPECIFIED)
        self.assertEqual(source.source_url, "https://reliefweb.int/report/example")
        self.assertEqual(source.publisher, "Example Ministry")
        self.assertEqual(source.publication_date, date(2026, 2, 14))
        self.assertEqual(source.relevant_excerpt, problem.description)
        self.assertEqual(source.source_type, EvidenceSource.SourceType.REPORT)
        self.assertTrue(source.external_source_id.startswith("reliefweb:reports:"))
        self.assertIsNotNone(source.retrieved_at)

    def test_missing_publication_date_and_publisher_remain_unknown(self):
        record = reliefweb_record(date_original=None)
        record["fields"]["source"] = []
        result = ingest_reliefweb_reports(records=[record])
        source = EvidenceSource.objects.get()
        self.assertEqual(result.created, 1)
        self.assertIsNone(source.publication_date)
        self.assertEqual(source.publisher, "")

    def test_ingestion_is_idempotent_and_updates_existing_source(self):
        first = reliefweb_record()
        second = reliefweb_record(body="<p>Updated source content from the report.</p>")
        initial = ingest_reliefweb_reports(records=[first])
        updated = ingest_reliefweb_reports(records=[second])
        self.assertEqual(initial.created, 1)
        self.assertEqual(updated.updated, 1)
        self.assertEqual(ProblemStatement.objects.count(), 1)
        self.assertEqual(EvidenceSource.objects.count(), 1)
        self.assertEqual(
            EvidenceSource.objects.get().relevant_excerpt,
            "Updated source content from the report.",
        )

    def test_ingestion_deduplicates_a_normalized_url_with_a_different_source_id(self):
        first = reliefweb_record(report_id="12345", url="https://reliefweb.int/report/example/")
        second = reliefweb_record(report_id="67890", url="https://RELIEFWEB.int/report/example/#overview")
        self.assertEqual(ingest_reliefweb_reports(records=[first]).created, 1)
        result = ingest_reliefweb_reports(records=[second])
        self.assertEqual(result.created, 0)
        self.assertEqual(result.updated, 1)
        self.assertEqual(ProblemStatement.objects.count(), 1)
        self.assertEqual(EvidenceSource.objects.count(), 1)
        self.assertEqual(
            ProblemStatement.objects.get().external_source_id,
            "reliefweb:reports:67890",
        )

    def test_ingestion_updates_an_existing_identifier_when_its_url_changes(self):
        first = reliefweb_record(url="https://reliefweb.int/report/old")
        second = reliefweb_record(url="https://reliefweb.int/report/updated")
        ingest_reliefweb_reports(records=[first])
        result = ingest_reliefweb_reports(records=[second])
        self.assertEqual(result.updated, 1)
        self.assertEqual(ProblemStatement.objects.count(), 1)
        self.assertEqual(EvidenceSource.objects.count(), 1)
        self.assertEqual(
            EvidenceSource.objects.get().source_url,
            "https://reliefweb.int/report/updated",
        )

    def test_invalid_or_incomplete_source_records_are_reported_not_invented(self):
        missing_description = reliefweb_record(body="<p> </p>")
        missing_title = reliefweb_record()
        missing_title["fields"]["title"] = ""
        result = ingest_reliefweb_reports(records=[missing_description, missing_title])
        self.assertEqual(result.skipped, 2)
        self.assertEqual(len(result.skip_reasons), 2)
        self.assertEqual(ProblemStatement.objects.count(), 0)
        self.assertEqual(EvidenceSource.objects.count(), 0)

    def test_request_uses_documented_endpoint_appname_and_bounded_limit(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps({"data": [reliefweb_record()]}).encode()

        opener = Mock(return_value=Response())
        reports = fetch_reports("approved-name", 5, opener=opener)
        self.assertEqual(len(reports), 1)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.reliefweb.int/v2/reports?appname=approved-name")
        self.assertEqual(request.method, "POST")
        self.assertEqual(opener.call_args.kwargs["timeout"], 3)
        self.assertEqual(json.loads(request.data)["limit"], 5)
        self.assertEqual(json.loads(request.data)["fields"]["include"][0], "id")

    def test_missing_approved_appname_and_invalid_limit_fail_explicitly(self):
        with self.assertRaisesRegex(SourceIngestionError, "pre-approved"):
            fetch_reports("", opener=Mock())
        with self.assertRaisesRegex(SourceIngestionError, "between 1 and"):
            fetch_reports("approved-name", 101, opener=Mock())

    def test_unexpected_response_and_http_errors_are_surfaced(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b'{"unexpected": []}'

        with self.assertRaisesRegex(SourceIngestionError, "unexpected response"):
            fetch_reports("approved-name", opener=Mock(return_value=Response()))

        from urllib.error import HTTPError

        http_error = HTTPError(
            "https://api.reliefweb.int/v2/reports",
            429,
            "Rate limited",
            {},
            None,
        )
        with self.assertRaisesRegex(SourceIngestionError, "HTTP 429"):
            fetch_reports("approved-name", opener=Mock(side_effect=http_error))

    def test_management_command_requires_a_preapproved_appname(self):
        with (
            override_settings(RELIEFWEB_APPNAME=""),
            captured_stderr() as stderr,
            self.assertRaisesRegex(CommandError, "pre-approved"),
        ):
            call_command("ingest_reliefweb")
        self.assertEqual(stderr.getvalue(), "")

    @patch("backend.catalogue.services.reliefweb.urlopen")
    def test_http_and_invalid_json_fail_without_creating_records(self, opener):
        opener.side_effect = OSError("private connection details")
        with self.assertRaisesRegex(SourceIngestionError, "request failed"):
            ingest_reliefweb_reports()
        self.assertEqual(ProblemStatement.objects.count(), 0)

        class InvalidJsonResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b"not-json"

        opener.side_effect = None
        opener.return_value = InvalidJsonResponse()
        with self.assertRaisesRegex(SourceIngestionError, "invalid JSON"):
            ingest_reliefweb_reports()
        self.assertEqual(EvidenceSource.objects.count(), 0)
