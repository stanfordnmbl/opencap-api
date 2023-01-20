from django.http import HttpResponse
from django.http import Http404

from django.shortcuts import get_object_or_404, render
from mcserver.models import Session, User, Trial, Video, Result, ResetPassword
from mcserver.serializers import SessionSerializer, TrialSerializer, VideoSerializer, ResultSerializer, UserSerializer, ResetPasswordSerializer, NewPasswordSerializer
from django.core.files.base import ContentFile
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from rest_framework.decorators import action, permission_classes
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework import status
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny

import qrcode
import json
import time
import platform

from rest_framework import viewsets
from decouple import config

import os
import zipfile

from django.http import FileResponse

from django.db.models import Count

from mcserver.zipsession import downloadAndZipSession

from datetime import datetime, timedelta

import sys
sys.path.insert(0,'/code/mobilecap')

from rest_framework import exceptions
from rest_framework.permissions import IsAuthenticated, AllowAny, DjangoModelPermissions

from rest_framework import permissions

from django.contrib.auth import authenticate, login
import logging

class IsOwner(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.otp_verified
    
    def has_object_permission(self, request, view, obj):
        return obj.get_user() == request.user

class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.groups.filter(name='admin').exists()
        
    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

class IsBackend(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.groups.filter(name='backend').exists()
        
    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

class IsPublic(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.method == "GET"

    def has_object_permission(self, request, view, obj):
        return obj.is_public()

class AllowPublicCreate(permissions.BasePermission):
    def has_permission(self, request, view):
        # create new or update existing video 
        return (request.method == "POST") or (request.method == "PATCH")

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

def setup_eager_loading(get_queryset):
    def decorator(self):
        queryset = get_queryset(self)
        queryset = self.get_serializer_class().setup_eager_loading(queryset)
        return queryset

    return decorator


#from utils import switchCalibrationForCamera

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def zipdir(path, ziph):
    # ziph is zipfile handle
    for root, dirs, files in os.walk(path):
        for file in files:
            ziph.write(os.path.join(root, file), 
                       os.path.relpath(os.path.join(root, file), 
                                       os.path.join(path, '..')))

class SessionViewSet(viewsets.ModelViewSet):
#    queryset = Session.objects.all().order_by("-created_at")
    serializer_class = SessionSerializer
    permission_classes = [IsPublic | ((IsOwner | IsAdmin | IsBackend))]
    # permission_classes = [IsOwner]

    @setup_eager_loading
    def get_queryset(self):
        """
        This view should return a list of all the sessions
        for the currently authenticated user.
        """
        user = self.request.user
        if user.is_authenticated and user.id == 1:
            return Session.objects.all().order_by("-created_at")
        return Session.objects.all().order_by("-created_at").filter(Q(user__id=user.id) | Q(public=True))
       
    @action(detail=False)
    def api_health_check(self, request):
        
        return Response({"status": "True"})
    
    @action(
        detail=True,
        methods=["get","post"],
    )
    def calibration(self, request, pk):
        session_path = "/data/{}".format(pk)
        session = Session.objects.get(pk=pk)
        trial = session.trial_set.filter(name="calibration").order_by("-created_at")[0]

        trial.meta = {
            "calibration": {
                cam: val for cam, val in request.data.items()
            }
        }
        trial.save()

        return Response({
            "status": "ok",
            "data": request.data,
        })
    
    def retrieve(self, request, pk=None):
        session = get_object_or_404(Session.objects.all(), pk=pk)

        self.check_object_permissions(self.request, session)
        serializer = SessionSerializer(session)

        return Response(serializer.data)

    @action(
        detail=False,
        methods=["get","post"],
    )
    def valid(self, request):
        # Get quantity from post request. If it does exist, use it. If not, set -1 as default (e.g., return all)
        if 'quantity' not in request.data:
            quantity = -1
        else:
            quantity = request.data['quantity']
        print(request.data['quantity'])
        if(quantity == -1):
            # Note the use of `get_queryset()` instead of `self.queryset`
            sessions = self.get_queryset().order_by("-created_at").annotate(trial_count=Count('trial')).filter(trial_count__gte=3, user=request.user)
        else:
            # Note the use of `get_queryset()` instead of `self.queryset`
            sessions = self.get_queryset().order_by("-created_at").annotate(trial_count=Count('trial')).filter(trial_count__gte=3, user=request.user)[:request.data['quantity']]

        serializer = SessionSerializer(sessions, many=True)
        return Response(serializer.data)

    ## New session GET '/new/'
    # Creates a new session, returns session id and the QR code
    @action(detail=False)
    def new(self, request):
        session = Session()

        user = request.user

        if not user.is_authenticated:
            user = User.objects.get(id=1)
        session.user = user
        session.save()

        img = qrcode.make("{}/sessions/{}/status/".format(settings.HOST_URL, session.id))
        print(session.id)
        
        # Hack for local builds on windows
        if platform.system() == 'Windows':
            cDir = os.path.dirname(os.path.abspath(__file__))
            tmpDir = os.path.join(cDir, 'tmp')
            os.makedirs(tmpDir, exist_ok=True)
            path = os.path.join(tmpDir, "{}.png".format(session.id))
        else:
            path = "/tmp/{}.png".format(session.id)
        img.save(path, "png")

        with open(path, "rb") as fh:
            with ContentFile(fh.read()) as file_content:
                session.qrcode.save("{}.png".format(session.id), file_content)
                session.save()

        serializer = SessionSerializer(Session.objects.filter(id=session.id), many=True)
                
        return Response(serializer.data)
    
    ## New session GET '/new_subject/'
    # Creates a new sessionm leaving metadata on previous session. Used to avoid
    # re-connecting and re-calibrating cameras with every new subject.
    @action(detail=True)
    def new_subject(self, request, pk):
        sessionNew = Session()
        sessionOld = Session.objects.get(pk=pk)

        user = request.user

        if not user.is_authenticated:
            user = User.objects.get(id=1)
        sessionNew.user = user        
        
        # tell the new session where it can find a calibration trial
        if sessionOld.meta and 'sessionWithCalibration' in sessionOld.meta:
            sessionWithCalibration = str(sessionOld.meta['sessionWithCalibration']['id'])
        else:
            sessionWithCalibration = str(sessionOld.id)

        sessionNew.meta = {}
        sessionNew.meta["sessionWithCalibration"] = {
                "id": sessionWithCalibration
            }
        sessionNew.save()

        # tell the old session to go to the new session - phones will connect to this new session
        if not sessionOld.meta:
            sessionOld.meta = {}
        sessionOld.meta["startNewSession"] = {
                "id": str(sessionNew.id)
            }
        sessionOld.save()
        
        serializer = SessionSerializer(Session.objects.filter(id=sessionNew.id), many=True)
                
        return Response(serializer.data)


    def get_permissions(self):
        if self.action == 'status' or self.action == 'get_status':
            return [AllowAny(), ]
        return super(SessionViewSet, self).get_permissions()
    
    def get_status(self, request, pk):
        session = Session.objects.get(pk=pk)
        self.check_object_permissions(self.request, session)
        serializer = SessionSerializer(session)

        trials = session.trial_set.order_by("-created_at")
        trial = None

        status = "ready" # if no trials then "ready" (equivalent to trial_status = done)

        # If there is at least one trial, check it's status
        if trials.count():
            trial = trials[0]

        # if trial_status == 'done' then session ready again
        if trial and trial.status == "done":
            status = "ready"
        
        # if trial_status == 'recording' then just continue and return 'recording'
        # otherwise recording is done and check processing
        if trial and (trial.status in ["stopped","processing"]):
            # if not all videos uploaded then the status is 'uploading'
            # if results are not ready then processing
            # otherwise it's ready again
            if any([(not v.video) for v in trial.video_set.all()]):
                status = 'uploading'
            elif trial.result_set.count() == 0:
                status = 'processing'
            else:
                status = 'ready'

        # If status 'recording' and 'device_id' provided
        if trial and trial.status == "recording" and "device_id" in request.GET:
            if trial.video_set.filter(device_id=request.GET["device_id"]).count() == 0:
                video = Video()
                video.device_id = request.GET["device_id"]
                video.trial = trial
                video.save()
            status = "recording"

        video_url = None
        if trial and "device_id" in request.GET:
            videos = trial.video_set.filter(device_id=request.GET["device_id"])
            if videos.count() > 0:
                video_url = reverse('video-detail', kwargs={'pk': videos[0].id})
        trial_url = reverse('trial-detail', kwargs={'pk': trial.id}) if trial else None
        
        # tell phones to pair with a new session
        if session.meta and "startNewSession" in session.meta:
            newSessionURL = "{}/sessions/{}/status/".format(settings.HOST_URL, session.meta['startNewSession']['id'])
        else:
            newSessionURL = None

        res = {
            "status": status,
            "trial": trial_url,
            "video": video_url,
            "framerate": 60,
            "newSessionURL":newSessionURL,
        }

        if "ret_session" in request.GET:
            res["session"] = SessionSerializer(session, many=False).data
            
        return res

    ## Session status GET '<id>/status/'
    # if no active trial then return "ready"
    # if there is an active trial then return "recording"
    # if recording completed (trial set to "done") but some videos pending then "uploading"
    # if recording and upload, but not processed then "processing"
    # if "processing" returns errors or is done then go back to "ready"
    #
    # Logic on the client side:
    # - if status changed "*" -> "recording" start recording
    # - if status change "recording" -> "*" stop recording and submit the video
    #
    # For each device checking the status in the "recording" phase, create a video record
    @action(detail=True)
    def status(self, request, pk):
        status_dict = self.get_status(request, pk)
            
        return Response(status_dict)

    ## Start recording POST '<id>/record/'
    # Create a new trial
    # - creates a new trial with "recording" state
    @action(detail=True)
    def record(self, request, pk):
        session = Session.objects.get(pk=pk)

        name = request.GET.get("name",None)

        trial = Trial()
        trial.session = session

        name_count = Trial.objects.filter(name__startswith=name, session=session).count()
        if (name_count > 0) and (name not in ["calibration","neutral"]):
            name = "{}_{}".format(name, name_count)
        
        trial.name = name
        trial.save()

        if name == "calibration" or name == "neutral":
            time.sleep(2)
            return self.stop(request, pk)
        
        serializer = TrialSerializer(trial, many=False)
        
        return Response(serializer.data)

    @action(detail=True)
    def download(self, request, pk):
        # Extract protocol and host.
        if request.is_secure():
            host = "https://" + request.get_host()
        else:
            host = "http://" + request.get_host()

        session_zip = downloadAndZipSession(pk, host=host)

        return FileResponse(open(session_zip, "rb"))
    
    
    @action(detail=True)
    def get_session_permission(self, request, pk): 
        session = Session.objects.get(pk=pk)

        isSessionOwner = session.user == request.user
        isSessionPublic = session.public
        isUserAdmin = request.user.groups.filter(name='admin').exists()
        sessionPermission = {'isOwner':isSessionOwner,
                             'isPublic':isSessionPublic,
                             'isAdmin':isUserAdmin}
        
        return Response(sessionPermission)

    @action(detail=True)
    def set_metadata(self, request, pk):
        session = Session.objects.get(pk=pk)

        if not session.meta:
            session.meta = {}
        
        if "subject_id" in request.GET:
            session.meta["subject"] = {
                "id": request.GET.get("subject_id",""),
                "mass": request.GET.get("subject_mass",""),
                "height": request.GET.get("subject_height",""),
                "sex": request.GET.get("subject_sex",""),
                "gender": request.GET.get("subject_gender",""),
                "datasharing": request.GET.get("subject_data_sharing",""),
                "posemodel": request.GET.get("subject_pose_model",""),
            }
            
        if "cb_square" in request.GET:
            session.meta["checkerboard"] = {
                "square_size": request.GET.get("cb_square",""),
                "rows": request.GET.get("cb_rows",""),
                "cols": request.GET.get("cb_cols",""),
                "placement": request.GET.get("cb_placement",""),
            }
            
        session.save()
    
        serializer = SessionSerializer(session, many=False)
        
        return Response(serializer.data)
        
    ## Stop recording POST '<id>/stop/'
    # Changes the trial status from "recording" to "done"
    # Logic on the client side:
    # - session status changed so they start uploading videos
    @action(detail=True)
    def stop(self, request, pk):
        session = Session.objects.get(pk=pk)
        trials = session.trial_set.order_by("-created_at")

        # name = request.GET.get("name",None)

        # meta = {
        #     "subject": {
        #         "id": request.GET.get("subject_id",""),
        #         "mass": request.GET.get("subject_mass",""),
        #         "height": request.GET.get("subject_height",""),
        #         "gender": request.GET.get("subject_gender",""),
        #     },
        #     "checkerboard": {
        #         "square_size": request.GET.get("cb_square",""),
        #         "rows": request.GET.get("cb_rows",""),
        #         "cols": request.GET.get("cb_cols",""),
        #         "placement": request.GET.get("cb_placement",""),
        #     }
        # }
        # session.meta = meta
        # session.save()

        # If there is at least one trial, check it's status
        trial = trials[0]
        trial.status = "stopped"
        trial.save()

        serializer = TrialSerializer(trial, many=False)
        return Response(serializer.data)

    @action(detail=True)
    def calibration_img(self, request, pk):
        session = Session.objects.get(pk=pk)
        self.check_object_permissions(self.request, session)
        
        trials = session.trial_set.filter(name="calibration").order_by("-created_at")

        if len(trials) == 0:
            data = {
                "status": "error",
                "img": [
                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                ],
            }
        elif not trials[0].status in ['done', 'error']: # this gets updated on the backend by app.py
            data = {
                "status": "processing",
                "img": [
#                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                ],
            }
        else:
            imgs = []
            for result in trials[0].result_set.all():
                if result.tag == "calibration-img":
                    imgs.append(result.media.url)
           
            if len(imgs) > 0:
                data = {
                    "status": "done",
                    "img": list(sorted(imgs, key=lambda x: x.split("-")[-1])),
                }
            
            else: 
               data = {
                    "status": "error",
                    "img": [
                    ],
                }
        
        return Response(data)
    
    @action(detail=True)
    def neutral_img(self, request, pk):
        session = Session.objects.get(pk=pk)
        self.check_object_permissions(self.request, session)
        trials = session.trial_set.filter(name="neutral").order_by("-created_at")

        if len(trials) == 0:
            data = {
                "status": "error",
                "img": [
                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/neutral_pose.png",
                ],
            }
        elif not trials[0].status in ['done', 'error']: # this gets updated on the backend by app.py
            data = {
                "status": "processing",
                "img": [
#                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                ],
            }
        else:
            imgs = []
            for result in trials[0].result_set.all():
                if result.tag == "neutral-img":
                    imgs.append(result.media.url)

            if len(imgs) > 0:
                data = {
                    "status": "done",
                    "img": imgs
                }
            else: 
               data = {
                    "status": "error",
                    "img": [
                    ],
                }
                
        
        return Response(data)
    

## Processing machine:
# A worker asks whether there is any trial to process
# - if no it asks again in 5 sec
# - if yes it runs processing and sends back the results
class TrialViewSet(viewsets.ModelViewSet):
    queryset = Trial.objects.all().order_by("created_at")
    serializer_class = TrialSerializer

    permission_classes = [IsPublic | ((IsOwner | IsAdmin | IsBackend))]
    
    @action(detail=False)
    def dequeue(self, request):
        ip = get_client_ip(request)

        # find trials with some videos not uploaded
        not_uploaded = Video.objects.filter(video='',
                                            updated_at__gte=datetime.now().date() + timedelta(days=-1)).values_list("trial__id", flat=True)

        print(not_uploaded)

        uploaded_trials = Trial.objects.exclude(id__in=not_uploaded)
#        uploaded_trials = Trial.objects.all()

        # Priority for 'calibration' and 'neutral'
        trials = uploaded_trials.filter(status="stopped",
                                      name__in=["calibration","neutral"],
                                      result=None)
        
        if trials.count() == 0:
            trials = uploaded_trials.filter(status="stopped",
                                      result=None)

        if trials.count() == 0:
            raise Http404

        trial = trials[0]
        trial.status = "processing"
        trial.save()

        print(ip)
        print(trial.session.server)
        if (not trial.session.server) or len(trial.session.server) < 1:
            session = Session.objects.get(id=trial.session.id)
            session.server = ip
            session.save()
            
        serializer = TrialSerializer(trial, many=False)
        
        return Response(serializer.data)
    
## Upload a video:
# Input: video and phone_id
# Logic: Find the Video model within this session with
# device_id. Upload Video to that model
class VideoViewSet(viewsets.ModelViewSet):
    queryset = Video.objects.all().order_by("-created_at")
    serializer_class = VideoSerializer

    permission_classes = [AllowPublicCreate | ((IsOwner | IsAdmin | IsBackend))]
    
    # Default 'update' should be enough


class ResultViewSet(viewsets.ModelViewSet):
    queryset = Result.objects.all().order_by("-created_at")
    serializer_class = ResultSerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    permission_classes = [IsAdmin]
    
    
class UserCreate(APIView):
    """ 
    Creates the user. 
    """
    permission_classes = [AllowAny]

    def post(self, request, format='json'):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            if user:
                token = Token.objects.create(user=user)
                json = serializer.data
                json['token'] = token.key
                return Response(json, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CustomAuthToken(ObtainAuthToken):

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)

        print("LOGGED IN")
        user.otp_verified = False
        user.save()
        login(request, user)
        
        return Response({
            'token': token.key,
            'user_id': user.id,
        })

from django.core.mail import send_mail
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
import traceback

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, format='json'):
        error_message = "success"
        serializer = ResetPasswordSerializer(data=request.data,
                                        context={'request': request})
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        host = request.data['host']

        # Check if there is already an existing token
        # associated to this email and remove it.
        objects = ResetPassword.objects.filter(email=email)
        for object in objects:
            object.delete()

        # Generate a new token for this email.
        ResetPassword.objects.create(
            email=email
        )

        token = get_object_or_404(ResetPassword, email__exact=email).id
        username = get_object_or_404(User, email__exact=email).username

        reset_password_email_subject = 'Opencap - Forgot Username or Password'

        link = host + '/new-password/' + str(token)

        logo_link = settings.LOGO_LINK
        
        email_body_html = render_to_string('email/reset_password_email.html')
        email_body_html = email_body_html % (logo_link, username, link, link, str(token))
        
        email = EmailMessage(reset_password_email_subject, email_body_html, to=[email])
        email.content_subtype = "html"
        email.send()

        return Response({
            'message': error_message
        })


class NewPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format='json'):
        error_message = "Success"

        serializer = NewPasswordSerializer(data=request.data,
                                        context={'request': request})
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['password']
        token = serializer.validated_data['token']

        # Try to retrieve email using token. If 404, the email does not exist and this link is not valid.
        try:
            email = get_object_or_404(ResetPassword, id__exact=token).email
        except:
            error_message = 'The link to reset your password has expired or does not exist.'

            # Return error message.
            return Response({
                'message': error_message
            })

        user = get_object_or_404(User, email__exact=email)

        # Check if token expired. First get date of creation.
        date = get_object_or_404(ResetPassword, email__exact=email).datetime
        # Check if today has passed more than 3 days since creation of token.
        if timezone.now().date() >= date + timedelta(days=3):
            error_message = 'The link to reset your password has expired or does not exist. Try reset your password again.'

            # Remove the expired token.
            objects = ResetPassword.objects.filter(email=email)
            for object in objects:
                object.delete()

            # Return error message.
            return Response({
                'message': error_message
            })

        else:
            # If token exists, and it has not expired, set new password.
            user.set_password(new_password)
            user.save()
                
            # Remove the token.
            objects = ResetPassword.objects.filter(email=email)
            for object in objects:
                object.delete()

        # Return message. At this point no error have been thrown and this should return success.
        return Response({
            'message': error_message
        })




from functools import partial
from django_otp.forms import OTPTokenForm

from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from rest_framework.authentication import TokenAuthentication

from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer

from rest_framework import status

@api_view(('POST',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
@csrf_exempt
def verify(request):

    device = request.user.emaildevice_set.all()[0]
    data = json.loads(request.body.decode('utf-8'))
    verified = device.verify_token(data["otp_token"])
    print("VERIFICATION", verified)
    request.user.otp_verified = verified
    request.user.save()

    if not verified:
        return Response({
        }, status.HTTP_401_UNAUTHORIZED)

    return Response({})
