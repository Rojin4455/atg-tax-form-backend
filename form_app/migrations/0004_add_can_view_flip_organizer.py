# Generated migration for Flip Organizer permission

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('form_app', '0003_add_admin_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='can_view_flip_organizer',
            field=models.BooleanField(default=False, help_text='Permission to view flip organizer data'),
        ),
    ]
