from urllib.parse import urlparse

from decouple import config

from .models import UserProfile
from typing import Protocol, Dict, Any, Union, List, Tuple, Optional


def get_frontend_base_url_from_request(request, *, env_fallback_key='TRUST_FRONTEND_BASE_URL', default='http://localhost:8081'):
    """
    Resolve the trust/estate frontend origin from the incoming request.

    Uses HTTP_ORIGIN, then HTTP_REFERER (scheme + host only). Falls back to env
    TRUST_FRONTEND_BASE_URL, then FRONTEND_BASE_URL, then default.
    """
    origin = (request.META.get('HTTP_ORIGIN') or request.META.get('HTTP_REFERER') or '').strip()
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme and parsed.netloc:
            return f'{parsed.scheme}://{parsed.netloc}'.rstrip('/')
        return origin.rstrip('/')

    fallback = config(env_fallback_key, default='')
    if fallback:
        return str(fallback).rstrip('/')
    return config('FRONTEND_BASE_URL', default=default).rstrip('/')


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip



class GHLCustomFields:
    LEGAL_NAME = {
        "id": "P8RTYweBi26MBBRkRMiJ",
        "field_key": "contact.legal_name",
        "name": "Legal Name"
    }
    PARTNERS_NAME = {
        "id": "9Mg0GSwX0dKGw3KTvDSO",
        "field_key": "contact.partners_name",
        "name": "Partner(s) Name"
    }
    NUMBER_OF_BUSINESSES = {
        "id": "3K4KkCmBUcLiPnPNwpIH",
        "field_key": "contact.number_of_businesse",
        "name": "Number of Business"
    }
    IS_FIRST_YEAR = {
        "id": "x2mDP54dxUV5ZtL0MOjL",
        "field_key": "contact.is_first_year",
        "name": "Is First Year?"
    }
    PRIOR_YEAR_TAX_RETURN = {
        "id": "BLrF99BxpreB69RWCVoY",
        "field_key": "contact.prioryear_tax_return",
        "name": "Prior-Year Tax Return"
    }
    HAS_SMART_VAULT = {
        "id": "IQR9RTKT6lp6Jol6pmR3",
        "field_key": "contact.has_smartvault",
        "name": "Has SmartVault"
    }



class GHLFileUploadProtocol(Protocol):
    def upload_and_format_custom_field(
        self, 
        ghl_service, 
        file_name: str, 
        file_content: bytes, 
        mime_type: str, 
        entity_id: str
    ) -> Tuple[Optional[str], Union[str, List[Dict[str, Any]], None]]:
        pass

class MediaFileUploadHandler:
    def upload_and_format_custom_field(
        self, 
        ghl_service, 
        file_name: str, 
        file_content: bytes, 
        mime_type: str, 
        entity_id: str
    ) -> Tuple[Optional[str], Union[str, List[Dict[str, Any]], None]]:
        upload_res = ghl_service.upload_media_file(
            file_name=file_name,
            file_content=file_content,
            mime_type=mime_type
        )
        file_url = upload_res.get("fileUrl") or upload_res.get("url")
        return file_url, file_url

class CustomFieldFileUploadHandler:
    def upload_and_format_custom_field(
        self, 
        ghl_service, 
        file_name: str, 
        file_content: bytes, 
        mime_type: str, 
        entity_id: str
    ) -> Tuple[Optional[str], Union[str, List[Dict[str, Any]], None]]:
        upload_res = ghl_service.upload_custom_field_file(
            entity_id=entity_id,
            file_name=file_name,
            file_content=file_content,
            mime_type=mime_type
        )
        meta_data = upload_res.get("meta", [])
        if meta_data:
            file_url = meta_data[0].get("url")
            field_value = [
                {
                    "url": file_url,
                    "meta": {
                        "mimetype": meta_data[0].get("mimetype"),
                        "name": meta_data[0].get("originalname"),
                        "size": meta_data[0].get("size")
                    },
                    "deleted": False
                }
            ]
            return file_url, field_value
        return None, None

def get_ghl_file_upload_adapter(use_media_upload: bool = False) -> GHLFileUploadProtocol:
    """Factory function to grab the correct upload strategy."""
    if use_media_upload:
        return MediaFileUploadHandler()
    return CustomFieldFileUploadHandler()

def get_or_create_ghl_contact(user):
    """
    Ensures the user has a UserProfile.
    If the UserProfile lacks a ghl_contact_id, query the GHL API by email using advanced search.
    If a contact is found in GHL, save and return the ghl_contact_id.
    If not found, create a contact in GHL, save and return the ghl_contact_id.
    """
    import logging
    import requests
    from accounts.models import GHLAuthCredentials
    
    logger = logging.getLogger(__name__)

    profile, created = UserProfile.objects.get_or_create(user=user)
    
    # If we already have the GHL ID stored or temporarily attached, use it
    if profile.ghl_contact_id:
        return profile.ghl_contact_id
    if getattr(user, "_ghl_contact_id", None):
        profile.ghl_contact_id = user._ghl_contact_id
        profile.save()
        return profile.ghl_contact_id

    # If ghl_contact_id is empty, resolve it from GHL
    try:
        token = GHLAuthCredentials.objects.get(location_id='3zdgsEJTjNPONjCuEzbx')
    except GHLAuthCredentials.DoesNotExist:
        token = GHLAuthCredentials.objects.first()

    if not token or not token.access_token:
        logger.warning(f"No GHL credentials found to resolve contact for user {user.email}")
        return None

    ghl_token = token.access_token
    location_id = token.location_id
    headers = {
        'Authorization': f'Bearer {ghl_token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Version': '2021-07-28',
    }

    # 1. Search if contact exists in GHL by email using advanced search POST API
    search_url = "https://services.leadconnectorhq.com/contacts/search"
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
        if response.status_code == 200 and response.json().get("contacts"):
            contact_id = response.json()["contacts"][0]["id"]
            profile.ghl_contact_id = contact_id
            profile.save()

            # Update basic details in GHL to make sure it's in sync
            update_url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
            update_data = {
                "email": user.email,
                "firstName": user.first_name or "",
                "lastName": user.last_name or "",
                "customFields": [
                    {"id": "QmI5yIMWYdY17ijOr4ta", "field_value": user.username},
                ],
            }
            requests.put(update_url, json=update_data, headers=headers)
            return contact_id
        else:
            # 2. Contact does not exist — Create it in GHL
            create_url = "https://services.leadconnectorhq.com/contacts/"
            create_data = {
                "email": user.email,
                "firstName": user.first_name or "",
                "lastName": user.last_name or "",
                "locationId": location_id,
                "customFields": [
                    {"id": "QmI5yIMWYdY17ijOr4ta", "field_value": user.username},
                ],
            }
            create_res = requests.post(create_url, json=create_data, headers=headers)
            if create_res.status_code in (200, 201):
                contact_id = create_res.json().get("contact", {}).get("id")
                if contact_id:
                    profile.ghl_contact_id = contact_id
                    profile.save()
                    return contact_id
    except Exception as e:
        logger.error(f"Error resolving/creating GHL contact for user {user.email}: {e}")

    return None