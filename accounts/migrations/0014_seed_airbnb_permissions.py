from django.db import migrations


NEW_ROLE_PERMISSIONS = {
    "Responsable Facturation": [
        "consulter_clients",
        "consulter_factures",
        "exporter_pdf_excel_facture",
        "editer_facture",
        "modifier_facture",
        "generer_facture",
        "envoi_facture_client",
        "consulter_tresorerie",
        "creer_mouvements_tresorerie",
        "filtrer_tresorerie",
        "mouvements_caisse",
        "consulter_infos_profil",
        "modifier_infos_profil",
        "modifier_mot_de_passe",
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "consulter_commandes_airbnb",
        "consulter_facturation_airbnb",
        "emettre_facture_airbnb",
        "annuler_facture_airbnb",
        "geste_commercial_airbnb",
        "lever_suspension_airbnb",
        "annuler_bascule_mensuelle_airbnb",
        "consulter_audit_airbnb",
    ],
    "Runner": [
        "consulter_infos_profil",
        "modifier_infos_profil",
        "modifier_mot_de_passe",
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "saisir_comptage_linge",
        "gerer_objets_trouves_airbnb",
    ],
    "Responsable Linge": [
        "consulter_infos_profil",
        "modifier_infos_profil",
        "modifier_mot_de_passe",
        "consulter_airbnb",
        "figer_montant_linge",
        "signaler_observation_linge",
        "arbitrer_ecart_linge",
    ],
    "Client Conciergerie": [
        "consulter_infos_profil",
        "modifier_infos_profil",
        "modifier_mot_de_passe",
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "creer_bien_airbnb",
        "consulter_commandes_airbnb",
        "creer_commande_airbnb",
        "consulter_facturation_airbnb",
        "declarer_virement_airbnb",
    ],
}

EXISTING_ROLE_AIRBNB_APPEND = {
    "Admin": [
        "consulter_airbnb",
        "gerer_config_airbnb",
        "consulter_biens_airbnb",
        "creer_bien_airbnb",
        "activer_bien_airbnb",
        "consulter_commandes_airbnb",
        "creer_commande_airbnb",
        "forcer_prix_airbnb",
        "assigner_commande_airbnb",
        "cloturer_commande_airbnb",
        "gerer_signalements_airbnb",
        "gerer_objets_trouves_airbnb",
        "saisir_comptage_linge",
        "figer_montant_linge",
        "signaler_observation_linge",
        "arbitrer_ecart_linge",
        "consulter_facturation_airbnb",
        "emettre_facture_airbnb",
        "annuler_facture_airbnb",
        "geste_commercial_airbnb",
        "lever_suspension_airbnb",
        "annuler_bascule_mensuelle_airbnb",
        "declarer_virement_airbnb",
        "consulter_audit_airbnb",
    ],
    "Responsable commercial": [
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "creer_bien_airbnb",
        "activer_bien_airbnb",
        "consulter_commandes_airbnb",
        "creer_commande_airbnb",
        "forcer_prix_airbnb",
        "gerer_signalements_airbnb",
        "gerer_objets_trouves_airbnb",
        "arbitrer_ecart_linge",
        "consulter_facturation_airbnb",
        "annuler_bascule_mensuelle_airbnb",
        "consulter_audit_airbnb",
    ],
    "commercial": [
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "creer_bien_airbnb",
        "consulter_commandes_airbnb",
        "creer_commande_airbnb",
        "gerer_signalements_airbnb",
        "gerer_objets_trouves_airbnb",
        "consulter_facturation_airbnb",
    ],
    "Chargée des Opérations": [
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "consulter_commandes_airbnb",
        "assigner_commande_airbnb",
        "cloturer_commande_airbnb",
        "gerer_signalements_airbnb",
        "gerer_objets_trouves_airbnb",
        "arbitrer_ecart_linge",
    ],
    "Responsable des Opérations": [
        "consulter_airbnb",
        "consulter_biens_airbnb",
        "consulter_commandes_airbnb",
        "assigner_commande_airbnb",
        "cloturer_commande_airbnb",
        "gerer_signalements_airbnb",
        "gerer_objets_trouves_airbnb",
        "arbitrer_ecart_linge",
        "consulter_audit_airbnb",
    ],
}

ALL_AIRBNB_KEYS = set(EXISTING_ROLE_AIRBNB_APPEND["Admin"])


def seed_airbnb_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')

    for role_name, perms_list in NEW_ROLE_PERMISSIONS.items():
        rp, created = RolePermission.objects.get_or_create(
            role=role_name,
            defaults={'permissions': list(perms_list)},
        )
        if not created:
            existing = list(rp.permissions or [])
            changed = False
            for perm in perms_list:
                if perm not in existing:
                    existing.append(perm)
                    changed = True
            if changed:
                rp.permissions = existing
                rp.save(update_fields=['permissions'])

    for role_name, perms_to_append in EXISTING_ROLE_AIRBNB_APPEND.items():
        rp = RolePermission.objects.filter(role=role_name).first()
        if not rp:
            continue
        existing = list(rp.permissions or [])
        changed = False
        for perm in perms_to_append:
            if perm not in existing:
                existing.append(perm)
                changed = True
        if changed:
            rp.permissions = existing
            rp.save(update_fields=['permissions'])


def unseed_airbnb_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')

    RolePermission.objects.filter(role__in=list(NEW_ROLE_PERMISSIONS.keys())).delete()

    for role_name in EXISTING_ROLE_AIRBNB_APPEND.keys():
        rp = RolePermission.objects.filter(role=role_name).first()
        if not rp:
            continue
        existing = list(rp.permissions or [])
        filtered = [p for p in existing if p not in ALL_AIRBNB_KEYS]
        if len(filtered) != len(existing):
            rp.permissions = filtered
            rp.save(update_fields=['permissions'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_user_client_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(seed_airbnb_permissions, reverse_code=unseed_airbnb_permissions),
    ]
