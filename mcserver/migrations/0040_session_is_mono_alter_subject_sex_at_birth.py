# Generated by Django 4.2.22 on 2025-06-05 21:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0039_merge_20241008_1623'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='is_mono',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='subject',
            name='sex_at_birth',
            field=models.CharField(blank=True, choices=[('woman', 'Female'), ('man', 'Male'), ('intersect', 'Intersex'), ('not-listed', 'Not Listed'), ('prefer-not-respond', 'Prefer Not to Respond')], max_length=20, null=True),
        ),
    ]
