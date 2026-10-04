"""Composite setup helpers.

Every helper builds its preconditions from scratch against a freshly restarted
server (the harness restarts the API before each test), using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    agency_payload, certification_payload, contract_payload, criterion_payload,
    go_live_payload, interface_payload, maintenance_payload, migration_batch_payload,
    milestone_payload, phase_payload, record_payload, staff_payload,
    training_session_payload, uat_cycle_payload, uat_session_payload,
    workflow_process_payload, decision_payload,
)
from .test_users import TEST_USERS, make_headers

ADMIN = TEST_USERS["platform_admin"]
PROC = TEST_USERS["procurement_officer"]
IMPL = TEST_USERS["implementation_manager"]
AGENCY_PM = TEST_USERS["agency_pm"]
VENDOR_PM = TEST_USERS["vendor_pm"]
FIN = TEST_USERS["finance_officer"]
BA = TEST_USERS["business_analyst"]
DML = TEST_USERS["data_migration_lead"]
IFACE = TEST_USERS["interface_engineer"]
SUPPORT = TEST_USERS["support_manager"]


def reset_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_agency(**overrides):
    return get_success_data(api_client.create_agency(agency_payload(**overrides), ADMIN))


def create_draft_contract(agency_id, **overrides):
    return get_success_data(api_client.create_contract(contract_payload(agency_id, **overrides), PROC))


def walk_contract_to_award_pending(contract_id):
    for target in ("POSTED", "Q&A_OPEN", "Q&A_CLOSED", "EVALUATION", "AWARD_PENDING"):
        get_success_data(api_client.transition_contract(contract_id, {"target": target}, PROC))


def award_contract(contract_id):
    current = get_success_data(api_client.get_contract(contract_id, PROC))
    return get_success_data(
        api_client.award_contract(
            contract_id, {"expected_contract_version": current["version"]}, PROC
        )
    )


def add_phase(contract_id, sequence_no=1, **overrides):
    return get_success_data(
        api_client.create_phase(contract_id, phase_payload(sequence_no, **overrides), IMPL)
    )


def create_contract_in_implementation(num_phases=1, agency=None, **contract_overrides):
    """Full path DRAFT -> IMPLEMENTATION with num_phases phases; phase 1 ACTIVE."""
    agency = agency or create_agency()
    contract = create_draft_contract(agency["id"], **contract_overrides)
    walk_contract_to_award_pending(contract["id"])
    award_contract(contract["id"])
    phases = [add_phase(contract["id"], i + 1) for i in range(num_phases)]
    contract = get_success_data(api_client.start_implementation(contract["id"], IMPL))
    # re-fetch: start_implementation flips phase 1 to ACTIVE server-side
    phases = [get_success_data(api_client.get_phase(p["id"], IMPL)) for p in phases]
    return {"agency": agency, "contract": contract, "phases": phases}


def create_milestone(phase_id, code=None, amount=1_000_000, variant=None, headers=None):
    overrides = {}
    if code is not None:
        overrides["code"] = code
    if variant is not None:
        overrides["billing_variant"] = variant
    payload = milestone_payload(billable_amount_cents=amount, **overrides)
    return get_success_data(api_client.create_milestone(phase_id, payload, headers or IMPL))


def submit_milestone(milestone_id, user_id="vendor-pm-1"):
    return get_success_data(
        api_client.submit_milestone(milestone_id, make_headers(user_id, "VendorProjectManager"))
    )


def accept_milestone(milestone_id, user_id="agency-pm-9"):
    return get_success_data(
        api_client.accept_milestone(milestone_id, make_headers(user_id, "AgencyProjectManager"))
    )


def create_accepted_milestone(phase_id, code=None, amount=1_000_000, variant=None):
    m = create_milestone(phase_id, code=code, amount=amount, variant=variant)
    submit_milestone(m["id"])
    return accept_milestone(m["id"])


def add_satisfied_criterion(milestone_id, code="AC-01"):
    c = get_success_data(api_client.create_criterion(milestone_id, criterion_payload(code=code), IMPL))
    get_success_data(api_client.record_criterion_result(c["id"], {"result": "SATISFIED"}, AGENCY_PM))
    return c


def create_batch(contract_id, **overrides):
    return get_success_data(
        api_client.create_migration_batch(contract_id, migration_batch_payload(**overrides), DML)
    )


def ingest_records(batch_id, records):
    return get_success_data(api_client.ingest_records(batch_id, {"records": records}, DML))


def load_batch_through(batch_id, records):
    """Ingest -> extract -> cleanse (no flagged records) -> load."""
    ingest_records(batch_id, records)
    get_success_data(api_client.extract_batch(batch_id, DML))
    get_success_data(api_client.cleanse_batch(batch_id, {"resolutions": {}}, DML))
    return get_success_data(api_client.load_batch(batch_id, DML))


def reconcile_batch(batch_id, user_id="dml-1"):
    return api_client.reconcile_batch(batch_id, make_headers(user_id, "DataMigrationLead"))


def create_accepted_batch(contract_id, domain="PROPERTY_TAX", expected_count=1,
                          expected_value=100, records=None, reconciler="dml-1",
                          acceptor="agency-pm-9"):
    """Batch walked DEFINED -> ACCEPTED (within tolerance by construction)."""
    records = records if records is not None else [record_payload("R1", expected_value)]
    batch = create_batch(
        contract_id, domain=domain,
        expected_record_count=expected_count, expected_net_value_cents=expected_value,
    )
    load_batch_through(batch["id"], records)
    resp = reconcile_batch(batch["id"], user_id=reconciler)
    data = get_success_data(resp)
    assert data["status"] == "RECONCILED", f"Setup failed: batch did not reconcile: {data}"
    return get_success_data(
        api_client.accept_batch(batch["id"], make_headers(acceptor, "AgencyProjectManager"))
    )


def create_interface(contract_id, **overrides):
    return get_success_data(api_client.create_interface(contract_id, interface_payload(**overrides), IFACE))


def create_certified_interface(contract_id, window=("2026-09-01", "2026-09-10"), **overrides):
    iface = create_interface(contract_id, **overrides)
    get_success_data(api_client.start_interface_development(iface["id"], IFACE))
    get_success_data(api_client.start_interface_testing(iface["id"], IFACE))
    cert = get_success_data(
        api_client.create_certification(
            iface["id"], certification_payload(
                window_starts_on=window[0], window_ends_on=window[1]), IFACE)
    )
    get_success_data(api_client.begin_certification(cert["id"], IFACE))
    get_success_data(api_client.pass_certification(cert["id"], AGENCY_PM))
    return iface, cert


def create_uat_tester(agency_id, **overrides):
    overrides.setdefault("staff_function", "UAT_TESTER")
    overrides.setdefault("tenure_years", 3)
    return get_success_data(api_client.create_staff(agency_id, staff_payload(**overrides), AGENCY_PM))


def create_passed_uat_cycle(contract_id, agency_id, session_date="2026-09-05"):
    tester = create_uat_tester(agency_id)
    cycle = get_success_data(api_client.create_uat_cycle(contract_id, uat_cycle_payload(), AGENCY_PM))
    session = get_success_data(
        api_client.create_uat_session(
            cycle["id"], uat_session_payload(tester["id"], scheduled_on=session_date), AGENCY_PM)
    )
    get_success_data(api_client.start_uat_cycle(cycle["id"], AGENCY_PM))
    get_success_data(api_client.record_uat_session_result(session["id"], {"result": "PASSED"}, AGENCY_PM))
    cycle = get_success_data(api_client.complete_uat_cycle(cycle["id"], AGENCY_PM))
    assert cycle["status"] == "PASSED", f"Setup failed: UAT cycle not PASSED: {cycle}"
    return cycle


def create_approved_process(contract_id, **overrides):
    wp = get_success_data(
        api_client.create_workflow_process(contract_id, workflow_process_payload(**overrides), BA)
    )
    get_success_data(api_client.map_process(wp["id"], BA))
    get_success_data(api_client.submit_process_review(wp["id"], BA))
    return get_success_data(api_client.approve_process(wp["id"], AGENCY_PM))


def propose_go_live(contract_id, planned_date=None):
    payload = go_live_payload()
    if planned_date is not None:
        payload["planned_date"] = planned_date
    return get_success_data(api_client.create_go_live_event(contract_id, payload, IMPL))


def readiness_check(event_id):
    return get_success_data(api_client.readiness_check(event_id, IMPL))


def approve_go_live(event_id, user_id="agency-pm-9"):
    return get_success_data(
        api_client.approve_go_live(event_id, make_headers(user_id, "AgencyProjectManager"))
    )


def setup_green_contract(planned_date="2026-12-01"):
    """Contract with 1 accepted milestone, 1 accepted batch, 1 certified interface,
    1 passed UAT cycle, 1 approved process, and a PROPOSED go-live event.
    Returns a context dict."""
    reset_clock()
    ctx = create_contract_in_implementation(num_phases=1)
    contract = ctx["contract"]
    agency = ctx["agency"]
    phase = ctx["phases"][0]
    ctx["milestone"] = create_accepted_milestone(phase["id"], code="M1")
    ctx["batch"] = create_accepted_batch(contract["id"])
    ctx["interface"], ctx["certification"] = create_certified_interface(contract["id"])
    ctx["uat_cycle"] = create_passed_uat_cycle(contract["id"], agency["id"])
    ctx["process"] = create_approved_process(contract["id"])
    ctx["go_live"] = propose_go_live(contract["id"], planned_date=planned_date)
    return ctx


def setup_approved_go_live(planned_date="2026-12-01"):
    ctx = setup_green_contract(planned_date=planned_date)
    ctx["go_live"] = readiness_check(ctx["go_live"]["id"])
    ctx["go_live"] = approve_go_live(ctx["go_live"]["id"])
    return ctx


def execute_go_live(event_id, planned_date="2026-12-01"):
    reset_clock(f"{planned_date}T00:00:00Z")
    return get_success_data(api_client.execute_go_live(event_id, IMPL))


def get_support_transition(contract_id):
    rows, _meta = _list_support(contract_id)
    assert len(rows) == 1, f"Setup failed: expected one SupportTransition, got {len(rows)}"
    return rows[0]


def _list_support(contract_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_support_transitions(contract_id, SUPPORT)
    return validate_paginated(resp)


def setup_executed_go_live(planned_date="2026-12-01"):
    ctx = setup_approved_go_live(planned_date=planned_date)
    ctx["go_live"] = execute_go_live(ctx["go_live"]["id"], planned_date=planned_date)
    ctx["support_transition"] = get_support_transition(ctx["contract"]["id"])
    return ctx


def setup_steady_state_support(planned_date="2026-12-01", after_warranty="2027-03-02"):
    """Executed go-live with SupportTransition advanced WARRANTY -> STABILIZATION
    -> STEADY_STATE (no tickets, so all SLA gates pass)."""
    ctx = setup_executed_go_live(planned_date=planned_date)
    reset_clock(f"{after_warranty}T00:00:00Z")
    st = ctx["support_transition"]
    st = get_success_data(api_client.advance_support_transition(st["id"], SUPPORT))
    st = get_success_data(api_client.advance_support_transition(st["id"], SUPPORT))
    assert st["status"] == "STEADY_STATE", f"Setup failed: support not STEADY_STATE: {st}"
    ctx["support_transition"] = st
    return ctx


def create_active_agreement(contract_id, annual_fee_cents=12_000_000, coverage_start_on="2027-03-02"):
    ma = get_success_data(
        api_client.create_maintenance_agreement(
            contract_id,
            maintenance_payload(annual_fee_cents=annual_fee_cents, coverage_start_on=coverage_start_on),
            FIN,
        )
    )
    return get_success_data(api_client.activate_agreement(ma["id"], FIN))
