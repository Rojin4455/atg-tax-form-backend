from django.db import models
import uuid
from django.contrib.auth.models import User


class SurveySubmission(models.Model):
    FORM_TYPES = (
        ('personal', 'Personal'),
        ('business', 'Business'),
        ('rental', 'Rental'),
    )
    STATUS_TYPES = (
        ('drafted', 'Drafted'),
        ('submitted', 'Submitted'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    form_type = models.CharField(max_length=20, choices=FORM_TYPES)
    form_name = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=20, choices=FORM_TYPES, default="drafted")
    submission_data = models.JSONField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.form_type} - {self.id}"



class TaxEngagementLetter(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    taxpayer_name = models.CharField(max_length=255)
    signature = models.TextField()  # store signature as base64 string
    date_signed = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tax Engagement Letter"
        verbose_name_plural = "Tax Engagement Letters"

    def __str__(self):
        return f"{self.taxpayer_name} ({self.user.username})"
