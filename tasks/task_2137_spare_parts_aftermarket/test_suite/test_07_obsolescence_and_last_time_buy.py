"""Phase-out, last-time-buy sizing, the approval cycle, window geometry and the
cascade that a campaign approval sets off."""

from test_helpers import (
    ApiErrorId, add_part_line, api_client, approve_campaign, assert_campaign,
    assert_part, assert_part_line, create_campaign_for, create_campaign_payload,
    create_forecast, create_part_line_payload, create_work_order,
    drive_part_to_obsolete, part_version, phase_out_part, read_campaign,
    read_part, read_part_line, setup_catalogue, submit_campaign, TEST_USERS,
    validate_error, validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _phase_out_part_with_forecast(part_number, stock_units=0, qty_per_unit=50,
                                  installed_units=1, **kwargs):
    """A part with a CURRENT 12-month INSTALLED_BASE_RATE forecast, moved to
    PHASE_OUT."""
    scenario = setup_catalogue(part_number=part_number,
                               installed_units=installed_units,
                               qty_per_unit=qty_per_unit,
                               stock_units=stock_units, **kwargs)
    scenario["forecast"] = create_forecast(scenario["part"]["id"], 12,
                                           "INSTALLED_BASE_RATE")
    phase_out_part(scenario["part"]["id"])
    return scenario


def test_demand_decay_sizing_proposes_seventeen_units(api):
    """PRD 3.8: "Under the `DEMAND_DECAY` variant the fleet is assumed to retire, so
    each successive year's demand is `annual_demand_units` multiplied by a decay factor
    of 0.85 raised to the power of that year's index counted from zero — the first year
    is full demand, the second is 85 percent of it, the third is 85 percent of that,
    and so on for `coverage_years` years."
    PRD 3.8: "The two variants diverge sharply on identical inputs: with an annual
    demand of 10 units, a coverage of 5 years and an existing cover of 20 units, the
    decayed years are 10, 9, 7, 6 and 5 for a total of 37 and a `proposed_qty` of 17,
    whereas the flat-rate requirement is 50 for a `proposed_qty` of 30."
    PRD 3.8: "The campaign snapshots `annual_demand_units` from the `forecast_units` of
    the part's `CURRENT` 12-month forecast, and refuses with `ERR_FORECAST_INPUT_EMPTY`
    when no such forecast exists."

    Design: Difficulty/dual_variant_calc/ltb_decay_vs_flat_quantity_divergence_on_campaign
    """
    scenario = _phase_out_part_with_forecast(
        "LTB-A", stock_units=20, unit_cost_cents=1333, lead_time_days=60,
        weight_kg=12.5, max_stock_units=30, dealer_code="D-GOLD-2",
        dealer_region="EU", model_code="EM-200", serial_prefix="SN-200",
        price_rules=())
    forecast = scenario["forecast"]
    assert forecast["installed_base_units"] == 1
    assert forecast["ib_rate_units"] == 10.00
    assert forecast["forecast_units"] == 10

    campaign = create_campaign_for(scenario["part"]["id"], "DEMAND_DECAY", 5)
    assert_campaign(campaign)
    assert campaign["annual_demand_units"] == 10
    assert campaign["proposed_qty"] == 17
    assert campaign["status"] == "DRAFT"


def test_flat_rate_sizing_proposes_thirty_and_cancels_the_prior_draft(api):
    """PRD 3.8: "Under the `FLAT_RATE` variant the requirement is simply
    `annual_demand_units` multiplied by `coverage_years`, and `proposed_qty` is that
    requirement less the existing cover, floored at 0."
    PRD 3.8: "What the shelf already covers is the part's `on_hand_units` plus its
    `in_transit_units`."
    PRD 3.8: "Any campaign already in `DRAFT` on the same part is moved to `CANCELLED`
    — that superseded draft's `approved_qty` and `remaining_qty` both stay 0, because a
    draft never held an entitlement in the first place."

    Design: Difficulty/dual_variant_calc/ltb_decay_vs_flat_quantity_divergence_on_campaign
    """
    scenario = _phase_out_part_with_forecast(
        "LTB-A", stock_units=20, unit_cost_cents=1333, lead_time_days=60,
        weight_kg=12.5, max_stock_units=30, dealer_code="D-GOLD-2",
        dealer_region="EU", model_code="EM-200", serial_prefix="SN-200",
        price_rules=())
    first = create_campaign_for(scenario["part"]["id"], "DEMAND_DECAY", 5)
    second = create_campaign_for(scenario["part"]["id"], "FLAT_RATE", 5)

    assert second["annual_demand_units"] == 10
    assert second["proposed_qty"] == 30
    assert second["status"] == "DRAFT"

    superseded = read_campaign(first["id"])
    assert superseded["status"] == "CANCELLED"
    assert superseded["approved_qty"] == 0
    assert superseded["remaining_qty"] == 0


def _rejected_campaign():
    scenario = _phase_out_part_with_forecast(
        "CYC-1", unit_cost_cents=1333, lead_time_days=60, weight_kg=12.5,
        dealer_code="D-CYC", dealer_tier="SILVER", dealer_region="APAC",
        model_code="EM-500", serial_prefix="SN-500", price_rules=())
    campaign = create_campaign_for(scenario["part"]["id"], "DEMAND_DECAY", 5)
    assert campaign["proposed_qty"] == 37, "setup precondition"
    submit_campaign(campaign["id"])
    scenario["campaign"] = campaign
    return scenario


def test_campaign_reject_then_revise_returns_to_draft_with_a_new_revision_index(api):
    """PRD 3.8: "Rejecting requires `status` `SUBMITTED` and the same non-self
    constraint; it stores the supplied `rejection_reason`, advances the campaign's
    `version`, and deliberately leaves the part where it was, in `PHASE_OUT`."
    PRD 3.8: "A rejected campaign is not dead. Revising it moves it from `REJECTED`
    back to `DRAFT`, increments `revision_index` by 1, clears both
    `submitted_by_user_id` and `rejection_reason` back to null, re-snapshots
    `annual_demand_units` from the part's `CURRENT` 12-month forecast (refusing with
    `ERR_FORECAST_INPUT_EMPTY` if that forecast has since disappeared) and recomputes
    `proposed_qty`."
    PRD 3.8: "Submitting moves the campaign from `DRAFT` to `SUBMITTED`, requires the
    part to be in `PHASE_OUT`, re-checks both window stages, and stamps
    `submitted_by_user_id` with the caller's `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/ltb_campaign_reject_revise_resubmit_cycle
    """
    scenario = _rejected_campaign()
    campaign_id = scenario["campaign"]["id"]

    submitted = read_campaign(campaign_id)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "planner-1"

    rejected = validate_success(api.reject_campaign(
        campaign_id, "coverage too aggressive", CONTROLLER))
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "coverage too aggressive"

    revised = validate_success(api.revise_campaign(
        campaign_id, {"coverage_years": 3}, PLANNER))
    assert revised["status"] == "DRAFT"
    assert revised["revision_index"] == 1
    assert revised["submitted_by_user_id"] is None
    assert revised["rejection_reason"] is None

    assert read_part(scenario["part"]["id"])["lifecycle_state"] == "PHASE_OUT"


def test_revise_recomputes_proposed_qty_and_resubmission_keeps_the_revision_index(api):
    """PRD 3.8: "The revise request may optionally supply a replacement `method` or
    `coverage_years`. That draft-submit-reject-revise loop can run as many times as
    needed."
    PRD 3.8: "Under the `DEMAND_DECAY` variant the fleet is assumed to retire, so each
    successive year's demand is `annual_demand_units` multiplied by a decay factor of
    0.85 raised to the power of that year's index counted from zero — the first year is
    full demand, the second is 85 percent of it, the third is 85 percent of that, and so
    on for `coverage_years` years. Crucially, **each year's figure is rounded half up to
    a whole unit before it is added into the running total, and the total is never
    re-rounded afterwards.**"
    PRD 3.8: "Submitting moves the campaign from `DRAFT` to `SUBMITTED`, requires the
    part to be in `PHASE_OUT`, re-checks both window stages, and stamps
    `submitted_by_user_id` with the caller's `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/ltb_campaign_reject_revise_resubmit_cycle
    """
    scenario = _rejected_campaign()
    campaign_id = scenario["campaign"]["id"]
    validate_success(api.reject_campaign(campaign_id, "coverage too aggressive",
                                         CONTROLLER))

    revised = validate_success(api.revise_campaign(
        campaign_id, {"coverage_years": 3}, PLANNER))
    assert revised["coverage_years"] == 3
    assert revised["proposed_qty"] == 26, \
        "10 + 9 + 7 with no shelf cover, down from 37 at five years"

    resubmitted = validate_success(api.submit_campaign(campaign_id, PLANNER))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_index"] == 1
    assert read_part(scenario["part"]["id"])["lifecycle_state"] == "PHASE_OUT"


def _cascade_scenario():
    """A RESERVED line for 7 units on a part already re-quoted at the PHASE_OUT
    uplift, with a SUBMITTED campaign waiting for approval."""
    scenario = setup_catalogue(
        part_number="CASC-1", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=12.5, max_stock_units=30, dealer_code="D-CASC",
        model_code="EM-700", serial_prefix="SN-700", qty_per_unit=50,
        stock_units=100, price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_id = scenario["dealer"]["id"]
    wo = create_work_order(scenario["unit"]["id"], dealer_id,
                           "SCHEDULED_MAINTENANCE", "PLANNED")
    line = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], 7)
    create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    phase_out_part(scenario["part"]["id"])
    at_phase_out = read_part_line(line["id"])
    assert at_phase_out["quoted_line_total_cents"] == 12970, "setup precondition"
    campaign = create_campaign_for(scenario["part"]["id"], "DEMAND_DECAY", 5)
    submit_campaign(campaign["id"])
    scenario["work_order"] = wo
    scenario["line"] = line
    scenario["campaign"] = campaign
    return scenario


def test_campaign_approval_moves_the_part_to_ltb_open_and_reprices_it(api):
    """PRD 3.8: "Approving requires `status` `SUBMITTED`, an `approved_qty` of at
    least 1 supplied in the request, and an approver whose `X-User-ID` differs from
    `submitted_by_user_id`. Approval sets `approved_qty`, sets `remaining_qty` equal to
    it, and stamps `approved_by_user_id` — and that first hop causes a chain: the part
    moves from `PHASE_OUT` to `LTB_OPEN`, which causes the part to be re-priced at the
    eight-point `LTB_OPEN` scarcity uplift, which in turn causes every line on that part
    in `REQUESTED`, `RESERVED` or `BACKORDERED` to be re-quoted with all six pricing
    figures changing."
    PRD 3.5: "The part's own catalogue fields are simply this calculation evaluated at
    a quantity of one: `current_effective_uplift_pct` holds the `effective_uplift_pct`
    and `current_list_unit_price_cents` holds the LIST unit price."

    Design: Difficulty/transitive_cascade/ltb_approve_cascades_lifecycle_then_price_then_open_line_requote
    """
    scenario = _cascade_scenario()

    campaign = validate_success(api.approve_campaign(
        scenario["campaign"]["id"], 40, CONTROLLER))
    assert campaign["status"] == "APPROVED"
    assert campaign["approved_qty"] == 40
    assert campaign["remaining_qty"] == 40
    assert campaign["approved_by_user_id"] == "ctrl-1"

    part = read_part(scenario["part"]["id"])
    assert_part(part)
    assert part["lifecycle_state"] == "LTB_OPEN"
    assert part["current_effective_uplift_pct"] == 0.43
    assert part["current_list_unit_price_cents"] == 1906
    assert part["on_hand_units"] == 100
    assert part["allocated_units"] == 7


def test_campaign_approval_requotes_the_open_part_line(api):
    """PRD 3.8: "the part moves from `PHASE_OUT` to `LTB_OPEN`, which causes the part
    to be re-priced at the eight-point `LTB_OPEN` scarcity uplift, which in turn causes
    every line on that part in `REQUESTED`, `RESERVED` or `BACKORDERED` to be re-quoted
    with all six pricing figures changing."
    PRD 3.5: "With the same cost and quantity at an uplift of 0.43, LIST yields 13342
    and QUOTE yields 13343, so the delta flips negative."
    PRD 3.5: "`variant_delta_cents` records the divergence as `list_line_total_cents`
    minus `quoted_line_total_cents`."

    Design: Difficulty/transitive_cascade/ltb_approve_cascades_lifecycle_then_price_then_open_line_requote
    """
    scenario = _cascade_scenario()
    validate_success(api.approve_campaign(scenario["campaign"]["id"], 40, CONTROLLER))

    line = read_part_line(scenario["line"]["id"])
    assert_part_line(line)
    assert line["effective_uplift_pct"] == 0.43
    assert line["list_unit_price_cents"] == 1906
    assert line["list_line_total_cents"] == 13342
    assert line["quoted_line_total_cents"] == 13343
    assert line["variant_delta_cents"] == -1
    assert line["line_status"] == "RESERVED"
    assert line["charged_amount_cents"] == 0, "a re-quote bills nothing"


def test_campaign_submit_refused_while_the_part_is_still_active(api):
    """PRD 3.8: "Submitting moves the campaign from `DRAFT` to `SUBMITTED`, requires
    the part to be in `PHASE_OUT`, re-checks both window stages, and stamps
    `submitted_by_user_id` with the caller's `X-User-ID`."
    PRD 2.10: "The target resource is in a state from which the requested transition
    is declared, including the cross-dimension guard on shipping a replenishment order
    and the cross-entity guards: submitting a campaign requires its part to be in
    `PHASE_OUT`; creating an allocation request requires the campaign to be in
    `APPROVED`; creating a return authorization requires the source line to be in
    `CONSUMED`; approving or receiving a replenishment order requires the part not to
    be `OBSOLETE`; and inspecting a return with a `RESTOCK` disposition requires the
    part not to be `OBSOLETE`."

    Design: Difficulty/cross_entity_state_dependency/campaign_submit_gated_by_part_lifecycle_phase_out
    """
    scenario = setup_catalogue(
        part_number="GATE-1", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=2.0, dealer_code="D-GATE", dealer_tier="SILVER",
        dealer_region="EU", model_code="EM-E10", serial_prefix="SN-E10",
        qty_per_unit=50, price_rules=())
    create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    campaign = create_campaign_for(scenario["part"]["id"], "DEMAND_DECAY", 5)

    assert read_part(scenario["part"]["id"])["lifecycle_state"] == "ACTIVE"
    resp = api.submit_campaign(campaign["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PART_LIFECYCLE_INVALID.value)

    unchanged = read_campaign(campaign["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_by_user_id"] is None


def test_campaign_submit_succeeds_once_the_part_is_phased_out(api):
    """PRD 3.8: "A planner opens the workflow by phasing a part out, moving
    `lifecycle_state` from `ACTIVE` to `PHASE_OUT`; a part in any other state gives
    `ERR_PART_LIFECYCLE_INVALID`."
    PRD 3.8: "Submitting moves the campaign from `DRAFT` to `SUBMITTED`, requires the
    part to be in `PHASE_OUT`, re-checks both window stages, and stamps
    `submitted_by_user_id` with the caller's `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/campaign_submit_gated_by_part_lifecycle_phase_out
    """
    scenario = setup_catalogue(
        part_number="GATE-1", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=2.0, dealer_code="D-GATE", dealer_tier="SILVER",
        dealer_region="EU", model_code="EM-E10", serial_prefix="SN-E10",
        qty_per_unit=50, price_rules=())
    create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    campaign = create_campaign_for(scenario["part"]["id"], "DEMAND_DECAY", 5)
    api.submit_campaign(campaign["id"], PLANNER)

    phased = validate_success(api.phase_out_part(scenario["part"]["id"], PLANNER))
    assert phased["lifecycle_state"] == "PHASE_OUT"

    submitted = validate_success(api.submit_campaign(campaign["id"], PLANNER))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "planner-1"


def _submitted_window_campaign():
    scenario = _phase_out_part_with_forecast(
        "WNDW-1", installed_units=0, qty_per_unit=1, unit_cost_cents=1000,
        lead_time_days=30, weight_kg=1.0, dealer_code="D-WNDW",
        model_code="EM-WND", serial_prefix="SN-WND", price_rules=())
    campaign = create_campaign_for(scenario["part"]["id"], "FLAT_RATE", 5,
                                   "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
    submit_campaign(campaign["id"])
    scenario["campaign"] = campaign
    scenario["part_version"] = part_version(scenario["part"]["id"])
    return scenario


def test_intersecting_last_time_buy_windows_are_rejected(api):
    """PRD 3.8: "The first stage treats the window as **half-open** — inclusive of
    `ltb_window_start`, exclusive of `ltb_window_end` — and refuses any new window that
    intersects an existing one with `ERR_LTB_WINDOW_OVERLAP`."
    PRD 3.8: "Two campaigns on the same part may not compete for the same supplier
    window, and the geometry is checked in two stages against every other campaign on
    that part whose `status` is `SUBMITTED`, `APPROVED` or `ALLOCATING`."

    Design: Difficulty/resource_temporal_overlap/ltb_window_half_open_with_symmetric_thirty_day_cooldown
    """
    scenario = _submitted_window_campaign()

    resp = api.create_campaign(create_campaign_payload(
        scenario["part"]["id"], scenario["part_version"], method="FLAT_RATE",
        coverage_years=5, ltb_window_start="2026-09-15T00:00:00Z",
        ltb_window_end="2026-10-15T00:00:00Z"), PLANNER)
    validate_error(resp, ApiErrorId.ERR_LTB_WINDOW_OVERLAP.value)

    assert read_campaign(scenario["campaign"]["id"])["status"] == "SUBMITTED"
    _, meta = validate_paginated(api.list_campaigns(
        PLANNER, params={"part_id": scenario["part"]["id"]}))
    assert meta["total_count"] == 1


def test_cooldown_buffer_rejects_a_near_window_and_accepts_a_thirty_day_gap(api):
    """PRD 3.8: "The second stage then imposes a symmetric 30-day cooldown buffer on
    the windows that survived: the new window's start must be at least 30 days after the
    other window's end, **or** the new window's end plus 30 days must be at or before
    the other window's start. Anything falling inside that buffer is refused with
    `ERR_LTB_COOLDOWN_VIOLATION`."
    PRD 3.8: "Note the deliberate contrast with the build-revision geometry of section
    3.2: adjacency is accepted there and rejected here. Both stages are applied at draft
    creation and applied again at submission."

    Design: Difficulty/resource_temporal_overlap/ltb_window_half_open_with_symmetric_thirty_day_cooldown
    """
    scenario = _submitted_window_campaign()
    part_id = scenario["part"]["id"]
    version = scenario["part_version"]

    inside_buffer = api.create_campaign(create_campaign_payload(
        part_id, version, method="FLAT_RATE", coverage_years=5,
        ltb_window_start="2026-10-25T00:00:00Z",
        ltb_window_end="2026-11-25T00:00:00Z"), PLANNER)
    validate_error(inside_buffer, ApiErrorId.ERR_LTB_COOLDOWN_VIOLATION.value)

    clear_of_buffer = validate_success(api.create_campaign(create_campaign_payload(
        part_id, version, method="FLAT_RATE", coverage_years=5,
        ltb_window_start="2026-10-31T00:00:00Z",
        ltb_window_end="2026-11-30T00:00:00Z"), PLANNER), 201)
    assert clear_of_buffer["status"] == "DRAFT"

    assert read_campaign(scenario["campaign"]["id"])["status"] == "SUBMITTED", \
        "a new DRAFT never supersedes a SUBMITTED campaign"
    _, meta = validate_paginated(api.list_campaigns(
        PLANNER, params={"part_id": part_id}))
    assert meta["total_count"] == 2


def test_reinstate_blocked_while_a_campaign_is_submitted(api):
    """PRD 3.8: "Phase-out is reversible while nothing has been committed. Reinstating
    a part moves it from `PHASE_OUT` back to `ACTIVE`, but only when no campaign on that
    part is currently `SUBMITTED`, `APPROVED` or `ALLOCATING`; a part not in `PHASE_OUT`,
    or one with a live campaign in any of those three states, gives
    `ERR_PART_LIFECYCLE_INVALID`."

    Design: Corner/state_machines/part_reinstate_blocked_while_campaign_submitted
    """
    scenario = _phase_out_part_with_forecast(
        "RST-1", installed_units=0, qty_per_unit=1, unit_cost_cents=100,
        lead_time_days=5, weight_kg=0.1, dealer_code="D-RST",
        model_code="EM-RST", serial_prefix="SN-RST", price_rules=())
    campaign = create_campaign_for(scenario["part"]["id"], "FLAT_RATE", 3)
    submit_campaign(campaign["id"])

    resp = api.reinstate_part(scenario["part"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PART_LIFECYCLE_INVALID.value)

    assert read_part(scenario["part"]["id"])["lifecycle_state"] == "PHASE_OUT"
    assert read_campaign(campaign["id"])["status"] == "SUBMITTED"


def test_obsolete_part_with_no_supply_cannot_go_on_a_line(api):
    """PRD 3.6: "A part in `OBSOLETE` whose `available_units` has reached 0 cannot be
    put on a line either, giving `ERR_PART_OBSOLETE_NO_SUPPLY`."
    PRD 3.8: "Obsoleting sets `stocking_policy` to `NO_STOCK` and zeroes both
    `safety_stock_units` and `reorder_point_units`; every replenishment order on the
    part whose `approval_status` is still `PENDING` is moved to `approval_status`
    `REJECTED`; `current_list_unit_price_cents` is recomputed at the fifteen-point
    `OBSOLETE` scarcity uplift; and the part's `version` advances."

    Design: Corner/validations/obsolete_part_with_no_stock_cannot_be_put_on_a_line
    """
    scenario = setup_catalogue(
        part_number="OBSL-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-OBSL", model_code="EM-AA1",
        serial_prefix="SN-AA1", qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    drive_part_to_obsolete(scenario, approved_qty=5)

    part = read_part(scenario["part"]["id"])
    assert part["lifecycle_state"] == "OBSOLETE"
    assert part["stocking_policy"] == "NO_STOCK"
    assert part["available_units"] == 0
    assert part["current_effective_uplift_pct"] == 0.50
    assert part["current_list_unit_price_cents"] == 2000

    wo = create_work_order(scenario["unit"]["id"], scenario["dealer"]["id"],
                           "SCHEDULED_MAINTENANCE", "PLANNED")
    resp = api.create_part_line(
        wo["id"], create_part_line_payload(scenario["part"]["id"], 1),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_PART_OBSOLETE_NO_SUPPLY.value)

    _, meta = validate_paginated(api.list_part_lines(
        PLANNER, params={"work_order_id": wo["id"]}))
    assert meta["total_count"] == 0
