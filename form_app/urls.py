from django.urls import path, include
from rest_framework.routers import DefaultRouter
from form_app import views
from rest_framework_simplejwt.views import TokenRefreshView


router = DefaultRouter()
router.register(r'submissions', views.TaxFormSubmissionViewSet, basename='taxformsubmission')

urlpatterns = [
    path('tax-forms/', include(router.urls)),
    path('signup/', views.UserSignupView.as_view(), name='user-signup'),
    path('login/', views.UserLoginView.as_view(), name='user-login'),
    path('logout/', views.UserLogoutView.as_view(), name='user-logout'),
    
    # Password reset
    path('forgot-password/request-otp/', views.RequestOTPView.as_view(), name='request-otp'),
    path('forgot-password/submit-otp/', views.SubmitOTPView.as_view(), name='submit-otp'),
    
    # Token refresh
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]