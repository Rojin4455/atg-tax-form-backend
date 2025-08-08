from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import SurveySubmission
from .serializers import SurveySubmissionSerializer, SurveySubmissionListSerializer
from .helpers import update_ghl_contact_tags_and_links


class SurveySubmissionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        form_type = request.data.get("form_type")
        form_status = request.data.get("status")

        if not form_type:
            return Response({"error": "Missing 'form_type'"}, status=status.HTTP_400_BAD_REQUEST)

        submission = SurveySubmission.objects.create(
            user=request.user,
            form_type=form_type,
            status=form_status or 'drafted',
            submission_data=request.data
        )


        update_ghl_contact_tags_and_links(
            user=request.user,
            form_type=submission.form_type,
            status=submission.status,
            form_id=submission.id
        )
        return Response({"id": submission.id}, status=status.HTTP_201_CREATED)


class SurveySubmissionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        form_type = request.query_params.get("type")

        if not form_type:
            return Response({"error": "Missing query param: type"}, status=status.HTTP_400_BAD_REQUEST)

        submission = get_object_or_404(
            SurveySubmission,
            id=id,
            form_type=form_type,
            user=request.user  # ✅ restrict to user
        )

        serializer = SurveySubmissionSerializer(submission)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        submission = get_object_or_404(SurveySubmission, id=id, user=request.user)

        submission.form_type = request.data.get("form_type", submission.form_type)
        submission.status = request.data.get("status", submission.status)
        submission.submission_data = request.data
        submission.save()

        update_ghl_contact_tags_and_links(
            user=request.user,
            form_type=submission.form_type,
            status=submission.status,
            form_id=submission.id
        )



        return Response({"message": "Submission updated"}, status=status.HTTP_200_OK)


class SurveySubmissionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        submissions = SurveySubmission.objects.filter(user=request.user).order_by('-submitted_at')
        serializer = SurveySubmissionListSerializer(submissions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
