from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from agents.models import Agent
from clients.models import Client
from demandes.models import Demande
from missions.models import Mission
from finance.models import Facture, Paiement, EntreeCaisse


class Command(BaseCommand):
    help = "Injecte des donnees fictives finance (missions, factures, paiements, caisse)."

    def handle(self, *args, **options):
        today = timezone.localdate()

        user, _ = User.objects.get_or_create(
            email='finance.demo@agencemenage.local',
            defaults={
                'first_name': 'Finance',
                'last_name': 'Demo',
                'role': User.ADMIN,
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if not user.has_usable_password():
            user.set_password('Demo1234!')
            user.save(update_fields=['password'])

        clients_data = [
            ('Houda', '', '0700000001', Client.PARTICULIER, 'Casablanca'),
            ('Meriem', '', '0700000002', Client.PARTICULIER, 'Casablanca'),
            ('Julien', 'Client', '0700000003', Client.PARTICULIER, 'Rabat'),
            ('', '', '0700000004', Client.ENTREPRISE, 'Casablanca'),
        ]
        clients = []
        for first_name, last_name, phone, segment, city in clients_data:
            defaults = {
                'last_name': last_name,
                'segment': segment,
                'city': city,
            }
            if segment == Client.ENTREPRISE:
                defaults['entity_name'] = 'Alpha Services'
                defaults['contact_person'] = 'Nora Amiri'
                defaults['first_name'] = ''
                defaults['last_name'] = ''
            else:
                defaults['first_name'] = first_name
                defaults['last_name'] = last_name

            client, _ = Client.objects.get_or_create(phone=phone, defaults=defaults)
            clients.append(client)

        agents_data = [
            ('Bonr', 'Karidja', '0711000001', Agent.DISPONIBLE, 'Casablanca'),
            ('Harit', 'Imane', '0711000002', Agent.DISPONIBLE, 'Casablanca'),
            ('Flean', 'Parfaite', '0711000003', Agent.DISPONIBLE, 'Casablanca'),
        ]
        agents = []
        for first_name, last_name, phone, statut, city in agents_data:
            agent, _ = Agent.objects.get_or_create(
                phone=phone,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'statut': statut,
                    'city': city,
                    'poste': 'femme_menage',
                },
            )
            agents.append(agent)

        demandes = []
        demandes_seed = [
            (clients[0], 'Grand menage', Decimal('1200.00'), Demande.SUR_PLACE, Demande.INTEGRAL, today - timedelta(days=32), Demande.PARTICULIER),
            (clients[1], 'Menage Air BnB', Decimal('500.00'), Demande.AGENCE, Demande.NON_PAYE, today - timedelta(days=20), Demande.PARTICULIER),
            (clients[2], 'Menage post-sinistre', Decimal('800.00'), Demande.VIREMENT, Demande.PARTIEL, today - timedelta(days=14), Demande.PARTICULIER),
            (clients[3], 'Menage bureaux', Decimal('2400.00'), Demande.CHEQUE, Demande.ACOMPTE, today - timedelta(days=8), Demande.ENTREPRISE),
            (clients[0], 'Nettoyage fin de chantier', Decimal('1800.00'), Demande.VIREMENT, Demande.INTEGRAL, today - timedelta(days=4), Demande.PARTICULIER),
        ]

        for index, (client, service, prix, mode_paiement, statut_paiement, date_intervention, segment) in enumerate(demandes_seed, start=1):
            demande, _ = Demande.objects.get_or_create(
                client=client,
                service=service,
                date_intervention=date_intervention,
                defaults={
                    'segment': segment,
                    'source': Demande.BACKOFFICE,
                    'statut': Demande.TERMINE,
                    'prix': prix,
                    'mode_paiement': mode_paiement,
                    'statut_paiement': statut_paiement,
                    'assigned_to': user,
                    'frequency': Demande.ONCE,
                    'frequency_label': 'Une fois',
                    'cao': True,
                },
            )
            demandes.append(demande)

            Mission.objects.get_or_create(
                demande=demande,
                agent=agents[index % len(agents)],
                defaults={
                    'statut': Mission.TERMINEE,
                    'date_debut': timezone.now() - timedelta(days=index * 3),
                    'date_fin': timezone.now() - timedelta(days=index * 3 - 1),
                    'notes': 'Mission seed finance',
                    'created_by': user,
                },
            )

        for idx, demande in enumerate(demandes, start=1):
            numero = f'FAC-2026-{idx:04d}'
            montant_total = demande.prix or Decimal('0')
            facture, _ = Facture.objects.get_or_create(
                numero=numero,
                defaults={
                    'client': demande.client,
                    'demande': demande,
                    'montant_total': montant_total,
                    'montant_paye': Decimal('0'),
                    'statut': Facture.EN_ATTENTE,
                    'date_echeance': (demande.date_intervention or today) + timedelta(days=10),
                    'created_by': user,
                    'notes': 'Facture creee par seed',
                },
            )

            if idx % 3 == 0:
                Paiement.objects.get_or_create(
                    facture=facture,
                    montant=montant_total,
                    mode=Paiement.VIREMENT,
                    date=(demande.date_intervention or today) + timedelta(days=1),
                    defaults={
                        'reference': f'PAY-{idx:04d}',
                        'notes': 'Paiement integral seed',
                        'created_by': user,
                    },
                )
                facture.montant_paye = montant_total
                facture.statut = Facture.PAYE
                facture.save(update_fields=['montant_paye', 'statut'])
            elif idx % 2 == 0:
                partiel = (montant_total * Decimal('0.5')).quantize(Decimal('0.01'))
                Paiement.objects.get_or_create(
                    facture=facture,
                    montant=partiel,
                    mode=Paiement.ESPECES,
                    date=(demande.date_intervention or today) + timedelta(days=2),
                    defaults={
                        'reference': f'PAY-{idx:04d}',
                        'notes': 'Paiement partiel seed',
                        'created_by': user,
                    },
                )
                facture.montant_paye = partiel
                facture.statut = Facture.PARTIEL
                facture.save(update_fields=['montant_paye', 'statut'])

        mouvements_seed = [
            (EntreeCaisse.ENTREE, Decimal('350.00'), 'Fond de la caisse', today - timedelta(days=30), EntreeCaisse.ESPECES, 'maria', ''),
            (EntreeCaisse.SORTIE, Decimal('120.00'), 'Achat produits menagers', today - timedelta(days=27), EntreeCaisse.ESPECES, '', 'Ravitaillement'),
            (EntreeCaisse.ENTREE, Decimal('800.00'), 'Reglement mission MSN-0009', today - timedelta(days=20), EntreeCaisse.VIREMENT, 'Julien Client', ''),
            (EntreeCaisse.ENTREE, Decimal('600.00'), 'Paiement entreprise Alpha', today - timedelta(days=10), EntreeCaisse.CHEQUE, 'Alpha Services', ''),
            (EntreeCaisse.SORTIE, Decimal('300.00'), 'Versement profil Flean Parfaite', today - timedelta(days=7), EntreeCaisse.PAIEMENT_AGENCE, '', 'Reglement interne'),
            (EntreeCaisse.ENTREE, Decimal('950.00'), 'Paiement mission urgente', today - timedelta(days=2), EntreeCaisse.ESPECES, 'Houda', ''),
        ]

        for t, montant, description, date_mouvement, mode, client_nom, notes in mouvements_seed:
            EntreeCaisse.objects.get_or_create(
                type_mouvement=t,
                montant=montant,
                description=description,
                date=date_mouvement,
                defaults={
                    'mode_paiement': mode,
                    'client_nom': client_nom,
                    'utilisateur': user.full_name,
                    'notes': notes,
                    'created_by': user,
                },
            )

        self.stdout.write(self.style.SUCCESS('Donnees finance fictives injectees avec succes.'))
