from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
import os
import uuid
import base64
import pathlib
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from rest_framework.authtoken.models import Token

from django.conf import settings


def random_filename(instance, filename):
    return "{}-{}".format(uuid.uuid4(), filename)


def archives_dir_path(instance, filename):
    filename, ext = filename.split(".")
    return os.path.join("archives", f"{filename}_{uuid.uuid4()}.{ext}")

                                            
class User(AbstractUser):
    institution = models.CharField(max_length=128, blank=True, null=True)
    profession = models.CharField(max_length=128, blank=True, null=True)
    country = models.CharField(max_length=128, blank=True, null=True)
    reason = models.CharField(max_length=256, blank=True, null=True)
    website = models.CharField(max_length=256, blank=True, null=True)
    otp_verified = models.BooleanField(default=False)
    otp_skip_till = models.DateTimeField(blank=True, null=True)
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

    subject = models.ForeignKey(
        'Subject', blank=True, null=True,
        related_name='sessions',
        on_delete=models.SET_NULL)

    trashed = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return str(self.id)

    def is_public(self):
        return self.public

    def get_user(self):
        return self.user

    # def save(self, *args, **kwargs):
    #     if self.subject:
    #         _subject_meta = self.subject.get_meta_dict()
    #         _meta = self.meta or dict()
    #         _meta.update({'subject': _subject_meta})
    #         self.meta = _meta
    #     super(Session, self).save(*args, **kwargs)


class Trial(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, blank=False, null=False, on_delete=models.CASCADE)
    status = models.CharField(max_length=64, default="recording")
    name = models.CharField(max_length=64, null=True)
    meta = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    trashed = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(blank=True, null=True)

    @property
    def formated_name(self):
        return self.name.replace(" ", "") if self.name else ""

    def is_public(self):
        return self.session.is_public()

    def get_user(self):
        return self.session.get_user()
    
    @classmethod
    def get_calibration_obj_or_none(cls, session_id):
        """ Returns trial with name `calibration` if it exists for session,
            otherwise returns None
        """
        calibration_trial = cls.objects.filter(
            session_id=session_id, name="calibration"
        ).order_by("created_at").last()
        if calibration_trial:
            return calibration_trial
        
        session = Session.objects.filter(id=session_id).first()
        if session and session.meta and "sessionWithCalibration" in session.meta:
            return cls.get_calibration_obj_or_none(
                session.meta["sessionWithCalibration"]["id"]
            )
        return None
    
    @classmethod
    def get_neutral_obj_or_none(cls, session_id):
        """ Returns trial with name `neutral` if it exists for session,
            otherwise returns None. 
        """
        neutral_trial = cls.objects.filter(
            session_id=session_id, name="neutral"
        ).order_by("created_at").last()
        if neutral_trial:
            return neutral_trial
        
        session = Session.objects.filter(id=session_id).first()
        if session and session.meta and "neutral_trial" in session.meta:
            return cls.objects.filter(
                id=session.meta["neutral_trial"]["id"]
            ).first()
        return None


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
    
    @classmethod
    def commit(cls, trial, device_id, tag, media_path, meta=None):
        """ Creates result record
        """
        with open(media_path, 'rb') as media:
            cls.objects.create(
                trial=trial,
                device_id=device_id,
                tag=tag,
                media=media,
                meta=meta
            )
    
    @classmethod
    def reset(cls, trial, tag=None, selected=[]):
        """ Deletes selected results, or all for trial with the tag
        """
        if selected:
            cls.objects.filter(id__in=selected).delete()
        elif tag:
            cls.objects.filter(trial=trial, tag=tag).delete()
        return


class DownloadLog(models.Model):
    """ This model is responsible for logging files downloading
        with Celery tasks
    """
    task_id = models.CharField(max_length=255)
    user = models.ForeignKey(
        to=User, on_delete=models.CASCADE, blank=True, null=True
    )
    media = models.FileField(upload_to=archives_dir_path, max_length=500)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.task_id


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

# @receiver(user_logged_in)
# def post_login(sender, user, request, **kwargs):
#     device = user.emaildevice_set.all()[0]
#
#     # The default EmailDevice didn't allow the use of html,
#     # so I have created a child class allowing it and here
#     # I am casting the device to that class.
#     device.__class__ = CustomEmailDevice
#
#     # Get template from path and set variables. The {{token}}
#     # is then substituted by the device by the real token.
#     settings.OTP_EMAIL_BODY_TEMPLATE = render_to_string(settings.OTP_EMAIL_BODY_TEMPLATE_PATH) % (settings.LOGO_LINK, "{{token}}")
#
#     # Set subject here, so everything is together.
#     settings.OTP_EMAIL_SUBJECT = "Opencap - Verification Code"
#
#     if not(user.otp_verified and user.otp_skip_till and user.otp_skip_till > timezone.now()):
#         device.generate_challenge()
#         print("CHALLENGE SENT")


class Subject(models.Model):
    GENDER_CHOICES = (
        ('woman', 'Woman'),
        ('man', 'Man'),
        ('transgender', 'Transgender'),
        ('non-binary', 'Non-Binary/Non-Conforming'),
        ('prefer-not-respond', 'Prefer Not to Respond'),
    )
    SEX_AT_BIRTH_CHOICES = (
        ('woman', 'Woman'),
        ('man', 'Man'),
        ('intersect', 'Intersect'),
        ('not-listed', 'Not Listed'),
        ('prefer-not-respond', 'Prefer Not to Respond'),
    )

    name = models.CharField(max_length=128)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    weight = models.FloatField('Weight (kg)', default=0.0, blank=True, null=True)
    height = models.FloatField('Height (m)', default=0.0, blank=True, null=True)
    age = models.IntegerField('Age (y)', default=0.0, blank=True, null=True)
    birth_year = models.PositiveIntegerField(
        'Birth year', blank=True, null=True, help_text="Use the following format: <YYYY>"
    )
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True, null=True)
    sex_at_birth = models.CharField(max_length=20, choices=SEX_AT_BIRTH_CHOICES, blank=True, null=True)
    characteristics = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    trashed = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['name', 'id']

    def __str__(self):
        return self.name

    def get_user(self):
        return self.user

    def get_meta_dict(self):
        return {
            'id': self.name,  # For backward compatibility
            'sex': self.get_sex_at_birth_display() or '',
            'mass': self.weight,
            'gender': self.get_gender_display() or '',
            'height': self.height,
        }

    def clean(self):
        super().clean()
        if self.birth_year is not None:
            if self.birth_year < 1900 or self.birth_year > timezone.now().year:
                raise ValidationError('Ensure this value is between 1900 and today\'s year.')

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.birth_year:
            self.birth_year = timezone.now().year - self.age
        return super().save(*args, **kwargs)
