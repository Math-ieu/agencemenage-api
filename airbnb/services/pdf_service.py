import os
import re
import uuid
from io import BytesIO
from xml.sax.saxutils import escape

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from demandes.utils.invoice_generator import AGENCY_INFO
from .pricing_engine import get_airbnb_config

TEAL = colors.HexColor('#00A896')
DARK_SLATE = colors.HexColor('#1E293B')
LIGHT_BG = colors.HexColor('#F8FAFC')
BORDER = colors.HexColor('#CBD5E1')
MUTED = colors.HexColor('#475569')
DANGER = colors.HexColor('#C53030')


def _safe_image(path: str, width_mm: float, max_height_mm: float):
    if path and os.path.exists(path):
        try:
            img = RLImage(path, width=width_mm * mm)
            if img.imageWidth:
                img.drawHeight = min(img.drawWidth * img.imageHeight / img.imageWidth, max_height_mm * mm)
            return img
        except Exception:
            return None
    return None


def _sanitize_no_money(text: str) -> str:
    """Supprime toute mention éventuelle de devise/prix des libellés sur la fiche de mission."""
    if not text:
        return ''
    cleaned = re.sub(r'\b\d+(?:[.,]\d+)?\s*(?:DH|MAD|EUR|€)\b', '', str(text), flags=re.IGNORECASE)
    return re.sub(r'\s{2,}', ' ', cleaned).strip()


def generate_fiche_mission_pdf(commande, hide_intervenantes: bool = False) -> bytes:
    """
    Génère la Fiche de Mission PDF pour les intervenantes / runners (Brief §2.2 & §6.3).
    CONTRAINTE ABSOLUE : ZÉRO MONTANT / ZÉRO TARIF / ZÉRO DEVISE (DH / MAD) SUR LE DOCUMENT.
    """
    cfg = get_airbnb_config()
    bien = commande.bien
    buf = BytesIO()
    page_w, _ = A4
    margin = 16 * mm
    col_w = page_w - 2 * margin

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        pageCompression=0,
        title=f"Fiche Mission {commande.numero}",
    )

    base = getSampleStyleSheet()['Normal']
    s_norm = ParagraphStyle('FMNorm', parent=base, fontSize=9, leading=13, textColor=DARK_SLATE)
    s_bold = ParagraphStyle('FMBold', parent=base, fontSize=9, leading=13, textColor=DARK_SLATE, fontName='Helvetica-Bold')
    s_title = ParagraphStyle('FMTitle', parent=base, fontSize=14, leading=18, textColor=TEAL, fontName='Helvetica-Bold')
    s_sec = ParagraphStyle('FMSec', parent=base, fontSize=10, leading=14, textColor=colors.white, fontName='Helvetica-Bold')
    s_small = ParagraphStyle('FMSmall', parent=base, fontSize=8, leading=11, textColor=MUTED)

    def p(txt, style=s_norm):
        return Paragraph(escape(str(txt)), style)

    def p_html(txt, style=s_norm):
        return Paragraph(str(txt), style)

    logo = _safe_image(os.path.join(settings.BASE_DIR, 'assets', 'logo.png'), 34, 18)
    header_left = [logo] if logo else [p_html(f"<b>{escape(AGENCY_INFO['name'])}</b>", s_title)]
    header_right = [
        p_html(f"<b>FICHE DE MISSION — TURNOVER</b>", s_title),
        p_html(f"<b>N° Commande :</b> {escape(commande.numero)}", s_bold),
        p_html(
            f"<b>Date :</b> {commande.date_prestation.strftime('%d/%m/%Y')} — "
            f"<b>Heure :</b> {str(commande.heure_prestation)[:5]} ({escape(commande.get_creneau_display())})",
            s_norm,
        ),
    ]
    header_tbl = Table([[header_left, header_right]], colWidths=[col_w * 0.28, col_w * 0.72])
    header_tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    story = [
        header_tbl,
        Spacer(1, 4 * mm),
        HRFlowable(width='100%', thickness=1.5, color=TEAL),
        Spacer(1, 4 * mm),
    ]

    # Bloc 1 : Identification & Accès au bien
    acces_lines = [
        ['Code Bien', bien.code],
        ['Nom du logement', bien.nom_bien or '-'],
        ['Ville / Quartier', f"{bien.ville} — {bien.quartier}"],
        ['Adresse complète', bien.adresse],
    ]
    if bien.complement_adresse:
        acces_lines.append(['Complément', bien.complement_adresse])
    if bien.etage_porte:
        acces_lines.append(['Étage / Porte', bien.etage_porte])
    acces_lines.append(['Type d\'accès', bien.get_acces_type_display()])
    acces_lines.append(['Détails accès / Digicode', bien.acces_detail or "Contacter la chargée des opérations"])
    if bien.gardien_nom or bien.gardien_horaires:
        acces_lines.append(['Gardien', f"{bien.gardien_nom} ({bien.gardien_horaires})".strip()])

    # Bloc 2 : Composition du logement
    couchages_str = ', '.join(
        f"{c.get('type', 'Lit')} x{c.get('quantite', 1)}" if isinstance(c, dict) else str(c)
        for c in (bien.couchages or [])
    ) or 'Standard selon typologie'
    comp_lines = [
        ['Typologie', bien.get_typologie_display()],
        ['Chambres / SDB', f"{bien.chambres} chambre(s) — {bien.salles_de_bain} salle(s) de bain"],
        ['Couchages', couchages_str],
    ]
    if bien.autres_pieces:
        comp_lines.append(['Autres pièces', bien.autres_pieces])

    # Bloc 3 : Prestation prévue (Zéro prix)
    options_labels = []
    for opt in (commande.options or []):
        if isinstance(opt, dict):
            lbl = _sanitize_no_money(opt.get('label') or opt.get('code') or '')
        else:
            lbl = _sanitize_no_money(str(opt))
        if lbl:
            options_labels.append(lbl)

    presta_lines = [
        ['Opération linge', commande.get_nature_linge_display()],
        ['Options prévues', ', '.join(options_labels) if options_labels else 'Aucune option additionnelle'],
    ]
    if not hide_intervenantes:
        interv_names = []
        if commande.intervenante:
            interv_names.append(f"{commande.intervenante.first_name} {commande.intervenante.last_name}")
        if commande.intervenante_2:
            interv_names.append(f"{commande.intervenante_2.first_name} {commande.intervenante_2.last_name} (Binôme)")
        presta_lines.append(['Intervenante(s)', ', '.join(interv_names) if interv_names else 'À assigner'])
    presta_lines.append([
        'Runner linge',
        f"{commande.runner.first_name} {commande.runner.last_name}".strip() if commande.runner else 'Non assigné',
    ])

    def _section_table(title_text, rows_list):
        tbl_rows = [[p(title_text, s_sec), '']]
        for k, v in rows_list:
            tbl_rows.append([p(k, s_bold), p(_sanitize_no_money(v), s_norm)])
        t = Table(tbl_rows, colWidths=[col_w * 0.34, col_w * 0.66])
        t.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('BACKGROUND', (0, 0), (1, 0), TEAL),
            ('ROWBACKGROUND', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ('BOX', (0, 0), (-1, -1), 0.6, BORDER),
            ('INNERGRID', (0, 1), (-1, -1), 0.3, BORDER),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        return t

    story.append(_section_table("1. LOCALISATION & ACCÈS AU LOGEMENT", acces_lines))
    story.append(Spacer(1, 3.5 * mm))
    story.append(_section_table("2. COMPOSITION DU BIEN", comp_lines))
    story.append(Spacer(1, 3.5 * mm))
    story.append(_section_table("3. MISSION & INTERVENANTS", presta_lines))
    story.append(Spacer(1, 3.5 * mm))

    # Bloc 4 : Consignes, Photos obligatoires et Signalements
    consignes_perm = [_sanitize_no_money(c) for c in (bien.consignes or []) if c]
    consignes_text = ' | '.join(consignes_perm) if consignes_perm else 'Consignes standard turnover.'
    if commande.consigne_ponctuelle:
        consignes_text += f" | Ponctuelle : {_sanitize_no_money(commande.consigne_ponctuelle)}"

    photos_req = bien.photos_attendues or cfg.photos_attendues or ['Salon', 'Cuisine', 'Salle de bain', 'Chambres']
    photos_str = ', '.join(str(ph) for ph in photos_req)

    bloc4_lines = [
        ['Consignes client', consignes_text],
        ['Photos obligatoires (4 min)', photos_str],
        ['Signalements possibles', '1) Bien anormalement sale (photos avant début) · 2) Objet oublié (ne rien déplacer, photo) · 3) Accès impossible (appel immédiat)'],
        ['Clôture & Linge', 'Remettre le sac de linge sale fermé au Runner. Laisser les clés selon consigne.'],
    ]
    story.append(_section_table("4. CONSIGNES, PHOTOS & PROCÉDURES", bloc4_lines))
    story.append(Spacer(1, 4 * mm))
    story.append(p("Document strictement opérationnel — Agence Ménage SARL.", s_small))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


def generate_facture_airbnb_pdf(facture) -> bytes:
    """
    Génère la facture PDF Airbnb / Conciergerie à partir de finance.Facture et FactureLigneAirbnb.
    Inclut les lignes positives, les gestes commerciaux / réductions négatives, et les infos de règlement.
    """
    buf = BytesIO()
    page_w, _ = A4
    margin = 16 * mm
    col_w = page_w - 2 * margin

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        pageCompression=0,
        title=f"Facture {facture.numero}",
    )

    base = getSampleStyleSheet()['Normal']
    s_norm = ParagraphStyle('AFNorm', parent=base, fontSize=9, leading=13, textColor=DARK_SLATE)
    s_bold = ParagraphStyle('AFBold', parent=base, fontSize=9, leading=13, textColor=DARK_SLATE, fontName='Helvetica-Bold')
    s_right = ParagraphStyle('AFRight', parent=base, fontSize=9, leading=13, textColor=DARK_SLATE, alignment=TA_RIGHT)
    s_neg = ParagraphStyle('AFNeg', parent=base, fontSize=9, leading=13, textColor=DANGER, alignment=TA_RIGHT)
    s_hdr_l = ParagraphStyle('AFHdrL', parent=base, fontSize=9, leading=13, textColor=colors.white, fontName='Helvetica-Bold')
    s_hdr_r = ParagraphStyle('AFHdrR', parent=base, fontSize=9, leading=13, textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_RIGHT)
    s_ttc_l = ParagraphStyle('AFTTCL', parent=base, fontSize=10, leading=14, textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_RIGHT)
    s_ttc_v = ParagraphStyle('AFTTCV', parent=base, fontSize=10, leading=14, textColor=TEAL, fontName='Helvetica-Bold', alignment=TA_RIGHT)
    s_small = ParagraphStyle('AFSmall', parent=base, fontSize=7.5, leading=11, textColor=MUTED)
    s_footer = ParagraphStyle('AFFoot', parent=base, fontSize=7, leading=10, textColor=MUTED, alignment=TA_CENTER)

    def p_html(txt, style=s_norm):
        return Paragraph(str(txt), style)

    def fmt(val):
        return f"{float(val):,.2f}".replace(',', ' ')

    logo = _safe_image(os.path.join(settings.BASE_DIR, 'assets', 'logo.png'), 38, 20)
    left_hdr = [logo] if logo else [p_html(f"<b>{AGENCY_INFO['name']}</b>", s_bold)]
    left_hdr += [
        Spacer(1, 2 * mm),
        p_html(f"<b>{AGENCY_INFO['name']} SARL</b>", s_bold),
        p_html(AGENCY_INFO['address_line1'], s_norm),
        p_html(AGENCY_INFO['address_line2'], s_norm),
    ]

    client = facture.client
    client_name = client.display_name if client else 'Client Airbnb'
    trigramme = f" [{client.trigramme}]" if (client and client.trigramme) else ''
    emit_str = facture.date_emission.strftime('%d/%m/%Y') if facture.date_emission else ''
    ech_str = facture.date_echeance.strftime('%d/%m/%Y') if facture.date_echeance else '-'

    right_hdr = [
        p_html(f"<b>FACTURE AIRBNB N° {escape(facture.numero)}</b>", s_bold),
        p_html(f"<b>Date d'émission :</b> {emit_str}", s_norm),
        p_html(f"<b>Date d'échéance :</b> {ech_str}", s_norm),
        Spacer(1, 4 * mm),
        p_html("<b>Client :</b>", s_bold),
        p_html(f"<b>{escape(client_name)}{escape(trigramme)}</b>", s_bold),
        p_html(f"Tél : {escape(client.phone if client else '')}", s_norm),
        p_html(f"Adresse : {escape(client.address or client.city or '-')}", s_norm),
    ]

    hdr_tbl = Table([[left_hdr, right_hdr]], colWidths=[col_w * 0.52, col_w * 0.48])
    hdr_tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))

    mode_labels = {
        'passage': 'Après chaque passage',
        'quinzaine': 'Quinzaine (Période probatoire)',
        'mensuel': 'Mensuel groupé',
    }
    mode_lbl = mode_labels.get(facture.mode_facturation, facture.mode_facturation or 'Airbnb / Conciergerie')
    if facture.periode_debut and facture.periode_fin:
        periode_str = f"{facture.periode_debut.strftime('%d/%m/%Y')} → {facture.periode_fin.strftime('%d/%m/%Y')}"
        if facture.est_prorata:
            periode_str += " (Prorata)"
    else:
        periode_str = "-"

    meta_tbl = Table([
        [p_html("<b>Service :</b>", s_bold), p_html("Turnovers Airbnb / Conciergerie", s_norm),
         p_html("<b>Mode :</b>", s_bold), p_html(escape(mode_lbl), s_norm)],
        [p_html("<b>Période :</b>", s_bold), p_html(escape(periode_str), s_norm),
         p_html("<b>Statut :</b>", s_bold), p_html(escape(facture.get_statut_display()), s_norm)],
    ], colWidths=[col_w * 0.16, col_w * 0.34, col_w * 0.16, col_w * 0.34])

    rows = [[p_html("<b>Désignation</b>", s_hdr_l), p_html("<b>Type</b>", s_hdr_l), p_html("<b>Montant (MAD)</b>", s_hdr_r)]]
    lignes = list(facture.lignes_airbnb.all())
    if lignes:
        for ligne in lignes:
            amt = float(ligne.montant)
            amt_style = s_neg if amt < 0 else s_right
            motif_txt = f"<br/><i><font size='7'>Motif : {escape(ligne.motif)}</font></i>" if ligne.motif else ''
            rows.append([
                p_html(f"{escape(ligne.designation)}{motif_txt}", s_norm),
                p_html(escape(ligne.get_type_ligne_display()), s_norm),
                p_html(f"{fmt(amt)} MAD", amt_style),
            ])
    else:
        rows.append([
            p_html(f"Prestations Airbnb ({escape(periode_str)})", s_norm),
            p_html("Prestation", s_norm),
            p_html(f"{fmt(facture.montant_total)} MAD", s_right),
        ])

    rows.append([p_html("", s_norm), p_html("<b>Total Facturé :</b>", s_right), p_html(f"<b>{fmt(facture.montant_total)} MAD</b>", s_right)])
    rows.append([p_html("", s_norm), p_html("Déjà payé :", s_right), p_html(f"{fmt(facture.montant_paye)} MAD", s_right)])
    rows.append([p_html("", s_norm), p_html("RESTE À PAYER :", s_ttc_l), p_html(f"<b>{fmt(facture.reste_a_payer)} MAD</b>", s_ttc_v)])

    ttc_row = len(rows) - 1
    items_end = max(1, len(lignes))
    items_tbl = Table(rows, colWidths=[col_w * 0.54, col_w * 0.22, col_w * 0.24])
    items_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), TEAL),
        ('ROWBACKGROUND', (0, 1), (-1, items_end), [colors.white, LIGHT_BG]),
        ('BACKGROUND', (1, ttc_row), (-1, ttc_row), DARK_SLATE),
        ('BOX', (0, 0), (-1, ttc_row), 0.6, BORDER),
        ('INNERGRID', (0, 0), (-1, items_end), 0.3, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    sig = _safe_image(os.path.join(settings.BASE_DIR, 'assets', 'signature.png'), 30, 20)
    pay_left = [
        p_html("<u><b>Règlement par virement bancaire</b></u>", s_bold),
        p_html(f"<b>RIB :</b> {AGENCY_INFO['rib']}", s_norm),
        p_html(f"<b>Banque :</b> {AGENCY_INFO['bank']} — <b>Titulaire :</b> {AGENCY_INFO['account_holder']}", s_norm),
        p_html("<i>Déclarez votre virement depuis votre espace conciergerie ou envoyez le justificatif par WhatsApp.</i>", s_small),
    ]
    pay_tbl = Table([[pay_left, [sig] if sig else [p_html("", s_norm)]]], colWidths=[col_w * 0.68, col_w * 0.32])
    pay_tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('ALIGN', (1, 0), (1, 0), 'CENTER')]))

    footer = p_html(
        f"<b>{AGENCY_INFO['name']} SARL</b> — {AGENCY_INFO['bureau_casa']}<br/>"
        f"RC : {AGENCY_INFO['rc']} · Patente : {AGENCY_INFO['patente']} · IF : {AGENCY_INFO['if_']} · ICE : {AGENCY_INFO['ice']}",
        s_footer,
    )

    story = [
        hdr_tbl,
        Spacer(1, 4 * mm),
        HRFlowable(width='100%', thickness=0.8, color=BORDER),
        Spacer(1, 3 * mm),
        meta_tbl,
        Spacer(1, 5 * mm),
        items_tbl,
        Spacer(1, 6 * mm),
        pay_tbl,
        Spacer(1, 6 * mm),
        HRFlowable(width='100%', thickness=2.5, color=TEAL),
        Spacer(1, 2 * mm),
        footer,
    ]
    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


def generate_and_save_facture_pdf(facture) -> bytes:
    """Génère le PDF de la facture et le sauvegarde sur facture.pdf_file si possible."""
    pdf_bytes = generate_facture_airbnb_pdf(facture)
    try:
        facture.pdf_file.save(f"{facture.numero}.pdf", ContentFile(pdf_bytes), save=True)
    except Exception:
        pass
    return pdf_bytes


def save_fiche_mission_pdf(commande, hide_intervenantes: bool = False) -> str:
    """Génère la Fiche de Mission PDF sans montant, l'enregistre via default_storage et met à jour fiche_mission_pdf_url."""
    pdf_bytes = generate_fiche_mission_pdf(commande, hide_intervenantes=hide_intervenantes)
    storage_path = f"airbnb/fiches_mission/{commande.numero}_{uuid.uuid4().hex[:8]}.pdf"
    saved_name = default_storage.save(storage_path, ContentFile(pdf_bytes))
    media_prefix = getattr(settings, 'MEDIA_URL', '/api/media/').rstrip('/')
    api_base = str(getattr(settings, 'API_BASE_URL', '') or '').rstrip('/')
    if api_base.startswith('http://localhost') or api_base.startswith('http://127.0.0.1'):
        api_base = ''
    public_base = (
        getattr(settings, 'BACKEND_PUBLIC_URL', '')
        or getattr(settings, 'SITE_URL', '')
        or api_base
        or ''
    ).rstrip('/')
    relative_url = f"{media_prefix}/{saved_name.lstrip('/')}"
    pdf_url = f"{public_base}{relative_url}" if public_base else relative_url
    commande.fiche_mission_pdf_url = pdf_url
    commande.save(update_fields=['fiche_mission_pdf_url', 'updated_at'])
    return pdf_url
