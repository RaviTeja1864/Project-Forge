import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from backend.catalogue.models import (
    EvidenceSource,
    ProblemStatement,
    normalize_source_url,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://api.reliefweb.int/v2/reports"
MAX_BATCH_SIZE = 100
MAX_EXCERPT_LENGTH = 2000
MAX_DESCRIPTION_LENGTH = 12000


class SourceIngestionError(Exception):
    pass


@dataclass
class IngestionResult:
    received: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    skip_reasons: list[str] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if self.ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self):
        return " ".join(self.parts)


def extract_text(value):
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    return " ".join(parser.text().split())


def _publication_date(value):
    if isinstance(value, dict):
        value = value.get("date")
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            logger.warning("ReliefWeb report contains an invalid publication date.")
            return None


def _source_publisher(sources):
    if not isinstance(sources, list):
        return ""
    names = []
    for source in sources:
        if isinstance(source, dict):
            name = source.get("name")
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
    return ", ".join(names)[:240]


def _sector(themes):
    if not isinstance(themes, list):
        return ""
    names = []
    for theme in themes:
        if isinstance(theme, dict):
            name = theme.get("name")
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
    return ", ".join(names)[:120]


def fetch_reports(appname, limit=20, *, opener=None):
    if not isinstance(appname, str) or not appname.strip():
        raise SourceIngestionError(
            "Set RELIEFWEB_APPNAME to an app name pre-approved by ReliefWeb."
        )
    if not 1 <= limit <= MAX_BATCH_SIZE:
        raise SourceIngestionError(f"Limit must be between 1 and {MAX_BATCH_SIZE}.")

    url = f"{API_ROOT}?{urlencode({'appname': appname.strip()})}"
    body = {
        "fields": {
            "include": [
                "id",
                "title",
                "url",
                "date.original",
                "body-html",
                "source",
                "theme",
            ]
        },
        "limit": limit,
        "sort": ["date.created:desc"],
        "filter": {"field": "status", "value": "published"},
    }
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"ProjectForge/1.0 ({appname.strip()})",
        },
        method="POST",
    )
    if opener is None:
        opener = urlopen
    try:
        with opener(request, timeout=settings.PROBLEM_SOURCE_HTTP_TIMEOUT) as response:
            if response.status != 200:
                raise SourceIngestionError(
                    f"ReliefWeb returned HTTP {response.status}."
                )
            payload = json.loads(response.read())
    except HTTPError as error:
        raise SourceIngestionError(
            f"ReliefWeb returned HTTP {error.code}."
        ) from error
    except URLError as error:
        raise SourceIngestionError("Could not connect to the ReliefWeb API.") from error
    except (TimeoutError, OSError) as error:
        raise SourceIngestionError("The ReliefWeb API request failed.") from error
    except json.JSONDecodeError as error:
        raise SourceIngestionError("ReliefWeb returned invalid JSON.") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SourceIngestionError("ReliefWeb returned an unexpected response.")
    return payload["data"]


def _report_values(item):
    if not isinstance(item, dict):
        return None, "record is not an object"
    fields = item.get("fields")
    if not isinstance(fields, dict):
        return None, "record has no fields"

    report_id = item.get("id")
    title = fields.get("title")
    source_url = fields.get("url")
    body = extract_text(fields.get("body-html"))
    if report_id is None or not str(report_id).strip():
        return None, "record has no external identifier"
    if not isinstance(title, str) or not title.strip():
        return None, "record has no source title"
    if not isinstance(source_url, str) or not source_url.strip():
        return None, "record has no source URL"
    if not body:
        return None, "record has no description in the retrieved source material"

    try:
        canonical_url = normalize_source_url(source_url)
    except (ValidationError, ValueError):
        return None, "record has an invalid source URL"
    if len(title.strip()) > 240 or len(source_url.strip()) > 2048:
        return None, "record exceeds the supported title or URL length"

    identifier = f"reliefweb:reports:{str(report_id).strip()}"
    return {
        "identifier": identifier[:160],
        "title": title.strip()[:240],
        "description": body[:MAX_DESCRIPTION_LENGTH],
        "sector": _sector(fields.get("theme")),
        "status": ProblemStatement.Status.PUBLISHED,
        "source_url": source_url.strip(),
        "canonical_url": canonical_url,
        "source_title": title.strip()[:300],
        "publisher": _source_publisher(fields.get("source")),
        "publication_date": _publication_date(
            (fields.get("date") or {}).get("original")
            if isinstance(fields.get("date"), dict)
            else None
        ),
        "relevant_excerpt": body[:MAX_EXCERPT_LENGTH],
        "source_identifier": identifier[:200],
    }, None


def ingest_reliefweb_reports(*, appname=None, limit=20, records=None):
    if records is None:
        records = fetch_reports(
            settings.RELIEFWEB_APPNAME if appname is None else appname,
            limit,
        )
    result = IngestionResult(received=len(records))

    for item in records:
        values, skip_reason = _report_values(item)
        if values is None:
            result.skipped += 1
            result.skip_reasons.append(skip_reason)
            continue
        with transaction.atomic():
            problem = ProblemStatement.objects.filter(
                external_source_id=values["identifier"]
            ).first()
            if problem is None:
                problem = ProblemStatement.objects.filter(
                    canonical_source_url=values["canonical_url"]
                ).first()
            created = problem is None
            if created:
                problem = ProblemStatement(
                    external_source_id=values["identifier"],
                    canonical_source_url=values["canonical_url"],
                )
            problem.external_source_id = values["identifier"]
            problem.canonical_source_url = values["canonical_url"]
            problem.title = values["title"]
            problem.description = values["description"]
            problem.sector = values["sector"]
            problem.difficulty = ProblemStatement.Difficulty.UNSPECIFIED
            problem.status = values["status"]
            problem.save()

            source = EvidenceSource.objects.filter(
                external_source_id=values["source_identifier"]
            ).first()
            if source is None:
                source = EvidenceSource.objects.filter(
                    canonical_url=values["canonical_url"]
                ).first()
            source_created = source is None
            if source_created:
                source = EvidenceSource(problem=problem)
            source.problem = problem
            source.external_source_id = values["source_identifier"]
            source.source_url = values["source_url"]
            source.canonical_url = values["canonical_url"]
            source.source_title = values["source_title"]
            source.publisher = values["publisher"]
            source.publication_date = values["publication_date"]
            source.relevant_excerpt = values["relevant_excerpt"]
            source.source_type = EvidenceSource.SourceType.REPORT
            source.retrieved_at = timezone.now()
            source.save()
        if created or source_created:
            result.created += 1
        else:
            result.updated += 1

    return result
