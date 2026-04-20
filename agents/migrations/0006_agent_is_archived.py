from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0005_alter_agent_poste_alter_agent_statut'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='is_archived',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
