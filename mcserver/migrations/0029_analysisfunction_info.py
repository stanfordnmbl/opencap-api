# Generated by Django 3.1.14 on 2024-02-16 09:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0028_user_institutional_use'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisfunction',
            name='info',
            field=models.TextField(blank=True, default='', verbose_name='Info'),
        ),
    ]
