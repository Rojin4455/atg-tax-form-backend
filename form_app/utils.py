from .models import UserProfile
from typing import Protocol, Dict, Any, Union, List, Tuple, Optional


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

def create_or_update_user_profile(instance):
    """
    Create profile when user is created, and also update ghl_contact_id if available.

    """
    print("reached herererere:``` ")

    profile, _ = UserProfile.objects.get_or_create(user=instance)

    print("reached herererere: ", profile)

    # If we have a GHL contact ID from signup view, save it
    ghl_contact_id = getattr(instance, "_ghl_contact_id", None)
    if ghl_contact_id:
        profile.ghl_contact_id = ghl_contact_id
        profile.save()