"""Composite setup builders.

The harness restarts the server and empties the store before every single test,
so every builder here starts from nothing and drives state forward only through
endpoints the PRD declares. Nothing is inserted behind the API's back.

Creates answer 201 with the created row; transitions answer 200 with the
updated row; the logical-clock advance and the sampling run answer 200 with a
summary object rather than a persisted row.
"""
from prd_bench_local_runner.testing import validate_success

from .api_client import ApiClient
from .assertions import validate_unpaginated
from .constants import COMPLAINT_SORE_THROAT, COVERAGE_INACTIVE
from .factories import (
    active_coverage_payload,
    appointment_payload,
    assessment_payload,
    clinic_payload,
    clinician_payload,
    eligibility_payload,
    insured_patient_payload,
    patient_payload,
    physician_payload,
    protocol_payload,
    staffing_assignment_payload,
    state_rule_payload,
    visit_payload,
    walk_in_payload,
)
from .test_users import (
    make_admin_headers,
    make_clinician_headers,
    make_front_desk_headers,
    make_patient_headers,
    make_physician_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-row creates
# ---------------------------------------------------------------------------

def set_clock(api: ApiClient, instant: str, admin=None) -> dict:
    """Move the logical clock and return the advance summary object."""
    admin = admin or make_admin_headers()
    return validate_unpaginated(api.set_clock(instant, admin))


def create_state_rule(api: ApiClient, admin=None, **kwargs) -> dict:
    admin = admin or make_admin_headers()
    return validate_success(api.create_state_rule(state_rule_payload(**kwargs), admin), 201)


def create_protocol(api: ApiClient, admin=None, **kwargs) -> dict:
    admin = admin or make_admin_headers()
    return validate_success(api.create_protocol(protocol_payload(**kwargs), admin), 201)


def create_clinic(api: ApiClient, admin=None, **kwargs) -> dict:
    admin = admin or make_admin_headers()
    return validate_success(api.create_clinic(clinic_payload(**kwargs), admin), 201)


def create_physician(api: ApiClient, admin=None, **kwargs) -> dict:
    admin = admin or make_admin_headers()
    return validate_success(api.create_physician(physician_payload(**kwargs), admin), 201)


def create_clinician(api: ApiClient, clinic_id, physician_id, admin=None,
                     **kwargs) -> dict:
    admin = admin or make_admin_headers()
    payload = clinician_payload(clinic_id, physician_id, **kwargs)
    return validate_success(api.create_clinician(payload, admin), 201)


def create_patient(api: ApiClient, admin=None, **kwargs) -> dict:
    admin = admin or make_admin_headers()
    return validate_success(api.create_patient(patient_payload(**kwargs), admin), 201)


def create_insured_patient(api: ApiClient, admin=None, **kwargs) -> dict:
    admin = admin or make_admin_headers()
    payload = insured_patient_payload(**kwargs)
    return validate_success(api.create_patient(payload, admin), 201)


def create_assignment(api: ApiClient, clinic_id, clinician_id, admin=None,
                      **kwargs) -> dict:
    admin = admin or make_admin_headers()
    payload = staffing_assignment_payload(clinic_id, clinician_id, **kwargs)
    return validate_success(api.create_staffing_assignment(payload, admin), 201)


def read_clinic(api: ApiClient, clinic_id, headers=None) -> dict:
    return validate_success(api.get_clinic(clinic_id, headers or make_admin_headers()))


def read_visit(api: ApiClient, visit_id, headers=None) -> dict:
    return validate_success(api.get_visit(visit_id, headers or make_admin_headers()))


def read_patient(api: ApiClient, patient_id, headers=None) -> dict:
    return validate_success(api.get_patient(patient_id, headers or make_admin_headers()))


def read_physician(api: ApiClient, physician_id, headers=None) -> dict:
    return validate_success(
        api.get_physician(physician_id, headers or make_admin_headers()))


def read_clinician(api: ApiClient, clinician_id, headers=None) -> dict:
    return validate_success(
        api.get_clinician(clinician_id, headers or make_admin_headers()))


def read_assignment(api: ApiClient, assignment_id, headers=None) -> dict:
    return validate_success(
        api.get_staffing_assignment(assignment_id, headers or make_admin_headers()))


def read_queue_entry(api: ApiClient, queue_entry_id, headers=None) -> dict:
    return validate_success(
        api.get_queue_entry(queue_entry_id, headers or make_admin_headers()))


def read_assessment(api: ApiClient, assessment_id, headers=None) -> dict:
    return validate_success(
        api.get_assessment(assessment_id, headers or make_admin_headers()))


def read_prescription(api: ApiClient, prescription_id, headers=None) -> dict:
    return validate_success(
        api.get_prescription(prescription_id, headers or make_admin_headers()))


def read_chart_review(api: ApiClient, chart_review_id, headers=None) -> dict:
    return validate_success(
        api.get_chart_review(chart_review_id, headers or make_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 2: a licensed, staffed, open clinic
# ---------------------------------------------------------------------------

def staffed_clinic(api: ApiClient, *, clock=None, state=None, protocol=None,
                   clinic=None, physician=None, clinician=None, assignment=None,
                   clinician_count=1, staff=True, with_protocol=True) -> dict:
    """State rule, protocol, clinic, supervising physician and staffed clinicians.

    `clock` moves the logical clock before any assignment is filed, which
    matters because an assignment whose window already contains the current
    instant activates on creation while a future one is merely scheduled.
    Every `*_kwargs`-style argument is a dict of factory overrides.
    """
    admin = make_admin_headers()
    env = {
        "admin": admin,
        "front_desk": make_front_desk_headers(),
        "clinicians": [],
        "assignments": [],
        "clinician_headers_list": [],
    }
    if clock is not None:
        env["clock"] = set_clock(api, clock, admin)

    env["state_rule"] = create_state_rule(api, admin, **(state or {}))
    if with_protocol:
        env["protocol"] = create_protocol(api, admin, **(protocol or {}))
    env["clinic"] = create_clinic(api, admin, **(clinic or {}))
    env["clinic_id"] = env["clinic"]["id"]
    env["physician"] = create_physician(api, admin, **(physician or {}))
    env["physician_id"] = env["physician"]["id"]
    env["physician_headers"] = make_physician_headers(env["physician_id"])

    # The default state rule requires a collaborating physician, so every shift
    # pins the clinician's own supervising physician unless a caller overrides it.
    shift = dict(assignment or {})
    shift.setdefault("pinned_supervising_physician_id", env["physician_id"])
    if shift.get("pinned_supervising_physician_id") is None:
        shift.pop("pinned_supervising_physician_id")

    for index in range(clinician_count):
        overrides = dict(clinician or {})
        overrides.setdefault("full_name", f"NP Test {index + 1}")
        row = create_clinician(api, env["clinic_id"], env["physician_id"], admin,
                               **overrides)
        env["clinicians"].append(row)
        env["clinician_headers_list"].append(make_clinician_headers(row["id"]))
        if staff:
            env["assignments"].append(
                create_assignment(api, env["clinic_id"], row["id"], admin, **shift))

    env["clinician"] = env["clinicians"][0]
    env["clinician_id"] = env["clinician"]["id"]
    env["clinician_headers"] = env["clinician_headers_list"][0]
    if staff:
        env["assignment"] = env["assignments"][0]
        env["assignment_id"] = env["assignment"]["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 3: queue entries
# ---------------------------------------------------------------------------

def add_walk_in(api: ApiClient, env, patient_id, complaint_code=COMPLAINT_SORE_THROAT,
                headers=None, **overrides) -> dict:
    headers = headers or env["front_desk"]
    payload = walk_in_payload(env["clinic_id"], patient_id,
                              complaint_code=complaint_code, **overrides)
    return validate_success(api.create_queue_entry(payload, headers), 201)


def add_appointment(api: ApiClient, env, patient_id, scheduled_at,
                    complaint_code=COMPLAINT_SORE_THROAT, headers=None,
                    **overrides) -> dict:
    headers = headers or env["front_desk"]
    payload = appointment_payload(env["clinic_id"], patient_id, scheduled_at,
                                  complaint_code=complaint_code, **overrides)
    return validate_success(api.create_queue_entry(payload, headers), 201)


def arrive(api: ApiClient, queue_entry_id, headers) -> dict:
    return validate_success(api.arrive_queue_entry(queue_entry_id, headers))


def call_next(api: ApiClient, env, headers=None) -> dict:
    """The treating clinician calls the highest-ranked waiting entry."""
    return validate_success(
        api.call_next(env["clinic_id"], headers or env["clinician_headers"]))


# ---------------------------------------------------------------------------
# Tier 4: visits and assessments
# ---------------------------------------------------------------------------

def start_visit(api: ApiClient, env, queue_entry_id, headers=None,
                clinician_id=None) -> dict:
    """Open the encounter on an already-called queue entry."""
    headers = headers or env["clinician_headers"]
    payload = visit_payload(queue_entry_id, clinician_id=clinician_id)
    return validate_success(api.create_visit(payload, headers), 201)


def screening_visit(api: ApiClient, env, patient_id,
                    complaint_code=COMPLAINT_SORE_THROAT, headers=None,
                    **entry_overrides) -> dict:
    """Walk in, get called, and open the encounter. Returns {entry, visit}."""
    entry = add_walk_in(api, env, patient_id, complaint_code=complaint_code,
                        **entry_overrides)
    call_next(api, env, headers=headers)
    visit = start_visit(api, env, entry["id"], headers=headers)
    return {"entry": entry, "visit": visit, "visit_id": visit["id"]}


def start_assessment(api: ApiClient, env, visit_id, headers=None, **vitals) -> dict:
    headers = headers or env["clinician_headers"]
    return validate_success(
        api.create_assessment(assessment_payload(visit_id, **vitals), headers), 201)


def submit_assessment(api: ApiClient, env, assessment_id, headers=None) -> dict:
    headers = headers or env["clinician_headers"]
    return validate_success(api.submit_assessment(assessment_id, headers))


def cosign_assessment(api: ApiClient, env, assessment_id, headers=None) -> dict:
    headers = headers or env["physician_headers"]
    return validate_success(api.cosign_assessment(assessment_id, headers))


def treated_visit(api: ApiClient, env, patient_id,
                  complaint_code=COMPLAINT_SORE_THROAT, cosign=False,
                  vitals=None, headers=None, **entry_overrides) -> dict:
    """Carry one patient from the queue through to an authorized treatment.

    Returns {entry, visit, visit_id, assessment}. `cosign` adds the supervising
    physician's countersignature, which the protocol may require before the
    encounter can be checked out.
    """
    started = screening_visit(api, env, patient_id, complaint_code=complaint_code,
                              headers=headers, **entry_overrides)
    assessment = start_assessment(api, env, started["visit_id"], headers=headers,
                                  **(vitals or {}))
    assessment = submit_assessment(api, env, assessment["id"], headers=headers)
    if cosign:
        assessment = cosign_assessment(api, env, assessment["id"])
    started["assessment"] = assessment
    started["assessment_id"] = assessment["id"]
    return started


# ---------------------------------------------------------------------------
# Tier 5: billing
# ---------------------------------------------------------------------------

def verify_active_coverage(api: ApiClient, env, visit_id, copay_cents=2500,
                           coinsurance_pct=12.5, headers=None) -> dict:
    headers = headers or env["front_desk"]
    payload = active_coverage_payload(copay_cents=copay_cents,
                                      coinsurance_pct=coinsurance_pct)
    return validate_success(api.eligibility_check(visit_id, payload, headers))


def quote_self_pay(api: ApiClient, env, visit_id, headers=None) -> dict:
    """An inactive eligibility answer turns the encounter into a self-pay quote."""
    headers = headers or env["front_desk"]
    payload = eligibility_payload(COVERAGE_INACTIVE)
    return validate_success(api.eligibility_check(visit_id, payload, headers))


def accept_quote(api: ApiClient, visit_id, acknowledged_price_cents,
                 patient_id=None, headers=None) -> dict:
    """The patient acknowledges the quoted self-pay price to the cent."""
    if headers is None:
        headers = make_patient_headers(patient_id)
    return validate_success(
        api.accept_self_pay(visit_id, acknowledged_price_cents, headers))


def checkout(api: ApiClient, env, visit_id, services_rendered=None,
             headers=None) -> dict:
    """Only the treating clinician's role may close and price a visit."""
    headers = headers or env["clinician_headers"]
    return validate_success(
        api.checkout(visit_id, headers, services_rendered=services_rendered or []))


def closed_insured_visit(api: ApiClient, env, patient_id, services_rendered=None,
                         cosign=False, copay_cents=2500, coinsurance_pct=12.5,
                         complaint_code=COMPLAINT_SORE_THROAT, **kwargs) -> dict:
    """Insured patient carried all the way to an invoiced, closed encounter."""
    bundle = treated_visit(api, env, patient_id, complaint_code=complaint_code,
                           cosign=cosign, **kwargs)
    verify_active_coverage(api, env, bundle["visit_id"], copay_cents=copay_cents,
                           coinsurance_pct=coinsurance_pct)
    bundle["visit"] = checkout(api, env, bundle["visit_id"],
                              services_rendered=services_rendered)
    return bundle


def run_sampling(api: ApiClient, clinic_id, window_start, window_end,
                 headers=None) -> dict:
    """Run the chart-review sampling; the answer is a run summary, not a page."""
    headers = headers or make_admin_headers()
    return validate_unpaginated(
        api.run_chart_review_sampling(clinic_id, window_start, window_end, headers))
