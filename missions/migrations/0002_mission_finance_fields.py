from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('missions', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='mission',
            name='date_paiement',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='mission',
            name='date_remise_agence',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='mission',
            name='date_versement_profil',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='mission',
            name='encaisse_par',
            field=models.CharField(choices=[('agence', 'Agence'), ('profil', 'Profil')], default='agence', max_length=10),
        ),
        migrations.AddField(
            model_name='mission',
            name='justificatif_financier',
            field=models.FileField(blank=True, null=True, upload_to='missions/finance/'),
        ),
        migrations.AddField(
            model_name='mission',
            name='mode_paiement_reel',
            field=models.CharField(blank=True, choices=[('virement', 'Virement'), ('cheque', 'Chèque'), ('especes_agence', "Espèces à l'agence"), ('sur_place', 'Sur place')], max_length=20),
        ),
        migrations.AddField(
            model_name='mission',
            name='montant_encaisse_profil',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='mission',
            name='montant_paye',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='mission',
            name='paiement_client_statut',
            field=models.CharField(choices=[('non_paye', 'Non payé'), ('en_attente', 'Paiement en attente'), ('effectue', 'Paiement effectué')], default='non_paye', max_length=20),
        ),
        migrations.AddField(
            model_name='mission',
            name='part_agence_reversee',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='mission',
            name='part_profil_versee',
            field=models.BooleanField(default=False),
        ),
    ]
