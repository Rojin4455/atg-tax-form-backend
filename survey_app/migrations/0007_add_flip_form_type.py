# Generated migration for Flip Organizer

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('survey_app', '0006_taxengagementletter'),
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
                ],
                max_length=20
            ),
        ),
    ]
