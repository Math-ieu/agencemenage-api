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

        is_sub = (
            getattr(demande, 'type_demande', '') == 'abonnement' or
            'abonnement' in str(demande.service).lower() or
            'semaine' in str(form_data.get('frequence', '')).lower() or
            'semaine' in str(getattr(demande, 'frequency_label', '')).lower()
        )

        # ── 1. Résolution de l'index du mois ──
        m_idx = None
        if month_index is not None:
            try:
                m_idx = int(month_index)
            except (ValueError, TypeError):
                m_idx = 1

        # ── 2. Recherche des données validées du mois ──
        mois_facturation = {}
        if m_idx:
            m_key = f"mois{m_idx}"
            mois_facturation = (form_data.get('mois_data') or {}).get(m_key, {}).get('facturation') or {}

        validated_facture = None
        factures_validees = form_data.get('factures_validees', [])
        if isinstance(factures_validees, list) and len(factures_validees) > 0:
            if m_idx:
                for fv in factures_validees:
                    if fv.get('month_index') == m_idx or fv.get('id') == f"M{m_idx}":
                        validated_facture = fv
                        break
            if not validated_facture and not m_idx:
                validated_facture = factures_validees[-1]
                m_idx = validated_facture.get('month_index', 1)

        if m_idx is None:
            m_idx = 1

        # ── 3. Extraction des paramètres de facturation ──
        nb_passages = mois_facturation.get('nombre_passages') or (validated_facture.get('nombre_passages') if validated_facture else None)
        prix_unitaire = mois_facturation.get('prix_unitaire') or (validated_facture.get('prix_unitaire') if validated_facture else None)
        montant_service = mois_facturation.get('montant_service') or (validated_facture.get('montant_service') if validated_facture else None)

        has_explicit_remise = False
        raw_remise_dh = mois_facturation.get('remise_dh', mois_facturation.get('remise')) if mois_facturation else None
        if raw_remise_dh is None and validated_facture:
            raw_remise_dh = validated_facture.get('remise_dh', validated_facture.get('remise'))

        raw_remise_pct = mois_facturation.get('remise_pct') if mois_facturation else None
        if raw_remise_pct is None and validated_facture:
            raw_remise_pct = validated_facture.get('remise_pct')

        raw_reduction_label = mois_facturation.get('reduction_label') if mois_facturation else None
        if raw_reduction_label is None and validated_facture:
            raw_reduction_label = validated_facture.get('reduction_label')

        if raw_remise_dh is not None:
            try:
                remise_dh = float(raw_remise_dh)
                has_explicit_remise = True
            except (ValueError, TypeError):
                remise_dh = 0.0
        else:
            remise_dh = 0.0

        if raw_remise_pct is not None:
            try:
                remise_pct = float(raw_remise_pct)
                has_explicit_remise = True
            except (ValueError, TypeError):
                remise_pct = 0.0
        else:
            remise_pct = 0.0

        reduction_label = raw_reduction_label

        # Fallback si pas de données spécifiques au mois (Mois 1 à l'initialisation)
        if not mois_facturation and not validated_facture and m_idx == 1:
            nb_passages = form_data.get('nombre_passages')
            prix_unitaire = form_data.get('prix_unitaire')
            if form_data.get('montant_service') is not None:
                try:
                    montant_service = float(form_data.get('montant_service'))
                except (ValueError, TypeError):
                    pass
            for r_k in ['remise_dh', 'remise', 'reduction_montant']:
                if form_data.get(r_k) is not None:
                    try:
                        remise_dh = float(form_data.get(r_k))
                        has_explicit_remise = True
                        break
                    except (ValueError, TypeError):
                        pass
            for p_k in ['remise_pct', 'reduction_pct', 'reduction_pourcentage', 'reduction_abonnement', 'taux_reduction']:
                if form_data.get(p_k) is not None:
                    try:
                        remise_pct = float(form_data.get(p_k))
                        has_explicit_remise = True
                        break
                    except (ValueError, TypeError):
                        pass

        # Calcul du montant brut du service
        if (montant_service is None or float(montant_service) <= 0) and nb_passages and prix_unitaire:
            try:
                montant_service = round(float(nb_passages) * float(prix_unitaire), 2)
            except (ValueError, TypeError):
                montant_service = 0.0

        if montant_service is None or float(montant_service) <= 0:
            montant_service = float(demande.prix or form_data.get('montant_devis', form_data.get('total', 0)) or 0.0)

        # ── 4. Calcul de la réduction propre au mois ──
        # Règle : Mois 1 a 10% par défaut si non spécifié. Mois 2+ n'a AUCUNE réduction par défaut.
        if not has_explicit_remise and is_sub and m_idx == 1:
            remise_pct = 10.0
            reduction_label = "10%"

        if remise_pct > 0 and remise_dh <= 0 and montant_service > 0:
            remise_dh = round(float(montant_service) * (remise_pct / 100.0), 2)
            if not reduction_label:
                reduction_label = f"{remise_pct:.0f}%"
        elif remise_dh > 0 and not reduction_label:
            if remise_pct > 0:
                reduction_label = f"{remise_pct:.0f}%"
            elif montant_service > 0:
                calc_pct = round((remise_dh / float(montant_service)) * 100)
                reduction_label = f"{calc_pct}%" if calc_pct > 0 else f"{remise_dh:.0f} MAD"

        if remise_dh <= 0:
            remise_dh = 0.0
            reduction_label = None

        # ── 5. Date de la facture ──
        invoice_date_str = mois_facturation.get('date_debut') or (validated_facture.get('date_validation') if validated_facture else None)
        invoice_date = datetime.date.today()
        if invoice_date_str:
            try:
                if 'T' in str(invoice_date_str):
                    invoice_date = datetime.datetime.fromisoformat(str(invoice_date_str).replace('Z', '')).date()
                elif '-' in str(invoice_date_str):
                    parts = str(invoice_date_str).split('-')
                    invoice_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            except Exception:
                invoice_date = datetime.date.today()

        # ── 6. Gestion de la TVA ──
        raw_tva_active = mois_facturation.get('tva_active')
        if raw_tva_active is None and validated_facture:
            raw_tva_active = validated_facture.get('tva_active')

        if raw_tva_active is not None:
            tva_active = bool(raw_tva_active)
            raw_tva = mois_facturation.get('tva') or (validated_facture.get('tva') if validated_facture else 20)
            try:
                tva_rate = (float(raw_tva) / 100.0) if (tva_active and float(raw_tva) > 0) else 0.0
            except (ValueError, TypeError):
                tva_rate = 0.20 if tva_active else 0.0
        else:
            tva_active_raw = form_data.get('tva_active') if form_data.get('tva_active') is not None else form_data.get('apply_tva')
            if tva_active_raw is not None:
                if isinstance(tva_active_raw, str):
                    tva_active = tva_active_raw.lower() in ['true', 'oui', '1']
                else:
                    tva_active = bool(tva_active_raw)
            else:
                tva_active = False if is_particulier else True

            if tva_active:
                raw_tva = form_data.get('tva', form_data.get('tva_pct', form_data.get('tva_pourcentage', 20)))
                try:
                    tva_rate = float(raw_tva) / 100.0 if float(raw_tva) > 0 else 0.20
                except (ValueError, TypeError):
                    tva_rate = 0.20
            else:
                tva_rate = 0.0

        # ── 7. Libellé et items ──
        pu_val = float(prix_unitaire) if prix_unitaire else (round(float(montant_service) / float(nb_passages), 2) if nb_passages and float(nb_passages) > 0 else 0.0)

        if nb_passages and pu_val > 0:
            pu_str = f"{pu_val:,.2f}".replace(",", " ").rstrip('0').rstrip('.')
            designation = f"{demande.service} ({nb_passages} passages × {pu_str} DH)"
        else:
            designation = f"{demande.service}"

        if is_sub or m_idx > 1:
            designation += f" - Mois {m_idx}"
            invoice_number = f"AM/F{demande.pk:03d}-M{m_idx}/{datetime.datetime.now().year}"
            filename = f"FACTURE_{client_nom.replace(' ', '_')}_{demande.pk}_M{m_idx}.pdf"
        else:
            invoice_number = f"AM/F{demande.pk:03d}/{datetime.datetime.now().year}"
            filename = f"FACTURE_{client_nom.replace(' ', '_')}_{demande.pk}.pdf"

        items = [
            InvoiceItem(designation, float(montant_service))
        ]

        invoice_data = InvoiceData(
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            client_name=client_nom,
            client_ice=form_data.get('ice', ''),
            client_address=client_adresse,
            service_type=f"{demande.service} - Mois {m_idx}" if (is_sub or m_idx > 1) else demande.service,
            frequency=resolve_frequency_label(demande),
            items=items,
            montant_service=float(montant_service),
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

