# Generated by Django 3.1.14 on 2023-05-25 10:00

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import mcserver.models


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0014_user_otp_skip_till'),
    ]

    operations = [
        migrations.CreateModel(
            name='DownloadLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(max_length=255)),
                ('media', models.FileField(max_length=500, upload_to=mcserver.models.archives_dir_path)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
