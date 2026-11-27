import os
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_DOC_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {'.pdf'}


def validate_uploaded_image(uploaded_file, max_size_mb: int = 10):
    """Valide extension, taille et signature binaire d'une image téléversée (exclut SVG/HTML)."""
    if uploaded_file is None:
        return uploaded_file

    name = getattr(uploaded_file, 'name', '') or ''
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError(
            "Format d'image non autorisé. Formats acceptés : JPG, PNG, WEBP, GIF."
        )

    max_bytes = max_size_mb * 1024 * 1024
    size = getattr(uploaded_file, 'size', None)
    if size is not None and size > max_bytes:
        raise serializers.ValidationError(
            f"Le fichier dépasse la taille maximale autorisée ({max_size_mb} Mo)."
        )

    try:
        pos = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else None
        img = Image.open(uploaded_file)
        img.verify()
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(pos if pos is not None else 0)
    except (UnidentifiedImageError, Exception):
        if hasattr(uploaded_file, 'seek'):
            try:
                uploaded_file.seek(0)
            except Exception:
                pass
        raise serializers.ValidationError("Le fichier téléversé n'est pas une image valide.")

    return uploaded_file


def validate_uploaded_document(uploaded_file, max_size_mb: int = 15, allow_heic: bool = False):
    """Valide extension, taille et magic bytes d'un document (images raster, PDF, HEIC optionnel)."""
    if uploaded_file is None:
        return uploaded_file

    allowed = set(ALLOWED_DOC_EXTENSIONS)
    if allow_heic:
        allowed.add('.heic')

    name = getattr(uploaded_file, 'name', '') or ''
    ext = os.path.splitext(name)[1].lower()
    if ext not in allowed:
        formats = "JPG, JPEG, PNG, WEBP, GIF, PDF" + (", HEIC" if allow_heic else "")
        raise serializers.ValidationError(
            f"Format de fichier non autorisé ({ext or 'inconnu'}). Formats acceptés : {formats}."
        )

    max_bytes = max_size_mb * 1024 * 1024
    size = getattr(uploaded_file, 'size', None)
    if size is not None and size > max_bytes:
        raise serializers.ValidationError(
            f"Le fichier dépasse la taille maximale autorisée ({max_size_mb} Mo)."
        )

    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return validate_uploaded_image(uploaded_file, max_size_mb=max_size_mb)

    pos = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else None
    try:
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(0)
        header = uploaded_file.read(16) or b''
    finally:
        if hasattr(uploaded_file, 'seek'):
            try:
                uploaded_file.seek(pos if pos is not None else 0)
            except Exception:
                pass

    if ext == '.pdf':
        if not header.startswith(b'%PDF-'):
            raise serializers.ValidationError("Le fichier PDF téléversé est invalide ou corrompu.")
    elif ext == '.heic':
        if len(header) < 12 or header[4:8] != b'ftyp':
            raise serializers.ValidationError("Le fichier HEIC téléversé est invalide.")

    return uploaded_file
