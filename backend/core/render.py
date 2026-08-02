"""Rendu Markdown → HTML pour le CV adapté — déterministe, sans dépendance, testable.

Le CV généré par l'agent est du Markdown ; on en produit aussi un HTML propre,
**imprimable en PDF** (format A4) et **ATS-friendly** : une seule colonne, texte
sélectionnable, balises sémantiques (h1/h2, ul/ol, p), pas d'image ni de tableau.

Convertisseur volontairement limité au sous-ensemble utilisé par un CV
(titres, gras/italique, listes, liens, ligne horizontale, paragraphes) : pas de
dépendance externe, sortie prévisible, échappement HTML systématique.
"""
import re
from html import escape


def _inline(text: str) -> str:
    """Applique le formatage inline sur du texte DÉJÀ échappé (gras, italique,
    code, liens)."""
    t = escape(text, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)  # liens
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)                     # **gras**
    t = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", t)                         # __gras__
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)                  # *italique*
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)                              # `code`
    return t


def md_to_html_fragment(md: str) -> str:
    """Convertit du Markdown en fragment HTML (sans <html>/<head>)."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    html, para, list_kind = [], [], None

    def flush_para():
        if para:
            html.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_kind
        if list_kind:
            html.append(f"</{list_kind}>")
            list_kind = None

    for raw in lines:
        s = raw.strip()
        if not s:
            flush_para(); close_list(); continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):                 # ligne horizontale
            flush_para(); close_list(); html.append("<hr>"); continue
        m = re.match(r"(#{1,6})\s+(.*)", s)                          # titre
        if m:
            flush_para(); close_list()
            lvl = len(m.group(1))
            html.append(f"<h{lvl}>{_inline(m.group(2).strip())}</h{lvl}>")
            continue
        m = re.match(r"[-*+]\s+(.*)", s)                             # liste à puces
        if m:
            flush_para()
            if list_kind != "ul":
                close_list(); html.append("<ul>"); list_kind = "ul"
            html.append(f"<li>{_inline(m.group(1).strip())}</li>")
            continue
        m = re.match(r"\d+[.)]\s+(.*)", s)                           # liste ordonnée
        if m:
            flush_para()
            if list_kind != "ol":
                close_list(); html.append("<ol>"); list_kind = "ol"
            html.append(f"<li>{_inline(m.group(1).strip())}</li>")
            continue
        close_list(); para.append(s)                                # paragraphe

    flush_para(); close_list()
    return "\n".join(html)


_CSS = """
*{box-sizing:border-box}
body{font-family:"Calibri","Segoe UI",Arial,sans-serif;color:#111;background:#fff;
  max-width:800px;margin:0 auto;padding:32px 40px;line-height:1.45;font-size:11.5pt}
h1{font-size:22pt;margin:0 0 2px;font-weight:700}
h2{font-size:13pt;margin:18px 0 6px;padding-bottom:3px;border-bottom:1.5px solid #333;
  text-transform:uppercase;letter-spacing:.5px}
h3{font-size:11.5pt;margin:12px 0 2px;font-weight:700}
p{margin:4px 0}
ul,ol{margin:4px 0 8px;padding-left:20px}
li{margin:2px 0}
a{color:#111;text-decoration:none}
hr{border:none;border-top:1px solid #ccc;margin:12px 0}
strong{font-weight:700}
@page{size:A4;margin:14mm}
@media print{body{padding:0;max-width:none}}
"""


def title_from_markdown(md: str, default: str = "CV") -> str:
    """Titre du document = premier titre `# ...` du Markdown, sinon `default`."""
    for line in (md or "").splitlines():
        m = re.match(r"#\s+(.*)", line.strip())
        if m and m.group(1).strip():
            return m.group(1).strip()[:80]
    return default


def cv_markdown_to_html(md: str, title: str = "CV") -> str:
    """Document HTML complet, autonome, imprimable A4 (ATS-friendly)."""
    body = md_to_html_fragment(md)
    return (
        "<!doctype html>\n<html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head>\n"
        f"<body>\n{body}\n</body></html>"
    )
