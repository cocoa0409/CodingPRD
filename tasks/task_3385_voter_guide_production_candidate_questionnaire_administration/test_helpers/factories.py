"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    DEFAULT_QUESTION,
    EXPLANATION_TEXT,
    FILING_DEADLINE,
    QUESTIONNAIRE_DUE_AT,
)


def make_clock_payload(current_utc, **overrides):
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def make_cycle_payload(**overrides):
    payload = {"cycle_name": "2026 General", "election_date": "2026-11-03"}
    payload.update(overrides)
    return payload


def make_jurisdiction_payload(**overrides):
    payload = {
        "jurisdiction_name": "City of Springfield",
        "fips_code": "06001",
        "supported_language_codes": ["EN"],
        "reading_level_metric": "FLESCH_KINCAID",
    }
    payload.update(overrides)
    return payload


def make_contest_payload(**overrides):
    payload = {
        "kind": "CANDIDATE_RACE",
        "office_name": "Mayor",
        "filing_deadline": FILING_DEADLINE,
    }
    payload.update(overrides)
    return payload


def make_measure_contest_payload(**overrides):
    payload = {"kind": "BALLOT_MEASURE", "filing_deadline": FILING_DEADLINE}
    payload.update(overrides)
    return payload


def make_filing_payload(**overrides):
    payload = {
        "candidate_name": "Ana One",
        "party_label": "Nonpartisan",
        "filing_reference": "F-1",
    }
    payload.update(overrides)
    return payload


def make_question(position_index=1, prompt_text="Why are you running?", **overrides):
    question = {"position_index": position_index, "prompt_text": prompt_text}
    question.update(overrides)
    return question


def make_questionnaire_payload(**overrides):
    payload = {
        "due_at": QUESTIONNAIRE_DUE_AT,
        "questions": [dict(DEFAULT_QUESTION)],
    }
    payload.update(overrides)
    return payload


def make_answer(position_index=1, text="one two three four five"):
    return {"position_index": position_index, "text": text}


def make_answers_payload(*answers, **overrides):
    payload = {"answers": list(answers) if answers else [make_answer()]}
    payload.update(overrides)
    return payload


def make_measure_payload(**overrides):
    payload = {
        "measure_title": "Measure A",
        "official_text": "Official text A",
        "explanation_text": EXPLANATION_TEXT,
    }
    payload.update(overrides)
    return payload


def make_argument_payload(**overrides):
    payload = {
        "side": "PRO",
        "argument_text": "one two three four five six seven eight nine ten",
        "author_credit": "Committee for the measure",
    }
    payload.update(overrides)
    return payload


def make_review_payload(**overrides):
    payload = {"verdict": "NEUTRAL", "notes": "Balanced and plain."}
    payload.update(overrides)
    return payload


def make_edition_payload(**overrides):
    payload = {
        "language_code": "EN",
        "channel": "PRINT",
        "accessibility_format": "STANDARD",
    }
    payload.update(overrides)
    return payload


def make_channel_request(channel_code, requested, priority_tier):
    return {
        "channel_code": channel_code,
        "requested": requested,
        "priority_tier": priority_tier,
    }


def make_distribute_payload(**overrides):
    payload = {
        "print_run_total": 100,
        "channel_requests": [make_channel_request("LIBRARY", 100, 1)],
    }
    payload.update(overrides)
    return payload


def make_forum_payload(**overrides):
    payload = {
        "scheduled_start": "2026-10-10T10:00:00Z",
        "scheduled_end": "2026-10-10T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_question_payload(**overrides):
    payload = {
        "question_text": "What is your housing plan?",
        "source": "PUBLIC_SUBMISSION",
    }
    payload.update(overrides)
    return payload


def make_volunteer_payload(**overrides):
    payload = {
        "volunteer_name": "Vic Volunteer",
        "chapter_code": "CH1",
        "roles": ["EDITOR"],
    }
    payload.update(overrides)
    return payload


def make_incident_payload(**overrides):
    payload = {
        "volunteer_id": None,
        "incident_type": "PARTISAN_STATEMENT",
        "description": "Alleged nonpartisanship breach.",
    }
    payload.update(overrides)
    return payload
