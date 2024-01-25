from django.contrib import admin
from django.shortcuts import render, redirect
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from mcserver.models import (
    User,
    Session,
    Trial,
    Video,
    Result,
    ResetPassword,
    Subject,
    DownloadLog,
    AnalysisFunction,
    AnalysisResult,
    AnalysisDashboardTemplate,
    AnalysisDashboard,
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
                'otp_skip_till',
            )}),
    )


class TrialInline(admin.TabularInline):
    model = Trial
    extra = 0


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
    inlines = [TrialInline]
    actions = ['set_subject']

    def set_subject(self, request, queryset):
        from .forms import SubjectSelectForm

        form = SubjectSelectForm()
        if request.method == 'POST' and 'apply' in request.POST:
            form = SubjectSelectForm(request.POST)
            if form.is_valid():
                subject = form.cleaned_data['subject']
                for obj in queryset:
                    obj.subject = subject
                    obj.save()
                self.message_user(request, f'Subject set to {subject}')
                return redirect(request.get_full_path())

        opts = self.model._meta
        context = self.admin_site.each_context(request)
        context.update({
            'opts': opts,
            'form': form,
            'objects': queryset,
        })
        return render(request, 'admin/set_subject.html', context)


class ResultInline(admin.TabularInline):
    model = Result
    extra = 0


@admin.register(Trial)
class TrialAdmin(admin.ModelAdmin):
    search_fields = ['id', 'session_id']
    list_display = (
        'id',
        'name',
        'session',
        'status',
        'created_at', 'updated_at',
        'trashed', 'trashed_at',
    )
    raw_id_fields = ('session',)
    inlines = [ResultInline]


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'trial', 'tag', 'media',
        'device_id',
        'created_at', 'updated_at')
    search_fields = ['trial']
    raw_id_fields = ('trial',)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    search_fields = ['trial']
    list_display = ('trial', 'video', 'created_at', 'updated_at')
    raw_id_fields = ('trial',)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    search_fields = ['name']
    list_display = (
        'id',
        'name',
        'user',
        'weight',
        'height',
        'age',
        'birth_year',
        'gender',
        'sex_at_birth',
        'trashed',
        'created_at',
        'updated_at',
    )
    raw_id_fields = ('user',)


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


@admin.register(DownloadLog)
class DownloadLogAdmin(admin.ModelAdmin):
    list_display = ['id', "task_id", "user", "created_at", "updated_at"]
    search_fields = ["task_id"]
    raw_id_fields = ["user"]


@admin.register(AnalysisFunction)
class AnalysisFunctionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'title', 'is_active',
        'only_for_users_display',
        'local_run', 'created_at']
    search_fields = ['title', 'description']
    raw_id_fields = ['only_for_users']

    def only_for_users_display(self, obj):
        return ", ".join([str(u) for u in obj.only_for_users.all()])


@admin.register(AnalysisResult)
class AnalysisResultAdmin(admin.ModelAdmin):
    list_display = ['id', 'task_id', 'user', 'function', 'status', 'state', "created_at", "updated_at"]
    list_filter = ['function', 'state']
    raw_id_fields = ['user', 'trial', 'result']
    search_fields = ['id', 'task_id']


@admin.register(AnalysisDashboardTemplate)
class AnalysisDashboardTemplateAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'function', 'created_at', 'updated_at']
    search_fields = ['title']


@admin.register(AnalysisDashboard)
class AnalysisDashboardAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'function', 'user', 'template', 'created_at', 'updated_at']
    search_fields = ['title']
    raw_id_fields = ['user', 'template']
