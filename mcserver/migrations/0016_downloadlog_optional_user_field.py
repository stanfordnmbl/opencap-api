# Generated by Django 3.1.14 on 2023-06-06 06:27

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0015_downloadlog_model'),
    ]

    operations = [
        migrations.AlterField(
            model_name='downloadlog',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
