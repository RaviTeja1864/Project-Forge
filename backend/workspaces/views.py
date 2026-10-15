from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.catalogue.models import ProblemStatement
from backend.workspaces.models import (
    ImplementationEvidence,
    ImplementationTask,
    ProjectWorkspace,
    RequirementVerification,
    WorkspaceArtifact,
    WorkspaceCollaborator,
)
from backend.workspaces.serializers import (
    ArtifactVersionCompareQuerySerializer,
    ImplementationEvidenceSerializer,
    ImplementationTaskSerializer,
    ResearchGenerationInputSerializer,
    TaskPlanInputSerializer,
    TechnologyGenerationInputSerializer,
    WorkspaceArtifactSerializer,
    WorkspaceCollaboratorGrantSerializer,
    WorkspaceCollaboratorSerializer,
    WorkspaceSerializer,
)
from backend.workspaces.services.generation import (
    generate_requirements,
    generate_research,
    generate_system_design,
    generate_technology_comparison,
)
from backend.workspaces.services.ollama import OllamaError, model_status
from backend.workspaces.services.planning import (
    generate_tasks,
    requirement_entries,
    requirements_artifact_is_outdated,
)
from backend.workspaces.services.specification import (
    INPUT_KINDS,
    approved_specification_inputs,
    compose_specification,
)
from backend.workspaces.services.specification_export import (
    SpecificationExportError,
    specification_filename,
    specification_markdown,
    specification_pdf,
)
from backend.workspaces.services.validation import ArtifactValidationError
from backend.workspaces.services.verification import (
    current_evidence,
    current_verification_payload,
    evaluate_requirement,
)


class OllamaStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            return Response(model_status())
        except OllamaError as error:
            state = {
                "OllamaConfigurationError": "misconfigured",
                "OllamaTimeoutError": "timeout",
                "OllamaProtocolError": "invalid_response",
                "OllamaModelMissingError": "model_missing",
            }.get(type(error).__name__, "offline")
            return Response(
                {
                    "available": False,
                    "model": settings.OLLAMA_MODEL,
                    "state": state,
                },
                status=status.HTTP_200_OK,
            )


def _owned_workspace(request, workspace_id):
    return get_object_or_404(ProjectWorkspace, pk=workspace_id, owner=request.user)


def _accessible_workspace(request, workspace_id):
    workspace = get_object_or_404(ProjectWorkspace, pk=workspace_id)
    if workspace.owner_id == request.user.pk or WorkspaceCollaborator.objects.filter(
        workspace=workspace,
        user=request.user,
        revoked_at__isnull=True,
    ).exists():
        return workspace
    raise Http404


def _is_workspace_owner(request, workspace):
    return workspace.owner_id == request.user.pk


def _require_workspace_owner(request, workspace):
    if not _is_workspace_owner(request, workspace):
        raise PermissionDenied("Only the workspace owner can make changes.")


def _visible_artifacts(request, workspace):
    artifacts = WorkspaceArtifact.objects.filter(workspace=workspace)
    if not _is_workspace_owner(request, workspace):
        artifacts = artifacts.filter(status=WorkspaceArtifact.Status.APPROVED)
    return artifacts


def _approved_artifact(workspace, kind):
    artifact = (
        WorkspaceArtifact.objects.filter(
            workspace=workspace,
            kind=kind,
            status=WorkspaceArtifact.Status.APPROVED,
        )
        .order_by("-updated_at", "id")
        .first()
    )
    if artifact is None:
        raise ValidationError(
            {"detail": f"Approve a {kind} artifact before generating the next phase."}
        )
    return artifact


def _linked_research(workspace, artifact):
    research = WorkspaceArtifact.objects.filter(
        workspace=workspace,
        kind=WorkspaceArtifact.Kind.RESEARCH,
        status=WorkspaceArtifact.Status.APPROVED,
        id__in=artifact.input_artifact_ids,
    ).first()
    if research is None:
        raise ValidationError(
            {"detail": "The approved artifact must be based on an approved research synthesis."}
        )
    return research


def _create_artifact(
    workspace,
    kind,
    content,
    *,
    author,
    source_snapshot=None,
    source_problem_id=None,
    input_artifact_ids=None,
    artifact_status=WorkspaceArtifact.Status.DRAFT,
):
    with transaction.atomic():
        locked_workspace = ProjectWorkspace.objects.select_for_update().get(pk=workspace.pk)
        previous = (
            WorkspaceArtifact.objects.select_for_update()
            .filter(workspace=locked_workspace, kind=kind)
            .order_by("-created_at", "-version_number", "id")
            .first()
        )
        if previous is None:
            lineage_root = None
            next_version = 1
        else:
            lineage_root = previous.lineage_root or previous
            max_version = lineage_root.lineage_versions.aggregate(
                highest=Max("version_number")
            )["highest"]
            next_version = (max_version or 0) + 1
        artifact = WorkspaceArtifact(
            workspace=locked_workspace,
            kind=kind,
            status=artifact_status,
            content=content,
            source_snapshot=source_snapshot if source_snapshot is not None else [],
            source_problem_id=source_problem_id,
            input_artifact_ids=[str(value) for value in (input_artifact_ids or [])],
            version_number=next_version,
            lineage_root=lineage_root,
            revision_of=previous,
            author=author,
        )
        artifact.content = WorkspaceArtifactSerializer.normalize_artifact_content(
            artifact, artifact.content
        )
        artifact.save()
    return artifact


class WorkspaceArtifactListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        workspace = _accessible_workspace(request, workspace_id)
        artifacts = _visible_artifacts(request, workspace)
        return Response(WorkspaceArtifactSerializer(artifacts, many=True).data)


class WorkspaceArtifactDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, workspace_id, artifact_id):
        workspace = _accessible_workspace(request, workspace_id)
        return get_object_or_404(_visible_artifacts(request, workspace), pk=artifact_id)

    def get(self, request, workspace_id, artifact_id):
        artifact = self.get_object(request, workspace_id, artifact_id)
        return Response(WorkspaceArtifactSerializer(artifact).data)

    def patch(self, request, workspace_id, artifact_id):
        with transaction.atomic():
            workspace = _owned_workspace(request, workspace_id)
            artifact = get_object_or_404(
                WorkspaceArtifact, workspace=workspace, pk=artifact_id
            )
            artifact = WorkspaceArtifact.objects.select_for_update().get(pk=artifact.pk)
            serializer = WorkspaceArtifactSerializer(
                artifact,
                data=request.data,
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(serializer.data)

    def delete(self, request, workspace_id, artifact_id):
        workspace = _owned_workspace(request, workspace_id)
        artifact = get_object_or_404(
            WorkspaceArtifact, workspace=workspace, pk=artifact_id
        )
        if artifact.status == WorkspaceArtifact.Status.APPROVED:
            raise ValidationError("Approved artifacts cannot be deleted; create a revision instead.")
        if artifact.lineage_versions.filter(
            version_number__gt=artifact.version_number
        ).exists():
            raise ValidationError("Historical versions cannot be deleted.")
        artifact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceArtifactRevisionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, workspace_id, artifact_id):
        original = get_object_or_404(
            WorkspaceArtifact,
            workspace__owner=request.user,
            workspace_id=workspace_id,
            pk=artifact_id,
        )
        with transaction.atomic():
            workspace = ProjectWorkspace.objects.select_for_update().get(
                pk=original.workspace_id,
                owner=request.user,
            )
            original = get_object_or_404(
                WorkspaceArtifact.objects.select_for_update(),
                workspace=workspace,
                pk=artifact_id,
            )
            if original.kind == WorkspaceArtifact.Kind.SPECIFICATION:
                raise ValidationError(
                    "Specification snapshots are immutable; generate a new snapshot."
                )
            root = original.lineage_root or original
            root = WorkspaceArtifact.objects.select_for_update().get(pk=root.pk)
            max_version = root.lineage_versions.aggregate(
                highest=Max("version_number")
            )["highest"]
            revision = WorkspaceArtifact.objects.create(
                workspace=workspace,
                kind=original.kind,
                content=original.content,
                source_snapshot=original.source_snapshot,
                source_problem_id=original.source_problem_id,
                input_artifact_ids=original.input_artifact_ids,
                version_number=(max_version or 0) + 1,
                lineage_root=root,
                revision_of=original,
                author=request.user,
            )
        return Response(
            WorkspaceArtifactSerializer(revision).data,
            status=status.HTTP_201_CREATED,
        )


class WorkspaceArtifactVersionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id, artifact_id):
        workspace = _accessible_workspace(request, workspace_id)
        artifact = get_object_or_404(
            _visible_artifacts(request, workspace), pk=artifact_id
        )
        root = artifact.lineage_root or artifact
        versions = _visible_artifacts(request, workspace).filter(
            workspace=workspace,
            lineage_root=root,
        ).order_by("version_number", "created_at", "id")
        return Response(WorkspaceArtifactSerializer(versions, many=True).data)


class WorkspaceArtifactVersionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id, artifact_id, version_id):
        workspace = _accessible_workspace(request, workspace_id)
        artifact = get_object_or_404(
            _visible_artifacts(request, workspace), pk=artifact_id
        )
        root = artifact.lineage_root or artifact
        version = get_object_or_404(
            _visible_artifacts(request, workspace).filter(lineage_root=root),
            pk=version_id,
        )
        return Response(WorkspaceArtifactSerializer(version).data)


def _version_changes(before, after, path="content"):
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            child_path = f"{path}.{key}"
            if key not in before or key not in after:
                changes.append(
                    {
                        "path": child_path,
                        "before": before.get(key),
                        "after": after.get(key),
                        "before_present": key in before,
                        "after_present": key in after,
                    }
                )
            else:
                changes.extend(_version_changes(before[key], after[key], child_path))
        return changes
    if before == after:
        return []
    return [{"path": path, "before": before, "after": after}]


class WorkspaceArtifactVersionCompareView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id, artifact_id):
        workspace = _accessible_workspace(request, workspace_id)
        artifact = get_object_or_404(
            _visible_artifacts(request, workspace), pk=artifact_id
        )
        query = ArtifactVersionCompareQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        root = artifact.lineage_root or artifact
        versions = _visible_artifacts(request, workspace).filter(
            workspace=workspace,
            lineage_root=root,
        )
        left = get_object_or_404(versions, pk=query.validated_data["left_version"])
        right = get_object_or_404(versions, pk=query.validated_data["right_version"])
        changes = _version_changes(left.content, right.content)
        for field in (
            "status",
            "source_snapshot",
            "source_problem_id",
            "input_artifact_ids",
        ):
            changes.extend(
                _version_changes(
                    getattr(left, field),
                    getattr(right, field),
                    path=field,
                )
            )
        return Response(
            {
                "left_version": WorkspaceArtifactSerializer(left).data,
                "right_version": WorkspaceArtifactSerializer(right).data,
                "changed_fields": [change["path"] for change in changes],
                "changes": changes,
            }
        )


class WorkspaceSpecificationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        workspace = _accessible_workspace(request, workspace_id)
        specifications = _visible_artifacts(request, workspace).filter(
            workspace=workspace,
            kind=WorkspaceArtifact.Kind.SPECIFICATION,
        ).order_by("-created_at", "-version_number", "id")
        return Response(WorkspaceArtifactSerializer(specifications, many=True).data)

    def post(self, request, workspace_id):
        workspace = _owned_workspace(request, workspace_id)
        if request.data:
            raise ValidationError(
                {"detail": "Specification generation does not accept request data."}
            )
        try:
            inputs = approved_specification_inputs(workspace)
            content = compose_specification(workspace, inputs)
        except ArtifactValidationError as error:
            raise ValidationError({"detail": error.message}) from error
        research = inputs[WorkspaceArtifact.Kind.RESEARCH]
        artifact = _create_artifact(
            workspace,
            WorkspaceArtifact.Kind.SPECIFICATION,
            content,
            author=request.user,
            source_snapshot=content["research"]["evidence_sources"],
            source_problem_id=research.source_problem_id,
            input_artifact_ids=[item.pk for item in inputs.values()],
            artifact_status=WorkspaceArtifact.Status.DRAFT,
        )
        return Response(
            WorkspaceArtifactSerializer(artifact).data,
            status=status.HTTP_201_CREATED,
        )


class WorkspaceSpecificationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_specification(self, request, workspace_id, artifact_id):
        workspace = _accessible_workspace(request, workspace_id)
        return get_object_or_404(
            _visible_artifacts(request, workspace).filter(
                kind=WorkspaceArtifact.Kind.SPECIFICATION
            ),
            pk=artifact_id,
        )

    def get(self, request, workspace_id, artifact_id):
        artifact = self.get_specification(request, workspace_id, artifact_id)
        return Response(WorkspaceArtifactSerializer(artifact).data)


class WorkspaceSpecificationExportView(WorkspaceSpecificationDetailView):
    def get(self, request, workspace_id, artifact_id, export_format):
        artifact = self.get_specification(request, workspace_id, artifact_id)
        outdated = WorkspaceArtifactSerializer(artifact).data["is_outdated"]
        if export_format == "md":
            response = HttpResponse(
                specification_markdown(artifact, outdated=outdated),
                content_type="text/markdown; charset=utf-8",
            )
            extension = "md"
        elif export_format == "pdf":
            try:
                content = specification_pdf(artifact, outdated=outdated)
            except SpecificationExportError:
                return Response(
                    {"detail": "The selected specification could not be rendered. Try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            response = HttpResponse(content, content_type="application/pdf")
            extension = "pdf"
        else:
            raise ValidationError({"detail": "Choose Markdown or PDF export."})
        response["Content-Disposition"] = content_disposition_header(
            as_attachment=True,
            filename=specification_filename(artifact, extension),
        )
        return response


class WorkspaceSpecificationInputsView(WorkspaceSpecificationDetailView):
    def get(self, request, workspace_id, artifact_id):
        specification = self.get_specification(request, workspace_id, artifact_id)
        input_refs = specification.content.get("input_artifacts", [])
        if not isinstance(input_refs, list) or len(input_refs) != len(INPUT_KINDS):
            raise ValidationError(
                "The specification does not contain a complete set of input artifact versions."
            )
        inputs = []
        seen_kinds = set()
        for reference in input_refs:
            if (
                not isinstance(reference, dict)
                or reference.get("kind") not in INPUT_KINDS
                or reference.get("kind") in seen_kinds
                or reference.get("status") != WorkspaceArtifact.Status.APPROVED
            ):
                raise ValidationError(
                    "The specification contains an invalid or unapproved input-artifact reference."
                )
            seen_kinds.add(reference["kind"])
            artifact = get_object_or_404(
                WorkspaceArtifact,
                workspace_id=specification.workspace_id,
                pk=reference.get("artifact_id"),
                kind=reference.get("kind"),
                version_number=reference.get("version_number"),
                status=WorkspaceArtifact.Status.APPROVED,
            )
            inputs.append(WorkspaceArtifactSerializer(artifact).data)
        return Response(
            {
                "specification_id": str(specification.pk),
                "is_outdated": WorkspaceArtifactSerializer(specification).data[
                    "is_outdated"
                ],
                "input_artifacts": inputs,
                "validation_findings": specification.content.get(
                    "validation_findings", []
                ),
            }
        )


class ArtifactGenerationView(APIView):
    permission_classes = [IsAuthenticated]
    artifact_kind = None

    def post(self, request, workspace_id):
        workspace = _owned_workspace(request, workspace_id)
        try:
            artifact = self.generate(workspace, request.data, request.user)
        except ArtifactValidationError as error:
            raise ValidationError({"detail": error.message}) from error
        except OllamaError as error:
            return Response(
                {"detail": error.public_message},
                status=error.status_code,
            )
        return Response(
            WorkspaceArtifactSerializer(artifact).data,
            status=status.HTTP_201_CREATED,
        )

    def generate(self, workspace, data, author):
        raise NotImplementedError


class ResearchGenerationView(ArtifactGenerationView):
    artifact_kind = WorkspaceArtifact.Kind.RESEARCH

    def generate(self, workspace, data, author):
        serializer = ResearchGenerationInputSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        problem = get_object_or_404(
            ProblemStatement,
            pk=serializer.validated_data["problem_id"],
            status=ProblemStatement.Status.PUBLISHED,
        )
        synthesis, evidence = generate_research(problem)
        return _create_artifact(
            workspace,
            self.artifact_kind,
            synthesis,
            author=author,
            source_snapshot=evidence,
            source_problem_id=problem.pk,
        )


class RequirementsGenerationView(ArtifactGenerationView):
    artifact_kind = WorkspaceArtifact.Kind.REQUIREMENTS

    def generate(self, workspace, data, author):
        if data:
            raise ValidationError({"detail": "Requirements generation does not accept request data."})
        research = _approved_artifact(workspace, WorkspaceArtifact.Kind.RESEARCH)
        content = generate_requirements(workspace, research)
        return _create_artifact(
            workspace,
            self.artifact_kind,
            content,
            author=author,
            source_snapshot=research.source_snapshot,
            source_problem_id=research.source_problem_id,
            input_artifact_ids=[research.pk],
        )


class TechnologyGenerationView(ArtifactGenerationView):
    artifact_kind = WorkspaceArtifact.Kind.TECHNOLOGY

    def generate(self, workspace, data, author):
        serializer = TechnologyGenerationInputSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        requirements = _approved_artifact(
            workspace, WorkspaceArtifact.Kind.REQUIREMENTS
        )
        research = _linked_research(workspace, requirements)
        content = generate_technology_comparison(
            workspace,
            requirements,
            research,
            serializer.validated_data["options"],
        )
        return _create_artifact(
            workspace,
            self.artifact_kind,
            content,
            author=author,
            source_snapshot=research.source_snapshot,
            source_problem_id=research.source_problem_id,
            input_artifact_ids=[research.pk, requirements.pk],
        )


class DesignGenerationView(ArtifactGenerationView):
    artifact_kind = WorkspaceArtifact.Kind.DESIGN

    def generate(self, workspace, data, author):
        if data:
            raise ValidationError({"detail": "Design generation does not accept request data."})
        technology = _approved_artifact(workspace, WorkspaceArtifact.Kind.TECHNOLOGY)
        requirements = get_object_or_404(
            WorkspaceArtifact,
            workspace=workspace,
            kind=WorkspaceArtifact.Kind.REQUIREMENTS,
            status=WorkspaceArtifact.Status.APPROVED,
            pk__in=technology.input_artifact_ids,
        )
        research = _linked_research(workspace, requirements)
        content = generate_system_design(workspace, research, requirements, technology)
        return _create_artifact(
            workspace,
            self.artifact_kind,
            content,
            author=author,
            source_snapshot=research.source_snapshot,
            source_problem_id=research.source_problem_id,
            input_artifact_ids=[research.pk, requirements.pk, technology.pk],
        )


class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer
    lookup_value_converter = "uuid"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return ProjectWorkspace.objects.filter(
            Q(owner=self.request.user)
            | Q(
                collaborators__user=self.request.user,
                collaborators__revoked_at__isnull=True,
            )
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def update(self, request, *args, **kwargs):
        _require_workspace_owner(request, self.get_object())
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        _require_workspace_owner(request, self.get_object())
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        _require_workspace_owner(request, self.get_object())
        return super().destroy(request, *args, **kwargs)


class WorkspaceCollaboratorListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        workspace = _owned_workspace(request, workspace_id)
        grants = WorkspaceCollaborator.objects.filter(workspace=workspace).select_related(
            "user", "granted_by"
        )
        return Response(WorkspaceCollaboratorSerializer(grants, many=True).data)

    def post(self, request, workspace_id):
        workspace = _owned_workspace(request, workspace_id)
        serializer = WorkspaceCollaboratorGrantSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        target = serializer.context["target_user"]
        with transaction.atomic():
            locked_workspace = ProjectWorkspace.objects.select_for_update().get(
                pk=workspace.pk, owner=request.user
            )
            grant, created = WorkspaceCollaborator.objects.select_for_update().get_or_create(
                workspace=locked_workspace,
                user=target,
                revoked_at__isnull=True,
                defaults={"granted_by": request.user, "granted_at": timezone.now()},
            )
            if not created:
                return Response(
                    WorkspaceCollaboratorSerializer(grant).data,
                    status=status.HTTP_200_OK,
                )
        return Response(
            WorkspaceCollaboratorSerializer(grant).data,
            status=status.HTTP_201_CREATED,
        )


class WorkspaceCollaboratorRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, workspace_id, collaborator_id):
        workspace = _owned_workspace(request, workspace_id)
        with transaction.atomic():
            ProjectWorkspace.objects.select_for_update().get(
                pk=workspace.pk, owner=request.user
            )
            grant = get_object_or_404(
                WorkspaceCollaborator.objects.select_for_update(),
                workspace=workspace,
                pk=collaborator_id,
            )
            if grant.is_active:
                grant.revoked_at = timezone.now()
                grant.save(update_fields=("revoked_at",))
        return Response(status=status.HTTP_204_NO_CONTENT)


def _requirements_artifact(workspace, artifact_id, *, approved_only=True):
    queryset = WorkspaceArtifact.objects.filter(
        workspace=workspace,
        kind=WorkspaceArtifact.Kind.REQUIREMENTS,
    )
    if approved_only:
        queryset = queryset.filter(status=WorkspaceArtifact.Status.APPROVED)
    return get_object_or_404(queryset, pk=artifact_id)


def _requirement_exists(requirements, requirement_id):
    return any(
        item.get("id") == requirement_id
        for item in requirement_entries(requirements)
    )


class WorkspaceTaskPlanView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, workspace_id):
        workspace = _owned_workspace(request, workspace_id)
        serializer = TaskPlanInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requirements = _requirements_artifact(
            workspace,
            serializer.validated_data["requirements_artifact_id"],
        )
        result = generate_tasks(workspace, requirements, request.user)
        return Response(
            {
                "requirements_artifact_id": str(requirements.pk),
                "requirements_version": requirements.version_number,
                "created_count": result["created_count"],
                "existing_count": result["existing_count"],
                "unmapped_requirements": result["unmapped_requirements"],
                "tasks": ImplementationTaskSerializer(result["tasks"], many=True).data,
            }
        )


class WorkspaceTaskListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        workspace = _accessible_workspace(request, workspace_id)
        tasks = ImplementationTask.objects.filter(
            workspace=workspace,
            source_requirements__status=WorkspaceArtifact.Status.APPROVED,
        ).select_related("source_requirements")
        return Response(ImplementationTaskSerializer(tasks, many=True).data)

    def post(self, request, workspace_id):
        workspace = _owned_workspace(request, workspace_id)
        serializer = ImplementationTaskSerializer(
            data=request.data,
            context={"request": request, "workspace": workspace},
        )
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response(
            ImplementationTaskSerializer(task).data,
            status=status.HTTP_201_CREATED,
        )


class WorkspaceTaskDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_task(self, request, workspace_id, task_id, *, owner=False):
        workspace = (
            _owned_workspace(request, workspace_id)
            if owner
            else _accessible_workspace(request, workspace_id)
        )
        return get_object_or_404(
            ImplementationTask.objects.select_related("source_requirements"),
            workspace=workspace,
            pk=task_id,
            source_requirements__status=WorkspaceArtifact.Status.APPROVED,
        )

    def get(self, request, workspace_id, task_id):
        task = self.get_task(request, workspace_id, task_id)
        return Response(ImplementationTaskSerializer(task).data)

    def patch(self, request, workspace_id, task_id):
        with transaction.atomic():
            workspace = _owned_workspace(request, workspace_id)
            ProjectWorkspace.objects.select_for_update().get(pk=workspace.pk)
            task = get_object_or_404(
                ImplementationTask.objects.select_for_update().select_related(
                    "source_requirements"
                ),
                workspace=workspace,
                pk=task_id,
                source_requirements__status=WorkspaceArtifact.Status.APPROVED,
            )
            serializer = ImplementationTaskSerializer(
                task,
                data=request.data,
                partial=True,
                context={"request": request, "workspace": task.workspace},
            )
            serializer.is_valid(raise_exception=True)
            task = serializer.save()
        return Response(ImplementationTaskSerializer(task).data)


class RequirementEvidenceListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get_requirements(self, request, workspace_id, artifact_id, requirement_id):
        workspace = _accessible_workspace(request, workspace_id)
        requirements = _requirements_artifact(workspace, artifact_id)
        if not _requirement_exists(requirements, requirement_id):
            raise Http404
        return requirements

    def get(self, request, workspace_id, artifact_id, requirement_id):
        requirements = self.get_requirements(
            request, workspace_id, artifact_id, requirement_id
        )
        evidence = ImplementationEvidence.objects.filter(
            requirements_artifact=requirements,
            requirement_id=requirement_id,
        ).select_related("author", "task", "supersedes")
        return Response(ImplementationEvidenceSerializer(evidence, many=True).data)

    def post(self, request, workspace_id, artifact_id, requirement_id):
        requirements = self.get_requirements(
            request, workspace_id, artifact_id, requirement_id
        )
        _require_workspace_owner(request, requirements.workspace)
        serializer = ImplementationEvidenceSerializer(
            data=request.data,
            context={
                "request": request,
                "requirements": requirements,
                "requirement_id": requirement_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                ProjectWorkspace.objects.select_for_update().get(
                    pk=requirements.workspace_id
                )
                evidence = serializer.save()
        except IntegrityError as error:
            if serializer.validated_data.get("supersedes") is None:
                raise
            raise ValidationError(
                {"supersedes_id": "This evidence was corrected by another request."}
            ) from error
        return Response(
            ImplementationEvidenceSerializer(evidence).data,
            status=status.HTTP_201_CREATED,
        )


class RequirementVerificationView(RequirementEvidenceListCreateView):
    def get(self, request, workspace_id, artifact_id, requirement_id):
        requirements = self.get_requirements(
            request, workspace_id, artifact_id, requirement_id
        )
        latest = RequirementVerification.objects.filter(
            requirements_artifact=requirements,
            requirement_id=requirement_id,
        ).select_related("requirements_artifact").first()
        if latest is None:
            result = evaluate_requirement(
                requirements,
                requirement_id,
                current_evidence(requirements, requirement_id),
            )
            outdated = requirements_artifact_is_outdated(requirements)
            return Response(
                {
                    "requirements_artifact_id": str(requirements.pk),
                    "requirements_version": requirements.version_number,
                    "requirement_id": requirement_id,
                    **(
                        {
                            **result,
                            "status": RequirementVerification.Status.UNVERIFIED,
                            "rationale": (
                                "This requirements artifact has a newer version; "
                                "review the new version before verifying."
                            ),
                        }
                        if outdated
                        else result
                    ),
                    "recorded_status": None,
                    "is_outdated": outdated,
                    "actor_id": None,
                    "created_at": None,
                }
            )
        return Response(current_verification_payload(latest))

    def post(self, request, workspace_id, artifact_id, requirement_id):
        requirements = self.get_requirements(
            request, workspace_id, artifact_id, requirement_id
        )
        _require_workspace_owner(request, requirements.workspace)
        if request.data:
            raise ValidationError({"detail": "Verification is computed from recorded evidence; no status may be supplied."})
        result = evaluate_requirement(
            requirements,
            requirement_id,
            current_evidence(requirements, requirement_id),
        )
        verification = RequirementVerification.objects.create(
            workspace=requirements.workspace,
            requirements_artifact=requirements,
            requirement_id=requirement_id,
            status=result["status"],
            rationale=result["rationale"],
            evidence_ids=result["evidence_ids"],
            criterion_results=result["criterion_results"],
            actor=request.user,
        )
        return Response(
            current_verification_payload(verification),
            status=status.HTTP_201_CREATED,
        )


class RequirementVerificationHistoryView(RequirementEvidenceListCreateView):
    def get(self, request, workspace_id, artifact_id, requirement_id):
        requirements = self.get_requirements(
            request, workspace_id, artifact_id, requirement_id
        )
        history = RequirementVerification.objects.filter(
            requirements_artifact=requirements,
            requirement_id=requirement_id,
        ).select_related("requirements_artifact", "actor")
        return Response(
            [
                current_verification_payload(verification)
                for verification in history
            ]
        )
