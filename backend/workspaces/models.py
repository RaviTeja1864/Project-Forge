import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan


class ProjectWorkspace(models.Model):
    class Status(models.TextChoices):
        PLANNING = "planning", "Planning"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspaces",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, max_length=2000)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=("owner", "-updated_at"), name="workspace_owner_updated_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("name")), 0),
                name="workspace_name_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("planning", "in_progress", "completed")),
                name="workspace_status_valid",
            ),
        ]

    def __str__(self):
        return self.name


class WorkspaceCollaborator(models.Model):
    workspace = models.ForeignKey(
        ProjectWorkspace,
        on_delete=models.CASCADE,
        related_name="collaborators",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shared_workspaces",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_access_grants_made",
    )
    granted_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("user__email", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user"),
                condition=models.Q(revoked_at__isnull=True),
                name="workspace_collaborator_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "revoked_at"),
                name="collaborator_user_active_idx",
            ),
        ]

    @property
    def is_active(self):
        return self.revoked_at is None


class WorkspaceArtifact(models.Model):
    class Kind(models.TextChoices):
        RESEARCH = "research", "Research synthesis"
        REQUIREMENTS = "requirements", "Project requirements"
        TECHNOLOGY = "technology", "Technology comparison"
        DESIGN = "design", "System design"
        SPECIFICATION = "specification", "Unified engineering specification"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        ProjectWorkspace,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    content = models.JSONField()
    source_snapshot = models.JSONField(default=list, blank=True)
    source_problem_id = models.UUIDField(null=True, blank=True)
    input_artifact_ids = models.JSONField(default=list, blank=True)
    version_number = models.PositiveIntegerField(default=1)
    lineage_root = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="lineage_versions",
    )
    revision_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workspace_artifact_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "id")
        indexes = [
            models.Index(fields=("workspace", "kind", "-updated_at"), name="artifact_workspace_kind_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("lineage_root", "version_number"),
                name="artifact_lineage_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version_number__gte=1),
                name="artifact_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    kind__in=(
                        "research",
                        "requirements",
                        "technology",
                        "design",
                        "specification",
                    )
                ),
                name="workspace_artifact_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("draft", "approved")),
                name="workspace_artifact_status_valid",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.workspace}"

    def save(self, *args, **kwargs):
        if self._state.adding and self.lineage_root_id is None:
            self.lineage_root_id = self.pk
        super().save(*args, **kwargs)


class ImplementationTask(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        COMPLETED = "completed", "Completed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    workspace = models.ForeignKey(
        ProjectWorkspace,
        on_delete=models.CASCADE,
        related_name="implementation_tasks",
    )
    source_requirements = models.ForeignKey(
        WorkspaceArtifact,
        on_delete=models.RESTRICT,
        related_name="implementation_tasks",
    )
    source_requirement_id = models.CharField(max_length=32)
    acceptance_criteria_ids = models.JSONField(default=list, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=4000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    dependencies = models.ManyToManyField("self", symmetrical=False, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="implementation_tasks_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("source_requirements", "source_requirement_id"),
                name="implementation_task_requirement_unique",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("todo", "in_progress", "blocked", "completed")),
                name="implementation_task_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(priority__in=("low", "medium", "high")),
                name="implementation_task_priority_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("workspace", "status", "created_at"),
                name="impl_task_workspace_status_idx",
            ),
        ]

    def __str__(self):
        return self.title


class ImplementationEvidence(models.Model):
    class EvidenceType(models.TextChoices):
        TEST_RESULT = "test_result", "Test result"
        TEST_DESCRIPTION = "test_description", "Test description"
        REPOSITORY_PATH = "repository_path", "Repository file path"
        API_ENDPOINT = "api_endpoint", "API endpoint"
        MANUAL_REVIEW = "manual_review", "Manual review"
        VERIFICATION_CHECK = "verification_check", "Verification check"

    class Result(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        INCONCLUSIVE = "inconclusive", "Inconclusive"
        ABSENT = "absent", "Absent"

    class ReviewBasis(models.TextChoices):
        SELF_REPORTED = "self_reported", "Self-reported"
        MANUALLY_REVIEWED = "manually_reviewed", "Manually reviewed"

    workspace = models.ForeignKey(
        ProjectWorkspace,
        on_delete=models.CASCADE,
        related_name="implementation_evidence",
    )
    requirements_artifact = models.ForeignKey(
        WorkspaceArtifact,
        on_delete=models.RESTRICT,
        related_name="implementation_evidence",
    )
    requirement_id = models.CharField(max_length=32)
    acceptance_criterion_id = models.CharField(max_length=32, blank=True)
    task = models.ForeignKey(
        ImplementationTask,
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="evidence",
    )
    evidence_type = models.CharField(max_length=24, choices=EvidenceType.choices)
    description = models.TextField(max_length=4000)
    source_reference = models.CharField(max_length=1000, blank=True)
    result = models.CharField(max_length=16, choices=Result.choices)
    review_basis = models.CharField(max_length=20, choices=ReviewBasis.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="implementation_evidence_created",
    )
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="corrections",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(
                fields=("workspace", "requirements_artifact", "requirement_id"),
                name="impl_evidence_req_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("supersedes",),
                condition=Q(supersedes__isnull=False),
                name="implementation_evidence_single_correction",
            ),
        ]


class RequirementVerification(models.Model):
    class Status(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        PARTIALLY_IMPLEMENTED = "partially_implemented", "Partially implemented"
        VERIFIED = "verified", "Verified"
        MISSING = "missing", "Missing"

    workspace = models.ForeignKey(
        ProjectWorkspace,
        on_delete=models.CASCADE,
        related_name="requirement_verifications",
    )
    requirements_artifact = models.ForeignKey(
        WorkspaceArtifact,
        on_delete=models.RESTRICT,
        related_name="requirement_verifications",
    )
    requirement_id = models.CharField(max_length=32)
    status = models.CharField(max_length=24, choices=Status.choices)
    rationale = models.TextField(max_length=2000)
    evidence_ids = models.JSONField(default=list, blank=True)
    criterion_results = models.JSONField(default=list, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="requirement_verifications_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("workspace", "requirements_artifact", "requirement_id", "-created_at"),
                name="req_verification_history_idx",
            ),
        ]
