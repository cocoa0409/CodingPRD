"""Issuing and activating harvest authorizations (PRD §3.7).

Four rules meet at the authorization endpoints: the ladder order between the
referential dealer-certification rung and the fiscal rent rung, the inclusive
day-age boundary on husbandry currency, the two-hop classification gate on
activation, and the half-open window arithmetic behind a vessel's concurrent
capacity.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_listed_dealer,
    create_vessel,
    design_world,
    DW_ACTIVATE_CLOCK,
    dw_dealer_payload,
    dw_deploy_unit,
    DW_WINDOW_END,
    DW_WINDOW_START,
    dw_vessel_payload,
    get_success_data,
    harvest_authorization_payload,
    iso,
    record_classification_decision,
    set_clock,
    TEST_USERS,
    to_millis,
    validate_error,
    validate_paginated,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _issue(world, unit=None, window_start=DW_WINDOW_START,
           window_end=DW_WINDOW_END, projected_bushels=600):
    return api_client.create_harvest_authorization(
        harvest_authorization_payload(
            world["lease"]["id"], (unit or world["unit"])["id"],
            world["vessel"]["id"], world["dealer"]["id"],
            window_start, window_end, projected_bushels=projected_bushels),
        OPERATOR)


# --------------------------------------------------------------------------
# Referential before fiscal
# --------------------------------------------------------------------------
def _world_with_expired_dealer_and_delinquent_rent():
    """The dealer's certification lapsed on 2026-07-15 and was never renewed, so
    it is also still NOT_LISTED, and the lease's rent is paid only through
    2026-07-31 -- two independent defects, both live at the 2026-08-01 clock."""
    return design_world(
        stage="unit",
        dealer_overrides={"certified_through": "2026-07-15"},
        list_dealer=False,
        rent_paid_through_date="2026-07-31",
    )


def test_expired_dealer_certification_answers_before_delinquent_rent():
    """Two rungs are violated by the same issue request. The referential
    dealer-certification rung is ordered ahead of the fiscal rent rung, so the
    response is ERR_DEALER_CERTIFICATION_EXPIRED at HTTP 409 -- and notably not
    ERR_LEASE_RENT_DELINQUENT, whose HTTP status would have been 402.

    Design: Difficulty/priority_pair_validation_conflict/authorization_with_expired_dealer_and_delinquent_rent_returns_referential_over_fiscal
    """
    world = _world_with_expired_dealer_and_delinquent_rent()

    response = _issue(world)

    body = validate_error(
        response, ApiErrorId.ERR_DEALER_CERTIFICATION_EXPIRED, 409)
    assert body["error_id"] != ApiErrorId.ERR_LEASE_RENT_DELINQUENT
    assert response.status_code != 402


def test_rejected_issue_leaves_no_authorization_and_no_counter_movement():
    """A rejected issue is a complete no-op: no authorization row is created, the
    vessel's `active_authorization_count` stays 0, the grow-out unit stays
    DEPLOYED and husbandry-current, and both offending fields keep their values.

    Design: Difficulty/priority_pair_validation_conflict/authorization_with_expired_dealer_and_delinquent_rent_returns_referential_over_fiscal
    """
    world = _world_with_expired_dealer_and_delinquent_rent()
    _issue(world)

    _rows, meta = validate_paginated(
        api_client.list_harvest_authorizations(AUTHORITY))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], AUTHORITY))
    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], AUTHORITY))
    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))

    assert meta["total_count"] == 0
    assert vessel["active_authorization_count"] == 0
    assert unit["status"] == "DEPLOYED"
    assert unit["husbandry_current"] is True
    assert dealer["certified_through"] == "2026-07-15"
    assert dealer["listing_status"] == "NOT_LISTED"
    assert lease["rent_paid_through_date"] == "2026-07-31"
    assert lease["status"] == "APPROVED"


# --------------------------------------------------------------------------
# The inclusive husbandry day-age boundary
# --------------------------------------------------------------------------
BOUNDARY_LOG_AT = iso(2026, 7, 11, 6)
ONE_SECOND_PAST = "2026-08-10T06:00:01Z"


def _world_with_logs_exactly_thirty_days_old():
    """Both husbandry logs sit at 2026-07-11T06:00:00Z, exactly
    `INSPECTION_MAX_AGE_DAYS` 30 twenty-four-hour periods before the
    2026-08-10T06:00:00Z clock the issue request runs at."""
    world = design_world(
        stage="unit",
        inspection_at=BOUNDARY_LOG_AT,
        predator_control_at=BOUNDARY_LOG_AT,
    )
    return world


def test_authorization_issues_with_husbandry_logs_exactly_at_the_age_limit():
    """The age comparison is inclusive, so logs exactly 30 days old still leave
    `husbandry_current` true and the authorization issues with HTTP 201 in
    ISSUED, denormalising `growing_area_id` from the lease and starting
    `harvested_bushels` at 0 against 600 projected bushels.

    Design: Difficulty/boundary_precision_check/authorization_with_inspection_exactly_thirty_days_old_succeeds
    """
    world = _world_with_logs_exactly_thirty_days_old()
    set_clock(DW_ACTIVATE_CLOCK)

    authorization = validate_success(_issue(world), 201)

    assert authorization["status"] == "ISSUED"
    assert authorization["growing_area_id"] == world["area"]["id"]
    assert authorization["harvested_bushels"] == 0
    assert authorization["projected_bushels"] == 600

    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    assert unit["last_inspection_at"] == to_millis(BOUNDARY_LOG_AT)
    assert unit["last_predator_control_at"] == to_millis(BOUNDARY_LOG_AT)
    assert unit["husbandry_current"] is True
    assert vessel["active_authorization_count"] == 1


def test_one_second_past_the_age_limit_the_husbandry_has_lapsed():
    """Moving the clock one second later makes the same logs older than the
    limit, and the identical request is refused with ERR_HUSBANDRY_LAPSED, which
    fixes the age comparison as inclusive rather than strict.

    Design: Difficulty/boundary_precision_check/authorization_with_inspection_exactly_thirty_days_old_succeeds
    """
    world = _world_with_logs_exactly_thirty_days_old()
    set_clock(ONE_SECOND_PAST)

    response = _issue(world)

    validate_error(response, ApiErrorId.ERR_HUSBANDRY_LAPSED, 409)
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    assert vessel["active_authorization_count"] == 0


# --------------------------------------------------------------------------
# Activation reads the area's classification two hops away
# --------------------------------------------------------------------------
def _issued_world_then_area_downgraded():
    """The authorization is issued while the area is APPROVED; only afterwards
    does the authority downgrade the classification administratively, leaving
    `harvest_status` OPEN and `eligible_classification` APPROVED."""
    world = design_world(
        stage="issued",
        sample_mpns=[2, 2, 2, 2, 2],
        activate_clock=None,
    )
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    world["area"] = record_classification_decision(
        area, "RESTRICTED",
        {"decision_note": "downgrade pending sanitary survey"})
    set_clock(DW_ACTIVATE_CLOCK)
    return world


def test_activation_is_blocked_by_the_areas_classification_not_its_closure():
    """Activation reads `classification` through the lease's `growing_area_id`,
    two hops from the addressed authorization. RESTRICTED is not harvestable, so
    the call is refused with ERR_AREA_CLASSIFICATION_NOT_HARVESTABLE -- and not
    with ERR_AREA_HARVEST_CLOSED, because the area's `harvest_status` dimension
    is still OPEN and no closure cascade has run.

    Design: Difficulty/cross_entity_state_dependency/authorization_activate_blocked_by_downgraded_area_classification
    """
    world = _issued_world_then_area_downgraded()

    response = api_client.activate_harvest_authorization(
        world["authorization"]["id"], OPERATOR)

    body = validate_error(
        response, ApiErrorId.ERR_AREA_CLASSIFICATION_NOT_HARVESTABLE, 409)
    assert body["error_id"] != ApiErrorId.ERR_AREA_HARVEST_CLOSED
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["classification"] == "RESTRICTED"
    assert area["harvest_status"] == "OPEN"
    assert area["eligible_classification"] == "APPROVED"


def test_blocked_activation_leaves_the_authorization_issued_and_not_voided():
    """The refusal is not a closure cascade: the authorization stays ISSUED with
    `harvest_start_at` null rather than moving to VOIDED, the unit never enters
    HARVESTING, and the vessel's counter is neither incremented nor released.

    Design: Difficulty/cross_entity_state_dependency/authorization_activate_blocked_by_downgraded_area_classification
    """
    world = _issued_world_then_area_downgraded()
    api_client.activate_harvest_authorization(
        world["authorization"]["id"], OPERATOR)

    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))

    assert authorization["status"] == "ISSUED"
    assert authorization["harvest_start_at"] is None
    assert unit["status"] == "DEPLOYED"
    assert vessel["active_authorization_count"] == 1


# --------------------------------------------------------------------------
# A vessel's concurrent capacity over half-open windows
# --------------------------------------------------------------------------
CAPACITY_WINDOWS = {
    "auth1": (iso(2026, 8, 10, 6), iso(2026, 8, 10, 12)),
    "auth2": (iso(2026, 8, 10, 10), iso(2026, 8, 10, 16)),
    "auth3": (iso(2026, 8, 10, 11), iso(2026, 8, 10, 15)),
    "adjacent": (iso(2026, 8, 10, 16), iso(2026, 8, 10, 18)),
}


def _vessel_at_capacity_with_a_spare_unit():
    """One vessel of `concurrent_authorization_capacity` 2 already carries two
    mutually overlapping authorizations, and a third deployed unit on the same
    lease is standing by."""
    world = design_world(stage="seed")
    world["vessel"] = create_vessel(OPERATOR, dw_vessel_payload())
    world["dealer"] = create_listed_dealer(dw_dealer_payload())
    units = []
    for plot, deployed, planned in (
            ("P1", "2026-05-05", "2026-10-15"),
            ("P2", "2026-05-06", "2026-10-16"),
            ("P3", "2026-05-07", "2026-10-17")):
        units.append(dw_deploy_unit(
            world["lease"], world["seed_lot"], OPERATOR,
            {"plot_code": plot, "seed_count_planted": 20000,
             "deployed_on": deployed, "planned_retrieval_on": planned}))
    world["units"] = units
    world["unit"] = units[0]
    for key, unit in (("auth1", units[0]), ("auth2", units[1])):
        start, end = CAPACITY_WINDOWS[key]
        world[key] = validate_success(_issue(world, unit, start, end), 201)
    return world


def test_the_third_overlapping_authorization_exceeds_the_vessel_capacity():
    """`concurrent_authorization_capacity` is 2 and the third window
    11:00-15:00 overlaps both existing windows at once, so the issue is refused
    with ERR_VESSEL_CAPACITY_CONFLICT while the two legal, mutually overlapping
    authorizations both stay ISSUED.

    Design: Difficulty/resource_temporal_overlap/third_overlapping_authorization_on_vessel_at_capacity_rejected
    """
    world = _vessel_at_capacity_with_a_spare_unit()
    start, end = CAPACITY_WINDOWS["auth3"]

    response = _issue(world, world["units"][2], start, end)

    validate_error(response, ApiErrorId.ERR_VESSEL_CAPACITY_CONFLICT, 409)
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    _rows, meta = validate_paginated(
        api_client.list_harvest_authorizations(AUTHORITY))
    assert vessel["active_authorization_count"] == 2
    assert meta["total_count"] == 2
    for key in ("auth1", "auth2"):
        assert get_success_data(api_client.get_harvest_authorization(
            world[key]["id"], OPERATOR))["status"] == "ISSUED"
    unit3 = get_success_data(
        api_client.get_growout_unit(world["units"][2]["id"], OPERATOR))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))
    assert unit3["status"] == "DEPLOYED"
    assert seed_lot["status"] == "PLANTED"
    assert seed_lot["unallocated_seed_count"] == 0


def test_a_window_adjacent_to_the_last_one_does_not_count_as_overlap():
    """The windows are half-open, so a `window_start` equal to an existing
    `window_end` is not an overlap: with 16:00-18:00 the same third unit issues
    with HTTP 201, because auth2's window has just ended and auth1's ended four
    hours earlier.

    Design: Difficulty/resource_temporal_overlap/third_overlapping_authorization_on_vessel_at_capacity_rejected
    """
    world = _vessel_at_capacity_with_a_spare_unit()
    start, end = CAPACITY_WINDOWS["adjacent"]

    authorization = validate_success(
        _issue(world, world["units"][2], start, end), 201)

    assert authorization["status"] == "ISSUED"
    assert authorization["window_start"] == to_millis(start)
    assert authorization["window_end"] == to_millis(end)
    _rows, meta = validate_paginated(
        api_client.list_harvest_authorizations(AUTHORITY))
    assert meta["total_count"] == 3
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    assert vessel["active_authorization_count"] == 3
