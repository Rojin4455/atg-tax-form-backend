from django.urls import path
from .views import *

urlpatterns = [
    path("finance-data/", UserFinanceDataView.as_view(), name="finance-data"),
    path("tracker-download/", TrackerDownloaded.as_view(), name="tracker-download"),
]