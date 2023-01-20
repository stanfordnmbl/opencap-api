from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from mcserver.models import (User, Session, Trial, Video, Result, ResetPassword)
from django.contrib.auth.models import Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin

#admin.site.unregister(Group)
admin.site.register(User, UserAdmin)
#admin.site.register(Group, GroupAdmin)

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at', 'updated_at', 'server')

@admin.register(Trial)
class TrialAdmin(admin.ModelAdmin):
    search_fields = ['session']
    list_display = ('session', 'name', 'status', 'created_at', 'updated_at')

@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('trial', 'tag', 'media', 'created_at', 'updated_at')
    search_fields = ['trial']

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    search_fields = ['trial']
    list_display = ('trial', 'video', 'created_at', 'updated_at')

@admin.register(ResetPassword)
class ResetPasswordAdmin(admin.ModelAdmin):
    search_field = ['email']
    list_display = ('email', 'id', 'datetime')

from django.contrib.admin.models import LogEntry

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
