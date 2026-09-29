"""Payload factories — one per write endpoint, client-supplied fields only.

Every factory takes ``**overrides`` so a test can control exactly the field
under examination.  Derived fields are never included: PRD §2.4 states that if
a client includes a server-owned field "the server ignores the supplied value".
"""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


def _merge(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    # An explicit None means "omit this key" so tests can probe missing fields.
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ----------------------------------------------------------------- clock
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# --------------------------------------------------------------- program
def create_program_payload(**overrides) -> dict:
    return _merge({
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }, overrides)


# --------------------------------------------------------------- athlete
def create_athlete_payload(**overrides) -> dict:
    return _merge({
        "legal_name": "Maya Foster",
        "birth_date": "2004-03-09",
        "sport": "ATHLETICS",
        "down_syndrome_flag": False,
    }, overrides)


def withdraw_athlete_payload(**overrides) -> dict:
    return _merge({"withdrawal_reason_code": "MOVED_AWAY"}, overrides)


# ---------------------------------------------------------- medical form
def create_medical_form_payload(**overrides) -> dict:
    return _merge({
        "exam_date": TEST_DEFAULTS["EXAM_DATE"],
        "physician_name": TEST_DEFAULTS["PHYSICIAN_NAME"],
        "physician_license_id": TEST_DEFAULTS["PHYSICIAN_LICENSE_ID"],
        "attestation_cardiac_clearance": True,
        "attestation_seizure_history": False,
        "attestation_atlantoaxial_screen": False,
        "restrictions": ["NONE"],
    }, overrides)


def review_medical_form_payload(**overrides) -> dict:
    return _merge({"decision": "APPROVE"}, overrides)


def resubmit_medical_form_payload(**overrides) -> dict:
    return create_medical_form_payload(**overrides)


# ------------------------------------------------------------- volunteer
def create_volunteer_payload(**overrides) -> dict:
    return _merge({
        "full_name": "Dana Ruiz",
        "email": "dana@rb.example",
        "date_of_birth": "1988-04-12",
        "volunteer_class": "COACH",
    }, overrides)


# ------------------------------------------------------------ credential
def create_credential_payload(**overrides) -> dict:
    return _merge({"role_class": "COACH"}, overrides)


def record_screening_payload(**overrides) -> dict:
    return _merge({
        "completed_on": TEST_DEFAULTS["SCREENING_COMPLETED_ON"],
        "result": "CLEAR",
        "vendor_reference": TEST_DEFAULTS["VENDOR_REFERENCE"],
    }, overrides)


def record_training_payload(**overrides) -> dict:
    return _merge({
        "completed_on": TEST_DEFAULTS["TRAINING_COMPLETED_ON"],
        "curriculum_code": TEST_DEFAULTS["CURRICULUM_CODE"],
    }, overrides)


def certify_credential_payload(**overrides) -> dict:
    return _merge({}, overrides)


# ---------------------------------------------------------------- season
def create_season_payload(**overrides) -> dict:
    return _merge({
        "sport": "ATHLETICS",
        "season_name": TEST_DEFAULTS["SEASON_NAME"],
        "practice_minimum_sessions": 2,
        "practice_minimum_minutes": 90,
        "registration_deadline": TEST_DEFAULTS["REGISTRATION_DEADLINE"],
        "divisioning_date": TEST_DEFAULTS["DIVISIONING_DATE"],
        "competition_date": TEST_DEFAULTS["COMPETITION_DATE"],
        "games_level": "LOCAL",
        "entry_slot_budget": TEST_DEFAULTS["ENTRY_SLOT_BUDGET"],
        "advancement_slots_per_division":
            TEST_DEFAULTS["ADVANCEMENT_SLOTS_PER_DIVISION"],
    }, overrides)


# ------------------------------------------------------ practice session
def create_practice_session_payload(season_id: str, coach_credential_id: str,
                                    **overrides) -> dict:
    return _merge({
        "season_id": season_id,
        "coach_credential_id": coach_credential_id,
        "scheduled_start": TEST_DEFAULTS["SESSION_START"],
        "duration_minutes": TEST_DEFAULTS["SESSION_DURATION_MINUTES"],
        "capacity_slots": TEST_DEFAULTS["SESSION_CAPACITY_SLOTS"],
    }, overrides)


def create_attendance_payload(athlete_id: str, expected_session_version: int,
                              **overrides) -> dict:
    return _merge({
        "athlete_id": athlete_id,
        "minutes_present": 60,
        "expected_session_version": expected_session_version,
    }, overrides)


def cancel_session_payload(**overrides) -> dict:
    return _merge({"void_reason_code": "WEATHER"}, overrides)


# ----------------------------------------------------------- unified team
def create_unified_team_payload(**overrides) -> dict:
    return _merge({"team_name": "Riverbend Unified"}, overrides)


def add_team_member_payload(member_type: str, member_id: str,
                            expected_team_version: int, **overrides) -> dict:
    return _merge({
        "member_type": member_type,
        "member_id": member_id,
        "expected_team_version": expected_team_version,
    }, overrides)


# ------------------------------------------------------ competition entry
def create_entry_payload(season_id: str, participant_id: str, **overrides) -> dict:
    return _merge({
        "season_id": season_id,
        "participant_type": "ATHLETE",
        "participant_id": participant_id,
        "event_code": TEST_DEFAULTS["EVENT_CODE"],
        "skill_score": 20.0,
    }, overrides)


def post_result_payload(result_value: float, **overrides) -> dict:
    return _merge({"result_value": result_value}, overrides)


# ----------------------------------------------------- health screenings
def create_health_screening_payload(athlete_id: str, **overrides) -> dict:
    return _merge({
        "athlete_id": athlete_id,
        "event_name": "Riverbend Fall Games",
        "discipline": "FUNFITNESS",
        "screened_on": "2026-08-01",
        "finding_severity": "ROUTINE",
    }, overrides)


def referral_followup_payload(outcome: str, **overrides) -> dict:
    return _merge({
        "outcome": outcome,
        "note": "Family contacted; clinic appointment booked.",
    }, overrides)


# ----------------------------------------------------------- contribution
def create_contribution_payload(**overrides) -> dict:
    return _merge({
        "donor_name": "Cedar Valley Rotary",
        "contribution_type": "CASH_PLEDGE",
        "designation": "GENERAL",
        "stated_value_cents": 250_000,
    }, overrides)


def fulfill_contribution_payload(**overrides) -> dict:
    return _merge({"received_on": "2026-08-01"}, overrides)


def void_contribution_payload(**overrides) -> dict:
    return _merge({"void_reason_code": "DONOR_RESCINDED"}, overrides)


# ------------------------------------------------------------------ sweep
def compliance_sweep_payload(**overrides) -> dict:
    return _merge({}, overrides)
