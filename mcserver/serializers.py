import json
from rest_framework import serializers
from mcserver.models import (
    Session,
    User,
    Video,
    Trial,
    Result,
    Subject,
    AnalysisFunction,
    AnalysisResult,
    AnalysisDashboardTemplate,
    AnalysisDashboard,
)
from rest_framework.validators import UniqueValidator
from django.db.models import Prefetch


class UserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
            required=True,
            validators=[UniqueValidator(queryset=User.objects.all())]
            )
    username = serializers.CharField(
            validators=[UniqueValidator(queryset=User.objects.all())]
            )
    password = serializers.CharField(min_length=8)

    def create(self, validated_data):
        user = User.objects.create_user(validated_data['username'],
                                        validated_data['email'],
                                        validated_data['password'],
                                        first_name=validated_data['first_name'],
                                        last_name=validated_data['last_name'],
                                        institution=validated_data['institution'],
                                        reason=validated_data['reason'],
                                        website=validated_data['website'],
                                        newsletter=validated_data['newsletter'],
                                        profession=validated_data['profession'],
                                        country=validated_data['country']
        )
        
        return user

    class Meta:
        model = User
        fields = (
            'id', 'username', 'first_name', 'last_name',
            'email', 'password', 'institution',
            'reason', 'website',
            'newsletter', 'profession', 'country',
            'institutional_use',
        )


class UserInstitutionalUseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('institutional_use',)


class ResetPasswordSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
            required=True,
            )

    class Meta:
        model = User
        fields = ('email',)

class NewPasswordSerializer(serializers.ModelSerializer):
    password = serializers.CharField(min_length=20,
            required=True,
            )
    token = serializers.CharField(min_length=36,
            required=True
            )

    class Meta:
        model = User
        fields = ('password','token',)

# Serializers define the API representation.
class VideoSerializer(serializers.ModelSerializer):
    video_url = serializers.CharField(max_length=256,
            required=False
            )
    class Meta:
        model = Video
        fields = ['id', 'trial', 'device_id', 'video', 'video_url', 'video_thumb', 'parameters', 'created_at', 'updated_at']

# Serializers define the API representation.
class ResultSerializer(serializers.ModelSerializer):
    media_url = serializers.CharField(max_length=256, required=False)

    class Meta:
        model = Result
        fields = ['id', 'trial', 'tag', 'media', 'media_url', 'meta', 'device_id', 'created_at', 'updated_at']

# Serializers define the API representation.
class TrialSerializer(serializers.ModelSerializer):
    videos = VideoSerializer(source='video_set', many=True)
    results = ResultSerializer(source='result_set', many=True)
    
    class Meta:
        model = Trial
        fields = [
            'id', 'session', 'name', 'status', 'videos',
            'results', 'meta', 'created_at', 'updated_at',
            'trashed', 'trashed_at',
        ]

# Serializers define the API representation.
class SessionSerializer(serializers.ModelSerializer):
#    trials = TrialSerializer(source='trial_set', many=True)
    trials = serializers.SerializerMethodField() #TrialSerializer(source='trial_set', many=True)

    name = serializers.SerializerMethodField('session_name')

    @staticmethod
    def setup_eager_loading(queryset):
        # queryset = queryset.prefetch_related("trial_set").all()
        queryset = queryset.prefetch_related(Prefetch('trial_set', queryset=Trial.objects.order_by('created_at'))).all()

        return queryset

    def get_trials(self, instance):
        trials = instance.trial_set.all()
        return TrialSerializer(trials, many=True).data
    
    def session_name(self, session):
        # Get subject name from the latest static trial
        subject_id = None
        if session.subject:
            subject_id = session.subject.name
        elif session.meta is not None and "subject" in session.meta and "id" in session.meta["subject"]:
            subject_id = session.meta["subject"]["id"] 

        # otherwise return session id
        if subject_id:
            return subject_id
        return str(session.id).split("-")[0]


    class Meta:
        model = Session
        fields = [
            'id', 'user', 'public', 'name',
            'qrcode', 'meta', 'trials', 'server',
            'subject',
            'created_at', 'updated_at',
            'trashed', 'trashed_at',
        ]


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = [
            'id',
            'name',
            'weight',
            'height',
            'age',
            'birth_year',
            'gender',
            'sex_at_birth',
            'characteristics',
            'sessions',
            'created_at',
            'updated_at',
            'trashed',
            'trashed_at'
        ]


class NewSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = [
            'name',
            'weight',
            'height',
            'birth_year',
            'gender',
            'sex_at_birth',
            'characteristics',
        ]

    def to_representation(self, instance):
        serializer = SubjectSerializer(instance)
        return serializer.data


class AnalysisFunctionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisFunction
        fields = ('id', 'title', 'description')


class AnalysisResultSerializer(serializers.ModelSerializer):
    analysis_function = AnalysisFunctionSerializer(source="function")
    result = ResultSerializer()
    response = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisResult
        fields = ('analysis_function', 'result', 'status', 'state', 'response')
    
    def get_response(self, obj):
        """ Returns Result.media content if analysis was successful,
            otherwise returns the original response with error details.
        """
        if obj.result:
            return json.loads(obj.result.media.read())
        return obj.response


class AnalysisDashboardTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisDashboardTemplate
        fields = ('id', 'title', 'function', 'layout')


class AnalysisDashboardSerializer(serializers.ModelSerializer):

    class Meta:
        model = AnalysisDashboard
        fields = ('id', 'title', 'function', 'template', 'layout')
