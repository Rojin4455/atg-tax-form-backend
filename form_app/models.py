# models.py
import json
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone


class EncryptedField(models.TextField):
    """Custom field for encrypting sensitive data like SSN"""
    
    def __init__(self, *args, **kwargs):
        self.encrypt_key = getattr(settings, 'ENCRYPTION_KEY', None)
        if not self.encrypt_key:
            raise ValueError("ENCRYPTION_KEY must be set in settings")
        super().__init__(*args, **kwargs)
    
    def get_cipher(self):
        return Fernet(self.encrypt_key.encode())
    
    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            cipher = self.get_cipher()
            return cipher.decrypt(value.encode()).decode()
        except:
            return value
    
    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)
    
    def get_prep_value(self, value):
        if value is None:
            return value
        cipher = self.get_cipher()
        return cipher.encrypt(value.encode()).decode()


class FormType(models.Model):
    """Defines the type of form (personal, business, etc.)"""
    FORM_TYPES = [
        ('personal', 'Personal Tax Form'),
        ('business', 'Business Tax Form'),
    ]
    
    name = models.CharField(max_length=50, choices=FORM_TYPES, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.display_name


class FormSection(models.Model):
    """Defines sections within a form type"""
    form_type = models.ForeignKey(FormType, on_delete=models.CASCADE, related_name='sections')
    section_key = models.CharField(max_length=100)  # e.g., 'basicInfo', 'income'
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['form_type', 'section_key']
        ordering = ['order', 'section_key']
    
    def __str__(self):
        return f"{self.form_type.name} - {self.title}"


class FormQuestion(models.Model):
    """Defines questions within form sections"""
    FIELD_TYPES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('select', 'Select'),
        ('textarea', 'Textarea'),
        ('json', 'JSON Array'),
        ('encrypted', 'Encrypted Text'),
        ('signature', 'Digital Signature'),
    ]
    
    section = models.ForeignKey(FormSection, on_delete=models.CASCADE, related_name='questions')
    question_key = models.CharField(max_length=100)  # e.g., 'firstName', 'ssn'
    question_text = models.TextField()
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default='text')
    is_required = models.BooleanField(default=False)
    is_sensitive = models.BooleanField(default=False)  # For SSN, signatures, etc.
    order = models.PositiveIntegerField(default=0)
    validation_rules = models.JSONField(blank=True, null=True)  # Store validation patterns
    help_text = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['section', 'question_key']
        ordering = ['order', 'question_key']
    
    def __str__(self):
        return f"{self.section.title} - {self.question_text[:50]}"


class TaxFormSubmission(models.Model):
    """Main submission record"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form_type = models.ForeignKey(FormType, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    submission_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Metadata
    client_info = models.JSONField(blank=True, null=True)  # Browser, IP, etc.
    processing_notes = models.TextField(blank=True)


    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['form_type', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['submission_date']),
        ]
    
    def __str__(self):
        return f"{self.form_type.name} - {self.id}"


class FormSectionData(models.Model):
    """Stores section-level data for each submission"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='section_data')
    section = models.ForeignKey(FormSection, on_delete=models.CASCADE)
    section_key = models.CharField(max_length=100)  # Denormalized for faster queries
    data = models.JSONField(default=dict)  # Store all section answers
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['submission', 'section']
        ordering = ['section__order']
        indexes = [
            models.Index(fields=['submission', 'section_key']),
            models.Index(fields=['section_key']),
        ]
    
    def __str__(self):
        return f"{self.submission.id} - {self.section.title}"


class FormAnswer(models.Model):
    """Individual answers to form questions"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(FormQuestion, on_delete=models.CASCADE)
    question_key = models.CharField(max_length=100)  # Denormalized
    
    # Different field types for different answer types
    text_value = models.TextField(blank=True, null=True)
    number_value = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    boolean_value = models.BooleanField(blank=True, null=True)
    date_value = models.DateTimeField(blank=True, null=True)
    json_value = models.JSONField(blank=True, null=True)  # For arrays, objects
    encrypted_value = EncryptedField(blank=True, null=True)  # For sensitive data
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['submission', 'question']
        indexes = [
            models.Index(fields=['submission', 'question_key']),
            models.Index(fields=['question', 'created_at']),
            models.Index(fields=['question_key']),
        ]
    
    def get_value(self):
        """Returns the appropriate value based on question type"""
        if self.question.field_type == 'encrypted':
            return self.encrypted_value
        elif self.question.field_type == 'number':
            return self.number_value
        elif self.question.field_type == 'boolean':
            return self.boolean_value
        elif self.question.field_type == 'date':
            return self.date_value
        elif self.question.field_type == 'json':
            return self.json_value
        else:
            return self.text_value
    
    def set_value(self, value):
        """Sets the appropriate value based on question type"""
        # Clear all values first
        self.text_value = None
        self.number_value = None
        self.boolean_value = None
        self.date_value = None
        self.json_value = None
        self.encrypted_value = None
        
        if value is None or value == '':
            return
        
        if self.question.field_type == 'encrypted':
            self.encrypted_value = str(value)
        elif self.question.field_type == 'number':
            self.number_value = float(value) if value else None
        elif self.question.field_type == 'boolean':
            if isinstance(value, str):
                self.boolean_value = value.lower() in ['true', 'yes', '1']
            else:
                self.boolean_value = bool(value)
        elif self.question.field_type == 'date':
            if isinstance(value, str):
                from django.utils.dateparse import parse_datetime, parse_date
                self.date_value = parse_datetime(value) or parse_date(value)
            else:
                self.date_value = value
        elif self.question.field_type == 'json':
            if isinstance(value, str):
                try:
                    self.json_value = json.loads(value)
                except json.JSONDecodeError:
                    self.json_value = value
            else:
                self.json_value = value
        else:
            self.text_value = str(value)
    
    def __str__(self):
        return f"{self.submission.id} - {self.question.question_text[:30]}"


class DependentInfo(models.Model):
    """Separate model for dependent information for better normalization"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='dependents')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    ssn = EncryptedField()
    relationship = models.CharField(max_length=50)
    date_of_birth = models.DateField()
    months_lived_with_you = models.PositiveIntegerField()
    is_full_time_student = models.BooleanField(default=False)
    child_care_expense = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['submission']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.submission.id}"


class BusinessOwnerInfo(models.Model):
    """Separate model for business owner information"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='business_owners')
    first_name = models.CharField(max_length=100)
    initial = models.CharField(max_length=5, blank=True)
    last_name = models.CharField(max_length=100)
    ssn = EncryptedField()
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    zip_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    work_phone = models.CharField(max_length=20)
    ownership_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['submission']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.ownership_percentage}%)"


class VehicleInfo(models.Model):
    """Business vehicle information"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='vehicles')
    description = models.CharField(max_length=200)
    date_placed_in_service = models.DateField()
    total_miles = models.PositiveIntegerField()
    business_miles = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.description} - {self.submission.id}"


class CharitableContribution(models.Model):
    """Charitable contributions"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='charitable_contributions')
    organization_name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.organization_name} - ${self.amount}"


class FormAuditLog(models.Model):
    """Audit trail for form submissions"""
    submission = models.ForeignKey(TaxFormSubmission, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=50)  # created, updated, submitted, etc.
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField(blank=True, null=True)  # What changed
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['submission', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.submission.id} - {self.action} - {self.timestamp}"