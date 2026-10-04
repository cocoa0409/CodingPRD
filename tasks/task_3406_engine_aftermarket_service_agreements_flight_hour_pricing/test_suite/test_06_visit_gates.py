"""Shop-visit induction gates (agreement state, daily capacity) and completion
gates (compliance gate order, approved-workscope requirement, open
requisitions), plus the calendar-based forecast variant."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_enrolled_engine,
    setup_enrolled_engines,
    setup_scheduled_visit,
    setup_inducted_visit,
    setup_submitted_workscope,
    setup_approved_workscope,
    setup_completed_visit,
    create_directive,
    create_visit,
    create_requisition,
    create_workscope_version,
    approve_workscope,
    reject_workscope,
    complete_visit,
    induct_visit,
    get_shop_visit,
    open_renegotiation,
    set_clock,
    workscope_item,
    TEST_USERS,
)


def test_induct_gated_by_agreement_status(api, shop_planner_headers):
    """PRD §3.5: "its enrolled agreement must be `ACTIVE` — induction is one
    of the operations blocked during `RENEGOTIATION`, failing with
    `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/induct_gated_by_agreement_status
    """
    fx = setup_enrolled_engine(
        esn="ESN-M301",
        operator_overrides={"name": "Mountain Air", "iata_code": "MC"},
        agreement_overrides={"contract_ref": "LTSA-M13"},
    )
    fx = setup_scheduled_visit(fx)
    open_renegotiation(fx["agreement"])

    res = api.induct_shop_visit(fx["visit"]["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    visit_after = get_shop_visit(fx["visit"]["id"])
    assert visit_after["status"] == "SCHEDULED", (
        "a rejected induction must leave the visit SCHEDULED"
    )


def test_shop_daily_induction_capacity(api, shop_planner_headers):
    """PRD §3.5: "The shop also enforces an aggregate daily capacity across
    all visits regardless of agreement or operator: if the number of visits
    already in `INDUCTED` status whose `actual_induction_date` equals the
    current logical-clock date has reached 2, the induction is rejected with
    `ERR_SHOP_CAPACITY_EXCEEDED` — at most 2 engines can be inducted on a
    single logical-clock day."
    PRD §3.5: "A successful induction stamps `actual_induction_date` with the
    logical clock, moves the visit to `INDUCTED`".

    The first two 2026-09-01 inductions succeed, the third is rejected, and
    advancing the clock one day releases the capacity.

    Design: Difficulty/resource_temporal_overlap/shop_daily_induction_capacity
    """
    fx = setup_enrolled_engines(
        [{"esn": "ESN-Q601"}, {"esn": "ESN-Q602"}, {"esn": "ESN-Q603"}],
        operator_overrides={"name": "Quarry Air", "iata_code": "QF"},
        agreement_overrides={"contract_ref": "LTSA-Q16"},
    )
    visits = [create_visit(e, fx["operator_headers"]) for e in fx["engines"]]

    v1 = induct_visit(visits[0])
    assert v1["status"] == "INDUCTED"
    v2 = induct_visit(visits[1])
    assert v2["status"] == "INDUCTED"

    res = api.induct_shop_visit(visits[2]["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_SHOP_CAPACITY_EXCEEDED.value)

    set_clock("2026-09-02T00:00:00Z")
    v3 = validate_success(
        api.induct_shop_visit(visits[2]["id"], shop_planner_headers), 200
    )
    assert v3["status"] == "INDUCTED"
    assert v3["actual_induction_date"].startswith("2026-09-02")


def test_complete_safety_beats_referential(api, shop_planner_headers):
    """PRD §2.8: "When several checks could fail on the same request, the
    system evaluates them in a fixed priority order and surfaces the
    **first** failing check's error; later checks are not evaluated." — the
    airworthiness compliance gate (tier 7) runs before the cross-entity
    referential rules (tier 9).
    PRD §3.5: "first, every due mandatory directive applicable to the engine's
    model must be incorporated into an `APPROVED` workscope of this visit —
    if any due mandatory directive is missing, completion is rejected with
    `ERR_MANDATORY_DIRECTIVE_OPEN`".
    PRD §3.6 (step 1): "its `compliance_date`, when non-null, is on or before
    the logical clock plus 18 months".

    At creation (clock 2026-09-01) the directive's compliance_date 2028-06-01
    is after 2026-09-01 + 18 months = 2028-03-01, so it is NOT due and is
    never appended (total stays 300000.00). After the clock advances to
    2028-01-01 the bound becomes 2028-06-01 <= 2029-07-01, so the directive
    is due; the visit also has an open REQUESTED requisition, but only the
    safety error may surface.

    Design: Difficulty/priority_pair_validation_conflict/complete_safety_beats_referential
    """
    fx = setup_enrolled_engine(
        esn="ESN-K801",
        operator_overrides={"name": "Kestrel Air", "iata_code": "KH"},
        agreement_overrides={"contract_ref": "LTSA-K10",
                             "end_date": "2030-08-31T00:00:00Z"},
    )
    create_directive(
        directive_ref="AD-2026-0200",
        mandatory=True,
        estimated_cost_usd=100000,
        compliance_cycles=None,
        compliance_date="2028-06-01T00:00:00Z",
    )
    fx = setup_inducted_visit(fx)
    workscope = create_workscope_version(
        fx["visit"]["id"],
        items=[workscope_item(item_code="MO-1", estimated_cost_usd=300000,
                              restores_cycles=8000)],
    )
    assert workscope["total_cost_usd"] == pytest.approx(300000.00, abs=0.01)
    approve_workscope(workscope, fx["operator_headers"])
    create_requisition(workscope, part_number="PN-K1", list_price_usd=1000,
                       requested_class="NEW",
                       required_by_date="2026-10-01T00:00:00Z")

    set_clock("2028-01-01T00:00:00Z")
    res = api.complete_shop_visit(fx["visit"]["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_MANDATORY_DIRECTIVE_OPEN.value)


def test_visit_complete_twice_rejected(api, shop_planner_headers):
    """PRD §3.5: "A `ShopPlanner` completes an `INDUCTED` visit; completing
    from any other status fails the state tier with `ERR_INVALID_STATE`."
    PRD §3.5: "when an `APPROVED` workscope exists, the engine's
    `llp_remaining_cycles` becomes the larger of its current value and that
    workscope's `restores_llp_cycles`".

    Restoration arithmetic: max(3000, 8000) = 8000.

    Design: Corner/state_machines/visit_complete_twice_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-S301",
        llp_remaining_cycles=3000,
        agreement_overrides={"contract_ref": "LTSA-C601"},
    )
    fx = setup_completed_visit(
        fx,
        items=[workscope_item(item_code="LLP-1", item_type="LLP_REPLACEMENT",
                              estimated_cost_usd=400000, restores_cycles=8000)],
    )
    assert fx["visit"]["status"] == "COMPLETED"
    engine = validate_success(
        api.get_engine(fx["engine"]["id"], TEST_USERS["shop_planner_headers"]),
        200,
    )
    assert engine["status"] == "IN_SERVICE"
    assert engine["llp_remaining_cycles"] == 8000

    res = api.complete_shop_visit(fx["visit"]["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_without_approved_workscope_rejected(api, shop_planner_headers):
    """PRD §3.5: "second, an `APPROVED` workscope must exist for the visit at
    all, else `ERR_NO_APPROVED_WORKSCOPE`."

    No directives exist, so the first compliance-gate step passes vacuously;
    the visit's only workscope was REJECTED.

    Design: Corner/validations/complete_without_approved_workscope_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-U201", agreement_overrides={"contract_ref": "LTSA-V3201"}
    )
    fx = setup_submitted_workscope(fx)
    reject_workscope(fx["workscope"], fx["operator_headers"])

    res = api.complete_shop_visit(fx["visit"]["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_NO_APPROVED_WORKSCOPE.value)


def test_complete_with_open_requisition_rejected(api, shop_planner_headers):
    """PRD §3.5: "no part requisition belonging to any non-`SUPERSEDED`
    workscope of the visit may still be open — any requisition still
    `REQUESTED` or `ESCALATED` blocks completion with
    `ERR_OPEN_REQUISITIONS`."

    The workscope is APPROVED (safety gate passes); its requisition stays
    REQUESTED.

    Design: Corner/validations/complete_with_open_requisition_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-U301", agreement_overrides={"contract_ref": "LTSA-V3301"}
    )
    fx = setup_approved_workscope(fx)
    create_requisition(fx["workscope"], part_number="PN-U3", list_price_usd=5000,
                       requested_class="NEW",
                       required_by_date="2026-10-01T00:00:00Z")

    res = api.complete_shop_visit(fx["visit"]["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_OPEN_REQUISITIONS.value)


def test_forecast_calendar_variant_when_cycles_far(api):
    """PRD §3.5: "The **calendar-based** forecast is insensitive to
    utilization: it takes the `completion_date` of the engine's most recent
    `COMPLETED` shop visit — or the engine's `created_at` if the engine has
    never completed a visit — and adds a fixed interval of 72 months."
    PRD §3.5: "The visit's `forecast_induction_date` is the earlier of the two
    dates, and `forecast_method` records which variant produced it:
    `CYCLE_BASED` when the cycle-based date is earlier or the two coincide
    exactly (ties always go to the cycle-based view), otherwise
    `CALENDAR_BASED`."

    Arithmetic: cycle-based = logical clock 2026-09-01 +
    floor(100000/100 * 30) = +30000 days (decades out), so min() selects the
    calendar variant: engine created 2026-09-01 + 72 months = 2032-09-01.

    Design: Corner/calculations/forecast_calendar_variant_when_cycles_far
    """
    fx = setup_enrolled_engine(
        esn="ESN-F101",
        llp_remaining_cycles=100000,
        assumed_cycles_per_month=100,
        operator_overrides={"name": "Falcon Air", "iata_code": "FA"},
        agreement_overrides={"contract_ref": "LTSA-C801"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2027-01-01T00:00:00Z")
    assert visit["forecast_method"] == "CALENDAR_BASED"
    assert visit["forecast_induction_date"].startswith("2032-09-01")
