#!/usr/bin/env python3
"""
survey_generator.py -- Generate a structured survey template.

Produces a JSON survey mapped to the 5 scorecard domains, with questions
reformulated as 1-5 scales from the interview guides in mds/2.

Outputs ``survey_template.json``.
"""

import os
import json
import logging
from datetime import datetime, timezone

from analytics_utils import load_env

log = logging.getLogger(__name__)

SURVEY_QUESTIONS = [
    {
        "id": "df_1",
        "domain": "delivery_flow",
        "question": "How predictable is your delivery (idea to production)?",
        "scale": {"1": "Very unpredictable", "3": "Somewhat predictable", "5": "Highly predictable"},
    },
    {
        "id": "df_2",
        "domain": "delivery_flow",
        "question": "How much unplanned work does the team handle?",
        "scale": {"1": ">50% unplanned", "3": "15-30% unplanned", "5": "<10% unplanned"},
    },
    {
        "id": "df_3",
        "domain": "delivery_flow",
        "question": "How quickly can a change go from commit to production?",
        "scale": {"1": ">2 weeks", "3": "A few days", "5": "Same day"},
    },
    {
        "id": "ah_1",
        "domain": "architecture_health",
        "question": "How independently can teams release their services?",
        "scale": {"1": "Fully coupled releases", "3": "Some coordination needed", "5": "Fully independent"},
    },
    {
        "id": "ah_2",
        "domain": "architecture_health",
        "question": "Are there parts of the system everyone avoids changing?",
        "scale": {"1": "Many fear zones", "3": "A few risky areas", "5": "No fear zones"},
    },
    {
        "id": "ah_3",
        "domain": "architecture_health",
        "question": "How distributed is knowledge of the codebase?",
        "scale": {"1": "1-2 people know everything", "3": "Some shared knowledge", "5": "Well-distributed ownership"},
    },
    {
        "id": "tt_1",
        "domain": "team_topology",
        "question": "How clear is code and service ownership?",
        "scale": {"1": "No clear ownership", "3": "Partial ownership", "5": "Clear owners for everything"},
    },
    {
        "id": "tt_2",
        "domain": "team_topology",
        "question": "How often are teams blocked by external dependencies?",
        "scale": {"1": "Every sprint", "3": "Occasionally", "5": "Rarely/never"},
    },
    {
        "id": "dm_1",
        "domain": "decision_making",
        "question": "How are technical decisions made?",
        "scale": {"1": "One person decides everything", "3": "Informal consensus", "5": "Clear framework with delegation"},
    },
    {
        "id": "dm_2",
        "domain": "decision_making",
        "question": "How quickly are architectural disputes resolved?",
        "scale": {"1": "Weeks/never", "3": "Days", "5": "Same meeting/day"},
    },
    {
        "id": "td_1",
        "domain": "tech_debt_sustainability",
        "question": "How well is technical debt managed?",
        "scale": {"1": "No debt allocation", "3": "Ad-hoc debt work", "5": "Dedicated debt budget"},
    },
    {
        "id": "td_2",
        "domain": "tech_debt_sustainability",
        "question": "How often do you work on weekends or after hours?",
        "scale": {"1": "Every week", "3": "Sometimes around releases", "5": "Almost never"},
    },
    {
        "id": "td_3",
        "domain": "tech_debt_sustainability",
        "question": "How well-documented are user stories / requirements?",
        "scale": {"1": "No descriptions", "3": "Brief descriptions", "5": "Detailed with acceptance criteria"},
    },
]


def generate_survey():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0",
        "instructions": "Rate each question from 1 (worst) to 5 (best). Be honest -- this is anonymous.",
        "domains": {
            "delivery_flow": "Delivery Flow",
            "architecture_health": "Architecture & Technical Health",
            "team_topology": "Team Topology & Org Model",
            "decision_making": "Decision-Making & Governance",
            "tech_debt_sustainability": "Tech Debt & Sustainability",
        },
        "questions": SURVEY_QUESTIONS,
    }


def main():
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR") or os.path.dirname(__file__) or "."

    survey = generate_survey()
    path = os.path.join(output_dir, "survey_template.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(survey, f, indent=2, ensure_ascii=False)
    print(f"[survey_generator] Wrote {path} ({len(SURVEY_QUESTIONS)} questions)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
