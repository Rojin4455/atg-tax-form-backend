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
    
    # Admin endpoints
    path('admin/login/', views.AdminLoginView.as_view(), name='admin-login'),
    path('admin/users/', views.AdminUserListView.as_view(), name='admin-users-list'),
    path('admin/users/toggle-active/', views.AdminUserToggleActiveView.as_view(), name='admin-toggle-user-active'),
    path('admin/users/<int:user_id>/forms/', views.AdminUserFormsView.as_view(), name='admin-user-forms'),
    
    # Password reset
    path('forgot-password/request-otp/', views.RequestOTPView.as_view(), name='request-otp'),
    path('forgot-password/submit-otp/', views.SubmitOTPView.as_view(), name='submit-otp'),
    
    # Token refresh
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]