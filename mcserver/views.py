import json
import os
import platform
import socket
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta

import boto3
import qrcode
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import AnonymousUser
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db.models import Count
from django.db.models import Q
from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.timezone import now
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from drf_yasg import openapi
from rest_framework import permissions
from rest_framework import status
from rest_framework import viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.exceptions import ValidationError, NotAuthenticated, NotFound, PermissionDenied, APIException
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from drf_yasg.utils import swagger_auto_schema

from mcserver.models import (
    Session,
    User,
    Trial,
    Video,
    Result,
    ResetPassword,
    Subject,
    SubjectTags,
    TrialTags,
    DownloadLog,
    AnalysisFunction,
    AnalysisResult,
    AnalysisResultState,
    AnalysisDashboard,
)
from mcserver.serializers import (
    SessionSerializer,
    TrialSerializer,
    VideoSerializer,
    ResultSerializer,
    NewSubjectSerializer,
    SubjectSerializer,
    SimpleSubjectSerializer,
    UserSerializer,
    UserUpdateSerializer,
    ResetPasswordSerializer,
    NewPasswordSerializer,
    AnalysisFunctionSerializer,
    AnalysisResultSerializer,
    AnalysisDashboardSerializer,
    ProfilePictureSerializer,
    UserInstitutionalUseSerializer,
    TagSerializer,
    ValidSessionLightSerializer,
    SubjectTagSerializer,
    TrialTagSerializer
)
from mcserver.tasks import (
    download_session_archive,
    download_subject_archive,
    invoke_aws_lambda_function
)
from mcserver.utils import send_otp_challenge
from mcserver.zipsession import downloadAndZipSession, downloadAndZipSubject

sys.path.insert(0, '/code/mobilecap')


class IsOwner(permissions.BasePermission):
    """
    Allow owners of an object to perform operations.

    A user is 'owner' if it is authenticated and the user associated to the object.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.otp_verified

    def has_object_permission(self, request, view, obj):
        return obj.get_user() == request.user


class IsAdmin(permissions.BasePermission):
    """
    Allow admins to perform operations.

    A user is admin if it belongs to the 'admin' group.
    """
    def has_permission(self, request, view):
        return request.user.groups.filter(name='admin').exists()

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsBackend(permissions.BasePermission):
    """
    Allow backend to perform operations.

    A user is backend if it belongs to the 'backend' group.
    """
    def has_permission(self, request, view):
        return request.user.groups.filter(name='backend').exists()

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsPublic(permissions.BasePermission):
    """
    Allows public users to perform operations.

    A method is public if it is a GET operation and the object retrieved is marked as 'public'.
    """
    def has_permission(self, request, view):
        return request.method == "GET"

    def has_object_permission(self, request, view, obj):
        return obj.is_public()


class AllowPublicCreate(permissions.BasePermission):
    """
    Allows public users to create new resources or update existing ones.

    Permission is granted for POST (create) and PATCH (update) methods.
    """
    def has_permission(self, request, view):
        # create new or update existing video 
        return (request.method == "POST") or (request.method == "PATCH")

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


def setup_eager_loading(get_queryset):
    """
    Decorator function to enable eager loading for a queryset.

    This decorator modifies the `get_queryset` method of a view to
    include related objects in a single query, optimizing database access.
     """
    def decorator(self):
        queryset = get_queryset(self)
        queryset = self.get_serializer_class().setup_eager_loading(queryset)
        return queryset

    return decorator


def get_client_ip(request):
    """
    Retrieves the client's IP address from the given request.

    This function checks the `HTTP_X_FORWARDED_FOR` header first (which may be
    set by proxies), and if not present, falls back to the `REMOTE_ADDR` header.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_client_hostname(request):
    """
    Retrieves the hostname corresponding to the client's IP address.

    Uses the IP address from `get_client_ip()` and performs a reverse DNS lookup
    to get the hostname. If the lookup fails, it returns `None`.
    """
    ip = get_client_ip(request)
    try:
        hostname = socket.gethostbyaddr(ip)
        return hostname[0]
    except socket.herror:
        return None


def zipdir(path, ziph):
    """
    Compresses a directory into a zip archive.

    Traverses the directory tree starting at the specified path and adds all files
    to the provided zip file handle. Preserves the directory structure in the archive.
    """
    # ziph is zipfile handle
    for root, dirs, files in os.walk(path):
        for file in files:
            ziph.write(os.path.join(root, file),
                       os.path.relpath(os.path.join(root, file),
                                       os.path.join(path, '..')))


class SessionViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing session objects.

    """
    serializer_class = SessionSerializer
    permission_classes = [IsPublic | (IsOwner | IsAdmin | IsBackend)]

    @setup_eager_loading
    def get_queryset(self):
        """
        Retrieves the queryset of sessions available to the current user.
        """
        user = self.request.user
        if user.is_authenticated and user.id == 1:
            return Session.objects.all().order_by("-created_at")
        return Session.objects.filter(Q(user__id=user.id) | Q(public=True)).order_by("-created_at")

    @swagger_auto_schema(
        operation_summary="API Health Check",
        responses={
            200: openapi.Response("Success - API health retrieved successfully."),
        }
    )
    @action(detail=False)
    def api_health_check(self, request):
        """
        Check the health of the API.
        """
        return Response({"status": "True"})

    @swagger_auto_schema(
        method="post",
        operation_summary="Update Calibration Data",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'calibration': openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    description="A dictionary containing calibration data for the session.",
                    additionalProperties=openapi.Schema(type=openapi.TYPE_STRING)
                ),
            },
            required=['calibration'],
            description="Calibration data to be updated."
        ),
        responses={
            200: openapi.Response("Success - Calibration data updated successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
        },
    )
    @action(detail=True, methods=["get", "post"], )
    def calibration(self, request, pk):
        """
        Update calibration data for a specific session.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = Session.objects.get(pk=pk)
            trial = session.trial_set.filter(name="calibration").order_by("-created_at")[0]

            trial.meta = {
                "calibration": {
                    cam: val for cam, val in request.data.items()
                }
            }
            trial.save()
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("calibration_error"))

        return Response({
            "status": "ok",
            "data": request.data,
        })

    @swagger_auto_schema(
        operation_summary="Get Number of Calibrated Cameras",
        responses={
            200: openapi.Response("Success - Number of calibrated cameras retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid Session data."),
            404: openapi.Response("Not Found - Session not found."),
        }
    )
    @action(detail=True)
    def get_n_calibrated_cameras(self, request, pk):
        """
        Retrieve the number of calibrated cameras for a specific session.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            error_message = ''
            session = get_object_or_404(Session, pk=pk)
            calibration_trials = session.trial_set.filter(name="calibration")
            last_calibration_trial_num_videos = 0

            # Check if there is a calibration trial. If not, it must be in a parent session.
            loop_counter = 0
            while not calibration_trials and session.meta.get('sessionWithCalibration') and loop_counter < 100:
                id_session_with_calibration = session.meta['sessionWithCalibration']
                # If parent does not exist, capture the exception, and continue.
                try:
                    session_with_calibration = Session.objects.filter(pk=id_session_with_calibration['id'])
                except Exception:
                    break
                # If parent exist, extract calibration trials.
                if session_with_calibration:
                    try:
                        calibration_trials = session_with_calibration[0].trial_set.filter(name="calibration")
                    except Exception:
                        break
                loop_counter += 1

            # If there are calibration trials, check if the number of cameras is the same as in the
            # current trial being stopped.
            if calibration_trials:
                last_calibration_trial = calibration_trials.order_by("-created_at")[0]

                last_calibration_trial_num_videos = Video.objects.filter(trial=last_calibration_trial).count()
            else:
                error_message = 'Sorry, there is no calibration trial for this session.' \
                                'Maybe it was created from a session that was remove.'

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("calibration_error"))

        return Response({
            'error_message': error_message,
            'data': last_calibration_trial_num_videos
        })

    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['sessionNewName'],
            properties={
                'sessionNewName': openapi.Schema(type=openapi.TYPE_STRING, description="New name for the session"),
            },
            description="Object containing the new session name."
        ),
        responses={
            200: openapi.Response("Success - Session renamed successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
        },
    )
    @action(detail=True, methods=['post'])
    def rename(self, request, pk):
        """
        Rename a specific session.
        """
        # Get session.
        session = get_object_or_404(Session.objects.all(), pk=pk)

        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))
            error_message = ""

            # Update session name and save.
            session.meta["sessionName"] = request.data['sessionNewName']
            self.check_object_permissions(self.request, session)
            session.save()

            serializer = SessionSerializer(session)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except NotAuthenticated:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('login_needed'))
        except PermissionDenied:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('permission_denied'))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_retrieve_error"))

        # Return error message and data.
        return Response({
            'message': error_message,
            'data': serializer.data
        })

    @swagger_auto_schema(
        operation_summary="Retrieve a session",
        responses={
            200: openapi.Response("Success - Session retrieved successfully."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Session not found."),
        },
    )
    def retrieve(self, request, pk=None):
        """
        Retrieve a specific session.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session.objects.all(), pk=pk)

            self.check_object_permissions(self.request, session)
            serializer = SessionSerializer(session)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except NotAuthenticated:
            # if settings.DEBUG:
            #     raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            return Response(_('login_needed'), status=status.HTTP_401_UNAUTHORIZED)
            # raise NotFound(_('login_needed'))
        except PermissionDenied:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('permission_denied'))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_retrieve_error"))

        return Response(serializer.data)

    @swagger_auto_schema(
        method="get",
        operation_summary="Retrieve valid sessions.",
        manual_parameters=[
            openapi.Parameter('quantity', openapi.IN_QUERY,
                              description="Number of sessions to retrieve.",
                              type=openapi.TYPE_INTEGER),
            openapi.Parameter('start', openapi.IN_QUERY,
                              description="Starting index for session retrieval.",
                              type=openapi.TYPE_INTEGER),
            openapi.Parameter('subject_id', openapi.IN_QUERY, description="Filter sessions by subject ID.", type=openapi.TYPE_INTEGER),
            openapi.Parameter('sort', openapi.IN_QUERY, description="Sort options for the sessions.", type=openapi.TYPE_ARRAY, items=openapi.Items(type=openapi.TYPE_STRING)),
            openapi.Parameter('sort_desc', openapi.IN_QUERY, description="Sort descending flags for each sort field.", type=openapi.TYPE_ARRAY, items=openapi.Items(type=openapi.TYPE_BOOLEAN)),
            openapi.Parameter('include_trashed', openapi.IN_QUERY, description="Include trashed sessions in the results.", type=openapi.TYPE_BOOLEAN),
            openapi.Parameter('only_trashed', openapi.IN_QUERY, description="Retrieve only trashed sessions.", type=openapi.TYPE_BOOLEAN),
        ],
        responses={
            200: openapi.Response("Success - Session retrieved and validated successfully.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'sessions': openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(type=openapi.TYPE_OBJECT)
                        ),
                        'total': openapi.Schema(type=openapi.TYPE_INTEGER, description="Total count of valid sessions.")
                    },
                )
            ),
            400: openapi.Response("Bad Request - Invalid subject data."),
            404: openapi.Response("Not Found - Session not found."),
        }
    )
    @swagger_auto_schema(
        method="post",
        operation_summary="Validate and retrieve user sessions.",
        responses={
            200: openapi.Response("Success - Session retrieved and validated successfully.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'sessions': openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(type=openapi.TYPE_OBJECT)
                        ),
                        'total': openapi.Schema(type=openapi.TYPE_INTEGER, description="Total count of valid sessions.")
                    },
                )),
            400: openapi.Response("Bad Request - Invalid subject data."),
            404: openapi.Response("Not Found - Session not found."),
        },
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["quantity"],
            properties={
                'quantity': openapi.Schema(type=openapi.TYPE_INTEGER,
                                           description="Number of sessions to retrieve. Set to -1 to retrieve all."),
                'start': openapi.Schema(type=openapi.TYPE_INTEGER, description="Starting index for session retrieval."),
                'subject_id': openapi.Schema(type=openapi.TYPE_INTEGER, description="Filter sessions by subject ID."),
                'sort': openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_STRING),
                                       description="Sort options for the sessions."),
                'sort_desc': openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                            description="Sort descending flags for each sort field."),
                'include_trashed': openapi.Schema(type=openapi.TYPE_BOOLEAN,
                                                  description="Include trashed sessions in the results."),
                'only_trashed': openapi.Schema(type=openapi.TYPE_BOOLEAN,
                                               description="Retrieve only trashed sessions."),
            }
        ),
    )
    @action(detail=False, methods=["get", "post"], )
    def valid(self, request):
        """
        Validate and retrieve user sessions based on various filters and sorting options.
        """
        try:
            # print(request.data)
            include_trashed = request.data.get('include_trashed', False) is True
            only_trashed = request.data.get('only_trashed', False) is True
            sort_by = request.data.get('sort', [])
            sort_desc = request.data.get('sort_desc', [])
            # Get quantity from post request. If it does exist, use it. If not, set -1 as default (e.g., return all)
            if 'quantity' not in request.data:
                quantity = -1
            else:
                quantity = request.data['quantity']
            start = 0 if 'start' not in request.data else request.data['start']
            # Note the use of `get_queryset()` instead of `self.queryset` (Confusing)
            sessions = self.get_queryset() \
                .annotate(trial_count=Count('trial')) \
                .filter(trial_count__gte=1, user=request.user)

            if only_trashed:
                sessions = sessions.filter(Q(trashed=True) | Q(trial__trashed=True))
            elif not include_trashed:
                sessions = sessions.exclude(trashed=True)

            if 'subject_id' in request.data:
                subject = get_object_or_404(
                    Subject,
                    id=request.data['subject_id'], user=request.user)
                sessions = sessions.filter(subject=subject)

            # A session is valid only if at least one trial is the "neutral" trial and its status is "done".
            for session in sessions:
                trials = Trial.objects.filter(session__exact=session, name__exact="neutral")
                if trials.count() < 1:
                    sessions = sessions.exclude(id__exact=session.id)

            # Sort by
            if sort_by:
                sessions = sessions.annotate(
                    trials_count=Count(
                        'trial',
                        filter=~Q(trial__name='calibration') & ~(Q(trial__name='neutral') & ~Q(trial__status='done')),
                    ))
                sort_options = {
                    'name': 'subject__name',
                    'trials_count': 'trials_count',
                    'created_at': 'created_at',
                    'sessionName': 'meta__sessionName',
                }

                sessions = sessions.order_by(
                    *[('-' if sort_desc[i] else '') + sort_options[x] for i, x in enumerate(sort_by) if
                      x in sort_options], '-id')

            sessions_count = sessions.count()
            # If quantity is not -1, retrieve only last n sessions.
            if quantity != -1 and start > 0:
                sessions = sessions[start: start + quantity]
            elif quantity != -1:
                sessions = sessions[:quantity]

            # serializer = SessionSerializer(sessions, many=True)
            serializer = ValidSessionLightSerializer(sessions, many=True)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("subject_uuid_not_found"))
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_not_valid"))

        if quantity != -1:
            return Response({'sessions': serializer.data, 'total': sessions_count})
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Permanently remove a session",
        responses={
            204: openapi.Response("Deleted - Session deleted successfully."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not remove the session."),
        },
    )
    @action(detail=True, methods=['post'])
    def permanent_remove(self, request, pk):
        """
        Permanently remove a specific session by its ID (UUID).
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk, user=request.user)
            self.check_object_permissions(self.request, session)
            # Delete all non-calibration trials. We keep the session itself to avoid breaking the chain of sessions.
            Trial.objects.filter(session=session).exclude(name="calibration").delete()
            # session.delete()
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except NotAuthenticated:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('login_needed'))
        except PermissionDenied:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('permission_denied'))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_permanent_remove_error"))

        return Response({})

    @swagger_auto_schema(
        operation_summary="Move a session to the trash",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "pk": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="UUID of the session to be moved to the trash.",
                ),
            },
            required=["pk"],
            description="JSON payload with the UUID of the session.",
        ),
        responses={
            200: openapi.Response("Success - Session trashed successfully."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not trash the session."),
        },
    )
    @action(detail=True, methods=['post'])
    def trash(self, request, pk):
        """
        Move a specific session to the trash by marking it as 'trashed'.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk, user=request.user)
            session.trashed = True
            session.trashed_at = now()
            session.save()

            serializer = SessionSerializer(session)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_remove_error"))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Restore a trashed session",
        responses={
            200: openapi.Response("Success - Session restored successfully."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not restore the session."),
        },
    )
    @action(detail=True, methods=['post'])
    def restore(self, request, pk):
        """
        Restore a specific session from the trash.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk, user=request.user)
            session.trashed = False
            session.trashed_at = None
            session.save()

            serializer = SessionSerializer(session)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_restore_error"))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Create a new session and generate a QR code for it.",
        responses={
            200: openapi.Response("Success - Session and QR created successfully."),
            400: openapi.Response("Bad Request - Invalid request data."),
            500: openapi.Response("Internal Server Error - Could not restore the session."),
        }
    )
    @action(detail=False)
    def new(self, request):
        """
        Create a new session and generate a QR code for it.
        """
        try:
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

        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_create_error"))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Retrieve QR code for a session.",
        responses={
            200: openapi.Response("Success - Session QR retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve the QR."),
        }
    )
    @action(detail=True)
    def get_qr(self, request, pk):
        """
        Retrieve the QR code for the session.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk, user=request.user)

            # get the QR code from the database
            if session.qrcode:
                qr = session.qrcode
            elif session.meta and 'sessionWithCalibration' in session.meta:
                sessionWithCalibration = Session.objects.get(pk=str(session.meta['sessionWithCalibration']['id']))
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

        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("qr_retrieve_error"))

        return Response(res)

    @swagger_auto_schema(
        operation_summary="Create a new session for a new subject.",
        responses={
            200: openapi.Response("Success - Session created successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not create the session."),
        }
    )
    @action(detail=True)
    def new_subject(self, request, pk):
        """
        Create a new session for a new subject.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            sessionNew = Session()
            sessionOld = get_object_or_404(Session, pk=pk, user=request.user)

            user = request.user

            if not user.is_authenticated:
                user = User.objects.get(id=1)
            sessionNew.user = user

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})

        try:
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

        except NotFound:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("user_not_found"))
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_create_error"))

        return Response(serializer.data)

    def get_permissions(self):
        if self.action == 'status' or self.action == 'get_status':
            return [AllowAny(), ]
        return super(SessionViewSet, self).get_permissions()

    @swagger_auto_schema(
        operation_summary="Get the status of the session.",
        responses={
            200: openapi.Response("Success - Session status retrieved successfully."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve the session status."),
        },
    )
    def get_status(self, request, pk):
        if pk == 'undefined':
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})

        session = get_object_or_404(Session, pk=pk)
        self.check_object_permissions(self.request, session)
        serializer = SessionSerializer(session)

        trials = session.trial_set.order_by("-created_at")
        trial = None

        status = "ready"  # if no trials then "ready" (equivalent to trial_status = done)

        # If there is at least one trial, check it's status
        if trials.count():
            trial = trials[0]

        # if trial_status == 'done' then session ready again
        if trial and trial.status == "done":
            status = "ready"

        # if trial_status == 'recording' then just continue and return 'recording'
        # otherwise recording is done and check processing
        if trial and (trial.status in ["stopped", "processing"]):
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

        # If status 'uploading' and 'device_id' provided
        n_videos_uploaded = 0
        n_cameras_connected = Video.objects.filter(trial=trial).count()
        for video in Video.objects.filter(trial=trial).all():
            if video.video and video.video.url:
                n_videos_uploaded = n_videos_uploaded + 1

        video_url = None
        if trial and trial.status == "recording" and "device_id" in request.GET:
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
        if trial and (trial.name in {'calibration', 'neutral'}):
            frameRate = 30

        res = {
            "status": status,
            "trial": trial_url,
            "video": video_url,
            "framerate": frameRate,
            "newSessionURL": newSessionURL,
            "n_cameras_connected": n_cameras_connected,
            "n_videos_uploaded": n_videos_uploaded
        }

        if "ret_session" in request.GET:
            res["session"] = SessionSerializer(session, many=False).data

        return res

    @action(detail=True)
    def get_presigned_url(self, request, pk):
        """
        Generates a presigned URL for uploading a file to S3.
        """
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

        if request.data and request.data.get('fileName'):
            fileName = '-' + request.data.get('fileName')  # for result uploading - matching old way
        else:  # default: link for phones to upload videos
            fileName = '.mov'

        key = str(uuid.uuid4()) + fileName

        response = s3_client.generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key,
            ExpiresIn=1200
        )

        return Response(response)

    # Session status GET '<id>/status/'
    @swagger_auto_schema(
        operation_summary="Get Session Status",
        responses={
            200: openapi.Response("Success - Session status retrieved successfully."),
            404: openapi.Response("Not Found - Session not found."),
        }
    )
    @action(detail=True)
    def status(self, request, pk):
        """
        Retrieves the current status of a session.

        Statuses:
        - "ready": No active trial, session is ready to start recording.
        - "recording": An active trial is in progress and recording is ongoing.
        - "uploading": Recording completed but some videos are still being uploaded.
        - "processing": Videos are uploaded but still being processed.
        - If "processing" results in errors or completes, the status reverts to "ready".

        Logic on the client side:
        - if status changed "*" -> "recording" start recording
        - if status change "recording" -> "*" stop recording and submit the video

        For each device checking the status in the "recording" phase, create a video record
        """
        status_dict = self.get_status(request, pk)

        return Response(status_dict)

    # Start recording POST '<id>/record/'
    @swagger_auto_schema(
        operation_summary="Start a New Recording Session",
        responses={
            200: openapi.Response("Success - Recording session started successfully."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not start recording session."),
        }
    )
    @action(detail=True)
    def record(self, request, pk):
        """
        Starts a new recording session by creating a trial.

        Creates a new trial associated with the given session and assigns it the status of "recording".
        If the specified trial name already exists in the session, the function generates a new name
        by appending a suffix.
        """
        def get_count_from_name(name, base_name):
            try:
                count = int(name[len(base_name) + 1:])
                return count
            except ValueError:
                return 0

        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk, user=request.user)

            name = request.GET.get("name", None)

            trial = Trial()
            trial.session = session

            name_count = Trial.objects.filter(name__startswith=name, session=session).count()
            if (name_count > 0) and (name not in ["calibration", "neutral"]):
                name = "{}_{}".format(name, name_count)

            existing_names = Trial.objects.filter(name__startswith=name, session=session).values_list('name', flat=True)
            if (len(existing_names) > 0) and (name not in ["calibration", "neutral"]) and (name in existing_names):
                highest_count = max([get_count_from_name(existing_name, name) for existing_name in existing_names])
                name = "{}_{}".format(name, highest_count + 1)

            trial.name = name
            trial.save()

            if name == "calibration" or name == "neutral":
                time.sleep(2)
                return self.stop(request, pk)

            serializer = TrialSerializer(trial, many=False)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('trial_record_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Download Session Files as a ZIP",
        responses={
            200: openapi.Response("Success - File download initiated successfully."),
            500: openapi.Response("Internal Server Error - Could not initiate file download."),
        }
    )
    @action(detail=True)
    def download(self, request, pk):
        """
        Downloads the files associated with a session and returns them as a ZIP archive.
        """
        try:
            # Extract protocol and host.
            if request.is_secure():
                host = "https://" + request.get_host()
            else:
                host = "http://" + request.get_host()

            session_zip = downloadAndZipSession(pk, host=host)

        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('session_download_error'))

        return FileResponse(open(session_zip, "rb"))

    @action(detail=True, url_path="async-download", url_name="async_session_download")
    def async_download(self, request, pk):
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            # Check if the session is public or belongs to the logged-in user
            session = get_object_or_404(Session, pk=pk)
            if not session.public and session.user != request.user:
                raise PermissionDenied(_('permission_denied'))

            if request.user.is_authenticated:
                task = download_session_archive.delay(session.id, request.user.id)
            else:
                task = download_session_archive.delay(session.id)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('session_download_error'))

        return Response({"task_id": task.id}, status=200)

    @swagger_auto_schema(
        operation_summary="Get Session Permissions",
        responses={
            200: openapi.Response("Success - Session permissions retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve session permissions."),
        }
    )
    @action(detail=True)
    def get_session_permission(self, request, pk):
        """
        Retrieves the permission settings for a specified session.

        This function checks the given session's ownership, visibility (public or private),
        and whether the requesting user has admin privileges.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)

            isSessionOwner = session.user == request.user
            isSessionPublic = session.public
            isUserAdmin = request.user.groups.filter(name='admin').exists()
            sessionPermission = {'isOwner': isSessionOwner,
                                 'isPublic': isSessionPublic,
                                 'isAdmin': isUserAdmin}

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('session_get_settings_error'))

        return Response(sessionPermission)

    @swagger_auto_schema(
        operation_summary="Get Session Settings",
        responses={
            200: openapi.Response("Success - Session settings retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve session settings."),
        }
    )
    @action(detail=True)
    def get_session_settings(self, request, pk):
        """
        Retrieves the settings of a specified session, including available framerate options.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)

            # Check if using same setup
            if session.meta and 'sessionWithCalibration' in session.meta and 'id' in session.meta[
                'sessionWithCalibration']:
                session = Session.objects.get(pk=session.meta['sessionWithCalibration']['id'])

            self.check_object_permissions(self.request, session)
            serializer = SessionSerializer(session)

            trials = session.trial_set.order_by("-created_at")
            trial = None

            # If there is at least one trial, check it's status
            if trials.count():
                trial = trials[0]

            maxFramerates = []
            if trial and trial.video_set.count() > 0:
                for video in trial.video_set.all():
                    if 'max_framerate' in video.parameters:
                        maxFramerates.append(video.parameters['max_framerate'])
                    else:
                        maxFramerates = [60]

            framerateOptions = [60, 120, 240]
            frameratesAvailable = [f for f in framerateOptions if f <= min(maxFramerates or [0])]

            settings_dict = {'framerates': frameratesAvailable}

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except NotAuthenticated:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('login_needed'))
        except PermissionDenied:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('permission_denied'))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('session_get_settings_error'))

        return Response(settings_dict)

    @swagger_auto_schema(
        operation_summary="Set Session Metadata",
        manual_parameters=[
            openapi.Parameter(
                name="subject_id",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="ID of the subject for this session."
            ),
            openapi.Parameter(
                name="subject_mass",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Mass of the subject."
            ),
            openapi.Parameter(
                name="subject_height",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Height of the subject."
            ),
            openapi.Parameter(
                name="subject_sex",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Sex of the subject."
            ),
            openapi.Parameter(
                name="subject_gender",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Gender of the subject."
            ),
            openapi.Parameter(
                name="subject_data_sharing",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Data sharing preferences for the subject."
            ),
            openapi.Parameter(
                name="subject_pose_model",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Pose model used for the subject."
            ),
            openapi.Parameter(
                name="settings_framerate",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Framerate setting for the session."
            ),
            openapi.Parameter(
                name="settings_data_sharing",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Data sharing setting for the session."
            ),
            openapi.Parameter(
                name="settings_pose_model",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Pose model setting for the session."
            ),
            openapi.Parameter(
                name="settings_openSimModel",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="OpenSim model used for the session."
            ),
            openapi.Parameter(
                name="settings_augmenter_model",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Augmenter model used for the session."
            ),
            openapi.Parameter(
                name="settings_filter_frequency",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Filter frequency setting for the session."
            ),
            openapi.Parameter(
                name="settings_scaling_setup",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Scaling setup used for the session."
            ),
            openapi.Parameter(
                name="cb_square",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Size of each square in the checkerboard pattern."
            ),
            openapi.Parameter(
                name="cb_rows",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Number of rows in the checkerboard pattern."
            ),
            openapi.Parameter(
                name="cb_cols",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Number of columns in the checkerboard pattern."
            ),
            openapi.Parameter(
                name="cb_placement",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Placement of the checkerboard."
            ),
            openapi.Parameter(
                name="settings_session_name",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Name of the session."
            ),
        ],
        responses={
            200: openapi.Response("Success - Session metadata updated successfully."),
            400: openapi.Response("Bad Request - Invalid request data."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not set the session metadata."),
        }
    )
    @action(detail=True)
    def set_metadata(self, request, pk):
        """
        Updates the metadata of a specified session with provided query parameters.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)

            if not session.meta:
                session.meta = {}

            if "subject_id" in request.GET:
                session.meta["subject"] = {
                    "id": request.GET.get("subject_id", ""),
                    "mass": request.GET.get("subject_mass", ""),
                    "height": request.GET.get("subject_height", ""),
                    "sex": request.GET.get("subject_sex", ""),
                    "gender": request.GET.get("subject_gender", ""),
                    "datasharing": request.GET.get("subject_data_sharing", ""),
                    "posemodel": request.GET.get("subject_pose_model", ""),
                }

            if "settings_framerate" in request.GET:
                session.meta["settings"] = {
                    "framerate": request.GET.get("settings_framerate", ""),
                }

            if "settings_data_sharing" in request.GET:
                if not session.meta["settings"]:
                    session.meta["settings"] = {}
                session.meta["settings"]["datasharing"] = request.GET.get("settings_data_sharing", "")

            if "settings_pose_model" in request.GET:
                if not session.meta["settings"]:
                    session.meta["settings"] = {}
                session.meta["settings"]["posemodel"] = request.GET.get("settings_pose_model", "")

            if "settings_openSimModel" in request.GET:
                if not session.meta["settings"]:
                    session.meta["settings"] = {}
                session.meta["settings"]["openSimModel"] = request.GET.get("settings_openSimModel", "")

            if "settings_augmenter_model" in request.GET:
                if not session.meta["settings"]:
                    session.meta["settings"] = {}
                session.meta["settings"]["augmentermodel"] = request.GET.get("settings_augmenter_model", "")

            if "settings_filter_frequency" in request.GET:
                if not session.meta["settings"]:
                    session.meta["settings"] = {}
                session.meta["settings"]["filterfrequency"] = request.GET.get("settings_filter_frequency", "")

            if "settings_scaling_setup" in request.GET:
                if not session.meta["settings"]:
                    session.meta["settings"] = {}
                session.meta["settings"]["scalingsetup"] = request.GET.get("settings_scaling_setup", "")

            if "cb_square" in request.GET:
                session.meta["checkerboard"] = {
                    "square_size": request.GET.get("cb_square", ""),
                    "rows": request.GET.get("cb_rows", ""),
                    "cols": request.GET.get("cb_cols", ""),
                    "placement": request.GET.get("cb_placement", ""),
                }

            if "settings_session_name" in request.GET:
                if "settings_session_name" not in session.meta:
                    session.meta["sessionName"] = request.GET.get("settings_session_name", "")

            session.save()

            serializer = SessionSerializer(session, many=False)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException("Error: " + traceback.format_exc())
            raise APIException(_('session_set_metadata_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Assign a Subject to a Session",
        manual_parameters=[
            openapi.Parameter(
                'subject_id', openapi.IN_QUERY, description="UUID of the subject to assign to the session",
                type=openapi.TYPE_STRING, required=True
            ),
        ],
        responses={
            200: openapi.Response("Success - Session subject updated successfully."),
            400: openapi.Response("Bad Request - Invalid request data."),
            404: openapi.Response("Not Found - Session or subject not found."),
            500: openapi.Response("Internal Server Error - Could not update the subject."),
        }
    )
    @action(detail=True)
    def set_subject(self, request, pk):
        """
        Assign a Subject to a Session.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_assign_error'))

        try:
            subject_id = request.GET.get("subject_id", "")
            subject = get_object_or_404(Subject, id=subject_id, user=request.user)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_found') % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_assign_error'))

        try:
            session.subject = subject
            session.save()
            serializer = SessionSerializer(session, many=False)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_assign_error'))

        return Response(serializer.data)

    # Stop recording POST '<id>/stop/'
    @swagger_auto_schema(
        operation_summary="Stop Trial Recording",
        responses={
            200: openapi.Response("Success - Session stopped successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session or trial not found."),
            500: openapi.Response("Internal Server Error - Could not stop the session."),
        }
    )
    @action(detail=True)
    def stop(self, request, pk):
        """
        Changes the trial status from "recording" to "done"

        Logic on the client side:
        - Session status changed, so they start uploading videos.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)
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

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException("Error: " + traceback.format_exc())
            raise APIException(_('trial_cancel_error'))

        return Response(serializer.data)

    # Cancel trial POST '<id>/stop/'
    @swagger_auto_schema(
        operation_summary="Cancel Trial",
        responses={
            200: openapi.Response("Success - Trial cancelled successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not stop the trial."),
        }
    )
    @action(detail=True)
    def cancel_trial(self, request, pk):
        """
        Changes the trial status from "stopped" to "error"

        Logic on the client side:
         - session status changed when cancel is pressed
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)
            trials = session.trial_set.order_by("-created_at")

            # If there is at least one trial, check its status
            if len(trials) > 0:
                trial = trials[0]
                trial.status = "error"
                trial.save()
                data = {"status": "error"}
            else:
                data = {"status": "noTrials"}
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException("Error: " + traceback.format_exc())
            raise APIException(_('trial_cancel_error'))

        return Response(data)

    @swagger_auto_schema(
        operation_summary="Retrieve Calibration Image and Status",
        responses={
            200: openapi.Response("Success - Calibration image retrieved successfully."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Session or trial not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve calibration image."),
        }
    )
    @action(detail=True)
    def calibration_img(self, request, pk):
        """
        Retrieve Calibration Image and Status.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)
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
            elif not trials[0].status in ['done', 'error']:  # this gets updated on the backend by app.py
                data = {
                    "status": "processing",
                    "img": [
                        # "https://main.d2stl78iuswh3t.amplifyapp.com/images/camera-calibration.png"
                    ],
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
                }
            elif trials[0].status == 'done':
                data = {
                    "status": "done",
                    "img": "None",
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
                }

            else:
                data = {
                    "status": "error",
                    "img": [],
                    "n_cameras_connected": status_session["n_cameras_connected"],
                    "n_videos_uploaded": status_session["n_videos_uploaded"]
                }
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except NotAuthenticated:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('login_needed'))
        except PermissionDenied:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('permission_denied'))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('calibration_image_retrieve_error'))

        return Response(data)

    @swagger_auto_schema(
        operation_summary="Retrieve Neutral Image and Status",
        responses={
            200: openapi.Response("Success - Neutral image retrieved successfully."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Session or trial not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve neutral image."),
        }
    )
    @action(detail=True)
    def neutral_img(self, request, pk):
        """
        Retrieve Calibration Image and Status.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)
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
            elif not trials[0].status in ['done', 'error']:  # this gets updated on the backend by app.py
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

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except NotAuthenticated:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('login_needed'))
        except PermissionDenied:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('permission_denied'))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("neutral_image_retrieve_error") % {"uuid": str(pk)})

        return Response(data)

    @swagger_auto_schema(
        operation_summary="Retrieve Session Statuses",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'status': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="Status of the sessions to filter (e.g., active, completed, error)."
                ),
                'date_range': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_STRING),
                    description="An array containing two date strings [start_date, end_date] for filtering sessions "
                                "by status change date."
                ),
                'username': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="Username of the user associated with the sessions (optional, requires admin or "
                                "backend permissions)."
                )
            },
            required=['status'],
        ),
        responses={
            200: openapi.Response("Success - Session statuses retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not retrieve session statuses."),
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[IsAdmin | IsBackend | IsOwner])
    def get_session_statuses(self, request):
        """
        Retrieve Session Statuses.
        """
        from .serializers import SessionIdSerializer, SessionFilteringSerializer
        try:
            filtering_serializer = SessionFilteringSerializer(data=request.data)
            serializer = SessionIdSerializer(Session.objects.none(), many=True)
            if filtering_serializer.is_valid():
                status_str = filtering_serializer.validated_data.get('status')
                date_range = filtering_serializer.validated_data.get('date_range')
                filter_kwargs = {'status': status_str}
                if date_range:
                    filter_kwargs['status_changed__gte'] = date_range[0]
                    filter_kwargs['status_changed__lte'] = date_range[1]
                if not IsAdmin().has_permission(request, self) and not IsBackend().has_permission(request, self):
                    filter_kwargs['user'] = request.user
                else:
                    if 'username' in filtering_serializer.validated_data:
                        filter_kwargs['user__username'] = filtering_serializer.validated_data.get('username')

                sessions = Session.objects.filter(**filter_kwargs)
                serializer = SessionIdSerializer(sessions, many=True)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("user_not_found"))
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_not_valid"))
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_remove_error"))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Set Session Status",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'status': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="The new status to set for the session (e.g., active, completed, error).",
                    example="completed"
                )
            },
            required=['status'],
        ),
        responses={
            200: openapi.Response("Success - Session status set successfully."),
            400: openapi.Response("Bad Request - Invalid session data."),
            404: openapi.Response("Not Found - Session not found."),
            500: openapi.Response("Internal Server Error - Could not set session status."),
        }
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin | IsBackend])
    def set_session_status(self, request, pk):
        """
        Set Session Status.
        """
        from .serializers import SessionStatusSerializer
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            session = get_object_or_404(Session, pk=pk)
            serializer = SessionStatusSerializer(data=request.data)
            if serializer.is_valid():
                session.status = serializer.validated_data['status']
                session.status_changed = timezone.now()
                session.save()

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("session_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_("session_remove_error"))

        return Response(serializer.data)


## Processing machine:
# A worker asks whether there is any trial to process
# - if no it asks again in 5 sec
# - if yes it runs processing and sends back the results
class TrialViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing trials.
    """
    queryset = Trial.objects.all().order_by("created_at")
    serializer_class = TrialSerializer

    permission_classes = [IsPublic | (IsOwner | IsAdmin | IsBackend)]

    @swagger_auto_schema(
        operation_summary="Dequeue a trial for processing",
        responses={
            200: openapi.Response("Success - Trial dequeued successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    @action(detail=False, permission_classes=[(IsAdmin | IsBackend)])
    def dequeue(self, request):
        """
        Dequeue a trial and set its status to 'processing' if available.
        """
        try:
            ip = get_client_ip(request)

            workerType = self.request.query_params.get('workerType')

            # find trials with some videos not uploaded
            not_uploaded = Video.objects.filter(video='',
                                                updated_at__gte=datetime.now() + timedelta(minutes=-15)).values_list(
                "trial__id", flat=True)

            print(not_uploaded)

            uploaded_trials = Trial.objects.exclude(id__in=not_uploaded)
            #       uploaded_trials = Trial.objects.all()

            if workerType != 'dynamic':
                # Priority for 'calibration' and 'neutral'
                trials = uploaded_trials.filter(status="stopped",
                                                name__in=["calibration", "neutral"],
                                                result=None)

                trialsReprocess = uploaded_trials.filter(status="reprocess",
                                                         name__in=["calibration", "neutral"],
                                                         result=None)

                if trials.count() == 0 and workerType != 'calibration':
                    trials = uploaded_trials.filter(status="stopped",
                                                    result=None)

                if trials.count() == 0 and trialsReprocess.count() == 0 and workerType != 'calibration':
                    trialsReprocess = uploaded_trials.filter(status="reprocess",
                                                             result=None)

            else:
                trials = uploaded_trials.filter(status="stopped",
                                                result=None).exclude(name__in=["calibration", "neutral"])

                trialsReprocess = uploaded_trials.filter(status="reprocess",
                                                         result=None).exclude(name__in=["calibration", "neutral"])

            if trials.count() == 0 and trialsReprocess.count() == 0:
                raise Http404

            # prioritize admin and priority group trials (priority group doesn't exist yet, but should have same
            # priv. as user)
            trialsPrioritized = trials.filter(session__user__groups__name__in=["admin", "priority"])
            # if not priority trials, go to normal trials
            if trialsPrioritized.count() == 0:
                trialsPrioritized = trials
            # if no normal trials, go to reprocess trials
            if trials.count() == 0:
                trialsPrioritized = trialsReprocess

            trial = trialsPrioritized[0]
            trial.status = "processing"
            trial.server = ip
            trial.processed_count += 1
            trial.save()

            print(ip)
            print(trial.session.server)
            if (not trial.session.server) or len(trial.session.server) < 1:
                session = Session.objects.get(id=trial.session.id)
                session.server = ip
                session.save()

            serializer = TrialSerializer(trial, many=False)

        except Http404:
            raise Http404 # we use the 404 to tell app.py that there are no trials, so need to pass this thru
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('trial_dequeue_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Get Trials by Status",
        responses={
            200: openapi.Response("Success - Trial list retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid search data."),
        },
    )
    @action(detail=False, permission_classes=[((IsAdmin | IsBackend))])
    def get_trials_with_status(self, request):
        """
        Returns a list of trials with the specified status that were updated more than 'hoursSinceUpdate' hours ago.
        """
        hours_since_update = request.query_params.get('hoursSinceUpdate', 0)
        hours_since_update = float(hours_since_update) if hours_since_update else 0

        status = self.request.query_params.get('status')
        # trials with given status and updated_at more than n hours ago
        trials = Trial.objects.filter(status=status,
                                      updated_at__lte=(datetime.now() - timedelta(hours=hours_since_update))).order_by(
            "-created_at")

        serializer = TrialSerializer(trials, many=True)

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Rename a specific trial by ID",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'trialNewName': openapi.Schema(type=openapi.TYPE_STRING, description='New name for the trial'),
            }
        ),
        responses={
            200: openapi.Response("Success - Trial renamed successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    @action(detail=True, methods=['post'])
    def rename(self, request, pk):
        """
        Rename a specific trial by its ID.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            # Get trial.
            trial = get_object_or_404(Trial, pk=pk, session__user=request.user)

            # Update trial name and save.
            trial.name = request.data['trialNewName']
            trial.save()

            # Serialize trial.
            serializer = TrialSerializer(trial)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('trial_rename_error'))

        # Return error message and data.
        return Response({
            'data': serializer.data
        })

    @swagger_auto_schema(
        operation_summary="Permanently Remove a Trial",
        responses={
            204: openapi.Response("Deleted - Trial deleted successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    @action(detail=True, methods=['post'])
    def permanent_remove(self, request, pk):
        """
        Permanently delete a trial by its ID.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            trial = get_object_or_404(Trial, pk=pk, session__user=request.user)
            trial.delete()

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('trial_permanent_remove_error'))

        return Response({})

    @swagger_auto_schema(
        operation_summary="Trash trial",
        operation_description="Move a trial to the trash.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"pk": openapi.Schema(type=openapi.TYPE_STRING)},
            required=["pk"]
        ),
        responses={
            200: openapi.Response("Succes - Trial trashed successfully."),
            404: openapi.Response("Not Found - Trial not found."),
        }
    )
    @action(detail=True, methods=['post'])
    def trash(self, request, pk):
        """
        Move a specific trial to the trash.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            trial = get_object_or_404(Trial, pk=pk, session__user=request.user)
            trial.trashed = True
            trial.trashed_at = now()
            trial.save()

            serializer = TrialSerializer(trial)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('trial_remove_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Restore a Trial from Trash",
        responses={
            200: openapi.Response("Success - Trial restored from trash successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    @action(detail=True, methods=['post'])
    def restore(self, request, pk):
        """
        Restore a specific trial from the trash.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            trial = get_object_or_404(Trial, pk=pk, session__user=request.user)
            trial.trashed = False
            trial.trashed_at = None
            trial.save()

            serializer = TrialSerializer(trial)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_valid") % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('trial_restore_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="List Trials",
        responses={
            200: openapi.Response("Success - List of trials retrieved successfully."),
        },
    )
    def list(self, request, *args, **kwargs):
        """
        Retrieve a list of trials.
        """
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Create a Trial",
        request_body=VideoSerializer,
        responses={
            201: openapi.Response("Created - Trial created successfully."),
            404: openapi.Response("Not Found - Trial not found."),
            403: openapi.Response("Forbidden - Authentication is required."),
        },
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new trial instance.
        """
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve Trial",
        responses={
            200: openapi.Response("Success - Trial retrieved successfully."),
            404: openapi.Response("Not Found - Trial not found."),
        },    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific trial instance by ID.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update Trial",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Trial updated successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    def update(self, request, *args, **kwargs):
        """
        Update a specific trial instance by ID.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partial Update Trial",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Trial partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid trial data."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a specific trial instance by ID.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Trial",
        responses={
            204: openapi.Response("Deleted - Trial deleted successfully."),
            404: openapi.Response("Not Found - Trial not found."),
        },
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a specific trial instance by ID.
        """
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def modifyTags(self, request, pk):
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            tags = request.data['trialNewTags']

            # Get trial.
            trial = get_object_or_404(Trial, pk=pk, session__user=request.user)

            # Remove previous tags.
            if TrialTags.objects.filter(trial=trial).exists():
                TrialTags.objects.filter(trial=trial).delete()

            # Insert new tags.
            for tag in tags:
                TrialTags.objects.create(trial=trial, tag=tag)

            print(tags)

            # Serialize trial.
            serializer = TrialSerializer(trial)

        except Http404:
            if settings.DEBUG:
                raise Exception(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_found") % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise Exception(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_("trial_uuid_not_valid") % {"uuid": str(pk)})

        # Return error message and data.
        return Response({
            'data': serializer.data
        })

## Upload a video:
# Input: video and phone_id
# Logic: Find the Video model within this session with
# device_id. Upload Video to that model
class VideoViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing videos.
    """
    queryset = Video.objects.all().order_by("-created_at")
    serializer_class = VideoSerializer

    permission_classes = [AllowPublicCreate | ((IsOwner | IsAdmin | IsBackend))]

    def perform_update(self, serializer):
        if ("video_url" in serializer.validated_data) and (serializer.validated_data["video_url"]):
            serializer.validated_data["video"] = serializer.validated_data["video_url"]
            del serializer.validated_data["video_url"]

        super().perform_update(serializer)

    @swagger_auto_schema(
        operation_summary="List Videos",
        responses={
            200: openapi.Response("Success - List of videos retrieved successfully."),
        },
    )
    def list(self, request, *args, **kwargs):
        """
        Retrieve a list of videos.
        """
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Create Video",
        request_body=VideoSerializer,
        responses={
            201: openapi.Response("Created - Video created successfully."),
            404: openapi.Response("Not Found - Video not found."),
            403: openapi.Response("Forbidden - Authentication is required."),
        },
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new video instance.
        """
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve Video",
        responses={
            200: openapi.Response("Success - Video retrieved successfully."),
            404: openapi.Response("Not Found - Video not found."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific video instance by ID.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update Video",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Video updated successfully."),
            400: openapi.Response("Bad Request - Invalid video data."),
            404: openapi.Response("Not Found - Video not found."),
        },
    )
    def update(self, request, *args, **kwargs):
        """
        Update a specific video instance by ID.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partial Update Video",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Video partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid video data."),
            404: openapi.Response("Not Found - Video not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a specific video instance by ID.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Video",
        responses={
            204: openapi.Response("Deleted - Video deleted successfully."),
            404: openapi.Response("Not Found - Video not found."),
        },
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a specific video instance by ID.
        """
        return super().destroy(request, *args, **kwargs)


class ResultViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing results.
    """
    queryset = Result.objects.all().order_by("-created_at")
    serializer_class = ResultSerializer

    permission_classes = [IsOwner | IsAdmin | IsBackend]

    @swagger_auto_schema(
        operation_summary="Create Result",
        request_body=ResultSerializer,
        responses={
            201: openapi.Response("Created - Result created successfully."),
            400: openapi.Response("Bad Request - Invalid Result data."),
            403: openapi.Response("Forbidden - Authentication is required."),
        },
    )
    def create(self, request):
        """
        Create a new result instance.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # We use [0] here because all our permissions is the single list element
        has_perms = self.permission_classes[0]().has_object_permission(
            request, self, serializer.validated_data["trial"])
        if not has_perms:
            raise PermissionDenied(_('permission_denied'))

        if request.data.get('media_url'):
            serializer.validated_data["media"] = serializer.validated_data["media_url"]
            del serializer.validated_data["media_url"]
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @swagger_auto_schema(
        operation_summary="List Results",
        responses={
            200: openapi.Response("Success - List of results retrieved successfully."),
        },
    )
    def list(self, request, *args, **kwargs):
        """
        Retrieve a list of results.
        """
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve Result",
        responses={
            200: openapi.Response("Success - Rrsult retrieved successfully."),
            404: openapi.Response("Not Found - Result not found."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific result instance by ID.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update Result",
        request_body=ResultSerializer,
        responses={
            200: openapi.Response("Success - Result updated successfully."),
            400: openapi.Response("Bad Request - Invalid Result data."),
            404: openapi.Response("Not Found - Result not found."),
        },
    )
    def update(self, request, *args, **kwargs):
        """
        Update a specific result instance by ID.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partial Update Result",
        request_body=ResultSerializer,
        responses={
            200: openapi.Response("Success - Result partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid result data."),
            404: openapi.Response("Not Found - Result not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a specific result instance by ID.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Result",
        responses={
            204: openapi.Response("Deleted - Result deleted successfully."),
            404: openapi.Response("Not Found - Result not found."),
        },
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a specific result instance by ID.
        """
        return super().destroy(request, *args, **kwargs)


class SubjectViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing subjects.
    """
    permission_classes = [IsOwner | IsAdmin | IsBackend]

    def get_queryset(self):
        """
        Returns a list of subjects for the currently authenticated user.

        - Admin users get all subjects.
        - Regular users get only their own subjects.
        """
        user = self.request.user
        # If user is authenticated, and it has privileges (e.g., is admin) return all.
        if (user.is_authenticated and user.id == 1) or (user.is_authenticated and user.id == 2):
            return Subject.objects.all().prefetch_related('subjecttags_set')
        # If user is authenticated, but has no privileges, return only its own data.
        elif user.is_authenticated and type(user) is not AnonymousUser:
            return Subject.objects.filter(user=user).prefetch_related('subjecttags_set')
        else:
            return []
        # public_subject_ids = Session.objects.filter(public=True).values_list('subject_id', flat=True).distinct()
        # return Subject.objects.filter(Q(user=user) | Q(id__in=public_subject_ids)).prefetch_related('subjecttags_set')
        # return Subject.objects.filter(user=user).prefetch_related('subjecttags_set')

    @swagger_auto_schema(
        operation_summary="List subjects",
        responses={
            200: openapi.Response("Success - List of subjects retrieved successfully."),
            400: openapi.Response("Bad Request - Invalid search parameters."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
        }
    )
    def list(self, request):
        """
        Retrieves a list of subjects based on the user's permissions and provided query parameters.
        The list can be filtered, sorted, and paginated using the provided options.
        """
        queryset = self.get_queryset()
        # Get quantity from post request. If it does exist, use it. If not, set -1 as default (e.g., return all)
        # print(request.query_params)
        is_simple = request.query_params.get('simple', 'false') == 'true'
        search = request.query_params.get('search', '')
        include_trashed = request.query_params.get('include_trashed', 'false') == 'true'
        sort_by = request.query_params.get('sort[]', 'name')
        sort_desc = request.query_params.get('sort_desc[]', 'false') == 'true'

        if 'quantity' not in self.request.query_params:
            quantity = -1
        else:
            quantity = int(self.request.query_params['quantity'])
        start = 0 if 'start' not in self.request.query_params else int(self.request.query_params['start'])

        if not include_trashed:
            queryset = queryset.exclude(trashed=True)
        if search:
            queryset = queryset.filter(name__icontains=search)

        sort_options = {
            'sex_display': 'sex_at_birth',
            'gender_display': 'gender',
        }

        queryset = queryset.order_by(
            *[('-' if sort_desc else '') + sort_options.get(sort_by, sort_by)],
            'id')

        if quantity != -1 and start > 0:
            queryset = queryset[start: start + quantity]
        elif quantity != -1:
            queryset = queryset[:quantity]

        serializer = (SimpleSubjectSerializer if is_simple else SubjectSerializer)(queryset, many=True)
        return Response({'subjects': serializer.data, 'total': self.get_queryset().count()})

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return NewSubjectSerializer
        return SubjectSerializer

    @swagger_auto_schema(
        operation_summary="Health check",
        responses={
            200: openapi.Response("Success - API health retrieved successfully."),
        }
    )
    @action(detail=False)
    def api_health_check(self, request):
        """
        Check the health of the API.
        """
        return Response({"status": "True"})

    @swagger_auto_schema(
        operation_summary="Trash subject",
        operation_description="Move a subject to the trash.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"pk": openapi.Schema(type=openapi.TYPE_STRING)},
            required=["pk"]
        ),
        responses={
            200: openapi.Response("Success - Subject trashed successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        }
    )
    @action(detail=True, methods=['post'])
    def trash(self, request, pk):
        """
        Move a specific subject to the trash.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            subject = get_object_or_404(Subject, pk=pk, user=request.user)
            subject.trashed = True
            subject.trashed_at = now()
            subject.save()

            serializer = SubjectSerializer(subject)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_found') % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_valid') % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_remove_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Restore subject",
        operation_description="Restore a subject from the trash.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"pk": openapi.Schema(type=openapi.TYPE_STRING)},
            required=["pk"]
        ),
        responses={
            200: openapi.Response("Success - Subject restored successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        }
    )
    @action(detail=True, methods=['post'])
    def restore(self, request, pk):
        """
        Restores a previously trashed subject.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            subject = get_object_or_404(Subject, pk=pk, user=request.user)
            subject.trashed = False
            subject.trashed_at = None
            subject.save()

            serializer = SubjectSerializer(subject)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_found') % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_valid') % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_restore_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Download subject",
        responses={
            200: openapi.Response("Success - Subject archive downloaded successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        }
    )
    @action(detail=True)
    def download(self, request, pk):
        """
        Downloads a zip file containing the data for the specified subject.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            subject = get_object_or_404(Subject, pk=pk, user=request.user)
            # Extract protocol and host.
            if request.is_secure():
                host = "https://" + request.get_host()
            else:
                host = "http://" + request.get_host()

            subject_zip = downloadAndZipSubject(pk, host=host)
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_found') % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_valid') % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_create_error'))

        return FileResponse(open(subject_zip, "rb"))

    @swagger_auto_schema(
        operation_summary="Async download",
        responses={
            200: openapi.Response("Success - Subject archive downloaded successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        }
    )
    @action(detail=True, url_path="async-download", url_name="async_subject_download")
    def async_download(self, request, pk):
        """
        Download a subject archive.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            subject = get_object_or_404(Subject, pk=pk, user=request.user)
            task = download_subject_archive.delay(subject.id, request.user.id)

        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_found') % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_valid') % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_create_error'))

        return Response({"task_id": task.id}, status=200)

    @swagger_auto_schema(
        operation_summary="Permanently remove subject",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"pk": openapi.Schema(type=openapi.TYPE_STRING)},
            required=["pk"]
        ),
        responses={
            200: openapi.Response("Success - Subject removed successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        }
    )
    @action(detail=True, methods=['post'])
    def permanent_remove(self, request, pk):
        """
        Permanently deletes a subject.
        """
        try:
            if pk == 'undefined':
                raise ValueError(_("undefined_uuid"))

            subject = get_object_or_404(Subject, pk=pk, user=request.user)
            subject.delete()
            return Response({})
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_found') % {"uuid": str(pk)})
        except ValueError:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('subject_uuid_not_valid') % {"uuid": str(pk)})
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_permanent_remove_error'))

    def perform_create(self, serializer):
        try:
            serializer.save(user=self.request.user)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_create_error'))

    def perform_update(self, serializer):
        try:
            serializer.save()

            tags = serializer.context['request'].data['subject_tags']

            # Get current subject.
            subject = Subject.objects.get(id=serializer.context['request'].data['id'])

            # Remove previous tags.
            SubjectTags.objects.filter(subject=subject).delete()

            # Insert new tags.
            for tag in tags:
                SubjectTags.objects.create(subject=subject, tag=tag)

            print(tags)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('subject_update_error'))

    @swagger_auto_schema(
        operation_summary="Retrieve Subject",
        responses={
            200: openapi.Response("Success - Subject retrieved successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific subject instance by ID.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update Subject",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Subject updated successfully."),
            400: openapi.Response("Bad Request - Invalid subject data."),
            404: openapi.Response("Not Found - Subject not found."),
        },
    )
    def update(self, request, *args, **kwargs):
        """
        Update a specific subject instance by ID.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partial Update Subject",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Subject partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid Subject data."),
            404: openapi.Response("Not Found - Subject not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a specific subject instance by ID.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Subject",
        responses={
            204: openapi.Response("Deleted - Subject deleted successfully."),
            404: openapi.Response("Not Found - Subject not found."),
        },
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a specific subject instance by ID.
        """
        return super().destroy(request, *args, **kwargs)


class SubjectTagViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing subject tags.
    """
    permission_classes = [IsOwner | IsAdmin | IsBackend]
    serializer_class = SubjectTagSerializer

    def get_queryset(self):
        """
        Retrieve a list of all the subject tags for the currently authenticated user.

        - If the user is authenticated, returns the tags associated with their subjects.
        - If the user is not authenticated, returns an empty list.
        """
        user = self.request.user
        if user.is_authenticated:
            # Get all subjects associated to a user.
            subject = Subject.objects.filter(user=self.request.user)

            # Get tags associated to those subjects.
            tags = SubjectTags.objects.filter(subject__in=list(subject))
        else:
            tags = []

        return tags

    @swagger_auto_schema(
        operation_summary="Get tags for a specific subject",
        operation_description="Retrieve tags associated with a specific subject identified by its ID.",
        manual_parameters=[
            openapi.Parameter('subject_id', openapi.IN_PATH, description="ID of the subject to retrieve tags for.",
                              type=openapi.TYPE_INTEGER),
        ],
        responses={
            200: openapi.Response("Success - Subject tags retrieved successfully."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Subject tags not found."),
        }
    )
    @action(detail=False, methods=['get'])
    def get_tags_subject(self, request, subject_id):
        """
        Retrieves the tags associated with a specific subject.
        """
        # Get subject associated to that id.
        subject = Subject.objects.filter(id=subject_id).first()

        if subject:
            # Get tags associated to the subject.
            tags = list(SubjectTags.objects.filter(subject=subject).values())

            return Response(tags, status=200)
        else:
            return Response(
                _("Subject with id: ") + str(subject_id) + _(" does not exist for user ") + self.request.user.username,
                status=404)

    @swagger_auto_schema(
        operation_summary="List Subject Tags",
        responses={
            200: openapi.Response("Success - List of subject tags retrieved successfully."),
        },
    )
    def list(self, request, *args, **kwargs):
        """
        Retrieve a list of subject tags.
        """
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Create Subject Tag",
        request_body=UserSerializer,
        responses={
            201: openapi.Response("Created - Subject tag created successfully."),
            400: openapi.Response("Bad Request - Invalid subject tag data."),
            403: openapi.Response("Forbidden - Authentication is required."),
        },
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new subject tag instance.
        """
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve Subject Tag",
        responses={
            200: openapi.Response("Success - Subject tag retrieved successfully."),
            404: openapi.Response("Not Found - Subject tag not found."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific subject tag instance by ID.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update Subject Tag",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Subject tag updated successfully."),
            400: openapi.Response("Bad Request - Invalid subject tag data."),
            404: openapi.Response("Not Found - Subject tag not found."),
        },
    )
    def update(self, request, *args, **kwargs):
        """
        Update a specific subject tag instance by ID.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partial Update Subject Tag",
        request_body=VideoSerializer,
        responses={
            200: openapi.Response("Success - Subject tag partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid subject tag data."),
            404: openapi.Response("Not Found - Subject tag not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a specific subject tag instance by ID.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Subject Tag",
        responses={
            204: openapi.Response("Deleted - Subject tag deleted successfully."),
            404: openapi.Response("Not Found - Subject tag not found."),
        },
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a specific subject tag instance by ID.
        """
        return super().destroy(request, *args, **kwargs)

class TrialTagViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwner | IsAdmin | IsBackend]
    serializer_class = TrialTagSerializer

    def get_queryset(self):
        """
        This view should return a list of all the trial tags
        for the currently authenticated user.
        """

        # Get all sessions associated to user.
        sessions = Session.objects.filter(user=self.request.user)

        # Get all subjects associated to a user.
        trials = Trial.objects.filter(session__in=list(sessions))

        # Get tags associated to those subjects.
        tags = TrialTags.objects.filter(trial__in=list(trials))

        return tags

    @action(detail=False, methods=['get'])
    def get_tags_trial(self, request, trial_id):
        # Get subject associated to that id.
        trial = Trial.objects.get(id=trial_id)

        # Get tags associated to the subject.
        tags = list(TrialTags.objects.filter(trial=trial).values())

        return Response(tags, status=200)



class DownloadFileOnReadyAPIView(APIView):
    """
    Retrieves the download URL for a file if it is ready.
    If the file is not ready, returns a 202 status to indicate processing.
    """
    permission_classes = (AllowAny,)

    @swagger_auto_schema(
        operation_summary="Get Download URL",
        responses={
            200: openapi.Response("Success - File URL for download retrieved successfully."),
            202: openapi.Response("Accepted - The file was accepted and its being processed."),
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Check if the download file is ready.
        """
        log = DownloadLog.objects.filter(task_id=self.kwargs["task_id"]).first()
        if log and log.media:
            return Response({"url": log.media.url})
        return Response(status=202)


class UserViewSet(viewsets.ModelViewSet):
    """
    A view set for viewing and editing users.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer

    permission_classes = [IsAdmin]

    @swagger_auto_schema(
        operation_summary="List Users",
        responses={
            200: openapi.Response("Success - User retrieved successfully."),
        },
    )
    def list(self, request, *args, **kwargs):
        """
        Retrieve a list of users.
        """
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Create User",
        request_body=UserSerializer,
        responses={
            201: openapi.Response("Created - User created successfully."),
            400: openapi.Response("Bad Request - Invalid user data."),
            403: openapi.Response("Forbidden - Authentication is required."),
        },
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new user instance.
        """
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve User",
        responses={
            200: openapi.Response("Success - User retrieved successfully."),
            404: openapi.Response("Not Found - User not found."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific user instance by ID.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update User",
        request_body=UserSerializer,
        responses={
            200: openapi.Response("Success - User updated successfully."),
            400: openapi.Response("Bad Request - Invalid user data."),
            404: openapi.Response("Not Found - User not found."),
        },
    )
    def update(self, request, *args, **kwargs):
        """
        Update a specific user instance by ID.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partial Update User",
        request_body=UserSerializer,
        responses={
            200: openapi.Response("Success - User partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid user data."),
            404: openapi.Response("Not Found - User not found."),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a specific user instance by ID.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete User",
        responses={
            204: openapi.Response("Deleted - User deleted successfully."),
            404: openapi.Response("Not Found - User not found."),

        },
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a specific user instance by ID.
        """
        return super().destroy(request, *args, **kwargs)


class UserCreate(APIView):
    """ 
    Creates a new user and returns the user data along with an authentication token.
    """
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Create User",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING, description='Username of the user'),
                'email': openapi.Schema(type=openapi.TYPE_STRING, description='Email of the user'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, description='Password for the user'),
                # Add additional fields as necessary based on your UserSerializer
            },
            required=['username', 'email', 'password'],
        ),
        responses={
            201: openapi.Response("Created - User created successfully."),
            400: openapi.Response("Bad Request - Invalid user information."),
            500: openapi.Response("Internal Server Error - Could not create user.")
        }
    )
    def post(self, request, format='json'):
        """
        Handles the POST request to create a new user.
        """
        try:
            serializer = UserSerializer(data=request.data)
            if serializer.is_valid():
                user = serializer.save()
                if user:
                    token = Token.objects.create(user=user)
                    json = serializer.data
                    json['token'] = token.key
                    return Response(json, status=status.HTTP_201_CREATED)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('user_create_error'))

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserDelete(APIView):
    """
    Deletes a user. Requires confirmation by providing the username in the request data.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Delete User Account",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'confirm': openapi.Schema(type=openapi.TYPE_STRING, description="Username for confirmation"),
            },
            required=['confirm'],
        ),
        responses={
            200: openapi.Response("Success - User deleted successfully."),
            400: openapi.Response("Bad Request - Invalid username confirmation."),
            401: openapi.Response("Unauthorized - User must be authenticated.")
        }
    )
    def post(self, request, format='json'):
        """
        Handle POST requests to delete the user account.
        """
        try:
            if "confirm" not in request.data:
                return Response(_('user_delete_error'), status=status.HTTP_400_BAD_REQUEST)
            # Check user confirmed by inserting username.
            if request.data["confirm"] == request.user.username:
                user = User.objects.get(email__exact=request.user.email)
                # Check user is authenticated.
                if request.user.is_authenticated:
                    user.delete()
                    return Response(_("user_removed"), status=status.HTTP_200_OK)
                else:
                    return Response(_("user_not_authenticated"), status=status.HTTP_401_UNAUTHORIZED)
            else:
                return Response(_('confirmation_username_not_correct'), status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('user_delete_error'))


class UserUpdate(APIView):
    """
    Updates a user.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Update User",
        request_body=UserUpdateSerializer,
        responses={
            200: openapi.Response("Success - User information updated successfully."),
            400: openapi.Response("Bad Request - Invalid user information."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            500: openapi.Response("Internal Server Error - Could not update user information.")
        },
    )
    def post(self, request, format='json'):
        """
        Updates the authenticated user's information.
        """
        try:
            user = request.user
            serializer = UserUpdateSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                updated_user = serializer.save()
                return Response(UserUpdateSerializer(updated_user).data, status=status.HTTP_200_OK)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('user_update_error'))

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdateProfilePicture(APIView):
    """
    Updates the profile picture of a user.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Update Profile Picture",
        request_body=ProfilePictureSerializer,
        responses={
            200: openapi.Response("Success - Profile picture updated successfully."),
            400: openapi.Response("Bad Request - Invalid profile picture."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            500: openapi.Response("Internal Server Error - Could not update profile picture.")
        },
    )
    def post(self, request, format='json'):
        """
        Updates the profile picture for the authenticated user.
        """
        try:
            user = request.user
            serializer = ProfilePictureSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                updated_user = serializer.save()
                return Response(ProfilePictureSerializer(updated_user).data, status=status.HTTP_200_OK)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('user_update_error'))

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GetUserInfo(APIView):
    """
    Retrieves information about a user based on a username.
    """
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Get User Info",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING,
                                           description="The username of the user to retrieve information for."),
            },
            required=['username'],
        ),
        responses={
            200: openapi.Response("Success - User information retrieved successfully."),
            404: openapi.Response("Not Found - The requested user does not exist."),
        }
    )
    def post(self, request, format='json'):
        """
        Handle POST requests to retrieve user information based on username.
        """
        username = request.data["username"]
        user = get_object_or_404(User, username__exact=username)

        user_info = {
            'username': user.username,
            'email': user.email,
            'institution': user.institution,
            'profession': user.profession,
            'country': user.country,
            'reason': user.reason,
            'website': user.website,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'newsletter': user.newsletter
        }

        if user.profile_picture:
            user_info['profile_picture'] = user.profile_picture.url
        else:
            user_info['profile_picture'] = None

        return Response(user_info)


class CustomAuthToken(ObtainAuthToken):
    """
    Custom authentication token view that handles user login and OTP verification.
    """

    @swagger_auto_schema(
        operation_summary="Obtain Auth Token",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING, description="Username of the user."),
                'password': openapi.Schema(type=openapi.TYPE_STRING, description="Password of the user."),
            },
            required=['username', 'password'],
        ),
        responses={
            200: openapi.Response("Success - Logged in successfully."),
            400: openapi.Response("Bad Request - Invalid credentials or other login error."),
        }
    )
    def post(self, request, *args, **kwargs):
        """
        Handles POST requests for user authentication and OTP verification.
        """
        try:
            serializer = self.serializer_class(data=request.data,
                                               context={'request': request})
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data['user']
            token, created = Token.objects.get_or_create(user=user)

            print("LOGGED IN")

            # Skip OTP verification if specified
            otp_challenge_sent = False

            if not (user.otp_verified and user.otp_skip_till and user.otp_skip_till > timezone.now()):
                user.otp_verified = False

            user.save()
            login(request, user)

            if not (user.otp_verified and user.otp_skip_till and user.otp_skip_till > timezone.now()):
                send_otp_challenge(user)
                otp_challenge_sent = True

        except ValidationError:
            if settings.DEBUG:
                print(str(traceback.format_exc()))
                raise APIException(_("error") % {"error_message": traceback.format_exc()})
            raise APIException(_('credentials_incorrect'))
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('login_error'))

        return Response({
            'token': token.key,
            'user_id': user.id,
            'otp_challenge_sent': otp_challenge_sent,
            'institutional_use': user.institutional_use,
        })


class ResetPasswordView(APIView):
    """
    Initiates the password reset process by sending a reset email.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    @swagger_auto_schema(
        operation_summary="Reset Password",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING,
                                        description='Email of the user requesting a password reset'),
                'host': openapi.Schema(type=openapi.TYPE_STRING, description='Host URL for generating the reset link'),
            },
            required=['email', 'host'],
        ),
        responses={
            200: openapi.Response("Success - Email sent successfully."),
            404: openapi.Response("Not Found - Email not found."),
            500: openapi.Response("Internal Server Error - Could not initiate password reset.")
        }
    )
    def post(self, request, format='json'):
        """
        Handles the POST request to send a password reset email.

        Validates the input data and sends a reset password email if valid.
        """
        try:
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

            reset_password_email_subject = _('reset_password_email_subject')

            link = host + '/new-password/' + str(token)

            logo_link = settings.LOGO_LINK

            email_body_html = render_to_string('email/reset_password_email.html')
            email_body_html = email_body_html % (logo_link, username, link, link, str(token))

            email = EmailMessage(reset_password_email_subject, email_body_html, to=[email])
            email.content_subtype = "html"
            email.send()
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('account_email_not_found'))
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('error_reset_password'))

        return Response({
            'message': error_message
        })


class NewPasswordView(APIView):
    """
    Allows users to set a new password using a reset token.
    """
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Reset Password",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'token': openapi.Schema(type=openapi.TYPE_STRING, description='Reset token'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, description='New password'),
            },
            required=['token', 'password'],
        ),
        responses={
            200: openapi.Response("Success - Password sent successfully."),
            404: openapi.Response("Not Found - The reset password link is expired or invalid.")
        }
    )
    def post(self, request, format='json'):
        """
        Handles the POST request to set a new password.

        Validates the provided token and sets the new password if valid.
        """
        try:
            serializer = NewPasswordSerializer(data=request.data,
                                               context={'request': request})
            serializer.is_valid(raise_exception=True)
            new_password = serializer.validated_data['password']
            token = serializer.validated_data['token']

            # Try to retrieve email using token. If 404, the email does not exist and this link is not valid.
            email = get_object_or_404(ResetPassword, id__exact=token).email

            user = get_object_or_404(User, email__exact=email)

            # Check if token expired. First get date of creation.
            date = get_object_or_404(ResetPassword, email__exact=email).datetime
            # Check if today has passed more than 3 days since creation of token.
            if timezone.now().date() >= date + timedelta(days=3):

                # Remove the expired token.
                objects = ResetPassword.objects.filter(email=email)
                for object in objects:
                    object.delete()

                if settings.DEBUG:
                    raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
                raise NotFound(_('reset_password_link_expired'))

            else:
                # If token exists, and it has not expired, set new password.
                user.set_password(new_password)
                user.save()

                # Remove the token.
                objects = ResetPassword.objects.filter(email=email)
                for object in objects:
                    object.delete()
        except Http404:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('reset_password_link_expired'))
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise NotFound(_('new_password_creation_error'))

        # Return message. At this point no error have been thrown and this should return success.
        return Response({})


@api_view(('POST',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
@csrf_exempt
def verify(request):
    """
    Verify the OTP token provided by the user.

    This endpoint allows users to verify their one-time password (OTP) using the token sent to their device.
    If the OTP is verified successfully, the user’s OTP verification status is updated.
    Optionally, users can choose to remember the device for 90 days.
    """
    try:
        device = request.user.emaildevice_set.all()[0]
        data = json.loads(request.body.decode('utf-8'))
        verified = device.verify_token(data["otp_token"])
        print("VERIFICATION", verified)
        request.user.otp_verified = verified

        if 'remember_device' in data and data['remember_device']:
            request.user.otp_skip_till = timezone.now() + timedelta(days=90)
        request.user.save()

    except Exception:
        if settings.DEBUG:
            raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
        raise APIException(_('verification_error'))

    if not verified:
        if settings.DEBUG:
            raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
        raise NotAuthenticated(_('verification_code_incorrect'))

    return Response({})


@api_view(('POST',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
@csrf_exempt
def set_institutional_use(request):
    """
    Set the user's institutional use status.

    This endpoint allows users to specify whether their account is being used for institutional purposes.
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        request.user.institutional_use = data['institutional_use']
        request.user.save()
    except Exception:
        if settings.DEBUG:
            raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
        raise APIException(_('set_institutional_use_error'))

    return Response({})


@api_view(('POST',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
@csrf_exempt
def reset_otp_challenge(request):
    """
    Reset the OTP verification challenge for the user.

    This endpoint sends a new OTP challenge to the user's registered device and resets their verification status.
    """
    from mcserver.utils import send_otp_challenge

    send_otp_challenge(request.user)

    request.user.otp_verified = False
    request.user.otp_skip_till = None
    request.user.save()
    return Response({'otp_challenge_sent': True})


@csrf_exempt
@api_view(('GET',))
@renderer_classes((TemplateHTMLRenderer, JSONRenderer))
def check_otp_verified(request):
    """
    Check if the user has verified their OTP.

    This endpoint returns the current OTP verification status of the user.
    """
    return Response({'otp_verified': request.user.otp_verified})


class UserInstitutionalUseView(APIView):
    """
    A view for handling user institutional use information.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserInstitutionalUseSerializer

    @swagger_auto_schema(
        operation_summary="Retrieve User Institutional Use",
        responses={
            200: openapi.Response("Success - Institutional use retrieved successfully."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            500: openapi.Response("Internal Server Error - Could not retrieve institutional use.")
        },
    )
    def get(self, request, format='json'):
        """
        Retrieve the institutional use data for the authenticated user.
        """
        try:
            user = request.user
            serializer = UserInstitutionalUseSerializer(user)
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('user_institutional_use_error'))

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Update User Institutional Use",
        responses={
            200: openapi.Response("Success - Institutional use set successfully."),
            400: openapi.Response("Bad Request - Invalid input data."),
            401: openapi.Response("Unauthorized - User must be authenticated."),
            500: openapi.Response("Internal Server Error - Could not set institutional use.")
        },
    )
    def post(self, request, format='json'):
        """
        Update the institutional use data for the authenticated user.
        """
        try:
            user = request.user
            serializer = UserInstitutionalUseSerializer(user, data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        except Exception:
            if settings.DEBUG:
                raise APIException(_("error") % {"error_message": str(traceback.format_exc())})
            raise APIException(_('user_institutional_use_error'))

        return Response(serializer.data)


class AnalysisFunctionsListAPIView(ListAPIView):
    """
    Returns a list of active AnalysisFunctions that are available
    to the authenticated user.
    """
    permission_classes = (IsAuthenticated,)
    serializer_class = AnalysisFunctionSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = AnalysisFunction.objects.filter(
            Q(is_active=True) & (
                    Q(only_for_users__isnull=True) | Q(only_for_users=user)
            ))
        return queryset

    @swagger_auto_schema(
        operation_summary="List active Analysis Functions",
        responses={
            200: openapi.Response("Success - Analysis functions retrieved successfully."),
            403: openapi.Response("Forbidden - Authentication is required.")
        }
    )
    def list(self, request, *args, **kwargs):
        """
        List all active Analysis Functions.
        This method overrides the default list method to provide
        additional documentation.
        """
        return super().list(request, *args, **kwargs)


class InvokeAnalysisFunctionAPIView(APIView):
    """
    Invokes an Analysis Function asynchronously using Celery.
    """
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        operation_summary="Invoke an Analysis Function",
        responses={
            201: openapi.Response("Created - Analysis function created successfully."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Analysis fuction not found.")
        }
    )
    def post(self, request, *args, **kwargs):
        function = get_object_or_404(
            AnalysisFunction, pk=self.kwargs['pk'], is_active=True
        )
        task = invoke_aws_lambda_function.delay(request.user.id, function.id, request.data)
        return Response({'task_id': task.id}, status=201)


class AnalysisFunctionTaskIdAPIView(APIView):
    """
    Returns the Celery task ID for the analysis function associated with the given trial ID.
    """
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        operation_summary="Get Task ID for Analysis Function",
        responses={
            200: openapi.Response("Success - Task ID retrieved successfully."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Analysis function or task ID not found.")
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Retrieve the task ID associated with the given trial ID for the specified AnalysisFunction.
        """
        function = get_object_or_404(
            AnalysisFunction, pk=self.kwargs['pk'], is_active=True
        )
        analysis_result = AnalysisResult.objects.filter(
            function=function, trial_id=kwargs['trial_id']).order_by('-id').first()
        if analysis_result:
            return Response({'task_id': analysis_result.task_id}, status=201)
        raise NotFound('task_id is not found')


class AnalysisResultOnReadyAPIView(APIView):
    """
    Returns the AnalysisResult if it has been processed;
    otherwise, responds with a 202 status, indicating that
    the frontend should wait for completion.
    """
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        operation_summary="Check Analysis Result Status",
        responses={
            202: openapi.Response("Accepted - The analysis result was accepted and is being processed."),
            404: openapi.Response("Not Found - Analysis result not found."),
            403: openapi.Response("Forbidden - Authentication is required.")
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Retrieve the AnalysisResult for a given task ID associated with the authenticated user.
        """
        result = AnalysisResult.objects.filter(
            task_id=self.kwargs["task_id"], user=request.user
        ).first()
        if result and result.state in (
                AnalysisResultState.SUCCESSFULL, AnalysisResultState.FAILED
        ):
            serializer = AnalysisResultSerializer(result)
            dashboard = AnalysisDashboard.objects.filter(
                user=request.user, function_id=result.function_id
            ).first()
            data = serializer.data
            if dashboard:
                data['dashboard_id'] = dashboard.id
            if result.state == AnalysisResultState.FAILED:
                # A fix with partial Result emulation to avoid errors on frontend
                if result.trial:
                    data['result'] = {
                        'trial': TrialSerializer(result.trial).data,
                    }
            return Response(data)
        return Response(status=202)


class AnalysisFunctionsPendingForTrialsAPIView(APIView):
    """
    Returns a list of pending AnalysisResults for trials associated
    with the authenticated user. The response includes a mapping
    of function IDs to the trial IDs that are pending.
    """
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        operation_summary="Get Pending Trials for Analysis Functions",
        responses={
            200: openapi.Response("Success - Pending trials for analysis functionsretrieved successfully."),
            403: openapi.Response("Forbidden - Authentication is required.")
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Retrieve pending AnalysisResults for trials associated
        with the authenticated user.
        """
        from collections import defaultdict
        results = AnalysisResult.objects.filter(
            user=request.user,
            state=AnalysisResultState.PENDING,
        )
        data = defaultdict(list)
        for result in results:
            trial_ids = Trial.objects.filter(
                session_id=result.data['session_id'],
                name__in=result.data['specific_trial_names']).values_list('id', flat=True)
            data[result.function_id] += list(trial_ids)

        return Response(data)


class AnalysisFunctionsStatesForTrialsAPIView(APIView):
    """
    Returns the state of AnalysisResults for trials associated
    with the authenticated user, including task IDs and dashboard IDs.
    Each function ID maps to a dictionary of trial IDs with their states.
    """
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        operation_summary="Get Analysis Function States for Trials",
        responses={
            200: openapi.Response("Success - Analysis results retrieved successfully."),
            403: openapi.Response("Forbidden - Authentication is required.")
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Retrieve the states of AnalysisResults for trials associated
        with the authenticated user.
        """
        from collections import defaultdict
        results = AnalysisResult.objects.filter(user=request.user).order_by('-id')
        data = defaultdict(dict)
        skip_lines = set()

        for result in results:
            # Skip duplicated results. Fetch only newest.
            if (result.function_id, str(result.data)) in skip_lines:
                continue
            dashboard_id = AnalysisDashboard.objects.filter(
                user=request.user,
                function_id=result.function_id,
            ).values_list('id', flat=True).first()
            trial_ids = Trial.objects.filter(
                session_id=result.data['session_id'],
                name__in=result.data['specific_trial_names']).values_list('id', flat=True)
            for t_id in trial_ids:
                data[result.function_id][str(t_id)] = {
                    'state': result.state,
                    'task_id': result.task_id,
                    'dashboard_id': dashboard_id,
                }
                skip_lines.add((result.function_id, str(result.data)))

        return Response(data)


class AnalysisDashboardViewSet(viewsets.ModelViewSet):
    """
    Allows authenticated users to retrieve data from the Analysis Dashboard,
    including both public and private sessions. It includes actions for retrieving detailed
    data related to a specific dashboard.
    """
    serializer_class = AnalysisDashboardSerializer
    permission_classes = [IsPublic | (IsOwner | IsAdmin | IsBackend)]

    def get_queryset(self):
        """
        Retrieve the list of sessions for the current user or public sessions.
        """
        user = self.request.user
        if user.is_authenticated:
            users_have_public_sessions = User.objects.filter(Q(session__public=True) | Q(id=user.id)).distinct()
        else:
            users_have_public_sessions = User.objects.filter(session__public=True).distinct()
        return AnalysisDashboard.objects.filter(user__in=users_have_public_sessions)

    @swagger_auto_schema(
        operation_summary="Get dashboard data",
        responses={
            200: openapi.Response("Success - Analysis dashboard retrieved successfully."),
            403: openapi.Response("Forbidden - Authentication is required."),
            404: openapi.Response("Not Found - Analysis dashboard not found.")
        }
    )
    @action(detail=True)
    def data(self, request, pk):
        """
        Retrieve data for a specific dashboard.
        """
        dashboard = get_object_or_404(AnalysisDashboard, pk=pk)
        if request.user.is_authenticated and request.user == dashboard.user:
            return Response(dashboard.get_available_data())

        return Response(dashboard.get_available_data(
            only_public=True, subject_id=request.GET.get('subject_id'), share_token=request.GET.get('share_token')))

    @swagger_auto_schema(
        operation_summary="List dashboards",
        responses={
            200: openapi.Response("Success - List of analysis dashboard retrieved successfully.")
        }
    )
    def list(self, request):
        queryset = self.get_queryset()
        if self.request.user.is_authenticated:
            queryset = queryset.filter(user=self.request.user)
        else:
            queryset = queryset.none()
        serializer = AnalysisDashboardSerializer(queryset, many=True)
        return Response(serializer.data)
    

    @swagger_auto_schema(
        operation_summary="Create a dashboard",
        request_body=AnalysisDashboardSerializer,
        responses={
            201: openapi.Response('Created - Analysis dashboard created successfully.'),
            400: openapi.Response("Bad Request - Invalid analysis dashboard.")
        }
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new dashboard.
        """
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve a dashboard",
        responses={
            200: openapi.Response("Success - Analysis dashboard retrieved successfully."),
            404: openapi.Response("Not Found - Analysis dashboard not found.")
        }
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a specific dashboard.
        """
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update a dashboard",
        request_body=AnalysisDashboardSerializer,
        responses={
            200: openapi.Response("Success - Analysis dashboard updated successfully."),
            400: openapi.Response("Bad Request - Invalid analysis dashboard."),
            404: openapi.Response("Not Found - Analysis dashboard not found.")
        }
    )
    def update(self, request, *args, **kwargs):
        """
        Update an existing dashboard.
        """
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Partially update a dashboard",
        request_body=AnalysisDashboardSerializer,
        responses={
            200: openapi.Response("Success - Dashboard partially updated successfully."),
            400: openapi.Response("Bad Request - Invalid analysis dashboard."),
            404: openapi.Response("Not Found - Analysis dashboard not found.")
        }
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a dashboard.
        """
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete a dashboard",
        responses={
            204: openapi.Response("Deleted - Analysis dashboard deleted successfully."),
            404: openapi.Response("Not Found - Analysis dashboard not found.")
        }
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a dashboard.
        """
        return super().destroy(request, *args, **kwargs)
