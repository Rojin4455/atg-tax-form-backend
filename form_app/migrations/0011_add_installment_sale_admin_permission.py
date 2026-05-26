from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('form_app', '0010_ssocode'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='can_view_installment_sale_organizer',
            field=models.BooleanField(default=False, help_text='Permission to view installment sale organizer data'),
        ),
    ]
