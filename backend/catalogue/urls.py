from django.urls import path

from backend.catalogue.views import (
    EvidenceSourceDetailView,
    EvidenceSourceListView,
    ProblemStatementDetailView,
    ProblemStatementListView,
    SimilarProblemListView,
)

urlpatterns = [
    path("", ProblemStatementListView.as_view(), name="problem-list"),
    path("<uuid:problem_id>/", ProblemStatementDetailView.as_view(), name="problem-detail"),
    path(
        "<uuid:problem_id>/similar/",
        SimilarProblemListView.as_view(),
        name="problem-similar",
    ),
    path(
        "<uuid:problem_id>/sources/",
        EvidenceSourceListView.as_view(),
        name="problem-sources",
    ),
    path(
        "<uuid:problem_id>/sources/<uuid:source_id>/",
        EvidenceSourceDetailView.as_view(),
        name="problem-source-detail",
    ),
]
