"""Payload factories — one per creatable resource, input fields only.

Server-managed fields (status, ids, computed fields, ``decided_by_*``,
timestamps stamped by the logical clock) are never placed in payloads.
Counters keep ``court_code`` and ``case_number`` unique within a test run;
optional fields are omitted (not sent as null) unless an override supplies
them, so server-side defaults stay observable.
"""

import itertools

from .constants import NOTICE_SERVED_AT_ISO

_court_seq = itertools.count(1)
_case_seq = itertools.count(1)
_judge_seq = itertools.count(1)
_interpreter_seq = itertools.count(1)
_program_seq = itertools.count(1)


def make_court_payload(**overrides) -> dict:
    n = next(_court_seq)
    payload = {
        "court_code": "CT-{0:03d}".format(n),
        "name": "Test Court {0}".format(n),
        "city": "Omaha",
        "annual_completion_goal": 100,
        "detained_daily_hearing_capacity": 2,
    }
    payload.update(overrides)
    return payload


def make_judge_payload(court_id, **overrides) -> dict:
    n = next(_judge_seq)
    payload = {
        "court_id": court_id,
        "full_name": "Judge Test {0}".format(n),
        "max_pending_cases": 5,
    }
    payload.update(overrides)
    return payload


def make_interpreter_payload(court_id, **overrides) -> dict:
    n = next(_interpreter_seq)
    payload = {
        "court_id": court_id,
        "full_name": "Interpreter Test {0}".format(n),
        "language_codes": ["spa"],
        "daily_hearing_cap": 4,
    }
    payload.update(overrides)
    return payload


def make_orientation_program_payload(court_id, **overrides) -> dict:
    n = next(_program_seq)
    payload = {
        "court_id": court_id,
        "program_name": "Orientation Program {0}".format(n),
        "coverage_pct": 50,
        "active": True,
    }
    payload.update(overrides)
    return payload


def make_set_coverage_payload(**overrides) -> dict:
    """Optional-body payload for the set-coverage operation (coverage_pct/active)."""
    return dict(overrides)


def make_case_payload(court_id, **overrides) -> dict:
    """Default case: NON_DETAINED English PRO_SE proceeding without an
    interpreter (interpreter_required False) — the least-constrained docket
    citizen.  Override ``custody_status`` / ``primary_language_code`` /
    ``representation_status`` / ``interpreter_required`` as needed."""
    n = next(_case_seq)
    payload = {
        "court_id": court_id,
        "case_number": "A{0:07d}".format(n),
        "respondent_full_name": "Respondent {0}".format(n),
        "custody_status": "NON_DETAINED",
        "primary_language_code": "eng",
        "representation_status": "PRO_SE",
        "interpreter_required": False,
    }
    payload.update(overrides)
    return payload


def make_assign_judge_payload(judge_id, **overrides) -> dict:
    payload = {"judge_id": judge_id}
    payload.update(overrides)
    return payload


def make_closure_payload(closure_reason="PENDING_APPLICATION", **overrides) -> dict:
    payload = {"closure_reason": closure_reason}
    payload.update(overrides)
    return payload


def make_hearing_payload(case_id, hearing_type, scheduled_start, expected_case_version,
                         is_remote=None, **overrides) -> dict:
    """``is_remote`` is omitted when None so the server default (false) applies;
    pass ``is_remote=True`` explicitly for DETAINED cases."""
    payload = {
        "case_id": case_id,
        "hearing_type": hearing_type,
        "scheduled_start": scheduled_start,
        "expected_case_version": expected_case_version,
    }
    if is_remote is not None:
        payload["is_remote"] = is_remote
    payload.update(overrides)
    return payload


def make_notice_payload(hearing_id, **overrides) -> dict:
    payload = {
        "hearing_id": hearing_id,
        "service_method": "MAIL",
        "served_at": NOTICE_SERVED_AT_ISO,
    }
    payload.update(overrides)
    return payload


def make_continuance_payload(case_id, hearing_id, reason_code="EVIDENCE_GATHERING",
                             **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "hearing_id": hearing_id,
        "reason_code": reason_code,
    }
    payload.update(overrides)
    return payload


def make_ruling_payload(decision, **overrides) -> dict:
    """Judge ruling body for continuance / venue-motion / reopen-motion decide."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def make_venue_motion_payload(case_id, destination_court_id, reason="respondent moved",
                              **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "destination_court_id": destination_court_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def make_reassignment_payload(case_id, expected_case_version, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def make_decision_payload(case_id, outcome="REMOVAL", expected_case_version=None,
                          **overrides) -> dict:
    payload = {"case_id": case_id, "outcome": outcome}
    if expected_case_version is not None:
        payload["expected_case_version"] = expected_case_version
    payload.update(overrides)
    return payload


def make_appeal_payload(decision_id, grounds=None, **overrides) -> dict:
    """``grounds`` is optional per the PRD; omitted unless supplied."""
    payload = {"decision_id": decision_id}
    if grounds is not None:
        payload["grounds"] = grounds
    payload.update(overrides)
    return payload


def make_appeal_ruling_payload(ruling, remand_instructions=None, **overrides) -> dict:
    """Board ruling body; ``remand_instructions`` is required iff REMANDED."""
    payload = {"ruling": ruling}
    if remand_instructions is not None:
        payload["remand_instructions"] = remand_instructions
    payload.update(overrides)
    return payload


def make_motion_to_reopen_payload(case_id, decision_id, basis="EXCEPTIONAL_CIRCUMSTANCES",
                                  **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "decision_id": decision_id,
        "basis": basis,
    }
    payload.update(overrides)
    return payload
