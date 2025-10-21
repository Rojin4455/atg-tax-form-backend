import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from accounts.models import GHLAuthCredentials  # adjust import as needed


class GHLCreateOrUpdateContactView(APIView):
    """
    Public endpoint to create or update a GHL contact and add a 'questionnaire_added' tag.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        username = request.data.get("username")
        phone = request.data.get("phone")

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Fetch the stored GHL credentials (assuming single account setup)
            token = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')
            ghl_token = token.access_token
            location_id = token.location_id
        except GHLAuthCredentials.DoesNotExist:
            return Response({"error": "GHL credentials not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        headers = {
            "Authorization": f"Bearer {ghl_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Version": "2021-07-28",
        }

        # --- Step 1: Search for existing contact ---
        search_url = f"https://services.leadconnectorhq.com/contacts/?locationId={location_id}&query={email}"
        search_res = requests.get(search_url, headers=headers)

        ghl_contact_id = None
        contact_payload = {
            "email": email,
            "name": username,
            "phone": phone,
            "locationId": location_id,
            "tags": ["questionnaire_added"],  # add tag directly
        }

        # --- Step 2: If contact exists → update ---
        if search_res.status_code == 200 and search_res.json().get("contacts"):
            contact_data = search_res.json()["contacts"][0]
            contact_id = contact_data["id"]
            ghl_contact_id = contact_id

            # Get existing tags if present
            existing_tags = contact_data.get("tags", [])
            all_tags = list(set(existing_tags + ["questionnaire_added"]))  # avoid duplicates

            update_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
            update_payload = {
                "email": email,
                "name": username,
                "phone": phone,
                "locationId": location_id,
                "tags": all_tags,
            }

            update_res = requests.put(update_url, json=update_payload, headers=headers)

            if update_res.status_code in (200, 201):
                return Response(
                    {"message": "Contact updated successfully", "contact_id": ghl_contact_id},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"error": "Failed to update contact", "details": update_res.text},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # --- Step 3: If not exists → create new contact ---
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
