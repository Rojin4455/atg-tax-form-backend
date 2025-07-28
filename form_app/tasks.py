from celery import shared_task
from form_app.models import TaxFormSubmission,FormAuditLog
from django.utils import timezone
from .pdf_generator import PDFGenerator


# Async tasks for background processing
@shared_task
def process_submission_async(submission_id, client_ip, user_agent, user_id):
    """Process submission data in background"""
    try:
        submission = TaxFormSubmission.objects.get(id=submission_id)
        
        # Update client info
        submission.client_info = {
            'ip_address': client_ip,
            'user_agent': user_agent,
            'processed_at': timezone.now().isoformat()
        }
        submission.save(update_fields=['client_info', 'updated_at'])
        
        # Create audit log
        FormAuditLog.objects.create(
            submission=submission,
            action='created',
            user_id=user_id,
            changes={'processed_async': True},
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        print(f"Successfully processed submission {submission_id}")
        
    except Exception as e:
        print(f"Error processing submission {submission_id}: {str(e)}")


@shared_task
def create_audit_log_async(submission_id, action, user_id, changes, ip_address, user_agent):
    """Create audit log in background"""
    try:
        FormAuditLog.objects.create(
            submission_id=submission_id,
            action=action,
            user_id=user_id,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent
        )
        print(f"Created audit log for submission {submission_id}")
    except Exception as e:
        print(f"Error creating audit log: {str(e)}")


@shared_task
def generate_pdf_async(submission_id):
    """Generate PDF in background"""
    try:
        submission = TaxFormSubmission.objects.get(id=submission_id)
        pdf_generator = PDFGenerator()
        pdf_content = pdf_generator.generate_tax_form_pdf(submission)
        
        # Store PDF or send notification
        # Implementation depends on your requirements
        
        print(f"Generated PDF for submission {submission_id}")
        return pdf_content
    except Exception as e:
        print(f"Error generating PDF for {submission_id}: {str(e)}")
        return None