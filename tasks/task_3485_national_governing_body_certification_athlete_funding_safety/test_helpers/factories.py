"""Payload factories — one per entity, input fields only.

Every default is PRD-legal against the startup logical clock
(2026-09-01T00:00:00Z): the default certification window opens at the startup
instant, procedure dates satisfy the 90-day publish lead and 14-day
registration-close rules, the default result date sits inside the trailing
window at full recency weight, and windows satisfy their end-after-start
rules. Pass explicit overrides for the boundary values under test.
"""
from .constants import CLOCK_STARTUP_DEFAULT

# ---------------------------------------------------------------------------
# Defaults (PRD-legal against the startup clock)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "BODY_NAME": "US Swim Federation",
    "SPORT_CODE": "SWIM",
    "FUNDING_BUDGET_CENTS": 10_000_000,
    "SPORT_SCIENCE_POOL_HOURS": 100,
    "CYCLE_WINDOW_START": CLOCK_STARTUP_DEFAULT,      # openable immediately
    "CYCLE_WINDOW_END": "2026-12-01T00:00:00Z",
    "COMPLAINT_CATEGORY": "GOVERNANCE",
    "COMPLAINT_SEVERITY": "MINOR",
    "COMPLAINT_DESCRIPTION": "Alleged bylaw violation under review.",
    "ATHLETE_FULL_NAME": "Test Athlete",
    "ATHLETE_DATE_OF_BIRTH": "1998-01-01",
    "EVENT_NAME": "August Cup",
    "EVENT_GRADE": "A",
    "PLACING": 1,
    "EVENT_DATE": "2026-08-01T00:00:00Z",             # 31 days before startup clock
    "COVERAGE_START": CLOCK_STARTUP_DEFAULT,
    "COVERAGE_END": "2027-09-01T00:00:00Z",
    "POINTS_METHOD": "TRAILING_365",
    "REPORTER_ROLE": "NGB_STAFF",
    "ALLEGATION": "Allegation under independent review.",
    "GAMES_NAME": "2028 Summer Olympics",
    "TRIALS_START": "2026-12-15T00:00:00Z",           # 105 days of publish lead
    "TRIALS_END": "2026-12-17T00:00:00Z",
    "REGISTRATION_DEADLINE": "2026-12-01T00:00:00Z",  # exactly 14 days before trials
    "QUALIFYING_SCORE": 80,
    "QUOTA_SLOTS": 2,
    "APPEAL_GROUNDS": "SELECTION_PROCESS",
    "SPONSOR_NAME": "Acme Sponsorship LLC",
    "GROSS_VALUE_CENTS": 1_000_000,
    "DEAL_BASIS": "GROSS_BASIS",
    "EXCLUSIVITY_START": CLOCK_STARTUP_DEFAULT,
    "EXCLUSIVITY_END": "2027-09-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Create payloads
# ---------------------------------------------------------------------------

def create_governing_body_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["BODY_NAME"],
        "sport_code": DEFAULTS["SPORT_CODE"],
        "funding_budget_cents": DEFAULTS["FUNDING_BUDGET_CENTS"],
        "sport_science_pool_hours": DEFAULTS["SPORT_SCIENCE_POOL_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_certification_cycle_payload(**overrides) -> dict:
    payload = {
        "window_start": DEFAULTS["CYCLE_WINDOW_START"],
        "window_end": DEFAULTS["CYCLE_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(**overrides) -> dict:
    payload = {
        "category": DEFAULTS["COMPLAINT_CATEGORY"],
        "severity": DEFAULTS["COMPLAINT_SEVERITY"],
        "description": DEFAULTS["COMPLAINT_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_athlete_payload(governing_body_id, **overrides) -> dict:
    payload = {
        "governing_body_id": governing_body_id,
        "full_name": DEFAULTS["ATHLETE_FULL_NAME"],
        "date_of_birth": DEFAULTS["ATHLETE_DATE_OF_BIRTH"],
        "team_sport": False,
    }
    payload.update(overrides)
    return payload


def create_result_payload(**overrides) -> dict:
    payload = {
        "event_name": DEFAULTS["EVENT_NAME"],
        "event_grade": DEFAULTS["EVENT_GRADE"],
        "placing": DEFAULTS["PLACING"],
        "event_date": DEFAULTS["EVENT_DATE"],
    }
    payload.update(overrides)
    return payload


def create_funding_agreement_payload(**overrides) -> dict:
    payload = {
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
        "points_method": DEFAULTS["POINTS_METHOD"],
    }
    payload.update(overrides)
    return payload


def create_abuse_report_payload(**overrides) -> dict:
    payload = {
        "reporter_role": DEFAULTS["REPORTER_ROLE"],
        "allegation": DEFAULTS["ALLEGATION"],
    }
    payload.update(overrides)
    return payload


def create_selection_procedure_payload(**overrides) -> dict:
    payload = {
        "games_name": DEFAULTS["GAMES_NAME"],
        "trials_start": DEFAULTS["TRIALS_START"],
        "trials_end": DEFAULTS["TRIALS_END"],
        "registration_deadline": DEFAULTS["REGISTRATION_DEADLINE"],
        "qualifying_score": DEFAULTS["QUALIFYING_SCORE"],
        "quota_slots": DEFAULTS["QUOTA_SLOTS"],
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(**overrides) -> dict:
    payload = {
        "grounds": DEFAULTS["APPEAL_GROUNDS"],
    }
    payload.update(overrides)
    return payload


def create_commercial_deal_payload(**overrides) -> dict:
    payload = {
        "sponsor_name": DEFAULTS["SPONSOR_NAME"],
        "gross_value_cents": DEFAULTS["GROSS_VALUE_CENTS"],
        "basis": DEFAULTS["DEAL_BASIS"],
        "exclusivity_start": DEFAULTS["EXCLUSIVITY_START"],
        "exclusivity_end": DEFAULTS["EXCLUSIVITY_END"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transition payloads
# ---------------------------------------------------------------------------

def transition_payload(to_state, **extra) -> dict:
    payload = {"to_state": to_state}
    payload.update(extra)
    return payload


def issue_findings_payload(governance_score, athlete_rep_score, financial_score) -> dict:
    return {
        "to_state": "FINDINGS_ISSUED",
        "governance_score": governance_score,
        "athlete_rep_score": athlete_rep_score,
        "financial_score": financial_score,
    }


def finalize_results_payload(results) -> dict:
    """results: list of {"athlete_id": ..., "score": ...} covering every
    still-REGISTERED entry exactly once."""
    return {"to_state": "RESULTS_FINALIZED", "results": list(results)}


def nomination_payload(expected_roster_version) -> dict:
    return {"expected_roster_version": expected_roster_version}


def slot_decisions_payload(decisions) -> dict:
    """decisions: list of {"athlete_id": ..., "decision": "ACCEPTED"|"DECLINED"}."""
    return {"to_state": "NOMINATED", "slot_decisions": list(decisions)}


def deal_transition_payload(to_state, expected_deal_version) -> dict:
    return {"to_state": to_state, "expected_deal_version": expected_deal_version}
