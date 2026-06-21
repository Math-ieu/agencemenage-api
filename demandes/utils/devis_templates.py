"""Sélection du template WhatsApp 360dialog + variables pour l'envoi d'un devis.

Un template par service (cf. updates/360dialog-templates-devis.md). Les variables
sont positionnelles ({{1}}, {{2}}, …) et doivent respecter l'ordre du markdown.

Tout est défensif : en cas de service inconnu ou de donnée manquante, on retombe
sur le template générique `envoi_devis_client`.
"""
import re


def _num(form, *keys, default=0):
    for k in keys:
        v = form.get(k)
        if v not in (None, ""):
            try:
                return float(str(v).replace(" ", "").replace(",", "."))
            except (ValueError, TypeError):
                continue
    return default


def _fmt_dh(value):
    try:
        n = float(value)
    except (ValueError, TypeError):
        return "Sur devis"
    if n <= 0:
        return "Sur devis"
    return f"{n:,.0f}".replace(",", " ") + " DH"


def _montant(demande):
    form = demande.formulaire_data or {}
    for key in ["total", "total_ht", "total_ttc", "prix_total", "montant_total", "montant", "prix"]:
        v = form.get(key)
        if v not in (None, ""):
            try:
                n = float(str(v).replace(" ", "").replace(",", "."))
                if n > 0:
                    return _fmt_dh(n)
            except (ValueError, TypeError):
                pass
    if demande.prix is not None:
        return _fmt_dh(demande.prix)
    return "Sur devis"


def _freq_jours(demande):
    """Nombre de passages par semaine (texte)."""
    form = demande.formulaire_data or {}
    label = demande.frequency_label or form.get("frequence") or ""
    m = re.search(r"(\d+)\s*/\s*sem", str(label))
    if m:
        return m.group(1)
    jps = _num(form, "jours_par_semaine", default=0)
    return str(int(jps)) if jps else "—"


def _duree(demande):
    form = demande.formulaire_data or {}
    d = _num(form, "duree", "nb_heures", "heures", default=0)
    return str(int(d)) if d else "—"


def _surface(demande):
    form = demande.formulaire_data or {}
    sfc = _num(form, "surface", "superficie", "surfaceArea", default=0)
    return str(int(sfc)) if sfc else "—"


def _nb_interv(demande):
    form = demande.formulaire_data or {}
    n = _num(form, "nb_intervenantes", "nb_intervenants", "numberOfPeople", default=1)
    return str(int(n)) if n else "1"


def _heures_jour(demande):
    form = demande.formulaire_data or {}
    h = _num(form, "heures_par_jour", "duree", "nb_heures", default=0)
    return str(int(h)) if h else "—"


def _remise_phrase(demande):
    """Phrase remise abonnement, ex. « −10 % (soit −288 DH / mois) »."""
    form = demande.formulaire_data or {}
    pct = _num(form, "reduction_abonnement", "reduction_pourcentage", default=0) or 10
    eco = _num(form, "reduction_montant", "reduction", default=0)
    base = f"−{int(pct)} %"
    if eco:
        return f"{base} (soit −{_fmt_dh(eco)} / mois)"
    return f"{base} (remise abonnement incluse)"


def get_devis_template(demande, client_name):
    """Renvoie (template_name, variables) selon le service du devis."""
    service = (demande.service or "").lower()
    form = demande.formulaire_data or {}
    is_entreprise = demande.segment == "entreprise"
    is_abo = demande.frequency == "abonnement"
    num = demande.devis_numero()
    montant = _montant(demande)

    # Airbnb
    if "airbnb" in service or "air bnb" in service:
        return "devis_menage_airbnb_v1", [client_name, num, montant]

    # Auxiliaire de vie / garde malade
    if "auxiliaire" in service or "garde malade" in service:
        return "devis_auxiliaire_vie_v1", [client_name, num, montant]

    # Fin de chantier (particulier / entreprise)
    if "chantier" in service:
        if is_entreprise:
            return "devis_fin_chantier_entreprise_v1", [num, _surface(demande), montant]
        return "devis_fin_chantier_particulier_v1", [client_name, num, _surface(demande), montant]

    # Post-sinistre (particulier / entreprise)
    if "sinistre" in service:
        if is_entreprise:
            return "devis_post_sinistre_entreprise_v1", [num, montant]
        return "devis_post_sinistre_particulier_v1", [client_name, num, montant]

    # Ménage bureaux (ponctuel / abonnement) — entreprise HT
    if "bureaux" in service:
        if is_abo:
            return "devis_menage_bureaux_abonnement_v1", [num, _freq_jours(demande), montant, _remise_phrase(demande)]
        return "devis_menage_bureaux_ponctuel_v1", [num, _duree(demande), _nb_interv(demande), montant]

    # Gestion 360° et Placement flexible (entreprise HT)
    service_type = str(form.get("service_type") or "").lower()
    if "gestion 360" in service or "gestion360" in service or service_type in ("premium", "gestion360"):
        return "devis_gestion_360_v1", [num, _nb_interv(demande), _heures_jour(demande), _freq_jours(demande), montant]
    if "placement" in service or "gestion" in service:
        return "devis_placement_flexible_v1", [num, _nb_interv(demande), _heures_jour(demande), _freq_jours(demande), montant]

    # Grand ménage (ponctuel / abonnement)
    if "grand menage" in service or "grand ménage" in service:
        if is_abo:
            return "devis_grand_menage_abonnement_v1", [client_name, num, _freq_jours(demande), montant, _remise_phrase(demande)]
        return "devis_grand_menage_ponctuel_v1", [client_name, num, _duree(demande), montant]

    # Ménage standard (ponctuel / abonnement) — défaut pour le ménage particulier
    if "standard" in service or "menage" in service or "ménage" in service:
        if is_abo:
            return "devis_menage_standard_abonnement_v1", [client_name, num, _freq_jours(demande), montant, _remise_phrase(demande)]
        return "devis_menage_standard_ponctuel_v1", [client_name, num, _duree(demande), montant]

    # Fallback : template générique historique
    return "envoi_devis_client", [client_name, num, demande.service]
