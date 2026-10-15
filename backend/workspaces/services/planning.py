from django.db.models import Q

from backend.workspaces.models import ImplementationTask, WorkspaceArtifact


def requirement_entries(requirements):
    content = requirements.content
    return [
        item
        for field in ("functional_requirements", "non_functional_requirements")
        for item in content.get(field, [])
    ]


def criteria_for_requirement(requirements, requirement_id):
    return [
        criterion
        for criterion in requirements.content.get("acceptance_criteria", [])
        if requirement_id in criterion.get("requirement_ids", [])
    ]


def requirements_artifact_is_outdated(requirements):
    return WorkspaceArtifact.objects.filter(
        workspace_id=requirements.workspace_id,
        kind=WorkspaceArtifact.Kind.REQUIREMENTS,
    ).filter(
        Q(created_at__gt=requirements.created_at)
        | Q(created_at=requirements.created_at, pk__gt=requirements.pk)
        | Q(
            lineage_root_id=requirements.lineage_root_id,
            version_number__gt=requirements.version_number,
        )
    ).exists()


def task_is_outdated(task):
    return requirements_artifact_is_outdated(task.source_requirements)


def generate_tasks(workspace, requirements, author):
    created = []
    unmapped = []
    for requirement in requirement_entries(requirements):
        requirement_id = requirement.get("id")
        statement = requirement.get("statement")
        if not isinstance(requirement_id, str) or not requirement_id or not statement:
            unmapped.append(
                {
                    "requirement_id": requirement_id,
                    "reason": "The approved requirement has no stable ID or statement.",
                }
            )
            continue
        criteria = criteria_for_requirement(requirements, requirement_id)
        title = f"Implement: {statement}"[:200]
        description = f"Implement requirement {requirement_id}: {statement}"
        if criteria:
            description += "\n\nAcceptance criteria:\n" + "\n".join(
                f"- {item['id']}: {item['criterion']}" for item in criteria
            )
        task, was_created = ImplementationTask.objects.get_or_create(
            source_requirements=requirements,
            source_requirement_id=requirement_id,
            defaults={
                "workspace": workspace,
                "acceptance_criteria_ids": [item["id"] for item in criteria],
                "title": title,
                "description": description,
                "created_by": author,
            },
        )
        created.append((task, was_created))
    return {
        "tasks": [task for task, _ in created],
        "created_count": sum(was_created for _, was_created in created),
        "existing_count": sum(not was_created for _, was_created in created),
        "unmapped_requirements": unmapped,
    }


def is_valid_status_transition(previous, next_status):
    allowed = {
        ImplementationTask.Status.TODO: {
            ImplementationTask.Status.IN_PROGRESS,
            ImplementationTask.Status.BLOCKED,
            ImplementationTask.Status.COMPLETED,
        },
        ImplementationTask.Status.IN_PROGRESS: {
            ImplementationTask.Status.TODO,
            ImplementationTask.Status.BLOCKED,
            ImplementationTask.Status.COMPLETED,
        },
        ImplementationTask.Status.BLOCKED: {
            ImplementationTask.Status.TODO,
            ImplementationTask.Status.IN_PROGRESS,
        },
        ImplementationTask.Status.COMPLETED: {
            ImplementationTask.Status.TODO,
            ImplementationTask.Status.IN_PROGRESS,
        },
    }
    return next_status == previous or next_status in allowed.get(previous, set())


def dependencies_create_cycle(task, dependencies):
    pending = list(dependencies)
    seen = set()
    while pending:
        dependency = pending.pop()
        if dependency.pk == task.pk:
            return True
        if dependency.pk in seen:
            continue
        seen.add(dependency.pk)
        pending.extend(dependency.dependencies.all())
    return False
