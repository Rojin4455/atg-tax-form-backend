from rest_framework import serializers
from .models import UserFinanceData

class UserFinanceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserFinanceData
        fields = ["income", "expenses"]
