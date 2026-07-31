"""Extraction de texte : CV uploadé (PDF / DOCX / TXT / MD) et offre depuis une URL.

Tolérant : un format non géré ou une dépendance absente renvoie une erreur claire
plutôt qu'une exception. Le fetch d'URL est borné à http/https (garde-fou minimal).
"""
import re
from html import unescape
from typing import Tuple


def extract_cv_text(filename: str, data: bytes) -> Tuple[str, str]:
    """Retourne (texte, err). err=None si OK. Formats : .pdf .docx .txt .md."""
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            return _pdf(data), None
        if name.endswith(".docx"):
            return _docx(data), None
        if name.endswith((".txt", ".md", ".markdown")):
            return data.decode("utf-8", errors="ignore"), None
        return "", f"Format non supporté : {filename} (utilise .pdf, .docx, .txt ou .md)"
    except Exception as e:
        return "", f"Lecture impossible ({e})"


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # repli
    import io
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


def _docx(data: bytes) -> str:
    from docx import Document
    import io
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs).strip()


def html_to_text(html: str) -> str:
    """Nettoie du HTML en texte lisible (offre récupérée depuis une page)."""
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def fetch_offer_url(url: str, max_chars: int = 12000) -> Tuple[str, str]:
    """Récupère le texte d'une offre depuis une URL http/https. Retourne (texte, err)."""
    if not re.match(r"^https?://", (url or "").strip(), re.IGNORECASE):
        return "", "URL invalide (http/https uniquement)"
    try:
        import httpx
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": "CareerMatchAgent/1.0"}) as client:
            r = client.get(url.strip())
        if r.status_code != 200:
            return "", f"La page a répondu {r.status_code}"
        return html_to_text(r.text)[:max_chars], None
    except Exception as e:
        return "", f"Page injoignable ({e})"
