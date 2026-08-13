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

        # ── 1. Vérification si une facture a été validée pour ce mois ──
        validated_facture = None
        factures_validees = form_data.get('factures_validees', [])
        if isinstance(factures_validees, list) and len(factures_validees) > 0:
            if month_index:
                try:
                    m_idx = int(month_index)
                    for fv in factures_validees:
                        if fv.get('month_index') == m_idx or fv.get('id') == f"M{m_idx}":
                            validated_facture = fv
                            break
                except (ValueError, TypeError):
                    pass
            if not validated_facture and len(factures_validees) > 0:
                validated_facture = factures_validees[-1]

        # ── 2. Gestion de la TVA (Non appliquée par défaut pour les particuliers) ──
        if validated_facture and validated_facture.get('tva_active') is not None:
            tva_active = bool(validated_facture.get('tva_active'))
            raw_tva = validated_facture.get('tva', 20)
            try:
                tva_rate = (float(raw_tva) / 100.0) if (tva_active and float(raw_tva) > 0) else 0.0
            except (ValueError, TypeError):
                tva_rate = 0.20 if tva_active else 0.0
        else:
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

        # ── 3. Décomposition Montant Service & Réduction issue du Devis ──
        nb_passages = None
        prix_unitaire = None
        montant_service = None
        remise_dh = 0.0
        remise_pct = 0.0
        reduction_label = None

        if validated_facture:
            nb_passages = validated_facture.get('nombre_passages')
            prix_unitaire = validated_facture.get('prix_unitaire')
            montant_service = validated_facture.get('montant_service')
            remise_dh = float(validated_facture.get('remise_dh', validated_facture.get('remise', 0)) or 0.0)
            remise_pct = float(validated_facture.get('remise_pct', 0) or 0.0)
            reduction_label = validated_facture.get('reduction_label')
        else:
            nb_passages = form_data.get('nombre_passages')
            prix_unitaire = form_data.get('prix_unitaire')

            if form_data.get('montant_service') is not None:
                try:
                    montant_service = float(form_data.get('montant_service'))
                except (ValueError, TypeError):
                    pass

            for r_k in ['remise_dh', 'remise', 'reduction_montant', 'remise_montant']:
                if form_data.get(r_k) is not None:
                    try:
                        remise_dh = float(form_data.get(r_k))
                        if remise_dh > 0:
                            break
                    except (ValueError, TypeError):
                        pass

            for p_k in ['remise_pct', 'reduction_pct', 'reduction_pourcentage', 'reduction_abonnement', 'taux_reduction', 'pourcentage_reduction']:
                if form_data.get(p_k) is not None:
                    try:
                        remise_pct = float(form_data.get(p_k))
                        if remise_pct > 0:
                            break
                    except (ValueError, TypeError):
                        pass

        # Si aucune réduction explicite n'a été trouvée et qu'il s'agit d'un abonnement
        is_sub = (
            getattr(demande, 'type_demande', '') == 'abonnement' or
            'abonnement' in str(demande.service).lower() or
            'semaine' in str(form_data.get('frequence', '')).lower() or
            'semaine' in str(getattr(demande, 'frequency_label', '')).lower()
        )

        devis_total = float(demande.prix or form_data.get('montant_devis', form_data.get('total', 0)) or 0.0)

        if remise_dh <= 0 and remise_pct <= 0 and is_sub and devis_total > 0:
            # Réduction standard abonnement 10%
            remise_pct = 10.0
            if montant_service is None or montant_service <= 0:
                montant_service = round(devis_total / 0.9, 2)
            remise_dh = round(montant_service - devis_total, 2)
            reduction_label = "10%"
        elif remise_pct > 0 and remise_dh <= 0 and devis_total > 0:
            if montant_service is None or montant_service <= 0:
                montant_service = round(devis_total / (1.0 - remise_pct / 100.0), 2)
            remise_dh = round(montant_service - devis_total, 2)
            reduction_label = f"{remise_pct:.0f}%"

        if (montant_service is None or montant_service <= 0) and nb_passages and prix_unitaire:
            try:
                montant_service = round(float(nb_passages) * float(prix_unitaire), 2)
            except (ValueError, TypeError):
                pass

        if montant_service is None or montant_service <= 0:
            if devis_total > 0:
                montant_service = devis_total + remise_dh
            else:
                montant_service = 0.0

        if remise_dh > 0 and not reduction_label:
            if remise_pct > 0:
                reduction_label = f"{remise_pct:.0f}%"
            elif montant_service > 0:
                calc_pct = round((remise_dh / montant_service) * 100)
                reduction_label = f"{calc_pct}%" if calc_pct > 0 else f"{remise_dh:.0f} MAD"

        # ── 4. Libellé et items ──
        pu_val = float(prix_unitaire) if prix_unitaire else (round(montant_service / float(nb_passages), 2) if nb_passages and float(nb_passages) > 0 else 0.0)
        
        if nb_passages and pu_val > 0:
            pu_str = f"{pu_val:,.2f}".replace(",", " ").rstrip('0').rstrip('.')
            designation = f"{demande.service} ({nb_passages} passages × {pu_str} DH)"
        else:
            designation = f"{demande.service}"

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

