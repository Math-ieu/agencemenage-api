import os
import django
import datetime

# Configure Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from clients.models import Client
from demandes.models import Demande
from demandes.constants import get_segment_from_service
from django.contrib.auth import get_user_model

User = get_user_model()

def create_pending_demandes():
    print("🚀 Démarrage de la création de demandes en attente...")
    
    # 1. Récupération d'un commercial s'il existe
    commercial = User.objects.filter(role='commercial').first() or User.objects.first()
    if commercial:
        print(f"👤 Commercial assigné par défaut : {commercial.username}")
    else:
        print("⚠️ Aucun utilisateur trouvé pour assignation par défaut.")

    # 2. Données clients fictifs réalistes (sans aucun mot "test")
    clients_data = [
        {
            'first_name': 'Amine',
            'last_name': 'El Amrani',
            'entity_name': '',
            'contact_person': '',
            'email': 'amine.amrani@gmail.com',
            'phone': '+212661234567',
            'segment': Client.PARTICULIER,
            'city': 'Casablanca',
            'neighborhood': 'Maârif',
            'address': '12, Rue Jura, Maârif',
        },
        {
            'first_name': 'Sarah',
            'last_name': 'Bennani',
            'entity_name': '',
            'contact_person': '',
            'email': 'sarah.bennani@yahoo.fr',
            'phone': '+212662345678',
            'segment': Client.PARTICULIER,
            'city': 'Casablanca',
            'neighborhood': 'Gauthier',
            'address': '45, Rue Gauthier, 3ème étage',
        },
        {
            'first_name': 'Youssef',
            'last_name': 'Tazi',
            'entity_name': '',
            'contact_person': '',
            'email': 'youssef.tazi@outlook.com',
            'phone': '+212663456789',
            'segment': Client.PARTICULIER,
            'city': 'Rabat',
            'neighborhood': 'Agdal',
            'address': '8, Avenue de France, Agdal',
        },
        {
            'first_name': 'Laila',
            'last_name': 'Alami',
            'entity_name': '',
            'contact_person': '',
            'email': 'laila.alami@gmail.com',
            'phone': '+212664567890',
            'segment': Client.PARTICULIER,
            'city': 'Casablanca',
            'neighborhood': 'Anfa',
            'address': '102, Boulevard d\'Anfa',
        },
        {
            'first_name': 'Karim',
            'last_name': 'Kadiri',
            'entity_name': '',
            'contact_person': '',
            'email': 'karim.kadiri@gmail.com',
            'phone': '+212665678901',
            'segment': Client.PARTICULIER,
            'city': 'Marrakech',
            'neighborhood': 'Gueliz',
            'address': 'Avenue Mohammed V, Résidence El Mansour',
        },
        {
            'first_name': 'Sofia',
            'last_name': 'Meziane',
            'entity_name': '',
            'contact_person': '',
            'email': 'sofia.meziane@gmail.com',
            'phone': '+212666789012',
            'segment': Client.PARTICULIER,
            'city': 'Casablanca',
            'neighborhood': 'Oasis',
            'address': '15, Rue des Lilas, Oasis',
        },
        {
            'first_name': 'Mehdi',
            'last_name': 'Filali',
            'entity_name': '',
            'contact_person': '',
            'email': 'mehdi.filali@gmail.com',
            'phone': '+212667890123',
            'segment': Client.PARTICULIER,
            'city': 'Casablanca',
            'neighborhood': 'Maârif',
            'address': '24, Rue de Libye',
        },
        {
            'first_name': '',
            'last_name': '',
            'entity_name': 'Tech Solutions Maroc',
            'contact_person': 'Meryem Toumi',
            'email': 'contact@techsolutions.ma',
            'phone': '+212522987654',
            'segment': Client.ENTREPRISE,
            'city': 'Casablanca',
            'neighborhood': 'Sidi Maarouf',
            'address': 'Casanearshore, Shore 1',
        },
        {
            'first_name': '',
            'last_name': '',
            'entity_name': 'Café Fleur de Sel',
            'contact_person': 'Rachid Mansouri',
            'email': 'direction@fleurdesel.ma',
            'phone': '+212522789123',
            'segment': Client.ENTREPRISE,
            'city': 'Casablanca',
            'neighborhood': 'Bourgogne',
            'address': '88, Boulevard de la Corniche',
        },
        {
            'first_name': '',
            'last_name': '',
            'entity_name': 'Cabinet Dentaire Dr. Alami',
            'contact_person': 'Dr. Laila Alami',
            'email': 'cabinet@alami-dentaire.ma',
            'phone': '+212537123456',
            'segment': Client.ENTREPRISE,
            'city': 'Rabat',
            'neighborhood': 'Hay Riad',
            'address': 'Angle Avenue Nakhil & Saria Ibn Zounaim',
        },
        {
            'first_name': '',
            'last_name': '',
            'entity_name': 'Immobilier Atlas Prestige',
            'contact_person': 'Jalal Bensouda',
            'email': 'j.bensouda@atlasprestige.ma',
            'phone': '+212524456789',
            'segment': Client.ENTREPRISE,
            'city': 'Marrakech',
            'neighborhood': 'Hivernage',
            'address': 'Rue de la Menara, Marrakech',
        }
    ]

    # 3. Association Services -> Clients fictifs
    # Nous créons une demande pour chaque type de service disponible.
    services_to_create = [
        # Particulier
        {"service": "Ménage standard", "client_idx": 0, "prix": 250.00},
        {"service": "Grand ménage", "client_idx": 1, "prix": 500.00},
        {"service": "Ménage Air BnB", "client_idx": 2, "prix": 350.00},
        {"service": "Ménage Airbnb", "client_idx": 6, "prix": 350.00},
        {"service": "Ménage fin de chantier", "client_idx": 3, "prix": 1200.00},
        {"service": "Auxiliaire de vie", "client_idx": 4, "prix": 1800.00},
        {"service": "Ménage post-sinistre", "client_idx": 5, "prix": 2500.00},
        # Entreprise
        {"service": "Ménage Bureaux", "client_idx": 7, "prix": 1500.00},
        {"service": "Placement & gestion", "client_idx": 8, "prix": 3000.00},
        {"service": "Ménage post-sinistre", "client_idx": 9, "prix": 3500.00},
        {"service": "Ménage fin de chantier", "client_idx": 10, "prix": 2800.00},
    ]

    # Date d'intervention future (dans 7 jours)
    future_date = datetime.date.today() + datetime.timedelta(days=7)

    created_count = 0
    for item in services_to_create:
        c_info = clients_data[item["client_idx"]]
        service_name = item["service"]
        prix = item["prix"]

        # Création ou récupération du client par son téléphone
        client, created = Client.objects.get_or_create(
            phone=c_info['phone'],
            defaults={
                'first_name': c_info['first_name'],
                'last_name': c_info['last_name'],
                'entity_name': c_info['entity_name'],
                'contact_person': c_info['contact_person'],
                'email': c_info['email'],
                'whatsapp': c_info['phone'],
                'segment': c_info['segment'],
                'city': c_info['city'],
                'neighborhood': c_info['neighborhood'],
                'address': c_info['address'],
                'assigned_commercial': commercial
            }
        )
        if created:
            print(f"🆕 Client créé : {client.display_name}")
        else:
            print(f"✅ Client existant trouvé : {client.display_name}")

        # Déterminer le segment du service
        segment = get_segment_from_service(service_name)

        # Créer la Demande en attente
        demande = Demande.objects.create(
            client=client,
            service=service_name,
            segment=segment,
            source=Demande.SITE,
            statut=Demande.EN_ATTENTE,
            frequency=Demande.ONCE,
            date_intervention=future_date,
            heure_intervention="09:00",
            preference_horaire="Matinée",
            prix=prix,
            mode_paiement=Demande.VIREMENT,
            statut_paiement=Demande.NON_PAYE,
            assigned_to=commercial,
            formulaire_data={
                "ville": client.city,
                "quartier": client.neighborhood,
                "adresse": client.address,
                "date_souhaitee": str(future_date),
                "note": "Demande initialisée automatiquement par script de population."
            }
        )
        print(f"   ↳ Demande créée : [ID: {demande.id}] [{segment}] {service_name} — {client.display_name}")
        created_count += 1

    print(f"\n🎉 Succès : {created_count} demandes en attente ont été créées !")

if __name__ == "__main__":
    create_pending_demandes()
