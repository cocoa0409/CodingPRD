"""Composite setup helpers for the destination-medicine workflow.

Every helper builds its preconditions from scratch through the public API only,
and uses get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    DEPOSIT_TWO_SPECIALTY_CENTS,
    SLOT_DATE,
)
from .factories import (
    create_case_review_payload,
    create_logistics_payload,
    create_medical_record_payload,
    create_patient_payload,
    create_referral_payload,
    create_slot_hold_payload,
    create_slot_payload,
    create_specialty_service_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
IC_B = TEST_USERS["intake_coordinator_b_headers"]
CR = TEST_USERS["case_reviewer_headers"]
FC = TEST_USERS["financial_counselor_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(iso=CLOCK_START):
    resp = api_client.set_clock(iso, ADMIN)
    assert resp.status_code == 200, f"set_clock failed: {resp.text}"
    return get_success_data(resp)


def create_service(**overrides):
    resp = api_client.create_specialty_service(
        create_specialty_service_payload(**overrides), ADMIN
    )
    assert resp.status_code == 201, f"create_service failed: {resp.text}"
    return get_success_data(resp)


def create_slot(service_id, slot_date=SLOT_DATE, start_min=540, end_min=600):
    resp = api_client.create_slot(
        service_id,
        create_slot_payload(
            slot_date=slot_date, start_min=start_min, end_min=end_min
        ),
        ADMIN,
    )
    assert resp.status_code == 201, f"create_slot failed: {resp.text}"
    return get_success_data(resp)


def create_referral(ic_headers=IC, **overrides):
    resp = api_client.create_referral(create_referral_payload(**overrides), ic_headers)
    assert resp.status_code == 201, f"create_referral failed: {resp.text}"
    return get_success_data(resp)


def register_record(referral_id, ic_headers=IC, **overrides):
    resp = api_client.create_medical_record(
        referral_id, create_medical_record_payload(**overrides), ic_headers
    )
    assert resp.status_code == 201, f"register_record failed: {resp.text}"
    return get_success_data(resp)


def verify_record(referral_id, record_id, cr_headers=CR):
    resp = api_client.verify_medical_record(referral_id, record_id, cr_headers)
    assert resp.status_code == 200, f"verify_record failed: {resp.text}"
    return get_success_data(resp)


def register_and_verify_record(referral_id, ic_headers=IC, cr_headers=CR, **overrides):
    record = register_record(referral_id, ic_headers=ic_headers, **overrides)
    # Return the verify response (status VERIFIED), not the stale register
    # response — PRD §3.2: verification moves the record RECEIVED -> VERIFIED.
    return verify_record(referral_id, record["id"], cr_headers=cr_headers)


def submit_review(referral_id, ic_headers=IC):
    resp = api_client.submit_review(referral_id, ic_headers)
    assert resp.status_code == 200, f"submit_review failed: {resp.text}"
    return get_success_data(resp)


def create_case(referral_id, case_type, team_ids, ic_headers=IC):
    payload = {
        "referral_id": referral_id,
        "case_type": case_type,
        "care_team_specialty_ids": list(team_ids),
    }
    resp = api_client.create_visit_case(payload, ic_headers)
    assert resp.status_code == 201, f"create_case failed: {resp.text}"
    return get_success_data(resp)


def approve_case(case_id, cr_headers=CR, **overrides):
    resp = api_client.create_case_review(
        case_id, create_case_review_payload(outcome="APPROVE", **overrides), cr_headers
    )
    assert resp.status_code == 201, f"approve_case failed: {resp.text}"
    return get_success_data(resp)


def post_deposit(case_id, amount_cents, fc_headers=FC):
    resp = api_client.create_billing_transaction(
        case_id, {"txn_type": "DEPOSIT", "amount_cents": amount_cents}, fc_headers
    )
    assert resp.status_code == 201, f"post_deposit failed: {resp.text}"
    return get_success_data(resp)


def get_case(case_id):
    resp = api_client.get_visit_case(case_id, IC)
    assert resp.status_code == 200, f"get_case failed: {resp.text}"
    return get_success_data(resp)


def get_case_version(case_id):
    return get_case(case_id)["version"]


def get_case_itinerary(case_id):
    resp = api_client.get_case_itinerary(case_id, IC)
    assert resp.status_code == 200, f"get_case_itinerary failed: {resp.text}"
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, "expected exactly one itinerary"
    return data[0]


def get_case_clearance(case_id):
    resp = api_client.get_case_financial_clearance(case_id, FC)
    assert resp.status_code == 200, f"get_case_clearance failed: {resp.text}"
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, "expected exactly one clearance"
    return data[0]


def hold_slot(case_id, slot_id, expected_version, ic_headers=IC, **overrides):
    payload = create_slot_hold_payload(
        appointment_slot_id=slot_id,
        expected_case_version=expected_version,
        **overrides,
    )
    resp = api_client.create_slot_hold(case_id, payload, ic_headers)
    assert resp.status_code == 201, f"hold_slot failed: {resp.text}"
    return get_success_data(resp)


def hold_slot_fresh(case_id, slot_id, ic_headers=IC, **overrides):
    """Hold with the version re-read immediately beforehand (happy-path OCC)."""
    return hold_slot(case_id, slot_id, get_case_version(case_id), ic_headers, **overrides)


def confirm_slot(slot_id, ic_headers=IC):
    resp = api_client.confirm_slot(slot_id, ic_headers)
    assert resp.status_code == 200, f"confirm_slot failed: {resp.text}"
    return get_success_data(resp)


def confirm_itinerary(itinerary_id, ic_headers=IC):
    resp = api_client.confirm_itinerary(itinerary_id, ic_headers)
    assert resp.status_code == 200, f"confirm_itinerary failed: {resp.text}"
    return get_success_data(resp)


def issue_estimate_letter(case_id, fc_headers=FC):
    resp = api_client.create_estimate_letter(case_id, fc_headers)
    assert resp.status_code == 201, f"issue_estimate_letter failed: {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Composite: referral driven to IN_REVIEW
# ---------------------------------------------------------------------------

def setup_referral_in_review(patient_overrides=None, ic_headers=IC, cr_headers=CR):
    """Referral + one medical record, verified, submitted. Returns (referral, record)."""
    referral = create_referral(
        ic_headers=ic_headers,
        patient=create_patient_payload(**(patient_overrides or {})),
    )
    record = register_and_verify_record(
        referral["id"], ic_headers=ic_headers, cr_headers=cr_headers
    )
    submit_review(referral["id"], ic_headers=ic_headers)
    return referral, record


# ---------------------------------------------------------------------------
# Composite: standard card/neur service pair
# ---------------------------------------------------------------------------

def setup_card_neur_services():
    card = create_service(
        code="CARD", name="Cardiology", destination_daily_capacity=2,
        supports_imaging=True, supports_remote_products=True,
    )
    neur = create_service(
        code="NEUR", name="Neurology", destination_daily_capacity=2,
        supports_imaging=False, supports_remote_products=True,
    )
    return card, neur


# ---------------------------------------------------------------------------
# Tier: approved case, clearance PENDING
# ---------------------------------------------------------------------------

def setup_approved_case(case_type="DESTINATION", team_size=2,
                        patient_overrides=None, ic_headers=IC, cr_headers=CR,
                        services=None):
    """Referral IN_REVIEW -> case created -> APPROVE review.

    Returns dict with keys: referral, case, services (list), itinerary (or None),
    clearance.
    """
    if services is None:
        if team_size == 2:
            services = list(setup_card_neur_services())
        else:
            services = [
                create_service(
                    code=f"TM{i}", name=f"TeamSvc{i}",
                    destination_daily_capacity=4,
                    supports_imaging=True, supports_remote_products=True,
                )
                for i in range(team_size)
            ]
    referral, _record = setup_referral_in_review(
        patient_overrides=patient_overrides, ic_headers=ic_headers, cr_headers=cr_headers
    )
    team_ids = [s["id"] for s in services[:team_size]]
    case = create_case(referral["id"], case_type, team_ids, ic_headers=ic_headers)
    approve_case(case["id"], cr_headers=cr_headers)
    case = get_case(case["id"])
    itinerary = None
    if case_type == "DESTINATION":
        itinerary = get_case_itinerary(case["id"])
    clearance = get_case_clearance(case["id"])
    return {
        "referral": referral,
        "case": case,
        "services": services,
        "itinerary": itinerary,
        "clearance": clearance,
    }


# ---------------------------------------------------------------------------
# Tier: case FINANCIAL_CLEARED via deposit
# ---------------------------------------------------------------------------

def setup_cleared_case(deposit_cents=DEPOSIT_TWO_SPECIALTY_CENTS, **kwargs):
    """Approved case with a deposit posted so the clearance is CLEARED."""
    ctx = setup_approved_case(**kwargs)
    post_deposit(ctx["case"]["id"], deposit_cents)
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["clearance"] = get_case_clearance(ctx["case"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier: case SCHEDULING with held slots
# ---------------------------------------------------------------------------

def setup_case_with_holds(hold_specs, **kwargs):
    """FINANCIAL_CLEARED case + one held slot per spec.

    hold_specs: list of dicts, each with keys service_index (default 0),
    slot_date, start_min, end_min, visit_type, listed_price_cents,
    sequencing_priority. Slots are created on the referenced service.
    Returns ctx extended with 'slots' and 'visits' lists.
    """
    ctx = setup_cleared_case(**kwargs)
    case_id = ctx["case"]["id"]
    slots = []
    visits = []
    for spec in hold_specs:
        svc = ctx["services"][spec.get("service_index", 0)]
        slot = create_slot(
            svc["id"],
            slot_date=spec.get("slot_date", SLOT_DATE),
            start_min=spec.get("start_min", 540),
            end_min=spec.get("end_min", 600),
        )
        visit = hold_slot_fresh(
            case_id,
            slot["id"],
            visit_type=spec.get("visit_type", "CONSULT"),
            listed_price_cents=spec.get("listed_price_cents", 200000),
            sequencing_priority=spec.get("sequencing_priority", len(visits) + 1),
        )
        slots.append(slot)
        visits.append(visit)
    ctx["slots"] = slots
    ctx["visits"] = visits
    ctx["case"] = get_case(case_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier: case SCHEDULED (slots confirmed + itinerary confirmed)
# ---------------------------------------------------------------------------

def setup_scheduled_case(hold_specs=None, **kwargs):
    """SCHEDULED case: 2 same-day visits held, slots confirmed, itinerary confirmed."""
    if hold_specs is None:
        hold_specs = [
            {"start_min": 540, "end_min": 600, "visit_type": "CONSULT",
             "listed_price_cents": 200000, "sequencing_priority": 1},
            {"start_min": 600, "end_min": 660, "visit_type": "IMAGING",
             "listed_price_cents": 200000, "sequencing_priority": 2},
        ]
    ctx = setup_case_with_holds(hold_specs, **kwargs)
    for slot in ctx["slots"]:
        confirm_slot(slot["id"])
    itinerary_id = ctx["itinerary"]["id"]
    confirm_itinerary(itinerary_id)
    ctx["case"] = get_case(ctx["case"]["id"])
    resp = api_client.get_itinerary(itinerary_id, IC)
    ctx["itinerary"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Tier: READY_TO_TRAVEL (estimate letter + travel authorization)
# ---------------------------------------------------------------------------

def setup_ready_to_travel_case(**kwargs):
    ctx = setup_scheduled_case(**kwargs)
    issue_estimate_letter(ctx["case"]["id"])
    resp = api_client.authorize_travel(ctx["case"]["id"], IC)
    assert resp.status_code == 200, f"authorize_travel failed: {resp.text}"
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier: fatigue scenario — five records, one case in INTAKE
# ---------------------------------------------------------------------------

def setup_fatigue_case(num_records=5, verify_first=1, cr_headers=CR):
    """Referral with `num_records` registered records; the first `verify_first`
    are verified, the referral submitted, and a DESTINATION case created
    (INTAKE, fatigue 0). Returns dict with referral, case, records, services."""
    card, neur = setup_card_neur_services()
    referral = create_referral(patient=create_patient_payload(
        full_name="Fred Fatigue", residence_state="IA",
    ))
    record_types = ["IMAGING", "LAB", "PATHOLOGY", "CLINICAL_NOTES", "MEDICATION_LIST"]
    records = [
        register_record(
            referral["id"],
            record_type=record_types[i % len(record_types)],
            source_facility="U Iowa",
        )
        for i in range(num_records)
    ]
    for rec in records[:verify_first]:
        verify_record(referral["id"], rec["id"], cr_headers=cr_headers)
    submit_review(referral["id"])
    case = create_case(referral["id"], "DESTINATION", [card["id"], neur["id"]])
    return {
        "referral": referral,
        "case": case,
        "records": records,
        "services": [card, neur],
    }
