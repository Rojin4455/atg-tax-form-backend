import requests
from django.conf import settings
from form_app.models import UserProfile
from accounts.models import GHLAuthCredentials
from decouple import config

def update_ghl_contact_tags_and_links(user, form_type, status, form_id):
    try:
        print(f"[DEBUG] Starting GHL update for user={user}, form_type={form_type}, status={status}, form_id={form_id}")

        # --- Get GHL contact ID ---
        profile = UserProfile.objects.get(user=user)
        ghl_contact_id = profile.ghl_contact_id
        print(f"[DEBUG] GHL Contact ID: {ghl_contact_id}")
        if not ghl_contact_id:
            print("[DEBUG] No GHL contact ID found — aborting")
            return

        # --- Get GHL API credentials ---
        ghl_creds = GHLAuthCredentials.objects.first()
        print(f"[DEBUG] GHL credentials found: {bool(ghl_creds)}")
        if not ghl_creds:
            print("[DEBUG] No GHL credentials found — aborting")
            return

        ghl_token = ghl_creds.access_token
        headers = {
            'Authorization': f'Bearer {ghl_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Version': '2021-07-28',
        }

        # --- Step 1: Fetch existing tags ---
        tags_url = f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}"
        print(f"[DEBUG] Fetching existing tags from: {tags_url}")
        resp = requests.get(tags_url, headers=headers)
        print(f"[DEBUG] Tags fetch response status: {resp.status_code}")
        print(f"[DEBUG] Tags fetch response body: {resp.text}")

        if resp.status_code != 200:
            print("[DEBUG] Failed to fetch tags — aborting")
            return

        contact_data = resp.json()
        existing_tags = contact_data.get("contact", {}).get("tags", [])
        print(f"[DEBUG] Existing tags: {existing_tags}")

        # --- Step 2: Remove old tag of same form type ---
        prefix = f"{form_type}_form_"
        updated_tags = [t for t in existing_tags if not t.startswith(prefix)]

        # --- Step 3: Add new tag ---
        new_tag = f"{form_type}_form_{status}"
        if new_tag not in updated_tags:
            updated_tags.append(new_tag)
        print(f"[DEBUG] Final tags list to send: {updated_tags}")

        # --- Step 4: Manage form link ---
        FORM_LINK_FIELD_IDS = {
            "personal": "tMVGgl6hCjaZH9V1nIec",
            "business": "WUfba2ft47FUmB5nLIbJ",
            "rental": "QCyDdzWXmNtUJ4gauM2f"
        }
        custom_field_id = FORM_LINK_FIELD_IDS.get(form_type)
        print(f"[DEBUG] Using custom field ID: {custom_field_id}")

        if status == "drafted":
            link_url = f"{config('FRONTEND_BASE_URL')}/?type={form_type}&form_id={form_id}"
            print(f"[DEBUG] Setting drafted form link: {link_url}")
            link_resp = requests.put(
                f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}",
                json={
                    "customFields": [{"id": custom_field_id, "field_value": link_url}],
                    "tags": updated_tags
                },
                headers=headers
            )
            print(f"[DEBUG] Set link response: {link_resp.status_code} {link_resp.text}")
        else:
            print(f"[DEBUG] Removing form link for status={status}")
            remove_link_resp = requests.put(
                f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}",
                json={
                    "customFields": [{"id": custom_field_id, "field_value": ""}],
                    "tags": updated_tags
                },
                headers=headers
            )
            print(f"[DEBUG] Remove link response: {remove_link_resp.status_code} {remove_link_resp.text}")

        print("[DEBUG] GHL contact update completed successfully.")

    except UserProfile.DoesNotExist:
        print(f"[DEBUG] UserProfile not found for user={user} — aborting")
    except Exception as e:
        print(f"[ERROR] Exception in update_ghl_contact_tags_and_links: {e}")

