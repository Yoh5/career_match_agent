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
    """Document HTML complet, autonome, imprimable A4 (ATS-friendly).
    Repli simple si la structuration LLM n'est pas disponible."""
    body = md_to_html_fragment(md)
    return (
        "<!doctype html>\n<html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head>\n"
        f"<body>\n{body}\n</body></html>"
    )


# =============================================================================
# CV HTML MIS EN PAGE (deux colonnes, template professionnel) depuis un JSON
# structuré — s'inspire du CV de candidature de référence.
# =============================================================================

_LABELS = {
    "fr": {"profile": "Profil", "exp": "Expériences", "proj": "Projets",
           "skills": "Compétences", "edu": "Formation", "certs": "Certifications",
           "langs": "Langues", "links": "Liens"},
    "en": {"profile": "Profile", "exp": "Experience", "proj": "Projects",
           "skills": "Skills", "edu": "Education", "certs": "Certifications",
           "langs": "Languages", "links": "Links"},
}

_CV_CSS = """
:root{--ink:#1f2430;--muted:#5b6472;--line:#e4e7ee;--accent:#4f46e5;
  --accent-soft:#eef0ff;--sidebar:#f6f7fb;}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--ink);font-size:10.6px;line-height:1.5;background:#eceef3}
.page{width:210mm;min-height:297mm;margin:14px auto;background:#fff;
  box-shadow:0 6px 30px rgba(20,30,60,.12);overflow:hidden}
header{padding:24px 30px 20px;border-bottom:3px solid var(--accent)}
header .name{font-size:30px;font-weight:800;letter-spacing:-.5px;line-height:1.05}
header .role{margin-top:4px;font-size:12.5px;font-weight:600;color:var(--accent)}
header .contact{margin-top:10px;display:flex;flex-wrap:wrap;gap:5px 16px;
  font-size:10px;color:var(--muted)}
header .contact a{color:var(--muted);text-decoration:none}
.grid{display:grid;grid-template-columns:1.95fr 1fr}
.main{padding:18px 26px 26px}
.side{padding:18px 20px 26px;background:var(--sidebar);border-left:1px solid var(--line)}
.sec{margin-top:16px}.sec:first-child{margin-top:0}
.sec h2{font-size:10px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;
  color:var(--accent);padding-bottom:4px;margin-bottom:9px;border-bottom:1.5px solid var(--line)}
.side h2{border-bottom-color:#dfe3ee}
.entry{margin-bottom:12px;page-break-inside:avoid}
.entry .top{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.entry .title{font-size:12px;font-weight:700}
.entry .date{font-size:9.3px;color:var(--muted);white-space:nowrap;font-weight:600}
.entry .org{font-size:10.5px;color:var(--accent);font-weight:600;margin-top:1px}
.entry .stack{font-size:9.5px;color:var(--muted);font-style:italic;margin-top:2px}
ul{list-style:none;margin-top:5px}
ul li{position:relative;padding-left:12px;margin-bottom:2.5px}
ul li::before{content:"▹";position:absolute;left:0;color:var(--accent);font-size:9px;top:1px}
.lead{font-size:10.6px;color:#333b49}
.kv{margin-bottom:9px}.kv .k{font-size:9.5px;font-weight:700;color:var(--ink)}
.kv .v{font-size:9.8px;color:var(--muted);margin-top:1px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}
.chips span{background:var(--accent-soft);color:var(--accent);border-radius:5px;
  padding:2px 6px;font-size:8.8px;font-weight:600}
.link{font-size:9.6px;color:var(--muted);word-break:break-all}
.link b{display:block;color:var(--ink);font-size:9px;text-transform:uppercase;letter-spacing:.5px}
.link+.link{margin-top:6px}
@media print{body{background:#fff}.page{margin:0;box-shadow:none;width:auto;min-height:auto}
  @page{size:A4;margin:11mm}}
"""


def _e(v) -> str:
    return escape(str(v or "").strip(), quote=True)


def _clean_list(v):
    return [x for x in v if str(x).strip()] if isinstance(v, list) else []


def _entry_html(e: dict, date_key: str) -> str:
    title = _e(e.get("title"))
    date = _e(e.get(date_key) or e.get("date") or e.get("meta"))
    org = _e(e.get("org"))
    stack = _e(e.get("stack"))
    bullets = "".join(f"<li>{_e(b)}</li>" for b in _clean_list(e.get("bullets")))
    html = ['<div class="entry"><div class="top">'
            f'<div class="title">{title}</div>'
            + (f'<div class="date">{date}</div>' if date else "") + "</div>"]
    if org:
        html.append(f'<div class="org">{org}</div>')
    if stack:
        html.append(f'<div class="stack">{stack}</div>')
    if bullets:
        html.append(f"<ul>{bullets}</ul>")
    html.append("</div>")
    return "".join(html)


def cv_html_from_structured(data: dict, lang: str = "fr") -> str:
    """Rend un CV HTML mis en page (deux colonnes, imprimable A4) à partir du JSON
    structuré produit par `agent.cv_to_structured`. Sections vides ignorées."""
    L = _LABELS["en" if str(lang).lower().startswith("en") else "fr"]
    d = data or {}
    name = _e(d.get("name")) or "CV"
    c = d.get("contact") or {}

    contact_bits = []
    if c.get("email"):
        contact_bits.append(f'<span>✉ <a href="mailto:{_e(c["email"])}">{_e(c["email"])}</a></span>')
    if c.get("phone"):
        contact_bits.append(f'<span>📱 {_e(c["phone"])}</span>')
    if c.get("location"):
        contact_bits.append(f'<span>📍 {_e(c["location"])}</span>')
    for key, icon in (("linkedin", "in"), ("github", "⌥"), ("portfolio", "🌐")):
        if c.get(key):
            contact_bits.append(f'<span>{icon} {_e(c[key])}</span>')

    main = []
    if d.get("summary"):
        main.append(f'<div class="sec"><h2>{L["profile"]}</h2>'
                    f'<p class="lead">{_e(d["summary"])}</p></div>')
    exps = _clean_list(d.get("experiences"))
    if exps:
        main.append(f'<div class="sec"><h2>{L["exp"]}</h2>'
                    + "".join(_entry_html(x, "date") for x in exps if isinstance(x, dict)) + "</div>")
    projs = _clean_list(d.get("projects"))
    if projs:
        main.append(f'<div class="sec"><h2>{L["proj"]}</h2>'
                    + "".join(_entry_html(x, "meta") for x in projs if isinstance(x, dict)) + "</div>")

    side = []
    skills = _clean_list(d.get("skills"))
    if skills:
        blocks = []
        for grp in skills:
            if not isinstance(grp, dict):
                continue
            items = "".join(f"<span>{_e(i)}</span>" for i in _clean_list(grp.get("items")))
            g = _e(grp.get("group"))
            blocks.append((f'<div class="kv"><div class="k">{g}</div>' if g else '<div class="kv">')
                          + f'<div class="chips">{items}</div></div>')
        side.append(f'<div class="sec"><h2>{L["skills"]}</h2>' + "".join(blocks) + "</div>")
    edu = _clean_list(d.get("education"))
    if edu:
        rows = "".join(
            f'<div class="kv"><div class="k">{_e(x.get("title"))}</div>'
            + (f'<div class="v">{_e(x.get("meta"))}</div>' if x.get("meta") else "") + "</div>"
            for x in edu if isinstance(x, dict))
        side.append(f'<div class="sec"><h2>{L["edu"]}</h2>{rows}</div>')
    certs = _clean_list(d.get("certifications"))
    if certs:
        side.append(f'<div class="sec"><h2>{L["certs"]}</h2>'
                    + "".join(f'<div class="kv"><div class="v">{_e(x)}</div></div>' for x in certs) + "</div>")
    langs = _clean_list(d.get("languages"))
    if langs:
        side.append(f'<div class="sec"><h2>{L["langs"]}</h2>'
                    + "".join(f'<div class="kv"><div class="v">{_e(x)}</div></div>' for x in langs) + "</div>")
    links = []
    for key, lbl in (("github", "GitHub"), ("linkedin", "LinkedIn"), ("portfolio", "Portfolio")):
        if c.get(key):
            links.append(f'<div class="link"><b>{lbl}</b>{_e(c[key])}</div>')
    if links:
        side.append(f'<div class="sec"><h2>{L["links"]}</h2>' + "".join(links) + "</div>")

    role = f'<div class="role">{_e(d.get("role"))}</div>' if d.get("role") else ""
    contact = f'<div class="contact">{"".join(contact_bits)}</div>' if contact_bits else ""
    return (
        "<!doctype html>\n<html lang=\"" + ("en" if str(lang).lower().startswith("en") else "fr") + "\">"
        "<head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{name}</title><style>{_CV_CSS}</style></head>\n<body>\n"
        f'<div class="page"><header><div class="name">{name}</div>{role}{contact}</header>'
        f'<div class="grid"><div class="main">{"".join(main)}</div>'
        f'<div class="side">{"".join(side)}</div></div></div>\n</body></html>'
    )


def cv_html(cv_markdown: str, structured: dict = None, lang: str = "fr") -> str:
    """Point d'entrée unique : rend le CV en HTML mis en page si `structured` est
    fourni (JSON de `agent.cv_to_structured`), sinon repli sur Markdown→HTML."""
    if structured:
        try:
            return cv_html_from_structured(structured, lang)
        except Exception:
            pass
    return cv_markdown_to_html(cv_markdown, title_from_markdown(cv_markdown))
