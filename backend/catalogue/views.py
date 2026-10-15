from datetime import date

from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.catalogue.models import EvidenceSource, ProblemStatement
from backend.catalogue.serializers import (
    EvidenceSourceSerializer,
    ProblemStatementDetailSerializer,
    ProblemStatementSerializer,
)
from backend.catalogue.services.similarity import find_similar_problems


class CataloguePagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 50


class ProblemStatementListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProblemStatementSerializer
    pagination_class = CataloguePagination

    def get_queryset(self):
        params = self.request.query_params
        queryset = ProblemStatement.objects.filter(status=ProblemStatement.Status.PUBLISHED)
        query = params.get("q", "").strip()
        if len(query) > 200:
            raise ValidationError({"q": "Search text must be 200 characters or fewer."})
        if query:
            matching_sources = EvidenceSource.objects.filter(problem_id=OuterRef("pk")).filter(
                Q(source_title__icontains=query)
                | Q(publisher__icontains=query)
                | Q(relevant_excerpt__icontains=query)
                | Q(source_url__icontains=query)
                | Q(source_type__icontains=query)
            )
            queryset = queryset.annotate(
                source_matches_query=Exists(matching_sources)
            ).filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(source_matches_query=True)
            )

        sector = params.get("sector", "").strip()
        if sector:
            queryset = queryset.filter(sector=sector)

        difficulty = params.get("difficulty", "").strip()
        if difficulty:
            valid_difficulties = ProblemStatement.Difficulty.values
            if difficulty not in valid_difficulties:
                raise ValidationError(
                    {"difficulty": f"Choose one of: {', '.join(valid_difficulties)}."}
                )
            queryset = queryset.filter(difficulty=difficulty)

        date_from = self._parse_date(params.get("source_date_from"), "source_date_from")
        date_to = self._parse_date(params.get("source_date_to"), "source_date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                {"source_date_to": "Must be on or after source_date_from."}
            )
        if date_from or date_to:
            source_dates = EvidenceSource.objects.filter(problem_id=OuterRef("pk"))
            if date_from:
                source_dates = source_dates.filter(publication_date__gte=date_from)
            if date_to:
                source_dates = source_dates.filter(publication_date__lte=date_to)
            queryset = queryset.annotate(
                source_matches_date=Exists(source_dates)
            ).filter(source_matches_date=True)

        ordering = params.get("ordering", "-created_at").strip()
        allowed_ordering = {
            "created_at": "created_at",
            "-created_at": "-created_at",
            "title": "title",
            "-title": "-title",
            "sector": "sector",
            "-sector": "-sector",
            "difficulty": "difficulty",
            "-difficulty": "-difficulty",
        }
        if ordering not in allowed_ordering:
            raise ValidationError(
                {"ordering": f"Choose one of: {', '.join(allowed_ordering)}."}
            )
        return (
            queryset.annotate(evidence_source_count=Count("evidence_sources"))
            .order_by(allowed_ordering[ordering], "id")
        )

    @staticmethod
    def _parse_date(value, parameter):
        if value is None or value == "":
            return None
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError
            return parsed
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {parameter: "Enter a date in YYYY-MM-DD format."}
            ) from error


class ProblemStatementDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProblemStatementDetailSerializer
    lookup_url_kwarg = "problem_id"
    lookup_field = "id"

    def get_queryset(self):
        return (
            ProblemStatement.objects.filter(status=ProblemStatement.Status.PUBLISHED)
            .annotate(evidence_source_count=Count("evidence_sources"))
            .prefetch_related("evidence_sources")
        )


class SimilarProblemListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, problem_id):
        problem = get_object_or_404(
            ProblemStatement.objects.filter(status=ProblemStatement.Status.PUBLISHED),
            id=problem_id,
        )
        results = find_similar_problems(problem)
        return Response(
            {
                "threshold": results.threshold,
                "count": len(results.candidates),
                "results": [
                    {
                        "problem": ProblemStatementSerializer(candidate.problem).data,
                        "similarity_score": candidate.score,
                        "matching_signals": candidate.matching_signals,
                    }
                    for candidate in results.candidates
                ],
            }
        )


class EvidenceSourceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EvidenceSourceSerializer
    pagination_class = CataloguePagination

    def get_queryset(self):
        problem = get_object_or_404(
            ProblemStatement.objects.filter(status=ProblemStatement.Status.PUBLISHED),
            id=self.kwargs["problem_id"],
        )
        return EvidenceSource.objects.filter(problem=problem).order_by(
            "-retrieved_at", "id"
        )


class EvidenceSourceDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EvidenceSourceSerializer
    lookup_url_kwarg = "source_id"

    def get_queryset(self):
        problem = get_object_or_404(
            ProblemStatement.objects.filter(status=ProblemStatement.Status.PUBLISHED),
            id=self.kwargs["problem_id"],
        )
        return EvidenceSource.objects.filter(problem=problem)
