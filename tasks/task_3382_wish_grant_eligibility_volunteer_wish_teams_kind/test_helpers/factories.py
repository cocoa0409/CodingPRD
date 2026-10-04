"""Payload factories — one per creatable entity / action, input fields only.

Every factory builds a fresh dict per call (no shared mutable defaults) and
accepts **overrides applied last, so tests control exactly the fields the
PRD lets them control.
"""
from .constants import (
    CANONICAL_CHILD_DOB,
    CANONICAL_CHILD_NAME,
    CANONICAL_CHILD_ZIP,
    DEFAULT_CHAPTER_NAME,
    DEFAULT_EVENT_END_DATE,
    DEFAULT_EVENT_START_DATE,
    DEFAULT_FISCAL_YEAR_BUDGET_CENTS,
    DEFAULT_CLOCK_ISO,
    DEFAULT_OFFER_VALID_FROM,
    DEFAULT_OFFER_VALID_UNTIL,
    DEFAULT_TARGET_AVG_COST_PER_WISH_CENTS,
    DEFAULT_VISIT_END,
    DEFAULT_VISIT_START,
    DEFAULT_ZIP_PREFIX,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def create_clock_payload(to_iso8601=DEFAULT_CLOCK_ISO, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Chapter
# ---------------------------------------------------------------------------

def create_chapter_payload(**overrides):
    payload = {
        "name": DEFAULT_CHAPTER_NAME,
        "territory_zip_prefixes": [DEFAULT_ZIP_PREFIX],
        "fiscal_year_budget_cents": DEFAULT_FISCAL_YEAR_BUDGET_CENTS,
        "target_avg_cost_per_wish_cents": DEFAULT_TARGET_AVG_COST_PER_WISH_CENTS,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Volunteer
# ---------------------------------------------------------------------------

def create_volunteer_payload(chapter_id, **overrides):
    payload = {
        "chapter_id": chapter_id,
        "full_name": "Nina Park",
        "email": "nina@example.org",
    }
    payload.update(overrides)
    return payload


def create_volunteer_transition_payload(target_state, **overrides):
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Referral intake / certification / determination
# ---------------------------------------------------------------------------

def create_referral_payload(**overrides):
    payload = {
        "child_full_name": CANONICAL_CHILD_NAME,
        "child_date_of_birth": CANONICAL_CHILD_DOB,
        "child_zip_code": CANONICAL_CHILD_ZIP,
        "parent_email": "monroe@example.org",
        "diagnosis_summary": "leukemia",
        "source_type": "FAMILY",
        "prognosis_months": 12,
    }
    payload.update(overrides)
    return payload


def create_certify_payload(qualifying_condition="ONCOLOGY", **overrides):
    payload = {"qualifying_condition": qualifying_condition}
    payload.update(overrides)
    return payload


def create_determine_payload(decision="APPROVED", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Child maintenance
# ---------------------------------------------------------------------------

def create_treatment_windows_payload(treatment_windows=None, **overrides):
    """PATCH /children/{id}: wholesale replacement of the treatment windows."""
    payload = {"treatment_windows": list(treatment_windows) if treatment_windows else []}
    payload.update(overrides)
    return payload


def create_treatment_window(start_date, end_date):
    """One closed-interval treatment window entry."""
    return {"start_date": start_date, "end_date": end_date}


# ---------------------------------------------------------------------------
# Wish teams and visits
# ---------------------------------------------------------------------------

def create_wish_team_payload(wish_id, lead_volunteer_id, second_volunteer_id,
                             expected_wish_version, **overrides):
    payload = {
        "wish_id": wish_id,
        "lead_volunteer_id": lead_volunteer_id,
        "second_volunteer_id": second_volunteer_id,
        "expected_wish_version": expected_wish_version,
    }
    payload.update(overrides)
    return payload


def create_wish_visit_payload(wish_team_id, **overrides):
    payload = {
        "wish_team_id": wish_team_id,
        "scheduled_start": DEFAULT_VISIT_START,
        "scheduled_end": DEFAULT_VISIT_END,
        "visit_method": "PLAY_BASED",
    }
    payload.update(overrides)
    return payload


def create_conclude_payload(outcome="COMPLETED", **overrides):
    """Conclude a visit. COMPLETED additionally requires captured_true_wish
    and captured_wish_type; pass them via overrides or the helper below."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_conclude_completed_payload(captured_true_wish="a treehouse",
                                      captured_wish_type="RECEIVE_ITEM",
                                      **overrides):
    payload = {
        "outcome": "COMPLETED",
        "captured_true_wish": captured_true_wish,
        "captured_wish_type": captured_wish_type,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Donation offers
# ---------------------------------------------------------------------------

def create_donation_offer_payload(**overrides):
    payload = {
        "partner_name": "ToyWorld",
        "category": "RETAILER",
        "valuation_method": "RETAIL_BASIS",
        "description": "toy truck",
        "quantity_total": 10,
        "unit_retail_cents": 12000,
        "valid_from": DEFAULT_OFFER_VALID_FROM,
        "valid_until": DEFAULT_OFFER_VALID_UNTIL,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Fulfillment plans and line items
# ---------------------------------------------------------------------------

def create_fulfillment_plan_payload(wish_id, expected_wish_version,
                                    cash_cost_cents=100000, **overrides):
    payload = {
        "wish_id": wish_id,
        "cash_cost_cents": cash_cost_cents,
        "expected_wish_version": expected_wish_version,
    }
    payload.update(overrides)
    return payload


def create_line_item_payload(donation_offer_id, quantity=1, **overrides):
    payload = {
        "donation_offer_id": donation_offer_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_abort_payload(reason=None, **overrides):
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Medical clearances
# ---------------------------------------------------------------------------

def create_medical_clearance_payload(wish_id, **overrides):
    payload = {"wish_id": wish_id}
    payload.update(overrides)
    return payload


def create_decide_payload(decision, **overrides):
    """Clearance decision. CLEARED requires valid_until; CONDITIONAL requires
    valid_until and non-empty accommodations; REVOKED from CLEARED/CONDITIONAL."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Wish events
# ---------------------------------------------------------------------------

def create_wish_event_payload(wish_id, event_start_date=DEFAULT_EVENT_START_DATE,
                              event_end_date=DEFAULT_EVENT_END_DATE, **overrides):
    payload = {
        "wish_id": wish_id,
        "event_start_date": event_start_date,
        "event_end_date": event_end_date,
    }
    payload.update(overrides)
    return payload
