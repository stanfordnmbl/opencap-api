# Generated by Django 3.1.4 on 2022-04-21 05:21

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('mcserver', '0016_auto_20220418_2000'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='reason',
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='status',
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
