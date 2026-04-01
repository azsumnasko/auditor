#!/usr/bin/env python3
"""
analyze_interviews.py -- Extract signals from interview notes via LLM (Ollama).

Accepts interview notes as JSON or plain text, runs them through a local
Ollama model to extract:
  - Recurring themes
  - Quotes mapped to scorecard domains
  - Sentiment per domain
  - Contradictions between roles

Outputs ``interview_signals.json`` that score_engine.py can ingest.
"""

import os
import json
import logging
from datetime import datetime, timezone

import requests

from analytics_utils import load_env, write_json, read_json

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an engineering due diligence auditor analyzing interview transcripts.

You will receive interview notes from multiple roles (CTO, EM, Tech Lead, PM).

Extract and return a JSON object with:
1. "themes": array of { "theme": string, "count": number, "roles": [string], "domain": string }
2. "quotes": array of { "text": string, "role": string, "domain": string, "sentiment": "positive"|"negative"|"neutral" }
3. "domain_sentiment": { "delivery_flow": -1 to 1, "architecture_health": -1 to 1, "team_topology": -1 to 1, "decision_making": -1 to 1, "tech_debt_sustainability": -1 to 1 }
4. "contradictions": array of { "topic": string, "role_a": string, "claim_a": string, "role_b": string, "claim_b": string }
5. "red_flags": array of strings

Domain mapping:
- delivery_flow: lead time, deployment, velocity, sprints, predictability
- architecture_health: coupling, fear zones, bus factor, tech stack
- team_topology: ownership, teams, dependencies, communication
- decision_making: who decides, governance, bottlenecks, frameworks
- tech_debt_sustainability: debt, burnout, documentation, testing, maintenance

Return ONLY valid JSON, no markdown."""


def _call_ollama(prompt, model="llama3", base_url="http://localhost:11434"):
    """Send a prompt to Ollama and parse JSON response."""
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "system": SYSTEM_PROMPT, "stream": False},
            timeout=120,
        )
        if resp.status_code != 200:
            log.warning("Ollama returned %s", resp.status_code)
            return None
        text = resp.json().get("response", "")
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return None
    except Exception as exc:
        log.warning("Ollama call failed: %s", exc)
        return None


def _load_notes(input_path):
    """Load interview notes from JSON file or plain text."""
    if not os.path.isfile(input_path):
        return None
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"raw_text": content}


def analyze(notes, ollama_model="llama3", ollama_url="http://localhost:11434"):
    """Run interview notes through Ollama LLM for analysis."""
    if isinstance(notes, dict) and "raw_text" in notes:
        prompt = f"Analyze these interview notes:\n\n{notes['raw_text'][:8000]}"
    elif isinstance(notes, dict) and "interviews" in notes:
        parts = []
        for interview in notes["interviews"]:
            role = interview.get("role", "Unknown")
            text = interview.get("notes", interview.get("text", ""))
            parts.append(f"## {role}\n{text}")
        prompt = "Analyze these interview notes:\n\n" + "\n\n".join(parts)[:8000]
    else:
        prompt = f"Analyze these interview notes:\n\n{json.dumps(notes, indent=2)[:8000]}"

    result = _call_ollama(prompt, model=ollama_model, base_url=ollama_url)
    if not result:
        return {
            "themes": [],
            "quotes": [],
            "domain_sentiment": {},
            "contradictions": [],
            "red_flags": [],
            "error": "LLM analysis failed -- ensure Ollama is running",
        }
    return result


def main():
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR") or os.path.dirname(__file__) or "."
    input_path = os.environ.get("INTERVIEW_NOTES_PATH", os.path.join(output_dir, "interview_notes.json"))
    ollama_model = os.environ.get("OLLAMA_MODEL", "llama3")
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    notes = _load_notes(input_path)
    if not notes:
        print(f"[analyze_interviews] No interview notes found at {input_path}, skipping.")
        return None

    print(f"[analyze_interviews] Analyzing notes with {ollama_model}...")
    signals = analyze(notes, ollama_model, ollama_url)
    signals["run_iso_ts"] = datetime.now(timezone.utc).isoformat()
    signals["source_file"] = input_path

    path = write_json(signals, "interview_signals", output_dir)
    print(f"[analyze_interviews] Wrote {path}")
    print(f"  Themes: {len(signals.get('themes', []))}")
    print(f"  Quotes: {len(signals.get('quotes', []))}")
    print(f"  Red flags: {len(signals.get('red_flags', []))}")

    return signals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
