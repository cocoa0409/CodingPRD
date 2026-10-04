"""Payload factories — one per creatable resource, input fields only.

Computed and system-managed fields are never emitted. Defaults are chosen to
be on the happy path of the PRD's eligibility screens (income exactly at the
household-of-four cap, gpa_scaled 390, test_score 1450) so a bare factory
payload passes the academic and income screens; tests that probe a screen
override the relevant fields.
"""
import itertools

from .constants import (
    CYCLE_A_APP_CLOSES_AT,
    CYCLE_A_APP_OPENS_AT,
    CYCLE_A_RANKING_CLOSES_AT,
    CYCLE_A_RANKING_OPENS_AT,
)

_email_counter = itertools.count(1)
_name_counter = itertools.count(1)


def _n() -> int:
    return next(_name_counter)


# --- MatchCycle -------------------------------------------------------------

def create_cycle_payload(**overrides) -> dict:
    """Defaults are the canonical Cycle A windows: the application window
    opens exactly at the logical-clock default (bounds inclusive) and the
    ranking window follows in October."""
    defaults = {
        "name": f"Cycle {_n()}",
        "app_opens_at": CYCLE_A_APP_OPENS_AT,
        "app_closes_at": CYCLE_A_APP_CLOSES_AT,
        "ranking_opens_at": CYCLE_A_RANKING_OPENS_AT,
        "ranking_closes_at": CYCLE_A_RANKING_CLOSES_AT,
    }
    defaults.update(overrides)
    return defaults


# --- PartnerCollege ---------------------------------------------------------

def create_college_payload(**overrides) -> dict:
    defaults = {
        "name": f"College {_n()}",
        "aid_policy": "NO_LOAN",
        "min_academic_index": 0,
        "match_slots": 1,
        "coa_cents": 8_000_000,
    }
    defaults.update(overrides)
    return defaults


# --- People -----------------------------------------------------------------

def create_counselor_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Counselor {_n()}",
        "school_name": "East High",
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_community_partner_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "org_name": f"Partner Org {i}",
        "state_code": "TX",
        "contact_email": f"partner{i}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    """A fresh unique email per call (student emails are globally unique)."""
    defaults = {
        "email": f"student{next(_email_counter)}@example.com",
        "full_name": f"Student {_n()}",
        "state_code": "TX",
        "source": "SELF",
    }
    defaults.update(overrides)
    return defaults


# --- Referral (requires student_id + cycle_id) ------------------------------

def create_referral_payload(student_id: str, cycle_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "cycle_id": cycle_id,
        "note": "",
    }
    defaults.update(overrides)
    return defaults


# --- PrepProgram (requires student_id; half-open [starts_on, ends_on)) ------

def create_prep_program_payload(student_id: str, **overrides) -> dict:
    """Default interval is a completed-looking summer before the cycle opens;
    prep records carry no logical-clock window gate, only the per-student
    half-open overlap check."""
    defaults = {
        "student_id": student_id,
        "program_type": "SUMMER",
        "cohort_label": "summer-2026",
        "starts_on": "2026-06-01T00:00:00Z",
        "ends_on": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- Application (student_id comes from X-User-ID, never the payload) -------

def create_application_payload(cycle_id: str, **overrides) -> dict:
    """Happy-path defaults: income exactly at the size-4 cap (eligible),
    academics comfortably above both screens."""
    defaults = {
        "cycle_id": cycle_id,
        "household_income_cents": 6_500_000,
        "household_size": 4,
        "self_reported_assets_cents": 0,
        "gpa_scaled": 390,
        "test_score": 1450,
        "essay_text": "",
    }
    defaults.update(overrides)
    return defaults


def submit_rankings_payload(entries, expected_application_version: int,
                            **overrides) -> dict:
    """entries: list of {"college_id": ..., "rank_position": ...}."""
    defaults = {
        "entries": entries,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def ranking_entry(college_id: str, rank_position: int) -> dict:
    return {"college_id": college_id, "rank_position": rank_position}


def review_payload(decision: str = "FINALIST") -> dict:
    return {"decision": decision}


def regular_decision_payload(decision: str = "ADMIT") -> dict:
    return {"decision": decision}


def release_match_payload(reason: str = "extenuating circumstances") -> dict:
    return {"reason": reason}


# --- IncomeVerification -----------------------------------------------------

def create_income_verification_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "verified_income_cents": 6_200_000,
        "verified_assets_cents": 500_000,
        "verified_household_size": 4,
    }
    defaults.update(overrides)
    return defaults


def decide_verification_payload(decision: str = "VERIFY") -> dict:
    return {"decision": decision}


# --- AidPackage -------------------------------------------------------------

def revise_aid_package_payload(expected_aid_package_version: int,
                               coa_cents=None) -> dict:
    payload = {"expected_aid_package_version": expected_aid_package_version}
    if coa_cents is not None:
        payload["coa_cents"] = coa_cents
    return payload


# --- PrepProgram close ------------------------------------------------------

def close_prep_program_payload(outcome: str = "COMPLETED") -> dict:
    return {"outcome": outcome}


# --- OutcomeRecord checkpoint -------------------------------------------------

def checkpoint_payload(to_status: str, credits_completed=None) -> dict:
    payload = {"to_status": to_status}
    if credits_completed is not None:
        payload["credits_completed"] = credits_completed
    return payload


# --- Logical clock ------------------------------------------------------------

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
