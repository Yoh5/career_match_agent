"""Career Match Agent — API FastAPI.

Endpoints :
  POST /extract-cv    (multipart) → texte du CV
  POST /analyze       → fit CV↔offre + mots-clés ATS + projets + suggestions CV
  POST /cover-letter  → lettre de motivation adaptée (fr/en, ATS)
  POST /tailored-cv   → CV réécrit pour l'offre (fr/en, ATS, Markdown)

Sert aussi le frontend statique à la racine.
"""
import os

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core import llm, ats, extract, agent

app = FastAPI(title="Career Match Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "index.html")


@app.get("/", response_class=HTMLResponse)
def home():
    try:
        with open(_FRONTEND, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Career Match Agent</h1><p>API prête. Frontend introuvable.</p>"


@app.get("/health")
def health():
    return {"status": "ok", "llm_ready": llm.is_enabled()}


@app.post("/extract-cv")
async def extract_cv(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 10 Mo)")
    text, err = extract.extract_cv_text(file.filename, data)
    if err:
        raise HTTPException(400, err)
    if len((text or "").strip()) < 30:
        raise HTTPException(422, "CV vide ou illisible (PDF scanné en image ?). Essaie un .txt/.md ou un PDF texte.")
    return {"filename": file.filename, "cv_text": text, "chars": len(text)}


class OfferBody(BaseModel):
    cv_text: str
    offer_text: Optional[str] = ""
    offer_url: Optional[str] = ""
    lang: str = "fr"
    tone: Optional[str] = "professionnel"


def _resolve(body: OfferBody):
    """Retourne (cv_text, offer_text) ou lève une HTTPException."""
    cv = (body.cv_text or "").strip()
    if len(cv) < 30:
        raise HTTPException(422, "CV manquant — upload-le d'abord.")
    offer = (body.offer_text or "").strip()
    if not offer and (body.offer_url or "").strip():
        offer, err = extract.fetch_offer_url(body.offer_url)
        if err:
            raise HTTPException(400, f"Offre (URL) : {err}")
    if len(offer) < 30:
        raise HTTPException(422, "Offre manquante — colle le texte de l'offre (ou une URL).")
    return cv, offer


def _guard_llm():
    if not llm.is_enabled():
        raise HTTPException(503, "OPENAI_API_KEY manquante — ajoute ta clé dans backend/.env")


@app.post("/analyze")
def do_analyze(body: OfferBody):
    _guard_llm()
    cv, offer = _resolve(body)
    keywords = ats.extract_keywords(offer)
    cov = ats.coverage(cv, keywords)
    data, err = agent.analyze(cv, offer, cov, body.lang)
    if err:
        raise HTTPException(502, f"Analyse indisponible : {err}")
    return {"ats": cov, "keywords": keywords, "analysis": data}


@app.post("/cover-letter")
def do_cover_letter(body: OfferBody):
    _guard_llm()
    cv, offer = _resolve(body)
    text, err = agent.cover_letter(cv, offer, body.lang, body.tone or "professionnel")
    if err:
        raise HTTPException(502, f"Génération indisponible : {err}")
    return {"cover_letter": text}


@app.post("/tailored-cv")
def do_tailored_cv(body: OfferBody):
    _guard_llm()
    cv, offer = _resolve(body)
    md, err = agent.tailored_cv(cv, offer, body.lang)
    if err:
        raise HTTPException(502, f"Génération indisponible : {err}")
    return {"tailored_cv_markdown": md}
