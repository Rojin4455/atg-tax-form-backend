from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.parsers import MultiPartParser, JSONParser
from .models import SurveySubmission
from .serializers import SurveySubmissionSerializer, SurveySubmissionListSerializer
from .helpers import update_ghl_contact_tags_and_links, upload_tax_engagement_pdf_to_ghl, add_ghl_contact_tag, add_ghl_submission_note, add_ghl_engagement_letter_note

import json


def _is_admin_user(user):
    """Check if user is staff, superuser, or has admin profile."""
    if user.is_staff or user.is_superuser:
        return True
    try:
        from form_app.models import UserProfile
        profile = UserProfile.objects.get(user=user)
        return profile.is_admin
    except Exception:
        return False


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
            target_user_id = request.data.get("target_user_id")  # When admin fills form "for" a client
            
            # Normalize status: frontend may send 'draft', model expects 'drafted'
            if form_status == 'draft':
                form_status = 'drafted'
            
            # Determine submission owner: use target_user_id only when requester is admin
            submission_owner = request.user
            if target_user_id is not None and _is_admin_user(request.user):
                try:
                    submission_owner = User.objects.get(pk=int(target_user_id))
                except (User.DoesNotExist, ValueError, TypeError):
                    return Response(
                        {"error": "Invalid target_user_id or user not found"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Build submission_data by copying all request data (exclude target_user_id from stored data)
            submission_data = {}
            for key, value in request.data.items():
                if key in ('pdf_data', 'target_user_id'):
                    continue
                if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                    try:
                        submission_data[key] = json.loads(value)
                    except json.JSONDecodeError:
                        submission_data[key] = value
                else:
                    submission_data[key] = value
            
            if not form_type:
                return Response({"error": "Missing 'form_type'"}, status=status.HTTP_400_BAD_REQUEST)
            
            print(f"[DEBUG] Creating submission with form_type={form_type}, status={form_status}, user={submission_owner.id}")
            print(f"[DEBUG] PDF data present: {bool(pdf_data)}")
            
            submission = SurveySubmission.objects.create(
                user=submission_owner,
                form_type=form_type,
                form_name=form_name,
                status=form_status,
                submission_data=submission_data
            )
            
            print(f"[DEBUG] Created submission with ID: {submission.id}")
            
            update_ghl_contact_tags_and_links(
                user=submission_owner,
                form_type=submission.form_type,
                status=submission.status,
                form_id=submission.id,
                pdf_data=pdf_data
            )
            add_ghl_contact_tag(submission_owner, "tax toolbox accessed")
            
            if form_status == 'submitted':
                if form_type == 'personal':
                    add_ghl_contact_tag(submission_owner, "personal form submitted for pipeline")
                elif form_type == 'business':
                    add_ghl_contact_tag(submission_owner, "business form submitted for pipeline")
                elif form_type == 'rental':
                    add_ghl_contact_tag(submission_owner, "rental form submitted for pipeline")
                elif form_type == 'flip':
                    add_ghl_contact_tag(submission_owner, "flip form submitted for pipeline")
                add_ghl_submission_note(submission_owner, form_type, submission.id, timezone.now(), submission_data=submission_data)
            
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
        
        # Allow admins to view any user's submission, regular users can only view their own
        if request.user.is_staff or request.user.is_superuser:
            submission = get_object_or_404(
                SurveySubmission,
                id=id,
                form_type=form_type
            )
        else:
            submission = get_object_or_404(
                SurveySubmission,
                id=id,
                form_type=form_type,
                user=request.user
            )
        
        serializer = SurveySubmissionSerializer(submission)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request, id):
        form_type = request.query_params.get("type")
        if not form_type:
            return Response({"error": "Missing query param: type"}, status=status.HTTP_400_BAD_REQUEST)
        # Allow admins to update any user's submission; regular users only their own
        if _is_admin_user(request.user):
            submission = get_object_or_404(SurveySubmission, id=id, form_type=form_type)
        else:
            submission = get_object_or_404(SurveySubmission, id=id, form_type=form_type, user=request.user)
        
        # Preserve the existing data so we can merge into it instead of overwriting
        existing_data = submission.submission_data or {}

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
            # Ensure we have a plain dict (DRF may give QueryDict)
            submission_data = dict(request.data)

        # Normalize status values coming from the frontend
        if form_status == 'draft':
            form_status = 'drafted'

        # Prevent accidentally downgrading a submitted organizer back to draft/drafted
        old_status = submission.status
        if old_status == 'submitted' and form_status in ('draft', 'drafted', None, ''):
            form_status = 'submitted'
        
        # Check if status is changing to 'submitted' (one-time tag addition)
        is_newly_submitted = old_status != 'submitted' and form_status == 'submitted'

        # Merge new data into existing submission_data so partial updates
        # (e.g. section saves) do not wipe previously saved answers.
        if isinstance(existing_data, dict) and isinstance(submission_data, dict):
            merged_data = {**existing_data, **submission_data}
        else:
            # Fallback to incoming data if shapes are unexpected
            merged_data = submission_data
        
        # Update submission
        submission.form_type = form_type
        submission.status = form_status
        submission.form_name = form_name
        submission.submission_data = merged_data
        submission.save()
        
        # Use submission owner for GHL (so client gets tags when admin fills for them)
        submission_owner = submission.user
        update_ghl_contact_tags_and_links(
            user=submission_owner,
            form_type=submission.form_type,
            status=submission.status,
            form_id=submission.id,
            pdf_data=pdf_data  # Pass the PDF data
        )
        add_ghl_contact_tag(submission_owner, "tax toolbox accessed")
        if is_newly_submitted:
            if form_type == 'personal':
                add_ghl_contact_tag(submission_owner, "personal form submitted for pipeline")
            elif form_type == 'business':
                add_ghl_contact_tag(submission_owner, "business form submitted for pipeline")
            elif form_type == 'rental':
                add_ghl_contact_tag(submission_owner, "rental form submitted for pipeline")
            elif form_type == 'flip':
                add_ghl_contact_tag(submission_owner, "flip form submitted for pipeline")
            add_ghl_submission_note(submission_owner, submission.form_type, submission.id, timezone.now(), submission_data=submission.submission_data)
        
        return Response({"message": "Submission updated"}, status=status.HTTP_200_OK)
    

    def delete(self, request, id):
        form_type = request.query_params.get("type")
        if not form_type:
            return Response({"error": "Missing query param: type"}, status=status.HTTP_400_BAD_REQUEST)
        if _is_admin_user(request.user):
            submission = get_object_or_404(SurveySubmission, id=id, form_type=form_type)
        else:
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


class SurveySubmissionPublicDetailView(APIView):
    """Public endpoint: fetch a submission by ID only. No auth required. Accepts ID in any format (UUID string)."""
    permission_classes = [AllowAny]

    def get(self, request, id):
        submission = get_object_or_404(SurveySubmission, id=id)
        serializer = SurveySubmissionSerializer(submission)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SurveySubmissionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        submissions = SurveySubmission.objects.filter(user=request.user).order_by('-submitted_at')
        serializer = SurveySubmissionListSerializer(submissions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class FormSubmissionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        form_type = request.GET.get("form_type", None)
        for_user_id = request.GET.get("for_user_id", None)

        # When admin requests another user's forms (e.g. "fill for client"), use that user
        if for_user_id is not None and _is_admin_user(request.user):
            try:
                target_user = User.objects.get(pk=int(for_user_id))
                submissions = SurveySubmission.objects.filter(user=target_user)
            except (User.DoesNotExist, ValueError, TypeError):
                submissions = SurveySubmission.objects.filter(user=request.user)
        else:
            submissions = SurveySubmission.objects.filter(user=request.user)

        valid_form_types = list(dict(SurveySubmission.FORM_TYPES).keys())
        if 'flip' not in valid_form_types:
            valid_form_types.append('flip')
        if form_type and form_type in valid_form_types:
            submissions = submissions.filter(form_type=form_type)
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
            
            # Add "tax toolbox accessed" tag when user signs tax engagement letter
            add_ghl_contact_tag(request.user, "tax toolbox accessed")
            # Add GHL note for engagement letter signed
            add_ghl_engagement_letter_note(request.user, obj.date_signed)
            
            return Response(self.serializer_class(obj).data, status=201 if created else 200)
        return Response(serializer.errors, status=400)