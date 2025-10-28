from rest_framework import serializers
from .models import SurveySubmission

class SurveySubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveySubmission
        fields = ['id', 'user', 'form_type', 'status', 'submission_data', 'submitted_at', 'form_name']
        read_only_fields = ['id', 'user', 'submitted_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Flatten nested submission_data if it has inner "submission_data"
        submission_data = data.get('submission_data', {})
        if isinstance(submission_data, dict) and 'submission_data' in submission_data:
            data['submission_data'] = submission_data.get('submission_data')

        return data


class SurveySubmissionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveySubmission
        fields = ['id', 'form_type', 'status', 'submitted_at', 'form_name']

