# 🎯 Career Match Agent — tailor your application to any job offer, any field

[![tests](https://github.com/Yoh5/career_match_agent/actions/workflows/tests.yml/badge.svg)](https://github.com/Yoh5/career_match_agent/actions/workflows/tests.yml)

![Career Match Agent — fit score, ATS coverage & go/no-go recommendation with action plan](docs/demo-analyze.jpg)

Upload your CV, paste a job/internship offer → the agent **scores the fit**, gives a **go/no-go recommendation with a prioritised action plan**, tells you **which projects to highlight**, **suggests concrete CV improvements to raise the score**, and generates an **ATS-optimised, tailored CV** and **cover letter** — in **French or English**.

> **Any field, not just tech.** ATS keywords are extracted *from the offer itself* by the LLM (marketing, finance, HR, healthcare, legal, sales, engineering…), so the signal is relevant whatever the role — a curated tech list only acts as a deterministic fallback.
>
> Built for a real need: apply *strategically* instead of sending the same CV everywhere. The agent reasons over the CV **and** the offer, and blends a **deterministic ATS keyword signal** with LLM analysis.
>
> **Integrity by design:** it never fabricates — it only reorganises, rephrases and surfaces what is genuinely in your CV.

**Stack:** Python · FastAPI · OpenAI (tool-calling) · pypdf / python-docx · vanilla-JS frontend · 90 unit tests (no network, no API key)

---

## ✨ What it does

| Capability | Detail |
|---|---|
| 📊 **Fit score (0–100)** | LLM assessment + a **deterministic ATS keyword-coverage %** (which offer keywords are/aren't in your CV) — an objective signal, not just vibes. |
| 📌 **Projects to highlight** | Which of *your* projects to emphasise **for this specific offer**, and why. |
| ✎ **CV improvement suggestions** | Concrete, actionable edits (wording, missing keywords, ordering, quantification) to raise the score. |
| 📝 **Tailored CV** | Your CV rewritten & reordered for the offer, **ATS-friendly** (standard sections, exact keywords you truly have). |
| 📄 **Designed HTML CV** | The tailored CV is rendered as a **professional two-column HTML** (accent header, skills sidebar, A4 print) — the LLM structures your CV into JSON, a fixed template lays it out. One click to **download HTML or print to PDF**; falls back to a clean single-column render. |
| ✉️ **Cover letter** | Tailored to the offer, tone-selectable, grounded in your real experience. |
| 🧭 **Go / no-go recommendation** | *Apply · strengthen first · skip* + a **prioritised action plan** — decision, not just data. |
| 🌍 **Bilingual** | All outputs in **French or English** (your choice). |
| 🛡️ **ATS-optimised** | Plain, keyword-aligned, parsable output — to pass automated screening. |
| 🔁 **Agentic optimisation loop** | The tailored CV isn't a one-shot: the agent **generates → measures ATS coverage (deterministic) → verifies integrity → revises**, keeping the best version. A real goal-directed loop with a measurable objective. |
| 🤖 **Autonomous agent (tool-calling)** | `/prepare` runs a **ReAct loop**: the LLM *chooses* which tools to call (measure ATS, analyse, recall memory, recommend, write CV/letter) and in what order — every step is traced. |
| 🧠 **Long-term memory** | Remembers offers already analysed and **recurring gaps** across offers ("you're often missing X") to sharpen future advice. |
| 🔎 **Internship sourcing** | Searches **public ATS job-board APIs** (Greenhouse, Lever, Ashby, RemoteOK) for internships matching your keywords/location (FR/EN location aliases: *Maroc ↔ Morocco ↔ Casablanca…*), and feeds a persistent **application pipeline**. |
| 🗂️ **Application pipeline** | Each offer moves through `sourced → analyzed → ready → sent/skipped`. One click per offer: analyse fit, or build the **full application kit** (tailored CV md+HTML, cover letter, outreach messages). |
| ✍️ **Your message templates** | LinkedIn invite (≤300 chars), LinkedIn message and application e-mail are rendered from **your editable templates** (`{company} {role} {highlight} {first_name}…`), personalised per offer with the best project to highlight. |
| 📤 **Safe outreach via lemlist** *(optional)* | With a `LEMLIST_API_KEY`, one click pushes the recruiter + personalised message into a **lemlist campaign** — lemlist handles the LinkedIn/e-mail sending with safe throttling. No key → copy-paste mode. |

## 🛡️ Why it never auto-applies (by design)

Auto-submitting on LinkedIn/Indeed violates their ToS, gets real accounts banned, and dies on CAPTCHAs. Like the best tools in this space, this agent is **a filter and a builder, not a spray-and-pray auto-applier**: it sources from job boards companies *voluntarily* expose as public JSON APIs, evaluates, and prepares everything — **you always make the final send**. The only automated channel is **lemlist** (optional), a dedicated outreach platform that sends LinkedIn invites/messages and e-mails under its own safe rate limits, triggered one recruiter at a time by *your* click.

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

## 🤖 Why it's a real agent (not a prompt wrapper)

| Agent trait | Here |
|---|---|
| **Autonomous tool-use** | `/prepare` = a ReAct loop where the LLM *decides* which tools to call (fetch offer, measure ATS, analyse, recall memory, recommend, write CV/letter) — `core/orchestrator.py`. |
| **Goal-directed loop** | `optimize_cv` iterates toward a measurable ATS target with an anti-fabrication gate. |
| **Self-critique** | `verify_grounding` checks each claim against the base CV and drives revision. |
| **Planning** | `recommend` turns the assessment into a go/no-go decision + ordered action plan. |
| **Long-term memory** | `core/memory.py` remembers offers and surfaces recurring gaps across sessions. |

Every step is **traced** and shown in the UI, and every LLM call is **fail-open** (a failure degrades gracefully instead of crashing).

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
python -m pytest tests/ -q                          # 90 tests, no network / no API key
```

## 🔌 API

| Endpoint | Body | Returns |
|---|---|---|
| `POST /extract-cv` | multipart file | `{cv_text, chars}` |
| `POST /analyze` | `{cv_text, offer_text\|offer_url, lang}` | `{ats, keywords, analysis, recommendation, memory}` |
| `POST /cover-letter` | `{cv_text, offer_text, lang, tone}` | `{cover_letter}` |
| `POST /tailored-cv` | `{cv_text, offer_text, lang}` | `{tailored_cv_markdown, tailored_cv_html, ats_start, ats_final, iterations, unsupported_final}` |
| `POST /prepare` | `{cv_text, offer_text\|offer_url, lang}` | `{steps[], analysis, ats, recommendation, cover_letter, tailored_cv, summary}` (autonomous agent) |
| `GET /memory` | — | `{count, avg_fit, recurring_gaps[]}` |
| `POST /source` | `{keywords[], location[], greenhouse[], lever[], ashby[], remoteok, internship_only}` | sourced offers → pipeline |
| `GET /pipeline` | `?status=` | `{stats, items[]}` |
| `POST /pipeline/{id}/analyze` | `{cv_text, lang}` | fit + ATS + go/no-go for that offer |
| `POST /pipeline/{id}/prepare` | `{cv_text, lang, tone, my_name, first_name}` | full kit: CV md+HTML, letter, outreach messages |
| `GET \| PUT /templates` | `{templates}` | your editable outreach message templates |
| `GET /outreach/status` · `POST /outreach/send` | `{item_id, campaign_id, email, …}` | push recruiter + message to a lemlist campaign |

## 🗂️ Layout

```
backend/
  app.py            FastAPI + serves the frontend
  core/
    llm.py          OpenAI client (chat + tool-calling) + tolerant JSON parse
    ats.py          deterministic keyword extraction + coverage (tested)
    extract.py      CV text (PDF/DOCX/TXT/MD) + offer URL → text
    agent.py        offer_keywords (any-field ATS) · analyze · recommend (go/no-go) ·
                    cover_letter · tailored_cv · verify_grounding · optimize_cv (loop)
    memory.py       long-term memory: offers seen + recurring gaps (fail-open)
    orchestrator.py ReAct agent — LLM chooses tools until the application is ready
    render.py       CV → designed HTML (2-col template from structured JSON) + Markdown fallback
    sources.py      internship sourcing via public ATS APIs (Greenhouse/Lever/Ashby/RemoteOK)
    pipeline.py     persistent application queue: sourced → analyzed → ready → sent/skipped
    templates.py    your editable outreach message templates (tolerant rendering)
    outreach.py     lemlist client — safe recruiter outreach (fail-open without key)
  tests/            90 unit tests (agent, ats, memory, orchestrator, render, extract, app,
                    sources, pipeline, templates, outreach)
frontend/index.html  single-page UI (light/dark)
```

---

*Built by [Axel AHO](https://github.com/Yoh5) — AI/Agent engineering, automation, Python.*
