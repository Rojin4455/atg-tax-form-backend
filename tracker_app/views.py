from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import UserFinanceData
from .serializers import UserFinanceDataSerializer
from survey_app.helpers import update_ghl_contact_tags_and_links

class UserFinanceDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        finance_data, created = UserFinanceData.objects.get_or_create(user=request.user)
        serializer = UserFinanceDataSerializer(finance_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        finance_data, created = UserFinanceData.objects.get_or_create(user=request.user)
        serializer = UserFinanceDataSerializer(finance_data, data=request.data)
        if serializer.is_valid():
            serializer.save()
            update_ghl_contact_tags_and_links(user=request.user,is_tracker=True, tracker_tag="Tracker Added")
            return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        try:
            finance_data = UserFinanceData.objects.get(user=request.user)
        except UserFinanceData.DoesNotExist:
            return Response({"error": "Finance data not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = UserFinanceDataSerializer(finance_data, data=request.data)
        if serializer.is_valid():
            serializer.save()
            update_ghl_contact_tags_and_links(user=request.user,is_tracker=True, tracker_tag="Tracker Added")
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        

    def delete(self, request):
        finance_data = UserFinanceData.objects.filter(user=request.user).first()
        if finance_data:
            finance_data.delete()
            update_ghl_contact_tags_and_links(user=request.user,is_tracker=True, tracker_tag="Tracker Resetted")
            return Response({"message": "Finance data deleted successfully."}, status=status.HTTP_200_OK)
        return Response({"message": "No finance data found. Nothing to delete."}, status=status.HTTP_200_OK)

