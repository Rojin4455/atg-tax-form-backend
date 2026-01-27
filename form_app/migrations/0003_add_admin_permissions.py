# Generated manually for admin permissions

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('form_app', '0002_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='is_admin',
            field=models.BooleanField(default=False, help_text='Designates if this user is an admin'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='is_super_admin',
            field=models.BooleanField(default=False, help_text='Designates if this user is a super admin with full access'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='can_list_users',
            field=models.BooleanField(default=False, help_text='Permission to list and view users'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='can_view_personal_organizer',
            field=models.BooleanField(default=False, help_text='Permission to view personal organizer data'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='can_view_business_organizer',
            field=models.BooleanField(default=False, help_text='Permission to view business organizer data'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='can_view_rental_organizer',
            field=models.BooleanField(default=False, help_text='Permission to view rental organizer data'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='can_view_engagement_letter',
            field=models.BooleanField(default=False, help_text='Permission to view engagement letter data'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]
