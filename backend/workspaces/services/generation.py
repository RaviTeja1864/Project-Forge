import json

from backend.workspaces.services.ollama import generate_json
from backend.workspaces.services.research import synthesize_research
from backend.workspaces.services.validation import (
    ArtifactValidationError,
    validate_design,
    validate_requirements,
    validate_technology_comparison,
)


def generate_research(problem):
    synthesis = synthesize_research(problem)
    evidence = synthesis.pop("evidence", [])
    synthesis.pop("problem", None)
    return synthesis, evidence


def generate_requirements(workspace, research_artifact):
    evidence_ids = {source["id"] for source in research_artifact.source_snapshot}
    prompt = (
        "Generate editable engineering project requirements from this workspace and "
        "approved research synthesis. Return JSON fields exactly: problem_statement, "
        "objectives (strings), target_users [{name, assumptions}], scope "
        "{in_scope: strings, out_of_scope: strings}, user_stories "
        "[{id: US-###, as_a, want, so_that, evidence_source_ids}], "
        "functional_requirements [{id: FR-###, statement, classification "
        "[evidence_backed|proposed|assumption], evidence_source_ids, needs_user_input}], "
        "non_functional_requirements [{id: NFR-###, statement, acceptance_condition "
        "(string or null), classification, evidence_source_ids, needs_user_input}], "
        "constraints/assumptions/dependencies/risks (each [{statement, evidence_source_ids}]), "
        "acceptance_criteria [{id: AC-###, criterion, requirement_ids, evidence_source_ids, needs_user_input}]. "
        "IDs must be unique within each category and use three digits. Cite only supplied "
        "source IDs. Do not create numerical targets without evidence; mark missing "
        "measurable targets needs_user_input=true. Distinguish evidence-backed items, "
        "proposals, and assumptions. Use no source facts beyond this approved research. "
        f"Allowed evidence IDs: {json.dumps(sorted(evidence_ids))}. Input JSON:\n"
        f"{json.dumps({'workspace': {'name': workspace.name, 'description': workspace.description}, 'research': research_artifact.content, 'evidence': research_artifact.source_snapshot}, ensure_ascii=False)}"
    )
    output = generate_json(prompt)
    return validate_requirements(output, evidence_ids)


def normalize_comparison_options(value):
    if not isinstance(value, list) or not 2 <= len(value) <= 8:
        raise ArtifactValidationError("Provide between 2 and 8 technology options.")
    options = []
    for option in value:
        if not isinstance(option, str):
            raise ArtifactValidationError("Each technology option must be text.")
        option = option.strip()
        if not option or len(option) > 120:
            raise ArtifactValidationError("Each technology option must be 1–120 characters.")
        options.append(option)
    if len({option.casefold() for option in options}) != len(options):
        raise ArtifactValidationError("Technology options must be distinct.")
    return options


def generate_technology_comparison(workspace, requirements_artifact, research_artifact, options):
    options = normalize_comparison_options(options)
    requirement_ids = {
        item["id"]
        for field in ("functional_requirements", "non_functional_requirements")
        for item in requirements_artifact.content[field]
    }
    evidence_ids = {source["id"] for source in research_artifact.source_snapshot}
    prompt = (
        "Compare only the user-supplied technology options for this project. Return a JSON "
        "object with selection_criteria [{name, reason}], scoring_method (explain qualitative "
        "comparison; do not invent numeric scores), options [{name, role, advantages, "
        "disadvantages, compatibility [{requirement_id, assessment [good|partial|poor|unknown], "
        "reason}], operational_considerations, learning_considerations, "
        "evidence_backed_claims [{claim, evidence_source_ids}], unverified_assumptions, "
        "missing_information}], recommendation {option, reasoning, limitations}, and "
        "insufficient_evidence (boolean). Option names must exactly match user input. "
        "Reference only listed requirement and evidence IDs. Do not state benchmarks, prices, "
        "popularity, versions, or compatibility as verified without cited supplied evidence. "
        "Label unverified considerations and state if a fair comparison is not possible. "
        f"Allowed options: {json.dumps(options)}. Requirement IDs: {json.dumps(sorted(requirement_ids))}. "
        f"Evidence IDs: {json.dumps(sorted(evidence_ids))}. Input JSON:\n"
        f"{json.dumps({'workspace': {'name': workspace.name, 'description': workspace.description}, 'requirements': requirements_artifact.content, 'research': research_artifact.content, 'evidence': research_artifact.source_snapshot}, ensure_ascii=False)}"
    )
    result = validate_technology_comparison(
        generate_json(prompt),
        evidence_ids,
        options,
    )
    for option in result["options"]:
        for rating in option["compatibility"]:
            if rating["requirement_id"] not in requirement_ids:
                raise ArtifactValidationError(
                    "Technology compatibility refers to a missing requirement."
                )
    return result


def generate_system_design(workspace, research_artifact, requirements_artifact, technology_artifact):
    requirement_ids = {
        item["id"]
        for field in ("functional_requirements", "non_functional_requirements")
        for item in requirements_artifact.content[field]
    }
    evidence_ids = {source["id"] for source in research_artifact.source_snapshot}
    recommended_technology = technology_artifact.content["recommendation"]["option"]
    prompt = (
        "Generate a reviewable proposed system design consistent with the approved research, "
        "requirements, and technology comparison. Return JSON fields: architecture_components "
        "[{name, responsibility, requirement_ids, evidence_source_ids}], architecture_diagram "
        "(Mermaid flowchart), data_flow_diagram (Mermaid flowchart), main_flows (strings), "
        "api_endpoints [{method, path, purpose, authentication, request_shape, response_shape}], "
        "selected_technology (must exactly match the approved comparison recommendation), "
        "technology_rationale, "
        "database_entities [{name (simple identifier), attributes [{name, type, constraints}]}], "
        "relationships [{from_entity, to_entity, cardinality, description}], er_diagram "
        "(Mermaid erDiagram mentioning every declared entity), security_considerations, "
        "privacy_considerations, reliability_considerations, failure_handling, tradeoffs, "
        "unresolved_decisions (all string arrays). Mermaid must be plain diagram syntax without "
        "HTML, directives, or scripts. API paths must be relative paths; describe auth explicitly. "
        "Cite only supplied requirement/evidence IDs. Mark the entire design as a proposal, not "
        "a production schema or implementation. Do not add unsupported technology claims. "
        f"Allowed requirement IDs: {json.dumps(sorted(requirement_ids))}. "
        f"Allowed evidence IDs: {json.dumps(sorted(evidence_ids))}. Input JSON:\n"
        f"{json.dumps({'workspace': {'name': workspace.name, 'description': workspace.description}, 'requirements': requirements_artifact.content, 'technology_comparison': technology_artifact.content, 'research': research_artifact.content, 'evidence': research_artifact.source_snapshot}, ensure_ascii=False)}"
    )
    return validate_design(
        generate_json(prompt),
        requirement_ids,
        evidence_ids,
        recommended_technology=recommended_technology,
    )
