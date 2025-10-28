import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from accounts.models import GHLAuthCredentials  # adjust import as needed


class GHLCreateOrUpdateContactView(APIView):
    """
    Public endpoint to create or update a GHL contact and add a 'questionnaire_added' tag.
    If both email and phone belong to different contacts, it updates only email contact without phone.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        username = request.data.get("username")
        phone = request.data.get("phone")

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch stored credentials
        try:
            creds = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')
            ghl_token = creds.access_token
            location_id = creds.location_id
        except GHLAuthCredentials.DoesNotExist:
            return Response({"error": "GHL credentials not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        headers = {
            "Authorization": f"Bearer {ghl_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Version": "2021-07-28",
        }

        # --- Step 1: Search by email ---
        email_search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={email}"
        email_search_res = requests.get(email_search_url, headers=headers)
        email_contact = None
        if email_search_res.status_code == 200 and email_search_res.json().get("contacts"):
            email_contact = email_search_res.json()["contacts"][0]

        # --- Step 2: Search by phone (if given) ---
        phone_contact = None
        if phone:
            phone_search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={phone}"
            phone_search_res = requests.get(phone_search_url, headers=headers)
            if phone_search_res.status_code == 200 and phone_search_res.json().get("contacts"):
                phone_contact = phone_search_res.json()["contacts"][0]
                print("phonecont: ", phone_contact)

        # --- Step 3: If email contact exists ---
        if email_contact:
            contact_id = email_contact["id"]
            existing_tags = email_contact.get("tags", [])
            all_tags = list(set(existing_tags + ["questionnaire_added"]))

            # If phone belongs to a *different* contact, do not update phone
            if phone_contact and phone_contact["id"] != contact_id:
                update_payload = {
                    "email": email,
                    "name": username,
                    "tags": all_tags,
                }
            else:
                update_payload = {
                    "email": email,
                    "name": username,
                    "phone": phone,
                    "tags": all_tags,
                }

            update_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
            update_res = requests.put(update_url, json=update_payload, headers=headers)

            if update_res.status_code in (200, 201):
                return Response(
                    {"message": "Contact updated successfully", "contact_id": contact_id},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"error": "Failed to update contact", "details": update_res.text},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # --- Step 4: Create new contact if not exists ---
        contact_payload = {
            "email": email,
            "name": username,
            "phone": phone,
            "locationId": location_id,
            "tags": ["questionnaire_added"],
        }
        create_url = "https://services.leadconnectorhq.com/contacts/"
        create_res = requests.post(create_url, json=contact_payload, headers=headers)

        if create_res.status_code in (200, 201):
            ghl_contact_id = create_res.json().get("contact", {}).get("id")
            return Response(
                {"message": "Contact created successfully", "contact_id": ghl_contact_id},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response(
                {"error": "Failed to create contact", "details": create_res.text},
                status=status.HTTP_400_BAD_REQUEST,
            )
