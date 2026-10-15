import uuid
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan


def normalize_source_url(value):
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    if scheme != "https" or not hostname:
        raise ValidationError({"source_url": "Enter an absolute source URL."})
    if parts.username or parts.password:
        raise ValidationError({"source_url": "Credentials are not allowed in source URLs."})
    try:
        port = parts.port
    except ValueError as error:
        raise ValidationError({"source_url": "Enter a valid source URL."}) from error
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port and port != 443:
        netloc = f"{netloc}:{port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


class ProblemStatement(models.Model):
    class Difficulty(models.TextChoices):
        UNSPECIFIED = "unspecified", "Unspecified"
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_source_id = models.CharField(max_length=160, unique=True)
    canonical_source_url = models.URLField(max_length=2048, unique=True, null=True, blank=True)
    title = models.CharField(max_length=240)
    description = models.TextField()
    sector = models.CharField(max_length=120, blank=True)
    difficulty = models.CharField(
        max_length=20,
        choices=Difficulty.choices,
        default=Difficulty.UNSPECIFIED,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PUBLISHED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at"), name="problem_status_created_idx"),
            models.Index(fields=("sector",), name="problem_sector_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("title")), 0),
                name="problem_title_not_empty",
            ),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("description")), 0),
                name="problem_description_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(
                    difficulty__in=("unspecified", "beginner", "intermediate", "advanced")
                ),
                name="problem_difficulty_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("published", "archived")),
                name="problem_status_valid",
            ),
        ]

    def clean(self):
        self.title = self.title.strip()
        self.sector = self.sector.strip()
        errors = {}
        if not self.title:
            errors["title"] = "Title must contain at least one character."
        if not self.description.strip():
            errors["description"] = "Description must contain at least one character."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        self.sector = self.sector.strip()
        if self.canonical_source_url:
            self.canonical_source_url = normalize_source_url(self.canonical_source_url)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class EvidenceSource(models.Model):
    class SourceType(models.TextChoices):
        REPORT = "report", "Report"
        ARTICLE = "article", "Article"
        DATASET = "dataset", "Dataset"
        OFFICIAL_RELEASE = "official_release", "Official release"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey(
        ProblemStatement,
        on_delete=models.CASCADE,
        related_name="evidence_sources",
    )
    source_url = models.URLField(max_length=2048)
    canonical_url = models.URLField(max_length=2048, unique=True, editable=False)
    external_source_id = models.CharField(max_length=200, unique=True)
    source_title = models.CharField(max_length=300)
    publisher = models.CharField(max_length=240, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    retrieved_at = models.DateTimeField(auto_now_add=True)
    relevant_excerpt = models.TextField(blank=True, max_length=2000)
    source_type = models.CharField(
        max_length=24,
        choices=SourceType.choices,
        default=SourceType.OTHER,
    )

    class Meta:
        ordering = ("-retrieved_at", "id")
        indexes = [
            models.Index(fields=("problem", "-retrieved_at"), name="evidence_problem_retrieved_idx"),
            models.Index(fields=("problem", "publication_date"), name="evidence_problem_pubdate_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("source_title")), 0),
                name="evidence_title_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(
                    source_type__in=(
                        "report",
                        "article",
                        "dataset",
                        "official_release",
                        "other",
                    )
                ),
                name="evidence_type_valid",
            ),
        ]

    def clean(self):
        self.source_url = self.source_url.strip()
        errors = {}
        try:
            URLValidator(schemes=("https",))(self.source_url)
        except ValidationError as error:
            errors["source_url"] = error.messages
        try:
            self.canonical_url = normalize_source_url(self.source_url)
        except (ValidationError, ValueError) as error:
            errors["source_url"] = getattr(error, "messages", [str(error)])
        self.source_title = self.source_title.strip()
        if not self.source_title:
            errors["source_title"] = "Source title must contain at least one character."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.source_url = self.source_url.strip()
        self.canonical_url = normalize_source_url(self.source_url)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.source_title
