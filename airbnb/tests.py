import re
from decimal import Decimal
from datetime import date, time, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from agents.models import Agent
from clients.models import Client
from demandes.models import AppNotification, Demande, SubscriptionPlanning
from finance.models import EntreeCaisse, Facture
from missions.models import Mission

from .models import (
    AirbnbConfig,
    Bien,
    CommandeAirbnb,
    FactureLigneAirbnb,
    FiletLinge,
    GrilleTarifaireVersion,
    JournalAuditAirbnb,
    ObjetTrouve,
    ObservationLinge,
    SignalementCommande,
)
from .services.billing_engine import (
    annuler_bascule_mensuelle,
    annuler_facture,
    appliquer_geste_commercial,
    appliquer_reduction_partielle,
    enregistrer_paiement,
    generer_facture_passage,
    generer_factures_cycle,
    is_commande_facturable,
    preview_calendrier_facturation,
    verifier_suspensions_et_relances,
)
from .services.codification_service import compute_client_trigramme, generate_bien_code, get_ville_trigramme
from .services.ical_service import confirmer_proposition, rejeter_proposition, sync_bien_ical_turnovers
from .services.linen_engine import (
    arbitrer_ecart_filet,
    calculate_linen_pieces_and_amount,
    compter_runner,
    confirmer_retrait_bureau,
    contester_retrait_bureau,
    freeze_laundry_filet,
    recevoir_laverie,
    toggle_observation_facturation,
    transmettre_observation_client,
)
from .services.pdf_service import generate_facture_airbnb_pdf, generate_fiche_mission_pdf
from .services.pricing_engine import (
    calculate_commande_pricing,
    check_cutoff_constraint,
    create_grille_tarifaire_version,
    forcer_prix_commande,
    normalize_commande_options,
    verifier_seuil_client,
)


def _make_user(username, role, **extra):
    return User.objects.create_user(
        username=username,
        email=f'{username}@agencemenage.test',
        password='TestPassword123!',
        role=role,
        first_name=extra.pop('first_name', username.capitalize()),
        last_name=extra.pop('last_name', 'Test'),
        **extra,
    )


class Section12CodificationAndBiensTests(APITestCase):
    def setUp(self):
        self.admin = _make_user('adm_s12', 'admin')
        self.rc = _make_user('rc_s12', 'responsable_commercial')
        self.com = _make_user('com_s12', 'commercial')
        self.ghali = Client.objects.create(
            first_name='Ghali',
            last_name='BENSOUDA',
            phone='0600110001',
            segment='particulier',
            type_client_airbnb='conciergerie',
            assigned_commercial=self.com,
        )
        self.portal_ghali = _make_user('portal_ghali', 'client_conciergerie', client=self.ghali)

    def test_codification_and_collision_and_immutability(self):
        # Ghali BENSOUDA -> GBE, 4e bien -> GBE004
        for idx in range(1, 4):
            Bien.objects.create(
                code=generate_bien_code(self.ghali),
                client=self.ghali,
                quartier='Maarif',
                adresse=f'Rue {idx}',
                typologie='1ch',
            )
        code4 = generate_bien_code(self.ghali)
        self.assertEqual(code4, 'GBE004')
        self.assertEqual(self.ghali.trigramme, 'GBE')

        # Si on supprime GBE002, le prochain reste GBE005 (jamais réattribué)
        Bien.objects.create(code=code4, client=self.ghali, quartier='Maarif', adresse='Rue 4', typologie='1ch')
        Bien.objects.filter(code='GBE002').delete()
        self.assertEqual(generate_bien_code(self.ghali), 'GBE005')

        # Collision : Ghita BENJELLOUN quand GBE existe -> repli 1ère + 3ème lettres du nom = GBN
        ghita = Client.objects.create(
            first_name='Ghita',
            last_name='BENJELLOUN',
            phone='0600110002',
            segment='particulier',
            type_client_airbnb='conciergerie',
        )
        self.assertEqual(compute_client_trigramme(ghita), 'GBN')
        self.assertEqual(generate_bien_code(ghita), 'GBN001')

        # Immutabilité : renommer le client ne change jamais son trigramme
        self.ghali.last_name = 'ALAOUI'
        self.ghali.save()
        self.assertEqual(compute_client_trigramme(self.ghali), 'GBE')

        # Codes villes
        self.assertEqual(get_ville_trigramme('Casablanca'), 'CAS')
        self.assertEqual(get_ville_trigramme('Rabat'), 'RAB')
        self.assertEqual(get_ville_trigramme('Marrakech'), 'MAR')

    def test_seuil_3_biens_upgrade_et_preavis_m_plus_1(self):
        # Client avec 2 biens vérifiés -> tarif standard 240 DH / 4h
        b1 = Bien.objects.create(code='GBE001', client=self.ghali, quartier='Maarif', adresse='A1', typologie='1ch')
        b2 = Bien.objects.create(code='GBE002', client=self.ghali, quartier='Maarif', adresse='A2', typologie='1ch')
        verifier_seuil_client(self.ghali, today=date(2026, 6, 1))
        self.ghali.refresh_from_db()
        self.assertFalse(self.ghali.eligible_conciergerie)
        p_sous_seuil = calculate_commande_pricing(b1)
        self.assertEqual(p_sous_seuil['prix_menage'], 240.0)
        self.assertTrue(p_sous_seuil['tarif_repli_applique'])

        # Ajout du 3e bien -> bascule immédiate à conciergerie (130 DH)
        Bien.objects.create(code='GBE003', client=self.ghali, quartier='Maarif', adresse='A3', typologie='1ch')
        verifier_seuil_client(self.ghali, today=date(2026, 6, 5))
        self.ghali.refresh_from_db()
        self.assertTrue(self.ghali.eligible_conciergerie)
        self.assertEqual(self.ghali.type_client_airbnb, 'conciergerie')
        self.assertEqual(calculate_commande_pricing(b1)['prix_menage'], 130.0)

        # Passage de 3 à 2 biens -> tarif préférentiel conservé le mois M + préavis 15j
        self.client.force_authenticate(user=self.rc)
        resp_desact = self.client.post(f'/api/airbnb/biens/{b2.id}/desactiver/')
        self.assertEqual(resp_desact.status_code, status.HTTP_200_OK)
        self.ghali.refresh_from_db()
        self.assertTrue(self.ghali.eligible_conciergerie)
        self.assertIsNotNone(self.ghali.reclassement_preavis_envoye_le)
        self.assertEqual(calculate_commande_pricing(b1)['prix_menage'], 130.0)

        # À M+1 (>= 15 jours après préavis) via commande cron -> bascule 240 DH
        future_date = self.ghali.reclassement_preavis_envoye_le + timedelta(days=32)
        call_command('verifier_seuil_conciergerie', date=future_date.isoformat())
        self.ghali.refresh_from_db()
        self.assertFalse(self.ghali.eligible_conciergerie)
        self.assertEqual(self.ghali.type_client_airbnb, 'particulier')
        self.assertEqual(calculate_commande_pricing(b1)['prix_menage'], 240.0)

    def test_rabat_menage_uniquement_et_zone_bouskoura_auto_et_validation_portail(self):
        self.client.force_authenticate(user=self.rc)
        # Rabat avec linge refusé
        bad_rabat = self.client.post('/api/airbnb/biens/', {
            'client': self.ghali.id,
            'ville': 'Rabat',
            'quartier': 'Agdal',
            'adresse': 'Av France',
            'typologie': '2ch',
            'services_souscrits': ['menage', 'linge'],
        }, format='json')
        self.assertEqual(bad_rabat.status_code, status.HTTP_400_BAD_REQUEST)

        # Rabat avec ménage seul OK
        ok_rabat = self.client.post('/api/airbnb/biens/', {
            'client': self.ghali.id,
            'ville': 'Rabat',
            'quartier': 'Agdal',
            'adresse': 'Av France',
            'typologie': '2ch',
            'services_souscrits': ['menage'],
        }, format='json')
        self.assertEqual(ok_rabat.status_code, status.HTTP_201_CREATED)
        rabat_id = ok_rabat.data['id']

        # Commande avec linge ou ramassage à Rabat refusée
        tomorrow = (timezone.localdate() + timedelta(days=2)).isoformat()
        bad_cmd = self.client.post('/api/airbnb/commandes/', {
            'bien': rabat_id,
            'date_prestation': tomorrow,
            'heure_prestation': '14:00',
            'creneau': 'apres_midi',
            'nature_linge': 'depot_ramassage',
        }, format='json')
        self.assertEqual(bad_cmd.status_code, status.HTTP_400_BAD_REQUEST)

        # Commande ménage sans linge à Rabat acceptée
        ok_cmd = self.client.post('/api/airbnb/commandes/', {
            'bien': rabat_id,
            'date_prestation': tomorrow,
            'heure_prestation': '14:00',
            'creneau': 'apres_midi',
            'nature_linge': 'sans_linge',
        }, format='json')
        self.assertEqual(ok_cmd.status_code, status.HTTP_201_CREATED)

        # Bien à Bouskoura -> zone_eloignee=True et +50 DH détectés automatiquement
        bouskoura = self.client.post('/api/airbnb/biens/', {
            'client': self.ghali.id,
            'ville': 'Casablanca',
            'quartier': 'Bouskoura',
            'adresse': 'Ville Verte Lot 12',
            'typologie': '2ch',
        }, format='json')
        self.assertEqual(bouskoura.status_code, status.HTTP_201_CREATED)
        self.assertTrue(bouskoura.data['zone_eloignee'])
        pricing_bouskoura = calculate_commande_pricing(Bien.objects.get(id=bouskoura.data['id']))
        self.assertEqual(pricing_bouskoura['supplement_zone'], 50.0)

        # Portail conciergerie crée un bien en 'en_validation' jusqu'à activation R.C.
        self.client.force_authenticate(user=self.portal_ghali)
        portal_bien = self.client.post('/api/airbnb/biens/', {
            'client': self.ghali.id,
            'ville': 'Casablanca',
            'quartier': 'Anfa',
            'adresse': 'Bd d\'Anfa',
            'typologie': 'studio',
        }, format='json')
        self.assertEqual(portal_bien.status_code, status.HTTP_201_CREATED)
        self.assertEqual(portal_bien.data['statut_activation'], 'en_validation')
        self.assertFalse(portal_bien.data['is_active'])

        self.client.force_authenticate(user=self.rc)
        act = self.client.post(f"/api/airbnb/biens/{portal_bien.data['id']}/activer/")
        self.assertEqual(act.status_code, status.HTTP_200_OK)
        self.assertEqual(act.data['statut_activation'], 'actif')
        self.assertTrue(act.data['is_active'])


class Section12LinenTests(APITestCase):
    def setUp(self):
        self.rl = _make_user('rl_s12', 'responsable_linge')
        self.com = _make_user('com_linge', 'commercial')
        self.ops = _make_user('ops_linge', 'responsable_operations')
        self.rf = _make_user('rf_linge', 'responsable_facturation')
        self.client_obj = Client.objects.create(
            first_name='Youssef', last_name='Bennani', phone='0600220001',
            type_client_airbnb='conciergerie', eligible_conciergerie=True,
            assigned_commercial=self.com,
        )
        self.runner = _make_user('runner_s12', 'runner')
        self.bien = Bien.objects.create(
            code='YBE001', client=self.client_obj, quartier='Gauthier',
            adresse='Rue 1', typologie='2ch',
        )
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.cmd_ram = CommandeAirbnb.objects.create(
            numero='CMD-2026-S12-R', bien=self.bien, date_prestation=tomorrow,
            nature_linge='ramassage_seul', runner=self.runner, statut='cloturee',
            photos_cloture=['p1', 'p2', 'p3', 'p4'],
        )
        self.cmd_dep = CommandeAirbnb.objects.create(
            numero='CMD-2026-S12-D', bien=self.bien, date_prestation=tomorrow + timedelta(days=1),
            nature_linge='depot_seul', runner=self.runner, statut='saisie',
        )

    def test_conversion_sets_et_minimum_50dh_section_12_2(self):
        # 2 housses, 2 draps, 3 taies, 4 gdes serv, 4 ptes serv, 1 tapis -> 1 set + 8 pièces = 90 DH
        r1 = calculate_linen_pieces_and_amount({
            'housses': 2, 'draps': 2, 'taies': 3,
            'grandes_serviettes': 4, 'petites_serviettes': 4, 'tapis_bain': 1,
        })
        self.assertEqual(r1['nb_sets_complets'], 1)
        self.assertEqual(r1['nb_pieces_hors_set'], 8)
        self.assertEqual(r1['montant_total'], 90.0)
        self.assertEqual(r1['article_limitant'], 'taies')

        # 1 housse, 1 drap, 2 taies, 2 gdes, 2 ptes -> 1 set + 0 pièce = 50 DH
        r2 = calculate_linen_pieces_and_amount({
            'housses': 1, 'draps': 1, 'taies': 2,
            'grandes_serviettes': 2, 'petites_serviettes': 2,
        })
        self.assertEqual(r2['nb_sets_complets'], 1)
        self.assertEqual(r2['nb_pieces_hors_set'], 0)
        self.assertEqual(r2['montant_total'], 50.0)

        # 3 pièces dépareillées -> 15 DH calculés -> 50 DH facturés (minimum)
        r3 = calculate_linen_pieces_and_amount({'draps': 3})
        self.assertEqual(r3['nb_sets_complets'], 0)
        self.assertEqual(r3['montant_brut'], 15.0)
        self.assertTrue(r3['forfait_minimum_applique'])
        self.assertEqual(r3['montant_total'], 50.0)

        # 0 pièce -> 0 DH
        r4 = calculate_linen_pieces_and_amount({})
        self.assertEqual(r4['montant_total'], 0.0)
        self.assertFalse(r4['forfait_minimum_applique'])

        # 2 housses, 2 draps, 4 taies, 4 gdes, 4 ptes -> 2 sets + 0 pièce = 100 DH
        r5 = calculate_linen_pieces_and_amount({
            'housses': 2, 'draps': 2, 'taies': 4,
            'grandes_serviettes': 4, 'petites_serviettes': 4,
        })
        self.assertEqual(r5['nb_sets_complets'], 2)
        self.assertEqual(r5['nb_pieces_hors_set'], 0)
        self.assertEqual(r5['montant_total'], 100.0)

    def test_ecart_tolerance_zero_arbitrage_figeage_immuable_et_observations(self):
        filet = FiletLinge.objects.create(
            code_filet='SAC-YBE001-01',
            bien=self.bien,
            commande_ramassage=self.cmd_ram,
            commande_depot=self.cmd_dep,
        )
        # Moment 1 : retrait bureau & contestation
        confirmer_retrait_bureau(filet, self.runner)
        self.assertIsNotNone(filet.retire_bureau_confirme_le)
        contester_retrait_bureau(filet, 2, "Manque 2 taies dans le sac propre", self.runner)
        self.assertTrue(filet.retire_bureau_conteste)

        # Moment 2 : Runner annonce 17 pièces et remplissage > 60%
        res_run = compter_runner(
            filet,
            {'housses': 2, 'draps': 2, 'taies': 3, 'grandes_serviettes': 5, 'petites_serviettes': 5},
            user=self.runner,
            remplissage_pct=75,
        )
        self.assertEqual(res_run['total_runner'], 17)
        self.assertTrue(res_run['necessite_second_filet'])

        # Moment 3 : Laverie recompte 16 pièces -> Écart -1, blocage figeage
        res_lav = recevoir_laverie(
            filet,
            {'housses': 2, 'draps': 2, 'taies': 3, 'grandes_serviettes': 5, 'petites_serviettes': 4},
            user=self.rl,
        )
        self.assertTrue(res_lav['ecart_detecte'])
        self.assertEqual(res_lav['ecart'], -1)
        self.cmd_ram.refresh_from_db()
        self.assertEqual(self.cmd_ram.statut, 'ecart_linge')

        with self.assertRaises(ValidationError):
            freeze_laundry_filet(filet, user=self.rl)

        # Arbitrage débloque et permet le figeage immuable sur N-1 (ramassage) mais jamais dépôt seul
        arbitrer_ecart_filet(filet, "Comptage laverie confirmé par photo", user=self.com)
        self.cmd_ram.refresh_from_db()
        self.assertEqual(self.cmd_ram.statut, 'cloturee')

        frozen = freeze_laundry_filet(filet, user=self.rl)
        self.assertIsNotNone(frozen.montant_fige_le)
        self.cmd_ram.refresh_from_db()
        self.cmd_dep.refresh_from_db()
        self.assertGreater(self.cmd_ram.montant_linge, Decimal('0.00'))
        self.assertEqual(self.cmd_dep.montant_linge, Decimal('0.00'))

        # Deuxième figeage interdit
        with self.assertRaises(ValidationError):
            freeze_laundry_filet(filet, user=self.rl)

        # Observation linge abîmé : facturee=False par défaut, jamais retirée du filet
        obs = ObservationLinge.objects.create(
            filet=filet, article='Drap', quantite=1, motif='taches_persistantes',
            created_by=self.rl,
        )
        self.assertFalse(obs.facturee)
        toggle_observation_facturation(obs, facturee=True, montant_facture=Decimal('40.00'), user=self.rl)
        obs.refresh_from_db()
        self.assertTrue(obs.facturee)
        self.assertEqual(obs.montant_facture, Decimal('40.00'))
        transmettre_observation_client(obs, "Tache tenace constatée", user=self.com)
        obs.refresh_from_db()
        self.assertIsNotNone(obs.notifie_client_le)


class Section12CommandesAndExecutionTests(APITestCase):
    def setUp(self):
        self.admin = _make_user('adm_cmd', 'admin')
        self.rc = _make_user('rc_cmd', 'responsable_commercial')
        self.com = _make_user('com_cmd', 'commercial')
        self.ops = _make_user('ops_cmd', 'responsable_operations')
        self.runner = _make_user('run_cmd', 'runner')
        self.client_obj = Client.objects.create(
            first_name='Nadia', last_name='Tazi', phone='0600330001',
            type_client_airbnb='conciergerie', eligible_conciergerie=True,
            assigned_commercial=self.com,
        )
        self.portal = _make_user('portal_cmd', 'client_conciergerie', client=self.client_obj)
        self.bien_2ch = Bien.objects.create(
            code='NTA001', client=self.client_obj, quartier='Racine', adresse='Rue 1', typologie='2ch',
        )
        self.bien_villa = Bien.objects.create(
            code='NTA002', client=self.client_obj, quartier='Anfa', adresse='Villa 2', typologie='villa_riad',
        )
        self.agent1 = Agent.objects.create(
            first_name='Fatima', last_name='Zahra', phone='0611000001',
            poste='femme_menage', city='Casablanca', neighborhood='Racine', statut='valide',
        )
        self.agent2 = Agent.objects.create(
            first_name='Khadija', last_name='Amrani', phone='0611000002',
            poste='femme_menage', city='Casablanca', neighborhood='Anfa', statut='valide',
        )

    def test_cutoff_constraints_and_exclusive_reassort_section_12_3(self):
        today = date(2026, 6, 10)
        tomorrow = date(2026, 6, 11)
        now_20h30 = timezone.make_aware(timezone.datetime(2026, 6, 10, 20, 30))
        now_21h30 = timezone.make_aware(timezone.datetime(2026, 6, 10, 21, 30))
        now_23h00 = timezone.make_aware(timezone.datetime(2026, 6, 10, 23, 0))

        self.assertTrue(check_cutoff_constraint(tomorrow, time(10, 0), 'matin', now=now_20h30)['allowed'])
        self.assertFalse(check_cutoff_constraint(tomorrow, time(10, 0), 'matin', now=now_21h30)['allowed'])
        self.assertTrue(check_cutoff_constraint(tomorrow, time(14, 0), 'apres_midi', now=now_23h00)['allowed'])
        self.assertFalse(check_cutoff_constraint(today, time(14, 0), 'apres_midi', now=now_20h30)['allowed'])

        # Réassort Essentiel puis Confort : Confort remplace Essentiel, jamais cumulés
        opts, prix_opts = normalize_commande_options(options=['reassort_essentiel', 'reassort_confort'])
        self.assertEqual(len(opts), 1)
        self.assertEqual(opts[0]['code'], 'reassort_confort')
        self.assertEqual(prix_opts, Decimal('79.00'))

    def test_villa_2_agents_cross_service_overlap_and_remise_en_etat_and_4_photos_and_pdf(self):
        target_day = timezone.localdate() + timedelta(days=3)
        # Demande classique déjà planifiée pour agent1 le même jour à 10:00
        dem = Demande.objects.create(
            client=self.client_obj, service='Ménage standard', date_intervention=target_day,
            heure_intervention='10:00', statut='validee',
        )
        dem.profils_envoyes.add(self.agent1)
        SubscriptionPlanning.objects.create(
            demande=dem, date_debut=target_day, date_fin=target_day, heure_debut=time(10, 0),
        )

        # Création commande Villa
        self.client.force_authenticate(user=self.com)
        resp_c = self.client.post('/api/airbnb/commandes/', {
            'bien': self.bien_villa.id,
            'date_prestation': str(target_day),
            'heure_prestation': '11:00',
            'creneau': 'matin',
            'nature_linge': 'sans_linge',
        }, format='json')
        self.assertEqual(resp_c.status_code, status.HTTP_201_CREATED)
        cmd_id = resp_c.data['id']
        cmd_obj = CommandeAirbnb.objects.get(id=cmd_id)

        # Commercial ne peut PAS forcer le prix (403) ; R.C. le peut avec motif + audit
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{cmd_id}/forcer_prix/', {
                'prix_menage': 280, 'motif': 'Test',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(user=self.rc)
        fp = self.client.post(f'/api/airbnb/commandes/{cmd_id}/forcer_prix/', {
            'prix_menage': 280, 'motif': 'Geste exceptionnel client VIP',
        }, format='json')
        self.assertEqual(fp.status_code, status.HTTP_200_OK)
        self.assertTrue(JournalAuditAirbnb.objects.filter(entite_id=str(cmd_id), action='forcage_prix').exists())

        # Assignation Villa : 1 agent -> 400 ; agent1 en conflit horaire -> 400
        self.client.force_authenticate(user=self.ops)
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{cmd_id}/assigner/', {'intervenante_id': self.agent2.id}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        conflict_resp = self.client.post(f'/api/airbnb/commandes/{cmd_id}/assigner/', {
            'intervenante_id': self.agent1.id, 'intervenante_2_id': self.agent2.id,
        }, format='json')
        self.assertEqual(conflict_resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Suggestion intervenantes : agent2 dispo (score > agent1 occupée)
        sugg = self.client.get(f'/api/airbnb/commandes/suggestions_intervenantes/?commande_id={cmd_id}')
        self.assertEqual(sugg.status_code, status.HTTP_200_OK)
        avail_map = {s['id']: s['disponible'] for s in sugg.data['suggestions']}
        self.assertFalse(avail_map[self.agent1.id])
        self.assertTrue(avail_map[self.agent2.id])

        # Libérons agent1 en annulant la demande classique puis assignons 2 agents
        dem.statut = Demande.ANNULE
        dem.save()
        ok_assign = self.client.post(f'/api/airbnb/commandes/{cmd_id}/assigner/', {
            'intervenante_id': self.agent1.id,
            'intervenante_2_id': self.agent2.id,
            'runner_id': self.runner.id,
        }, format='json')
        self.assertEqual(ok_assign.status_code, status.HTTP_200_OK)

        # Fiche mission PDF : binaire PDF sans aucun montant/DH/MAD dans le texte rendu ; runner ne voit pas intervenantes
        self.client.force_authenticate(user=self.ops)
        pdf_resp = self.client.get(f'/api/airbnb/commandes/{cmd_id}/exporter_fiche_mission_pdf/')
        self.assertEqual(pdf_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(pdf_resp.content.startswith(b'%PDF'))
        bt_strings = re.findall(rb'\(((?:\\.|[^()\r\n])*)\)\s*T[jJ]', pdf_resp.content)
        rendered_text = b' '.join(bt_strings)
        self.assertNotIn(b'DH', rendered_text)
        self.assertNotIn(b'MAD', rendered_text)
        self.assertNotIn(b'280', rendered_text)
        self.assertIn(b'NTA002', rendered_text)

        # Remise en état sans accord écrit bloque facturabilité
        cmd_obj.refresh_from_db()
        self.client.force_authenticate(user=self.ops)
        self.client.post(f'/api/airbnb/commandes/{cmd_id}/valider_remise_en_etat/', {
            'heures': 2, 'montant': 120,
        }, format='json')

        # Clôture < 4 photos refusée -> 4 photos acceptée
        bad_close = self.client.post(f'/api/airbnb/commandes/{cmd_id}/cloturer/', {
            'photos': ['p1', 'p2', 'p3'],
        }, format='json')
        self.assertEqual(bad_close.status_code, status.HTTP_400_BAD_REQUEST)

        ok_close = self.client.post(f'/api/airbnb/commandes/{cmd_id}/cloturer/', {
            'photos': ['p1', 'p2', 'p3', 'p4'],
        }, format='json')
        self.assertEqual(ok_close.status_code, status.HTTP_200_OK)
        self.assertFalse(ok_close.data['facturable'])

        # Accord écrit -> passe facturable et total mis à jour
        self.client.force_authenticate(user=self.portal)
        ok_accord = self.client.post(f'/api/airbnb/commandes/{cmd_id}/accord_remise_en_etat/', {
            'decision': 'accepte',
            'accord_preuve': 'Message WhatsApp client OK +120 DH',
        }, format='json')
        self.assertEqual(ok_accord.status_code, status.HTTP_200_OK)
        self.assertTrue(ok_accord.data['facturable'])
        self.assertEqual(Decimal(ok_accord.data['total_ttc']), Decimal('400.00'))

    def test_objet_trouve_workflow_et_relances_j1_j7(self):
        cmd = CommandeAirbnb.objects.create(
            numero='CMD-2026-OBJ1', bien=self.bien_2ch,
            date_prestation=timezone.localdate(), statut='cloturee',
            photos_cloture=['1', '2', '3', '4'],
        )
        self.client.force_authenticate(user=self.ops)
        cr = self.client.post('/api/airbnb/objets-trouves/', {
            'commande': cmd.id, 'bien': self.bien_2ch.id, 'description': 'Montre connectée',
        }, format='json')
        self.assertEqual(cr.status_code, status.HTTP_201_CREATED)
        oid = cr.data['id']

        self.assertEqual(self.client.post(f'/api/airbnb/objets-trouves/{oid}/mettre_en_securite/').status_code, 200)
        self.client.force_authenticate(user=self.com)
        self.assertEqual(self.client.post(f'/api/airbnb/objets-trouves/{oid}/notifier_client/').status_code, 200)

        # Simuler passage à J+8 sans instruction -> déclenche relances J+1 et J+7
        obj = ObjetTrouve.objects.get(id=oid)
        obj.signale_le = timezone.now() - timedelta(days=8)
        obj.save(update_fields=['signale_le'])
        call_command('relances_execution_airbnb')
        obj.refresh_from_db()
        self.assertIsNotNone(obj.relance_j1_le)
        self.assertIsNotNone(obj.relance_j7_le)


class Section12BillingTests(APITestCase):
    def setUp(self):
        self.rf = _make_user('rf_bil', 'responsable_facturation')
        self.rc = _make_user('rc_bil', 'responsable_commercial')
        self.com = _make_user('com_bil', 'commercial')
        self.ops = _make_user('ops_bil', 'responsable_operations')
        self.runner = _make_user('run_bil', 'runner')
        self.agent = Agent.objects.create(first_name='Salma', last_name='Kabbaj', phone='0622000001')

        self.c_mensuel = Client.objects.create(
            first_name='Amine', last_name='Berrada', phone='0600440001',
            type_client_airbnb='conciergerie', eligible_conciergerie=True,
            mode_paiement_airbnb='mensuel',
            date_demarrage_airbnb=date(2026, 3, 1),
            probatoire_jusqu_au=date(2026, 5, 1),
            assigned_commercial=self.com,
        )
        self.c_probatoire = Client.objects.create(
            first_name='Sanaa', last_name='Idrissi', phone='0600440002',
            type_client_airbnb='conciergerie', eligible_conciergerie=True,
            mode_paiement_airbnb='mensuel',
            date_demarrage_airbnb=date(2026, 7, 5),
            probatoire_jusqu_au=date(2026, 9, 5),
            assigned_commercial=self.com,
        )
        self.portal_prob = _make_user('portal_prob', 'client_conciergerie', client=self.c_probatoire)

        self.b_m = Bien.objects.create(code='ABE001', client=self.c_mensuel, quartier='Maarif', adresse='A', typologie='2ch')
        self.b_p = Bien.objects.create(code='SID001', client=self.c_probatoire, quartier='Maarif', adresse='B', typologie='2ch')

    def test_calendrier_quinzaine_prorata_mensuel_et_bascule_section_12_4(self):
        # Cycle mensuel 26/06 -> 25/07 : émis le 26/07, échéance 30/07
        cmd_m = CommandeAirbnb.objects.create(
            numero='CMD-BIL-M1', bien=self.b_m, date_prestation=date(2026, 7, 10),
            nature_linge='sans_linge', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
            statut='cloturee', photos_cloture=['1', '2', '3', '4'],
        )
        res_m = generer_factures_cycle(target_date=date(2026, 7, 26), user=self.rf, client_id=self.c_mensuel.id)
        self.assertEqual(len(res_m['factures']), 1)
        f_m = res_m['factures'][0]
        self.assertEqual(f_m.date_emission, date(2026, 7, 26))
        self.assertEqual(f_m.date_echeance, date(2026, 7, 30))
        self.assertEqual(f_m.periode_debut, date(2026, 6, 26))
        self.assertEqual(f_m.periode_fin, date(2026, 7, 25))
        self.assertEqual(f_m.montant_total, Decimal('160.00'))

        # Nouveau client démarrant 05/07 : calendrier exact Brief §7.2
        cal = preview_calendrier_facturation(self.c_probatoire, n=5, ref_date=date(2026, 7, 5))
        self.assertEqual(cal[0]['periode_debut'], '2026-07-05')
        self.assertEqual(cal[0]['periode_fin'], '2026-07-10')
        self.assertEqual(cal[0]['date_emission'], '2026-07-11')
        self.assertEqual(cal[0]['date_echeance'], '2026-07-15')
        self.assertTrue(cal[0]['est_prorata'])

        # Génération réelle 1ère quinzaine au 11/07
        cmd_p = CommandeAirbnb.objects.create(
            numero='CMD-BIL-P1', bien=self.b_p, date_prestation=date(2026, 7, 7),
            nature_linge='sans_linge', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
            statut='cloturee', photos_cloture=['1', '2', '3', '4'],
        )
        res_p = generer_factures_cycle(target_date=date(2026, 7, 11), user=self.rf, client_id=self.c_probatoire.id)
        self.assertEqual(len(res_p['factures']), 1)
        self.assertTrue(res_p['factures'][0].est_prorata)
        self.assertEqual(res_p['factures'][0].date_echeance, date(2026, 7, 15))

        # Fin de probatoire après 2 mois (06/09/2026) -> bascule auto en mensuel
        res_basc = generer_factures_cycle(target_date=date(2026, 9, 6), user=self.rf, client_id=self.c_probatoire.id)
        self.c_probatoire.refresh_from_db()
        self.assertEqual(self.c_probatoire.mode_paiement_airbnb, 'mensuel')
        self.assertIn(self.c_probatoire.id, res_basc['bascules'])

        # Commercial ne peut PAS annuler la bascule (403), R.C. le peut
        self.client.force_authenticate(user=self.com)
        self.assertEqual(
            self.client.post('/api/airbnb/facturation/annuler_bascule_mensuelle/', {
                'client_id': self.c_probatoire.id, 'motif': 'Test',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(user=self.rc)
        resp_ann = self.client.post('/api/airbnb/facturation/annuler_bascule_mensuelle/', {
            'client_id': self.c_probatoire.id, 'motif': 'Client préfère rester au passage',
        }, format='json')
        self.assertEqual(resp_ann.status_code, status.HTTP_200_OK)
        self.c_probatoire.refresh_from_db()
        self.assertEqual(self.c_probatoire.mode_paiement_airbnb, 'passage')
        self.assertTrue(self.c_probatoire.probatoire_bascule_annulee)

    def test_suspension_j_plus_1_reactivation_et_entree_caisse_et_3_leviers_rf(self):
        today = date(2026, 8, 10)
        self.c_probatoire.mode_paiement_airbnb = 'passage'
        self.c_probatoire.save(update_fields=['mode_paiement_airbnb'])
        # Mode passage : 2 factures dont la plus ancienne a pour échéance le 09/08 (J+1 le 10/08)
        f_old = Facture.objects.create(
            client=self.c_probatoire, source=Facture.SOURCE_AIRBNB,
            numero='FAC-AB-OLD1', montant_total=Decimal('160.00'),
            date_echeance=today - timedelta(days=1), statut=Facture.EN_ATTENTE,
        )
        f_new = Facture.objects.create(
            client=self.c_probatoire, source=Facture.SOURCE_AIRBNB,
            numero='FAC-AB-NEW2', montant_total=Decimal('160.00'),
            date_echeance=today + timedelta(days=1), statut=Facture.EN_ATTENTE,
        )

        # Commande planifiée du surlendemain + commande déjà passée d'avant-hier
        cmd_fut = CommandeAirbnb.objects.create(
            numero='CMD-SUSP-FUT', bien=self.b_p, date_prestation=today + timedelta(days=2),
            statut='assignee', intervenante=self.agent, runner=self.runner,
        )
        cmd_past = CommandeAirbnb.objects.create(
            numero='CMD-SUSP-PAST', bien=self.b_p, date_prestation=today - timedelta(days=2),
            statut='saisie',
        )

        # J-1 sur f_new -> rappel envoyé ; J+1 sur f_old -> suspension + annulation des commandes
        res_susp = verifier_suspensions_et_relances(today=today, user=self.rf)
        self.assertEqual(res_susp['suspended'], 1)
        self.assertEqual(res_susp['reminders'], 1)

        self.c_probatoire.refresh_from_db()
        cmd_fut.refresh_from_db()
        cmd_past.refresh_from_db()
        self.assertEqual(self.c_probatoire.statut_airbnb, 'suspendu')
        self.assertEqual(cmd_fut.statut, 'annulee')
        self.assertTrue(cmd_fut.annulee_par_suspension)
        self.assertTrue(cmd_fut.reactivable_apres_suspension)
        self.assertIsNone(cmd_fut.intervenante)
        self.assertIsNone(cmd_fut.runner)
        # Commande d'avant-hier reste non réactivable
        self.assertFalse(cmd_past.reactivable_apres_suspension)

        # Client suspendu bloqué pour créer une nouvelle commande
        self.client.force_authenticate(user=self.portal_prob)
        blocked_cmd = self.client.post('/api/airbnb/commandes/', {
            'bien': self.b_p.id,
            'date_prestation': str(today + timedelta(days=5)),
            'heure_prestation': '14:00',
            'creneau': 'apres_midi',
        }, format='json')
        self.assertEqual(blocked_cmd.status_code, status.HTTP_400_BAD_REQUEST)

        # Paiement des 2 factures -> crée EntreeCaisse + lève suspension + permet réactivation du surlendemain
        enregistrer_paiement(f_old, Decimal('160.00'), 'virement', payment_date=today, reference='VIR-1', user=self.rf)
        enregistrer_paiement(f_new, Decimal('160.00'), 'virement', payment_date=today, reference='VIR-2', user=self.rf)
        self.c_probatoire.refresh_from_db()
        self.assertEqual(self.c_probatoire.statut_airbnb, 'actif')
        self.assertEqual(EntreeCaisse.objects.filter(paiement__facture__in=[f_old, f_new]).count(), 2)

        # Réactivation de la commande du surlendemain
        self.client.force_authenticate(user=self.ops)
        react = self.client.post(f'/api/airbnb/commandes/{cmd_fut.id}/reactiver/')
        self.assertEqual(react.status_code, status.HTTP_200_OK)
        cmd_fut.refresh_from_db()
        self.assertEqual(cmd_fut.statut, 'saisie')

        # 3 Leviers R.F. vs Commercial 403
        cmd_to_bill = CommandeAirbnb.objects.create(
            numero='CMD-LEV-1', bien=self.b_m, date_prestation=today - timedelta(days=1),
            nature_linge='sans_linge', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
            statut='cloturee', photos_cloture=['1', '2', '3', '4'],
        )
        fac = generer_facture_passage(cmd_to_bill, user=self.rf)

        self.client.force_authenticate(user=self.com)
        self.assertEqual(
            self.client.post(f'/api/airbnb/facturation/{fac.id}/geste_commercial/', {
                'montant': 20, 'motif': 'Test',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f'/api/airbnb/facturation/{fac.id}/annuler_facture/', {'motif': 'Test'}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Geste commercial + réduction partielle par R.F.
        self.client.force_authenticate(user=self.rf)
        r_geste = self.client.post(f'/api/airbnb/facturation/{fac.id}/geste_commercial/', {
            'montant': 20, 'designation': 'Retard léger', 'motif': 'Retard 30 min',
        }, format='json')
        self.assertEqual(r_geste.status_code, status.HTTP_200_OK)
        fac.refresh_from_db()
        self.assertEqual(fac.montant_total, Decimal('140.00'))

        r_red = self.client.post(f'/api/airbnb/facturation/{fac.id}/reduction_partielle/', {
            'montant': 10, 'commande_id': str(cmd_to_bill.id), 'motif': 'Option non livrée',
        }, format='json')
        self.assertEqual(r_red.status_code, status.HTTP_200_OK)
        fac.refresh_from_db()
        self.assertEqual(fac.montant_total, Decimal('130.00'))

        # Facture PDF générée avec coordonnées légales
        pdf_fac = self.client.get(f'/api/airbnb/facturation/{fac.id}/exporter_facture_pdf/')
        self.assertEqual(pdf_fac.status_code, status.HTTP_200_OK)
        self.assertTrue(pdf_fac.content.startswith(b'%PDF'))

        # Annulation facture -> conserve la prestation non facturée pour le cycle suivant
        r_ann = self.client.post(f'/api/airbnb/facturation/{fac.id}/annuler_facture/', {
            'motif': 'Erreur destinataire',
        }, format='json')
        self.assertEqual(r_ann.status_code, status.HTTP_200_OK)
        fac.refresh_from_db()
        cmd_to_bill.refresh_from_db()
        self.assertEqual(fac.statut, Facture.ANNULE)
        self.assertIsNone(cmd_to_bill.facture)
        self.assertEqual(cmd_to_bill.statut, 'facturable')


class Section12SettingsAndIcalAndCronTests(APITestCase):
    def setUp(self):
        self.admin = _make_user('adm_ic', 'admin')
        self.ops = _make_user('ops_ic', 'responsable_operations')
        self.rf = _make_user('rf_ic', 'responsable_facturation')
        self.com = _make_user('com_ic', 'commercial')
        self.client_obj = Client.objects.create(
            first_name='Karim', last_name='Fassi', phone='0600550001',
            type_client_airbnb='conciergerie', eligible_conciergerie=True,
            assigned_commercial=self.com,
        )
        self.bien = Bien.objects.create(
            code='KFA001', client=self.client_obj, quartier='Bourgogne',
            adresse='Rue 10', typologie='2ch', ical_url='https://example.test/cal.ics',
        )

    def test_grille_tarifaire_versioning_et_composition_set_immuable_section_12_5(self):
        # Version v1 à 160 DH créée pour aujourd'hui
        today = timezone.localdate()
        cmd_avant = CommandeAirbnb.objects.create(
            numero='CMD-VER-1', bien=self.bien, date_prestation=today + timedelta(days=1),
            grille_version='v1', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
        )

        # Nouvelle grille à 175 DH effective dans 5 jours
        eff_future = today + timedelta(days=5)
        create_grille_tarifaire_version(
            version_label='2026-v2',
            date_entree_vigueur=eff_future,
            tarifs_json={'studio': 130, '1ch': 130, '2ch': 175, '3ch': 190, '4ch': 220, '5ch': 250, 'villa_riad': 300},
            user=self.admin,
        )
        # L'ancienne commande ne bouge jamais ; une nouvelle à J+6 prend 175 DH
        cmd_avant.refresh_from_db()
        self.assertEqual(cmd_avant.prix_menage, Decimal('160.00'))
        p_new = calculate_commande_pricing(self.bien, date_prestation=today + timedelta(days=6))
        self.assertEqual(p_new['prix_menage'], 175.0)
        self.assertEqual(p_new['grille_version'], '2026-v2')

        # Changement de composition du set (taies 2 -> 1) : filet figé inchangé, futur recalculé
        filet_fige = FiletLinge.objects.create(
            code_filet='SAC-KFA001-01', bien=self.bien,
            comptage_runner={'housses': 2, 'draps': 2, 'taies': 2, 'grandes_serviettes': 4, 'petites_serviettes': 4},
        )
        freeze_laundry_filet(
            filet_fige, user=self.admin,
            comptage_laverie_final={'housses': 2, 'draps': 2, 'taies': 2, 'grandes_serviettes': 4, 'petites_serviettes': 4},
        )
        self.assertEqual(filet_fige.sets_calcules, 1)
        self.assertEqual(filet_fige.montant, Decimal('80.00'))

        cfg = AirbnbConfig.objects.first()
        cfg.set_composition_standard = {'housses': 1, 'draps': 1, 'taies': 1, 'grandes_serviettes': 2, 'petites_serviettes': 2}
        cfg.save()
        filet_fige.refresh_from_db()
        self.assertEqual(filet_fige.montant, Decimal('80.00'))  # Figé immuable
        r_futur = calculate_linen_pieces_and_amount({
            'housses': 2, 'draps': 2, 'taies': 2, 'grandes_serviettes': 4, 'petites_serviettes': 4,
        })
        self.assertEqual(r_futur['nb_sets_complets'], 2)
        self.assertEqual(r_futur['montant_total'], 100.0)

    def test_ical_propositions_deduplication_et_cron_commands(self):
        d1 = (timezone.localdate() + timedelta(days=3)).strftime('%Y%m%d')
        d2 = (timezone.localdate() + timedelta(days=6)).strftime('%Y%m%d')
        d3 = (timezone.localdate() + timedelta(days=8)).strftime('%Y%m%d')
        # Commande ferme existante à d3 -> ne doit jamais créer de proposition en double
        CommandeAirbnb.objects.create(
            numero='CMD-EX-D3', bien=self.bien,
            date_prestation=timezone.localdate() + timedelta(days=8),
            statut='saisie',
        )

        ics_sample = "\r\n".join([
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:evt-ical-001",
            f"DTSTART;VALUE=DATE:{d1}",
            f"DTEND;VALUE=DATE:{d2}",
            "SUMMARY:Reserved",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:evt-ical-002",
            f"DTSTART;VALUE=DATE:{d2}",
            f"DTEND;VALUE=DATE:{d3}",
            "SUMMARY:Reserved 2",
            "END:VEVENT",
            "END:VCALENDAR",
        ])
        res1 = sync_bien_ical_turnovers(self.bien, ical_content=ics_sample)
        self.assertTrue(res1['success'])
        self.assertEqual(res1['created_turnovers'], 1)
        prop = CommandeAirbnb.objects.get(bien=self.bien, source='ical_auto')
        self.assertEqual(prop.statut, 'proposition')

        # Deuxième passage : zéro doublon
        res2 = sync_bien_ical_turnovers(self.bien, ical_content=ics_sample)
        self.assertEqual(res2['created_turnovers'], 0)

        # Confirmation proposition -> commande ferme 'confirmee' avec prix calculé
        conf = confirmer_proposition(prop, user=self.com)
        self.assertEqual(conf.statut, 'confirmee')
        self.assertEqual(conf.prix_menage, Decimal('160.00'))

        # Crons 18h remontée TDB + 20h dispatch WhatsApp via call_command et via API lancer_cron
        tomorrow = timezone.localdate() + timedelta(days=1)
        agent = Agent.objects.create(first_name='Mina', last_name='Razi', phone='0644000001')
        cmd_j1 = CommandeAirbnb.objects.create(
            numero='CMD-CRON-1', bien=self.bien, date_prestation=tomorrow,
            statut='saisie', intervenante=agent,
        )
        call_command('remontee_tdb_18h')
        cmd_j1.refresh_from_db()
        self.assertEqual(cmd_j1.statut, 'remontee_tdb')

        self.client.force_authenticate(user=self.ops)
        cron_resp = self.client.post('/api/airbnb/facturation/lancer_cron/', {
            'job': 'dispatch_whatsapp_20h',
        }, format='json')
        self.assertEqual(cron_resp.status_code, status.HTTP_200_OK)
        cmd_j1.refresh_from_db()
        self.assertIsNotNone(cmd_j1.fiche_envoyee_le)

    def test_cloisonnement_http_virement_et_crons_restants(self):
        runner = _make_user('run_clo', 'runner')
        rl = _make_user('rl_clo', 'responsable_linge')
        portal_own = _make_user('por_own', 'client_conciergerie', client=self.client_obj)
        other_client = Client.objects.create(
            first_name='Autre', last_name='Client', phone='0600880002',
            type_client_airbnb='conciergerie', eligible_conciergerie=True,
        )
        other_bien = Bien.objects.create(
            code='ACL001', client=other_client, quartier='Anfa', adresse='Rue Z', typologie='2ch',
        )
        cmd_own = CommandeAirbnb.objects.create(
            numero='CMD-CLO-1', bien=self.bien, date_prestation=timezone.localdate(),
            nature_linge='depot_ramassage', runner=runner,
            prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
            statut='cloturee', photos_cloture=['1', '2', '3', '4'],
        )
        filet = FiletLinge.objects.create(
            code_filet='SAC-KFA001-99', bien=self.bien, commande_ramassage=cmd_own,
            comptage_runner={'draps': 2, 'housses': 1, 'taies': 2, 'grandes_serviettes': 2, 'petites_serviettes': 2},
            montant=Decimal('50.00'),
        )

        # Runner et R.L. ne voient aucun champ financier sur FiletLinge
        for u in (runner, rl):
            self.client.force_authenticate(user=u)
            r = self.client.get(f'/api/airbnb/filets/{filet.id}/')
            self.assertEqual(r.status_code, status.HTTP_200_OK)
            self.assertNotIn('montant', r.data)
            self.assertNotIn('minimum_applique', r.data)
            self.assertNotIn('montant', r.data.get('details_articles', {}))

        # R.L. crée une ObservationLinge : facturee=False forcé, runner bloqué sur activer_facturation
        self.client.force_authenticate(user=rl)
        obs_resp = self.client.post('/api/airbnb/observations-linge/', {
            'filet': filet.id,
            'article': 'draps',
            'motif': 'taches_persistantes',
            'quantite': 1,
            'note': 'Tache encre',
            'facturee': True,
        }, format='json')
        self.assertEqual(obs_resp.status_code, status.HTTP_201_CREATED)
        self.assertFalse(obs_resp.data['facturee'])
        self.assertNotIn('montant_facture', obs_resp.data)

        # R.L. active facturation pièce par pièce sans voir ni saisir de montant (calcul auto tarif_piece_supp)
        act_obs = self.client.post(
            f"/api/airbnb/observations-linge/{obs_resp.data['id']}/activer_facturation/",
            {'facturee': True},
            format='json',
        )
        self.assertEqual(act_obs.status_code, status.HTTP_200_OK)
        self.assertTrue(act_obs.data['observation']['facturee'])
        self.assertNotIn('montant_facture', act_obs.data['observation'])
        obs_db = ObservationLinge.objects.get(pk=obs_resp.data['id'])
        self.assertEqual(obs_db.montant_facture, Decimal('5.00'))

        self.client.force_authenticate(user=runner)
        forbid_obs = self.client.post(f"/api/airbnb/observations-linge/{obs_resp.data['id']}/activer_facturation/")
        self.assertEqual(forbid_obs.status_code, status.HTTP_403_FORBIDDEN)

        # Client conciergerie déclare virement sur sa propre facture OK, 404 sur facture d'autrui, 403 journal audit
        fac_own = Facture.objects.create(
            numero='FAC-CLO-OWN', client=self.client_obj, source=Facture.SOURCE_AIRBNB,
            mode_facturation='passage', date_emission=timezone.localdate(),
            date_echeance=timezone.localdate() + timedelta(days=2),
            montant_total=Decimal('160.00'), statut=Facture.EN_ATTENTE,
        )
        fac_other = Facture.objects.create(
            numero='FAC-CLO-OTH', client=other_client, source=Facture.SOURCE_AIRBNB,
            mode_facturation='passage', date_emission=timezone.localdate(),
            date_echeance=timezone.localdate() + timedelta(days=2),
            montant_total=Decimal('160.00'), statut=Facture.EN_ATTENTE,
        )
        self.client.force_authenticate(user=portal_own)
        self.assertEqual(
            self.client.post(f'/api/airbnb/facturation/{fac_own.id}/declarer_virement/', {
                'reference': 'VIR-TEST-001', 'montant_declare': '160.00',
            }, format='json').status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(f'/api/airbnb/facturation/{fac_other.id}/declarer_virement/', {
                'reference': 'VIR-OTHER-001',
            }, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(self.client.get('/api/airbnb/journal-audit/').status_code, status.HTTP_403_FORBIDDEN)

        # Exécution propre des 3 autres commandes cron manquantes dans les tests
        with patch('airbnb.services.ical_service.fetch_and_parse_ical', return_value=[]):
            call_command('sync_ical_turnovers')
        call_command('verifier_suspensions_clients')
        call_command('generer_factures_airbnb')
        self.assertTrue(other_bien.id)



class Section12AuditRemediationTests(APITestCase):
    """Couverture exhaustive des corrections d'audit A1–A10 et B1–B5."""

    def setUp(self):
        self.admin = _make_user('adm_aud', 'admin', phone='0601000001')
        self.rc = _make_user('rc_aud', 'responsable_commercial', phone='0601000002')
        self.com = _make_user('com_aud', 'commercial', phone='0601000003')
        self.com2 = _make_user('com2_aud', 'commercial', phone='0601000004')
        self.ops_ro = _make_user('ro_aud', 'responsable_operations', phone='0601000005')
        self.ops_co = _make_user('co_aud', 'charge_operations', phone='0601000006')
        self.rf = _make_user('rf_aud', 'responsable_facturation', phone='0601000007')
        self.rl = _make_user('rl_aud', 'responsable_linge', phone='0601000008')
        self.runner = _make_user('run_aud', 'runner', phone='0601000009')

        self.c1 = Client.objects.create(
            first_name='Amine',
            last_name='Tazi',
            phone='0600990001',
            email='amine.tazi@test.ma',
            type_client_airbnb='conciergerie',
            eligible_conciergerie=True,
            assigned_commercial=self.com,
        )
        self.c2 = Client.objects.create(
            first_name='Nadia',
            last_name='Chraibi',
            phone='0600990002',
            email='nadia.chraibi@test.ma',
            type_client_airbnb='conciergerie',
            eligible_conciergerie=True,
            assigned_commercial=self.com2,
        )
        self.portal1 = _make_user('portal_c1', 'client_conciergerie', client=self.c1)

        for idx in range(1, 4):
            Bien.objects.create(
                code=f'ATA-CAS-{idx:03d}',
                nom_bien=f'Bien C1 #{idx}',
                client=self.c1,
                ville='Casablanca',
                quartier='Maarif',
                adresse=f'Rue {idx}',
                typologie='2ch',
                statut_activation='actif',
                is_active=True,
            )
            Bien.objects.create(
                code=f'NCH-CAS-{idx:03d}',
                nom_bien=f'Bien C2 #{idx}',
                client=self.c2,
                ville='Casablanca',
                quartier='Anfa',
                adresse=f'Av {idx}',
                typologie='1ch',
                statut_activation='actif',
                is_active=True,
            )

        self.bien1 = self.c1.biens_airbnb.first()
        self.bien2 = self.c2.biens_airbnb.first()
        self.bien_rabat = Bien.objects.create(
            code='ATA-RAB-004',
            nom_bien='Riad Rabat',
            client=self.c1,
            ville='Rabat',
            quartier='Agdal',
            adresse='Av Fal',
            typologie='2ch',
            services_souscrits=['menage'],
            statut_activation='actif',
            is_active=True,
        )

    def test_a1_patch_locks_invariants_across_viewsets(self):
        target_date = timezone.localdate() + timedelta(days=3)
        agent = Agent.objects.create(
            first_name='Fatima', last_name='Z', phone='0601020304',
            poste='femme_menage', statut='disponible', city='Casablanca',
        )

        # 1. CommandeAirbnb: lock workflow/billing/remise/assignment fields & force server-side recalc
        self.client.force_authenticate(user=self.com)
        create_resp = self.client.post('/api/airbnb/commandes/', {
            'bien': self.bien1.id,
            'date_prestation': str(target_date),
            'creneau': 'matin',
            'nature_linge': 'depot_ramassage',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        cmd_id = create_resp.data['id']
        self.assertEqual(Decimal(str(create_resp.data['total_ttc'])), Decimal('160.00'))

        # Tentative PATCH de champs protégés -> ignorés par read_only_fields
        patch_hack = self.client.patch(f'/api/airbnb/commandes/{cmd_id}/', {
            'statut': 'facturee',
            'prix_menage': '1.00',
            'total_ttc': '1.00',
            'remise_en_etat': '500.00',
            'remise_en_etat_statut': 'accord_ecrit',
            'intervenante': agent.id,
            'prix_force_motif': 'Tentative illégale',
        }, format='json')
        self.assertEqual(patch_hack.status_code, status.HTTP_200_OK)
        cmd = CommandeAirbnb.objects.get(id=cmd_id)
        self.assertEqual(cmd.statut, 'saisie')
        self.assertEqual(cmd.total_ttc, Decimal('160.00'))
        self.assertEqual(cmd.remise_en_etat, Decimal('0.00'))
        self.assertIsNone(cmd.intervenante)
        self.assertIsNone(cmd.prix_force_par)

        # PATCH légitime sur options -> recalcul serveur
        patch_opt = self.client.patch(f'/api/airbnb/commandes/{cmd_id}/', {
            'options': [{'code': 'reassort_confort'}],
        }, format='json')
        self.assertEqual(patch_opt.status_code, status.HTTP_200_OK)
        cmd.refresh_from_db()
        self.assertEqual(cmd.prix_options, Decimal('79.00'))
        self.assertEqual(cmd.total_ttc, Decimal('239.00'))

        # PATCH vers un bien Rabat tout en gardant nature_linge='depot_ramassage' -> 400
        self.assertEqual(
            self.client.patch(f'/api/airbnb/commandes/{cmd_id}/', {'bien': self.bien_rabat.id}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        # PATCH hors cut-off (date aujourd'hui par commercial) -> 400
        self.assertEqual(
            self.client.patch(f'/api/airbnb/commandes/{cmd_id}/', {
                'date_prestation': str(timezone.localdate()),
            }, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        # PATCH sur commande terminée ('cloturee') -> 400
        cmd.statut = 'cloturee'
        cmd.save(update_fields=['statut'])
        self.assertEqual(
            self.client.patch(f'/api/airbnb/commandes/{cmd_id}/', {
                'instructions': 'Tentative tardive',
            }, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        # 2. FiletLinge: lock comptages/montant/statut + blocage PUT/PATCH après figer_montant
        filet = FiletLinge.objects.create(
            code_filet='SAC-LOCK-01',
            bien=self.bien1,
            comptage_runner={'draps': 2, 'housses': 1, 'taies': 2, 'grandes_serviettes': 2, 'petites_serviettes': 2},
            montant=Decimal('50.00'),
        )
        self.client.force_authenticate(user=self.rl)
        self.client.patch(f'/api/airbnb/filets/{filet.id}/', {
            'montant': '999.00',
            'statut': 'pret',
            'ecart': 0,
        }, format='json')
        filet.refresh_from_db()
        self.assertEqual(filet.montant, Decimal('50.00'))
        self.assertEqual(filet.statut, 'compte_runner')

        freeze_laundry_filet(filet, user=self.rl, comptage_laverie_final={
            'draps': 2, 'housses': 1, 'taies': 2, 'grandes_serviettes': 2, 'petites_serviettes': 2,
        })
        self.assertEqual(
            self.client.patch(f'/api/airbnb/filets/{filet.id}/', {'remplissage_pct': 90}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        # 3. ObservationLinge: lock facturee/montant_facture sur PATCH
        obs = ObservationLinge.objects.create(
            filet=filet, article='draps', motif='dechirure', quantite=1, created_by=self.rl,
        )
        self.client.patch(f'/api/airbnb/observations-linge/{obs.id}/', {
            'facturee': True, 'montant_facture': '300.00',
        }, format='json')
        obs.refresh_from_db()
        self.assertFalse(obs.facturee)
        self.assertEqual(obs.montant_facture, Decimal('0.00'))

        # 4. Bien: lock code + Rabat effectif sans resending services_souscrits + Bouskoura auto zone_eloignee
        self.client.force_authenticate(user=self.rc)
        self.assertEqual(
            self.client.patch(f'/api/airbnb/biens/{self.bien1.id}/', {'code': 'HACK-999'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.patch(f'/api/airbnb/biens/{self.bien1.id}/', {'ville': 'Rabat'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        bouskoura_patch = self.client.patch(
            f'/api/airbnb/biens/{self.bien1.id}/', {'quartier': 'Bouskoura Ville Verte'}, format='json'
        )
        self.assertEqual(bouskoura_patch.status_code, status.HTTP_200_OK)
        self.bien1.refresh_from_db()
        self.assertTrue(self.bien1.zone_eloignee)

    def test_a2_annuler_cutoff_and_derogation(self):
        today = timezone.localdate()
        cmd_today = CommandeAirbnb.objects.create(
            numero='CMD-CUT-TODAY',
            bien=self.bien1,
            date_prestation=today,
            creneau='matin',
            statut='confirmee',
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
        )
        # Client conciergerie bloqué après cut-off
        self.client.force_authenticate(user=self.portal1)
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{cmd_today.id}/annuler/', {'motif': 'Annul tardive'}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        # Commercial bloqué même avec forcer_hors_delai
        self.client.force_authenticate(user=self.com)
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{cmd_today.id}/annuler/', {
                'motif': 'Tardive com', 'forcer_hors_delai': True,
            }).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        # R.C. sans forcer_hors_delai -> 400
        self.client.force_authenticate(user=self.rc)
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{cmd_today.id}/annuler/', {'motif': 'Sans derog'}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        # R.C. avec forcer_hors_delai=True -> 200 + horodatage + audit + hors_delai_derogation
        ok = self.client.post(f'/api/airbnb/commandes/{cmd_today.id}/annuler/', {
            'motif': 'Dérogation urgence client', 'forcer_hors_delai': True,
        }, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertIn('horodatage_annulation', ok.data)
        cmd_today.refresh_from_db()
        self.assertEqual(cmd_today.statut, 'annulee')
        self.assertTrue(cmd_today.hors_delai_derogation)
        self.assertIsNotNone(cmd_today.annulee_le)
        self.assertTrue(
            JournalAuditAirbnb.objects.filter(
                entite='CommandeAirbnb', entite_id=str(cmd_today.id), action='annulation_hors_delai_derogation'
            ).exists()
        )

        # J+3 dans les délais -> Client Conciergerie peut annuler
        cmd_future = CommandeAirbnb.objects.create(
            numero='CMD-CUT-FUT',
            bien=self.bien1,
            date_prestation=today + timedelta(days=3),
            creneau='matin',
            statut='confirmee',
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
        )
        self.client.force_authenticate(user=self.portal1)
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{cmd_future.id}/annuler/', {'motif': 'Changement séjour'}).status_code,
            status.HTTP_200_OK,
        )

    def test_a3_a4_resume_isolation_and_lever_suspension(self):
        self.c1.statut_airbnb = 'suspendu'
        self.c1.save(update_fields=['statut_airbnb'])
        self.c2.statut_airbnb = 'suspendu'
        self.c2.save(update_fields=['statut_airbnb'])

        cmd_susp = CommandeAirbnb.objects.create(
            numero='CMD-SUSP-REACT',
            bien=self.bien1,
            date_prestation=timezone.localdate() + timedelta(days=2),
            statut='annulee',
            annulee_par_suspension=True,
            reactivable_apres_suspension=False,
        )

        # Client conciergerie C1 ne voit jamais C2 dans /resume/
        self.client.force_authenticate(user=self.portal1)
        r_portal = self.client.get('/api/airbnb/facturation/resume/')
        self.assertEqual(r_portal.status_code, status.HTTP_200_OK)
        self.assertEqual(r_portal.data['clients_suspendus'], 1)

        self.c1.statut_airbnb = 'actif'
        self.c1.save(update_fields=['statut_airbnb'])
        r_portal_active = self.client.get('/api/airbnb/facturation/resume/')
        self.assertEqual(r_portal_active.data['clients_suspendus'], 0)

        # Commercial 1 ne voit que ses clients assignés
        self.c1.statut_airbnb = 'suspendu'
        self.c1.save(update_fields=['statut_airbnb'])
        self.client.force_authenticate(user=self.com)
        r_com = self.client.get('/api/airbnb/facturation/resume/')
        self.assertEqual(r_com.status_code, status.HTTP_200_OK)
        self.assertEqual(r_com.data['clients_suspendus'], 1)

        # lever_suspension bloqué pour commercial et R.C. (403)
        self.assertEqual(
            self.client.post('/api/airbnb/facturation/lever_suspension/', {
                'client_id': self.c1.id, 'motif': 'Test',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(user=self.rc)
        self.assertEqual(
            self.client.post('/api/airbnb/facturation/lever_suspension/', {
                'client_id': self.c1.id, 'motif': 'Test',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # R.F. sans motif -> 400
        self.client.force_authenticate(user=self.rf)
        self.assertEqual(
            self.client.post('/api/airbnb/facturation/lever_suspension/', {
                'client_id': self.c1.id,
            }).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        # R.F. avec motif -> 200, client réactivé, commandes marquées réactivables + audit + notif
        with override_settings(D360_API_KEY='test-key'), patch(
            'airbnb.services.notification_service.WhatsAppService.send_template_message'
        ) as mock_wa:
            ok = self.client.post('/api/airbnb/facturation/lever_suspension/', {
                'client_id': self.c1.id,
                'motif': 'Virement compensé validé par direction financière',
            }, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.statut_airbnb, 'actif')
        cmd_susp.refresh_from_db()
        self.assertTrue(cmd_susp.reactivable_apres_suspension)
        self.assertEqual(ok.data['reactivable_count'], 1)
        self.assertTrue(
            JournalAuditAirbnb.objects.filter(
                entite='Client', entite_id=str(self.c1.id), action='suspension_levee_manuelle'
            ).exists()
        )
        self.assertTrue(
            AppNotification.objects.filter(type='airbnb_suspension', target_user=self.portal1).exists()
        )
        self.assertTrue(mock_wa.called)

    def test_a5_subscription_planning_conflicts_and_suggestions(self):
        today = timezone.localdate()
        # Trouver prochain lundi
        days_until_mon = (7 - today.weekday()) % 7 or 7
        next_mon = today + timedelta(days=days_until_mon)
        next_tue = next_mon + timedelta(days=1)
        next_wed = next_mon + timedelta(days=2)
        next_sun = next_mon + timedelta(days=6)

        ag_sub = Agent.objects.create(
            first_name='Aicha', last_name='Sub', phone='0601991101',
            poste='femme_menage', statut='disponible', city='Casablanca', neighborhood='Maarif',
        )
        ag_cont = Agent.objects.create(
            first_name='Salma', last_name='Cont', phone='0601991102',
            poste='femme_menage', statut='disponible', city='Casablanca', neighborhood='Maarif',
        )

        # Continuité via intervenante_2 sur commande facturée récente
        CommandeAirbnb.objects.create(
            numero='CMD-CONT-A5',
            bien=self.bien1,
            date_prestation=today - timedelta(days=5),
            statut='facturee',
            intervenante_2=ag_cont,
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
        )

        # Abonnement classique : Lundi 10h, Mercredi surchargé à 15h dans planning.semaines
        dem = Demande.objects.create(
            client=self.c1,
            service='menage_standard',
            statut=Demande.PRES_CONFIRMEE,
            mode_paiement='abonnement',
        )
        dem.profils_envoyes.add(ag_sub)
        SubscriptionPlanning.objects.create(
            demande=dem,
            date_debut=next_mon,
            date_fin=next_sun,
            jours_intervention=['lundi', 'mercredi'],
            heure_debut=time(10, 0),
            semaines=[{
                'date_debut': str(next_mon),
                'date_fin': str(next_sun),
                'jours': {
                    'lundi': {'selected': True, 'heure_debut': '10:00'},
                    'mercredi': {'selected': True, 'heure_debut': '15:00'},
                },
            }],
        )

        self.client.force_authenticate(user=self.ops_co)
        # Lundi 10h : ag_sub en conflit, ag_cont dispo + continuité + zone récente
        r_mon = self.client.get(
            f'/api/airbnb/commandes/suggestions_intervenantes/?bien_id={self.bien1.id}&date={next_mon}&heure=10:00'
        )
        self.assertEqual(r_mon.status_code, status.HTTP_200_OK)
        by_id_mon = {x['id']: x for x in r_mon.data['suggestions']}
        self.assertFalse(by_id_mon[ag_sub.id]['disponible'])
        self.assertTrue(by_id_mon[ag_cont.id]['disponible'])
        self.assertGreaterEqual(by_id_mon[ag_cont.id]['continuite_bien'], 1)
        self.assertTrue(by_id_mon[ag_cont.id]['zone_recente'])

        # Mardi 10h : ag_sub n'a AUCUNE intervention (pas de faux positif sur mardi)
        r_tue = self.client.get(
            f'/api/airbnb/commandes/suggestions_intervenantes/?bien_id={self.bien1.id}&date={next_tue}&heure=10:00'
        )
        by_id_tue = {x['id']: x for x in r_tue.data['suggestions']}
        self.assertTrue(by_id_tue[ag_sub.id]['disponible'])
        self.assertEqual(by_id_tue[ag_sub.id]['charge_jour'], 0)

        # Mercredi 10h : ag_sub intervient à 15h donc 10h-14h est libre, mais charge_jour == 1
        r_wed_10 = self.client.get(
            f'/api/airbnb/commandes/suggestions_intervenantes/?bien_id={self.bien1.id}&date={next_wed}&heure=10:00'
        )
        by_id_w10 = {x['id']: x for x in r_wed_10.data['suggestions']}
        self.assertTrue(by_id_w10[ag_sub.id]['disponible'])
        self.assertEqual(by_id_w10[ag_sub.id]['charge_jour'], 1)

        # Mercredi 14h : 14h-18h chevauche l'occurrence surchargée à 15h
        r_wed_14 = self.client.get(
            f'/api/airbnb/commandes/suggestions_intervenantes/?bien_id={self.bien1.id}&date={next_wed}&heure=14:00'
        )
        by_id_w14 = {x['id']: x for x in r_wed_14.data['suggestions']}
        self.assertFalse(by_id_w14[ag_sub.id]['disponible'])

    def test_a6_signalements_objet_oublie_and_acces_impossible(self):
        cmd = CommandeAirbnb.objects.create(
            numero='CMD-SIG-A6',
            bien=self.bien1,
            date_prestation=timezone.localdate() + timedelta(days=1),
            statut='assignee',
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
        )
        self.client.force_authenticate(user=self.ops_co)

        # objet_oublie -> auto-crée ObjetTrouve + WhatsApp B4
        with override_settings(D360_API_KEY='test-key'), patch(
            'airbnb.services.notification_service.WhatsAppService.send_template_message'
        ) as mock_wa:
            r_obj = self.client.post('/api/airbnb/signalements/', {
                'commande': cmd.id,
                'motif': 'objet_oublie',
                'description': 'Montre oubliée sur table de nuit',
                'piece': 'Chambre principale',
                'photos': ['/media/montre.jpg'],
            }, format='json')
        self.assertEqual(r_obj.status_code, status.HTTP_201_CREATED)
        obj_cree = ObjetTrouve.objects.filter(commande=cmd, description__icontains='Montre').first()
        self.assertIsNotNone(obj_cree)
        self.assertEqual(obj_cree.statut, 'trouve')
        self.assertIsNotNone(obj_cree.signale_le)
        wa_templates = [c.kwargs.get('template_name') for c in mock_wa.call_args_list]
        self.assertIn('airbnb_objet_trouve_signale', wa_templates)

        # acces_impossible -> suspend la commande + audit + alertes + verrou PATCH
        r_acc = self.client.post('/api/airbnb/signalements/', {
            'commande': cmd.id,
            'motif': 'acces_impossible',
            'description': 'Boîte à clé bloquée, code invalide',
        }, format='json')
        self.assertEqual(r_acc.status_code, status.HTTP_201_CREATED)
        cmd.refresh_from_db()
        self.assertEqual(cmd.statut, 'suspendue')
        self.client.force_authenticate(user=self.rc)
        self.assertEqual(
            self.client.patch(f'/api/airbnb/commandes/{cmd.id}/', {'consigne_ponctuelle': 'Bypass'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertTrue(
            JournalAuditAirbnb.objects.filter(
                entite='CommandeAirbnb', entite_id=str(cmd.id), action='suspension_commande_acces_impossible'
            ).exists()
        )

        # Résolution via arbitrer (reprendre -> saisie)
        self.client.force_authenticate(user=self.ops_ro)
        arb_resp = self.client.post(
            f"/api/airbnb/signalements/{r_acc.data['id']}/arbitrer/",
            {'decision_commande': 'reprendre', 'commentaire': 'Nouveau code reçu'},
            format='json',
        )
        self.assertEqual(arb_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(arb_resp.data.get('commande_statut'), 'saisie')
        cmd.refresh_from_db()
        self.assertEqual(cmd.statut, 'saisie')

    def test_a7_dispatch_20h_persists_pdf_url_and_post_dispatch_notify(self):
        from django.core.files.storage import default_storage
        tomorrow = timezone.localdate() + timedelta(days=1)
        ag1 = Agent.objects.create(
            first_name='Khadija', last_name='A', phone='0601001122',
            whatsapp='0601001122', poste='femme_menage', statut='disponible',
        )
        ag2 = Agent.objects.create(
            first_name='Meryem', last_name='B', phone='0601001123',
            whatsapp='0601001123', poste='femme_menage', statut='disponible',
        )
        cmd = CommandeAirbnb.objects.create(
            numero='CMD-PDF-A7',
            bien=self.bien1,
            date_prestation=tomorrow,
            statut='assignee',
            intervenante=ag1,
            runner=self.runner,
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
        )
        with override_settings(D360_API_KEY='test-key'), patch(
            'airbnb.services.notification_service.WhatsAppService.send_template_message'
        ) as mock_wa:
            call_command('dispatch_whatsapp_20h', date=str(tomorrow))
        cmd.refresh_from_db()
        self.assertTrue(bool(cmd.fiche_mission_pdf_url))
        self.assertIsNotNone(cmd.fiche_envoyee_le)
        rel_path = cmd.fiche_mission_pdf_url.split('/media/', 1)[-1]
        self.assertTrue(default_storage.exists(rel_path))
        self.assertTrue(
            any(c.kwargs.get('media_url') for c in mock_wa.call_args_list)
        )

        # Réassignation après dispatch -> régénération PDF + notification agent + runner
        self.client.force_authenticate(user=self.ops_co)
        with override_settings(D360_API_KEY='test-key'), patch(
            'airbnb.services.notification_service.WhatsAppService.send_template_message'
        ) as mock_post:
            r_assign = self.client.post(f'/api/airbnb/commandes/{cmd.id}/assigner/', {
                'intervenante_id': ag2.id,
                'runner_id': self.runner.id,
            }, format='json')
        self.assertEqual(r_assign.status_code, status.HTTP_200_OK)
        self.assertTrue(mock_post.called)

    def test_a8_linen_metadata_runner_tournee_and_premier_passage(self):
        today = timezone.localdate()
        # Avertissement premier passage sans stock filet sur commande dépôt
        self.client.force_authenticate(user=self.com)
        warn_resp = self.client.post('/api/airbnb/commandes/', {
            'bien': self.bien1.id,
            'date_prestation': str(today + timedelta(days=3)),
            'creneau': 'matin',
            'nature_linge': 'depot_seul',
        }, format='json')
        self.assertEqual(warn_resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('avertissement_premier_passage', warn_resp.data)

        # Filet d'hier invisible pour le runner (404), filet d'aujourd'hui visible
        cmd_yest = CommandeAirbnb.objects.create(
            numero='CMD-RUN-YEST', bien=self.bien1, date_prestation=today - timedelta(days=1),
            runner=self.runner, nature_linge='depot_ramassage', statut='cloturee',
            photos_cloture=['1', '2', '3', '4'],
        )
        filet_yest = FiletLinge.objects.create(
            code_filet='SAC-YEST-01', bien=self.bien1, commande_ramassage=cmd_yest,
        )
        cmd_today = CommandeAirbnb.objects.create(
            numero='CMD-RUN-TODAY', bien=self.bien1, date_prestation=today,
            runner=self.runner, nature_linge='depot_ramassage', statut='assignee',
        )
        CommandeAirbnb.objects.create(
            numero='CMD-RUN-PROP', bien=self.bien1, date_prestation=today,
            runner=self.runner, nature_linge='depot_ramassage', statut='proposition',
        )
        filet_today = FiletLinge.objects.create(
            code_filet='SAC-TODAY-01', bien=self.bien1, commande_ramassage=cmd_today,
        )

        self.client.force_authenticate(user=self.runner)
        self.assertEqual(
            self.client.get(f'/api/airbnb/filets/{filet_yest.id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # Comptage plat avec métadonnées -> aucune facturation 5 DH des métadonnées
        flat_resp = self.client.post(f'/api/airbnb/filets/{filet_today.id}/compter_runner/', {
            'draps': 2,
            'remplissage_pct': 85,
            'necessite_second_filet': True,
            'custom_meta_non_article': 10,
        }, format='json')
        self.assertEqual(flat_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(flat_resp.data['details']['total_runner'], 2)
        self.assertEqual(flat_resp.data['details']['calcul']['total_pieces'], 2)
        self.assertNotIn('montant', flat_resp.data['details']['calcul'])
        filet_today.refresh_from_db()
        self.assertEqual(filet_today.montant, Decimal('50.00'))

        # Tournée runner : exclut 'proposition' et signale l'absence de filet prêt
        tournee = self.client.get('/api/airbnb/filets/tournee_runner/')
        self.assertEqual(tournee.status_code, status.HTTP_200_OK)
        nums = [m['numero'] for m in tournee.data['missions_runner']]
        self.assertIn('CMD-RUN-TODAY', nums)
        self.assertNotIn('CMD-RUN-PROP', nums)
        self.assertGreaterEqual(len(tournee.data['alertes_filets_non_prets']), 1)

    def test_a9_billing_probatoire_remise_partial_cancel_and_geste(self):
        # 1. Probatoire auto-initialisé sur Client.save() quand mensuel
        c_mens = Client.objects.create(
            first_name='Karim', last_name='Mens', phone='0600771122',
            mode_paiement_airbnb='mensuel',
            type_client_airbnb='conciergerie',
            eligible_conciergerie=True,
        )
        self.assertIsNotNone(c_mens.date_demarrage_airbnb)
        self.assertIsNotNone(c_mens.probatoire_jusqu_au)

        # 2. Sortie probatoire entre le 11 et le 25 (pas de double facturation du 26->10)
        c_exit = Client.objects.create(
            first_name='Salim', last_name='Exit', phone='0600771133',
            mode_paiement_airbnb='mensuel',
            date_demarrage_airbnb=date(2026, 9, 15),
            probatoire_jusqu_au=date(2026, 11, 15),
            type_client_airbnb='conciergerie',
            eligible_conciergerie=True,
        )
        b_exit = Bien.objects.create(
            code='SEX-CAS-001', nom_bien='Bien Exit', client=c_exit,
            ville='Casablanca', quartier='Anfa', adresse='Rue E', typologie='2ch',
        )
        cmd_q1 = CommandeAirbnb.objects.create(
            numero='CMD-EXIT-Q1', bien=b_exit, date_prestation=date(2026, 11, 2),
            nature_linge='sans_linge', photos_cloture=['1', '2', '3', '4'],
            statut='facturable', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
        )
        cmd_q2 = CommandeAirbnb.objects.create(
            numero='CMD-EXIT-Q2', bien=b_exit, date_prestation=date(2026, 11, 18),
            nature_linge='sans_linge', photos_cloture=['1', '2', '3', '4'],
            statut='facturable', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
        )
        res_11 = generer_factures_cycle(target_date=date(2026, 11, 11), user=self.rf, client_id=c_exit.id)
        self.assertEqual(len(res_11['factures']), 1)
        self.assertEqual(res_11['factures'][0].periode_debut, date(2026, 10, 26))
        self.assertEqual(res_11['factures'][0].periode_fin, date(2026, 11, 10))
        self.assertEqual(res_11['factures'][0].montant_total, Decimal('160.00'))

        res_26 = generer_factures_cycle(target_date=date(2026, 11, 26), user=self.rf, client_id=c_exit.id)
        self.assertEqual(len(res_26['factures']), 1)
        f_trans = res_26['factures'][0]
        self.assertEqual(f_trans.periode_debut, date(2026, 11, 11))
        self.assertEqual(f_trans.periode_fin, date(2026, 11, 25))
        self.assertEqual(f_trans.montant_total, Decimal('160.00'))
        cmd_q1.refresh_from_db()
        cmd_q2.refresh_from_db()
        self.assertEqual(cmd_q1.statut, 'facturee')
        self.assertEqual(cmd_q2.statut, 'facturee')

        # 3. Remise en état 'signalee' bloque facturabilité
        cmd_rem = CommandeAirbnb.objects.create(
            numero='CMD-REM-BLK', bien=self.bien1, date_prestation=timezone.localdate(),
            statut='cloturee', photos_cloture=['1', '2', '3', '4'],
            remise_en_etat_statut='signalee',
        )
        ok_fact, reasons = is_commande_facturable(cmd_rem)
        self.assertFalse(ok_fact)
        self.assertTrue(any('remise' in r.lower() for r in reasons))

        # 4. Geste commercial sur facture créée directement sans lignes préexistantes
        fac_direct = Facture.objects.create(
            numero='FAC-DIRECT-BASE', client=self.c1, source=Facture.SOURCE_AIRBNB,
            mode_facturation='passage', date_emission=timezone.localdate(),
            date_echeance=timezone.localdate() + timedelta(days=4),
            montant_total=Decimal('300.00'), statut=Facture.EN_ATTENTE,
        )
        appliquer_geste_commercial(fac_direct, Decimal('50.00'), designation='Geste', motif='Retard', user=self.rf)
        fac_direct.refresh_from_db()
        self.assertEqual(fac_direct.montant_total, Decimal('250.00'))

        # 5. Annulation partielle d'une facture multi-commandes
        c_p1 = CommandeAirbnb.objects.create(
            numero='CMD-PART-1', bien=self.bien1, date_prestation=timezone.localdate(),
            statut='facturable', prix_menage=Decimal('160.00'), total_ttc=Decimal('160.00'),
        )
        c_p2 = CommandeAirbnb.objects.create(
            numero='CMD-PART-2', bien=self.bien1, date_prestation=timezone.localdate(),
            statut='facturable', prix_menage=Decimal('200.00'), total_ttc=Decimal('200.00'),
        )
        fac_multi = Facture.objects.create(
            numero='FAC-MULTI-PART', client=self.c1, source=Facture.SOURCE_AIRBNB,
            mode_facturation='mensuel', date_emission=timezone.localdate(),
            date_echeance=timezone.localdate() + timedelta(days=4),
            montant_total=Decimal('360.00'), statut=Facture.EN_ATTENTE,
        )
        FactureLigneAirbnb.objects.create(
            facture=fac_multi, commande=c_p1, type_ligne='prestation', designation='Presta 1',
            montant=Decimal('160.00'),
        )
        FactureLigneAirbnb.objects.create(
            facture=fac_multi, commande=c_p2, type_ligne='prestation', designation='Presta 2',
            montant=Decimal('200.00'),
        )
        c_p1.statut = 'facturee'
        c_p1.facture = fac_multi
        c_p1.save(update_fields=['statut', 'facture'])
        c_p2.statut = 'facturee'
        c_p2.facture = fac_multi
        c_p2.save(update_fields=['statut', 'facture'])

        self.client.force_authenticate(user=self.rf)
        part_resp = self.client.post(f'/api/airbnb/facturation/{fac_multi.id}/annuler_facture/', {
            'commande_id': c_p1.id,
            'motif': 'Prestation 1 reportée en avoir',
        }, format='json')
        self.assertEqual(part_resp.status_code, status.HTTP_200_OK)
        fac_multi.refresh_from_db()
        c_p1.refresh_from_db()
        c_p2.refresh_from_db()
        self.assertEqual(fac_multi.statut, Facture.EN_ATTENTE)
        self.assertEqual(fac_multi.montant_total, Decimal('200.00'))
        self.assertEqual(c_p1.statut, 'facturable')
        self.assertIsNone(c_p1.facture)
        self.assertEqual(c_p2.statut, 'facturee')
        self.assertEqual(c_p2.facture_id, fac_multi.id)

    def test_a10_role_cloisonnement_non_airbnb_and_cron_scoping(self):
        AppNotification.objects.create(
            type='nouvelle_demande',
            title='Demande classique interne',
            message='Doit être masqué pour R.F.',
        )
        for u in (self.portal1, self.runner, self.rl, self.rf):
            self.client.force_authenticate(user=u)
            for url in ('/api/missions/', '/api/demandes/', '/api/audit/', '/api/documents/'):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN, msg=f'{u.role} -> {url}')

        for u in (self.runner, self.rl):
            self.client.force_authenticate(user=u)
            self.assertEqual(self.client.get('/api/clients/').status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.rf)
        notifs = self.client.get('/api/notifications/')
        self.assertEqual(notifs.status_code, status.HTTP_200_OK)
        items = notifs.data['results'] if isinstance(notifs.data, dict) else notifs.data
        self.assertFalse(any(n.get('type') == 'nouvelle_demande' for n in items))

        # charge_operations peut lancer les crons ops, mais pas facturation
        self.client.force_authenticate(user=self.ops_co)
        self.assertEqual(
            self.client.post('/api/airbnb/facturation/lancer_cron/', {'job': 'remontee_tdb_18h'}).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post('/api/airbnb/facturation/lancer_cron/', {'job': 'generer_factures_airbnb'}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_b1_b2_b3_b4_b5_audit_items(self):
        # B1: Options négatives & options libres non autorisées
        self.client.force_authenticate(user=self.com)
        future_d = str(timezone.localdate() + timedelta(days=4))
        self.assertEqual(
            self.client.post('/api/airbnb/commandes/', {
                'bien': self.bien1.id, 'date_prestation': future_d,
                'options': [{'code': 'reassort_essentiel', 'prix': '-10'}],
            }, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post('/api/airbnb/commandes/', {
                'bien': self.bien1.id, 'date_prestation': future_d,
                'options': [{'code': 'custom_hack', 'prix': '1'}],
            }, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.client.force_authenticate(user=self.rc)
        rc_ok = self.client.post('/api/airbnb/commandes/', {
            'bien': self.bien1.id, 'date_prestation': future_d,
            'options': [{'code': 'prestation_speciale', 'prix': '45'}],
        }, format='json')
        self.assertEqual(rc_ok.status_code, status.HTTP_201_CREATED)

        # B2: GrilleTarifaireVersion immuable (PUT/PATCH/DELETE -> 405)
        grille = GrilleTarifaireVersion.objects.first() or create_grille_tarifaire_version(
            version_label='v-b2-test', date_entree_vigueur=timezone.localdate(), user=self.admin,
        )
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(
            self.client.patch(f'/api/airbnb/grilles-tarifaires/{grille.id}/', {'studio': '99'}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(f'/api/airbnb/grilles-tarifaires/{grille.id}/').status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        # B3: BienViewSet.stats ne compte pas en_validation vers >=3 et inclut clients à 0 actif
        c_zero = Client.objects.create(
            first_name='Zero', last_name='Actif', phone='0600881234',
            type_client_airbnb='particulier_sous_seuil', assigned_commercial=self.com,
        )
        for i in range(1, 4):
            Bien.objects.create(
                code=f'ZAC-CAS-{i:03d}', nom_bien=f'Pending {i}', client=c_zero,
                ville='Casablanca', quartier='Anfa', adresse='Rue Z', typologie='studio',
                statut_activation='en_validation', is_active=True,
            )
        self.client.force_authenticate(user=self.com)
        stats_resp = self.client.get('/api/airbnb/biens/stats/')
        self.assertEqual(stats_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(stats_resp.data['clients_sous_seuil_alerte'], 1)

        # B4: ObjetTrouve crée WhatsApp avec template objet_trouve_signale
        cmd_b4 = CommandeAirbnb.objects.create(
            numero='CMD-B4-OBJ', bien=self.bien1, date_prestation=timezone.localdate(), statut='en_cours',
        )
        with override_settings(D360_API_KEY='test-key'), patch(
            'airbnb.services.notification_service.WhatsAppService.send_template_message'
        ) as mock_wa_b4:
            self.client.force_authenticate(user=self.ops_co)
            obj_resp = self.client.post('/api/airbnb/objets-trouves/', {
                'bien': self.bien1.id, 'commande': cmd_b4.id, 'description': 'Passeport', 'piece': 'Salon',
            }, format='json')
        self.assertEqual(obj_resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('airbnb_objet_trouve_signale', [c.kwargs.get('template_name') for c in mock_wa_b4.call_args_list])

        # B5: FiletLingeViewSet.deposer garde-fous
        cmd_pickup_b5 = CommandeAirbnb.objects.create(
            numero='CMD-B5-PICK', bien=self.bien1, date_prestation=timezone.localdate(),
            nature_linge='ramassage_seul', runner=self.runner,
        )
        filet_b5 = FiletLinge.objects.create(
            code_filet='SAC-B5-01', bien=self.bien1, commande_ramassage=cmd_pickup_b5, statut='recu_laverie',
        )
        cmd_depot_bad_bien = CommandeAirbnb.objects.create(
            numero='CMD-B5-BAD', bien=self.bien2, date_prestation=timezone.localdate(),
            nature_linge='depot_seul', runner=self.runner,
        )
        cmd_depot_rabat = CommandeAirbnb.objects.create(
            numero='CMD-B5-RAB', bien=self.bien_rabat, date_prestation=timezone.localdate(),
            nature_linge='menage_seul',
        )
        cmd_depot_ok = CommandeAirbnb.objects.create(
            numero='CMD-B5-OK', bien=self.bien1, date_prestation=timezone.localdate(),
            nature_linge='depot_seul', runner=self.runner,
        )
        self.client.force_authenticate(user=self.runner)
        self.assertEqual(
            self.client.post(f'/api/airbnb/filets/{filet_b5.id}/deposer/', {'commande_depot_id': cmd_depot_ok.id}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        filet_b5.statut = 'pret'
        filet_b5.save(update_fields=['statut'])
        self.assertEqual(
            self.client.post(f'/api/airbnb/filets/{filet_b5.id}/deposer/', {'commande_depot_id': cmd_depot_bad_bien.id}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(f'/api/airbnb/filets/{filet_b5.id}/deposer/', {'commande_depot_id': cmd_depot_rabat.id}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        ok_dep = self.client.post(
            f'/api/airbnb/filets/{filet_b5.id}/deposer/', {'commande_depot_id': cmd_depot_ok.id}, format='json'
        )
        self.assertEqual(ok_dep.status_code, status.HTTP_200_OK)
        self.assertEqual(ok_dep.data['statut'], 'depose')
