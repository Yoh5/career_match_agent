"""Orchestrateur agentique (#2) — boucle ReAct où le LLM CHOISIT ses outils.

Un seul point d'entrée, `prepare_application()` : au lieu d'un pipeline figé, le
modèle décide lui-même quels outils appeler et dans quel ordre — récupérer l'offre,
mesurer l'ATS, analyser le fit, consulter la mémoire, recommander (go/no-go), puis
générer lettre et CV adapté s'il juge que ça vaut le coup — jusqu'à `finish`.

Chaque étape est tracée (outil + résumé). Fail-open : toute erreur LLM/outil est
renvoyée proprement. Aucune invention (les outils s'appuient sur le CV réel).
"""
import json
from typing import Dict, List, Tuple

from core import agent, ats, extract, llm, memory, render

# --- Schémas d'outils exposés au LLM (function-calling OpenAI) ---
TOOLS = [
    {"type": "function", "function": {
        "name": "fetch_offer",
        "description": "Récupère le texte d'une offre depuis une URL (si l'offre n'a pas été fournie en texte).",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "ats_coverage",
        "description": "Mesure déterministe : % de mots-clés de l'offre présents dans le CV + ceux qui manquent.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "analyze_fit",
        "description": "Analyse LLM du fit CV↔offre : score, forces, écarts, projets à mettre en avant, suggestions.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "recall_memory",
        "description": "Consulte la mémoire long terme : cette offre a-t-elle déjà été traitée ? écarts récurrents du candidat ?",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "recommend",
        "description": "Décision go/no-go (postuler / renforcer d'abord / passer) + plan d'action priorisé.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "write_cover_letter",
        "description": "Rédige la lettre de motivation adaptée à l'offre, ancrée sur le CV réel.",
        "parameters": {"type": "object", "properties": {"tone": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "write_tailored_cv",
        "description": "Génère le CV adapté à l'offre (boucle ATS + anti-invention). À faire si la reco est favorable.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Termine : rends un court résumé de la candidature préparée pour le candidat.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]

_SYS = {
    "fr": ("Tu es un agent de candidature autonome, TOUS MÉTIERS. À partir du CV et de l'offre, "
           "prépare une candidature complète en appelant les outils : mesure l'ATS, analyse le fit, "
           "consulte la mémoire, recommande (go/no-go), puis — si c'est pertinent — génère le CV "
           "adapté et la lettre. N'invente jamais rien. Termine par `finish` avec un résumé clair."),
    "en": ("You are an autonomous job-application agent, ANY FIELD. From the CV and the offer, "
           "prepare a complete application by calling tools: measure ATS, analyse fit, check memory, "
           "recommend (go/no-go), then — if worthwhile — generate the tailored CV and cover letter. "
           "Never fabricate. End with `finish` and a clear summary."),
}


def _keywords(ctx: dict) -> List[str]:
    if ctx.get("_keywords") is None:
        extra, _ = agent.offer_keywords(ctx["offer_text"], ctx["lang"])
        ctx["_keywords"] = ats.extract_keywords(ctx["offer_text"], extra=extra)
    return ctx["_keywords"]


def _ensure_ats(ctx: dict) -> dict:
    if "ats" not in ctx["out"]:
        ctx["out"]["ats"] = ats.coverage(ctx["cv_text"], _keywords(ctx))
    return ctx["out"]["ats"]


def _ensure_analysis(ctx: dict) -> Tuple[dict, str]:
    if "analysis" not in ctx["out"]:
        data, err = agent.analyze(ctx["cv_text"], ctx["offer_text"], _ensure_ats(ctx), ctx["lang"])
        if err:
            return None, err
        ctx["out"]["analysis"] = data
    return ctx["out"]["analysis"], None


def _run_tool(name: str, args: dict, ctx: dict) -> dict:
    """Exécute un outil et renvoie un dict compact (renvoyé au LLM). Les sorties
    complètes sont stockées dans ctx['out']."""
    out = ctx["out"]
    if name == "fetch_offer":
        text, err = extract.fetch_offer_url(args.get("url", ""))
        if err:
            return {"error": err}
        ctx["offer_text"] = text
        ctx["_keywords"] = None
        return {"chars": len(text), "preview": text[:200]}

    if name == "ats_coverage":
        cov = _ensure_ats(ctx)
        return {"pct": cov["pct"], "missing": cov["missing"][:12]}

    if name == "analyze_fit":
        data, err = _ensure_analysis(ctx)
        if err:
            return {"error": err}
        return {"fit_score": data["fit_score"], "verdict": data["verdict"],
                "gaps": data["gaps"][:5], "projects_to_highlight": data["projects_to_highlight"][:5]}

    if name == "recall_memory":
        prev = memory.recall(ctx["offer_text"])
        prof = memory.profile_summary()
        out["memory"] = {"seen_before": bool(prev), "previous": prev, "profile": prof}
        return {"seen_before": bool(prev),
                "previous_recommendation": (prev or {}).get("recommendation"),
                "recurring_gaps": prof.get("recurring_gaps", [])}

    if name == "recommend":
        data, err = _ensure_analysis(ctx)
        if err:
            return {"error": err}
        note = ""
        if out.get("memory"):
            gaps = out["memory"]["profile"].get("recurring_gaps", [])
            note = ", ".join(g["keyword"] for g in gaps) if gaps else ""
        rec, err = agent.recommend(data, _ensure_ats(ctx), ctx["lang"], memory_note=note)
        if err:
            return {"error": err}
        out["recommendation"] = rec
        return {"decision": rec["decision"], "confidence": rec["confidence"],
                "action_plan": rec["action_plan"][:6]}

    if name == "write_cover_letter":
        text, err = agent.cover_letter(ctx["cv_text"], ctx["offer_text"], ctx["lang"],
                                       args.get("tone", "professionnel"))
        if err:
            return {"error": err}
        out["cover_letter"] = text
        return {"chars": len(text), "preview": text[:160]}

    if name == "write_tailored_cv":
        res, err = agent.optimize_cv(ctx["cv_text"], ctx["offer_text"], ctx["lang"])
        if err:
            return {"error": err}
        structured, _ = agent.cv_to_structured(res["cv_markdown"], ctx["lang"])   # fail-open
        res["cv_html"] = render.cv_html(res["cv_markdown"], structured, ctx["lang"])
        out["tailored_cv"] = res
        return {"ats_start": res["ats_start"], "ats_final": res["ats_final"],
                "unsupported_final": len(res["unsupported_final"])}

    if name == "finish":
        out["summary"] = str(args.get("summary", "")).strip()
        return {"done": True}

    return {"error": f"outil inconnu: {name}"}


def prepare_application(cv_text: str, offer_text: str = "", offer_url: str = "",
                        lang: str = "fr", max_steps: int = 8) -> tuple:
    """Boucle ReAct autonome. Le LLM enchaîne les outils jusqu'à `finish`.
    Retourne (result, err). result = {steps[], analysis, ats, recommendation,
    cover_letter, tailored_cv, memory, summary} (clés présentes selon ce que
    l'agent a jugé utile de produire)."""
    lg = "en" if str(lang).lower().startswith("en") else "fr"
    ctx = {"cv_text": cv_text, "offer_text": offer_text or "", "offer_url": offer_url or "",
           "lang": lg, "_keywords": None, "out": {"steps": []}}

    task = (f"CV:\n{cv_text[:5000]}\n\nOFFER:\n{offer_text[:5000]}"
            if offer_text else f"CV:\n{cv_text[:5000]}\n\nOFFER URL: {offer_url}")
    messages = [{"role": "system", "content": _SYS[lg]}, {"role": "user", "content": task}]

    for _ in range(max(1, max_steps)):
        msg, err = llm.complete_tools(messages, TOOLS)
        if err:
            return None, err
        calls = msg.get("tool_calls") or []
        if not calls:                                   # le LLM a répondu en texte → fin
            ctx["out"].setdefault("summary", (msg.get("content") or "").strip())
            break
        messages.append({"role": "assistant", "content": msg.get("content"),
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"],
                                                      "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                                        for c in calls]})
        done = False
        for c in calls:
            result = _run_tool(c["name"], c["arguments"], ctx)
            ctx["out"]["steps"].append({"tool": c["name"], "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False)[:3500]})
            if c["name"] == "finish":
                done = True
        if done:
            break

    # persiste en mémoire long terme ce que l'agent a produit
    _persist(ctx)
    return ctx["out"], None


def _persist(ctx: dict) -> None:
    out = ctx["out"]
    a = out.get("analysis") or {}
    cov = out.get("ats") or {}
    rec = out.get("recommendation") or {}
    if a or cov:
        memory.record_application(ctx["offer_text"], {
            "fit_score": a.get("fit_score"),
            "ats_pct": cov.get("pct"),
            "recommendation": rec.get("decision"),
            "missing_keywords": cov.get("missing"),
        })
