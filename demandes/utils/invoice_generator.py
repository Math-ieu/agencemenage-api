import os
from io import BytesIO
from dataclasses import dataclass
from typing import List, Optional
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage,
)

from django.conf import settings

# ── Infos agence ─────────────────────────────
AGENCY_INFO = {
    "name":          "Agence Ménage",
    "address_line1": "36 Boulevard d'Anfa, Résidence Anafee A",
    "address_line2": "Num 78, Casablanca",
    "bureau_casa":   "36A Boulevard d'Anfa, 7ème étage",
    "bureau_rabat":  "Avenue Hassan 2, centre commercial REDA porte G",
    "email":         "contact@agencemenage.ma",
    "phone":         "0664331463",
    "phone2":        "0522 200 177",
    "rc":            "704771",
    "patente":       "35409085",
    "if_":           "71002832",
    "ice":           "003854034000063",
    "rib":           "011 780 0 00036 21 000139 83 89",
    "bank":          "Bank Of Africa",
    "account_holder":"Agence Ménage",
}

# ── Couleurs ─────────────────────────────────
TEAL        = colors.HexColor("#00A896")
DARK_GRAY   = colors.HexColor("#333333")
LIGHT_GRAY  = colors.HexColor("#F5F5F5")
BORDER_COLOR= colors.HexColor("#CCCCCC")


# ─────────────────────────────────────────────
#  MODÈLES DE DONNÉES
# ─────────────────────────────────────────────
@dataclass
class InvoiceItem:
    designation: str
    amount: float   # HT

@dataclass
class InvoiceData:
    invoice_number:  str
    invoice_date:    date
    client_name:     str
    client_ice:      str
    client_address:  str
    service_type:    str
    frequency:       str
    items:           List[InvoiceItem]
    tva_rate:        float = 0.20
    logo_path:       Optional[str] = None
    signature_path:  Optional[str] = None

    @property
    def total_ht(self):    return sum(i.amount for i in self.items)
    @property
    def tva_amount(self):  return round(float(self.total_ht) * self.tva_rate, 2)
    @property
    def total_ttc(self):   return float(self.total_ht) + self.tva_amount
    def get_logo_path(self):      return self.logo_path or os.path.join(settings.BASE_DIR, "assets", "logo.png")
    def get_signature_path(self): return self.signature_path or os.path.join(settings.BASE_DIR, "assets", "signature.png")


# ─────────────────────────────────────────────
#  GÉNÉRATEUR
# ─────────────────────────────────────────────
class InvoiceGenerator:
    PAGE_W, PAGE_H = A4
    MARGIN = 18 * mm

    def __init__(self, data: InvoiceData):
        self.data = data
        self._setup_styles()

    def _setup_styles(self):
        base = getSampleStyleSheet()["Normal"]
        mk = lambda name, **kw: ParagraphStyle(name, parent=base, **kw)

        self.sNormal  = mk("AMn",  fontSize=9,   leading=13, textColor=DARK_GRAY)
        self.sBold    = mk("AMb",  fontSize=9,   leading=13, textColor=DARK_GRAY, fontName="Helvetica-Bold")
        self.sSmall   = mk("AMs",  fontSize=7.5, leading=11, textColor=DARK_GRAY)
        self.sRight   = mk("AMr",  fontSize=9,   leading=13, textColor=DARK_GRAY, alignment=TA_RIGHT)
        self.sBoldR   = mk("AMbr", fontSize=9,   leading=13, textColor=DARK_GRAY, fontName="Helvetica-Bold", alignment=TA_RIGHT)
        self.sFooter  = mk("AMf",  fontSize=7,   leading=10, textColor=colors.HexColor("#555555"), alignment=TA_CENTER)
        self.sAmtR    = mk("AMar", fontSize=9,   leading=13, textColor=DARK_GRAY, alignment=TA_RIGHT)
        self.sHdrC    = mk("AMhc", fontSize=9,   leading=13, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_CENTER)
        self.sHdrR    = mk("AMhr", fontSize=9,   leading=13, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_RIGHT)
        self.sTTCl    = mk("AMtl", fontSize=9,   leading=13, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_RIGHT)
        self.sTTCv    = mk("AMtv", fontSize=11,  leading=14, textColor=TEAL,         fontName="Helvetica-Bold", alignment=TA_RIGHT)

    def _p(self, text, style=None):
        return Paragraph(str(text), style or self.sNormal)

    def _img(self, path, w_mm, max_h_mm):
        if path and os.path.exists(path):
            img = RLImage(path, width=w_mm * mm)
            img.drawHeight = min(img.drawWidth * img.imageHeight / img.imageWidth, max_h_mm * mm)
            return img
        return None

    def _fmt(self, v):
        return f"{float(v):,.2f}".replace(",", " ")

    # ── HEADER ───────────────────────────────
    def _build_header(self) -> Table:
        d = self.data
        col_w = self.PAGE_W - 2 * self.MARGIN
        LEFT_W  = 90 * mm
        RIGHT_W = col_w - LEFT_W

        sAddr = ParagraphStyle("addr", parent=self.sNormal, fontSize=9, leading=13)
        sBoldA= ParagraphStyle("baddr",parent=sAddr, fontName="Helvetica-Bold")

        logo = self._img(d.get_logo_path(), w_mm=40, max_h_mm=22)
        left = []
        if logo:
            left.append(logo)
        else:
            left.append(self._p(f"<b>{AGENCY_INFO['name']}</b>", sBoldA))
        left += [
            Spacer(1, 2*mm),
            self._p(f"<b>{AGENCY_INFO['name']}</b>", sBoldA),
            self._p(AGENCY_INFO["address_line1"], sAddr),
            self._p(AGENCY_INFO["address_line2"], sAddr),
        ]

        sDateLabel = ParagraphStyle("dl", parent=self.sNormal, fontSize=9, fontName="Helvetica-Bold")
        sClientLbl = ParagraphStyle("cl", parent=self.sNormal, fontSize=9, fontName="Helvetica-Bold")
        sClientVal = ParagraphStyle("cv", parent=self.sNormal, fontSize=9, fontName="Helvetica-Bold")
        sClientSub = ParagraphStyle("cs", parent=self.sNormal, fontSize=9)

        date_tbl = Table(
            [[
                self._p("<b>Date de facture :</b>", sDateLabel),
                self._p(d.invoice_date.strftime("%d/%m/%Y"), self.sRight),
            ]],
            colWidths=[RIGHT_W * 0.55, RIGHT_W * 0.45],
            style=TableStyle([
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
                ("TOPPADDING",    (0,0), (-1,-1), 0),
                ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                ("LEFTPADDING",   (0,0), (-1,-1), 0),
                ("RIGHTPADDING",  (0,0), (-1,-1), 0),
            ])
        )

        right = [
            date_tbl,
            Spacer(1, 8*mm),
            self._p("<b>Client:</b>",                        sClientLbl),
            self._p(f"<b>{d.client_name}</b>",               sClientVal),
            self._p(f"ICE: {d.client_ice}",                  sClientSub),
            self._p(f"Adresse: {d.client_address}",          sClientSub),
        ]

        tbl = Table(
            [[left, right]],
            colWidths=[LEFT_W, RIGHT_W],
        )
        tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
        ]))
        return tbl

    def _build_invoice_meta(self) -> Table:
        d = self.data
        col_w = self.PAGE_W - 2 * self.MARGIN
        rows = [
            [self._p("<b>Facturation n°</b>", self.sBold), self._p(":"), self._p(d.invoice_number)],
            [self._p("<b>Service</b>",        self.sBold), self._p(":"), self._p(d.service_type)],
            [self._p("<b>Fréquence</b>",      self.sBold), self._p(":"), self._p(d.frequency)],
        ]
        tbl = Table(rows, colWidths=[35*mm, 5*mm, col_w - 40*mm])
        tbl.setStyle(TableStyle([
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        return tbl

    def _build_items_table(self) -> Table:
        d = self.data
        col_w = self.PAGE_W - 2 * self.MARGIN
        DES_W = col_w * 0.70
        AMT_W = col_w * 0.30

        rows = [[
            self._p("<b>Désignation</b>", self.sHdrC),
            self._p("<b>Montant</b>",     self.sHdrR),
        ]]

        for item in d.items:
            rows.append([
                self._p(item.designation),
                self._p(self._fmt(item.amount), self.sAmtR),
            ])

        rows.append([Spacer(1, 4*mm), ""])

        rows.append([
            self._p("Total HT:", ParagraphStyle("tht", parent=self.sNormal, alignment=TA_RIGHT)),
            self._p(self._fmt(d.total_ht), self.sAmtR),
        ])
        rows.append([
            self._p(f"TVA {int(d.tva_rate*100)}%:", ParagraphStyle("ttva", parent=self.sNormal, alignment=TA_RIGHT)),
            self._p(self._fmt(d.tva_amount), self.sAmtR),
        ])
        rows.append([
            self._p("MONTANT TOTAL A PAYER T.T.C :", self.sTTCl),
            self._p(f"<b>{self._fmt(d.total_ttc)} MAD</b>", self.sTTCv),
        ])

        n        = len(rows)
        item_end = len(d.items)
        ttc_row  = n - 1

        tbl = Table(rows, colWidths=[DES_W, AMT_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),         (-1,0),        TEAL),
            ("ROWBACKGROUND", (0,1),         (-1,item_end), [colors.white, LIGHT_GRAY]),
            ("BACKGROUND",    (0,ttc_row),   (-1,ttc_row),  DARK_GRAY),
            ("BOX",           (0,0),         (-1,ttc_row-1),0.5, BORDER_COLOR),
            ("LINEABOVE",     (0,ttc_row),   (-1,ttc_row),  1,   DARK_GRAY),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("RIGHTPADDING",  (0,0), (-1,-1), 6),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        return tbl

    def _build_payment_block(self) -> Table:
        info = AGENCY_INFO
        left = [
            self._p("<u><b>Règlement par virement</b></u>", self.sBold),
            Spacer(1, 2*mm),
            self._p(f"<b>RIB :</b>  {info['rib']}"),
            self._p(f"<b>Banque :</b>  {info['bank']}"),
            self._p(f"<b>Titulaire du compte :</b>  {info['account_holder']}"),
            self._p(f"<b>Téléphone :</b>  {info['phone2']}"),
            Spacer(1, 2*mm),
            self._p("<i>Merci d'envoyer le justificatif de virement par WhatsApp</i>", self.sSmall),
        ]
        sig = self._img(self.data.get_signature_path(), w_mm=32, max_h_mm=22)
        right = [sig] if sig else [self._p("")]

        col_w = self.PAGE_W - 2 * self.MARGIN
        tbl = Table([[left, right]], colWidths=[col_w * 0.65, col_w * 0.35])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "BOTTOM"),
            ("ALIGN",  (1,0), (1,0),   "CENTER"),
        ]))
        return tbl

    def _build_footer(self) -> Paragraph:
        info = AGENCY_INFO
        return self._p(
            f"<b>{info['name']} SARL</b> – Entreprise de ménage pour entreprises et particuliers<br/>"
            f"Bureau Casa : {info['bureau_casa']} / Bureau Rabat : {info['bureau_rabat']} – "
            f"Email : {info['email']}, téléphone : {info['phone']}<br/>"
            f"RC : {info['rc']} – Patente : {info['patente']} – IF : {info['if_']} – ICE : {info['ice']}",
            self.sFooter
        )

    def generate(self, output: BytesIO) -> BytesIO:
        doc = SimpleDocTemplate(
            output, pagesize=A4,
            leftMargin=self.MARGIN, rightMargin=self.MARGIN,
            topMargin=self.MARGIN, bottomMargin=self.MARGIN,
            title=f"Facture {self.data.invoice_number}",
        )
        story = [
            self._build_header(),
            Spacer(1, 8*mm),
            HRFlowable(width="100%", thickness=0.5, color=BORDER_COLOR),
            Spacer(1, 4*mm),
            self._build_invoice_meta(),
            Spacer(1, 6*mm),
            self._build_items_table(),
            Spacer(1, 8*mm),
            self._build_payment_block(),
            Spacer(1, 10*mm),
            HRFlowable(width="100%", thickness=4, color=TEAL),
            Spacer(1, 3*mm),
            self._build_footer(),
        ]
        doc.build(story)
        output.seek(0)
        return output


def generate_invoice(data: InvoiceData, output: Optional[BytesIO] = None) -> BytesIO:
    buf = output or BytesIO()
    return InvoiceGenerator(data).generate(buf)
