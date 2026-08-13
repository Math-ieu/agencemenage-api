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
        segment_val = (demande.segment or '').lower()
        client_seg = getattr(client, 'segment', '') if client else ''
        is_particulier = (
            segment_val in ['particulier', 'spp'] or 
            (client_seg and client_seg.lower() == 'particulier') or 
            (str(form_data.get('segment', '')).lower() == 'particulier') or
            (not segment_val and not client_seg)
        )

        # ── Gestion de la TVA (Non appliquée par défaut pour les particuliers) ──
        tva_active_raw = form_data.get('tva_active')
        if tva_active_raw is None:
            tva_active_raw = form_data.get('apply_tva')

        if tva_active_raw is not None:
            if isinstance(tva_active_raw, str):
                tva_active = tva_active_raw.lower() in ['true', 'oui', '1']
            else:
                tva_active = bool(tva_active_raw)
        else:
            # Règle : Pour les clients particuliers, ne jamais appliquer la TVA par défaut
            tva_active = False if is_particulier else True

        if tva_active:
            raw_tva = form_data.get('tva', form_data.get('tva_pct', form_data.get('tva_pourcentage', 20)))
            try:
                tva_rate = float(raw_tva) / 100.0 if float(raw_tva) > 0 else 0.20
            except (ValueError, TypeError):
                tva_rate = 0.20
        else:
            tva_rate = 0.0

        # ── Décomposition Montant Service & Réduction ──
        nb_passages = form_data.get('nombre_passages')
        prix_unitaire = form_data.get('prix_unitaire')

        montant_service = None
        if form_data.get('montant_service') is not None:
            try:
                montant_service = float(form_data.get('montant_service'))
            except (ValueError, TypeError):
                pass

        if (montant_service is None or montant_service <= 0) and nb_passages and prix_unitaire:
            try:
                montant_service = round(float(nb_passages) * float(prix_unitaire), 2)
            except (ValueError, TypeError):
                pass

        # Réduction
        remise_dh = 0.0
        remise_pct = 0.0
        for r_k in ['remise_dh', 'remise', 'reduction_montant', 'remise_montant']:
            if form_data.get(r_k) is not None:
                try:
                    remise_dh = float(form_data.get(r_k))
                    if remise_dh > 0:
                        break
                except (ValueError, TypeError):
                    pass

        for p_k in ['remise_pct', 'reduction_pct', 'pourcentage_reduction']:
            if form_data.get(p_k) is not None:
                try:
                    remise_pct = float(form_data.get(p_k))
                    if remise_pct > 0:
                        break
                except (ValueError, TypeError):
                    pass

        if remise_pct > 0 and remise_dh <= 0 and montant_service and montant_service > 0:
            remise_dh = round(montant_service * (remise_pct / 100.0), 2)

        reduction_label = None
        if remise_dh > 0:
            if remise_pct > 0:
                reduction_label = f"{remise_pct:.0f}%"
            elif montant_service and montant_service > 0:
                calc_pct = round((remise_dh / montant_service) * 100)
                if calc_pct > 0:
                    reduction_label = f"{calc_pct}%"

        total_ht_form = float(form_data.get('total_ht', form_data.get('montant_ht', 0)) or 0.0)
        total_ttc_form = float(form_data.get('total_ttc', form_data.get('montant_ttc', form_data.get('montant_final', demande.prix or 0))) or 0.0)

        if montant_service is None or montant_service <= 0:
            if total_ht_form > 0:
                montant_service = total_ht_form + remise_dh
            elif total_ttc_form > 0:
                if tva_active and tva_rate > 0:
                    montant_service = round(total_ttc_form / (1.0 + tva_rate), 2) + remise_dh
                else:
                    montant_service = total_ttc_form + remise_dh
            elif demande.prix:
                montant_service = float(demande.prix)
            else:
                montant_service = 0.0

        designation = f"{demande.service}"
        if nb_passages and prix_unitaire:
            designation = f"{demande.service} ({nb_passages} passages × {prix_unitaire} DH)"

        if month_index:
            try:
                month_idx_int = int(month_index)
            except (ValueError, TypeError):
                month_idx_int = 1
            designation += f" - Mois {month_idx_int}"
            invoice_number = f"AM/F{demande.pk:03d}-M{month_idx_int}/{datetime.datetime.now().year}"
            filename = f"FACTURE_{client_nom.replace(' ', '_')}_{demande.pk}_M{month_idx_int}.pdf"
        else:
            invoice_number = f"AM/F{demande.pk:03d}/{datetime.datetime.now().year}"
            filename = f"FACTURE_{client_nom.replace(' ', '_')}_{demande.pk}.pdf"

        items = [
            InvoiceItem(designation, montant_service)
        ]
            
        invoice_data = InvoiceData(
            invoice_number=invoice_number,
            invoice_date=datetime.date.today(),
            client_name=client_nom,
            client_ice=form_data.get('ice', ''),
            client_address=client_adresse,
            service_type=demande.service if not month_index else f"{demande.service} - Mois {month_index}",
            frequency=resolve_frequency_label(demande),
            items=items,
            montant_service=montant_service,
            reduction_label=reduction_label,
            reduction_amount=remise_dh,
            tva_active=tva_active,
            tva_rate=tva_rate
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

