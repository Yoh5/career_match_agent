# 🎯 Career Match Agent — tailor your application to any job offer

Upload your CV, paste a job/internship offer → the agent **scores the fit**, tells you **which projects to highlight**, **suggests concrete CV improvements to raise the score**, and generates an **ATS-optimised, tailored CV** and **cover letter** — in **French or English**.

> Built for a real need: apply *strategically* instead of sending the same CV everywhere. The agent reasons over the CV **and** the offer, and blends a **deterministic ATS keyword signal** with LLM analysis.
>
> **Integrity by design:** it never fabricates — it only reorganises, rephrases and surfaces what is genuinely in your CV.

**Stack:** Python · FastAPI · OpenAI · pypdf / python-docx · vanilla-JS frontend · 17 unit tests (no network, no API key)

---

## ✨ What it does

| Capability | Detail |
|---|---|
| 📊 **Fit score (0–100)** | LLM assessment + a **deterministic ATS keyword-coverage %** (which offer keywords are/aren't in your CV) — an objective signal, not just vibes. |
| 📌 **Projects to highlight** | Which of *your* projects to emphasise **for this specific offer**, and why. |
| ✎ **CV improvement suggestions** | Concrete, actionable edits (wording, missing keywords, ordering, quantification) to raise the score. |
| 📝 **Tailored CV** | Your CV rewritten & reordered for the offer, **ATS-friendly** (single column, standard sections, exact keywords you truly have). |
| ✉️ **Cover letter** | Tailored to the offer, tone-selectable, grounded in your real experience. |
| 🌍 **Bilingual** | All outputs in **French or English** (your choice). |
| 🛡️ **ATS-optimised** | Plain, keyword-aligned, parsable output — to pass automated screening. |
| 🔁 **Agentic optimisation loop** | The tailored CV isn't a one-shot: the agent **generates → measures ATS coverage (deterministic) → verifies integrity → revises**, keeping the best version. A real goal-directed loop with a measurable objective. |

## 🔁 The agentic loop (tailored CV)

`optimize_cv()` doesn't just generate — it *iterates toward a goal*:

```
generate tailored CV
  └─► loop (bounded):
        measure   ats.coverage(cv, offer_keywords)      ← deterministic objective (%)
        verify    agent.verify_grounding(cv, base_cv)    ← anti-fabrication check
        if ATS ≥ target AND no invented claims → stop
        else revise (add real missing keywords, remove unsupported claims) → repeat
  └─► return the BEST version (0 fabrication first, then highest ATS) + a trace
```

It keeps the candidate honest (unsupported claims are detected and removed) **and** pushes the ATS score up — a measurable generate→evaluate→reflect→revise loop, not a single prompt.

## 🏗️ How it works

```
CV (PDF/DOCX/TXT/MD) ──► extract.py         plain text
Job offer (text/URL) ──► extract.fetch_url  plain text
        │
        ├─► ats.py         deterministic: offer keywords → coverage % vs CV   (tested, no LLM)
        └─► agent.py        LLM: fit score, strengths/gaps, projects, CV suggestions,
                            cover letter, and an agentic optimise_cv() loop
                            (generate → measure → verify_grounding → revise)
```

The **ATS layer is deterministic and unit-tested** — it doubles as the loop's objective function; the LLM layer adds the reasoning. Every LLM function returns `(result, err)` — the API surfaces a clear error instead of crashing.

## 🚀 Quickstart

```bash
cd backend
python -m venv venv && venv\Scripts\activate      # Windows (source venv/bin/activate on Unix)
pip install -r requirements.txt
copy .env.example .env                             # then set OPENAI_API_KEY

uvicorn app:app --reload                            # → http://localhost:8000
```
Open `http://localhost:8000`, upload your CV, paste an offer, and go.

```bash
python -m pytest tests/ -q                          # 17 tests, no network / no API key
```

## 🔌 API

| Endpoint | Body | Returns |
|---|---|---|
| `POST /extract-cv` | multipart file | `{cv_text, chars}` |
| `POST /analyze` | `{cv_text, offer_text\|offer_url, lang}` | `{ats, keywords, analysis}` |
| `POST /cover-letter` | `{cv_text, offer_text, lang, tone}` | `{cover_letter}` |
| `POST /tailored-cv` | `{cv_text, offer_text, lang}` | `{tailored_cv_markdown, ats_start, ats_final, iterations, unsupported_final}` |

## 🗂️ Layout

```
backend/
  app.py            FastAPI + serves the frontend
  core/
    llm.py          OpenAI client + tolerant JSON parse
    ats.py          deterministic keyword extraction + coverage (tested)
    extract.py      CV text (PDF/DOCX/TXT/MD) + offer URL → text
    agent.py        analyze · cover_letter · tailored_cv · verify_grounding ·
                    optimize_cv (agentic loop) — bilingual, ATS, no-fabrication
  tests/            17 unit tests
frontend/index.html  single-page UI
```

---

*Built by [Axel AHO](https://github.com/Yoh5) — AI/Agent engineering, automation, Python.*
