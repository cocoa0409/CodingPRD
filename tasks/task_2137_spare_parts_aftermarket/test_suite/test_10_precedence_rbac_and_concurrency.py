"""Validation precedence between rule categories, role-based access control,
dealer scoping, segregation of duties and optimistic concurrency."""

from test_helpers import (
    ApiErrorId, add_part_line, adjust_balance, api_client, approve_campaign,
    campaign_version, create_allocation_request,
    create_allocation_request_payload, create_campaign_for,
    create_campaign_payload, create_dealer, create_forecast, create_part,
    create_part_line_payload, create_return_authorization_payload,
    create_work_order, make_controller_headers, make_dealer_headers,
    part_version, phase_out_part, read_campaign, read_dealer, read_part,
    read_part_line, set_clock, setup_approved_campaign, setup_catalogue,
    setup_consumed_line, setup_scenario_with_work_order, submit_campaign,
    TEST_USERS, validate_error, validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _draft_campaign_and_held_dealer():
    """A dealer on credit hold and a campaign still in DRAFT — an allocation request
    against them violates the state rule and the fiscal rule at once."""
    scenario = setup_catalogue(
        part_number="PRI-1", unit_cost_cents=1000, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-HOLD", dealer_tier="SILVER",
        dealer_region="LATAM", credit_limit_cents=0, model_code="EM-PRI",
        serial_prefix="SN-PRI", installed_units=0, price_rules=())
    adjust_balance(scenario["dealer"]["id"], 100,
                   "opening debit to force credit hold")
    create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    scenario["campaign"] = create_campaign_for(scenario["part"]["id"], "FLAT_RATE", 5)
    return scenario


def test_campaign_state_error_outranks_dealer_credit_hold(api):
    """PRD 2.10: "When more than one rule could reject a request, the rules are
    evaluated strictly in the ascending priority order below and the **first** failing
    rule determines the response. This ordering is normative: a request that violates
    several rules always surfaces the lowest-numbered one, and a later rule can never
    mask an earlier one."
    PRD 2.10: "The target resource is in a state from which the requested transition
    is declared, including the cross-dimension guard on shipping a replenishment order
    and the cross-entity guards: submitting a campaign requires its part to be in
    `PHASE_OUT`; creating an allocation request requires the campaign to be in
    `APPROVED`; creating a return authorization requires the source line to be in
    `CONSUMED`; approving or receiving a replenishment order requires the part not to
    be `OBSOLETE`; and inspecting a return with a `RESTOCK` disposition requires the
    part not to be `OBSOLETE`."
    PRD 2.10: "The acting or referenced dealer is not on credit hold — otherwise
    `ERR_DEALER_CREDIT_HOLD` (402). Applies to adding a part line to a work order,
    consuming a part line, and creating an allocation request."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_allocation_request_create
    """
    scenario = _draft_campaign_and_held_dealer()
    campaign_id = scenario["campaign"]["id"]

    resp = api.create_allocation_request(create_allocation_request_payload(
        campaign_id, scenario["dealer"]["id"], 5, campaign_version(campaign_id)),
        make_dealer_headers(scenario["dealer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_STATE_INVALID.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_DEALER_CREDIT_HOLD.value


def test_rejected_allocation_request_leaves_both_violations_visible(api):
    """PRD 3.1: "Derived from it is `credit_hold`, which is true exactly when
    `outstanding_balance_cents` is strictly greater than `credit_limit_cents`, and which
    is recomputed every single time the balance or the limit changes."
    PRD 3.8: "It starts with `status` `DRAFT`, a `revision_index` of 0, an
    `approved_qty` of 0, a `remaining_qty` of 0, and both `submitted_by_user_id` and
    `approved_by_user_id` null."
    PRD 3.8: "Requests can be listed and filtered by `campaign_id`, by `dealer_id` and
    by `status`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_allocation_request_create
    """
    scenario = _draft_campaign_and_held_dealer()
    campaign_id = scenario["campaign"]["id"]
    before = read_campaign(campaign_id)

    api.create_allocation_request(create_allocation_request_payload(
        campaign_id, scenario["dealer"]["id"], 5, before["version"]),
        make_dealer_headers(scenario["dealer"]["id"]))

    assert read_dealer(scenario["dealer"]["id"])["credit_hold"] is True, \
        "the fiscal violation really was present"
    after = read_campaign(campaign_id)
    assert after["status"] == "DRAFT"
    assert after["version"] == before["version"]
    _, meta = validate_paginated(api.list_allocation_requests(
        PLANNER, params={"campaign_id": campaign_id}))
    assert meta["total_count"] == 0


def _superseded_and_inapplicable_part():
    """A part whose only applicability row covers revisions 200 to 300 — so it does
    not cover the machine at revision 100 — and which is also SUPERSEDED."""
    scenario = setup_catalogue(
        part_number="OLD-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-SAFE", dealer_region="EU",
        model_code="EM-900", serial_prefix="SN-900", build_revision=100,
        applicability_from=200, applicability_to=300,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    successor = create_part(part_number="NEW-1", description="Replacement filter",
                            unit_cost_cents=1400, lead_time_days=30, weight_kg=1.0)
    validate_success(api_client.supersede_part(
        scenario["part"]["id"], successor["id"], PLANNER))
    scenario["successor"] = successor
    scenario["work_order"] = create_work_order(
        scenario["unit"]["id"], scenario["dealer"]["id"],
        "SCHEDULED_MAINTENANCE", "PLANNED")
    return scenario


def test_part_not_applicable_outranks_part_superseded(api):
    """PRD 2.10: "When more than one rule could reject a request, the rules are
    evaluated strictly in the ascending priority order below and the **first** failing
    rule determines the response. This ordering is normative: a request that violates
    several rules always surfaces the lowest-numbered one, and a later rule can never
    mask an earlier one."
    PRD 2.10: "Part applicability to the machine being worked on — otherwise
    `ERR_PART_NOT_APPLICABLE` (422). Applies to adding a part line to a work order."
    PRD 2.10: "The requested part is not in `SUPERSEDED` — otherwise
    `ERR_PART_SUPERSEDED` (422). Applies to adding a part line to a work order, creating
    a replenishment order, and creating a last-time-buy campaign."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_part_line_create
    """
    scenario = _superseded_and_inapplicable_part()

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 1),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_PART_NOT_APPLICABLE.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_PART_SUPERSEDED.value


def test_refused_part_line_leaves_the_superseded_part_untouched(api):
    """PRD 3.8: "On success the part's `superseded_by_part_id` is set to the nominated
    successor, its `lifecycle_state` becomes `SUPERSEDED`, and its `stocking_policy`
    becomes `NO_STOCK`."
    PRD 3.6: "Lines can be listed and filtered by `work_order_id`, by `part_id` and by
    `line_status`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_part_line_create
    """
    scenario = _superseded_and_inapplicable_part()
    api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 1),
        scenario["dealer_headers"])

    part = read_part(scenario["part"]["id"])
    assert part["lifecycle_state"] == "SUPERSEDED", \
        "the referential violation really was present"
    assert part["superseded_by_part_id"] == scenario["successor"]["id"]

    _, meta = validate_paginated(api.list_part_lines(
        PLANNER, params={"work_order_id": scenario["work_order"]["id"]}))
    assert meta["total_count"] == 0


def _expired_and_over_returned_line():
    """A line that consumed 2 units 200 days ago — both the return window and the
    quantity ceiling will fail for a 5-unit return."""
    scenario = setup_consumed_line(
        part_number="LATE-1", qty=2, stock_units=10, unit_cost_cents=1333,
        lead_time_days=30, weight_kg=2.0, dealer_code="D-LATE",
        model_code="EM-A10", serial_prefix="SN-A10", qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    set_clock("2027-02-17T00:00:00Z")
    return scenario


def test_return_window_expiry_outranks_the_over_return_quantity(api):
    """PRD 2.10: "When more than one rule could reject a request, the rules are
    evaluated strictly in the ascending priority order below and the **first** failing
    rule determines the response. This ordering is normative: a request that violates
    several rules always surfaces the lowest-numbered one, and a later rule can never
    mask an earlier one."
    PRD 2.10: "The return is raised inside the return window — otherwise
    `ERR_RETURN_WINDOW_EXPIRED` (422). Applies to creating a return authorization."
    PRD 2.10: "Cumulative returned quantity does not exceed the consumed quantity of
    the line — otherwise `ERR_RETURN_QTY_EXCEEDS_CONSUMED` (422). Applies to creating a
    return authorization."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_return_authorization_create
    """
    scenario = _expired_and_over_returned_line()

    resp = api.create_return_authorization(
        create_return_authorization_payload(scenario["line"]["id"], 5,
                                            "UNUSED_SURPLUS"),
        make_dealer_headers(scenario["dealer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value)
    assert resp.json()["data"]["error_id"] != \
        ApiErrorId.ERR_RETURN_QTY_EXCEEDS_CONSUMED.value


def test_expired_return_stores_nothing_even_though_the_quantity_also_fails(api):
    """PRD 3.9: "The return must be timely: `age_days`, the number of whole days from
    the line's `consumed_at` to the current logical instant with any partial day
    discarded, may not exceed 180 days, and an older return is refused with
    `ERR_RETURN_WINDOW_EXPIRED`."
    PRD 3.9: "And the return must not over-return: the requested `qty_returned` plus
    the `qty_returned` of every return authorization already raised against the same line
    and not in `REJECTED` may not exceed that line's `qty_consumed`, or the request is
    refused with `ERR_RETURN_QTY_EXCEEDS_CONSUMED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_return_authorization_create
    """
    scenario = _expired_and_over_returned_line()
    api.create_return_authorization(
        create_return_authorization_payload(scenario["line"]["id"], 5,
                                            "UNUSED_SURPLUS"),
        make_dealer_headers(scenario["dealer"]["id"]))

    assert read_part_line(scenario["line"]["id"])["qty_consumed"] == 2, \
        "the quantity violation really was present"
    _, meta = validate_paginated(api.list_return_authorizations(
        PLANNER, params={"work_order_part_line_id": scenario["line"]["id"]}))
    assert meta["total_count"] == 0


def test_missing_user_id_header_is_unauthenticated_before_any_other_check(api):
    """PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    caller, and `X-User-Role`, naming the caller's role. If either header is absent, or
    if `X-User-Role` is not one of the five role names below spelled exactly, the request
    is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
    PRD 2.10: "Both `X-User-ID` and `X-User-Role` are present, and `X-User-Role` is one
    of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every
    endpoint."

    Design: Corner/rbac/request_missing_x_user_id_header_returns_unauthenticated
    """
    headers_without_user_id = {"X-User-Role": "AftermarketPlanner",
                               "Content-Type": "application/json"}
    resp = api.raw_post("/aftermarket/parts",
                        {"part_number": "AUTH-1", "description": "Auth probe"},
                        headers_without_user_id)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        "authentication is checked before the missing-field rule, even though "
        "unit_cost_cents, lead_time_days and weight_kg are all absent")

    _, meta = validate_paginated(api.list_parts(PLANNER))
    assert meta["total_count"] == 0


def _submitted_campaign(part_number, dealer_code, submit_headers=None,
                        with_dealer=True):
    scenario = setup_catalogue(
        part_number=part_number, unit_cost_cents=100, lead_time_days=5,
        weight_kg=0.1, dealer_code=dealer_code, model_code=f"EM-{part_number}",
        serial_prefix=f"SN-{part_number}", installed_units=0, price_rules=())
    create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    phase_out_part(scenario["part"]["id"])
    campaign = create_campaign_for(scenario["part"]["id"], "FLAT_RATE", 3)
    submit_campaign(campaign["id"], submit_headers)
    scenario["campaign"] = read_campaign(campaign["id"])
    return scenario


def test_dealer_user_cannot_approve_a_campaign(api):
    """PRD 2.1: "If both headers are present and well-formed but the named role is not
    among the roles authorised for the requested operation in section 4, the request is
    rejected with `ERR_UNAUTHORIZED` and HTTP 403."
    PRD 3.8: "Approving requires `status` `SUBMITTED`, an `approved_qty` of at least 1
    supplied in the request, and an approver whose `X-User-ID` differs from
    `submitted_by_user_id`. Approval sets `approved_qty`, sets `remaining_qty` equal to
    it, and stamps `approved_by_user_id`"

    Design: Corner/rbac/dealer_user_cannot_approve_a_campaign
    """
    scenario = _submitted_campaign("RB-1", "D-RB")

    resp = api.approve_campaign(scenario["campaign"]["id"], 10,
                                make_dealer_headers(scenario["dealer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    campaign = read_campaign(scenario["campaign"]["id"])
    assert campaign["status"] == "SUBMITTED"
    assert campaign["approved_qty"] == 0
    assert campaign["approved_by_user_id"] is None
    assert read_part(scenario["part"]["id"])["lifecycle_state"] == "PHASE_OUT"


def test_submitting_controller_cannot_approve_the_same_campaign(api):
    """PRD 2.1: "Recording those two operator identifiers exists for one reason:
    **segregation of duties**. The operator who submits a last-time-buy campaign for
    approval may not be the operator who approves or rejects it, even though both the
    `AftermarketPlanner` and the `InventoryController` role are permitted to submit. When
    the `X-User-ID` presented at approval or rejection equals the campaign's stored
    `submitted_by_user_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES` and
    HTTP 403."
    PRD 3.8: "Submission is open to both an `AftermarketPlanner` and an
    `InventoryController`, which is precisely what gives segregation of duties its bite."

    Design: Corner/rbac/submitting_controller_cannot_approve_the_same_campaign
    """
    scenario = _submitted_campaign("SOD-1", "D-SOD",
                                   submit_headers=make_controller_headers("ctrl-9"))
    campaign_id = scenario["campaign"]["id"]
    assert scenario["campaign"]["submitted_by_user_id"] == "ctrl-9"

    refused = api.approve_campaign(campaign_id, 10, make_controller_headers("ctrl-9"))
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert read_campaign(campaign_id)["status"] == "SUBMITTED"

    approved = validate_success(api.approve_campaign(
        campaign_id, 10, make_controller_headers("ctrl-8")))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "ctrl-8"
    assert approved["approved_qty"] == 10
    assert approved["remaining_qty"] == 10
    assert read_part(scenario["part"]["id"])["lifecycle_state"] == "LTB_OPEN"


def test_dealer_user_cannot_add_a_line_to_another_dealers_work_order(api):
    """PRD 2.1: "Concretely, a `DealerUser` may act only where the `dealer_id`
    reachable from the target resource equals its own `X-User-ID` — directly on a service
    work order, indirectly through a part line's parent work order, directly on an
    allocation request, directly on a return authorization, or as the `dealer_id`
    supplied in a request body. A mismatch is rejected with `ERR_DEALER_SCOPE_VIOLATION`
    and HTTP 403."
    PRD 3.6: "The work order's `dealer_id` is not supplied by the caller; it is copied
    from the installed unit's own `dealer_id` at creation."

    Design: Corner/rbac/dealer_user_cannot_open_a_line_on_another_dealers_work_order
    """
    scenario = setup_scenario_with_work_order(
        part_number="SCP-1", unit_cost_cents=1333, lead_time_days=0,
        weight_kg=1.0, dealer_code="SC-A", model_code="EM-AD1",
        serial_prefix="SN-AD1", price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    other_dealer = create_dealer("SC-B", "GOLD", "NA")

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 1),
        make_dealer_headers(other_dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_DEALER_SCOPE_VIOLATION.value)

    work_order = validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))
    assert work_order["dealer_id"] == scenario["dealer"]["id"]
    _, meta = validate_paginated(api.list_part_lines(
        PLANNER, params={"work_order_id": scenario["work_order"]["id"]}))
    assert meta["total_count"] == 0


def test_stale_part_version_rejects_a_second_campaign_create(api):
    """PRD 2.6: "A `POST /aftermarket/last-time-buy-campaigns` request must carry
    `expected_part_version`, holding the `version` of the target `Part` as the client
    last observed it. If that value does not equal the part's current `version`, the
    create is rejected with `ERR_STALE_PART_VERSION` and HTTP 412. The guard is necessary
    because a successful create legitimately supersedes any existing `DRAFT` campaign on
    the same part by moving it to `CANCELLED`; a client working from an out-of-date view
    of the part would otherwise destroy a draft it never read."

    Design: Corner/cross_cutting_layers/occ_stale_part_version_rejects_second_campaign_create
    """
    scenario = setup_catalogue(
        part_number="OCC-1", unit_cost_cents=100, lead_time_days=5,
        weight_kg=0.1, dealer_code="D-OCC1", model_code="EM-OCC1",
        serial_prefix="SN-OCC1", installed_units=0, price_rules=())
    part_id = scenario["part"]["id"]
    create_forecast(part_id, 12, "INSTALLED_BASE_RATE")
    phase_out_part(part_id)
    observed_version = part_version(part_id)
    first = create_campaign_for(part_id, "FLAT_RATE", 3,
                                expected_part_version=observed_version)

    resp = api.create_campaign(create_campaign_payload(
        part_id, observed_version, method="DEMAND_DECAY", coverage_years=4),
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_PART_VERSION.value)

    assert read_campaign(first["id"])["status"] == "DRAFT", \
        "the stale create must not supersede the existing draft"
    _, meta = validate_paginated(api.list_campaigns(
        PLANNER, params={"part_id": part_id}))
    assert meta["total_count"] == 1


def test_stale_campaign_version_rejects_a_second_allocation_request(api):
    """PRD 2.6: "A `POST /aftermarket/allocation-requests` request must carry
    `expected_campaign_version`, holding the `version` of the target
    `LastTimeBuyCampaign` as the client last observed it. If that value does not equal
    the campaign's current `version`, the create is rejected with
    `ERR_STALE_CAMPAIGN_VERSION` and HTTP 412. Here too a successful create supersedes
    the same dealer's prior `PENDING` request on that campaign by moving it to
    `WITHDRAWN`, and the campaign's `version` also advances whenever the allocation
    waterfall runs or a grant is withdrawn — so a client holding an out-of-date view of
    the campaign must not be permitted to write."

    Design: Corner/cross_cutting_layers/occ_stale_campaign_version_rejects_second_allocation_request
    """
    scenario = setup_approved_campaign(
        part_number="OCC-2", approved_qty=50, campaign_method="FLAT_RATE",
        coverage_years=3, unit_cost_cents=100, lead_time_days=5, weight_kg=0.1,
        dealer_code="D-OCC2", model_code="EM-OCC2", serial_prefix="SN-OCC2",
        installed_units=0, price_rules=())
    campaign_id = scenario["campaign"]["id"]
    dealer_id = scenario["dealer"]["id"]
    observed_version = campaign_version(campaign_id)
    first = create_allocation_request(campaign_id, dealer_id, 20,
                                      expected_campaign_version=observed_version)

    resp = api.create_allocation_request(create_allocation_request_payload(
        campaign_id, dealer_id, 30, observed_version),
        make_dealer_headers(dealer_id))
    validate_error(resp, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value)

    settled = validate_success(api.get_allocation_request(first["id"], PLANNER))
    assert settled["status"] == "PENDING", \
        "the stale create must not supersede the existing request"
    assert settled["requested_units"] == 20
    _, meta = validate_paginated(api.list_allocation_requests(
        PLANNER, params={"campaign_id": campaign_id}))
    assert meta["total_count"] == 1


def test_dealer_on_credit_hold_cannot_add_a_part_line(api):
    """PRD 3.1: "A dealer on credit hold is not merely flagged, it is blocked. Three
    operations refuse to proceed for a dealer whose `credit_hold` is true, each with
    `ERR_DEALER_CREDIT_HOLD` and HTTP 402: adding a part line to a work order, consuming
    a part line, and creating an allocation request."
    PRD 3.1: "A `PlatformAdmin` may post a manual movement to the receivable by
    supplying an `amount_cents` — positive for a debit, negative for a credit — together
    with a free-text `reason`; the amount is added to `outstanding_balance_cents`,
    `credit_hold` is recomputed against `credit_limit_cents`, and the dealer's `version`
    advances."

    Design: Corner/validations/dealer_credit_hold_blocks_part_line_create
    """
    scenario = setup_scenario_with_work_order(
        part_number="HLD-1", unit_cost_cents=1333, lead_time_days=0,
        weight_kg=1.0, dealer_code="D-HLD", credit_limit_cents=50,
        model_code="EM-Y10", serial_prefix="SN-Y10",
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    adjust_balance(scenario["dealer"]["id"], 100, "unpaid invoice")

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 1),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_DEALER_CREDIT_HOLD.value)

    dealer = read_dealer(scenario["dealer"]["id"])
    assert dealer["outstanding_balance_cents"] == 100
    assert dealer["credit_hold"] is True
    _, meta = validate_paginated(api.list_part_lines(
        PLANNER, params={"work_order_id": scenario["work_order"]["id"]}))
    assert meta["total_count"] == 0
