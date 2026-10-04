"""Composite setup helpers for multi-step workflows.

The runner restarts the API server before every test, so each helper builds
its preconditions from scratch via PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_care_team_payload,
    create_market_payload,
    create_patient_payload,
    create_payer_contract_payload,
    create_triage_assessment_payload,
    create_vehicle_shift_payload,
    create_visit_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_care_team_member_headers,
    make_field_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
APP = TEST_USERS["app_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
ADJUDICATOR = TEST_USERS["payer_adjudicator_headers"]

CLOCK_START = "2026-09-15T10:00:00Z"

# Vitals yielding an URGENT-band acuity score for the default patient
# (DOB 1980-01-01 -> age 46 at the default clock, comorbidity_count 1):
# hr |130-80|//4 = 12, bp |95-120|//5 = 5, spo2 (95-92)*2 = 6, comorbidity 3
# => 26 would be NON_ACUTE, so heart_rate is set to 250 to cap the HR
# component at 25 and systolic_bp at 181 to trip the extreme branch (25)
# => 25 + 25 + 6 + 3 = 59, still no red flags => URGENT band.
URGENT_VITALS = {
    "heart_rate": 250,
    "systolic_bp": 181,
    "spo2_pct": 92,
    "is_chest_pain": False,
    "is_stroke_signs": False,
    "is_severe_trauma": False,
    "is_altered_mental_status": False,
}

# Vitals yielding a score of exactly 20 with one red flag.
RED_FLAG_VITALS = {
    "heart_rate": 130,
    "systolic_bp": 90,
    "spo2_pct": 90,
    "is_chest_pain": True,
    "is_stroke_signs": False,
    "is_severe_trauma": False,
    "is_altered_mental_status": False,
}

DISCHARGE_RATIONALE = (
    "Stable after evaluation; discharged home with precautions reviewed."
)


def set_clock(current_utc=CLOCK_START):
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_market(**overrides):
    return get_success_data(
        api_client.create_market(create_market_payload(**overrides), ADMIN)
    )


def create_patient(pcp_npi="1234567890", **overrides):
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(pcp_npi=pcp_npi, **overrides), NURSE
        )
    )


def create_contract_and_activate(market_id, **overrides):
    contract = get_success_data(
        api_client.create_payer_contract(
            create_payer_contract_payload(market_id, **overrides), ADMIN
        )
    )
    return get_success_data(api_client.activate_payer_contract(contract["id"], ADMIN))


def create_team_and_shift(
    market_id,
    app_user="app-001",
    tech_user="tech-001",
    md_user="md-001",
    skill_tags=("POCT",),
    window_start="2026-09-15T08:00:00Z",
    window_end="2026-09-15T20:00:00Z",
    go_available=True,
    start_shift=True,
):
    team = get_success_data(
        api_client.create_care_team(
            create_care_team_payload(
                market_id,
                app_user_id=app_user,
                tech_user_id=tech_user,
                supervising_physician_user_id=md_user,
                skill_tags=list(skill_tags),
            ),
            DISPATCHER,
        )
    )
    if go_available:
        get_success_data(api_client.care_team_go_available(team["id"], DISPATCHER))
    shift = get_success_data(
        api_client.create_vehicle_shift(
            create_vehicle_shift_payload(
                team["id"], market_id,
                window_start=window_start, window_end=window_end,
            ),
            DISPATCHER,
        )
    )
    if start_shift:
        get_success_data(api_client.start_vehicle_shift(shift["id"], DISPATCHER))
    return team, shift


def setup_market_team_shift(
    app_user="app-001",
    tech_user="tech-001",
    md_user="md-001",
    skill_tags=("POCT",),
    clock=CLOCK_START,
    market_overrides=None,
    shift_overrides=None,
    go_available=True,
    start_shift=True,
):
    """Market + AVAILABLE team + started ACTIVE shift. Returns dict."""
    set_clock(clock)
    market = create_market(**(market_overrides or {}))
    team, shift = create_team_and_shift(
        market["id"], app_user, tech_user, md_user, skill_tags,
        go_available=go_available, start_shift=start_shift,
        **(shift_overrides or {}),
    )
    return {
        "market": market, "team": team, "shift": shift,
        "app_user": app_user, "tech_user": tech_user, "md_user": md_user,
    }


def create_triaged_visit(
    market_id,
    patient_id,
    chief_complaint="fever",
    vitals=None,
    outcome="APPROPRIATE",
):
    """Create a visit + triage assessment, submit it. Returns dict."""
    vr = get_success_data(
        api_client.create_visit_request(
            create_visit_request_payload(
                patient_id, market_id, chief_complaint=chief_complaint
            ),
            NURSE,
        )
    )
    trg = get_success_data(
        api_client.create_triage_assessment(
            vr["id"],
            create_triage_assessment_payload(**(vitals or URGENT_VITALS)),
            NURSE,
        )
    )
    submitted = get_success_data(
        api_client.submit_triage_assessment(trg["id"], {"outcome": outcome}, NURSE)
    )
    return {"vr": vr, "trg": submitted}


def offer_dispatch(vr_id, expected_version):
    return get_success_data(
        api_client.create_dispatch_offer(
            vr_id,
            {"expected_visit_request_version": expected_version},
            DISPATCHER,
        )
    )


def offer_dispatch_fresh(vr_id):
    """Offer a dispatch using the visit's CURRENT version (the OCC token must
    match the version after the triage cascade mutated the visit)."""
    vr = get_success_data(api_client.get_visit_request(vr_id, DISPATCHER))
    return offer_dispatch(vr_id, vr["version"])


def setup_visit_on_scene(
    app_user="app-001",
    tech_user="tech-001",
    md_user="md-001",
    skill_tags=("POCT",),
    chief_complaint="fever",
    vitals=None,
    market_overrides=None,
    clock=CLOCK_START,
    with_contract=False,
    contract_overrides=None,
):
    """Full pipeline: market, team, shift, patient, visit triaged, dispatch
    offered, accepted, arrived. Returns dict with every handle a test needs.
    With with_contract=True, an ACTIVE payer contract is created for the
    market before the visit is driven, so the auto-created claim can resolve
    its payer_contract_id at disposition."""
    ctx = setup_market_team_shift(
        app_user, tech_user, md_user, skill_tags, clock=clock,
        market_overrides=market_overrides,
    )
    if with_contract:
        ctx["contract"] = create_contract_and_activate(
            ctx["market"]["id"], **(contract_overrides or {})
        )
    patient = create_patient()
    ctx["patient"] = patient
    t = create_triaged_visit(
        ctx["market"]["id"], patient["id"],
        chief_complaint=chief_complaint, vitals=vitals,
    )
    ctx.update(t)
    da = offer_dispatch_fresh(ctx["vr"]["id"])
    ctx["da"] = da
    member = make_care_team_member_headers(app_user)
    get_success_data(api_client.accept_dispatch(da["id"], member))
    encounter = get_success_data(api_client.arrive_dispatch(da["id"], member))
    ctx["enc"] = encounter
    return ctx


def drive_to_disposition_review(ctx):
    """From ON_SCENE: begin disposition review (requires no unresolved orders)."""
    return get_success_data(
        api_client.begin_disposition_review(ctx["enc"]["id"], APP)
    )


def discharge_home(ctx, rationale=DISCHARGE_RATIONALE):
    """Record a DISCHARGE_HOME disposition. Returns the DispositionDecision."""
    drive_to_disposition_review(ctx)
    return get_success_data(
        api_client.create_disposition_decision(
            ctx["enc"]["id"],
            {"disposition": "DISCHARGE_HOME", "rationale": rationale},
            APP,
        )
    )


def escalate_to_facility(ctx, facility_id="FAC-DALLAS-001",
                         rationale="Patient worsening; escalated to facility-level care."):
    drive_to_disposition_review(ctx)
    return get_success_data(
        api_client.create_disposition_decision(
            ctx["enc"]["id"],
            {
                "disposition": "ESCALATE_TO_FACILITY",
                "rationale": rationale,
                "receiving_facility_id": facility_id,
            },
            APP,
        )
    )


def get_claim_for_visit(vr_id):
    vr = get_success_data(api_client.get_visit_request(vr_id, BILLING))
    claim_id = vr["claim_id"]
    claim = get_success_data(api_client.get_claim(claim_id, BILLING))
    return vr, claim


def queue_follow_up_notice(ctx):
    pcp_npi = ctx["patient"]["pcp_npi"]
    return get_success_data(
        api_client.create_follow_up_notice(
            ctx["vr"]["id"],
            {
                "pcp_npi": pcp_npi,
                "payload_summary": (
                    "Visit summary for PCP: patient seen at home for "
                    "evaluation; stable on discharge; precautions reviewed."
                ),
            },
            NURSE,
        )
    )


def setup_dispositioned_home_visit(**kwargs):
    """Full pipeline ending in DISCHARGE_HOME disposition (Claim auto-created).
    Returns ctx extended with 'disp', 'claim'."""
    ctx = setup_visit_on_scene(**kwargs)
    ctx["disp"] = discharge_home(ctx)
    vr, claim = get_claim_for_visit(ctx["vr"]["id"])
    ctx["vr"] = vr
    ctx["claim"] = claim
    return ctx


def result_order(ctx, order_id, result_value="result recorded"):
    """Collect + result a diagnostic order as the team's field technician."""
    tech = make_field_technician_headers(ctx["tech_user"])
    get_success_data(api_client.collect_diagnostic_order(order_id, tech))
    return get_success_data(
        api_client.result_diagnostic_order(order_id, {"result_value": result_value}, tech)
    )
