import requests
from django.conf import settings
from form_app.models import UserProfile
from accounts.models import GHLAuthCredentials
from decouple import config
import base64
import uuid
from django.core.files.base import ContentFile
from tempfile import NamedTemporaryFile
import os

def update_ghl_contact_tags_and_links(user, form_type, status, form_id, pdf_data=None):
    try:
        print(f"[DEBUG] Starting GHL update for user={user}, form_type={form_type}, status={status}, form_id={form_id}")
        print(f"[DEBUG] PDF data provided: {bool(pdf_data)}")

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
            'Version': '2021-07-28',
        }

        # --- Step 1: Fetch existing tags ---
        tags_url = f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}"
        resp = requests.get(tags_url, headers=headers)
        print(f"[DEBUG] Tags fetch response status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[DEBUG] Failed to fetch tags — response: {resp.text}")
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

        # --- Step 4: Manage form link + PDF ---
        FORM_LINK_FIELD_IDS = {
            "personal": "tMVGgl6hCjaZH9V1nIec",
            "business": "WUfba2ft47FUmB5nLIbJ",
            "rental": "QCyDdzWXmNtUJ4gauM2f"
        }
        FORM_PDF_FIELD_IDS = {
            "personal": "0KNK08rbVnK3VOgN0QMw",
            "business": "vMAxcikxmYHhEqUX7Q0J",  # Update when created
            "rental": "0u5IVof2PwxJpLDbtayd"      # Update when created
        }

        link_field_id = FORM_LINK_FIELD_IDS.get(form_type)
        pdf_field_id = FORM_PDF_FIELD_IDS.get(form_type)

        custom_fields = []

        # --- Handle form links based on status ---
        if status == "drafted":
            # For drafted forms: set the form link
            link_url = f"{config('FRONTEND_BASE_URL')}/?type={form_type}&form_id={form_id}"
            print(f"[DEBUG] Setting drafted form link: {link_url}")
            if link_field_id:
                custom_fields.append({"id": link_field_id, "field_value": link_url})
        else:
            # For non-drafted forms: clear the form link
            print(f"[DEBUG] Removing form link for status={status}")
            if link_field_id:
                custom_fields.append({"id": link_field_id, "field_value": ""})

        # --- Handle PDF upload if provided ---
        if pdf_data and pdf_field_id and pdf_field_id != "YOUR_BUSINESS_PDF_FIELD_ID" and pdf_field_id != "YOUR_RENTAL_PDF_FIELD_ID":
            try:
                print(f"[DEBUG] Processing PDF data for form_type={form_type}")
                
                # Handle base64 data URL format
                if pdf_data.startswith("data:"):
                    print("[DEBUG] PDF data is in data URL format, extracting base64")
                    pdf_data = pdf_data.split(",")[1]
                
                # Decode base64 PDF data
                try:
                    decoded_file = base64.b64decode(pdf_data)
                    print(f"[DEBUG] Successfully decoded PDF data, size: {len(decoded_file)} bytes")
                except Exception as decode_error:
                    print(f"[ERROR] Failed to decode base64 PDF data: {decode_error}")
                    return

                # Create temporary file and upload to GHL
                with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(decoded_file)
                    tmp.flush()
                    
                    # Generate unique filename
                    filename = f"{form_type}_form_{form_id}_{uuid.uuid4().hex[:8]}.pdf"
                    
                    print(f"[DEBUG] Uploading PDF to GHL with filename: {filename}")
                    
                    # Reset file pointer for reading
                    tmp.seek(0)
                    
                    # Upload to GHL
                    upload_resp = requests.post(
                        "https://services.leadconnectorhq.com/medias/upload-file",
                        headers={
                            'Authorization': f'Bearer {ghl_token}',
                            'Accept': 'application/json',
                            'Version': '2021-07-28',
                        },
                        files={"file": (filename, tmp, "application/pdf")},
                        data={
                            "hosted": "false", 
                            "name": filename
                        }
                    )

                # Clean up temp file
                try:
                    os.unlink(tmp.name)
                except Exception as cleanup_error:
                    print(f"[WARNING] Failed to cleanup temp file: {cleanup_error}")

                print(f"[DEBUG] GHL Upload response: {upload_resp.status_code}")
                print(f"[DEBUG] GHL Upload response body: {upload_resp.text}")

                if upload_resp.status_code in [200, 201]:
                    upload_data = upload_resp.json()
                    file_url = upload_data.get("fileUrl") or upload_data.get("url")

                    if file_url:
                        print(f"[DEBUG] Successfully uploaded PDF, setting file URL: {file_url}")

                        # Step 1 - clear old file field
                        clear_payload = {
                            "customFields": [{"id": pdf_field_id, "value": ""}]
                        }
                        requests.put(
                            f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}",
                            json=clear_payload,
                            headers={**headers, "Content-Type": "application/json"}
                        )
                        print(f"[DEBUG] Cleared old PDF for field {pdf_field_id}")

                        # Step 2 - set new file
                        custom_fields.append({"id": pdf_field_id, "value": file_url})

                    else:
                        print("[ERROR] No file URL returned from GHL upload")
                        print(f"[DEBUG] Full upload response: {upload_data}")
                    
            except Exception as pdf_error:
                print(f"[ERROR] Failed to process PDF: {pdf_error}")
                import traceback
                print(f"[ERROR] PDF processing traceback: {traceback.format_exc()}")
        
        elif pdf_data and not pdf_field_id:
            print(f"[WARNING] PDF data provided but no PDF field ID configured for form_type={form_type}")
        
        elif pdf_data and pdf_field_id in ["YOUR_BUSINESS_PDF_FIELD_ID", "YOUR_RENTAL_PDF_FIELD_ID"]:
            print(f"[WARNING] PDF field ID not yet configured for form_type={form_type}")

        # --- Update contact with tags + custom fields ---
        update_payload = {
            "tags": updated_tags
        }
        
        # Only include customFields if we have some to update
        if custom_fields:
            update_payload["customFields"] = custom_fields
            print(f"[DEBUG] Updating custom fields: {custom_fields}")

        update_resp = requests.put(
            f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}",
            json=update_payload,
            headers={**headers, "Content-Type": "application/json"}
        )
        
        print(f"[DEBUG] Contact update response status: {update_resp.status_code}")
        print(f"[DEBUG] Contact update response body: {update_resp.text}")
        
        if update_resp.status_code == 200:
            print("[DEBUG] GHL contact update completed successfully.")
        else:
            print(f"[ERROR] Failed to update GHL contact: {update_resp.status_code} - {update_resp.text}")

    except UserProfile.DoesNotExist:
        print(f"[DEBUG] UserProfile not found for user={user} — aborting")
    except Exception as e:
        print(f"[ERROR] Exception in update_ghl_contact_tags_and_links: {e}")
        import traceback
        print(f"[ERROR] Full traceback: {traceback.format_exc()}")


