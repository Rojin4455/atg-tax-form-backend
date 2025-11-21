from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import UserFinanceData
from .serializers import UserFinanceDataSerializer
from survey_app.helpers import update_ghl_contact_tags_and_links, add_ghl_contact_tag

class UserFinanceDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        finance_data = UserFinanceData.objects.filter(user=request.user).first()
        if not finance_data:
            return Response({"message": "No finance data found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = UserFinanceDataSerializer(finance_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # Create or overwrite finance data for user
        existing = UserFinanceData.objects.filter(user=request.user).first()
        if existing:
            serializer = UserFinanceDataSerializer(existing, data=request.data, partial=True)
        else:
            serializer = UserFinanceDataSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(user=request.user)
            update_ghl_contact_tags_and_links(
                user=request.user, is_tracker=True, tracker_tag="Tracker Added/Updated"
            )
            # Add "tax toolbox accessed" tag when user accesses tracker
            add_ghl_contact_tag(request.user, "tax toolbox accessed")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        finance_data = UserFinanceData.objects.filter(user=request.user).first()
        if finance_data:
            finance_data.delete()
            update_ghl_contact_tags_and_links(
                user=request.user, is_tracker=True, tracker_tag="Tracker Deleted"
            )
            return Response({"message": "Finance data deleted successfully."}, status=status.HTTP_200_OK)
        return Response({"message": "No finance data found."}, status=status.HTTP_404_NOT_FOUND)
    



class TrackerDownloaded(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        update_ghl_contact_tags_and_links(
                user=request.user, is_tracker=True, tracker_tag="Tracker Completed"
        )

        return Response({"message": "Finance data downloaded successfully."}, status=status.HTTP_200_OK)
