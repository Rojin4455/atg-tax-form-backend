from django.contrib import admin
from django.urls import path
from questionnaire_app.views import *

urlpatterns = [
    path('create-or-update-contact/', GHLCreateOrUpdateContactView.as_view(), name='ghl-create-update'),
]