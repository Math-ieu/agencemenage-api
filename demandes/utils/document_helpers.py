import datetime
from django.core.files.base import ContentFile
from ..models import Document
from .document_generators import generate_devis_pdf, generate_recap_png

def generate_demande_document(demande, doc_type, user=None):
    """
    Logic to generate a document (devis or png) and save it.
    """
    client = demande.client
    client_nom = client.display_name if client else "Client"
    client_phone = client.phone if client else ""
    client_adresse = demande.formulaire_data.get('adresse', client.neighborhood if client else "")
    
    data = {
        'numero': str(demande.pk),
        'date': datetime.datetime.now().strftime("%d %B %Y"),
        'client_nom': client_nom,
        'client_telephone': client_phone,
        'client_adresse': client_adresse,
        'service_type': demande.service,
        'segment': demande.get_segment_display(),
        'intervenants': demande.formulaire_data.get('nb_intervenants', demande.formulaire_data.get('nb_personnel', 1)),
        'frequence': demande.frequency_label or demande.get_frequency_display(),
        'total': f"{demande.prix}" if demande.prix else "À définir"
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
