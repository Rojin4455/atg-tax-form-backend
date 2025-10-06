from django.db import models
from django.contrib.auth.models import User

# Create your models here.

class UserFinanceData(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="finance_data")
    finance_data = models.JSONField(default=dict)  # Will store full JSON {businessTabs, activeTabId}
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Finance Data for {self.user.username}"