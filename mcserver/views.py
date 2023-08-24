from django.http import HttpResponse
from django.http import Http404

from django.shortcuts import get_object_or_404, render
from mcserver.models import (
    Session, User, Trial, Video, Result, ResetPassword, Subject, DownloadLog
)
from mcserver.serializers import (
    SessionSerializer, TrialSerializer,
    VideoSerializer, ResultSerializer,
    NewSubjectSerializer,
    SubjectSerializer,
    UserSerializer,
    ResetPasswordSerializer,
    NewPasswordSerializer)
from django.core.files.base import ContentFile
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from rest_framework.decorators import action, permission_classes
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework import status
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.generics import RetrieveAPIView

import qrcode
import json
import time
import platform

from rest_framework import viewsets
from decouple import config

import os
import zipfile
import pathlib

from django.http import FileResponse

from django.db.models import Count

from mcserver.zipsession import downloadAndZipSession, downloadAndZipSubject
from mcserver.tasks import download_session_archive, download_subject_archive

from datetime import datetime, timedelta

import sys
sys.path.insert(0,'/code/mobilecap')

from rest_framework import exceptions
from rest_framework.permissions import IsAuthenticated, AllowAny, DjangoModelPermissions

from rest_framework import permissions

from django.contrib.auth import authenticate, login
import logging

import boto3
import requests

import uuid

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
        return Session.objects.filter(Q(user__id=user.id) | Q(public=True)).order_by("-created_at")
       
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

    @action(detail=True)
    def get_n_calibrated_cameras(self, request, pk):
        error_message = ''
        session = get_object_or_404(Session, pk=pk)
        calibration_trials = session.trial_set.filter(name="calibration")
        last_calibration_trial_num_videos = 0

        # Check if there is a calibration trial. If not, it must be in a parent session.
        while not calibration_trials and session.meta['sessionWithCalibration']:
            id_session_with_calibration = session.meta['sessionWithCalibration']
            # If parent does not exist, capture the exception, and continue.
            try:
                session_with_calibration = Session.objects.filter(pk=id_session_with_calibration)
            except Exception:
                break
            # If parent exist, extract calibration trials.
            if session_with_calibration:
                try:
                    calibration_trials = session_with_calibration.trial_set.filter(name="calibration")
                except Exception:
                    break

        # If there are calibration trials, check if the number of cameras is the same as in the
        # current trial being stopped.
        if calibration_trials:
            last_calibration_trial = calibration_trials.order_by("-created_at")[0]

            last_calibration_trial_num_videos = Video.objects.filter(trial=last_calibration_trial).count()
        else:
            error_message = 'Sorry, there is no calibration trial for this session.' \
                                             'Maybe it was created from a session that was remove.'

        return Response({
            'error_message': error_message,
            'data': last_calibration_trial_num_videos
        })

    @action(detail=True, methods=['post'])
    def rename(self, request, pk):
        # Get session.
        session = get_object_or_404(Session.objects.all(), pk=pk)

        try:
            error_message = ""

            # Update session name and save.
            session.meta["sessionName"] = request.data['sessionNewName']
            session.save()

        except Exception as e:
            error_message = 'There was an error while renaming your session: ' + str(e)
            print(error_message)

        # Serialize session.
        serializer = SessionSerializer(session)

        # Return error message and data.
        return Response({
            'message': error_message,
            'data': serializer.data
        })

    def retrieve(self, request, pk=None):
        session = get_object_or_404(Session.objects.all(), pk=pk)

        self.check_object_permissions(self.request, session)
        serializer = SessionSerializer(session)

        return Response(serializer.data)

    @action(
        detail=False,
        methods=["get", "post"],
    )
    def valid(self, request):
        # Get quantity from post request. If it does exist, use it. If not, set -1 as default (e.g., return all)
        if 'quantity' not in request.data:
            quantity = -1
        else:
            quantity = request.data['quantity']

        # Note the use of `get_queryset()` instead of `self.queryset`
        sessions = self.get_queryset()\
            .annotate(trial_count=Count('trial'))\
            .filter(trial_count__gte=1, user=request.user)
        if 'subject_id' in request.data:
            subject = get_object_or_404(
                Subject,
                id=request.data['subject_id'], user=request.user)
            sessions = sessions.filter(subject=subject)

        # A session is valid only if at least one trial is the "neutral" trial and its status is "done".
        for session in sessions:
            trials = Trial.objects.filter(session__exact=session, name__exact="neutral").filter(status__exact="done")
            if trials.count() < 1:
                sessions = sessions.exclude(id__exact=session.id)

        # If quantity is not -1, retrieve only last n sessions.
        if quantity != -1:
            sessions = sessions[: request.data['quantity']]

        serializer = SessionSerializer(sessions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def permanent_remove(self, request, pk):
        session = Session.objects.get(pk=pk, user=request.user)
        session.delete()
        return Response({})

    @action(detail=True, methods=['post'])
    def trash(self, request, pk):
        from django.utils.timezone import now

        session = Session.objects.get(pk=pk, user=request.user)
        session.trashed = True
        session.trashed_at = now()
        session.save()

        serializer = SessionSerializer(session)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk):
        session = Session.objects.get(pk=pk, user=request.user)
        session.trashed = False
        session.trashed_at = None
        session.save()

        serializer = SessionSerializer(session)
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
    
    ## Get and send QR code
    @action(detail=True)
    def get_qr(self, request, pk):
        session = Session.objects.get(pk=pk)
       
        # # get the QR code from the database
        if session.qrcode:
            qr = session.qrcode
        elif session.meta and 'sessionWithCalibration' in session.meta:
            sessionWithCalibration = Session.objects.get(pk = str(session.meta['sessionWithCalibration']['id']))
            qr = sessionWithCalibration.qrcode

        s3_client = boto3.client(
            's3',
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                'Key': str(qr)
            },
            ExpiresIn=12000
        )
    
        res = {'qr': url}
        return Response(res)
       
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
        n_cameras_connected = None
        if trial and trial.status == "recording" and "device_id" in request.GET:
            n_cameras_connected = Video.objects.filter(trial=trial).count()
            if trial.video_set.filter(device_id=request.GET["device_id"]).count() == 0:
                video = Video()
                video.device_id = request.GET["device_id"]
                video.trial = trial
                video.save()
            status = "recording"

        # If status 'uploading' and 'device_id' provided
        n_videos_uploaded = 0
        for video in Video.objects.filter(trial=trial).all():
            if video.video.url:
                n_videos_uploaded = n_videos_uploaded + 1

        n_cameras_connected = None
        if trial and trial.status == "recording" and "device_id" in request.GET:
            n_cameras_connected = Video.objects.filter(trial=trial).count()
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
            
        if session.meta and "settings" in session.meta and "framerate" in session.meta['settings']:
            frameRate = int(session.meta['settings']['framerate'])
        else:
            frameRate = 60
        if trial and (trial.name in {'calibration','neutral'}):
            frameRate = 30


        res = {
            "status": status,
            "trial": trial_url,
            "video": video_url,
            "framerate": frameRate,
            "newSessionURL":newSessionURL,
            "n_cameras_connected": n_cameras_connected,
            "n_videos_uploaded": n_videos_uploaded
        }

        if "ret_session" in request.GET:
            res["session"] = SessionSerializer(session, many=False).data
            
        return res

     
    @action(detail=True)
    def get_presigned_url(self, request, pk):
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        
        if request.data and request.data.get('fileName'): 
            fileName = '-' + request.data.get('fileName') # for result uploading - matching old way
        else: # default: link for phones to upload videos
            fileName = '.mov'
        
        key = str(uuid.uuid4()) + fileName 
        
        response = s3_client.generate_presigned_post(
            Bucket = settings.AWS_STORAGE_BUCKET_NAME,
            Key = key,
            ExpiresIn = 1200 
        )

        return Response(response)
    
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
        def get_count_from_name(name, base_name):
            try:
                count = int(name[len(base_name) + 1:])
                return count
            except ValueError:
                return 0
        
        session = Session.objects.get(pk=pk)

        name = request.GET.get("name",None)

        trial = Trial()
        trial.session = session

        existing_names = Trial.objects.filter(name__startswith=name, session=session).values_list('name', flat=True)
        if (len(existing_names) > 0) and (name not in ["calibration","neutral"]) and (name in existing_names):
            highest_count = max([get_count_from_name(existing_name, name) for existing_name in existing_names])
            name = "{}_{}".format(name, highest_count + 1)
        
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
    
    @action(
        detail=True,
        url_path="async-download",
        url_name="async_session_download"
    )
    def async_download(self, request, pk):
        if request.user.is_authenticated:
            session = get_object_or_404(Session, pk=pk, user=request.user)
            task = download_session_archive.delay(session.id, request.user.id)
        else:
            session = get_object_or_404(Session, pk=pk, public=True)
            task = download_session_archive.delay(session.id)
        return Response({"task_id": task.id}, status=200)
    
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
    def get_session_settings(self, request, pk):
        session = Session.objects.get(pk=pk)
        
        # Check if using same setup
        if session.meta and 'sessionWithCalibration' in session.meta and 'id' in session.meta['sessionWithCalibration']:
            session = Session.objects.get(pk=session.meta['sessionWithCalibration']['id'])
        
        self.check_object_permissions(self.request, session)
        serializer = SessionSerializer(session)

        trials = session.trial_set.order_by("-created_at")
        trial = None

        # If there is at least one trial, check it's status
        if trials.count():
            trial = trials[0]
        
        if trial and trial.video_set.count() > 0:
            maxFramerates = []
            for video in trial.video_set.all():
                if 'max_framerate' in video.parameters:
                    maxFramerates.append(video.parameters['max_framerate'])
                else:
                    maxFramerates = [60]
                           
        framerateOptions = [60,120,240]
        frameratesAvailable = [f for f in framerateOptions if f<=min(maxFramerates)]
        
        settings_dict = {'framerates':frameratesAvailable}                          
            
        return Response(settings_dict)

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

        if "settings_framerate" in request.GET:
            session.meta["settings"] = {
                "framerate": request.GET.get("settings_framerate",""),
            }

        if "settings_data_sharing" in request.GET:
            if not session.meta["settings"]:
                session.meta["settings"] = {}
            session.meta["settings"]["datasharing"] = request.GET.get("settings_data_sharing","")

        if "settings_pose_model" in request.GET:
            if not session.meta["settings"]:
                session.meta["settings"] = {}
            session.meta["settings"]["posemodel"] = request.GET.get("settings_pose_model","")

        if "settings_openSimModel" in request.GET:
            if not session.meta["settings"]:
                session.meta["settings"] = {}
            session.meta["settings"]["openSimModel"] = request.GET.get("settings_openSimModel", "")

        if "settings_augmenter_model" in request.GET:
            if not session.meta["settings"]:
                session.meta["settings"] = {}
            session.meta["settings"]["augmentermodel"] = request.GET.get("settings_augmenter_model", "")
            
        if "cb_square" in request.GET:
            session.meta["checkerboard"] = {
                "square_size": request.GET.get("cb_square",""),
                "rows": request.GET.get("cb_rows",""),
                "cols": request.GET.get("cb_cols",""),
                "placement": request.GET.get("cb_placement",""),
            }

        if "settings_session_name" in request.GET:
            if "settings_session_name" not in session.meta:
                session.meta["sessionName"] = request.GET.get("settings_session_name", "")

        session.save()
    
        serializer = SessionSerializer(session, many=False)
        
        return Response(serializer.data)

    @action(detail=True)
    def set_subject(self, request, pk):
        session = Session.objects.get(pk=pk)
        subject_id = request.GET.get("subject_id", "")
        subject = get_object_or_404(Subject, id=subject_id, user=request.user)
        session.subject = subject
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

        # delete video instances if there are any redundant ones
        # which happens when theres wifi latency in phone connection
        videos = trial.video_set.all()
        unique_device_ids = set()
        videos_to_delete = []

        for video in videos:
            if video.device_id in unique_device_ids:
                videos_to_delete.append(video)
            else:
                unique_device_ids.add(video.device_id)

        for video in videos_to_delete:
            video.delete()

        trial.status = "stopped"
        trial.save()

        serializer = TrialSerializer(trial, many=False)
        return Response(serializer.data)
    
    ## Cancel trial POST '<id>/stop/'
    # Changes the trial status from "stopped" to "error"
    # Logic on the client side:
    # - session status changed when cancel is pressed
    @action(detail=True)
    def cancel_trial(self, request, pk):
        session = Session.objects.get(pk=pk)
        trials = session.trial_set.order_by("-created_at")

        # If there is at least one trial, check it's status
        if len(trials) >0:
            trial = trials[0]
            trial.status = "error"
            trial.save()
            data = {"status": "error"}
        else:
            data = {"status": "noTrials"}

        return Response(data)

    @action(detail=True)
    def calibration_img(self, request, pk):
        session = Session.objects.get(pk=pk)
        self.check_object_permissions(self.request, session)
        
        trials = session.trial_set.filter(name="calibration").order_by("-created_at")
        print(trials)
        status_session = self.get_status(request, pk)

        if len(trials) == 0:
            data = {
                "status": "error",
                "img": [
                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                ],
                "n_cameras_connected": status_session["n_cameras_connected"],
                "n_videos_uploaded": status_session["n_videos_uploaded"]
            }
        elif not trials[0].status in ['done', 'error']: # this gets updated on the backend by app.py
            data = {
                "status": "processing",
                "img": [
                    # "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                ],
                "n_cameras_connected": status_session["n_cameras_connected"],
                "n_videos_uploaded": status_session["n_videos_uploaded"]
            }
        else:
            imgs = []
            for result in trials[0].result_set.all():
                if result.tag == "calibration-img":
                    imgs.append(result.media.url)
            print(imgs)
            if len(imgs) > 0:
                data = {
                    "status": "done",
                    "img": list(sorted(imgs, key=lambda x: x.split("-")[-1])),
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
                }
            
            else: 
                data = {
                    "status": "error",
                    "img": [
                    ],
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
                }
        
        return Response(data)
    
    @action(detail=True)
    def neutral_img(self, request, pk):
        session = Session.objects.get(pk=pk)
        self.check_object_permissions(self.request, session)
        trials = session.trial_set.filter(name="neutral").order_by("-created_at")

        status_session = self.get_status(request, pk)

        if len(trials) == 0:
            data = {
                "status": "error",
                "img": [
                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/neutral_pose.png",
                ],
                "n_cameras_connected": status_session["n_cameras_connected"],
                "n_videos_uploaded": status_session["n_videos_uploaded"]
            }
        elif not trials[0].status in ['done', 'error']: # this gets updated on the backend by app.py
            data = {
                "status": "processing",
                "img": [
#                    "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                ],
                "n_cameras_connected": status_session["n_cameras_connected"],
                "n_videos_uploaded": status_session["n_videos_uploaded"]
            }
        else:
            imgs = []
            for result in trials[0].result_set.all():
                if result.tag == "neutral-img":
                    imgs.append(result.media.url)

            if len(imgs) > 0:
                data = {
                    "status": "done",
                    "img": imgs,
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
                }
            else: 
               data = {
                    "status": "error",
                    "img": [
                    ],
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
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

    
    @action(detail=False, permission_classes=[((IsAdmin | IsBackend))])
    def dequeue(self, request):

        ip = get_client_ip(request)

        workerType = self.request.query_params.get('workerType')

        # find trials with some videos not uploaded
        not_uploaded = Video.objects.filter(video='',
                                            updated_at__gte=datetime.now() + timedelta(minutes=-15)).values_list("trial__id", flat=True)

        print(not_uploaded)

        uploaded_trials = Trial.objects.exclude(id__in=not_uploaded)
#        uploaded_trials = Trial.objects.all()

        if workerType != 'dynamic':
            # Priority for 'calibration' and 'neutral'
            trials = uploaded_trials.filter(status="stopped",
                                      name__in=["calibration","neutral"],
                                      result=None)
            
            trialsReprocess = uploaded_trials.filter(status="reprocess",
                                      name__in=["calibration","neutral"],
                                      result=None)
            
            if trials.count() == 0 and workerType != 'calibration':
                trials = uploaded_trials.filter(status="stopped",
                                          result=None)
                
            if trials.count()==0 and trialsReprocess.count() == 0 and workerType != 'calibration':
                trialsReprocess = uploaded_trials.filter(status="reprocess",
                                          result=None)
            
        else:
            trials = uploaded_trials.filter(status="stopped",
                                            result=None).exclude(name__in=["calibration", "neutral"])
            
            trialsReprocess = uploaded_trials.filter(status="reprocess",
                                            result=None).exclude(name__in=["calibration", "neutral"])
            
        
        if trials.count() == 0 and trialsReprocess.count() == 0:
            raise Http404
        
        # prioritize admin and priority group trials (priority group doesn't exist yet, but should have same priv. as user)
        trialsPrioritized = trials.filter(session__user__groups__name__in=["admin","priority"])
        # if not priority trials, go to normal trials
        if trialsPrioritized.count() == 0:
            trialsPrioritized = trials
        # if no normal trials, go to reprocess trials
        if trials.count() == 0:
            trialsPrioritized = trialsReprocess

        trial = trialsPrioritized[0]
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
    
    @action(detail=False, permission_classes=[((IsAdmin | IsBackend))])
    def get_trials_with_status(self, request):
        """
        This view returns a list of all the trials with the specified status
        that was updated more than hoursSinceUpdate hours ago.
        """
        hours_since_update = request.query_params.get('hoursSinceUpdate', 0)
        hours_since_update = float(hours_since_update) if hours_since_update else 0 

        status = self.request.query_params.get('status')
        # trials with given status and updated_at more than n hours ago
        trials = Trial.objects.filter(status=status,
                                     updated_at__lte=(datetime.now() - timedelta(hours=hours_since_update))).order_by("-created_at")
        
        serializer = TrialSerializer(trials, many=True)

        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def rename(self, request, pk):
        # Get trial.
        trial = Trial.objects.get(pk=pk, session__user=request.user)

        try:
            error_message = ""

            # Update trial name and save.
            trial.name = request.data['trialNewName']
            trial.save()

        except Exception as e:
            error_message = 'There was an error while renaming your trial: ' + str(e)
            print(error_message)

        # Serialize trial.
        serializer = TrialSerializer(trial)

        # Return error message and data.
        return Response({
            'message': error_message,
            'data': serializer.data
        })

    @action(detail=True, methods=['post'])
    def permanent_remove(self, request, pk):
        trial = get_object_or_404(Trial, pk=pk, session__user=request.user)
        trial.delete()
        return Response({})

    @action(detail=True, methods=['post'])
    def trash(self, request, pk):
        from django.utils.timezone import now

        trial = get_object_or_404(Trial, pk=pk, session__user=request.user)
        trial.trashed = True
        trial.trashed_at = now()
        trial.save()

        serializer = TrialSerializer(trial)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk):
        trial = get_object_or_404(Trial, pk=pk, session__user=request.user)
        trial.trashed = False
        trial.trashed_at = None
        trial.save()

        serializer = TrialSerializer(trial)
        return Response(serializer.data)




## Upload a video:
# Input: video and phone_id
# Logic: Find the Video model within this session with
# device_id. Upload Video to that model
class VideoViewSet(viewsets.ModelViewSet):
    queryset = Video.objects.all().order_by("-created_at")
    serializer_class = VideoSerializer

    permission_classes = [AllowPublicCreate | ((IsOwner | IsAdmin | IsBackend))]
    
    def perform_update(self, serializer):
        if ("video_url" in serializer.validated_data) and (serializer.validated_data["video_url"]):
            serializer.validated_data["video"] = serializer.validated_data["video_url"]
            del serializer.validated_data["video_url"]

        super().perform_update(serializer)

class ResultViewSet(viewsets.ModelViewSet):
    queryset = Result.objects.all().order_by("-created_at")
    serializer_class = ResultSerializer

    permission_classes = [IsOwner | IsAdmin | IsBackend]

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if request.data.get('media_url'):
            serializer.validated_data["media"] = serializer.validated_data["media_url"]
            del serializer.validated_data["media_url"]
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class SubjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwner | IsAdmin | IsBackend]

    def get_queryset(self):
        """
        This view should return a list of all the subjects
        for the currently authenticated user.
        """
        user = self.request.user
        if user.is_authenticated and user.id == 1:
            return Subject.objects.all()
        return Subject.objects.filter(user=user)

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return NewSubjectSerializer
        return SubjectSerializer

    @action(detail=False)
    def api_health_check(self, request):
        return Response({"status": "True"})

    @action(detail=True, methods=['post'])
    def trash(self, request, pk):
        from django.utils.timezone import now

        subject = get_object_or_404(Subject, pk=pk, user=request.user)
        subject.trashed = True
        subject.trashed_at = now()
        subject.save()

        serializer = SubjectSerializer(subject)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk):
        subject = get_object_or_404(Subject, pk=pk, user=request.user)
        subject.trashed = False
        subject.trashed_at = None
        subject.save()

        serializer = SubjectSerializer(subject)
        return Response(serializer.data)

    @action(detail=True)
    def download(self, request, pk):
        subject = get_object_or_404(Subject, pk=pk, user=request.user)
        # Extract protocol and host.
        if request.is_secure():
            host = "https://" + request.get_host()
        else:
            host = "http://" + request.get_host()

        subject_zip = downloadAndZipSubject(pk, host=host)

        return FileResponse(open(subject_zip, "rb"))
    
    @action(
        detail=True,
        url_path="async-download",
        url_name="async_subject_download"
    )
    def async_download(self, request, pk):
        subject = get_object_or_404(Subject, pk=pk, user=request.user)
        task = download_subject_archive.delay(subject.id, request.user.id)
        return Response({"task_id": task.id}, status=200)

    @action(detail=True, methods=['post'])
    def permanent_remove(self, request, pk):
        subject = get_object_or_404(Subject, pk=pk, user=request.user)
        subject.delete()
        return Response({})

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class DownloadFileOnReadyAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        log = DownloadLog.objects.filter(task_id=self.kwargs["task_id"]).first()
        if log and log.media:
            return Response({"url": log.media.url})
        return Response(status=202)


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
        from mcserver.utils import send_otp_challenge
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)

        print("LOGGED IN")

        # Skip OTP verification if specified
        otp_challenge_sent = False

        if not(user.otp_verified and user.otp_skip_till and user.otp_skip_till > timezone.now()):
            user.otp_verified = False
        user.save()
        login(request, user)
        if not (user.otp_verified and user.otp_skip_till and user.otp_skip_till > timezone.now()):
            send_otp_challenge(user)
            otp_challenge_sent = True
        
        return Response({
            'token': token.key,
            'user_id': user.id,
            'otp_challenge_sent': otp_challenge_sent,
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
    if 'remember_device' in data and data['remember_device']:
        request.user.otp_skip_till = timezone.now() + timedelta(days=90)
    request.user.save()

    if not verified:
        return Response({
        }, status.HTTP_401_UNAUTHORIZED)

    return Response({})


@api_view(('POST',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
@csrf_exempt
def reset_otp_challenge(request):
    from mcserver.utils import send_otp_challenge

    send_otp_challenge(request.user)

    request.user.otp_verified = False
    request.user.otp_skip_till = None
    request.user.save()
    return Response({'otp_challenge_sent': True})


@api_view(('GET',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
@csrf_exempt
def check_otp_verified(request):
    return Response({'otp_verified': request.user.otp_verified})
