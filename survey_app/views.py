from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from rest_framework.parsers import MultiPartParser, JSONParser
from .models import SurveySubmission
from .serializers import SurveySubmissionSerializer, SurveySubmissionListSerializer
from .helpers import update_ghl_contact_tags_and_links,upload_tax_engagement_pdf_to_ghl

import json
class SurveySubmissionCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]  # Add parsers
    
    def post(self, request):
        try:
            print(f"[DEBUG] Request content type: {request.content_type}")
            print(f"[DEBUG] Request data keys: {list(request.data.keys())}")
            
            # Extract data (DRF parsers handle both JSON and multipart automatically)
            form_type = request.data.get("form_type")
            form_name = request.data.get("form_name")
            form_status = request.data.get("status", "drafted")
            pdf_data = request.data.get("pdf_data")
            
            # Build submission_data by copying all request data
            submission_data = {}
            for key, value in request.data.items():
                if key == 'pdf_data':
                    continue  # Don't store PDF data in submission_data
                    
                # Parse JSON strings back to objects if they were stringified for FormData
                if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                    try:
                        submission_data[key] = json.loads(value)
                    except json.JSONDecodeError:
                        submission_data[key] = value
                else:
                    submission_data[key] = value
            
            if not form_type:
                return Response({"error": "Missing 'form_type'"}, status=status.HTTP_400_BAD_REQUEST)
            
            print(f"[DEBUG] Creating submission with form_type={form_type}, status={form_status}")
            print(f"[DEBUG] PDF data present: {bool(pdf_data)}")
            
            # Create submission
            submission = SurveySubmission.objects.create(
                user=request.user,
                form_type=form_type,
                form_name=form_name,
                status=form_status,
                submission_data=submission_data
            )
            
            print(f"[DEBUG] Created submission with ID: {submission.id}")
            
            # Update GHL with PDF data if provided
            update_ghl_contact_tags_and_links(
                user=request.user,
                form_type=submission.form_type,
                status=submission.status,
                form_id=submission.id,
                pdf_data=pdf_data
            )
            
            return Response({"id": submission.id}, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print(f"[ERROR] Exception in SurveySubmissionCreateView.post: {e}")
            import traceback
            print(f"[ERROR] Full traceback: {traceback.format_exc()}")
            return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SurveySubmissionDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]  # Add parsers
    
    def get(self, request, id):
        form_type = request.query_params.get("type")
        if not form_type:
            return Response({"error": "Missing query param: type"}, status=status.HTTP_400_BAD_REQUEST)
        
        submission = get_object_or_404(
            SurveySubmission,
            id=id,
            form_type=form_type,
            user=request.user
        )
        
        serializer = SurveySubmissionSerializer(submission)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request, id):
        submission = get_object_or_404(SurveySubmission, id=id, user=request.user)
        
        # Handle both JSON and multipart form data
        if request.content_type.startswith('multipart/form-data'):
            # Extract form data from multipart request
            form_type = request.data.get("form_type", submission.form_type)
            form_name = request.data.get("form_name", submission.form_name)
            form_status = request.data.get("status", submission.status)
            pdf_data = request.data.get("pdf_data")
            
            # Parse JSON fields that were stringified
            submission_data = {}
            for key, value in request.data.items():
                if key not in ['form_type', 'status', 'pdf_data']:
                    try:
                        if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                            submission_data[key] = json.loads(value)
                        else:
                            submission_data[key] = value
                    except json.JSONDecodeError:
                        submission_data[key] = value
            
            # Add form_type and status to submission_data
            submission_data['form_type'] = form_type
            submission_data['status'] = form_status
            submission_data['form_name'] = form_name
            
        else:
            # Handle regular JSON request
            form_type = request.data.get("form_type", submission.form_type)
            form_status = request.data.get("status", submission.status)
            form_name = request.data.get("form_name", submission.form_name)
            
            pdf_data = request.data.get("pdf_data")
            submission_data = request.data
        
        # Update submission
        submission.form_type = form_type
        submission.status = form_status
        submission.form_name=form_name
        submission.submission_data = submission_data
        submission.save()
        
        # Update GHL with PDF data if provided
        update_ghl_contact_tags_and_links(
            user=request.user,
            form_type=submission.form_type,
            status=submission.status,
            form_id=submission.id,
            pdf_data=pdf_data  # Pass the PDF data
        )
        
        return Response({"message": "Submission updated"}, status=status.HTTP_200_OK)
    

    def delete(self, request, id):
        form_type = request.query_params.get("type")
        if not form_type:
            return Response({"error": "Missing query param: type"}, status=status.HTTP_400_BAD_REQUEST)

        submission = get_object_or_404(
            SurveySubmission,
            id=id,
            form_type=form_type,
            user=request.user
        )

        submission.delete()
        return Response(
            {"message": "Form submission deleted successfully."},
            status=status.HTTP_200_OK
        )


class SurveySubmissionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        submissions = SurveySubmission.objects.filter(user=request.user).order_by('-submitted_at')
        serializer = SurveySubmissionListSerializer(submissions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class FormSubmissionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get optional form_type from query params
        form_type = request.GET.get("form_type", None)

        # Filter submissions by user
        submissions = SurveySubmission.objects.filter(user=request.user)

        # If form_type is provided, filter further
        if form_type in dict(SurveySubmission.FORM_TYPES).keys():
            submissions = submissions.filter(form_type=form_type)
            # submissions.delete()
        submissions = submissions.order_by('-submitted_at')
        serializer = SurveySubmissionListSerializer(submissions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)




from .models import TaxEngagementLetter
from .serializers import TaxEngagementLetterSerializer
from rest_framework import generics


class TaxEngagementLetterView(generics.GenericAPIView):
    serializer_class = TaxEngagementLetterSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get the current user's existing tax engagement form, if any"""
        try:
            letter = TaxEngagementLetter.objects.get(user=request.user)
            serializer = self.serializer_class(letter)
            return Response(serializer.data, status=200)
        except TaxEngagementLetter.DoesNotExist:
            return Response({"detail": "No existing form found."}, status=404)

    def post(self, request):
        """Create or update the tax engagement letter for the current user"""
        serializer = self.serializer_class(data=request.data)

        pdf_data = request.data.get("pdf_data")

        if serializer.is_valid():
            # Update if exists, else create new
            obj, created = TaxEngagementLetter.objects.update_or_create(
                user=request.user,
                defaults={
                    'taxpayer_name': serializer.validated_data['taxpayer_name'],
                    'signature': serializer.validated_data['signature'],
                    'date_signed': serializer.validated_data['date_signed']
                }
            )

            if pdf_data:
                upload_tax_engagement_pdf_to_ghl(request.user, pdf_data)
            return Response(self.serializer_class(obj).data, status=201 if created else 200)
        return Response(serializer.errors, status=400)