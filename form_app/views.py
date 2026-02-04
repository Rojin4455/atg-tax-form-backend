# views.py
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import Q, Prefetch
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import transaction
from django.utils import timezone
import json
from .models import (
    TaxFormSubmission, FormType, FormSection, FormQuestion,
    FormAnswer, FormSectionData, DependentInfo, BusinessOwnerInfo, FormAuditLog,
    UserProfile
)
from django.utils.dateparse import parse_datetime

from .serializers import (
    TaxFormSubmissionSerializer, TaxFormSubmissionCreateSerializer,
    UserSignupSerializer, 
    UserLoginSerializer, 
    AdminLoginSerializer,
    UserProfileSerializer,
    UserLogoutSerializer,
    RequestOTPSerializer,
    SubmitOTPSerializer,
    AdminProfileSerializer,
    CreateAdminSerializer,
    UpdateAdminPermissionsSerializer,
    ResetAdminPasswordSerializer
)
from .utils import get_client_ip,create_or_update_user_profile
from survey_app.helpers import add_ghl_contact_tag
import logging
from django.core.cache import cache




logger = logging.getLogger(__name__)

class TaxFormSubmissionViewSet(viewsets.ModelViewSet):
    """ViewSet for handling tax form submissions"""
    queryset = TaxFormSubmission.objects.all()
    serializer_class = TaxFormSubmissionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter queryset based on user permissions"""
        queryset = super().get_queryset()
        
        # If not staff, only show user's own submissions
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        
        # Optimize queries with select_related and prefetch_related
        queryset = queryset.select_related('form_type').prefetch_related(
            'answers__question__section',
            'section_data__section',
            'dependents',
            'business_owners',
            'vehicles',
            'charitable_contributions'
        )
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'create':
            return TaxFormSubmissionCreateSerializer
        return TaxFormSubmissionSerializer
    
    def create(self, request, *args, **kwargs):
        """Create a new tax form submission"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Add client information to context
        context = {
            'request': request,
            'client_ip': get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')
        }
        serializer.context.update(context)
        
        submission = serializer.save()
        
        # Add "tax toolbox accessed" tag when user submits tax form
        add_ghl_contact_tag(request.user, "tax toolbox accessed")
        
        # Return detailed response
        response_serializer = TaxFormSubmissionSerializer(submission)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['get'])
    def formatted_data(self, request, pk=None):
        """Return formatted form data for display"""
        submission = self.get_object()
        
        formatted_data = {
            'submission_info': {
                'id': str(submission.id),
                'form_type': submission.form_type.display_name,
                'status': submission.get_status_display(),
                'submission_date': submission.submission_date,
                'created_at': submission.created_at
            },
            'sections': []
        }
        
        # Group answers by section
        sections_data = {}
        for section_data in submission.section_data.all():
            sections_data[section_data.section_key] = {
                'title': section_data.section.title,
                'order': section_data.section.order,
                'questions': []
            }
        
        # Add questions and answers
        for answer in submission.answers.select_related('question__section'):
            section_key = answer.question.section.section_key
            if section_key in sections_data:
                field_type = answer.question.field_type
                is_sensitive = answer.question.is_sensitive
                raw_value = answer.get_value()

                # If it's the specific encrypted field you want to override
                if answer.question.question_text.strip() == "Business Name":
                    if field_type == 'encrypted':
                        raw_value = decrypt_value(raw_value)
                        field_type = 'text'
                        is_sensitive = False

                sections_data[section_key]['questions'].append({
                    'question': answer.question.question_text,
                    'answer': raw_value,
                    'field_type': field_type,
                    'is_sensitive': is_sensitive
                })

        
        # Sort sections by order and add to response
        sorted_sections = sorted(sections_data.items(), key=lambda x: x[1]['order'])
        formatted_data['sections'] = [
            {'section_key': key, **data} for key, data in sorted_sections
        ]
        
        # Add structured data
        if submission.dependents.exists():
            formatted_data['dependents'] = [
                {
                    'name': f"{dep.first_name} {dep.last_name}",
                    'relationship': dep.relationship,
                    'date_of_birth': dep.date_of_birth,
                    'months_lived': dep.months_lived_with_you,
                    'is_student': dep.is_full_time_student,
                    'care_expense': dep.child_care_expense
                }
                for dep in submission.dependents.all()
            ]
        
        if submission.business_owners.exists():
            formatted_data['business_owners'] = [
                {
                    'name': f"{owner.first_name} {owner.last_name}",
                    'ownership_percentage': owner.ownership_percentage,
                    'address': f"{owner.address}, {owner.city}, {owner.state} {owner.zip_code}",
                    'phone': owner.work_phone
                }
                for owner in submission.business_owners.all()
            ]
        
        return Response(formatted_data)
    
    @action(detail=True, methods=['get'])
    def generate_pdf(self, request, pk=None):
        """Generate PDF for the form submission"""
        submission = self.get_object()
        
        try:
            pdf_generator = PDFGenerator()
            pdf_content = pdf_generator.generate_tax_form_pdf(submission)
            
            response = HttpResponse(pdf_content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="tax_form_{submission.id}.pdf"'
            return response
            
        except Exception as e:
            return Response(
                {'error': f'Failed to generate PDF: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def form_statistics(self, request):
        """Get statistics about form submissions"""
        queryset = self.get_queryset()
        
        stats = {
            'total_submissions': queryset.count(),
            'by_status': {},
            'by_form_type': {},
            'recent_submissions': queryset.order_by('-created_at')[:5].values(
                'id', 'form_type__name', 'status', 'created_at'
            )
        }
        
        # Count by status
        for status_choice in TaxFormSubmission.STATUS_CHOICES:
            count = queryset.filter(status=status_choice[0]).count()
            stats['by_status'][status_choice[1]] = count
        
        # Count by form type
        form_types = FormType.objects.all()
        for form_type in form_types:
            count = queryset.filter(form_type=form_type).count()
            stats['by_form_type'][form_type.display_name] = count
        
        return Response(stats)
    

    @action(detail=False, methods=['get'], url_path='user-forms')
    def list_user_forms(self, request):
        """List all form submissions (personal and business) for the current user with basic details"""
        queryset = self.get_queryset().only(
            'id', 'form_type__display_name', 'status', 'submission_date', 'created_at'
        ).select_related('form_type')

        results = [
            {
                'id': submission.id,
                'form_type': submission.form_type.display_name,
                'status': submission.get_status_display(),
                'submission_date': submission.submission_date,
                'created_at': submission.created_at,
            }
            for submission in queryset
        ]

        return Response(results)
    
    def update(self, request, *args, **kwargs):
        """Update entire tax form submission"""
        submission = self.get_object()
        
        # Check if user has permission to update
        if not request.user.is_staff and submission.user != request.user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if status is being changed to 'submitted'
        old_status = submission.status
        new_status = request.data.get('status', old_status)
        form_type_name = request.data.get('form_type', submission.form_type.name if submission.form_type else None)
        
        # Use the create serializer for updates too
        serializer = TaxFormSubmissionCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        
        # Store old data for audit
        old_data = self._get_submission_data_for_audit(submission)
        
        # Update the submission
        with transaction.atomic():
            updated_submission = self._update_submission(submission, serializer.validated_data)
            
            # Check if status changed to 'submitted' and add tag accordingly
            if old_status != 'submitted' and new_status == 'submitted' and submission.user:
                if form_type_name == 'personal':
                    add_ghl_contact_tag(submission.user, "personal form submitted for pipeline")
                elif form_type_name == 'business':
                    add_ghl_contact_tag(submission.user, "business form submitted for pipeline")
            
            # Create audit log
            FormAuditLog.objects.create(
                submission=submission,
                action='updated',
                user=request.user,
                changes={
                    'sections_updated': list(serializer.validated_data['sections'].keys()),
                    'timestamp': timezone.now().isoformat()
                },
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        
        response_serializer = TaxFormSubmissionSerializer(updated_submission)
        return Response(response_serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """Partially update tax form submission"""
        submission = self.get_object()
        
        # Check permissions
        if not request.user.is_staff and submission.user != request.user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if status is being changed to 'submitted'
        old_status = submission.status
        new_status = request.data.get('status', old_status)
        form_type_name = submission.form_type.name if submission.form_type else None
        
        with transaction.atomic():
            updated_fields = []
            
            # Handle direct field updates
            direct_fields = ['status', 'processing_notes']
            for field in direct_fields:
                if field in request.data:
                    old_value = getattr(submission, field)
                    new_value = request.data[field]
                    setattr(submission, field, new_value)
                    updated_fields.append(f"{field}: {old_value} → {new_value}")
            
            # Handle section updates
            if 'sections' in request.data:
                sections_data = request.data['sections']
                for section_key, section_data in sections_data.items():
                    self._update_section(submission, section_key, section_data)
                    updated_fields.append(f"Section: {section_key}")
            
            submission.save()
            
            # Check if status changed to 'submitted' and add tag accordingly
            if old_status != 'submitted' and new_status == 'submitted' and submission.user:
                if form_type_name == 'personal':
                    add_ghl_contact_tag(submission.user, "personal form submitted for pipeline")
                elif form_type_name == 'business':
                    add_ghl_contact_tag(submission.user, "business form submitted for pipeline")
            
            # Create audit log
            FormAuditLog.objects.create(
                submission=submission,
                action='partial_update',
                user=request.user,
                changes={'updated_fields': updated_fields},
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        
        response_serializer = TaxFormSubmissionSerializer(submission)
        return Response(response_serializer.data)
    
    @action(detail=True, methods=['put', 'patch'])
    def update_section(self, request, pk=None):
        """Update specific section of the form"""
        submission = self.get_object()
        section_key = request.data.get('section_key')
        section_data = request.data.get('section_data')
        
        if not section_key or not section_data:
            return Response(
                {'error': 'section_key and section_data are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check permissions
        if not request.user.is_staff and submission.user != request.user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        with transaction.atomic():
            self._update_section(submission, section_key, section_data)
            
            # Create audit log
            FormAuditLog.objects.create(
                submission=submission,
                action='section_updated',
                user=request.user,
                changes={
                    'section_key': section_key,
                    'questions_updated': list(section_data.get('questionsAndAnswers', {}).keys())
                },
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        
        # Return updated section data
        updated_section = FormSectionData.objects.get(
            submission=submission,
            section_key=section_key
        )
        return Response({
            'section_key': section_key,
            'data': updated_section.data,
            'message': f'Section {section_key} updated successfully'
        })
    
    @action(detail=True, methods=['patch'])
    def update_question(self, request, pk=None):
        """Update individual question answer"""
        submission = self.get_object()
        question_key = request.data.get('question_key')
        new_answer = request.data.get('answer')
        section_key = request.data.get('section_key')
        
        if not all([question_key, section_key]):
            return Response(
                {'error': 'question_key and section_key are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check permissions
        if not request.user.is_staff and submission.user != request.user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            with transaction.atomic():
                # Get the question
                section = FormSection.objects.get(
                    form_type=submission.form_type,
                    section_key=section_key
                )
                question = FormQuestion.objects.get(
                    section=section,
                    question_key=question_key
                )
                
                # Update the answer
                form_answer, created = FormAnswer.objects.get_or_create(
                    submission=submission,
                    question=question,
                    question_key=question_key
                )
                
                old_value = form_answer.get_value()
                form_answer.set_value(new_answer)
                form_answer.save()
                
                # Also update the section data
                section_data, created = FormSectionData.objects.get_or_create(
                    submission=submission,
                    section=section,
                    section_key=section_key,
                    defaults={'data': {}}
                )
                
                if 'questionsAndAnswers' not in section_data.data:
                    section_data.data['questionsAndAnswers'] = {}
                
                section_data.data['questionsAndAnswers'][question_key] = {
                    'question': question.question_text,
                    'answer': new_answer
                }
                section_data.save()
                
                # Create audit log
                FormAuditLog.objects.create(
                    submission=submission,
                    action='question_updated',
                    user=request.user,
                    changes={
                        'section_key': section_key,
                        'question_key': question_key,
                        'old_value': str(old_value) if old_value is not None else None,
                        'new_value': str(new_answer) if new_answer is not None else None
                    },
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
                
                return Response({
                    'message': 'Question updated successfully',
                    'question_key': question_key,
                    'old_value': old_value,
                    'new_value': new_answer
                })
                
        except (FormSection.DoesNotExist, FormQuestion.DoesNotExist):
            return Response(
                {'error': 'Section or question not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['put', 'patch'])
    def update_dependents(self, request, pk=None):
        """Update dependents information"""
        submission = self.get_object()
        dependents_data = request.data.get('dependents', [])
        
        # Check permissions
        if not request.user.is_staff and submission.user != request.user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        with transaction.atomic():
            # Clear existing dependents
            submission.dependents.all().delete()
            
            # Add new dependents
            created_dependents = []
            for dependent_data in dependents_data:
                if isinstance(dependent_data, dict) and dependent_data.get('firstName'):
                    dependent = DependentInfo.objects.create(
                        submission=submission,
                        first_name=dependent_data.get('firstName', ''),
                        last_name=dependent_data.get('lastName', ''),
                        ssn=dependent_data.get('ssn', ''),
                        relationship=dependent_data.get('relationship', ''),
                        date_of_birth=parse_datetime(dependent_data.get('dateOfBirth', '')).date() if dependent_data.get('dateOfBirth') else None,
                        months_lived_with_you=int(dependent_data.get('monthsLivedWithYou', 0)),
                        is_full_time_student=dependent_data.get('isFullTimeStudent', False),
                        child_care_expense=float(dependent_data.get('childCareExpense', 0))
                    )
                    created_dependents.append({
                        'id': dependent.id,
                        'name': f"{dependent.first_name} {dependent.last_name}"
                    })
            
            # Update section data
            self._update_dependents_section_data(submission, dependents_data)
            
            # Create audit log
            FormAuditLog.objects.create(
                submission=submission,
                action='dependents_updated',
                user=request.user,
                changes={
                    'dependents_count': len(created_dependents),
                    'dependents': created_dependents
                },
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        
        return Response({
            'message': 'Dependents updated successfully',
            'dependents_count': len(created_dependents),
            'dependents': created_dependents
        })
    
    @action(detail=True, methods=['put', 'patch'])
    def update_business_owners(self, request, pk=None):
        """Update business owners information"""
        submission = self.get_object()
        owners_data = request.data.get('owners', [])
        
        # Check permissions
        if not request.user.is_staff and submission.user != request.user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        with transaction.atomic():
            # Clear existing owners
            submission.business_owners.all().delete()
            
            # Add new owners
            created_owners = []
            for owner_data in owners_data:
                if isinstance(owner_data, dict) and owner_data.get('firstName'):
                    owner = BusinessOwnerInfo.objects.create(
                        submission=submission,
                        first_name=owner_data.get('firstName', ''),
                        initial=owner_data.get('initial', ''),
                        last_name=owner_data.get('lastName', ''),
                        ssn=owner_data.get('ssn', ''),
                        address=owner_data.get('address', ''),
                        city=owner_data.get('city', ''),
                        state=owner_data.get('state', ''),
                        zip_code=owner_data.get('zip', ''),
                        country=owner_data.get('country', ''),
                        work_phone=owner_data.get('workTel', ''),
                        ownership_percentage=float(owner_data.get('ownershipPercentage', 0))
                    )
                    created_owners.append({
                        'id': owner.id,
                        'name': f"{owner.first_name} {owner.last_name}",
                        'ownership': f"{owner.ownership_percentage}%"
                    })
            
            # Update section data
            self._update_business_owners_section_data(submission, owners_data)
            
            # Create audit log
            FormAuditLog.objects.create(
                submission=submission,
                action='business_owners_updated',
                user=request.user,
                changes={
                    'owners_count': len(created_owners),
                    'owners': created_owners
                },
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        
        return Response({
            'message': 'Business owners updated successfully',
            'owners_count': len(created_owners),
            'owners': created_owners
        })
    
    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        """Update submission status"""
        submission = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(TaxFormSubmission.STATUS_CHOICES):
            return Response(
                {'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_status = submission.status
        submission.status = new_status
        submission.save()
        
        # Create audit log
        from .models import FormAuditLog
        FormAuditLog.objects.create(
            submission=submission,
            action='status_updated',
            user=request.user,
            changes={
                'old_status': old_status,
                'new_status': new_status
            },
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return Response({'status': submission.get_status_display()})
    
    # Helper methods for updates
    def _update_submission(self, submission, validated_data):
        """Update entire submission with new data"""
        form_type_name = validated_data['formType']
        submission_date = validated_data['submissionDate']
        sections_data = validated_data['sections']
        
        # Update basic info
        submission.submission_date = submission_date
        submission.save()
        
        # Clear existing related data
        submission.section_data.all().delete()
        submission.answers.all().delete()
        submission.dependents.all().delete()
        submission.business_owners.all().delete()
        submission.vehicles.all().delete()
        submission.charitable_contributions.all().delete()
        
        # Process sections again (reuse create logic)
        from .serializers import TaxFormSubmissionCreateSerializer
        serializer = TaxFormSubmissionCreateSerializer()
        
        for section_key, section_data in sections_data.items():
            serializer._process_section(submission, submission.form_type, section_key, section_data)
        
        return submission
    
    def _update_section(self, submission, section_key, section_data):
        """Update specific section"""
        try:
            # Get or create section
            section = FormSection.objects.get(
                form_type=submission.form_type,
                section_key=section_key
            )
            
            # Update section data
            section_data_obj, created = FormSectionData.objects.get_or_create(
                submission=submission,
                section=section,
                section_key=section_key
            )
            
            section_data_obj.data = section_data.get('questionsAndAnswers', {})
            section_data_obj.save()
            
            # Update individual answers
            questions_and_answers = section_data.get('questionsAndAnswers', {})
            
            for question_key, answer_data in questions_and_answers.items():
                if isinstance(answer_data, dict) and 'answer' in answer_data:
                    answer_value = answer_data['answer']
                    question_text = answer_data.get('question', question_key.title())
                else:
                    answer_value = answer_data
                    question_text = question_key.title()
                
                # Get or create question
                question, created = FormQuestion.objects.get_or_create(
                    section=section,
                    question_key=question_key,
                    defaults={
                        'question_text': question_text,
                        'field_type': self._determine_field_type(question_key, answer_value),
                        'is_sensitive': self._is_sensitive_field(question_key)
                    }
                )
                
                # Update answer
                form_answer, created = FormAnswer.objects.get_or_create(
                    submission=submission,
                    question=question,
                    question_key=question_key
                )
                form_answer.set_value(answer_value)
                form_answer.save()
            
            # Handle special section updates
            if section_key == 'dependents' and 'dependents' in questions_and_answers:
                self._update_dependents_from_section(submission, questions_and_answers['dependents'])
            elif section_key == 'ownerInfo' and 'owners' in questions_and_answers:
                self._update_business_owners_from_section(submission, questions_and_answers['owners'])
                
        except FormSection.DoesNotExist:
            # Create new section if it doesn't exist
            section = FormSection.objects.create(
                form_type=submission.form_type,
                section_key=section_key,
                title=section_data.get('sectionTitle', section_key.title()),
                order=FormSection.objects.filter(form_type=submission.form_type).count() + 1
            )
            self._update_section(submission, section_key, section_data)
    
    def _update_dependents_from_section(self, submission, dependents_data):
        """Update dependents from section data"""
        if isinstance(dependents_data, dict) and 'answer' in dependents_data:
            dependents_json = dependents_data['answer']
        else:
            dependents_json = dependents_data
        
        if isinstance(dependents_json, str):
            try:
                dependents_list = json.loads(dependents_json)
            except:
                return
        else:
            dependents_list = dependents_json
        
        if isinstance(dependents_list, list):
            # Clear existing
            submission.dependents.all().delete()
            
            # Create new
            for dependent_data in dependents_list:
                if isinstance(dependent_data, dict) and dependent_data.get('firstName'):
                    DependentInfo.objects.create(
                        submission=submission,
                        first_name=dependent_data.get('firstName', ''),
                        last_name=dependent_data.get('lastName', ''),
                        ssn=dependent_data.get('ssn', ''),
                        relationship=dependent_data.get('relationship', ''),
                        date_of_birth=parse_datetime(dependent_data.get('dateOfBirth', '')).date() if dependent_data.get('dateOfBirth') else None,
                        months_lived_with_you=int(dependent_data.get('monthsLivedWithYou', 0)),
                        is_full_time_student=dependent_data.get('isFullTimeStudent', False),
                        child_care_expense=float(dependent_data.get('childCareExpense', 0))
                    )
    
    def _update_business_owners_from_section(self, submission, owners_data):
        """Update business owners from section data"""
        if isinstance(owners_data, dict) and 'answer' in owners_data:
            owners_json = owners_data['answer']
        else:
            owners_json = owners_data
        
        if isinstance(owners_json, str):
            try:
                owners_list = json.loads(owners_json)
            except:
                return
        else:
            owners_list = owners_json
        
        if isinstance(owners_list, list):
            # Clear existing
            submission.business_owners.all().delete()
            
            # Create new
            for owner_data in owners_list:
                if isinstance(owner_data, dict) and owner_data.get('firstName'):
                    BusinessOwnerInfo.objects.create(
                        submission=submission,
                        first_name=owner_data.get('firstName', ''),
                        initial=owner_data.get('initial', ''),
                        last_name=owner_data.get('lastName', ''),
                        ssn=owner_data.get('ssn', ''),
                        address=owner_data.get('address', ''),
                        city=owner_data.get('city', ''),
                        state=owner_data.get('state', ''),
                        zip_code=owner_data.get('zip', ''),
                        country=owner_data.get('country', ''),
                        work_phone=owner_data.get('workTel', ''),
                        ownership_percentage=float(owner_data.get('ownershipPercentage', 0))
                    )
    
    def _update_dependents_section_data(self, submission, dependents_data):
        """Update dependents section data"""
        try:
            section = FormSection.objects.get(
                form_type=submission.form_type,
                section_key='dependents'
            )
            
            section_data_obj, created = FormSectionData.objects.get_or_create(
                submission=submission,
                section=section,
                section_key='dependents'
            )
            
            section_data_obj.data = {
                'questionsAndAnswers': {
                    'dependents': {
                        'question': 'List of Dependents',
                        'answer': json.dumps(dependents_data)
                    }
                }
            }
            section_data_obj.save()
            
        except FormSection.DoesNotExist:
            pass
    
    def _update_business_owners_section_data(self, submission, owners_data):
        """Update business owners section data"""
        try:
            section = FormSection.objects.get(
                form_type=submission.form_type,
                section_key='ownerInfo'
            )
            
            section_data_obj, created = FormSectionData.objects.get_or_create(
                submission=submission,
                section=section,
                section_key='ownerInfo'
            )
            
            section_data_obj.data = {
                'questionsAndAnswers': {
                    'owners': {
                        'question': 'Business Owners Details',
                        'answer': json.dumps(owners_data)
                    }
                }
            }
            section_data_obj.save()
            
        except FormSection.DoesNotExist:
            pass
    
    def _get_submission_data_for_audit(self, submission):
        """Get current submission data for audit purposes"""
        return {
            'sections': list(submission.section_data.values_list('section_key', flat=True)),
            'dependents_count': submission.dependents.count(),
            'business_owners_count': submission.business_owners.count(),
            'answers_count': submission.answers.count()
        }
    
    def _determine_field_type(self, question_key, answer):
        """Determine field type (reuse from serializer)"""
        from .serializers import TaxFormSubmissionCreateSerializer
        serializer = TaxFormSubmissionCreateSerializer()
        return serializer._determine_field_type(question_key, answer)
    
    def _is_sensitive_field(self, question_key):
        """Check if field is sensitive (reuse from serializer)"""
        from .serializers import TaxFormSubmissionCreateSerializer
        serializer = TaxFormSubmissionCreateSerializer()
        return serializer._is_sensitive_field(question_key)


def get_tokens_for_user(user):
    """Generate JWT tokens for user"""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


from accounts.models import GHLAuthCredentials
import requests
from survey_app.helpers import add_ghl_contact_tag
class UserSignupView(generics.CreateAPIView):
    """User registration endpoint"""
    queryset = User.objects.all()
    serializer_class = UserSignupSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        tokens = get_tokens_for_user(user)

        token = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')

        # --- GHL Integration ---
        ghl_token = token.access_token  # Ideally from env or settings
        location_id = token.location_id
        headers = {
            'Authorization': f'Bearer {ghl_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Version': '2021-07-28',
        }

        # 1. Search if contact exists
        search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={user.email}"
        response = requests.get(search_url, headers=headers)

        print("response: ", response)

        ghl_contact_id = None  # placeholder

        if response.status_code == 200 and response.json().get("contacts"):
            # Contact exists — Update it
            contact_id = response.json()["contacts"][0]["id"]
            ghl_contact_id = contact_id
            update_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
            update_data = {
                "email": user.email,
                "customFields": [
                    {"id": "QmI5yIMWYdY17ijOr4ta", "field_value": user.username},
                    {"id": "nBDNBPX0gUFz7wqfTj51", "field_value": request.data.get("password")}
                ],
            }
            requests.put(update_url, json=update_data, headers=headers)
        else:
            # Contact does not exist — Create it
            create_url = "https://services.leadconnectorhq.com/contacts/"
            create_data = {
                "email": user.email,
                "locationId": location_id,
                "customFields": [
                    {"id": "QmI5yIMWYdY17ijOr4ta", "field_value": user.username},
                    {"id": "nBDNBPX0gUFz7wqfTj51", "field_value": request.data.get("password")}
                ],
            }
            create_res = requests.post(create_url, json=create_data, headers=headers)
            print("FFF:", create_res.json())

            if create_res.status_code in (200, 201):
                ghl_contact_id = create_res.json().get("contact").get("id")

        # Temporarily attach the ghl_contact_id to the user instance
        user._ghl_contact_id = ghl_contact_id

        create_or_update_user_profile(user)

        # Add "tax toolbox created" tag to GHL contact
        add_ghl_contact_tag(user, "tax toolbox created")

        return Response({
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'tokens': tokens
        }, status=status.HTTP_201_CREATED)



class UserLoginView(generics.GenericAPIView):
    """User login endpoint - allows both regular users and admins"""
    serializer_class = UserLoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        tokens = get_tokens_for_user(user)
        permissions = get_user_permissions(user)
        
        return Response({
            'message': 'Login successful',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            },
            'permissions': permissions,
            'tokens': tokens
        }, status=status.HTTP_200_OK)



class UserLogoutView(generics.GenericAPIView):
    """User logout endpoint - blacklists the refresh token"""
    serializer_class = UserLogoutSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'message': 'Successfully logged out'
        }, status=status.HTTP_200_OK)


class AdminLoginView(generics.GenericAPIView):
    """Admin login endpoint"""
    serializer_class = AdminLoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        # Check if user is an admin (either through UserProfile or is_staff/is_superuser)
        is_admin = False
        is_super_admin = False
        try:
            profile = UserProfile.objects.get(user=user)
            is_admin = profile.is_admin
            is_super_admin = profile.is_super_admin
        except UserProfile.DoesNotExist:
            # Fallback to is_staff or is_superuser for backward compatibility
            is_admin = user.is_staff or user.is_superuser
            is_super_admin = user.is_superuser
        
        if not is_admin:
            return Response(
                {'error': 'Access denied. Admin privileges required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        tokens = get_tokens_for_user(user)
        permissions = get_user_permissions(user)
        
        return Response({
            'message': 'Admin login successful',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            },
            'permissions': permissions,
            'tokens': tokens
        }, status=status.HTTP_200_OK)


class AdminUserListView(generics.ListAPIView):
    """List all users for admin panel"""
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        # Check if user has permission to list users
        permissions = get_user_permissions(self.request.user)
        can_list = permissions.get('can_list_users', False) or permissions.get('is_super_admin', False) or self.request.user.is_staff or self.request.user.is_superuser
        
        if not can_list:
            return User.objects.none()
        
        queryset = User.objects.all().order_by('-date_joined')
        
        # Search functionality
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
        
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Calculate statistics from the full queryset (before pagination)
        total_count = queryset.count()
        active_count = queryset.filter(is_active=True).count()
        inactive_count = queryset.filter(is_active=False).count()
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            # Add statistics to paginated response
            response.data['stats'] = {
                'total': total_count,
                'active': active_count,
                'inactive': inactive_count
            }
            return response
        
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'users': serializer.data,
            'count': total_count,
            'stats': {
                'total': total_count,
                'active': active_count,
                'inactive': inactive_count
            }
        }, status=status.HTTP_200_OK)


class AdminUserToggleActiveView(generics.GenericAPIView):
    """Toggle user active/inactive status"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Only allow staff/superuser to access
        if not (request.user.is_staff or request.user.is_superuser):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(id=user_id)
            # Prevent admin from deactivating themselves
            if user.id == request.user.id:
                return Response(
                    {'error': 'You cannot deactivate your own account'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            user.is_active = not user.is_active
            user.save()
            
            return Response({
                'message': f'User {"activated" if user.is_active else "deactivated"} successfully',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'is_active': user.is_active
                }
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class AdminUserFormsView(generics.GenericAPIView):
    """Get all forms for a specific user, grouped by form type"""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # Check if user is admin
        permissions = get_user_permissions(request.user)
        is_admin = permissions.get('is_admin', False) or request.user.is_staff or request.user.is_superuser
        
        if not is_admin:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = kwargs.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Import SurveySubmission and TaxEngagementLetter from survey_app
        from survey_app.models import SurveySubmission, TaxEngagementLetter
        from survey_app.serializers import SurveySubmissionListSerializer, TaxEngagementLetterSerializer
        
        # Get all submissions for this user
        submissions = SurveySubmission.objects.filter(user=user).order_by('-submitted_at')
        
        # Group by form type (normalize to lowercase so 'Flip' / 'flip' both map to 'flip')
        forms_by_type = {
            'personal': [],
            'business': [],
            'rental': [],
            'flip': [],
        }
        
        for submission in submissions:
            raw_type = (submission.form_type or '').strip()
            form_type_key = raw_type.lower() if raw_type else ''
            # Check permissions for each form type
            if form_type_key == 'personal' and not permissions.get('can_view_personal_organizer', False) and not permissions.get('is_super_admin', False):
                continue
            if form_type_key == 'business' and not permissions.get('can_view_business_organizer', False) and not permissions.get('is_super_admin', False):
                continue
            if form_type_key == 'rental' and not permissions.get('can_view_rental_organizer', False) and not permissions.get('is_super_admin', False):
                continue
            if form_type_key == 'flip' and not permissions.get('can_view_flip_organizer', False) and not permissions.get('is_super_admin', False):
                continue
            
            if form_type_key in forms_by_type:
                serializer = SurveySubmissionListSerializer(submission)
                forms_by_type[form_type_key].append(serializer.data)
        
        # Get engagement letter if it exists and user has permission
        engagement_letter = None
        if permissions.get('can_view_engagement_letter', False) or permissions.get('is_super_admin', False):
            try:
                letter = TaxEngagementLetter.objects.get(user=user)
                engagement_letter = TaxEngagementLetterSerializer(letter).data
            except TaxEngagementLetter.DoesNotExist:
                pass
        
        # Add engagement letter to response
        response_data = forms_by_type.copy()
        response_data['engagement_letter'] = engagement_letter
        
        return Response(response_data, status=status.HTTP_200_OK)


class AdminReassignSubmissionView(generics.GenericAPIView):
    """Reassign a submission from the current admin user to a target client (admin only)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        permissions = get_user_permissions(request.user)
        is_admin = permissions.get('is_admin', False) or request.user.is_staff or request.user.is_superuser
        if not is_admin:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        submission_id = request.data.get('submission_id')
        form_type = request.data.get('form_type')
        target_user_id = request.data.get('target_user_id')
        if not submission_id or not form_type or target_user_id is None:
            return Response(
                {'error': 'submission_id, form_type, and target_user_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from survey_app.models import SurveySubmission
        try:
            submission = SurveySubmission.objects.get(
                id=submission_id,
                form_type=form_type,
                user=request.user
            )
        except SurveySubmission.DoesNotExist:
            return Response(
                {'error': 'Submission not found or you do not own it'},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            target_user = User.objects.get(pk=int(target_user_id))
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({'error': 'Target user not found'}, status=status.HTTP_404_NOT_FOUND)

        submission.user = target_user
        submission.save(update_fields=['user'])
        return Response({'message': 'Submission reassigned to client', 'id': str(submission.id)}, status=status.HTTP_200_OK)


class RequestOTPView(generics.GenericAPIView):
    """Request OTP for password reset"""
    serializer_class = RequestOTPSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {'error': 'No user found with this email address.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Generate 6-digit OTP
        import random
        otp = str(random.randint(100000, 999999))
        
        # Get GHL credentials
        try:
            token = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')
            ghl_token = token.access_token
            location_id = token.location_id
        except GHLAuthCredentials.DoesNotExist:
            return Response(
                {'error': 'GHL credentials not configured.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        headers = {
            'Authorization': f'Bearer {ghl_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Version': '2021-07-28',
        }
        
        # Search for contact by email
        search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={email}"
        response = requests.get(search_url, headers=headers)
        
        if response.status_code == 200 and response.json().get("contacts"):
            # Contact exists - Update it with OTP
            contact_id = response.json()["contacts"][0]["id"]
            update_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
            update_data = {
                "customFields": [
                    {"id": "DVc7s2Y0ZgqUi4sTRI7h", "field_value": otp}
                ],
            }
            update_response = requests.put(update_url, json=update_data, headers=headers)
            
            if update_response.status_code == 200:
                return Response({
                    'message': 'OTP has been sent to your email address.'
                }, status=status.HTTP_200_OK)
            else:
                logger.error(f"Failed to update GHL contact with OTP: {update_response.text}")
                return Response(
                    {'error': 'Failed to send OTP. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            # Contact doesn't exist - Create it with OTP
            create_url = "https://services.leadconnectorhq.com/contacts/"
            create_data = {
                "email": email,
                "locationId": location_id,
                "customFields": [
                    {"id": "DVc7s2Y0ZgqUi4sTRI7h", "field_value": otp}
                ],
            }
            create_response = requests.post(create_url, json=create_data, headers=headers)
            
            if create_response.status_code in (200, 201):
                return Response({
                    'message': 'OTP has been sent to your email address.'
                }, status=status.HTTP_200_OK)
            else:
                logger.error(f"Failed to create GHL contact with OTP: {create_response.text}")
                return Response(
                    {'error': 'Failed to send OTP. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


class SubmitOTPView(generics.GenericAPIView):
    """Submit OTP and reset password"""
    serializer_class = SubmitOTPSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        new_password = serializer.validated_data['new_password']
        user = serializer.validated_data['user']
        
        # Get GHL credentials
        try:
            token = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')
            ghl_token = token.access_token
            location_id = token.location_id
        except GHLAuthCredentials.DoesNotExist:
            return Response(
                {'error': 'GHL credentials not configured.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        headers = {
            'Authorization': f'Bearer {ghl_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Version': '2021-07-28',
        }
        
        # Search for contact by email
        search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={email}"
        response = requests.get(search_url, headers=headers)
        
        if response.status_code == 200 and response.json().get("contacts"):
            contact_id = response.json()["contacts"][0]["id"]
            
            # Get contact details to verify OTP
            contact_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
            contact_response = requests.get(contact_url, headers=headers)
            
            if contact_response.status_code == 200:
                contact_data = contact_response.json().get("contact", {})
                custom_fields = contact_data.get("customFields", [])
                
                # Find the OTP field
                otp_field = None
                for field in custom_fields:
                    if field.get("id") == "DVc7s2Y0ZgqUi4sTRI7h":
                        otp_field = field
                        break
                
                stored_otp = otp_field.get("value") if otp_field else None
                
                # Verify OTP
                if stored_otp and stored_otp == otp:
                    # OTP is valid - update password
                    user.set_password(new_password)
                    user.save()
                    
                    # Clear OTP from GHL custom field
                    update_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
                    update_data = {
                        "customFields": [
                            {"id": "DVc7s2Y0ZgqUi4sTRI7h", "field_value": ""}
                        ],
                    }
                    requests.put(update_url, json=update_data, headers=headers)
                    
                    return Response({
                        'message': 'Password has been reset successfully.'
                    }, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {'error': 'Invalid OTP. Please check and try again.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                return Response(
                    {'error': 'Failed to verify OTP. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return Response(
                {'error': 'No contact found. Please request a new OTP.'},
                status=status.HTTP_404_NOT_FOUND
            )


from cryptography.fernet import Fernet

def decrypt_value(encrypted_text):
    try:
        cipher = Fernet(settings.ENCRYPTION_KEY.encode())
        return cipher.decrypt(encrypted_text.encode()).decode()
    except:
        return encrypted_text


def is_super_admin(user):
    """Check if user is a super admin"""
    try:
        profile = UserProfile.objects.get(user=user)
        return profile.is_super_admin
    except UserProfile.DoesNotExist:
        return False


def get_user_permissions(user):
    """Get user permissions from UserProfile"""
    try:
        profile = UserProfile.objects.get(user=user)
        return {
            'is_admin': profile.is_admin,
            'is_super_admin': profile.is_super_admin,
            'can_list_users': profile.can_list_users,
            'can_view_personal_organizer': profile.can_view_personal_organizer,
            'can_view_business_organizer': profile.can_view_business_organizer,
            'can_view_rental_organizer': profile.can_view_rental_organizer,
            'can_view_flip_organizer': profile.can_view_flip_organizer,
            'can_view_engagement_letter': profile.can_view_engagement_letter,
        }
    except UserProfile.DoesNotExist:
        return {
            'is_admin': False,
            'is_super_admin': False,
            'can_list_users': False,
            'can_view_personal_organizer': False,
            'can_view_business_organizer': False,
            'can_view_rental_organizer': False,
            'can_view_flip_organizer': False,
            'can_view_engagement_letter': False,
        }


class AdminManagementListView(generics.ListAPIView):
    """List all admins - only accessible by super admins"""
    permission_classes = [IsAuthenticated]
    serializer_class = AdminProfileSerializer

    def get_queryset(self):
        # Only allow super admins to access
        if not is_super_admin(self.request.user):
            return UserProfile.objects.none()
        
        return UserProfile.objects.filter(is_admin=True).select_related('user').order_by('-created_at')


class CreateAdminView(generics.GenericAPIView):
    """Create admin from existing user - only accessible by super admins"""
    permission_classes = [IsAuthenticated]
    serializer_class = CreateAdminSerializer

    def post(self, request, *args, **kwargs):
        # Only allow super admins to create admins
        if not is_super_admin(request.user):
            return Response(
                {'error': 'Permission denied. Super admin access required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user_id = serializer.validated_data['user_id']
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get or create UserProfile
        profile, created = UserProfile.objects.get_or_create(user=user)
        
        # Set admin status and permissions
        profile.is_admin = True
        profile.is_super_admin = serializer.validated_data.get('is_super_admin', False)
        profile.can_list_users = serializer.validated_data.get('can_list_users', False)
        profile.can_view_personal_organizer = serializer.validated_data.get('can_view_personal_organizer', False)
        profile.can_view_business_organizer = serializer.validated_data.get('can_view_business_organizer', False)
        profile.can_view_rental_organizer = serializer.validated_data.get('can_view_rental_organizer', False)
        profile.can_view_flip_organizer = serializer.validated_data.get('can_view_flip_organizer', False)
        profile.can_view_engagement_letter = serializer.validated_data.get('can_view_engagement_letter', False)
        profile.save()
        
        # Also set is_staff to True so they can access admin portal
        user.is_staff = True
        user.save()
        
        return Response({
            'message': 'Admin created successfully',
            'admin': AdminProfileSerializer(profile).data
        }, status=status.HTTP_201_CREATED)


class UpdateAdminPermissionsView(generics.GenericAPIView):
    """Update admin permissions - only accessible by super admins"""
    permission_classes = [IsAuthenticated]
    serializer_class = UpdateAdminPermissionsSerializer

    def post(self, request, *args, **kwargs):
        # Only allow super admins to update permissions
        if not is_super_admin(request.user):
            return Response(
                {'error': 'Permission denied. Super admin access required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        admin_id = request.data.get('admin_id')
        if not admin_id:
            return Response(
                {'error': 'admin_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            profile = UserProfile.objects.get(user_id=admin_id, is_admin=True)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'Admin not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent super admin from modifying their own super admin status
        if profile.user.id == request.user.id and 'is_super_admin' in request.data:
            if not request.data.get('is_super_admin', False):
                return Response(
                    {'error': 'You cannot remove your own super admin status'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Update permissions
        for field, value in serializer.validated_data.items():
            setattr(profile, field, value)
        profile.save()
        
        return Response({
            'message': 'Admin permissions updated successfully',
            'admin': AdminProfileSerializer(profile).data
        }, status=status.HTTP_200_OK)


class DeactivateAdminView(generics.GenericAPIView):
    """Deactivate/reactivate admin - only accessible by super admins"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Only allow super admins to deactivate admins
        if not is_super_admin(request.user):
            return Response(
                {'error': 'Permission denied. Super admin access required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        admin_id = request.data.get('admin_id')
        if not admin_id:
            return Response(
                {'error': 'admin_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            profile = UserProfile.objects.get(user_id=admin_id, is_admin=True)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'Admin not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent super admin from deactivating themselves
        if profile.user.id == request.user.id:
            return Response(
                {'error': 'You cannot deactivate your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Toggle admin status
        profile.is_admin = not profile.is_admin
        profile.save()
        
        # Also update user's is_staff status
        profile.user.is_staff = profile.is_admin
        profile.user.save()
        
        return Response({
            'message': f'Admin {"activated" if profile.is_admin else "deactivated"} successfully',
            'admin': AdminProfileSerializer(profile).data
        }, status=status.HTTP_200_OK)


class ResetAdminPasswordView(generics.GenericAPIView):
    """Reset admin password - only accessible by super admins"""
    permission_classes = [IsAuthenticated]
    serializer_class = ResetAdminPasswordSerializer

    def post(self, request, *args, **kwargs):
        # Only allow super admins to reset passwords
        if not is_super_admin(request.user):
            return Response(
                {'error': 'Permission denied. Super admin access required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        admin_id = request.data.get('admin_id')
        if not admin_id:
            return Response(
                {'error': 'admin_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            profile = UserProfile.objects.get(user_id=admin_id, is_admin=True)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'Admin not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Set new password
        profile.user.set_password(serializer.validated_data['new_password'])
        profile.user.save()
        
        return Response({
            'message': 'Password reset successfully'
        }, status=status.HTTP_200_OK)


class AdminPermissionsView(generics.GenericAPIView):
    """Get current admin's permissions"""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        permissions = get_user_permissions(request.user)
        return Response(permissions, status=status.HTTP_200_OK)