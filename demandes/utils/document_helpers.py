import datetime
from django.core.files.base import ContentFile
from ..models import Document
from .document_generators import generate_devis_pdf, generate_recap_png
from .invoice_generator import generate_invoice, InvoiceData, InvoiceItem

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


def generate_demande_document(demande, doc_type, user=None, month_index=None):
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
        'description': form_data.get('description', ''),
        'is_autre_service': form_data.get('is_autre_service', False),
        'duration_unit': form_data.get('duration_unit', 'heures'),
        'tva_active': form_data.get('tva_active', True),
    }

    if doc_type == 'devis':
        content_bytes = generate_devis_pdf(data)
        filename = f"DEVIS_{client_nom.replace(' ', '_')}_{demande.pk}.pdf"
        db_content_type = Document.DEVIS
    elif doc_type == 'facture':
        if month_index:
            try:
                month_idx_int = int(month_index)
            except (ValueError, TypeError):
                month_idx_int = 1
                
            weeks = demande.planning.semaines if (demande.planning and demande.planning.semaines) else []
            max_month = 1
            for w in weeks:
                if isinstance(w, dict) and w.get('mois', 1) > max_month:
                    max_month = w.get('mois', 1)
            
            monthly_price = float(demande.prix) / max_month if (demande.prix and max_month > 0) else 0.0
            items = [
                InvoiceItem(f"{demande.service} - Mois {month_idx_int}", monthly_price)
            ]
            invoice_number = f"AM/F{demande.pk:03d}-M{month_idx_int}/{datetime.datetime.now().year}"
            filename = f"FACTURE_{client_nom.replace(' ', '_')}_{demande.pk}_M{month_idx_int}.pdf"
        else:
            items = [
                InvoiceItem(demande.service, float(demande.prix or 0))
            ]
            invoice_number = f"AM/F{demande.pk:03d}/{datetime.datetime.now().year}"
            filename = f"FACTURE_{client_nom.replace(' ', '_')}_{demande.pk}.pdf"
            
        invoice_data = InvoiceData(
            invoice_number=invoice_number,
            invoice_date=datetime.date.today(),
            client_name=client_nom,
            client_ice=form_data.get('ice', ''),
            client_address=client_adresse,
            service_type=demande.service if not month_index else f"{demande.service} - Mois {month_index}",
            frequency=resolve_frequency_label(demande),
            items=items,
            tva_rate=0.20 if form_data.get('tva_active') else 0.00
        )
        
        content_bytes = generate_invoice(invoice_data).read()
        db_content_type = Document.FACTURE
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

