from django import forms
from .models import Subject


class SubjectChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} ({obj.weight} Kg, {obj.height} m, {obj.age} years) [{obj.user}]'


class SubjectSelectForm(forms.Form):
    subject = SubjectChoiceField(queryset=Subject.objects.exclude(trashed=True))
