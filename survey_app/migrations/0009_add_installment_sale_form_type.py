from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('survey_app', '0008_alter_surveysubmission_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='surveysubmission',
            name='form_type',
            field=models.CharField(
                choices=[
                    ('personal', 'Personal'),
                    ('business', 'Business'),
                    ('rental', 'Rental'),
                    ('flip', 'Flip'),
                    ('installment_sale', 'Installment Sale'),
                ],
                max_length=20,
            ),
        ),
    ]
