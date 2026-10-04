"""Payload factories — one per writable resource, input fields only.

Field names, required-vs-optional sets, and enum values follow PRD §3/§4
verbatim. Optional fields are always sent explicitly unless the caller passes
None, in which case the key is omitted from the payload (PRD §3.1 names the
server default for local_dues_fee_cents as 0).

Note on mediation party responses: PRD §3.5 states the party-response payload
carries a `response` of `ACCEPTED` or `DECLINED` (the same values recorded
into business_response / consumer_response). Factories emit exactly those.
"""

import itertools

from .constants import CLOCK_START_ISO

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ---------------------------------------------------------------------------
# Bureaus / consumers / businesses (PRD §3.1)
# ---------------------------------------------------------------------------
def create_bureau_payload(**overrides) -> dict:
    n = _seq()
    payload = {
        "name": f"Test Bureau {n}",
        "territory_state_codes": ["IA", "NE"],
        "local_dues_fee_cents": 0,
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)  # None means: omit the optional field
        else:
            payload[key] = value
    return payload


def create_consumer_payload(**overrides) -> dict:
    n = _seq()
    payload = {
        "full_name": f"Test Consumer {n}",
        "email": f"consumer-{n}@example.com",  # unique: emails must not repeat
        "home_state_code": "IA",
    }
    payload.update(overrides)
    return payload


def create_business_payload(**overrides) -> dict:
    n = _seq()
    payload = {
        "legal_name": f"Test Business {n} LLC",
        "home_state_code": "IA",
        "employee_count": 250,  # LARGE by default
        # Founded well before the logical-clock start so the business is old
        # enough for accreditation (>= 183 days, PRD §3.2) at CLOCK_START_ISO
        # and carries zero age deduction (>= 3 full years, PRD §3.6).
        "founded_on": "2018-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Accreditation applications & decisions (PRD §3.2)
# ---------------------------------------------------------------------------
def create_application_payload(**overrides) -> dict:
    n = _seq()
    payload = {
        "billing_plan": "ANNUAL_PREPAID",
        "license_number": f"LIC-{n}",
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)  # application_id omitted unless supplied
        else:
            payload[key] = value
    return payload


def decide_application_payload(**overrides) -> dict:
    payload = {
        "decision": "APPROVE",
        "advertising_practices_result": "PASS",
        "complaint_history_result": "PASS",
        "licensing_result": "PASS",
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)  # denial_reason omitted unless supplied
        else:
            payload[key] = value
    return payload


def deny_application_payload(denial_reason: str = "standards not met",
                             **overrides) -> dict:
    payload = {
        "decision": "DENY",
        "advertising_practices_result": "PASS",
        "complaint_history_result": "PASS",
        "licensing_result": "FAIL",
        "denial_reason": denial_reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dues invoice ledger entries (PRD §3.3)
# ---------------------------------------------------------------------------
def ledger_entry_payload(kind: str = "PAYMENT", amount_cents: int = 1,
                         **overrides) -> dict:
    payload = {"kind": kind, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Complaints (PRD §3.4)
# ---------------------------------------------------------------------------
def create_complaint_payload(consumer_id: str, business_id: str,
                             **overrides) -> dict:
    n = _seq()
    payload = {
        "consumer_id": consumer_id,
        "business_id": business_id,
        "category": "SERVICE",
        "description": f"Complaint body {n}",
    }
    payload.update(overrides)
    return payload


def complaint_response_payload(kind: str = "BUSINESS_RESPONSE",
                               body: str = None, **overrides) -> dict:
    n = _seq()
    payload = {"kind": kind, "body": body or f"response body {n}"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Mediation (PRD §3.5)
# ---------------------------------------------------------------------------
def party_response_payload(party: str = "BUSINESS",
                           response: str = "ACCEPTED",
                           **overrides) -> dict:
    payload = {"party": party, "response": response}
    payload.update(overrides)
    return payload


def schedule_mediation_payload(mediator_id: str = "med-1",
                               session_start_at: str = "2026-09-21T10:00:00Z",
                               session_end_at: str = "2026-09-21T11:00:00Z",
                               **overrides) -> dict:
    payload = {
        "mediator_id": mediator_id,
        "session_start_at": session_start_at,
        "session_end_at": session_end_at,
    }
    payload.update(overrides)
    return payload


def conclude_mediation_payload(outcome: str = "AGREEMENT",
                               **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Arbitration (PRD §3.5)
# ---------------------------------------------------------------------------
def schedule_hearing_payload(hearing_room_id: str = "room-A",
                             hearing_start_at: str = "2026-10-05T10:00:00Z",
                             hearing_end_at: str = "2026-10-05T11:00:00Z",
                             **overrides) -> dict:
    payload = {
        "hearing_room_id": hearing_room_id,
        "hearing_start_at": hearing_start_at,
        "hearing_end_at": hearing_end_at,
    }
    payload.update(overrides)
    return payload


def render_decision_payload(outcome: str = "ADVERSE_TO_BUSINESS",
                            **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rating snapshots & disputes (PRD §3.6 / §3.7)
# ---------------------------------------------------------------------------
def create_rating_snapshot_payload(variant: str = "PUBLISHED",
                                   **overrides) -> dict:
    payload = {"variant": variant}
    payload.update(overrides)
    return payload


def create_rating_dispute_payload(snapshot_id: str,
                                  expected_business_version: int,
                                  reason: str = None,
                                  **overrides) -> dict:
    n = _seq()
    payload = {
        "snapshot_id": snapshot_id,
        "reason": reason or f"dispute reason {n}",
        "expected_business_version": expected_business_version,
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)  # disputed_complaint_id omitted unless set
        else:
            payload[key] = value
    return payload


def appeal_decision_payload(decision: str = "UPHELD", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Advertising reviews (PRD §3.8)
# ---------------------------------------------------------------------------
def create_advertising_review_payload(**overrides) -> dict:
    n = _seq()
    payload = {"claim_description": f"advertising claim under review {n}"}
    payload.update(overrides)
    return payload


def conclude_advertising_review_payload(outcome: str = "CLEARED",
                                        **overrides) -> dict:
    payload = {"outcome": outcome}
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)  # regulator_name omitted unless supplied
        else:
            payload[key] = value
    return payload


def conclude_review_deceptive_payload(regulator_name: str = "FTC",
                                      **overrides) -> dict:
    payload = {
        "outcome": "SUBSTANTIATED_DECEPTIVE",
        "regulator_name": regulator_name,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Scam reports (PRD §3.8)
# ---------------------------------------------------------------------------
def create_scam_report_payload(consumer_id: str, business_id: str,
                               **overrides) -> dict:
    n = _seq()
    payload = {
        "consumer_id": consumer_id,
        "business_id": business_id,
        "description": f"scam report body {n}",
        # An incident date shortly before the clock start; incident_date is a
        # client-supplied fact, not a clock-derived stamp.
        "incident_date": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str = CLOCK_START_ISO) -> dict:
    return {"to_iso8601": to_iso8601}
