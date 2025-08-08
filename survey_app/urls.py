from django.urls import path
from .views import SurveySubmissionListView,SurveySubmissionCreateView,SurveySubmissionDetailView

urlpatterns = [
    path('all-submissions/', SurveySubmissionListView.as_view(), name='submission-list'),
    path('submit-tax-form/', SurveySubmissionCreateView.as_view(), name='submission-create'),
    path('submit-tax-form/<uuid:id>/', SurveySubmissionDetailView.as_view(), name='submission-detail'),
]
