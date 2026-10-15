from rest_framework import serializers

from backend.catalogue.models import EvidenceSource, ProblemStatement


class EvidenceSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceSource
        fields = (
            "id",
            "source_url",
            "source_title",
            "publisher",
            "publication_date",
            "retrieved_at",
            "relevant_excerpt",
            "source_type",
        )
        read_only_fields = fields


class ProblemStatementSerializer(serializers.ModelSerializer):
    evidence_source_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProblemStatement
        fields = (
            "id",
            "title",
            "description",
            "sector",
            "difficulty",
            "status",
            "evidence_source_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ProblemStatementDetailSerializer(ProblemStatementSerializer):
    evidence_sources = EvidenceSourceSerializer(many=True, read_only=True)

    class Meta(ProblemStatementSerializer.Meta):
        fields = (*ProblemStatementSerializer.Meta.fields, "evidence_sources")
