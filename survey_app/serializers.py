from rest_framework import serializers
from .models import SurveySubmission

class SurveySubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveySubmission
        fields = ['id', 'user', 'form_type', 'status', 'submission_data', 'submitted_at']
        read_only_fields = ['id', 'user', 'submitted_at']


class SurveySubmissionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveySubmission
        fields = ['id', 'form_type', 'status', 'submitted_at']

