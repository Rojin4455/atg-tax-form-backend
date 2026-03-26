"""
SSO views — backend-orchestrated single-sign-on between App1 and App2.

Flow:
  App1 (authenticated) → POST /api/form/sso/issue-code/  → {"code": "<uuid>"}
  App1 redirects user   → https://trust.../sso-callback?code=<uuid>
  App2                  → POST /api/form/sso/exchange/   → {access, refresh, user}
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import SSOCode

SSO_CODE_TTL_MINUTES = 5


class SSOIssueCodeView(APIView):
    """
    POST /api/form/sso/issue-code/
    Requires: Bearer token (IsAuthenticated)

    Creates a 5-minute single-use code for the authenticated user and returns it.
    App1 calls this after confirming the user is logged in, then redirects App2
    to /sso-callback?code=<uuid>.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Expire any existing unused codes for this user to avoid accumulation
        SSOCode.objects.filter(user=request.user, used=False).delete()

        expires_at = timezone.now() + timedelta(minutes=SSO_CODE_TTL_MINUTES)
        sso_code = SSOCode.objects.create(user=request.user, expires_at=expires_at)

        return Response(
            {"code": str(sso_code.code), "expires_in_seconds": SSO_CODE_TTL_MINUTES * 60},
            status=status.HTTP_201_CREATED,
        )


class SSOExchangeView(APIView):
    """
    POST /api/form/sso/exchange/
    Body: { "code": "<uuid>" }
    Auth: none (AllowAny) — the code itself proves identity

    Validates the code, marks it as used, and returns fresh JWT tokens + user details.
    App2 uses the response to populate Redux + localStorage without any sensitive data
    having traversed a URL.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        code_str = request.data.get("code")
        if not code_str:
            return Response({"error": "code is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            sso_code = SSOCode.objects.select_related("user").get(code=code_str)
        except SSOCode.DoesNotExist:
            return Response({"error": "Invalid code"}, status=status.HTTP_400_BAD_REQUEST)

        if sso_code.used:
            return Response({"error": "Code already used"}, status=status.HTTP_400_BAD_REQUEST)

        if sso_code.expires_at <= timezone.now():
            return Response({"error": "Code expired"}, status=status.HTTP_400_BAD_REQUEST)

        # Mark as used immediately to prevent replay attacks
        sso_code.used = True
        sso_code.save(update_fields=["used"])

        user = sso_code.user

        # Issue fresh JWT pair for this user
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "onboard_required": getattr(getattr(user, "userprofile", None), "onboard_required", False),
                },
            },
            status=status.HTTP_200_OK,
        )
