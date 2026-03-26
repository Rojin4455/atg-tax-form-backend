from rest_framework import serializers
from .models import EstatePlanningSubmission


class EstatePlanningSubmissionSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = EstatePlanningSubmission
        fields = [
            'id',
            'user',
            'status',
            'current_step',
            'step1_personal',
            'step2_heirs_legal',
            'step3_distribution',
            'step4_financials',
            'staff_notes',
            'submitted_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'status', 'submitted_at', 'created_at', 'updated_at']


class EstatePlanningSubmissionStaffSerializer(serializers.ModelSerializer):
    """Full serializer for staff — status and staff_notes are writable."""
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = EstatePlanningSubmission
        fields = [
            'id',
            'user',
            'status',
            'current_step',
            'step1_personal',
            'step2_heirs_legal',
            'step3_distribution',
            'step4_financials',
            'staff_notes',
            'submitted_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'submitted_at', 'created_at', 'updated_at']
