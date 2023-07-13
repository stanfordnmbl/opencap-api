"""mcserver URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from mcserver.views import (
    SessionViewSet, VideoViewSet,
    TrialViewSet, ResultViewSet,
    SubjectViewSet, DownloadFileOnReadyAPIView,
    UserCreate,
    CustomAuthToken, verify,
    reset_otp_challenge,
    check_otp_verified,
    UserViewSet, ResetPasswordView, NewPasswordView)
from rest_framework import routers, serializers, viewsets
from rest_framework.authtoken.views import obtain_auth_token

from django_otp.forms import OTPAuthenticationForm
from django.http import HttpResponse

router = routers.DefaultRouter()

router.register(r'sessions', SessionViewSet, "session")
router.register(r'videos', VideoViewSet)
router.register(r'trials', TrialViewSet)
router.register(r'results', ResultViewSet)
router.register(r'subjects', SubjectViewSet, "subject")
router.register(r'users', UserViewSet)

urlpatterns = [
#    path('session/', new_session),
    path('', include(router.urls)),
    path("health/", lambda x: HttpResponse("OK"), name="health"),
#    path('session/<id>/status/', status),
    path('login/', CustomAuthToken.as_view()),
    path('verify/', verify),
    path('reset-otp-challenge/', reset_otp_challenge),
    path('check-otp-verified/', check_otp_verified),
    path('admin/', admin.site.urls),
    path('register/', UserCreate.as_view(), name='account-create'),
    path('reset-password/', ResetPasswordView.as_view()),
    path('new-password/', NewPasswordView.as_view()),
    path(
        'logs/<str:task_id>/on-ready/',
        DownloadFileOnReadyAPIView.as_view(),
        name="logs-on-ready"
    )
#    path('accounts/login/', OTPAuthenticationForm.as_view(authentication_form=OTPAuthenticationForm)),
]
