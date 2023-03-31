from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from mcserver.models import (
    User,
    Session,
    Trial,
    Video,
    Result,
    ResetPassword,
    Subject,
)
from django.contrib.auth.models import Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.admin.models import LogEntry


#admin.site.unregister(Group)
#admin.site.register(Group, GroupAdmin)


@admin.register(User)
class UserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Extras', {
            'fields': (
                'website',
                'institution',
                'profession',
                'country',
                'reason',
                'newsletter',
                'otp_verified',
            )}),
    )


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'subject',
        'public',
        'created_at', 'updated_at', 'server',
        'trashed', 'trashed_at',
    )
    raw_id_fields = ('user', 'subject')
    search_fields = ['id']


@admin.register(Trial)
class TrialAdmin(admin.ModelAdmin):
    search_fields = ['session']
    list_display = (
        'session', 'name',
        'status',
        'created_at', 'updated_at',
        'trashed', 'trashed_at',
    )


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('trial', 'tag', 'media', 'created_at', 'updated_at')
    search_fields = ['trial']


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    search_fields = ['trial']
    list_display = ('trial', 'video', 'created_at', 'updated_at')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    search_fields = ['name']
    list_display = (
        'name', 'user',
        'weight', 'height',
        'age', 'gender', 'sex_at_birth',
        'trashed',
        'created_at', 'updated_at',
    )


@admin.register(ResetPassword)
class ResetPasswordAdmin(admin.ModelAdmin):
    search_field = ['email']
    list_display = ('email', 'id', 'datetime')


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    # to have a date-based drilldown navigation in the admin page
    date_hierarchy = 'action_time'

    # to filter the resultes by users, content types and action flags
    list_filter = [
        'user',
        'content_type',
        'action_flag'
    ]

    # when searching the user will be able to search in both object_repr and change_message
    search_fields = [
        'object_repr',
        'change_message'
    ]

    list_display = [
        'action_time',
        'user',
        'content_type',
        'action_flag',
    ]
