import re


class ArtifactValidationError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]{3}$")
_ENTITY_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_API_PATH = re.compile(r"^/[A-Za-z0-9_{}./-]*$")


def _text(value, label, *, limit=4000, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or (
        not allow_empty and not value.strip()
    ):
        raise ArtifactValidationError(f"{label} must be valid text (maximum {limit} characters).")
    return value.strip()


def _list(value, label, *, limit=30):
    if not isinstance(value, list) or len(value) > limit:
        raise ArtifactValidationError(f"{label} must be a list of at most {limit} items.")
    return value


def _citations(value, known_sources, label):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ArtifactValidationError(f"{label} must contain source identifiers.")
    if set(value) - known_sources:
        raise ArtifactValidationError(f"{label} contains an identifier outside the research evidence.")
    if len(value) != len(set(value)):
        raise ArtifactValidationError(f"{label} contains duplicate source identifiers.")
    return value


def _unique_ids(items, prefix, label):
    identifiers = []
    for item in items:
        if not isinstance(item, dict):
            raise ArtifactValidationError(f"Each {label} must be an object.")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not _IDENTIFIER.fullmatch(identifier)
            or not identifier.startswith(prefix)
        ):
            raise ArtifactValidationError(
                f"{label} identifiers must use {prefix}### format."
            )
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise ArtifactValidationError(f"{label} identifiers must be unique.")
    return identifiers


def validate_requirements(value, known_sources):
    if not isinstance(value, dict):
        raise ArtifactValidationError("Requirements must be a JSON object.")
    objectives = [
        _text(item, "objective", limit=1000)
        for item in _list(value.get("objectives"), "objectives")
    ]
    if not objectives:
        raise ArtifactValidationError("At least one project objective is required.")
    result = {
        "problem_statement": _text(value.get("problem_statement"), "problem_statement"),
        "objectives": objectives,
        "target_users": [],
        "scope": {},
        "user_stories": [],
        "functional_requirements": [],
        "non_functional_requirements": [],
        "constraints": [],
        "assumptions": [],
        "dependencies": [],
        "risks": [],
        "acceptance_criteria": [],
    }
    target_users = _list(value.get("target_users"), "target_users", limit=20)
    if not target_users:
        raise ArtifactValidationError("At least one target user or stakeholder assumption is required.")
    for user in target_users:
        if not isinstance(user, dict):
            raise ArtifactValidationError("Each target user must be an object.")
        result["target_users"].append(
            {
                "name": _text(user.get("name"), "target user", limit=300),
                "assumptions": [
                    _text(item, "user assumption", limit=1000)
                    for item in _list(user.get("assumptions"), "user assumptions", limit=10)
                ],
            }
        )
    scope = value.get("scope")
    if not isinstance(scope, dict):
        raise ArtifactValidationError("scope must include in_scope and out_of_scope lists.")
    for key in ("in_scope", "out_of_scope"):
        result["scope"][key] = [
            _text(item, key, limit=1000)
            for item in _list(scope.get(key), key, limit=30)
        ]

    stories = _list(value.get("user_stories"), "user_stories")
    if not stories:
        raise ArtifactValidationError("At least one user story is required.")
    _unique_ids(stories, "US-", "user stories")
    for story in stories:
        result["user_stories"].append(
            {
                "id": story["id"],
                "as_a": _text(story.get("as_a"), "user story as_a", limit=300),
                "want": _text(story.get("want"), "user story want", limit=1000),
                "so_that": _text(story.get("so_that"), "user story so_that", limit=1000),
                "evidence_source_ids": _citations(
                    story.get("evidence_source_ids"), known_sources, "user story citations"
                ),
            }
        )

    requirement_ids = []
    for field, prefix in (
        ("functional_requirements", "FR-"),
        ("non_functional_requirements", "NFR-"),
    ):
        items = _list(value.get(field), field)
        if not items:
            raise ArtifactValidationError(f"At least one {field} entry is required.")
        _unique_ids(items, prefix, field)
        for item in items:
            citations = _citations(
                item.get("evidence_source_ids"), known_sources, f"{field} citations"
            )
            classification = item.get("classification")
            if classification not in ("evidence_backed", "proposed", "assumption"):
                raise ArtifactValidationError(
                    f"{field} classification must be evidence_backed, proposed, or assumption."
                )
            normalized = {
                "id": item["id"],
                "statement": _text(item.get("statement"), f"{field} statement", limit=2000),
                "classification": classification,
                "evidence_source_ids": citations,
                "needs_user_input": item.get("needs_user_input"),
            }
            if not isinstance(normalized["needs_user_input"], bool):
                raise ArtifactValidationError(f"{field} needs_user_input must be boolean.")
            if classification == "evidence_backed" and not citations:
                raise ArtifactValidationError(
                    f"Evidence-backed {field} entries must cite supplied sources."
                )
            if field == "non_functional_requirements":
                condition = item.get("acceptance_condition")
                normalized["acceptance_condition"] = (
                    None
                    if condition is None
                    else _text(condition, "acceptance_condition", limit=1000)
                )
                if (
                    normalized["acceptance_condition"] is None
                    and not normalized["needs_user_input"]
                ):
                    raise ArtifactValidationError(
                        "A missing measurable acceptance condition must be marked needs_user_input."
                    )
                if (
                    normalized["acceptance_condition"]
                    and re.search(r"\d", normalized["acceptance_condition"])
                    and not citations
                    and not normalized["needs_user_input"]
                ):
                    raise ArtifactValidationError(
                        "Unsubstantiated quantitative targets must be marked needs_user_input."
                    )
            result[field].append(normalized)
            requirement_ids.append(item["id"])

    for field in ("constraints", "assumptions", "dependencies", "risks"):
        for item in _list(value.get(field), field):
            if not isinstance(item, dict):
                raise ArtifactValidationError(f"Each {field} entry must be an object.")
            result[field].append(
                {
                    "statement": _text(item.get("statement"), field, limit=1500),
                    "evidence_source_ids": _citations(
                        item.get("evidence_source_ids"), known_sources, f"{field} citations"
                    ),
                }
            )

    criteria = _list(value.get("acceptance_criteria"), "acceptance_criteria")
    if not criteria:
        raise ArtifactValidationError("At least one acceptance criterion is required.")
    _unique_ids(criteria, "AC-", "acceptance criteria")
    for criterion in criteria:
        refs = criterion.get("requirement_ids")
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or ref not in requirement_ids for ref in refs
        ):
            raise ArtifactValidationError(
                "Acceptance criteria must reference existing requirement identifiers."
            )
        if not refs:
            raise ArtifactValidationError(
                "Acceptance criteria must reference at least one requirement."
            )
        result["acceptance_criteria"].append(
            {
                "id": criterion["id"],
                "criterion": _text(criterion.get("criterion"), "acceptance criterion", limit=1500),
                "requirement_ids": refs,
                "evidence_source_ids": _citations(
                    criterion.get("evidence_source_ids"),
                    known_sources,
                    "acceptance criterion citations",
                ),
                "needs_user_input": criterion.get("needs_user_input"),
            }
        )
        criterion_result = result["acceptance_criteria"][-1]
        if not isinstance(criterion_result["needs_user_input"], bool):
            raise ArtifactValidationError("Acceptance criterion needs_user_input must be boolean.")
        if (
            re.search(r"\d", criterion_result["criterion"])
            and not criterion_result["evidence_source_ids"]
            and not criterion_result["needs_user_input"]
        ):
            raise ArtifactValidationError(
                "Unsubstantiated quantitative acceptance criteria must be marked needs_user_input."
            )
    return result


def validate_technology_comparison(value, known_sources, requested_options):
    if not isinstance(value, dict):
        raise ArtifactValidationError("Technology comparison must be a JSON object.")
    criteria = []
    for criterion in _list(value.get("selection_criteria"), "selection_criteria", limit=15):
        if not isinstance(criterion, dict):
            raise ArtifactValidationError("Each selection criterion must be an object.")
        criteria.append(
            {
                "name": _text(criterion.get("name"), "criterion name", limit=200),
                "reason": _text(criterion.get("reason"), "criterion reason", limit=1000),
            }
        )
    if not criteria:
        raise ArtifactValidationError("At least one technology selection criterion is required.")
    options = _list(value.get("options"), "options", limit=8)
    expected_names = {option.casefold() for option in requested_options}
    actual_names = []
    normalized_options = []
    for option in options:
        if not isinstance(option, dict):
            raise ArtifactValidationError("Each technology option must be an object.")
        name = _text(option.get("name"), "technology name", limit=120)
        actual_names.append(name.casefold())
        claims = []
        for claim in _list(option.get("evidence_backed_claims"), "evidence_backed_claims", limit=20):
            if not isinstance(claim, dict):
                raise ArtifactValidationError("Each technology evidence claim must be an object.")
            claims.append(
                {
                    "claim": _text(claim.get("claim"), "technology claim", limit=1200),
                    "evidence_source_ids": _citations(
                        claim.get("evidence_source_ids"),
                        known_sources,
                        "technology claim citations",
                    ),
                }
            )
        ratings = option.get("compatibility")
        if not isinstance(ratings, list) or len(ratings) > 20:
            raise ArtifactValidationError("compatibility must be a list of qualitative assessments.")
        compatibility = []
        for rating in ratings:
            if not isinstance(rating, dict) or rating.get("assessment") not in (
                "good",
                "partial",
                "poor",
                "unknown",
            ):
                raise ArtifactValidationError("Technology compatibility must be qualitative.")
            compatibility.append(
                {
                    "requirement_id": _text(rating.get("requirement_id"), "requirement_id", limit=30),
                    "assessment": rating["assessment"],
                    "reason": _text(rating.get("reason"), "compatibility reason", limit=1000),
                }
            )
        normalized_options.append(
            {
                "name": name,
                "role": _text(option.get("role"), "technology role", limit=500),
                "advantages": [
                    _text(item, "advantage", limit=1000)
                    for item in _list(option.get("advantages"), "advantages", limit=20)
                ],
                "disadvantages": [
                    _text(item, "disadvantage", limit=1000)
                    for item in _list(option.get("disadvantages"), "disadvantages", limit=20)
                ],
                "compatibility": compatibility,
                "operational_considerations": [
                    _text(item, "operational consideration", limit=1000)
                    for item in _list(
                        option.get("operational_considerations"),
                        "operational_considerations",
                        limit=20,
                    )
                ],
                "learning_considerations": [
                    _text(item, "learning consideration", limit=1000)
                    for item in _list(
                        option.get("learning_considerations"),
                        "learning_considerations",
                        limit=20,
                    )
                ],
                "evidence_backed_claims": claims,
                "unverified_assumptions": [
                    _text(item, "unverified assumption", limit=1000)
                    for item in _list(
                        option.get("unverified_assumptions"),
                        "unverified_assumptions",
                        limit=20,
                    )
                ],
                "missing_information": [
                    _text(item, "missing information", limit=1000)
                    for item in _list(option.get("missing_information"), "missing_information", limit=20)
                ],
            }
        )
    if len(actual_names) != len(set(actual_names)) or set(actual_names) != expected_names:
        raise ArtifactValidationError("Comparison options must match the user-supplied options exactly.")
    recommendation = value.get("recommendation")
    if not isinstance(recommendation, dict):
        raise ArtifactValidationError("recommendation must be an object.")
    recommendation_name = _text(recommendation.get("option"), "recommended option", limit=120)
    if recommendation_name.casefold() not in expected_names:
        raise ArtifactValidationError("The recommendation must be one of the compared options.")
    result = {
        "selection_criteria": criteria,
        "scoring_method": _text(value.get("scoring_method"), "scoring_method", limit=1500),
        "options": normalized_options,
        "recommendation_status": "provisional",
        "recommendation": {
            "option": recommendation_name,
            "reasoning": _text(recommendation.get("reasoning"), "recommendation reasoning", limit=2000),
            "limitations": [
                _text(item, "recommendation limitation", limit=1000)
                for item in _list(
                    recommendation.get("limitations"), "recommendation limitations", limit=20
                )
            ],
        },
        "insufficient_evidence": value.get("insufficient_evidence"),
    }
    if not isinstance(result["insufficient_evidence"], bool):
        raise ArtifactValidationError("insufficient_evidence must be boolean.")
    if not known_sources:
        result["insufficient_evidence"] = True
    return result


def _mermaid(value, label, *, kind):
    diagram = _text(value, label, limit=12000)
    first_line = diagram.splitlines()[0].strip()
    valid = (
        first_line.startswith(("flowchart ", "graph "))
        if kind == "flowchart"
        else first_line == "erDiagram"
    )
    if (
        not valid
        or re.search(r"<\s*/?\s*[A-Za-z!]", diagram)
        or "javascript:" in diagram.casefold()
        or "%%{init" in diagram
    ):
        raise ArtifactValidationError(f"{label} is not permitted Mermaid {kind} syntax.")
    return diagram


def validate_design(
    value,
    requirement_ids,
    known_sources,
    *,
    recommended_technology=None,
):
    if not isinstance(value, dict):
        raise ArtifactValidationError("System design must be a JSON object.")
    components = []
    component_items = _list(value.get("architecture_components"), "architecture_components", limit=30)
    if not component_items:
        raise ArtifactValidationError("At least one architecture component is required.")
    for component in component_items:
        if not isinstance(component, dict):
            raise ArtifactValidationError("Each architecture component must be an object.")
        components.append(
            {
                "name": _text(component.get("name"), "component name", limit=120),
                "responsibility": _text(component.get("responsibility"), "component responsibility", limit=1200),
                "requirement_ids": _existing_refs(
                    component.get("requirement_ids"), requirement_ids, "component requirement IDs"
                ),
                "evidence_source_ids": _citations(
                    component.get("evidence_source_ids"), known_sources, "component evidence citations"
                ),
            }
        )
    api_endpoints = []
    endpoint_keys = set()
    endpoint_items = _list(value.get("api_endpoints"), "api_endpoints", limit=50)
    if not endpoint_items:
        raise ArtifactValidationError("At least one proposed REST API endpoint is required.")
    for endpoint in endpoint_items:
        if not isinstance(endpoint, dict):
            raise ArtifactValidationError("Each API endpoint must be an object.")
        method = endpoint.get("method")
        path = endpoint.get("path")
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE") or not isinstance(path, str) or not _API_PATH.fullmatch(path):
            raise ArtifactValidationError("API endpoints need an allowed method and safe relative path.")
        key = method, path
        if key in endpoint_keys:
            raise ArtifactValidationError("API endpoints must be unique by method and path.")
        endpoint_keys.add(key)
        api_endpoints.append(
            {
                "method": method,
                "path": path,
                "purpose": _text(endpoint.get("purpose"), "endpoint purpose", limit=1000),
                "authentication": _text(endpoint.get("authentication"), "endpoint authentication", limit=300),
                "request_shape": _text(endpoint.get("request_shape"), "endpoint request shape", limit=1500, allow_empty=True),
                "response_shape": _text(endpoint.get("response_shape"), "endpoint response shape", limit=1500, allow_empty=True),
            }
        )

    entities = []
    entity_names = set()
    entity_items = _list(value.get("database_entities"), "database_entities", limit=30)
    if not entity_items:
        raise ArtifactValidationError("At least one proposed database entity is required.")
    for entity in entity_items:
        if not isinstance(entity, dict):
            raise ArtifactValidationError("Each database entity must be an object.")
        name = _text(entity.get("name"), "entity name", limit=64)
        if not _ENTITY_NAME.fullmatch(name) or name in entity_names:
            raise ArtifactValidationError("Database entity names must be unique identifiers.")
        entity_names.add(name)
        attributes = []
        for attribute in _list(entity.get("attributes"), "entity attributes", limit=40):
            if not isinstance(attribute, dict):
                raise ArtifactValidationError("Each database attribute must be an object.")
            attributes.append(
                {
                    "name": _text(attribute.get("name"), "attribute name", limit=100),
                    "type": _text(attribute.get("type"), "attribute type", limit=100),
                    "constraints": [
                        _text(item, "attribute constraint", limit=300)
                        for item in _list(
                            attribute.get("constraints"), "attribute constraints", limit=10
                        )
                    ],
                }
            )
        entities.append({"name": name, "attributes": attributes})
    relationships = []
    for relationship in _list(value.get("relationships"), "relationships", limit=50):
        if not isinstance(relationship, dict):
            raise ArtifactValidationError("Each database relationship must be an object.")
        source = relationship.get("from_entity")
        target = relationship.get("to_entity")
        if (
            not isinstance(source, str)
            or not isinstance(target, str)
            or source not in entity_names
            or target not in entity_names
        ):
            raise ArtifactValidationError("Database relationships must reference declared entities.")
        relationships.append(
            {
                "from_entity": source,
                "to_entity": target,
                "cardinality": _text(relationship.get("cardinality"), "relationship cardinality", limit=50),
                "description": _text(relationship.get("description"), "relationship description", limit=500),
            }
        )
    er_diagram = _mermaid(value.get("er_diagram"), "er_diagram", kind="erDiagram")
    if any(not re.search(rf"\b{re.escape(name)}\b", er_diagram) for name in entity_names):
        raise ArtifactValidationError("The ER diagram must include every declared database entity.")
    normalized_relationships = _validate_text_list(value.get("main_flows"), "main_flows", limit=20)
    if not normalized_relationships:
        raise ArtifactValidationError("At least one main request or processing flow is required.")
    selected_technology = _text(
        value.get("selected_technology"), "selected_technology", limit=120
    )
    if (
        recommended_technology is not None
        and selected_technology.casefold() != recommended_technology.casefold()
    ):
        raise ArtifactValidationError(
            "The design must use the user-approved technology recommendation."
        )
    return {
        "proposal_status": "proposed",
        "selected_technology": selected_technology,
        "technology_rationale": _text(
            value.get("technology_rationale"), "technology_rationale", limit=1500
        ),
        "architecture_components": components,
        "architecture_diagram": _mermaid(
            value.get("architecture_diagram"), "architecture_diagram", kind="flowchart"
        ),
        "data_flow_diagram": _mermaid(
            value.get("data_flow_diagram"), "data_flow_diagram", kind="flowchart"
        ),
        "main_flows": normalized_relationships,
        "api_endpoints": api_endpoints,
        "database_entities": entities,
        "relationships": relationships,
        "er_diagram": er_diagram,
        "security_considerations": _validate_text_list(
            value.get("security_considerations"), "security_considerations", limit=30
        ),
        "privacy_considerations": _validate_text_list(
            value.get("privacy_considerations"), "privacy_considerations", limit=30
        ),
        "reliability_considerations": _validate_text_list(
            value.get("reliability_considerations"), "reliability_considerations", limit=30
        ),
        "failure_handling": _validate_text_list(
            value.get("failure_handling"), "failure_handling", limit=30
        ),
        "tradeoffs": _validate_text_list(value.get("tradeoffs"), "tradeoffs", limit=30),
        "unresolved_decisions": _validate_text_list(
            value.get("unresolved_decisions"), "unresolved_decisions", limit=30
        ),
    }


def _existing_refs(value, allowed, label):
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in allowed for item in value):
        raise ArtifactValidationError(f"{label} must reference existing requirement identifiers.")
    return value


def _validate_text_list(value, label, *, limit=30):
    return [
        _text(item, label, limit=2000)
        for item in _list(value, label, limit=limit)
    ]
