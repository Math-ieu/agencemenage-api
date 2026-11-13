from django.utils import timezone


def check_and_lift_client_suspension(client, user=None):
    """
    Vérifie si un client Airbnb n'a plus aucune facture échue impayée.
    Si tel est le cas et qu'il était suspendu, lève automatiquement sa suspension,
    marque ses commandes futures annulées par suspension comme réactivables,
    et enregistre l'action dans le JournalAuditAirbnb.
    """
    if client is None:
        return {'lifted': False, 'reason': 'no_client', 'reactivable_count': 0}

    from finance.models import Facture
    from airbnb.models import CommandeAirbnb, JournalAuditAirbnb

    today = timezone.localdate()
    has_overdue = Facture.objects.filter(
        client=client,
        source=Facture.SOURCE_AIRBNB,
        statut__in=[Facture.EN_ATTENTE, Facture.PARTIEL],
        date_echeance__lt=today,
    ).exists()

    if has_overdue:
        return {'lifted': False, 'reason': 'overdue_invoices_remaining', 'reactivable_count': 0}

    was_suspended = (client.statut_airbnb == 'suspendu')
    reactivable_count = CommandeAirbnb.objects.filter(
        bien__client=client,
        statut='annulee',
        annulee_par_suspension=True,
        date_prestation__gte=today,
        reactivable_apres_suspension=False,
    ).update(reactivable_apres_suspension=True)

    if was_suspended:
        client.statut_airbnb = 'actif'
        client.save(update_fields=['statut_airbnb'])
        JournalAuditAirbnb.objects.create(
            entite='Client',
            entite_id=str(client.id),
            action='suspension_levee_automatique',
            user=user,
            motif="Aucune facture Airbnb échue impayée restante après encaissement",
            valeur_avant={'statut_airbnb': 'suspendu'},
            valeur_apres={
                'statut_airbnb': 'actif',
                'commandes_reactivables': reactivable_count,
            },
        )

    return {
        'lifted': was_suspended,
        'reason': 'lifted' if was_suspended else 'already_active',
        'reactivable_count': reactivable_count,
    }
