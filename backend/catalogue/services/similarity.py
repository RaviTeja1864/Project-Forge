import unicodedata
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Count

from backend.catalogue.models import ProblemStatement


@dataclass(frozen=True)
class SimilarityCandidate:
    problem: ProblemStatement
    score: float
    matching_signals: tuple[str, ...]


@dataclass(frozen=True)
class SimilarityResults:
    threshold: float
    candidates: tuple[SimilarityCandidate, ...]


def normalize_text(value):
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(
        "".join(character if character.isalnum() else " " for character in normalized).split()
    )


def _token_similarity(left, right):
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0, 0
    shared = left_tokens & right_tokens
    return len(shared) / len(left_tokens | right_tokens), len(shared)


def score_problems(left, right):
    left_title = normalize_text(left.title)
    right_title = normalize_text(right.title)
    left_description = normalize_text(left.description)
    right_description = normalize_text(right.description)

    title_similarity, shared_title_terms = _token_similarity(left_title, right_title)
    description_similarity, shared_description_terms = _token_similarity(
        left_description, right_description
    )
    signals = []
    if left_title and left_title == right_title:
        score = 1.0
        signals.append("Normalized titles match exactly")
    else:
        score = 0.65 * title_similarity + 0.35 * description_similarity
        if shared_title_terms:
            signals.append(f"Titles share {shared_title_terms} normalized term(s)")
    if left_description and left_description == right_description:
        signals.append("Normalized descriptions match exactly")
    elif shared_description_terms:
        signals.append(
            f"Descriptions share {shared_description_terms} normalized term(s)"
        )
    return round(score, 4), tuple(signals)


def find_similar_problems(problem):
    threshold = settings.PROBLEM_SIMILARITY_THRESHOLD
    limit = settings.PROBLEM_SIMILARITY_LIMIT
    if not 0 <= threshold <= 1:
        raise ImproperlyConfigured("PROBLEM_SIMILARITY_THRESHOLD must be between 0 and 1.")
    if not 1 <= limit <= 20:
        raise ImproperlyConfigured("PROBLEM_SIMILARITY_LIMIT must be between 1 and 20.")

    candidates = []
    problem_sector = normalize_text(problem.sector)
    for candidate in ProblemStatement.objects.filter(
        status=ProblemStatement.Status.PUBLISHED
    ).exclude(pk=problem.pk).annotate(evidence_source_count=Count("evidence_sources")):
        candidate_sector = normalize_text(candidate.sector)
        if problem_sector and candidate_sector and problem_sector != candidate_sector:
            continue
        score, signals = score_problems(problem, candidate)
        if score >= threshold and signals:
            candidates.append(SimilarityCandidate(candidate, score, signals))

    candidates.sort(key=lambda candidate: (-candidate.score, str(candidate.problem.pk)))
    return SimilarityResults(threshold, tuple(candidates[:limit]))
