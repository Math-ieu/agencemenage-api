from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
        ('finance', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='entreecaisse',
            name='client',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='mouvements_caisse', to='clients.client'),
        ),
        migrations.AddField(
            model_name='entreecaisse',
            name='client_nom',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='entreecaisse',
            name='document_file',
            field=models.FileField(blank=True, null=True, upload_to='finance/caisse/'),
        ),
        migrations.AddField(
            model_name='entreecaisse',
            name='mode_paiement',
            field=models.CharField(choices=[('especes', 'Espèces'), ('virement', 'Virement'), ('cheque', 'Chèque'), ('paiement_agence', 'Paiement agence')], default='especes', max_length=20),
        ),
        migrations.AddField(
            model_name='entreecaisse',
            name='notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='entreecaisse',
            name='utilisateur',
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
