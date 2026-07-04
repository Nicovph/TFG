"""Serializers for the initial interpretation API surface."""

from rest_framework import serializers


class ApiHealthSerializer(serializers.Serializer):
    """Represent non-sensitive API health metadata for connectivity checks."""

    status = serializers.ChoiceField(choices=["ok"]) # Only accepts "ok".
    service = serializers.ChoiceField(choices=["django"])
    api_version = serializers.CharField(max_length=32)
    features = serializers.ListField( # Validates lists. Besides, features is used to represent the capabilities of the API
        # (feature discovery).
        child=serializers.CharField(max_length=64), # child validates the inner elements of the list.
                                                    # Maximum of 64 characters for each feature.
        allow_empty=False, # The list of features must not be empty.
        max_length=10, # Maximum of 10 features.
    )


class MockInterpretationSerializer(serializers.Serializer):
    """Represent the deterministic mock interpretation returned in iteration two."""

    kind = serializers.ChoiceField(choices=["mock_interpretation"])
    summary = serializers.CharField(max_length=500)
    tone = serializers.ChoiceField(choices=["neutral"])
    signals = serializers.ListField(
        child=serializers.CharField(max_length=200),
        allow_empty=False,
        max_length=10,
    )
    visual_concepts = serializers.ListField(
        child=serializers.CharField(max_length=64),
        allow_empty=False,
        max_length=10,
    )