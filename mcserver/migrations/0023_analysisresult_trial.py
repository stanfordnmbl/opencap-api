# Generated by Django 3.1.14 on 2023-09-20 15:24

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mcserver', '0022_analysisresult_fk_to_result_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisresult',
            name='trial',
            field=models.ForeignKey(blank=True, help_text='Trial function was called with. Set automatically.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='mcserver.trial', verbose_name='Trial'),
        ),
    ]
