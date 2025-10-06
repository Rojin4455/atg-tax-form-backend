from rest_framework import serializers
from .models import UserFinanceData

class UserFinanceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserFinanceData
        fields = ['id', 'user', 'finance_data', 'created_at', 'updated_at']
        read_only_fields = ['user', 'created_at', 'updated_at']
