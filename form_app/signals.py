# # signals.py
# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from django.contrib.auth.models import User
# from .models import UserProfile

# @receiver(post_save, sender=User)
# def create_or_update_user_profile(sender, instance, created, **kwargs):
#     """
#     Create profile when user is created, and also update ghl_contact_id if available.

#     """
#     print("reached herererere:``` ")

#     profile, _ = UserProfile.objects.get_or_create(user=instance)

#     print("reached herererere: ", profile)

#     # If we have a GHL contact ID from signup view, save it
#     ghl_contact_id = getattr(instance, "_ghl_contact_id", None)
#     if ghl_contact_id:
#         profile.ghl_contact_id = ghl_contact_id
#         profile.save()
