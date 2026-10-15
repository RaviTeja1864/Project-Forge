from django.utils import timezone

from backend.workspaces.models import WorkspaceArtifact
from backend.workspaces.services.validation import (
    ArtifactValidationError,
    validate_design,
)

INPUT_KINDS = (
    WorkspaceArtifact.Kind.RESEARCH,
    WorkspaceArtifact.Kind.REQUIREMENTS,
    WorkspaceArtifact.Kind.TECHNOLOGY,
    WorkspaceArtifact.Kind.DESIGN,
)


def approved_specification_inputs(workspace):
    inputs = {}
    missing = []
    for kind in INPUT_KINDS:
        artifact = (
            WorkspaceArtifact.objects.filter(
                workspace=workspace,
                kind=kind,
                status=WorkspaceArtifact.Status.APPROVED,
            )
            .order_by("-updated_at", "-created_at", "-id")
            .first()
        )
        if artifact is None:
            missing.append(kind)
            continue
        inputs[kind] = artifact
    if missing:
        names = ", ".join(WorkspaceArtifact.Kind(kind).label.lower() for kind in missing)
        raise ArtifactValidationError(
            f"Approve all required artifacts in this workspace before generating a specification. "
            f"Missing approved inputs: {names}."
        )
    return inputs


def specification_is_outdated(artifact):
    if artifact.kind != WorkspaceArtifact.Kind.SPECIFICATION:
        return False
    recorded_inputs = {
        item.get("kind"): item.get("artifact_id")
        for item in artifact.content.get("input_artifacts", [])
        if isinstance(item, dict)
    }
    for kind in INPUT_KINDS:
        current = (
            WorkspaceArtifact.objects.filter(
                workspace=artifact.workspace,
                kind=kind,
                status=WorkspaceArtifact.Status.APPROVED,
            )
            .order_by("-updated_at", "-created_at", "-id")
            .first()
        )
        if current is None or recorded_inputs.get(kind) != str(current.pk):
            return True
    return False


def _collect_source_references(value, known_source_ids, findings, path="$"):
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key == "evidence_source_ids":
                if not isinstance(item, list):
                    findings.append(
                        {
                            "severity": "error",
                            "code": "invalid_evidence_references",
                            "path": item_path,
                            "message": "Evidence references must be a list of source identifiers.",
                        }
                    )
                    continue
                for source_id in item:
                    if source_id not in known_source_ids:
                        findings.append(
                            {
                                "severity": "error",
                                "code": "unknown_evidence_reference",
                                "path": item_path,
                                "message": (
                                    f"Evidence identifier {source_id!r} is not present "
                                    "in the approved research source snapshot."
                                ),
                            }
                        )
            else:
                _collect_source_references(item, known_source_ids, findings, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_source_references(
                item, known_source_ids, findings, f"{path}[{index}]"
            )


def _missing_information(inputs):
    research = inputs[WorkspaceArtifact.Kind.RESEARCH].content
    requirements = inputs[WorkspaceArtifact.Kind.REQUIREMENTS].content
    technology = inputs[WorkspaceArtifact.Kind.TECHNOLOGY].content
    design = inputs[WorkspaceArtifact.Kind.DESIGN].content
    return {
        "research_gaps": research.get("research_gaps", []),
        "unknown_or_unsupported_details": research.get(
            "unknown_or_unsupported_details", []
        ),
        "evidence_limitations": research.get("evidence_limitations", []),
        "conflicting_information": research.get("conflicting_information", []),
        "unverified_technology_assumptions": [
            assumption
            for option in technology.get("options", [])
            for assumption in option.get("unverified_assumptions", [])
        ],
        "technology_missing_information": [
            item
            for option in technology.get("options", [])
            for item in option.get("missing_information", [])
        ],
        "technology_recommendation_limitations": technology.get(
            "recommendation", {}
        ).get("limitations", []),
        "requirements_assumptions": requirements.get("assumptions", []),
        "requirements_needing_user_input": [
            item
            for field in ("functional_requirements", "non_functional_requirements")
            for item in requirements.get(field, [])
            if item.get("needs_user_input")
        ],
        "constraints": requirements.get("constraints", []),
        "risks": requirements.get("risks", []),
        "unresolved_design_decisions": design.get("unresolved_decisions", []),
    }


def compose_specification(workspace, inputs):
    findings = []
    research = inputs[WorkspaceArtifact.Kind.RESEARCH]
    requirements = inputs[WorkspaceArtifact.Kind.REQUIREMENTS]
    technology = inputs[WorkspaceArtifact.Kind.TECHNOLOGY]
    design = inputs[WorkspaceArtifact.Kind.DESIGN]
    expected_dependencies = {
        requirements: (research,),
        technology: (research, requirements),
        design: (research, requirements, technology),
    }
    for artifact, dependencies in expected_dependencies.items():
        for dependency in dependencies:
            if str(dependency.pk) not in artifact.input_artifact_ids:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "approved_input_lineage_mismatch",
                        "path": f"{artifact.kind}.input_artifact_ids",
                        "message": (
                            f"The approved {artifact.kind} version does not record the "
                            f"selected {dependency.kind} version {dependency.pk} as an input. "
                            "Both approved versions are retained without assuming they are aligned."
                        ),
                    }
                )

    evidence_by_id = {}
    for kind, artifact in inputs.items():
        for source in artifact.source_snapshot:
            source_id = source.get("id")
            source_path = f"{kind}.source_snapshot"
            if not isinstance(source_id, str):
                findings.append(
                    {
                        "severity": "error",
                        "code": "invalid_evidence_snapshot",
                        "path": source_path,
                        "message": "Every evidence snapshot entry must have a source identifier.",
                    }
                )
                continue
            current = evidence_by_id.get(source_id)
            if current is not None and current != source:
                findings.append(
                    {
                        "severity": "error",
                        "code": "conflicting_evidence_metadata",
                        "path": source_path,
                        "message": f"Evidence identifier {source_id!r} has conflicting metadata.",
                    }
                )
            else:
                evidence_by_id[source_id] = source

    for kind, artifact in inputs.items():
        _collect_source_references(
            artifact.content,
            set(evidence_by_id),
            findings,
            path=kind,
        )

    requirement_ids = {
        item["id"]
        for field in ("functional_requirements", "non_functional_requirements")
        for item in requirements.content.get(field, [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for option in technology.content.get("options", []):
        for compatibility in option.get("compatibility", []):
            if compatibility.get("requirement_id") not in requirement_ids:
                findings.append(
                    {
                        "severity": "error",
                        "code": "unknown_requirement_reference",
                        "path": "technology.options.compatibility",
                        "message": (
                            f"Technology compatibility references unknown requirement "
                            f"{compatibility.get('requirement_id')!r}."
                        ),
                    }
                )

    technology_recommendation = technology.content.get("recommendation", {}).get(
        "option"
    )
    design_selection = design.content.get("selected_technology")
    if technology_recommendation != design_selection:
        findings.append(
            {
                "severity": "warning",
                "code": "technology_decision_conflict",
                "path": "technology.recommendation.option",
                "message": (
                    "The approved system design selects "
                    f"{design_selection!r}, while the approved technology comparison "
                    f"recommends {technology_recommendation!r}. Neither decision was "
                    "selected over the other."
                ),
            }
        )

    design_requirement_refs = {
        requirement_id
        for component in design.content.get("architecture_components", [])
        for requirement_id in component.get("requirement_ids", [])
    }
    unknown_design_requirements = design_requirement_refs - requirement_ids
    if unknown_design_requirements:
        findings.append(
            {
                "severity": "error",
                "code": "unknown_design_requirement",
                "path": "design.architecture_components",
                "message": (
                    "The system design references requirements absent from the approved "
                    f"requirements version: {sorted(unknown_design_requirements)}."
                ),
            }
        )

    for criterion in requirements.content.get("acceptance_criteria", []):
        for requirement_id in criterion.get("requirement_ids", []):
            if requirement_id not in requirement_ids:
                findings.append(
                    {
                        "severity": "error",
                        "code": "unknown_acceptance_requirement",
                        "path": "requirements.acceptance_criteria",
                        "message": (
                            "An acceptance criterion references unknown requirement "
                            f"{requirement_id!r}."
                        ),
                    }
                )

    validate_design(
        design.content,
        requirement_ids,
        set(evidence_by_id),
        recommended_technology=None,
    )

    errors = [finding for finding in findings if finding["severity"] == "error"]
    if errors:
        raise ArtifactValidationError(
            "Specification validation failed: "
            + " ".join(finding["message"] for finding in errors)
        )

    return {
        "specification_status": "review_required",
        "generated_at": timezone.now().isoformat(),
        "project": {
            "title": workspace.name,
            "description": workspace.description or None,
            "problem_statement": requirements.content["problem_statement"],
            "research_problem_summary": research.content["problem_summary"],
        },
        "objectives": requirements.content["objectives"],
        "scope": requirements.content["scope"],
        "target_users": requirements.content["target_users"],
        "research": {
            "key_claims": research.content["key_claims"],
            "evidence_limitations": research.content["evidence_limitations"],
            "conflicting_information": research.content["conflicting_information"],
            "unknown_or_unsupported_details": research.content[
                "unknown_or_unsupported_details"
            ],
            "research_gaps": research.content["research_gaps"],
            "interpretations_and_recommendations": research.content[
                "interpretations_and_recommendations"
            ],
            "evidence_sources": list(evidence_by_id.values()),
        },
        "requirements": {
            "user_stories": requirements.content["user_stories"],
            "functional_requirements": requirements.content[
                "functional_requirements"
            ],
            "non_functional_requirements": requirements.content[
                "non_functional_requirements"
            ],
            "acceptance_criteria": requirements.content["acceptance_criteria"],
            "dependencies": requirements.content.get("dependencies", []),
        },
        "technology": {
            "selection_criteria": technology.content["selection_criteria"],
            "scoring_method": technology.content["scoring_method"],
            "options": technology.content["options"],
            "recommendation": technology.content["recommendation"],
            "insufficient_evidence": technology.content["insufficient_evidence"],
            "design_selected_technology": design_selection,
        },
        "architecture": {
            "components": design.content["architecture_components"],
            "architecture_diagram": design.content["architecture_diagram"],
            "data_flow_diagram": design.content["data_flow_diagram"],
            "main_flows": design.content["main_flows"],
            "api_endpoints": design.content["api_endpoints"],
            "database_entities": design.content["database_entities"],
            "relationships": design.content["relationships"],
            "er_diagram": design.content["er_diagram"],
        },
        "security_and_reliability": {
            "security": design.content["security_considerations"],
            "privacy": design.content["privacy_considerations"],
            "reliability": design.content["reliability_considerations"],
            "failure_handling": design.content["failure_handling"],
        },
        "constraints": requirements.content["constraints"],
        "risks": requirements.content["risks"],
        "assumptions": requirements.content["assumptions"],
        "unresolved_information": _missing_information(inputs),
        "tradeoffs": {
            "technology_options": {
                option["name"]: {
                    "advantages": option["advantages"],
                    "disadvantages": option["disadvantages"],
                    "operational_considerations": option[
                        "operational_considerations"
                    ],
                    "learning_considerations": option["learning_considerations"],
                }
                for option in technology.content["options"]
            },
            "architecture": design.content["tradeoffs"],
        },
        "validation_findings": findings,
        "input_artifacts": [
            {
                "kind": artifact.kind,
                "artifact_id": str(artifact.pk),
                "version_number": artifact.version_number,
                "status": artifact.status,
                "lineage_root_id": str(artifact.lineage_root_id),
            }
            for artifact in inputs.values()
        ],
    }
