from django.contrib.auth import get_user_model
from rest_framework import serializers

from backend.workspaces.models import (
    ImplementationEvidence,
    ImplementationTask,
    ProjectWorkspace,
    WorkspaceArtifact,
    WorkspaceCollaborator,
)
from backend.workspaces.services.planning import (
    criteria_for_requirement,
    dependencies_create_cycle,
    is_valid_status_transition,
)
from backend.workspaces.services.research import validate_research_output
from backend.workspaces.services.validation import (
    ArtifactValidationError,
    validate_design,
    validate_requirements,
    validate_technology_comparison,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    access_role = serializers.SerializerMethodField()

    class Meta:
        model = ProjectWorkspace
        fields = (
            "id",
            "name",
            "description",
            "status",
            "created_at",
            "updated_at",
            "access_role",
        )
        read_only_fields = ("id", "created_at", "updated_at", "access_role")

    def get_access_role(self, workspace):
        request = self.context.get("request")
        if request is None:
            return "owner"
        return "owner" if workspace.owner_id == request.user.pk else "collaborator"

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Name must contain at least one character.")
        return name

    def validate_description(self, value):
        return value.strip()


class WorkspaceArtifactSerializer(serializers.ModelSerializer):
    lineage_root_id = serializers.UUIDField(read_only=True)
    revision_of_id = serializers.UUIDField(read_only=True, allow_null=True)
    author_id = serializers.IntegerField(read_only=True, allow_null=True)
    is_outdated = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceArtifact
        fields = (
            "id",
            "kind",
            "status",
            "version_number",
            "lineage_root_id",
            "revision_of_id",
            "author_id",
            "is_outdated",
            "content",
            "source_snapshot",
            "source_problem_id",
            "input_artifact_ids",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "kind",
            "version_number",
            "lineage_root_id",
            "revision_of_id",
            "author_id",
            "source_snapshot",
            "source_problem_id",
            "input_artifact_ids",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        artifact = self.instance
        if artifact is None:
            raise serializers.ValidationError("Artifacts are created by the generation workflow.")
        if artifact.lineage_versions.filter(
            version_number__gt=artifact.version_number
        ).exists():
            raise serializers.ValidationError(
                "Historical versions are read-only; create a revision instead."
            )
        if artifact.status == WorkspaceArtifact.Status.APPROVED:
            raise serializers.ValidationError("Approved artifacts are immutable; create a revision.")
        if artifact.kind == WorkspaceArtifact.Kind.SPECIFICATION:
            if "content" in attrs:
                raise serializers.ValidationError(
                    {"content": "Specification snapshots are immutable; generate a new snapshot."}
                )
            next_status = attrs.get("status", artifact.status)
            if next_status not in (
                WorkspaceArtifact.Status.DRAFT,
                WorkspaceArtifact.Status.APPROVED,
            ):
                raise serializers.ValidationError({"status": "Choose draft or approved."})
            return attrs
        next_status = attrs.get("status", artifact.status)
        if next_status not in (WorkspaceArtifact.Status.DRAFT, WorkspaceArtifact.Status.APPROVED):
            raise serializers.ValidationError({"status": "Choose draft or approved."})
        if artifact.status == WorkspaceArtifact.Status.APPROVED and next_status != artifact.status:
            raise serializers.ValidationError({"status": "Approved artifacts cannot be changed."})

        content = attrs.get("content", artifact.content)
        try:
            attrs["content"] = self.normalize_artifact_content(artifact, content)
        except ArtifactValidationError as error:
            raise serializers.ValidationError({"content": error.message}) from error
        return attrs

    @staticmethod
    def normalize_artifact_content(artifact, content):
        if artifact.kind == WorkspaceArtifact.Kind.SPECIFICATION:
            if not isinstance(content, dict) or content.get("specification_status") not in (
                "review_required",
                "composed_from_approved_artifacts",
            ):
                raise ArtifactValidationError("The specification snapshot is invalid.")
            return content
        if artifact.kind == WorkspaceArtifact.Kind.RESEARCH:
            return validate_research_output(content, artifact.source_snapshot)
        if artifact.kind == WorkspaceArtifact.Kind.REQUIREMENTS:
            return validate_requirements(
                content, {item["id"] for item in artifact.source_snapshot}
            )
        if artifact.kind == WorkspaceArtifact.Kind.TECHNOLOGY:
            options = content.get("options", []) if isinstance(content, dict) else []
            names = [option.get("name") for option in options if isinstance(option, dict)]
            result = validate_technology_comparison(
                content, {item["id"] for item in artifact.source_snapshot}, names
            )
            requirements_artifact = artifact.workspace.artifacts.filter(
                id__in=artifact.input_artifact_ids,
                kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            ).first()
            if requirements_artifact is None:
                raise ArtifactValidationError("The requirements comparison input is unavailable.")
            requirement_ids = {
                item["id"]
                for field in ("functional_requirements", "non_functional_requirements")
                for item in requirements_artifact.content[field]
            }
            if any(
                rating["requirement_id"] not in requirement_ids
                for option in result["options"]
                for rating in option["compatibility"]
            ):
                raise ArtifactValidationError(
                    "Technology compatibility refers to a missing requirement."
                )
            return result
        if artifact.kind == WorkspaceArtifact.Kind.DESIGN:
            requirements_artifact = artifact.workspace.artifacts.filter(
                id__in=artifact.input_artifact_ids,
                kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            ).first()
            if requirements_artifact is None:
                raise ArtifactValidationError("The approved requirements input is unavailable.")
            technology_artifact = artifact.workspace.artifacts.filter(
                id__in=artifact.input_artifact_ids,
                kind=WorkspaceArtifact.Kind.TECHNOLOGY,
            ).first()
            if technology_artifact is None:
                raise ArtifactValidationError("The approved technology input is unavailable.")
            requirement_ids = {
                item["id"]
                for field in ("functional_requirements", "non_functional_requirements")
                for item in requirements_artifact.content[field]
            }
            return validate_design(
                content,
                requirement_ids,
                {item["id"] for item in artifact.source_snapshot},
                recommended_technology=technology_artifact.content["recommendation"]["option"],
            )
        raise ArtifactValidationError("Unknown artifact type.")

    def get_is_outdated(self, artifact):
        from backend.workspaces.services.specification import specification_is_outdated

        return specification_is_outdated(artifact)


class ResearchGenerationInputSerializer(serializers.Serializer):
    problem_id = serializers.UUIDField()


class TechnologyGenerationInputSerializer(serializers.Serializer):
    options = serializers.ListField(
        child=serializers.CharField(max_length=120, allow_blank=False),
        min_length=2,
        max_length=8,
    )


class ArtifactVersionCompareQuerySerializer(serializers.Serializer):
    left_version = serializers.UUIDField()
    right_version = serializers.UUIDField()


class WorkspaceCollaboratorSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    granted_by_email = serializers.EmailField(source="granted_by.email", read_only=True)
    access_status = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceCollaborator
        fields = ("id", "email", "granted_by_email", "granted_at", "revoked_at", "access_status")
        read_only_fields = fields

    def get_access_status(self, grant):
        return "active" if grant.is_active else "revoked"


class WorkspaceCollaboratorGrantSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)

    def validate_email(self, value):
        email = value.strip().lower()
        request = self.context["request"]
        if email == request.user.email.lower():
            raise serializers.ValidationError("You already own this workspace.")
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            raise serializers.ValidationError("No eligible account is available for that address.")
        self.context["target_user"] = user
        return email


class ImplementationTaskSerializer(serializers.ModelSerializer):
    source_requirements_artifact_id = serializers.UUIDField(
        source="source_requirements_id",
        required=False,
    )
    source_requirements_version = serializers.IntegerField(
        source="source_requirements.version_number",
        read_only=True,
    )
    dependency_ids = serializers.SerializerMethodField()
    dependencies = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        write_only=True,
        required=False,
    )
    is_outdated = serializers.SerializerMethodField()

    class Meta:
        model = ImplementationTask
        fields = (
            "id",
            "source_requirements_artifact_id",
            "source_requirements_version",
            "source_requirement_id",
            "acceptance_criteria_ids",
            "title",
            "description",
            "status",
            "priority",
            "dependency_ids",
            "dependencies",
            "is_outdated",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "source_requirements_version",
            "acceptance_criteria_ids",
            "dependency_ids",
            "is_outdated",
            "created_at",
            "updated_at",
        )

    def get_dependency_ids(self, task):
        return list(task.dependencies.values_list("pk", flat=True))

    def get_is_outdated(self, task):
        from backend.workspaces.services.planning import task_is_outdated

        return task_is_outdated(task)

    def validate(self, attrs):
        task = self.instance
        if task is None:
            workspace = self.context["workspace"]
            artifact_id = attrs.get("source_requirements_id")
            requirement_id = attrs.get("source_requirement_id")
            if not artifact_id or not requirement_id:
                raise serializers.ValidationError(
                    "A source requirements artifact and requirement ID are required."
                )
            artifact = WorkspaceArtifact.objects.filter(
                pk=artifact_id,
                workspace=workspace,
                kind=WorkspaceArtifact.Kind.REQUIREMENTS,
                status=WorkspaceArtifact.Status.APPROVED,
            ).first()
            if artifact is None:
                raise serializers.ValidationError(
                    {"source_requirements_artifact_id": "Choose an approved requirements version in this workspace."}
                )
            requirement = next(
                (
                    item
                    for field in ("functional_requirements", "non_functional_requirements")
                    for item in artifact.content.get(field, [])
                    if item.get("id") == requirement_id
                ),
                None,
            )
            if requirement is None:
                raise serializers.ValidationError(
                    {"source_requirement_id": "The requirement does not exist in the selected artifact version."}
                )
            attrs["acceptance_criteria_ids"] = [
                item["id"] for item in criteria_for_requirement(artifact, requirement_id)
            ]
            attrs["workspace"] = workspace
            attrs["source_requirements"] = artifact
        elif "source_requirements_id" in attrs or "source_requirement_id" in attrs:
            raise serializers.ValidationError(
                "Task source requirement provenance cannot be changed after creation."
            )

        next_status = attrs.get("status", task.status if task else ImplementationTask.Status.TODO)
        if task is None and next_status != ImplementationTask.Status.TODO:
            raise serializers.ValidationError(
                {"status": "New tasks must start in the to-do state."}
            )
        if task and not is_valid_status_transition(task.status, next_status):
            raise serializers.ValidationError(
                {"status": f"Cannot change task status from {task.status} to {next_status}."}
            )

        dependency_ids = attrs.get("dependencies")
        if dependency_ids is not None:
            if len(dependency_ids) != len(set(dependency_ids)):
                raise serializers.ValidationError(
                    {"dependencies": "A dependency may be listed only once."}
                )
            workspace = task.workspace if task else self.context["workspace"]
            dependencies = list(
                ImplementationTask.objects.filter(
                    workspace=workspace,
                    pk__in=dependency_ids,
                )
            )
            if len(dependencies) != len(dependency_ids):
                raise serializers.ValidationError(
                    {"dependencies": "Every dependency must belong to this workspace."}
                )
            if task and dependencies_create_cycle(task, dependencies):
                raise serializers.ValidationError(
                    {"dependencies": "Dependencies cannot create a cycle."}
                )
            attrs["resolved_dependencies"] = dependencies
        return attrs

    def create(self, validated_data):
        dependencies = validated_data.pop("resolved_dependencies", [])
        validated_data.pop("dependencies", None)
        task = ImplementationTask.objects.create(
            created_by=self.context["request"].user,
            **validated_data,
        )
        if dependencies:
            task.dependencies.set(dependencies)
        return task

    def update(self, instance, validated_data):
        dependencies = validated_data.pop("resolved_dependencies", None)
        validated_data.pop("dependencies", None)
        task = super().update(instance, validated_data)
        if dependencies is not None:
            task.dependencies.set(dependencies)
        return task


class ImplementationEvidenceSerializer(serializers.ModelSerializer):
    task_id = serializers.IntegerField(required=False, allow_null=True)
    supersedes_id = serializers.IntegerField(
        required=False,
        allow_null=True,
    )
    author_id = serializers.IntegerField(read_only=True, allow_null=True)
    trust_label = serializers.SerializerMethodField()

    class Meta:
        model = ImplementationEvidence
        fields = (
            "id",
            "requirement_id",
            "acceptance_criterion_id",
            "task_id",
            "evidence_type",
            "description",
            "source_reference",
            "result",
            "review_basis",
            "trust_label",
            "supersedes_id",
            "author_id",
            "created_at",
        )
        read_only_fields = (
            "id",
            "trust_label",
            "author_id",
            "created_at",
        )

    def get_trust_label(self, evidence):
        return (
            "self-reported claim"
            if evidence.review_basis == ImplementationEvidence.ReviewBasis.SELF_REPORTED
            else "recorded as manually reviewed; not an automated verification"
        )

    def validate(self, attrs):
        requirements = self.context["requirements"]
        requirement_id = attrs.get("requirement_id", self.context.get("requirement_id"))
        if requirement_id != self.context.get("requirement_id"):
            raise serializers.ValidationError(
                {"requirement_id": "Evidence must match the requirement in this route."}
            )
        exists = any(
            item.get("id") == requirement_id
            for field in ("functional_requirements", "non_functional_requirements")
            for item in requirements.content.get(field, [])
        )
        if not exists:
            raise serializers.ValidationError(
                {"requirement_id": "The requirement is not present in this artifact version."}
            )
        criterion_id = attrs.get("acceptance_criterion_id", "")
        criterion_ids = {
            item["id"]
            for item in criteria_for_requirement(requirements, requirement_id)
        }
        if criterion_id and criterion_id not in criterion_ids:
            raise serializers.ValidationError(
                {"acceptance_criterion_id": "The acceptance criterion is not linked to this requirement."}
            )
        task_id = attrs.get("task_id")
        task = None
        if task_id is not None:
            task = ImplementationTask.objects.filter(
                pk=task_id,
                workspace=requirements.workspace,
                source_requirements=requirements,
                source_requirement_id=requirement_id,
            ).first()
            if task is None:
                raise serializers.ValidationError(
                    {"task_id": "The task must match this requirement and artifact version."}
                )
        attrs["task"] = task
        supersedes_id = attrs.pop("supersedes_id", None)
        if supersedes_id is not None:
            previous = ImplementationEvidence.objects.filter(
                pk=supersedes_id,
                workspace=requirements.workspace,
                requirements_artifact=requirements,
                requirement_id=requirement_id,
                acceptance_criterion_id=criterion_id,
            ).first()
            if previous is None:
                raise serializers.ValidationError(
                    {"supersedes_id": "The evidence to correct must match this requirement and criterion."}
                )
            if previous.corrections.exists():
                raise serializers.ValidationError(
                    {"supersedes_id": "This evidence has already been corrected."}
                )
            if previous.task_id is not None and task_id is None:
                task = previous.task
            elif previous.task_id != (task.pk if task else None):
                raise serializers.ValidationError(
                    {"task_id": "A correction must keep the original task association."}
                )
            attrs["supersedes"] = previous
            attrs["task"] = task
        attrs["workspace"] = requirements.workspace
        attrs["requirements_artifact"] = requirements
        attrs["requirement_id"] = requirement_id
        return attrs

    def create(self, validated_data):
        return ImplementationEvidence.objects.create(
            author=self.context["request"].user,
            **validated_data,
        )


class TaskPlanInputSerializer(serializers.Serializer):
    requirements_artifact_id = serializers.UUIDField()
