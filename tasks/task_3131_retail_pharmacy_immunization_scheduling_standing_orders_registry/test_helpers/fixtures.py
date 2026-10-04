"""Composite setup helpers for multi-step scenarios.

All fixtures build preconditions from scratch using only PRD-declared endpoints.
The harness restarts the server before every test, so each fixture starts
against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_store_payload,
    create_state_protocol_payload,
    create_vaccine_product_payload,
    create_patient_payload,
    create_lot_payload,
    create_appointment_payload,
    create_questionnaire_payload,
    create_clinic_event_payload,
)


# ---- Role header shortcuts (opaque roles use fixed test user ids) ----

def _mgr():
    return build_user_headers("user-mgr-1", "StoreManager")


def _co():
    return build_user_headers("user-co-1", "ComplianceOfficer")


def _tech(user_id="user-tech-1"):
    return build_user_headers(user_id, "PharmacyTechnician")


def _pharm(user_id="user-pharm-1"):
    return build_user_headers(user_id, "Pharmacist")


def _imm(user_id="user-imm-1"):
    return build_user_headers(user_id, "Immunizer")


def _obs(user_id="user-obs-1"):
    return build_user_headers(user_id, "ObservationMonitor")


# ---- Clock ----

def set_clock(to_iso8601: str, as_role: str = "StoreManager"):
    headers = _mgr() if as_role == "StoreManager" else _co()
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers)
    return get_success_data(resp)


# ---- Tier 1: single-entity creators ----

def create_store(store_number="S-1", state_code="CA", address_line="1 Main St"):
    resp = api_client.create_store(
        create_store_payload(store_number=store_number, state_code=state_code, address_line=address_line),
        _mgr(),
    )
    return get_success_data(resp)


def create_product(cvx_code="141", name="Influenza Quadrivalent", **overrides):
    payload = create_vaccine_product_payload(cvx_code=cvx_code, name=name, **overrides)
    resp = api_client.create_vaccine_product(payload, _co())
    return get_success_data(resp)


def create_protocol(state_code="CA", vaccine_product_id=None, **overrides):
    payload = create_state_protocol_payload(state_code=state_code, vaccine_product_id=vaccine_product_id, **overrides)
    resp = api_client.create_state_protocol(payload, _co())
    return get_success_data(resp)


def create_patient(full_name="Test Patient", date_of_birth="1980-01-01", **overrides):
    payload = create_patient_payload(full_name=full_name, date_of_birth=date_of_birth, **overrides)
    resp = api_client.create_patient(payload, _tech())
    return get_success_data(resp)


def create_lot(store_id, vaccine_product_id, lot_number="L1", **overrides):
    payload = create_lot_payload(vaccine_product_id=vaccine_product_id, lot_number=lot_number, **overrides)
    resp = api_client.create_lot(store_id, payload, _mgr())
    return get_success_data(resp)


def create_insurance_plan(plan_name="Plan", benefit_type="PHARMACY", copay_cents=1000,
                          covered_cvx_codes=None, **overrides):
    from .factories import create_insurance_plan_payload
    payload = create_insurance_plan_payload(
        plan_name=plan_name, benefit_type=benefit_type, copay_cents=copay_cents,
        covered_cvx_codes=covered_cvx_codes or ["141"], **overrides,
    )
    resp = api_client.create_insurance_plan(payload, _co())
    return get_success_data(resp)


# ---- Tier 2: composite store + product + protocol ----

def setup_store_with_product(store_number="S-1", state_code="CA", product_overrides=None, protocol_overrides=None):
    """Create store + FLU product + governing protocol. Returns (store, product, protocol)."""
    store = create_store(store_number=store_number, state_code=state_code)
    product = create_product(**(product_overrides or {}))
    protocol = create_protocol(
        state_code=state_code,
        vaccine_product_id=product["id"],
        **(protocol_overrides or {}),
    )
    return store, product, protocol


# ---- Tier 3: appointment lifecycle ----

def book_appointment(store_id, patient_id, product_id, slot_start="2026-09-02T10:00:00Z",
                     is_walk_in=None, tech_user_id="user-tech-1"):
    """Book an appointment; returns the appointment dict."""
    payload = create_appointment_payload(
        store_id=store_id, patient_id=patient_id, vaccine_product_id=product_id, slot_start=slot_start,
    )
    if is_walk_in is not None:
        payload["is_walk_in"] = is_walk_in
    resp = api_client.create_appointment(payload, _tech(tech_user_id))
    return get_success_data(resp)


def walk_appointment_to_screened(store, patient, product, slot_start="2026-09-01T10:00:00Z",
                                 is_walk_in=True, tech_user_id="user-tech-1"):
    """Book + check-in + questionnaire. Returns the appointment (SCREENED)."""
    appt = book_appointment(store["id"], patient["id"], product["id"], slot_start=slot_start,
                            is_walk_in=is_walk_in, tech_user_id=tech_user_id)
    api_client.check_in_appointment(appt["id"], _tech(tech_user_id))
    api_client.submit_questionnaire(appt["id"], create_questionnaire_payload(), _tech())
    return appt


def walk_appointment_to_consented(store, patient, product, slot_start="2026-09-01T10:00:00Z",
                                  is_walk_in=True, tech_user_id="user-tech-1",
                                  pharm_user_id="user-pharm-1", outcome="CLEAR"):
    """Book + check-in + questionnaire + review-consent. Returns the appointment (CONSENTED)."""
    appt = book_appointment(store["id"], patient["id"], product["id"], slot_start=slot_start,
                            is_walk_in=is_walk_in, tech_user_id=tech_user_id)
    api_client.check_in_appointment(appt["id"], _tech(tech_user_id))
    api_client.submit_questionnaire(appt["id"], create_questionnaire_payload(), _tech())
    # Re-read to get the current version (post-questionnaire)
    current = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
    resp = api_client.review_consent(
        appt["id"],
        {"expected_appointment_version": current["version"], "outcome": outcome},
        _pharm(pharm_user_id),
    )
    return get_success_data(resp)


def administer_appointment(appointment_id, lot, immunizer_user_id="user-imm-1", clinic_event_id=None):
    """Administer a dose against a lot, using the lot's current version."""
    current_lot = get_success_data(api_client.get_lot(lot["id"], _mgr()))
    payload = {
        "lot_id": lot["id"],
        "expected_lot_version": current_lot["version"],
    }
    if clinic_event_id:
        payload["clinic_event_id"] = clinic_event_id
    resp = api_client.administer(appointment_id, payload, _imm(immunizer_user_id))
    return get_success_data(resp)


def full_administration(store, patient, product, lot, slot_start="2026-09-01T10:00:00Z",
                        tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                        imm_user_id="user-imm-1", clinic_event_id=None):
    """Book → check-in → questionnaire → review-consent → administer. Returns the ImmunizationRecord."""
    appt = walk_appointment_to_consented(store, patient, product, slot_start=slot_start,
                                         tech_user_id=tech_user_id, pharm_user_id=pharm_user_id)
    return administer_appointment(appt["id"], lot, immunizer_user_id=imm_user_id,
                                  clinic_event_id=clinic_event_id)


# ---- Tier 4: clinic event helpers ----

def create_clinic_event_for_lot(store_id, lot_id, event_start="2026-09-01T10:00:00Z",
                                event_end="2026-09-01T12:00:00Z", doses_reserved=4,
                                employer_name="Acme Corp"):
    payload = create_clinic_event_payload(
        store_id=store_id, employer_name=employer_name, event_start=event_start,
        event_end=event_end, mobile_lot_id=lot_id, doses_reserved=doses_reserved,
    )
    resp = api_client.create_clinic_event(payload, _mgr())
    return get_success_data(resp)


# ---- Tier 5: registry helpers ----

def get_submission_for_record(record_id):
    resp = api_client.list_record_registry_submissions(record_id, _co())
    subs = get_success_data(resp)
    assert isinstance(subs, list) and len(subs) == 1, "expected exactly one submission"
    return subs[0]


def get_observation_session_for_record(record_id):
    resp = api_client.list_record_observation_sessions(record_id, _obs())
    sessions = get_success_data(resp)
    assert isinstance(sessions, list) and len(sessions) == 1, "expected exactly one session"
    return sessions[0]
