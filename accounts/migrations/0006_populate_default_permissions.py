from django.db import migrations

def populate_default_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    
    DEFAULT_PERMISSIONS = {
        "Admin": [
            "consulter_dashboard", "consulter_compte_client_dashboard", "editer_besoin", "confirmation_avant_operation", "supprimer_demande_dashboard", "facturation_annulee", "annulation_demande", "note_operationnelle_dashboard", "note_commerciale_dashboard", "assigner_charge_operation", "application_taux_horaire_standard", "taux_horaire_exceptionnel", "taux_forfaitaire",
            "creer_demande", "creer_devis", "modifier_demande", "consulter_demandes", "affecter_commercial", "valider_demandes", "refuser_demande",
            "consulter_agents", "consulter_docs_confidentiels", "creer_agents", "modifier_agents", "desactiver_profil", "blacklister_agents", "supprimer_profil",
            "consulter_clients", "consulter_compte_client", "affectation_client", "note_operationnelle", "note_commerciale", "geste_commercial", "modifier_clients", "blacklister_clients", "delete_client",
            "consulter_historique_global", "filtrer_historique", "exporter_historique_csv",
            "voir_la_caisse", "consulter_debit", "valider_paiement_debit", "filtrer_debit", "consulter_credit", "valider_paiement_credit", "filtrer_credit", "consulter_factures", "exporter_pdf_excel_facture", "editer_facture", "modifier_facture", "editer_besoin_facture", "generer_facture", "envoi_facture_client", "consulter_comptes_profil",
            "consulter_solde_caisse", "mouvements_caisse", "sorties_caisse", "cloturer_caisse_journaliere",
            "consulter_marketing", "creer_code_promo", "creer_geste_commercial", "creer_campagne",
            "consulter_retours_qualite", "repondre_avis_clients", "moderer_masquer_avis", "generer_rapports_qualite",
            "rediger_blog", "modifier_articles_blog", "publier_articles_blog",
            "consulter_infos_profil", "modifier_infos_profil", "modifier_mot_de_passe", "activer_mfa",
            "consulter_utilisateurs", "creer_utilisateurs", "parametres_globaux", "activer_desactiver_utilisateurs"
        ],
        "Moderateur": [
            "consulter_dashboard", "consulter_compte_client_dashboard", "editer_besoin", "confirmation_avant_operation", "supprimer_demande_dashboard", "facturation_annulee", "annulation_demande", "note_operationnelle_dashboard", "note_commerciale_dashboard", "assigner_charge_operation", "application_taux_horaire_standard", "taux_horaire_exceptionnel", "taux_forfaitaire",
            "creer_demande", "creer_devis", "modifier_demande", "consulter_demandes", "affecter_commercial", "valider_demandes", "refuser_demande",
            "consulter_agents", "consulter_docs_confidentiels", "creer_agents", "modifier_agents", "desactiver_profil", "blacklister_agents", "supprimer_profil",
            "consulter_clients", "consulter_compte_client", "affectation_client", "note_operationnelle", "note_commerciale", "geste_commercial", "modifier_clients", "blacklister_clients", "delete_client",
            "consulter_historique_global", "filtrer_historique", "exporter_historique_csv",
            "voir_la_caisse", "consulter_debit", "valider_paiement_debit", "filtrer_debit", "consulter_credit", "valider_paiement_credit", "filtrer_credit", "consulter_factures", "exporter_pdf_excel_facture", "editer_facture", "modifier_facture", "editer_besoin_facture", "generer_facture", "envoi_facture_client", "consulter_comptes_profil",
            "consulter_solde_caisse", "mouvements_caisse", "sorties_caisse", "cloturer_caisse_journaliere",
            "consulter_marketing", "creer_code_promo", "creer_geste_commercial", "creer_campagne",
            "consulter_retours_qualite", "repondre_avis_clients", "moderer_masquer_avis", "generer_rapports_qualite",
            "rediger_blog", "modifier_articles_blog", "publier_articles_blog",
            "consulter_infos_profil", "modifier_infos_profil", "modifier_mot_de_passe", "activer_mfa",
            "consulter_utilisateurs", "creer_utilisateurs", "parametres_globaux", "activer_desactiver_utilisateurs"
        ],
        "Responsable commercial": [
            "consulter_dashboard", "consulter_compte_client_dashboard", "editer_besoin", "confirmation_avant_operation", "supprimer_demande_dashboard", "facturation_annulee", "annulation_demande", "note_operationnelle_dashboard", "note_commerciale_dashboard", "application_taux_horaire_standard", "taux_horaire_exceptionnel", "taux_forfaitaire",
            "creer_demande", "creer_devis", "modifier_demande", "consulter_demandes", "affecter_commercial", "valider_demandes", "refuser_demande",
            "consulter_agents",
            "consulter_clients", "consulter_compte_client", "affectation_client", "note_operationnelle", "note_commerciale", "geste_commercial", "modifier_clients", "blacklister_clients",
            "consulter_historique_global", "filtrer_historique", "exporter_historique_csv",
            "voir_la_caisse", "consulter_debit", "valider_paiement_debit", "filtrer_debit", "consulter_credit", "valider_paiement_credit", "filtrer_credit", "consulter_factures", "exporter_pdf_excel_facture", "editer_facture", "modifier_facture", "editer_besoin_facture", "generer_facture", "envoi_facture_client", "consulter_comptes_profil",
            "consulter_solde_caisse", "mouvements_caisse", "sorties_caisse", "cloturer_caisse_journaliere",
            "consulter_marketing", "creer_code_promo", "creer_geste_commercial", "creer_campagne",
            "consulter_retours_qualite", "repondre_avis_clients",
            "rediger_blog",
            "consulter_infos_profil", "modifier_infos_profil", "modifier_mot_de_passe", "activer_mfa"
        ],
        "commercial": [
            "consulter_dashboard", "consulter_compte_client_dashboard", "editer_besoin", "confirmation_avant_operation", "supprimer_demande_dashboard", "facturation_annulee", "annulation_demande", "note_operationnelle_dashboard", "note_commerciale_dashboard",
            "creer_demande", "creer_devis", "modifier_demande", "consulter_demandes", "affecter_commercial", "valider_demandes", "refuser_demande",
            "consulter_agents", "consulter_docs_confidentiels", "creer_agents", "modifier_agents", "desactiver_profil", "blacklister_agents", "supprimer_profil",
            "consulter_clients", "consulter_compte_client", "affectation_client", "note_operationnelle", "note_commerciale", "geste_commercial", "modifier_clients", "blacklister_clients", "delete_client",
            "consulter_historique_global", "filtrer_historique", "exporter_historique_csv",
            "consulter_factures", "editer_besoin_facture",
            "mouvements_caisse",
            "consulter_marketing",
            "consulter_retours_qualite",
            "consulter_infos_profil", "modifier_infos_profil", "modifier_mot_de_passe", "activer_mfa"
        ],
        "Responsable des Opérations": [
            "consulter_dashboard", "consulter_compte_client_dashboard", "editer_besoin", "confirmation_avant_operation", "supprimer_demande_dashboard", "facturation_annulee", "annulation_demande", "note_operationnelle_dashboard", "note_commerciale_dashboard", "assigner_charge_operation", "application_taux_horaire_standard",
            "creer_demande", "consulter_demandes", "valider_demandes",
            "consulter_agents", "consulter_docs_confidentiels", "creer_agents", "modifier_agents", "desactiver_profil", "blacklister_agents",
            "consulter_clients", "consulter_compte_client", "note_operationnelle",
            "consulter_historique_global", "filtrer_historique", "exporter_historique_csv",
            "voir_la_caisse", "consulter_debit", "filtrer_debit", "consulter_credit", "valider_paiement_credit", "filtrer_credit", "consulter_factures", "consulter_comptes_profil",
            "consulter_solde_caisse", "sorties_caisse",
            "consulter_marketing",
            "consulter_retours_qualite", "generer_rapports_qualite",
            "consulter_infos_profil", "modifier_infos_profil", "modifier_mot_de_passe", "activer_mfa"
        ],
        "Chargée des Opérations": [
            "consulter_dashboard", "consulter_compte_client_dashboard", "editer_besoin", "confirmation_avant_operation", "supprimer_demande_dashboard", "facturation_annulee", "annulation_demande", "note_operationnelle_dashboard", "note_commerciale_dashboard",
            "creer_demande", "consulter_demandes",
            "consulter_agents", "consulter_docs_confidentiels",
            "consulter_clients", "consulter_compte_client", "note_operationnelle",
            "consulter_historique_global", "filtrer_historique",
            "consulter_comptes_profil",
            "consulter_marketing",
            "consulter_retours_qualite",
            "consulter_infos_profil", "modifier_infos_profil", "modifier_mot_de_passe", "activer_mfa"
        ],
        "Opérationnel": [
            "consulter_dashboard",
            "consulter_demandes"
        ]
    }
    
    for role, perms in DEFAULT_PERMISSIONS.items():
        RolePermission.objects.update_or_create(
            role=role,
            defaults={'permissions': perms}
        )

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_rolepermission'),
    ]

    operations = [
        migrations.RunPython(populate_default_permissions),
    ]
