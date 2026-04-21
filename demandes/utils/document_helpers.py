import datetime
from django.core.files.base import ContentFile
from ..models import Document
from .document_generators import generate_devis_pdf, generate_recap_png

# Human-readable labels for all frequency codes sent from the frontend
FREQUENCY_LABELS = {
    'ponctuel': 'Une fois',
    'oneshot': 'Une fois',
    '1/sem': '1 fois / semaine',
    '2/sem': '2 fois / semaine',
    '3/sem': '3 fois / semaine',
    '4/sem': '4 fois / semaine',
    '5/sem': '5 fois / semaine',
    '6/sem': '6 fois / semaine',
    '7/sem': '7 fois / semaine (quotidien)',
    '1/mois': '1 fois / mois',
    '2/mois': '2 fois / mois',
    '3/mois': '3 fois / mois',
    '4/mois': '4 fois / mois',
    'quotidien': 'Quotidien',
}


def resolve_frequency_label(demande):
    """Return a human-readable frequency label from the stored frequency_label or frequency."""
    raw = demande.frequency_label or ''
    if raw in FREQUENCY_LABELS:
        return FREQUENCY_LABELS[raw]
    # Fallback to model's get_frequency_display
    return raw or demande.get_frequency_display()


def generate_demande_document(demande, doc_type, user=None):
    """
    Logic to generate a document (devis or png) and save it.
    """
    client = demande.client
    client_nom = client.display_name if client else "Client"
    client_phone = client.phone if client else ""
    form_data = demande.formulaire_data or {}
    client_adresse = form_data.get('adresse', client.neighborhood if client else "")
    
    data = {
        'numero': str(demande.pk),
        'date': datetime.datetime.now().strftime("%d %B %Y"),
        'client_nom': client_nom,
        'client_telephone': client_phone,
        'client_adresse': client_adresse,
        'service_type': demande.service,
        'segment': demande.get_segment_display(),
        'intervenants': form_data.get('nb_intervenants', form_data.get('nb_personnel', 1)),
        'frequence': resolve_frequency_label(demande),
        'total': f"{demande.prix}" if demande.prix else "À définir",
        # Extra fields from form (used if document templates are enriched)
        'type_habitation': form_data.get('type_habitation', ''),
        'surface': form_data.get('surface', ''),
        'duree': form_data.get('duree', ''),
        'ville': form_data.get('ville', ''),
        'quartier': form_data.get('quartier', ''),
    }

    if doc_type == 'devis':
        content_bytes = generate_devis_pdf(data)
        filename = f"DEVIS_{client_nom.replace(' ', '_')}_{demande.pk}.pdf"
        db_content_type = Document.DEVIS
    else:
        content_bytes = generate_recap_png(data)
        filename = f"RECAP_{client_nom.replace(' ', '_')}_{demande.pk}.png"
        db_content_type = Document.PNG
        
    doc = Document.objects.create(
        demande=demande,
        type_document=db_content_type,
        nom=filename,
        created_by=user
    )
    doc.fichier.save(filename, ContentFile(content_bytes))
    return doc

