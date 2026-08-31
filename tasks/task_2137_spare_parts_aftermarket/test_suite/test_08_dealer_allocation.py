"""The dealer allocation waterfall, its compensating withdrawal edge and the
entitlement invariant that ties them together."""

from test_helpers import (
    ApiErrorId, adjust_balance, allocate_campaign, api_client, approve_campaign,
    assert_allocation_request, assert_campaign,
    assert_campaign_entitlement_conserved, close_campaign,
    create_allocation_request, create_allocation_request_payload,
    create_applicability, create_campaign_for, create_dealer,
    create_equipment_model, create_forecast, create_installed_unit, create_part,
    campaign_version, make_dealer_headers, phase_out_part,
    read_allocation_request, read_campaign, read_dealer, read_part, set_clock,
    setup_approved_campaign, submit_campaign, TEST_USERS, validate_error,
    validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _granted_campaign():
    """A PLATINUM dealer granted all 60 of the 100 units it asked for, leaving the
    campaign in ALLOCATING with 40 remaining."""
    scenario = setup_approved_campaign(
        part_number="ENT-1", approved_qty=100, campaign_method="FLAT_RATE",
        coverage_years=5, unit_cost_cents=1000, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-ENT", dealer_tier="PLATINUM",
        dealer_region="EU", model_code="EM-ENT", serial_prefix="SN-ENT",
        installed_units=0, price_rules=())
    scenario["request"] = create_allocation_request(
        scenario["campaign"]["id"], scenario["dealer"]["id"], 60)
    allocate_campaign(scenario["campaign"]["id"])
    return scenario


def test_waterfall_grants_all_sixty_units_and_leaves_forty_remaining(api):
    """PRD 3.8: "The award itself runs in two passes. The first pass is an equal fair
    share, computed as half of the campaign's `approved_qty` divided by the number of
    candidates and rounded **down** to a whole unit; each candidate is granted the
    smaller of its `requested_units` and that fair share. Whatever of `approved_qty` is
    left after the first pass then flows down the sort order in a strict waterfall: each
    candidate in turn takes the smaller of its own unmet request and the units still
    unallocated, until either every request is satisfied or nothing remains."
    PRD 3.8: "The campaign's `remaining_qty` becomes whatever is still unallocated
    after the second pass, and the invariant to hold at all times is that `approved_qty`
    equals `remaining_qty` plus the sum of `granted_units` across every request now in
    `GRANTED` or `PARTIALLY_GRANTED`."
    PRD 3.8: "Its `priority_score` is then a tier weight — 50 for `PLATINUM`, 30 for
    `GOLD`, 10 for `SILVER` — plus an installed-base weight, which is three points for
    every complete pair of covered machines the dealer owns (that is, the dealer's
    covered machine count halved and rounded down, then multiplied by three) capped at
    30 points, minus a penalty of 20 points when the dealer's `credit_hold` is true,
    with the whole expression floored at 0."

    Design: Difficulty/compensating_invariant/campaign_entitlement_conservation_grant_then_withdraw
    """
    scenario = _granted_campaign()

    request = read_allocation_request(scenario["request"]["id"])
    assert_allocation_request(request)
    assert request["status"] == "GRANTED"
    assert request["granted_units"] == 60
    assert request["priority_score"] == 50
    assert request["dealer_installed_units"] == 0

    campaign = read_campaign(scenario["campaign"]["id"])
    assert campaign["remaining_qty"] == 40
    assert campaign["approved_qty"] == 100
    assert_campaign_entitlement_conserved(campaign, [request])


def test_withdrawing_a_grant_returns_the_units_to_the_campaign(api):
    """PRD 3.8: "A request in `GRANTED` or `PARTIALLY_GRANTED` may also be withdrawn,
    but only while the campaign is still `ALLOCATING`; doing so adds that request's
    `granted_units` back to the campaign's `remaining_qty`, resets the request's
    `granted_units` to 0, moves it to `WITHDRAWN`, and advances the campaign's
    `version`."
    PRD 3.8: "the invariant to hold at all times is that `approved_qty` equals
    `remaining_qty` plus the sum of `granted_units` across every request now in
    `GRANTED` or `PARTIALLY_GRANTED`."

    Design: Difficulty/compensating_invariant/campaign_entitlement_conservation_grant_then_withdraw
    """
    scenario = _granted_campaign()

    withdrawn = validate_success(api.withdraw_allocation_request(
        scenario["request"]["id"], make_dealer_headers(scenario["dealer"]["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["granted_units"] == 0

    campaign = read_campaign(scenario["campaign"]["id"])
    assert campaign["remaining_qty"] == 100
    assert campaign["approved_qty"] == 100
    assert campaign["status"] == "ALLOCATING", "a withdrawal does not reopen the campaign"
    assert_campaign_entitlement_conserved(campaign, [withdrawn])

    part = read_part(scenario["part"]["id"])
    assert part["lifecycle_state"] == "LTB_OPEN"
    assert part["on_hand_units"] == 0, \
        "allocation entitlement never touches physical stock"


def test_waterfall_ranks_three_dealers_and_partially_grants(api):
    """PRD 3.8: "Each candidate is ranked. Its `dealer_installed_units` is counted as
    the number of installed units belonging to that dealer whose `status` is `ACTIVE`
    and which are covered by an `ACTIVE` applicability row for the campaign's part,
    using exactly the same build-revision coverage predicate as the forecasting
    installed-base leg."
    PRD 3.8: "Its `priority_score` is then a tier weight — 50 for `PLATINUM`, 30 for
    `GOLD`, 10 for `SILVER` — plus an installed-base weight, which is three points for
    every complete pair of covered machines the dealer owns (that is, the dealer's
    covered machine count halved and rounded down, then multiplied by three) capped at
    30 points, minus a penalty of 20 points when the dealer's `credit_hold` is true,
    with the whole expression floored at 0."
    PRD 3.8: "The award itself runs in two passes. The first pass is an equal fair
    share, computed as half of the campaign's `approved_qty` divided by the number of
    candidates and rounded **down** to a whole unit; each candidate is granted the
    smaller of its `requested_units` and that fair share."
    PRD 3.8: "A candidate ending with a grant equal to its `requested_units` moves from
    `PENDING` to `GRANTED`; one ending with a grant above 0 but below its request moves
    to `PARTIALLY_GRANTED`; one ending with nothing moves to `DENIED`."

    Design: Corner/calculations/allocation_waterfall_ranks_three_dealers_and_partially_grants
    """
    dealer_a = create_dealer("WF-A", "PLATINUM", "NA")
    dealer_b = create_dealer("WF-B", "GOLD", "NA")
    dealer_c = create_dealer("WF-C", "SILVER", "NA", credit_limit_cents=0)
    model = create_equipment_model("EM-T10", "Tamper T10")
    for index, owner in enumerate(
            [dealer_a, dealer_a, dealer_b, dealer_b, dealer_b, dealer_b,
             dealer_c, dealer_c], start=1):
        create_installed_unit(model["id"], owner["id"],
                              serial_number=f"SN-T1{index:02d}")
    part = create_part(part_number="WF-1", description="Waterfall probe part",
                       unit_cost_cents=1000, lead_time_days=30, weight_kg=1.0)
    create_applicability(part["id"], model["id"], 0, None, 1)
    create_forecast(part["id"], 12, "INSTALLED_BASE_RATE")
    phase_out_part(part["id"])
    campaign = create_campaign_for(part["id"], "FLAT_RATE", 5)
    submit_campaign(campaign["id"])
    approve_campaign(campaign["id"], 100)

    req_a = create_allocation_request(campaign["id"], dealer_a["id"], 60)
    req_b = create_allocation_request(campaign["id"], dealer_b["id"], 50)
    req_c = create_allocation_request(campaign["id"], dealer_c["id"], 40)
    adjust_balance(dealer_c["id"], 100,
                   "debit that pushes WF-C over its zero credit limit")
    assert read_dealer(dealer_c["id"])["credit_hold"] is True

    validate_success(api.allocate_campaign(campaign["id"], CONTROLLER))

    a = read_allocation_request(req_a["id"])
    b = read_allocation_request(req_b["id"])
    c = read_allocation_request(req_c["id"])
    assert (a["priority_score"], a["dealer_installed_units"]) == (53, 2)
    assert (b["priority_score"], b["dealer_installed_units"]) == (36, 4)
    assert (c["priority_score"], c["dealer_installed_units"]) == (0, 2)
    assert (a["granted_units"], a["status"]) == (60, "GRANTED")
    assert (b["granted_units"], b["status"]) == (24, "PARTIALLY_GRANTED")
    assert (c["granted_units"], c["status"]) == (16, "PARTIALLY_GRANTED")

    final = read_campaign(campaign["id"])
    assert final["status"] == "ALLOCATING"
    assert final["remaining_qty"] == 0
    assert_campaign_entitlement_conserved(final, [a, b, c])


def test_allocation_tie_is_broken_by_created_at_ascending(api):
    """PRD 3.8: "Candidates are then ordered by `priority_score` descending, then by
    `requested_units` descending, then by `created_at` ascending; no identifier is ever
    part of the sort key."
    PRD 3.8: "Whatever of `approved_qty` is left after the first pass then flows down
    the sort order in a strict waterfall: each candidate in turn takes the smaller of
    its own unmet request and the units still unallocated, until either every request is
    satisfied or nothing remains."

    Design: Corner/calculations/allocation_tie_broken_by_created_at_ascending
    """
    dealer_a = create_dealer("TIE-A", "GOLD", "EU")
    dealer_b = create_dealer("TIE-B", "GOLD", "EU")
    part = create_part(part_number="TIE-1", description="Tie-break probe",
                       unit_cost_cents=1000, lead_time_days=30, weight_kg=1.0)
    create_forecast(part["id"], 12, "INSTALLED_BASE_RATE")
    phase_out_part(part["id"])
    campaign = create_campaign_for(part["id"], "FLAT_RATE", 3)
    submit_campaign(campaign["id"])
    approve_campaign(campaign["id"], 10)

    earlier = create_allocation_request(campaign["id"], dealer_a["id"], 8)
    set_clock("2026-08-02T00:00:00Z")
    later = create_allocation_request(campaign["id"], dealer_b["id"], 8)

    validate_success(api.allocate_campaign(campaign["id"], CONTROLLER))

    first = read_allocation_request(earlier["id"])
    second = read_allocation_request(later["id"])
    assert first["priority_score"] == 30 and first["dealer_installed_units"] == 0
    assert second["priority_score"] == 30 and second["dealer_installed_units"] == 0
    assert (first["granted_units"], first["status"]) == (8, "GRANTED")
    assert (second["granted_units"], second["status"]) == (2, "PARTIALLY_GRANTED")

    final = read_campaign(campaign["id"])
    assert final["remaining_qty"] == 0
    assert_campaign_entitlement_conserved(final, [first, second])


def test_campaign_close_locks_the_award_and_moves_the_part_to_ltb_closed(api):
    """PRD 3.8: "Closing the campaign moves it from `ALLOCATING` to `CLOSED`. Every
    request on it still in `PENDING` is moved to `DENIED`, and the part moves from
    `LTB_OPEN` to `LTB_CLOSED` — which, being a lifecycle change, re-prices the part at
    the fifteen-point `LTB_CLOSED` scarcity uplift and re-quotes every open line on it,
    exactly as the earlier lifecycle hops did."
    PRD 3.5: "A **cascaded** re-price — one triggered by a change of the part's
    `lifecycle_state` rather than by a client request — is a no-op when no active rule
    matches the band: `current_effective_uplift_pct` and `current_list_unit_price_cents`
    keep whatever values they already held, and no error is raised."

    Design: Corner/state_machines/campaign_close_denies_pending_allocation_requests
    """
    scenario = setup_approved_campaign(
        part_number="CLOSE-1", approved_qty=20, campaign_method="FLAT_RATE",
        coverage_years=3, unit_cost_cents=100, lead_time_days=5, weight_kg=0.1,
        dealer_code="D-CL1", model_code="EM-CL1", serial_prefix="SN-CL1",
        installed_units=0, price_rules=())
    request = create_allocation_request(
        scenario["campaign"]["id"], scenario["dealer"]["id"], 5)
    allocate_campaign(scenario["campaign"]["id"])

    closed = validate_success(api.close_campaign(scenario["campaign"]["id"],
                                                 CONTROLLER))
    assert_campaign(closed)
    assert closed["status"] == "CLOSED"
    assert closed["remaining_qty"] == 15

    granted = read_allocation_request(request["id"])
    assert granted["status"] == "GRANTED", "an awarded request is untouched by the close"
    assert granted["granted_units"] == 5
    assert_campaign_entitlement_conserved(closed, [granted])

    part = read_part(scenario["part"]["id"])
    assert part["lifecycle_state"] == "LTB_CLOSED"
    assert part["current_list_unit_price_cents"] == 0, \
        "no active rule was ever published, so the cascaded re-price is a no-op"


def test_withdrawing_twice_is_refused_and_does_not_double_credit(api):
    """PRD 3.8: "Withdrawing a request already in `DENIED` or `WITHDRAWN`, or
    withdrawing a granted request when the campaign is not `ALLOCATING`, is refused with
    `ERR_ALLOCATION_STATE_INVALID`."
    PRD 3.8: "A request in `GRANTED` or `PARTIALLY_GRANTED` may also be withdrawn, but
    only while the campaign is still `ALLOCATING`; doing so adds that request's
    `granted_units` back to the campaign's `remaining_qty`, resets the request's
    `granted_units` to 0, moves it to `WITHDRAWN`, and advances the campaign's
    `version`."

    Design: Corner/state_machines/allocation_request_withdraw_twice_returns_allocation_state_invalid
    """
    scenario = setup_approved_campaign(
        part_number="WD2-1", approved_qty=100, campaign_method="FLAT_RATE",
        coverage_years=3, unit_cost_cents=100, lead_time_days=5, weight_kg=0.1,
        dealer_code="D-WD2", dealer_tier="PLATINUM", dealer_region="EU",
        model_code="EM-WD2", serial_prefix="SN-WD2", installed_units=0,
        price_rules=())
    dealer_headers = make_dealer_headers(scenario["dealer"]["id"])
    request = create_allocation_request(
        scenario["campaign"]["id"], scenario["dealer"]["id"], 60)
    allocate_campaign(scenario["campaign"]["id"])
    validate_success(api.withdraw_allocation_request(request["id"], dealer_headers))

    resp = api.withdraw_allocation_request(request["id"], dealer_headers)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_STATE_INVALID.value)

    settled = read_allocation_request(request["id"])
    assert settled["status"] == "WITHDRAWN"
    assert settled["granted_units"] == 0
    assert read_campaign(scenario["campaign"]["id"])["remaining_qty"] == 100, \
        "the second withdrawal must not credit the entitlement again"


def test_allocation_request_over_the_remaining_entitlement_is_rejected(api):
    """PRD 3.8: "The campaign must be in `APPROVED`, the dealer must not be on credit
    hold, and `requested_units` may not exceed the campaign's current `remaining_qty` at
    the moment the request is created — an over-ask is refused with
    `ERR_ALLOCATION_EXCEEDS_REMAINING`."

    Design: Corner/validations/allocation_request_exceeding_remaining_qty_is_rejected
    """
    scenario = setup_approved_campaign(
        part_number="EXC-1", approved_qty=10, campaign_method="FLAT_RATE",
        coverage_years=3, unit_cost_cents=100, lead_time_days=5, weight_kg=0.1,
        dealer_code="D-EXC", model_code="EM-EXC", serial_prefix="SN-EXC",
        installed_units=0, price_rules=())
    campaign_id = scenario["campaign"]["id"]
    before = read_campaign(campaign_id)

    resp = api.create_allocation_request(create_allocation_request_payload(
        campaign_id, scenario["dealer"]["id"], 20, before["version"]),
        make_dealer_headers(scenario["dealer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_REMAINING.value)

    after = read_campaign(campaign_id)
    assert after["remaining_qty"] == 10
    assert after["version"] == before["version"], \
        "a rejected create performs no mutation, so version must not advance"
    _, meta = validate_paginated(api.list_allocation_requests(
        PLANNER, params={"campaign_id": campaign_id}))
    assert meta["total_count"] == 0


def test_allocation_run_without_eligible_requests_is_rejected(api):
    """PRD 3.8: "Running the allocation moves the campaign from `APPROVED` to
    `ALLOCATING`, and it requires at least one request on the campaign that is `PENDING`
    and whose dealer's `status` is `ACTIVE`; with no such request the run is refused with
    `ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS` and the campaign stays in `APPROVED`."

    Design: Corner/validations/allocate_with_no_eligible_requests_is_rejected
    """
    scenario = setup_approved_campaign(
        part_number="NOEL-1", approved_qty=25, campaign_method="FLAT_RATE",
        coverage_years=3, unit_cost_cents=100, lead_time_days=5, weight_kg=0.1,
        dealer_code="D-NOEL", model_code="EM-NOEL", serial_prefix="SN-NOEL",
        installed_units=0, price_rules=())

    resp = api.allocate_campaign(scenario["campaign"]["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS.value)

    campaign = read_campaign(scenario["campaign"]["id"])
    assert campaign["status"] == "APPROVED"
    assert campaign["remaining_qty"] == 25
