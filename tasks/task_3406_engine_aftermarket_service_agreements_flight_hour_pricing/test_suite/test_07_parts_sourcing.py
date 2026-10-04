"""Parts sourcing: class eligibility and fallback, escalation + manager
override, the directive-reopen cascade onto requisitions, and the
committed-parts-cost invariant across supersede."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_enrolled_engine,
    setup_approved_workscope,
    create_directive,
    create_requisition,
    source_requisition,
    create_workscope_version,
    get_workscope,
    get_shop_visit,
    workscope_item,
)


def test_directive_issue_to_requisition_cancel_chain(api, shop_planner_headers):
    """PRD §3.6: "On an `APPROVED` workscope of such a visit, the approved
    baseline is instead protected: the workscope transitions from `APPROVED`
    to `REOPENED` with its items left untouched, every requisition of that
    workscope still `REQUESTED` or `ESCALATED` is set to `CANCELLED` (each
    incrementing its own `version`), and the workscope's `version`
    increments."
    PRD §3.6 (step 1): a directive is due when "its `compliance_cycles`, when
    non-null, is at most the engine's `llp_remaining_cycles` plus a buffer of
    18 months' worth of assumed cycles" — here 50 <= 8000 + 18*100 = 9800.

    Design: Difficulty/transitive_cascade/directive_issue_to_requisition_cancel_chain
    """
    fx = setup_enrolled_engine(
        esn="ESN-H801",
        base_severity_tier="BENIGN",
        agreement_overrides={
            "contract_ref": "LTSA-H08",
            "allowed_sourcing_classes": ["NEW", "REPAIRED", "USM"],
            "max_workscope_cost_usd": 2000000,
        },
    )
    fx = setup_approved_workscope(
        fx,
        items=[workscope_item(item_code="MO-1", estimated_cost_usd=300000,
                              restores_cycles=8000)],
    )
    create_requisition(fx["workscope"], part_number="PN-H1", quantity=1,
                       list_price_usd=50000, requested_class="NEW",
                       required_by_date="2026-10-01T00:00:00Z")

    create_directive(directive_ref="AD-2026-0113", mandatory=True,
                     estimated_cost_usd=400000, compliance_cycles=50)

    w_after = get_workscope(fx["workscope"]["id"])
    assert w_after["status"] == "REOPENED"
    assert w_after["total_cost_usd"] == pytest.approx(300000.00, abs=0.01), (
        "REOPENED preserves the approved item set; nothing is appended"
    )
    reqs, _ = validate_paginated(
        api.list_workscope_part_requisitions(fx["workscope"]["id"],
                                             shop_planner_headers))
    assert reqs[0]["status"] == "CANCELLED"


def test_committed_parts_cost_conserved_across_supersede(api, shop_planner_headers):
    """PRD §3.7: "the visit's `committed_parts_cost_usd` is the sum of
    `quantity` multiplied by `unit_cost_usd` over all `SOURCED` requisitions
    belonging to any non-`SUPERSEDED` workscope of the visit, so it rises as
    requisitions source and falls back when a supersede cascade releases
    them".
    PRD §3.6: "Cancelling a `SOURCED` requisition releases committed money:
    the visit's `committed_parts_cost_usd` decreases by that requisition's
    `quantity` multiplied by its `unit_cost_usd`."

    Arithmetic: requested USM is allowed and its 3-day lead fits
    (2026-09-01 + 3d <= 2026-09-20); unit cost = round2(10000.00 * 0.45) =
    4500.00; committed = 2 * 4500.00 = 9000.00, released back to 0.00 when
    the next workscope version supersedes the approved one.

    Design: Difficulty/compensating_invariant/committed_parts_cost_conserved_across_supersede
    """
    fx = setup_enrolled_engine(
        esn="ESN-S801",
        base_severity_tier="BENIGN",
        agreement_overrides={
            "contract_ref": "LTSA-S18",
            "allowed_sourcing_classes": ["NEW", "REPAIRED", "USM"],
            "max_workscope_cost_usd": 2000000,
        },
    )
    fx = setup_approved_workscope(
        fx,
        items=[workscope_item(item_code="MO-1", estimated_cost_usd=300000,
                              restores_cycles=8000)],
    )
    req = create_requisition(fx["workscope"], part_number="PN-S1", quantity=2,
                             list_price_usd=10000, requested_class="USM",
                             required_by_date="2026-09-20T00:00:00Z")

    visit_pre = get_shop_visit(fx["visit"]["id"])
    assert visit_pre["committed_parts_cost_usd"] == pytest.approx(0.00, abs=0.001)

    sourced = source_requisition(req)
    assert sourced["status"] == "SOURCED"
    assert sourced["sourced_class"] == "USM"
    assert sourced["unit_cost_usd"] == pytest.approx(4500.00, abs=0.001)

    visit_mid = get_shop_visit(fx["visit"]["id"])
    assert visit_mid["committed_parts_cost_usd"] == pytest.approx(9000.00, abs=0.01)

    w2 = create_workscope_version(
        fx["visit"]["id"],
        items=[workscope_item(item_code="MO-2", estimated_cost_usd=350000,
                              restores_cycles=8000)],
    )
    assert w2["scope_version"] == 2

    visit_post = get_shop_visit(fx["visit"]["id"])
    assert visit_post["committed_parts_cost_usd"] == pytest.approx(0.00, abs=0.001)

    w1_after = get_workscope(fx["workscope"]["id"])
    assert w1_after["status"] == "SUPERSEDED"
    reqs, _ = validate_paginated(
        api.list_workscope_part_requisitions(fx["workscope"]["id"],
                                             shop_planner_headers))
    assert reqs[0]["status"] == "CANCELLED"


def test_sourcing_falls_back_to_cheapest_allowed(api):
    """PRD §3.7: "Otherwise, if any class is eligible, the eligible class with
    the lowest unit cost is chosen" and "the candidate unit cost for a class
    is the requisition's `list_price_usd` multiplied by the class factor,
    rounded half-up to 2 decimal places."

    Arithmetic: requested USM is not in the agreement's allowed
    [NEW, REPAIRED]; NEW (1.00 -> 10000.00) and REPAIRED (0.70 -> 7000.00)
    both fit the 2026-10-15 required-by date (leads 7d and 21d from
    2026-09-01), so the cheapest eligible class wins: REPAIRED at 7000.00.

    Design: Corner/calculations/sourcing_falls_back_to_cheapest_allowed
    """
    fx = setup_enrolled_engine(
        esn="ESN-G101",
        agreement_overrides={"contract_ref": "LTSA-C1101",
                             "allowed_sourcing_classes": ["NEW", "REPAIRED"]},
    )
    fx = setup_approved_workscope(fx)
    req = create_requisition(fx["workscope"], part_number="PN-G1", quantity=1,
                             list_price_usd=10000, requested_class="USM",
                             required_by_date="2026-10-15T00:00:00Z")

    sourced = source_requisition(req)
    assert sourced["status"] == "SOURCED"
    assert sourced["sourced_class"] == "REPAIRED"
    assert sourced["unit_cost_usd"] == pytest.approx(7000.00, abs=0.001)


def test_sourcing_escalation_then_manager_override(api, shop_planner_headers):
    """PRD §3.7: "Otherwise no class can serve the demand: the requisition
    transitions from `REQUESTED` to `ESCALATED`, its `version` increments, and
    the request is rejected with `ERR_NO_ELIGIBLE_SOURCING_CLASS`."
    PRD §3.7: "If the request carries `override` set to true — permitted only
    to a `ContractManager` — the selector chooses the cheapest class in
    `allowed_sourcing_classes` by unit cost, bypassing the lead-time check
    entirely; the allowed-class list itself is never bypassed."

    Arithmetic: the only allowed class is REPAIRED with a 21-day lead;
    2026-09-01 + 21d = 2026-09-22 is after required_by 2026-09-10, so the
    plain run escalates. The override sources REPAIRED at
    round2(10000.00 * 0.70) = 7000.00.

    Design: Corner/calculations/sourcing_escalation_then_manager_override
    """
    fx = setup_enrolled_engine(
        esn="ESN-G201",
        agreement_overrides={"contract_ref": "LTSA-C1201",
                             "allowed_sourcing_classes": ["REPAIRED"]},
    )
    fx = setup_approved_workscope(fx)
    req = create_requisition(fx["workscope"], part_number="PN-G2", quantity=1,
                             list_price_usd=10000, requested_class="REPAIRED",
                             required_by_date="2026-09-10T00:00:00Z")

    res = api.source_part_requisition(req["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_SOURCING_CLASS.value)
    reqs, _ = validate_paginated(
        api.list_workscope_part_requisitions(fx["workscope"]["id"],
                                             shop_planner_headers))
    assert reqs[0]["status"] == "ESCALATED"

    sourced = source_requisition(req, override=True)
    assert sourced["status"] == "SOURCED"
    assert sourced["sourced_class"] == "REPAIRED"
    assert sourced["unit_cost_usd"] == pytest.approx(7000.00, abs=0.001)
