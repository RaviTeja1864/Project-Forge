from backend.workspaces.models import (
    ImplementationEvidence,
    RequirementVerification,
)
from backend.workspaces.services.planning import (
    criteria_for_requirement,
    requirements_artifact_is_outdated,
)


def current_evidence(requirements, requirement_id):
    return list(
        ImplementationEvidence.objects.filter(
            requirements_artifact=requirements,
            requirement_id=requirement_id,
            corrections__isnull=True,
        ).order_by("created_at", "pk")
    )


def evaluate_requirement(requirements, requirement_id, evidence):
    criteria = criteria_for_requirement(requirements, requirement_id)
    manually_reviewed = ImplementationEvidence.ReviewBasis.MANUALLY_REVIEWED
    requirement_absence = any(
        item.acceptance_criterion_id == ""
        and item.result == ImplementationEvidence.Result.ABSENT
        and item.review_basis == manually_reviewed
        for item in evidence
    )
    criterion_results = []
    for criterion in criteria:
        related = [
            item
            for item in evidence
            if item.acceptance_criterion_id == criterion["id"]
        ]
        reviewed = [
            item for item in related if item.review_basis == manually_reviewed
        ]
        passing_checks = [
            item
            for item in related
            if item.evidence_type == ImplementationEvidence.EvidenceType.VERIFICATION_CHECK
            and item.result == ImplementationEvidence.Result.PASSED
            and item.review_basis == manually_reviewed
        ]
        absent = any(
            item.result == ImplementationEvidence.Result.ABSENT
            for item in reviewed
        )
        failed = any(
            item.result == ImplementationEvidence.Result.FAILED for item in reviewed
        )
        criterion_results.append(
            {
                "acceptance_criterion_id": criterion["id"],
                "result": (
                    "missing"
                    if absent
                    else "failed"
                    if failed
                    else "passed"
                    if passing_checks
                    else "unverified"
                ),
                "evidence_ids": [str(item.pk) for item in related],
            }
        )

    if requirement_absence or (criteria and all(item["result"] == "missing" for item in criterion_results)):
        result = RequirementVerification.Status.MISSING
        rationale = "A manually reviewed inspection explicitly records the requirement as absent."
    elif criteria and all(item["result"] == "passed" for item in criterion_results):
        recorded_checks = [
            item
            for item in evidence
            if item.evidence_type == ImplementationEvidence.EvidenceType.VERIFICATION_CHECK
        ]
        if all(
            item.result == ImplementationEvidence.Result.PASSED
            and item.review_basis == manually_reviewed
            for item in recorded_checks
        ):
            result = RequirementVerification.Status.VERIFIED
            rationale = (
                "Every linked acceptance criterion has a passing verification check "
                "recorded as manually reviewed. No automated command or repository inspection was run."
            )
        else:
            result = RequirementVerification.Status.PARTIALLY_IMPLEMENTED
            rationale = "Some evidence supports the criteria, but one or more recorded checks did not pass review."
    elif any(
        item["result"] in ("passed", "failed", "missing")
        for item in criterion_results
    ):
        result = RequirementVerification.Status.PARTIALLY_IMPLEMENTED
        rationale = (
            "Reviewed evidence shows that some linked acceptance criteria are met, "
            "failed, or absent while others remain unmet or unverified."
        )
    else:
        result = RequirementVerification.Status.UNVERIFIED
        rationale = (
            "Evidence is absent, inconclusive, self-reported, or insufficient to establish "
            "the linked acceptance criteria."
        )

    return {
        "status": result,
        "rationale": rationale,
        "evidence_ids": [str(item.pk) for item in evidence],
        "criterion_results": criterion_results,
    }


def verification_is_outdated(verification):
    if requirements_artifact_is_outdated(verification.requirements_artifact):
        return True
    current_ids = {
        str(item.pk)
        for item in current_evidence(
            verification.requirements_artifact,
            verification.requirement_id,
        )
    }
    return current_ids != set(verification.evidence_ids)


def current_verification_payload(verification):
    is_outdated = verification_is_outdated(verification)
    return {
        "id": str(verification.pk),
        "requirements_artifact_id": str(verification.requirements_artifact_id),
        "requirements_version": verification.requirements_artifact.version_number,
        "requirement_id": verification.requirement_id,
        "status": (
            RequirementVerification.Status.UNVERIFIED
            if is_outdated
            else verification.status
        ),
        "recorded_status": verification.status,
        "is_outdated": is_outdated,
        "rationale": (
            "This decision is stale because the requirement version or evidence has changed; "
            "rerun verification."
            if is_outdated
            else verification.rationale
        ),
        "evidence_ids": verification.evidence_ids,
        "criterion_results": verification.criterion_results,
        "actor_id": verification.actor_id,
        "created_at": verification.created_at,
    }
