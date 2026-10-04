"""Regulated-substance phase-out programs (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_component,
    advance_phase_out,
    create_formulation,
    create_jurisdiction,
    create_phase_out_program,
    create_substance,
    create_successor_formulation,
    decide_clearance,
    get_clearance,
    get_formulation,
    get_order,
    get_accrual,
    get_phase_out_program,
    qualification_payload,
    record_qualification,
    set_clock,
    setup_phaseout_enforceable_scenario,
    submit_clearance,
    TEST_USERS,
    validate_error,
    validate_success,
)

RM = TEST_USERS["regulatory_manager_headers"]
TE = TEST_USERS["technical_engineer_headers"]


def test_phaseout_qualifying_advance_without_successor_rejected(api):
    """PRD §3.8: "Moving from `REFORMULATING` to `QUALIFYING` requires
    designating the reformulated replacement: the advance payload must carry a
    `successor_formulation_id`, and that successor's own `successor_of_id` must
    resolve to a formulation affected by this program — one containing the
    program's substance at or above the trigger concentration — else the advance
    is rejected with `ERR_PHASEOUT_SUCCESSOR_REQUIRED` (409)."

    Design: Corner/state_machines/phaseout_qualifying_advance_without_successor_rejected
    """
    set_clock()
    sub = create_substance()
    form = create_formulation()
    add_component(form["id"], sub["id"], 5000)
    pop = create_phase_out_program(sub["id"], ["DE"], 1000)
    advance_phase_out(pop["id"])
    assert get_phase_out_program(pop["id"])["status"] == "REFORMULATING"
    resp = api.advance_phase_out_program(pop["id"], {}, RM)
    validate_error(resp, ApiErrorId.ERR_PHASEOUT_SUCCESSOR_REQUIRED)
    after = get_phase_out_program(pop["id"])
    assert after["status"] == "REFORMULATING"
    assert after["successor_formulation_id"] is None


def test_phaseout_enforce_blocked_with_single_qualified_customer(api):
    """PRD §3.8: "Advancing from `QUALIFYING` to `ENFORCED` requires two
    conditions, both reported as `ERR_QUALIFICATION_GATE_UNMET` (409):
    `qualified_customer_count` must be at least 2, and the successor formulation
    must hold a `CLEARED` clearance in every jurisdiction whose `code` appears
    in `jurisdiction_codes`." and "When `samples_passed` is at least 3, the
    customer is qualified".

    Design: Corner/state_machines/phaseout_enforce_blocked_with_single_qualified_customer
    """
    set_clock()
    jur = create_jurisdiction()
    sub = create_substance()
    form = create_formulation()
    add_component(form["id"], sub["id"], 5000)
    pop = create_phase_out_program(sub["id"], ["DE"], 1000)
    advance_phase_out(pop["id"])
    succ = create_successor_formulation(form["id"], product_code="F-100R")
    cls = submit_clearance(succ["id"], jur["id"], "EXEMPT")
    decide_clearance(cls["id"], "CLEARED")
    advance_phase_out(pop["id"], successor_formulation_id=succ["id"])
    record_qualification(pop["id"], "K-1", samples_passed=3)
    assert get_phase_out_program(pop["id"])["qualified_customer_count"] == 1
    blocked = api.advance_phase_out_program(pop["id"], {}, RM)
    validate_error(blocked, ApiErrorId.ERR_QUALIFICATION_GATE_UNMET)
    assert get_phase_out_program(pop["id"])["status"] == "QUALIFYING"
    record_qualification(pop["id"], "K-2", samples_passed=5)
    assert get_phase_out_program(pop["id"])["qualified_customer_count"] == 2
    ok = api.advance_phase_out_program(pop["id"], {}, RM)
    assert validate_success(ok, 200)["status"] == "ENFORCED", (
        "2 qualified customers meets the inclusive gate"
    )


def test_phaseout_enforcement_suspends_clearances(api):
    """PRD §3.8: "First, every `CLEARED` clearance whose formulation is affected
    and whose jurisdiction's `code` appears in `jurisdiction_codes` is suspended
    to `SUSPENDED`, and each suspension decrements its formulation's
    `active_clearance_count` by one; clearances in `SUBMITTED`,
    `CHANGES_REQUESTED`, `SUSPENDED`, or `REJECTED` are untouched, and the
    successor's own clearances are never targeted — the successor is the
    reformulated replacement and is excluded from the affected set by
    construction, since the advance gate required it to be free of the
    trigger."

    Design: Difficulty/transitive_cascade/phaseout_enforce_cascades_clearance_order_accrual
    """
    ctx = setup_phaseout_enforceable_scenario()
    pop_id = ctx["phaseout"]["id"]
    ok = api.advance_phase_out_program(pop_id, {}, RM)
    assert validate_success(ok, 200)["status"] == "ENFORCED"
    cl_after = get_clearance(ctx["clearance"]["id"])
    assert cl_after["status"] == "SUSPENDED"
    form_after = get_formulation(ctx["formulation"]["id"])
    assert form_after["active_clearance_count"] == 0
    succ_cl = get_clearance(ctx["successor_clearance"]["id"])
    assert succ_cl["status"] == "CLEARED", "the successor's own clearances are never targeted"


def test_phaseout_enforcement_flags_orders_and_recomputes_accrual(api):
    """PRD §3.8: "Second, every order on one of those (formulation,
    jurisdiction) pairs whose fulfillment stands `PENDING`, `ALLOCATED`, or
    `SHIPPED` and whose compliance stands `CLEAR` is flagged. Third,
    `excluded_order_count` is recomputed on every rebate accrual touching a
    flagged order."

    Design: Difficulty/transitive_cascade/phaseout_enforce_cascades_clearance_order_accrual
    """
    ctx = setup_phaseout_enforceable_scenario()
    pop_id = ctx["phaseout"]["id"]
    validate_success(api.advance_phase_out_program(pop_id, {}, RM), 200)
    shipped = get_order(ctx["order_shipped"]["id"])
    pending = get_order(ctx["order_pending"]["id"])
    assert shipped["fulfillment_status"] == "SHIPPED"
    assert shipped["compliance_status"] == "FLAGGED"
    assert pending["fulfillment_status"] == "PENDING"
    assert pending["compliance_status"] == "FLAGGED"
    acc = get_accrual(ctx["accrual"]["id"])
    assert acc["excluded_order_count"] == 1, "only the SHIPPED flagged order counts"
    assert acc["provisional_amount_cents"] == 1000, (
        "the provisional variant still includes the flagged shipped order"
    )
