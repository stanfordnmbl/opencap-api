# Generated by Django 3.1.4 on 2020-12-11 22:52

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0004_auto_20201211_0540'),
    ]

    operations = [
        migrations.RenameField(
            model_name='video',
            old_name='file',
            new_name='video',
        ),
        migrations.AlterField(
            model_name='session',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, db_index=False),
        ),
        migrations.AlterField(
            model_name='video',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, db_index=False),
        ),
    ]
