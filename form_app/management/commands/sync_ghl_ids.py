import requests
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from form_app.models import UserProfile
from accounts.models import GHLAuthCredentials
from django.db.models import Q

class Command(BaseCommand):
    help = 'Syncs missing GHL contact IDs for users without creating new contacts in GHL.'

    def handle(self, *args, **options):
        # Find users with no profile OR profile with no ghl_contact_id
        users_missing_ghl = User.objects.filter(
            Q(userprofile__isnull=True) | 
            Q(userprofile__ghl_contact_id__isnull=True) | 
            Q(userprofile__ghl_contact_id='')
        ).distinct()

        total_users = users_missing_ghl.count()
        if total_users == 0:
            self.stdout.write(self.style.SUCCESS('All users have a GHL contact ID.'))
            return

        self.stdout.write(f'Found {total_users} users missing GHL contact ID. Starting sync...')

        try:
            token = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')
        except GHLAuthCredentials.DoesNotExist:
            token = GHLAuthCredentials.objects.first()

        if not token or not token.access_token:
            self.stdout.write(self.style.ERROR('No GHL credentials found in the database. Cannot sync.'))
            return

        ghl_token = token.access_token
        location_id = token.location_id
        headers = {
            'Authorization': f'Bearer {ghl_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Version': '2021-07-28',
        }

        search_url = "https://services.leadconnectorhq.com/contacts/search"

        success_count = 0
        not_found_count = 0
        error_count = 0

        for user in users_missing_ghl:
            self.stdout.write(f'\nProcessing user: {user.email} (ID: {user.id})')
            
            search_payload = {
                "locationId": location_id,
                "pageLimit": 10,
                "filters": [
                    {
                        "field": "email",
                        "operator": "eq",
                        "value": user.email
                    }
                ]
            }

            try:
                response = requests.post(search_url, json=search_payload, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("contacts"):
                        contact_id = data["contacts"][0]["id"]
                        
                        # Get or create UserProfile so we can save the found ID
                        profile, _ = UserProfile.objects.get_or_create(user=user)
                        profile.ghl_contact_id = contact_id
                        profile.save()
                        
                        self.stdout.write(self.style.SUCCESS(f'  [SUCCESS] Linked GHL ID {contact_id} to user {user.email}.'))
                        success_count += 1
                    else:
                        self.stdout.write(self.style.ERROR(f'  [ERROR] User {user.email} NOT FOUND in GHL. No contact was created.'))
                        not_found_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f'  [ERROR] API request failed for {user.email}: {response.status_code} - {response.text}'))
                    error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [ERROR] Exception occurred for {user.email}: {e}'))
                error_count += 1

        self.stdout.write(self.style.WARNING(f'\nSummary:'))
        self.stdout.write(f'Total Processed: {total_users}')
        self.stdout.write(self.style.SUCCESS(f'Successfully Linked: {success_count}'))
        self.stdout.write(self.style.ERROR(f'Not Found in GHL: {not_found_count}'))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'API/Other Errors: {error_count}'))
