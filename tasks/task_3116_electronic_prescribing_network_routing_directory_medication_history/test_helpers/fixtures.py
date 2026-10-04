"""Composite setup helpers for multi-step prerequisites.

Every helper builds its preconditions from scratch with PRD-declared endpoints only,
because the harness restarts the API server before every individual test and each test
therefore starts against an empty database. Setup calls go through `get_success_data()`
so a broken setup raises a clear "Setup step failed" error rather than a confusing
assertion failure inside the test body.

Identity threading: every ownership-gated call made on behalf of an entity-backed role
(`ParticipantAdmin`, `Prescriber`, `Pharmacy`) builds its headers from the real entity id
via `make_<role>_headers(entity_id)`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_DEFAULT
from .factories import (
    create_participant_payload,
    create_clinic_payload,
    create_second_clinic_payload,
    create_pharmacy_payload,
    create_payer_payload,
    create_endpoint_payload,
    create_patient_payload,
    create_consent_payload,
    create_prescription_payload,
    create_history_record_payload,
    create_history_batch_payload,
    create_benefit_check_payload,
    create_transaction_fee_payload,
)
from .test_users import (
    TEST_USERS,
    make_participant_admin_headers,
    make_prescriber_headers,
    make_pharmacy_headers,
)

OPERATOR = TEST_USERS["network_operator_headers"]
PATIENT_SERVICE = TEST_USERS["patient_service_headers"]
HUB_OPERATOR = TEST_USERS["hub_operator_headers"]


# ═══════════════ Tier 0: logical clock ═══════════════

def set_clock(current_utc: str = CLOCK_STARTUP_DEFAULT) -> dict:
    """Pin the logical clock (PRD §2.10). Defaults to the startup instant."""
    return get_success_data(api_client.set_current_utc(current_utc, OPERATOR))


def advance_logical_clock(minutes: int) -> dict:
    """Advance the logical clock by a whole number of minutes (PRD §2.10)."""
    return get_success_data(api_client.advance_clock(minutes, OPERATOR))


# ═══════════════ Tier 1: participants and certification ═══════════════

def register_participant(name: str, participant_type: str, npi: str, **overrides) -> dict:
    payload = create_participant_payload(
        name=name, participant_type=participant_type, npi=npi, **overrides
    )
    return get_success_data(api_client.create_participant(payload, OPERATOR))


def create_clinic(**overrides) -> dict:
    return get_success_data(
        api_client.create_participant(create_clinic_payload(**overrides), OPERATOR)
    )


def create_second_clinic(**overrides) -> dict:
    return get_success_data(
        api_client.create_participant(create_second_clinic_payload(**overrides), OPERATOR)
    )


def create_pharmacy(**overrides) -> dict:
    return get_success_data(
        api_client.create_participant(create_pharmacy_payload(**overrides), OPERATOR)
    )


def create_payer(**overrides) -> dict:
    return get_success_data(
        api_client.create_participant(create_payer_payload(**overrides), OPERATOR)
    )


def add_endpoint(participant_id: str, **overrides) -> dict:
    """Register a directory endpoint owned by `participant_id` (PRD §3.1)."""
    payload = create_endpoint_payload(**overrides)
    return get_success_data(
        api_client.create_endpoint(
            participant_id, payload, make_participant_admin_headers(participant_id)
        )
    )


def record_test(participant_id: str, test_code: str, outcome: str = "PASS") -> dict:
    return get_success_data(
        api_client.record_certification_test(
            participant_id,
            {"test_code": test_code, "outcome": outcome},
            make_participant_admin_headers(participant_id),
        )
    )


def start_certification_window(participant_id: str) -> dict:
    return get_success_data(
        api_client.start_certification(
            participant_id, make_participant_admin_headers(participant_id)
        )
    )


def certify_participant(participant_id: str,
                        test_codes=("CONNECTIVITY", "SCRIPT_NEW_RX")) -> dict:
    """Open the certification window, record `test_codes` as PASS, then promote.

    The promotion carries the participant's freshly observed version as
    `expected_participant_version` (PRD §3.2), because recording tests and recomputing
    `directory_listed` both advance the participant's version.
    """
    start_certification_window(participant_id)
    for code in test_codes:
        record_test(participant_id, code, "PASS")
    fresh = reload_participant(participant_id)
    return get_success_data(
        api_client.certify_participant(
            participant_id, fresh["version"],
            make_participant_admin_headers(participant_id),
        )
    )


def reload_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, OPERATOR))


def reload_endpoint(endpoint_id: str) -> dict:
    return get_success_data(api_client.get_endpoint(endpoint_id, OPERATOR))


def reload_prescription(prescription_id: str) -> dict:
    return get_success_data(api_client.get_prescription(prescription_id, OPERATOR))


def reload_signing_session(session_id: str) -> dict:
    return get_success_data(api_client.get_signing_session(session_id, OPERATOR))


def setup_certified_clinic(**overrides) -> dict:
    """A CERTIFIED prescriber clinic holding one in-window NEW_RX sender endpoint."""
    clinic = create_clinic(**overrides)
    add_endpoint(
        clinic["id"],
        service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    return certify_participant(clinic["id"])


def setup_certified_pharmacy(endpoint_specs=None, test_codes=("CONNECTIVITY", "SCRIPT_NEW_RX"),
                             **overrides):
    """A CERTIFIED pharmacy with the given endpoint specifications (default: one in-window
    NEW_RX endpoint). Returns (pharmacy, [endpoints]).

    Pass `test_codes` including MED_HISTORY to exercise the certification prerequisite pair.
    """
    if endpoint_specs is None:
        endpoint_specs = [{}]
    pharmacy = create_pharmacy(**overrides)
    endpoints = [add_endpoint(pharmacy["id"], **spec) for spec in endpoint_specs]
    pharmacy = certify_participant(pharmacy["id"], test_codes=test_codes)
    endpoints = [reload_endpoint(ep["id"]) for ep in endpoints]
    return pharmacy, endpoints


# ═══════════════ Tier 1: patients and consents ═══════════════

def create_patient(**overrides) -> dict:
    return get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), PATIENT_SERVICE)
    )


def grant_consent(patient_id: str, scope: str = "MEDICATION_HISTORY",
                  duration_days: int = 365) -> dict:
    return get_success_data(
        api_client.grant_consent(
            patient_id, create_consent_payload(scope=scope, duration_days=duration_days),
            PATIENT_SERVICE,
        )
    )


def revoke_consents(patient_id: str) -> dict:
    return get_success_data(api_client.revoke_consents(patient_id, PATIENT_SERVICE))


def reload_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, OPERATOR))


# ═══════════════ Tier 1: prescriptions and signing ═══════════════

def create_prescription(clinic_id: str, pharmacy_id: str, patient_id: str, **overrides) -> dict:
    payload = create_prescription_payload(clinic_id, pharmacy_id, patient_id, **overrides)
    return get_success_data(
        api_client.create_prescription(payload, make_prescriber_headers(clinic_id))
    )


def open_signing_session(prescription_id: str, clinic_id: str) -> dict:
    return get_success_data(
        api_client.create_signing_session(prescription_id, make_prescriber_headers(clinic_id))
    )


def pass_two_factor(session_id: str, clinic_id: str) -> dict:
    """Identity-proof PASSED, request the challenge, then verify the issued code."""
    prescriber = make_prescriber_headers(clinic_id)
    get_success_data(api_client.identity_proof(session_id, "PASSED", prescriber))
    issued = get_success_data(api_client.request_otp(session_id, prescriber))
    get_success_data(api_client.verify_otp(session_id, issued["otp_challenge_code"], prescriber))
    return get_success_data(api_client.get_signing_session(session_id, OPERATOR))


def create_ready_session(prescription_id: str, clinic_id: str) -> dict:
    """Open a signing session and drive it through both proofs. Returns the session."""
    session = open_signing_session(prescription_id, clinic_id)
    return pass_two_factor(session["id"], clinic_id)


def sign_prescription(prescription_id: str, session_id: str, clinic_id: str) -> dict:
    return get_success_data(
        api_client.sign_prescription(
            prescription_id, session_id, make_prescriber_headers(clinic_id)
        )
    )


def route_prescription(prescription_id: str, clinic_id: str) -> dict:
    """Route a signed order, asserting the freshly read version (PRD §2.8)."""
    fresh = reload_prescription(prescription_id)
    return get_success_data(
        api_client.route_prescription(
            prescription_id, fresh["version"], make_prescriber_headers(clinic_id)
        )
    )


def current_attempts(prescription_id: str) -> list:
    return get_success_data(api_client.list_attempts(prescription_id, OPERATOR))


def latest_attempt(prescription_id: str) -> dict:
    attempts = current_attempts(prescription_id)
    attempts = sorted(attempts, key=lambda a: a["attempt_no"])
    return attempts[-1]


def report_acknowledged(attempt_id: str) -> dict:
    return get_success_data(api_client.report_acknowledged(attempt_id, OPERATOR))


def report_undeliverable(attempt_id: str, failure_code: str = "CF_0000") -> dict:
    return get_success_data(
        api_client.report_undeliverable(attempt_id, failure_code, OPERATOR)
    )


def report_rejected(attempt_id: str, failure_code: str = "POST_DELIVERY",
                    error_code_returned: str = None) -> dict:
    return get_success_data(
        api_client.report_rejected(attempt_id, failure_code, OPERATOR, error_code_returned)
    )


def create_fallback_attempt(prescription_id: str, clinic_id: str, channel: str = "FAX") -> dict:
    return get_success_data(
        api_client.create_fallback_attempt(
            prescription_id, channel, make_prescriber_headers(clinic_id)
        )
    )


def report_fallback(attempt_id: str, outcome: str = "ACKNOWLEDGED", failure_code: str = None) -> dict:
    return get_success_data(
        api_client.report_fallback(attempt_id, outcome, OPERATOR, failure_code)
    )


def route_and_report(prescription_id: str, clinic_id: str, outcome: str,
                     failure_code: str = None, error_code_returned: str = None) -> dict:
    """Route the order (creating a fresh in-flight attempt), then report that attempt's
    terminal outcome. Returns the reported attempt."""
    route_prescription(prescription_id, clinic_id)
    attempt = latest_attempt(prescription_id)
    if outcome == "ACKNOWLEDGED":
        report_acknowledged(attempt["id"])
    elif outcome == "UNDELIVERABLE":
        report_undeliverable(attempt["id"], failure_code or "CF_0000")
    elif outcome == "REJECTED":
        report_rejected(
            attempt["id"], failure_code or "POST_DELIVERY", error_code_returned
        )
    else:
        raise ValueError(f"unsupported report outcome {outcome!r}")
    return reload_attempt(attempt["id"])


def build_attempt_history(prescription_id: str, clinic_id: str, outcomes) -> list:
    """Drive a sequence of route-and-report cycles on one order and return the attempts.

    `outcomes` is a sequence of ("ACKNOWLEDGED" | "UNDELIVERABLE" | "REJECTED") values,
    optionally paired with a failure_code as a (outcome, failure_code) tuple.
    """
    attempts = []
    for entry in outcomes:
        if isinstance(entry, tuple):
            outcome, failure_code = entry
        else:
            outcome, failure_code = entry, None
        attempts.append(
            route_and_report(prescription_id, clinic_id, outcome, failure_code)
        )
    return attempts


# ═══════════════ Tier 1: medication history ═══════════════

def add_history_record(patient_id: str, source_participant_id: str, **overrides) -> dict:
    """Submit a medication history entry. Pharmacy-sourced records use the Pharmacy role,
    payer claims the HubOperator role."""
    payload = create_history_record_payload(source_participant_id, **overrides)
    if payload["source_type"] == "PHARMACY_FILL":
        headers = make_pharmacy_headers(source_participant_id)
    else:
        headers = HUB_OPERATOR
    return get_success_data(api_client.create_history_record(patient_id, payload, headers))


def open_history_batch(patient_id: str, clinic_id: str,
                       trigger_reason: str = "PRESCRIBER_QUERY") -> dict:
    return get_success_data(
        api_client.create_history_batch(
            create_history_batch_payload(patient_id, trigger_reason=trigger_reason),
            make_prescriber_headers(clinic_id),
        )
    )


def aggregate_batch(batch_id: str) -> dict:
    return get_success_data(api_client.aggregate_history_batch(batch_id, HUB_OPERATOR))


def reload_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_history_batch(batch_id, OPERATOR))


def reload_history_record(record_id: str) -> dict:
    return get_success_data(api_client.get_history_record(record_id, OPERATOR))


# ═══════════════ Tier 1: transaction fees ═══════════════

def post_fee_entry(participant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.post_transaction_fee(
            create_transaction_fee_payload(participant_id, **overrides), OPERATOR
        )
    )


def reload_fee_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_transaction_fee(entry_id, OPERATOR))


def reverse_fee_entry(entry_id: str, participant_id: str, expect_success: bool = True):
    """Reverse a posted entry. Pass `expect_success=False` when the caller is asserting the
    refusal itself, so a legitimate 4xx is handed back instead of aborting the setup."""
    fresh = reload_participant(participant_id)
    response = api_client.reverse_transaction_fee(entry_id, fresh["version"], OPERATOR)
    if not expect_success:
        return response
    return get_success_data(response)


# ═══════════════ Tier 1: benefit checks ═══════════════

def open_benefit_check(prescription_id: str, payer_id: str, clinic_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_benefit_check(
            create_benefit_check_payload(prescription_id, payer_id, **overrides),
            make_prescriber_headers(clinic_id),
        )
    )


# ═══════════════ Tier 2: entity hierarchies ═══════════════

def setup_clinic_pharmacy_patient(pharmacy_endpoint_specs=None, pharmacy_test_codes=None,
                                  patient_overrides=None, clinic_certified=True):
    """Certified clinic + certified pharmacy + one patient. Returns a bundle dict."""
    clinic = setup_certified_clinic() if clinic_certified else create_clinic()
    if pharmacy_test_codes is None:
        pharmacy_test_codes = ("CONNECTIVITY", "SCRIPT_NEW_RX")
    pharmacy, endpoints = setup_certified_pharmacy(
        endpoint_specs=pharmacy_endpoint_specs, test_codes=pharmacy_test_codes
    )
    patient = create_patient(**(patient_overrides or {}))
    return {"clinic": clinic, "pharmacy": pharmacy, "endpoints": endpoints, "patient": patient}


def setup_signed_prescription(clinic_id, pharmacy_id, patient_id, session=None, **rx_overrides):
    """Draft → OPEN session → both proofs → SIGNED. Returns (prescription, session)."""
    prescription = create_prescription(clinic_id, pharmacy_id, patient_id, **rx_overrides)
    if session is None:
        session = create_ready_session(prescription["id"], clinic_id)
    prescription = sign_prescription(prescription["id"], session["id"], clinic_id)
    return prescription, session


def setup_routed_prescription(clinic_id, pharmacy_id, patient_id, **rx_overrides):
    """Draft → SIGNED → ROUTED with one in-flight NETWORK attempt.
    Returns (prescription, attempt)."""
    prescription, _ = setup_signed_prescription(
        clinic_id, pharmacy_id, patient_id, **rx_overrides
    )
    prescription = route_prescription(prescription["id"], clinic_id)
    attempt = latest_attempt(prescription["id"])
    return prescription, attempt


def setup_delivered_prescription(clinic_id, pharmacy_id, patient_id, **rx_overrides):
    """Draft → SIGNED → ROUTED → attempt ACKNOWLEDGED (clinical DELIVERED).
    Returns (prescription, attempt)."""
    prescription, attempt = setup_routed_prescription(
        clinic_id, pharmacy_id, patient_id, **rx_overrides
    )
    report_acknowledged(attempt["id"])
    return reload_prescription(prescription["id"]), reload_attempt(attempt["id"])


def reload_attempt(attempt_id: str) -> dict:
    return get_success_data(api_client.get_attempt(attempt_id, OPERATOR))


# ═══════════════ Tier 3/4: scenario bundles ═══════════════

def setup_two_new_rx_endpoint_pharmacy(extra_endpoint_specs=None):
    """Riverbend Pharmacy CERTIFIED with two in-window NEW_RX endpoints on the 2022011
    standard: an ELIGIBLE_A endpoint at 15 minutes and an ELIGIBLE_B endpoint at 30 minutes,
    so the service-level key alone separates them and both speak the order's standard.
    Returns (pharmacy, ep_a, ep_b)."""
    specs = [
        {"service_set": "NEW_RX", "endpoint_role": "BOTH", "service_level": "ELIGIBLE_A",
         "sla_response_minutes": 15, "message_standard": "NCPDP_SCRIPT_2022011"},
        {"service_set": "NEW_RX", "endpoint_role": "BOTH", "service_level": "ELIGIBLE_B",
         "sla_response_minutes": 30, "message_standard": "NCPDP_SCRIPT_2022011"},
    ]
    if extra_endpoint_specs:
        specs.extend(extra_endpoint_specs)
    pharmacy, endpoints = setup_certified_pharmacy(endpoint_specs=specs)
    return pharmacy, endpoints[0], endpoints[1]


def setup_fallback_ready_prescription(fallback_channel="FAX", fax_number="+1-555-0100",
                                      with_fallback_endpoint=True):
    """Clinic (with the given fallback provisioning) + a pharmacy whose only NEW_RX endpoint
    is accompanied by an inert MED_HISTORY endpoint, so degrading the NEW_RX endpoint does not
    trip the coverage invariant while leaving no alternative for the same service set.

    A signed order is routed, its attempt reported undeliverable, leaving routing_status
    ROUTE_FAILED. Returns a bundle dict.
    """
    set_clock()
    clinic = create_clinic(fallback_channel=fallback_channel, fax_number=fax_number)
    add_endpoint(clinic["id"], service_set="NEW_RX", endpoint_role="SENDER",
                 service_level="ELIGIBLE_A", sla_response_minutes=15,
                 message_standard="NCPDP_SCRIPT_2022011")
    clinic = certify_participant(clinic["id"])

    specs = [{"service_set": "NEW_RX", "endpoint_role": "BOTH", "service_level": "ELIGIBLE_A",
              "sla_response_minutes": 15, "message_standard": "NCPDP_SCRIPT_2022011"}]
    if with_fallback_endpoint:
        specs.append({"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                      "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                      "message_standard": "NCPDP_SCRIPT_2022011"})
    pharmacy, endpoints = setup_certified_pharmacy(endpoint_specs=specs)
    patient = create_patient()

    prescription, attempt = setup_routed_prescription(
        clinic["id"], pharmacy["id"], patient["id"]
    )
    report_undeliverable(attempt["id"], "CF_0000")
    prescription = reload_prescription(prescription["id"])
    return {
        "clinic": clinic,
        "pharmacy": pharmacy,
        "endpoint": endpoints[0],
        "patient": patient,
        "prescription": prescription,
        "attempt": reload_attempt(attempt["id"]),
    }


def setup_medication_history_scenario(record_specs, consent_scope="MEDICATION_HISTORY",
                                      duration_days=45, pharmacy_overrides=None,
                                      uncertified_source=False, clinic_id=None):
    """A CERTIFIED pharmacy with a MED_HISTORY endpoint, a patient holding an ACTIVE consent,
    and the supplied history records. Returns a bundle dict.

    `record_specs` is a list of dicts; each may name `source_type`, `source_participant_id`
    ("certified" / "uncertified"), `drug_ndc`, `fill_date`, `days_supply` and `quantity`.

    Opening a batch is a `Prescriber` operation whose identity is entity-backed, so the
    fixture certifies a prescriber participant to act as the caller.
    """
    set_clock()
    pharmacy, _ = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}],
        **(pharmacy_overrides or {}),
    )
    extra = {}
    if uncertified_source:
        extra["uncertified_pharmacy"] = register_participant(
            "Harborside Pharmacy", "PHARMACY", "5555555555"
        )
    patient = create_patient()
    consent = grant_consent(patient["id"], scope=consent_scope, duration_days=duration_days)

    records = []
    for spec in record_specs:
        spec = dict(spec)
        owner = spec.pop("source_participant_id", "certified")
        source_id = extra["uncertified_pharmacy"]["id"] if owner == "uncertified" else pharmacy["id"]
        if source_id == extra.get("uncertified_pharmacy", {}).get("id"):
            # A record naming a source that is not CERTIFIED is reported by the
            # HubOperator capacity, because a Pharmacy identity is entity-backed (§2.1)
            # and could not resolve to that source.
            payload = create_history_record_payload(source_id, **spec)
            records.append(get_success_data(
                api_client.create_history_record(patient["id"], payload, HUB_OPERATOR)))
        else:
            records.append(add_history_record(patient["id"], source_id, **spec))

    # Opening a batch is a Prescriber operation; the identity supplied must resolve to a
    # CERTIFIED prescriber participant, so a real (freshly certified) clinic id is used as
    # the acting identity.
    acting_clinic = clinic_id or create_certified_second_clinic()["id"]
    batch = open_history_batch(patient["id"], acting_clinic)
    return {
        "pharmacy": pharmacy,
        "patient": patient,
        "consent": consent,
        "records": records,
        "batch": batch,
        **extra,
    }


def create_certified_second_clinic() -> dict:
    """A CERTIFIED prescriber clinic distinct from `create_clinic()`'s Northside participant."""
    clinic = create_second_clinic()
    add_endpoint(
        clinic["id"],
        service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    return certify_participant(clinic["id"])