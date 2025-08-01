from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from io import BytesIO
import json
from form_app.views import decrypt_value


class PDFGenerator:
    """Generate PDF documents for tax form submissions"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.custom_styles = self._create_custom_styles()
    
    def _create_custom_styles(self):
        """Create custom paragraph styles"""
        return {
            'FormTitle': ParagraphStyle(
                'FormTitle',
                parent=self.styles['Heading1'],
                fontSize=18,
                spaceAfter=30,
                alignment=1,  # Center alignment
                textColor=colors.darkblue
            ),
            'SectionTitle': ParagraphStyle(
                'SectionTitle',
                parent=self.styles['Heading2'],
                fontSize=14,
                spaceAfter=12,
                spaceBefore=20,
                textColor=colors.darkblue,
                borderWidth=1,
                borderColor=colors.darkblue,
                borderPadding=5
            ),
            'QuestionStyle': ParagraphStyle(
                'QuestionStyle',
                parent=self.styles['Normal'],
                fontSize=10,
                textColor=colors.black,
                fontName='Helvetica-Bold'
            ),
            'AnswerStyle': ParagraphStyle(
                'AnswerStyle',
                parent=self.styles['Normal'],
                fontSize=10,
                textColor=colors.darkgreen,
                leftIndent=20
            )
        }
    
    def generate_tax_form_pdf(self, submission):
        """Generate PDF for tax form submission"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        story = []
        
        # Title
        title = f"{submission.form_type.display_name} - Submission {submission.id}"
        story.append(Paragraph(title, self.custom_styles['FormTitle']))
        
        # Submission info
        info_data = [
            ['Submission Date:', submission.submission_date.strftime('%Y-%m-%d %H:%M:%S')],
            ['Status:', submission.get_status_display()],
            ['Form Type:', submission.form_type.display_name]
        ]
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 20))
        
        # Process sections
        sections_data = {}
        for section_data in submission.section_data.all().order_by('section__order'):
            sections_data[section_data.section_key] = {
                'title': section_data.section.title,
                'questions': []
            }
        
        # Add questions and answers
        for answer in submission.answers.select_related('question__section').order_by('question__order'):
            section_key = answer.question.section.section_key
            if section_key in sections_data:
                value = answer.get_value()
                
                # Handle sensitive data
                if answer.question.is_sensitive and value:
                    if 'ssn' in answer.question.question_key.lower():
                        value = f"***-**-{str(value)[-4:]}" if len(str(value)) >= 4 else "***"
                    elif 'signature' in answer.question.question_key.lower():
                        value = "[Digital Signature Present]"
                
                # Format JSON data
                if answer.question.field_type == 'json' and isinstance(value, (list, dict)):
                    value = self._format_json_for_pdf(value)
                
                sections_data[section_key]['questions'].append({
                    'question': answer.question.question_text,
                    'answer': decrypt_value(str(value))
                })
        
        # Add sections to PDF
        for section_key, section_info in sections_data.items():
            if section_info['questions']:
                story.append(Paragraph(section_info['title'], self.custom_styles['SectionTitle']))
                
                for qa in section_info['questions']:
                    story.append(Paragraph(qa['question'], self.custom_styles['QuestionStyle']))
                    story.append(Paragraph(qa['answer'], self.custom_styles['AnswerStyle']))
                    story.append(Spacer(1, 6))
                
                story.append(Spacer(1, 12))
        
        # Add structured data sections
        if submission.dependents.exists():
            story.append(Paragraph("Dependents Information", self.custom_styles['SectionTitle']))
            
            for dep in submission.dependents.all():
                dep_data = [
                    ['Name:', f"{dep.first_name} {dep.last_name}"],
                    ['Relationship:', dep.relationship],
                    ['Date of Birth:', dep.date_of_birth.strftime('%Y-%m-%d') if dep.date_of_birth else 'Not provided'],
                    ['Months Lived with You:', str(dep.months_lived_with_you)],
                    ['Full-time Student:', 'Yes' if dep.is_full_time_student else 'No'],
                    ['Child Care Expense:', f"${dep.child_care_expense}"]
                ]
                
                dep_table = Table(dep_data, colWidths=[2*inch, 4*inch])
                dep_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))
                
                story.append(dep_table)
                story.append(Spacer(1, 12))
        
        if submission.business_owners.exists():
            story.append(Paragraph("Business Owners Information", self.custom_styles['SectionTitle']))
            
            for owner in submission.business_owners.all():
                owner_data = [
                    ['Name:', f"{owner.first_name} {owner.initial} {owner.last_name}".strip()],
                    ['Ownership %:', f"{owner.ownership_percentage}%"],
                    ['Address:', f"{owner.address}, {owner.city}, {owner.state} {owner.zip_code}"],
                    ['Phone:', owner.work_phone],
                    ['Country:', owner.country]
                ]
                
                owner_table = Table(owner_data, colWidths=[2*inch, 4*inch])
                owner_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))
                
                story.append(owner_table)
                story.append(Spacer(1, 12))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()
    
    def _format_json_for_pdf(self, json_data):
        """Format JSON data for readable PDF display"""
        if isinstance(json_data, list):
            if not json_data:
                return "No items"
            
            formatted_items = []
            for i, item in enumerate(json_data, 1):
                if isinstance(item, dict):
                    item_str = f"Item {i}: " + ", ".join([f"{k}: {v}" for k, v in item.items() if v])
                else:
                    item_str = f"Item {i}: {str(item)}"
                formatted_items.append(item_str)
            
            return "; ".join(formatted_items)
        
        elif isinstance(json_data, dict):
            return ", ".join([f"{k}: {v}" for k, v in json_data.items() if v])
        
        return str(json_data)