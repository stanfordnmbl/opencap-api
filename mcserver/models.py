from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid
import base64
from django.utils import timezone
from django.db.models.signals import post_save
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from rest_framework.authtoken.models import Token

from django.conf import settings

def random_filename(instance, filename):
    return "{}-{}".format(uuid.uuid4(), filename)
                                            

class User(AbstractUser):
    institution = models.CharField(max_length=128, blank=True, null=True)
    profession = models.CharField(max_length=128, blank=True, null=True)
    country = models.CharField(max_length=128, blank=True, null=True)
    reason = models.CharField(max_length=256, blank=True, null=True)
    otp_verified = models.BooleanField(default=False)
    newsletter = models.BooleanField(default=True)

class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, blank=False, null=False, on_delete=models.CASCADE)
    qrcode = models.FileField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    meta = models.JSONField(blank=True, null=True)
    public = models.BooleanField(blank=False, null=False, default=False)
    server = models.GenericIPAddressField(null=True, blank=True)

    def is_public(self):
        return self.public

    def get_user(self):
        return self.user

class Trial(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, blank=False, null=False, on_delete=models.CASCADE)
    status = models.CharField(max_length=64, default="recording")
    name = models.CharField(max_length=64, null=True)
    meta = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_public(self):
        return self.session.is_public()

    def get_user(self):
        return self.session.get_user()

class Video(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.UUIDField()
    trial = models.ForeignKey(Trial, blank=False, null=False, on_delete=models.CASCADE)
    video = models.FileField(blank=True, null=True, upload_to=random_filename)
    video_thumb = models.FileField(blank=True, null=True, upload_to=random_filename)
    keypoints = models.FileField(blank=True, null=True)
    parameters = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    def is_public(self):
        return self.trial.is_public()

    def get_user(self):
        return self.trial.get_user()

class Result(models.Model):
    trial = models.ForeignKey(Trial, blank=False, null=False, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=36, blank=True, null=True)
    media = models.FileField(blank=True, null=True, upload_to=random_filename,max_length=500)
    tag = models.CharField(max_length=32, blank=True, null=True)
    meta = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def is_public(self):
        return self.trial.is_public()

    def get_user(self):
        return self.trial.get_user()

class ResetPassword(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.CharField(max_length=255)
    datetime = models.DateField(default=timezone.now)

from django_otp.plugins.otp_email.models import EmailDevice
from django.template.loader import render_to_string
from mcserver.customEmailDevice import CustomEmailDevice

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    """Create a matching profile whenever a user object is created."""
    if created:
        device = EmailDevice(user = instance, name = "default e-mail")
        device.save()

@receiver(user_logged_in)
def post_login(sender, user, request, **kwargs):
    device = user.emaildevice_set.all()[0]

    # The default EmailDevice didn't allow the use of html,
    # so I have created a child class allowing it and here
    # I am casting the device to that class.
    device.__class__ = CustomEmailDevice

    # Get template from path and set variables. The {{token}}
    # is then substituted by the device by the real token.
    settings.OTP_EMAIL_BODY_TEMPLATE = render_to_string(settings.OTP_EMAIL_BODY_TEMPLATE_PATH) % (settings.LOGO_LINK, "{{token}}")

    # Set subject here, so everything is together.
    settings.OTP_EMAIL_SUBJECT = "Opencap - Verification Code"

    device.generate_challenge()
    print("CHALLENGE SENT")

