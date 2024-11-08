# Generated by Django 3.2 on 2024-09-19 23:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0035_auto_20240918_2354'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='trial',
            name='docker',
        ),
        migrations.AddField(
            model_name='trial',
            name='hostname',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='trial',
            name='is_docker',
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
