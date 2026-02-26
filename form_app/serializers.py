from rest_framework import serializers
from django.db import transaction
from django.utils.dateparse import parse_datetime
import json
from .models import (
    TaxFormSubmission, FormType, FormSection, FormQuestion, 
    FormAnswer, FormSectionData, DependentInfo, BusinessOwnerInfo,
    VehicleInfo, CharitableContribution, FormAuditLog
)


from rest_framework import serializers
from django.db import transaction
from django.utils.dateparse import parse_datetime
import json
from .models import (
    TaxFormSubmission, FormType, FormSection, FormQuestion, 
    FormAnswer, FormSectionData, DependentInfo, BusinessOwnerInfo,
    VehicleInfo, CharitableContribution, FormAuditLog
)


class DependentInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DependentInfo
        fields = '__all__'
        extra_kwargs = {'submission': {'write_only': True}}


class BusinessOwnerInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessOwnerInfo
        fields = '__all__'
        extra_kwargs = {'submission': {'write_only': True}}


class VehicleInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleInfo
        fields = '__all__'
        extra_kwargs = {'submission': {'write_only': True}}


class CharitableContributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CharitableContribution
        fields = '__all__'
        extra_kwargs = {'submission': {'write_only': True}}


class FormAnswerSerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField()
    
    class Meta:
        model = FormAnswer
        fields = ['question_key', 'value', 'created_at']
    
    def get_value(self, obj):
        return obj.get_value()


class FormSectionDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormSectionData
        fields = ['section_key', 'data']


class TaxFormSubmissionSerializer(serializers.ModelSerializer):
    answers = FormAnswerSerializer(many=True, read_only=True)
    section_data = FormSectionDataSerializer(many=True, read_only=True)
    dependents = DependentInfoSerializer(many=True, read_only=True)
    business_owners = BusinessOwnerInfoSerializer(many=True, read_only=True)
    vehicles = VehicleInfoSerializer(many=True, read_only=True)
    charitable_contributions = CharitableContributionSerializer(many=True, read_only=True)
    
    class Meta:
        model = TaxFormSubmission
        fields = '__all__'


class TaxFormSubmissionCreateSerializer(serializers.Serializer):
    """Serializer for creating tax form submissions from frontend payload"""
    formType = serializers.CharField()
    submissionDate = serializers.DateTimeField()
    sections = serializers.DictField()
    
    def create(self, validated_data):
        """Create tax form submission with all related data"""
        form_type_name = validated_data['formType']
        submission_date = validated_data['submissionDate']
        sections_data = validated_data['sections']
        
        with transaction.atomic():
            # Get or create form type
            form_type, _ = FormType.objects.get_or_create(
                name=form_type_name,
                defaults={'display_name': form_type_name.title()}
            )
            
            # Create submission
            submission = TaxFormSubmission.objects.create(
                form_type=form_type,
                submission_date=submission_date,
                status='submitted',
                user=self.context.get('request').user if self.context.get('request') else None
            )
            
            # Process each section
            for section_key, section_data in sections_data.items():
                self._process_section(submission, form_type, section_key, section_data)
            
            # Create audit log
            FormAuditLog.objects.create(
                submission=submission,
                action='created',
                user=self.context.get('request').user if self.context.get('request') else None,
                changes={'sections': list(sections_data.keys())}
            )
            
            return submission
    
    def _process_section(self, submission, form_type, section_key, section_data):
        """Process individual section data"""
        section_title = section_data.get('sectionTitle', section_key.title())
        questions_and_answers = section_data.get('questionsAndAnswers', {})
        
        # Get or create section
        section, _ = FormSection.objects.get_or_create(
            form_type=form_type,
            section_key=section_key,
            defaults={'title': section_title}
        )
        
        # Create section data record
        FormSectionData.objects.create(
            submission=submission,
            section=section,
            section_key=section_key,
            data=questions_and_answers
        )
        
        # Process individual questions and answers
        for question_key, answer_value in questions_and_answers.items():
            self._process_question_answer(
                submission, section, question_key, answer_value
            )
        
        # Handle special cases for structured data
        if section_key == 'dependents':
            self._process_dependents(submission, questions_and_answers)
        elif section_key == 'ownerInfo':
            self._process_business_owners(submission, questions_and_answers)
        elif section_key == 'incomeExpenses':
            self._process_vehicles(submission, questions_and_answers)
        elif section_key == 'deductions':
            self._process_charitable_contributions(submission, questions_and_answers)
    
    def _process_question_answer(self, submission, section, question_key, answer_value):
        """Process individual question and answer"""
        if isinstance(answer_value, dict) and 'question' in answer_value and 'answer' in answer_value:
            question_text = answer_value['question']
            answer = answer_value['answer']
        else:
            question_text = question_key.replace('_', ' ').title()
            answer = answer_value
        
        # Determine field type and if it's sensitive
        field_type = self._determine_field_type(question_key, answer)
        is_sensitive = self._is_sensitive_field(question_key)
        
        # Get or create question
        question, _ = FormQuestion.objects.get_or_create(
            section=section,
            question_key=question_key,
            defaults={
                'question_text': question_text,
                'field_type': field_type,
                'is_sensitive': is_sensitive
            }
        )
        
        # Create or update answer
        form_answer, created = FormAnswer.objects.get_or_create(
            submission=submission,
            question=question,
            question_key=question_key
        )
        
        form_answer.set_value(answer)
        form_answer.save()
    
    def _determine_field_type(self, question_key, answer):
        """Determine the appropriate field type based on question key and answer"""
        # Only these specific fields should be encrypted (sensitive personal data)
        sensitive_fields = ['ssn', 'spousessn', 'ein']  # Removed business name related fields
        signature_fields = ['taxpayersignature', 'spousesignature', 'signature']
        
        boolean_fields = ['hasSpouse', 'taxpayerBlind', 'isFullTimeStudent', 'firstYear', 'hasHomeOffice']
        date_fields = ['dateOfBirth', 'submissionDate', 'startDate', 'datePlacedInService', 'spouseDeathDate']
        number_fields = ['monthsLivedWithYou', 'childCareExpense', 'ownershipPercentage', 'grossReceipts', 'totalMiles']
        json_fields = ['dependents', 'owners', 'vehicles', 'charitableOrganizations', 'otherExpenses', 'businessDescriptions', 'entityTypes']
        
        # Check for encrypted fields (only specific sensitive personal data)
        if any(field in question_key.lower() for field in sensitive_fields):
            return 'encrypted'
        elif any(field in question_key.lower() for field in signature_fields):
            return 'signature'
        elif question_key in boolean_fields or str(answer).lower() in ['yes', 'no', 'true', 'false']:
            return 'boolean'
        elif question_key in date_fields or 'date' in question_key.lower():
            return 'date'
        elif question_key in number_fields or (isinstance(answer, (int, float)) or str(answer).replace('.', '').isdigit()):
            return 'number'
        elif question_key in json_fields or isinstance(answer, (list, dict)):
            return 'json'
        else:
            return 'text'
    
    def _is_sensitive_field(self, question_key):
        """Check if field contains sensitive data that needs encryption"""
        # Only these specific fields contain sensitive personal/financial data
        sensitive_keywords = [
            'ssn',           # Social Security Numbers
            'spousessn',     # Spouse SSN
            'ein',           # Employer Identification Number (business tax ID)
            'signature'      # Digital signatures
        ]
        
        question_lower = question_key.lower()
        return any(keyword in question_lower for keyword in sensitive_keywords)
    
    def _process_dependents(self, submission, questions_data):
        """Process dependents data into separate model"""
        dependents_data = questions_data.get('dependents', {}).get('answer', '[]')
        
        if isinstance(dependents_data, str):
            try:
                dependents_list = json.loads(dependents_data)
            except json.JSONDecodeError:
                return
        else:
            dependents_list = dependents_data
        
        if isinstance(dependents_list, list):
            for dependent_data in dependents_list:
                if not isinstance(dependent_data, dict):
                    continue
                
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
    
    def _process_business_owners(self, submission, questions_data):
        """Process business owners data"""
        owners_data = questions_data.get('owners', {}).get('answer', '[]')
        
        if isinstance(owners_data, str):
            try:
                owners_list = json.loads(owners_data)
            except json.JSONDecodeError:
                return
        else:
            owners_list = owners_data
        
        if isinstance(owners_list, list):
            for owner_data in owners_list:
                if not isinstance(owner_data, dict):
                    continue
                
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
    
    def _process_vehicles(self, submission, questions_data):
        """Process vehicle information"""
        vehicles_data = questions_data.get('vehicles', {}).get('answer', '[]')
        
        if isinstance(vehicles_data, str):
            try:
                vehicles_list = json.loads(vehicles_data)
            except json.JSONDecodeError:
                return
        else:
            vehicles_list = vehicles_data
        
        if isinstance(vehicles_list, list):
            for vehicle_data in vehicles_list:
                if not isinstance(vehicle_data, dict) or not vehicle_data.get('description'):
                    continue
                
                VehicleInfo.objects.create(
                    submission=submission,
                    description=vehicle_data.get('description', ''),
                    date_placed_in_service=parse_datetime(vehicle_data.get('datePlacedInService', '')).date() if vehicle_data.get('datePlacedInService') else None,
                    total_miles=int(vehicle_data.get('totalMiles', 0)),
                    business_miles=int(vehicle_data.get('businessMiles', 0))
                )
    
    def _process_charitable_contributions(self, submission, questions_data):
        """Process charitable contributions"""
        contributions_data = questions_data.get('charitableOrganizations', {}).get('answer', '[]')
        
        if isinstance(contributions_data, str):
            try:
                contributions_list = json.loads(contributions_data)
            except json.JSONDecodeError:
                return
        else:
            contributions_list = contributions_data
        
        if isinstance(contributions_list, list):
            for contribution_data in contributions_list:
                if not isinstance(contribution_data, dict):
                    continue
                
                CharitableContribution.objects.create(
                    submission=submission,
                    organization_name=contribution_data.get('name', ''),
                    amount=float(contribution_data.get('amount', 0))
                )




from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken


def _generate_username_from_name(first_name, last_name):
    """Generate a unique username from first_name and last_name (e.g. john_doe, john_doe_2)."""
    import re
    raw = f"{first_name or ''}_{last_name or ''}".strip('_').lower()
    base = re.sub(r'[^\w]', '_', raw) or 'user'
    base = base[:25]  # leave room for _N suffix
    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}_{counter}"[:30]
        counter += 1
    return username


class UserSignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'password_confirm', 'first_name', 'last_name')
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match.")
        return attrs

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        first_name = validated_data.get('first_name', '')
        last_name = validated_data.get('last_name', '')
        validated_data['username'] = _generate_username_from_name(first_name, last_name)
        user = User.objects.create_user(**validated_data)
        return user


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            # Find user by email first
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise serializers.ValidationError('Invalid credentials.')
            
            # Authenticate using the username (Django's authenticate uses username)
            authenticated_user = authenticate(username=user.username, password=password)
            
            if not authenticated_user:
                raise serializers.ValidationError('Invalid credentials.')
            
            if not authenticated_user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            
            attrs['user'] = authenticated_user
            return attrs
        else:
            raise serializers.ValidationError('Must include email and password.')


class AdminLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            
            if not user:
                raise serializers.ValidationError('Invalid credentials.')
            
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            
            if not (user.is_staff or user.is_superuser):
                raise serializers.ValidationError('Access denied. Admin privileges required.')
            
            attrs['user'] = user
            return attrs
        else:
            raise serializers.ValidationError('Must include username and password.')


class UserProfileSerializer(serializers.ModelSerializer):
    profile = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'is_active', 'is_staff', 'is_superuser', 'profile')
        read_only_fields = ('id', 'username', 'date_joined')
    
    def get_profile(self, obj):
        """Get UserProfile data if it exists"""
        try:
            from .models import UserProfile
            profile = UserProfile.objects.get(user=obj)
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
        except:
            return None


class AdminProfileSerializer(serializers.ModelSerializer):
    """Serializer for UserProfile with admin permissions"""
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)
    date_joined = serializers.DateTimeField(source='user.date_joined', read_only=True)
    
    class Meta:
        from .models import UserProfile
        model = UserProfile
        fields = (
            'user_id', 'username', 'email', 'first_name', 'last_name', 
            'is_active', 'date_joined',
            'is_admin', 'is_super_admin',
            'can_list_users', 'can_view_personal_organizer', 
            'can_view_business_organizer', 'can_view_rental_organizer',
            'can_view_flip_organizer', 'can_view_engagement_letter', 'created_at', 'updated_at'
        )
        read_only_fields = ('created_at', 'updated_at')


class CreateAdminSerializer(serializers.Serializer):
    """Serializer for creating an admin from existing user"""
    user_id = serializers.IntegerField(required=True)
    is_super_admin = serializers.BooleanField(default=False)
    can_list_users = serializers.BooleanField(default=False)
    can_view_personal_organizer = serializers.BooleanField(default=False)
    can_view_business_organizer = serializers.BooleanField(default=False)
    can_view_rental_organizer = serializers.BooleanField(default=False)
    can_view_flip_organizer = serializers.BooleanField(default=False)
    can_view_engagement_letter = serializers.BooleanField(default=False)
    
    def validate_user_id(self, value):
        """Validate that user exists"""
        try:
            user = User.objects.get(id=value)
            if not user.is_active:
                raise serializers.ValidationError("Cannot create admin from inactive user.")
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")


class UpdateAdminPermissionsSerializer(serializers.Serializer):
    """Serializer for updating admin permissions"""
    is_super_admin = serializers.BooleanField(required=False)
    can_list_users = serializers.BooleanField(required=False)
    can_view_personal_organizer = serializers.BooleanField(required=False)
    can_view_business_organizer = serializers.BooleanField(required=False)
    can_view_rental_organizer = serializers.BooleanField(required=False)
    can_view_flip_organizer = serializers.BooleanField(required=False)
    can_view_engagement_letter = serializers.BooleanField(required=False)


class ResetAdminPasswordSerializer(serializers.Serializer):
    """Serializer for resetting admin password"""
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Passwords don't match.")
        return attrs


class UserLogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs):
        self.token = attrs['refresh']
        return attrs

    def save(self, **kwargs):
        try:
            RefreshToken(self.token).blacklist()
        except Exception as e:
            raise serializers.ValidationError('Invalid token.')


class RequestOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        """Check if user with this email exists"""
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError('No user found with this email address.')
        return value


class SubmitOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """Validate that passwords match"""
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Passwords don't match.")
        
        # Check if user exists
        try:
            user = User.objects.get(email=attrs['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError('No user found with this email address.')
        
        attrs['user'] = user
        return attrs