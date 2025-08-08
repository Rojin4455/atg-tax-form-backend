def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


from .models import UserProfile

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