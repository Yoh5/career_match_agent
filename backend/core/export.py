"""Exports bureautiques : lettre de motivation en .docx, CV en .pdf.

- Lettre → Word via python-docx (déjà utilisé pour LIRE les CV) : marges A4,
  interligne aéré, prête à personnaliser/envoyer.
- CV → PDF via fpdf2 (pur Python, zéro dépendance système — là où career-ops
  passe par Playwright/Chromium). Mise en page 2 colonnes reconstruite depuis le
  JSON structuré (`agent.cv_to_structured`) ; repli simple si structuré absent.

Tout retourne des bytes ; aucune écriture disque, aucune dépendance réseau.
"""
import io
import re
from typing import Dict, List, Optional

# ── Couleurs de la charte (identiques au template HTML) ────────────────────
_ACCENT = (43, 108, 176)     # bleu
_INK = (26, 32, 44)
_MUTED = (74, 85, 104)
_LINE = (226, 232, 240)

_LABELS = {
    "fr": {"profile": "Profil", "experience": "Expériences", "projects": "Projets",
           "education": "Formation", "skills": "Compétences", "certs": "Certifications",
           "langs": "Langues", "links": "Liens"},
    "en": {"profile": "Profile", "experience": "Experience", "projects": "Projects",
           "education": "Education", "skills": "Skills", "certs": "Certifications",
           "langs": "Languages", "links": "Links"},
}


def _latin(s: str) -> str:
    """fpdf2 en polices de base = latin-1 : on remplace les caractères hors charte."""
    repl = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"',
            "”": '"', "•": "-", "…": "...", " ": " ", "→": "->",
            "·": "-", "✅": "", "▸": "-"}
    for a, b in repl.items():
        s = (s or "").replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


# ═══ Lettre de motivation → .docx ═══════════════════════════════════════════

def letter_docx(text: str) -> bytes:
    """Lettre en Word : paragraphes du texte, marges A4, police lisible."""
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_LINE_SPACING

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.2)
    sec.left_margin = sec.right_margin = Cm(2.4)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    for block in re.split(r"\n\s*\n", (text or "").strip()):
        p = doc.add_paragraph(block.strip())
        p.paragraph_format.space_after = Pt(10)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        p.paragraph_format.line_spacing = 1.15

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ═══ CV → .pdf (2 colonnes, depuis le JSON structuré) ═══════════════════════

_M = 12          # marge (mm)
_PAGE_W = 210
_PAGE_H = 297
_MAIN_X, _MAIN_W = _M, 120                  # colonne principale
_SIDE_X = _MAIN_X + _MAIN_W + 8             # barre latérale
_SIDE_W = _PAGE_W - _SIDE_X - _M
_LIMIT_Y = _PAGE_H - _M


class _Col:
    """Curseur de colonne indépendant (x fixe, y qui coule, saut de page géré)."""

    def __init__(self, pdf, x, w, y):
        self.pdf, self.x, self.w, self.y = pdf, x, w, y
        self.page = pdf.page

    def _ensure(self, h):
        if self.y + h > _LIMIT_Y:
            if self.page >= self.pdf.pages_count:
                self.pdf.add_page()
            self.page += 1
            self.pdf.page = self.page
            self.y = _M

    def text(self, s, size=9.2, style="", color=_INK, lh=1.32, before=0.0):
        s = _latin(s).strip()
        if not s:
            return
        self.pdf.page = self.page
        self.pdf.set_font("Helvetica", style, size)
        self.pdf.set_text_color(*color)
        line_h = size * 0.3528 * lh
        self._ensure(line_h + before)
        self.y += before
        self.pdf.set_xy(self.x, self.y)
        self.pdf.multi_cell(self.w, line_h, s)
        self.y = self.pdf.get_y()

    def bullet(self, s, size=9.2):
        s = _latin(s).strip()
        if not s:
            return
        self.pdf.page = self.page
        self.pdf.set_font("Helvetica", "", size)
        line_h = size * 0.3528 * 1.32
        self._ensure(line_h)
        self.pdf.set_text_color(*_ACCENT)
        self.pdf.set_xy(self.x, self.y)
        self.pdf.cell(4, line_h, "-")
        self.pdf.set_text_color(*_INK)
        self.pdf.set_xy(self.x + 4, self.y)
        self.pdf.multi_cell(self.w - 4, line_h, s)
        self.y = self.pdf.get_y()

    def heading(self, s):
        self.pdf.page = self.page
        self._ensure(9)
        self.y += 3.5
        self.text(s.upper(), size=9.6, style="B", color=_ACCENT, before=0)
        self.pdf.page = self.page
        self.pdf.set_draw_color(*_LINE)
        self.pdf.line(self.x, self.y + 0.6, self.x + self.w, self.y + 0.6)
        self.y += 2.4


def _clean(items) -> List:
    return [x for x in (items or []) if x]


def cv_pdf(structured: Optional[Dict], cv_markdown: str = "", lang: str = "fr") -> bytes:
    """CV PDF A4. Avec `structured` → 2 colonnes (bandeau, profil/expériences/projets
    à gauche ; compétences/formation/certifs/langues à droite). Sinon → repli
    simple 1 colonne depuis le Markdown."""
    from fpdf import FPDF

    L = _LABELS.get("en" if str(lang).lower().startswith("en") else "fr", _LABELS["fr"])
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(_M, _M, _M)
    pdf.add_page()

    if not isinstance(structured, dict) or not structured.get("name"):
        return _cv_pdf_fallback(pdf, cv_markdown)

    # ── Bandeau d'en-tête ──
    contact = structured.get("contact") or {}
    contact_bits = _clean([contact.get(k) for k in ("email", "phone", "location", "linkedin", "github", "portfolio")])
    head_h = 30 if contact_bits else 24
    pdf.set_fill_color(*_ACCENT)
    pdf.rect(0, 0, _PAGE_W, head_h, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_xy(_M, 7)
    pdf.cell(0, 8, _latin(structured.get("name") or ""))
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(_M, 15)
    pdf.cell(0, 6, _latin(structured.get("role") or ""))
    if contact_bits:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(_M, 22)
        pdf.multi_cell(_PAGE_W - 2 * _M, 4, _latin("  |  ".join(contact_bits)))

    y0 = head_h + 5
    main = _Col(pdf, _MAIN_X, _MAIN_W, y0)
    side = _Col(pdf, _SIDE_X, _SIDE_W, y0)

    # ── Colonne principale ──
    if structured.get("summary"):
        main.heading(L["profile"])
        main.text(structured["summary"])
    for key, label in (("experiences", L["experience"]), ("projects", L["projects"])):
        entries = _clean(structured.get(key))
        if not entries:
            continue
        main.heading(label)
        for e in entries:
            if not isinstance(e, dict):
                main.bullet(str(e))
                continue
            title = e.get("title") or ""
            org = e.get("org") or e.get("meta") or ""
            head = f"{title} - {org}" if org else title
            main.text(head, style="B", before=1.6)
            sub = " | ".join(_clean([e.get("date"), e.get("stack")]))
            if sub:
                main.text(sub, size=8.2, color=_MUTED)
            for b in _clean(e.get("bullets"))[:6]:
                main.bullet(str(b))

    # ── Barre latérale ──
    pdf.page = side.page
    skills = _clean(structured.get("skills"))
    if skills:
        side.heading(L["skills"])
        for g in skills:
            if isinstance(g, dict):
                if g.get("group"):
                    side.text(str(g["group"]), size=8.6, style="B", before=1.2)
                side.text(", ".join(str(i) for i in _clean(g.get("items"))), size=8.4, color=_MUTED)
            else:
                side.bullet(str(g), size=8.4)
    edu = _clean(structured.get("education"))
    if edu:
        side.heading(L["education"])
        for e in edu:
            if isinstance(e, dict):
                side.text(str(e.get("title") or ""), size=8.6, style="B", before=1.2)
                if e.get("meta"):
                    side.text(str(e["meta"]), size=8.2, color=_MUTED)
            else:
                side.text(str(e), size=8.6, before=1.2)
    for key, label in (("certifications", L["certs"]), ("languages", L["langs"])):
        entries = _clean(structured.get(key))
        if entries:
            side.heading(label)
            for e in entries:
                side.bullet(str(e), size=8.4)
    links = _clean([contact.get(k) for k in ("linkedin", "github", "portfolio")])
    if links:
        side.heading(L["links"])
        for u in links:
            side.text(str(u), size=8.0, color=_ACCENT)

    return bytes(pdf.output())


def _cv_pdf_fallback(pdf, cv_markdown: str) -> bytes:
    """Repli 1 colonne (Markdown brut) si le JSON structuré n'est pas disponible."""
    from fpdf.enums import XPos, YPos

    def cell(h, s):
        # new_x explicite : selon la version de fpdf2, multi_cell laisse sinon le
        # curseur en fin de ligne → « Not enough horizontal space » au bloc suivant
        pdf.multi_cell(0, h, s, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_auto_page_break(True, margin=_M)
    pdf.set_text_color(*_INK)
    for raw in (cv_markdown or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            pdf.ln(2.2)
            continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(*_ACCENT)
            cell(7, _latin(line[2:]))
            pdf.set_text_color(*_INK)
        elif line.startswith("## "):
            pdf.ln(1.5)
            pdf.set_font("Helvetica", "B", 11.5)
            pdf.set_text_color(*_ACCENT)
            cell(5.5, _latin(line[3:].upper()))
            pdf.set_text_color(*_INK)
        elif line.lstrip().startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 9.2)
            cell(4.4, _latin("- " + line.lstrip()[2:].replace("**", "")))
        else:
            pdf.set_font("Helvetica", "", 9.2)
            cell(4.4, _latin(line.replace("**", "")))
    return bytes(pdf.output())
