from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0003_client_avis_commercial_client_avis_operationnel'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='is_archived',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
