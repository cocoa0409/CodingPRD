"""Channels and allocation offers: subsidy derivation, season-posture gating,
capacity and credit boundaries, respond lifecycle, supersede recapture, and the
lot-unit conservation invariant.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_season,
    assert_channel_account,
    assert_lot_units_conserved,
    create_allocation,
    create_allocation_payload,
    create_channel,
    create_lot,
    create_model,
    create_season,
    make_channel_rep_headers,
    refetch_allocation,
    respond_allocation_payload,
    respond_to_allocation,
    setup_offered_allocation,
    setup_season_in_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]


def _offer(api, season_id, channel_id, model_id, units):
    """Raw allocation create carrying the season's current version (PRD 2.7)."""
    season = validate_success(api.get_season(season_id, headers=PLANNER), 200)
    payload = create_allocation_payload(season_id, channel_id, model_id, units, season["version"])
    return api.create_allocation(payload, headers=PLANNER)


def test_channel_subsidy_derived_from_channel_type(api):
    """PRD 3.4: "The channel's assembly-fee subsidy is derived, never written: a
    `HOME_CENTER` carries a `subsidy_bp` of 2000 (a 20 percent subsidy), a
    `SPECIALTY_DEALER` carries 1000 (10 percent), and a `DIRECT` channel carries 0."
    PRD 3.5: "When the denominator is empty, both rates are exactly 0.0000 — an empty
    channel reports zeros rather than an error."

    Design: Corner/entities/channel_subsidy_derived_from_channel_type
    """
    home = validate_success(api.create_channel(
        {"name": "BigBox", "channel_type": "HOME_CENTER", "allocation_priority": 10,
         "credit_limit_cents": 100000000}, headers=PLANNER), 201)
    direct = validate_success(api.create_channel(
        {"name": "WebDirect", "channel_type": "DIRECT", "allocation_priority": 5,
         "credit_limit_cents": 100000000}, headers=PLANNER), 201)
    assert_channel_account(home)
    assert_channel_account(direct)
    assert home["subsidy_bp"] == 2000
    assert direct["subsidy_bp"] == 0
    assert float(home["accessory_attach_rate"]) == 0.0
    assert float(home["fuel_attach_rate"]) == 0.0


def test_allocation_gated_by_season_posture(api):
    """PRD 3.1: "Posture is a gate, not a suggestion. Inventory lots can only be
    created while the season is `PLANNING` or `BUILD`; allocation offers can only be
    written while the season is `ALLOCATION`; sales can only be recorded while the
    season is `IN_SEASON` or `CLEARANCE`. Attempting any of these against a season in
    the wrong posture is rejected with `ERR_SEASON_POSTURE_FORBIDDEN`."
    PRD 3.4: "A successful create stamps `offered_at` from the logical clock, sets the
    allocation `OFFERED` with `committed_units` at 0"

    Design: Difficulty/cross_entity_state_dependency/allocation_gated_by_season_posture
    """
    season = create_season()
    model = create_model()
    channel = create_channel()
    create_lot(season["id"], model["id"], units_built=20)
    refused = _offer(api, season["id"], channel["id"], model["id"], 5)
    validate_error(refused, ApiErrorId.ERR_SEASON_POSTURE_FORBIDDEN)
    advance_season(season["id"], "BUILD")
    advance_season(season["id"], "ALLOCATION")
    accepted = _offer(api, season["id"], channel["id"], model["id"], 5)
    data = validate_success(accepted, 201)
    assert data["status"] == "OFFERED", f"the identical request must succeed in ALLOCATION, got {data['status']}"


def test_posture_error_precedes_credit_error(api):
    """PRD 2.9: "When a single request violates several rules at once, the category
    with the lowest priority number wins and alone determines the response; later
    violations are masked until the earlier one is fixed."
    PRD 2.9: "10. **Fiscal limits, always last.** The channel credit check on
    allocation create and revise (`ERR_CREDIT_LIMIT_EXCEEDED`, 422)"

    Design: Difficulty/priority_pair_validation_conflict/posture_error_precedes_credit_error
    """
    season = create_season()  # PLANNING: the state gate (rung 5) is violated
    model = create_model()
    channel = create_channel(
        name="TinyCredit", channel_type="SPECIALTY_DEALER", allocation_priority=3,
        credit_limit_cents=1,  # 5 x 100000 > 1: the fiscal gate (rung 10) is violated too
    )
    resp = _offer(api, season["id"], channel["id"], model["id"], 5)
    validate_error(resp, ApiErrorId.ERR_SEASON_POSTURE_FORBIDDEN)
    _allocs, meta = validate_paginated(api.list_allocations(headers=PLANNER))
    assert meta["total_count"] == 0, "no allocation may be persisted by the rejected create"


def test_credit_limit_boundary_inclusive_and_exceeded(api):
    """PRD 3.4: "Credit: the channel's `outstanding_exposure_cents` plus the new
    offer's `allocated_units` times the model's `base_price_cents` must not exceed
    `credit_limit_cents`; equality passes, one cent over is
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_boundary_inclusive_and_exceeded
    """
    bundle = setup_season_in_allocation(units_built=20)
    season_id, model_id = bundle["season"]["id"], bundle["model"]["id"]
    exact = create_channel(name="ExactFit", channel_type="HOME_CENTER",
                           allocation_priority=10, credit_limit_cents=400000)
    short = create_channel(name="ShortOne", channel_type="HOME_CENTER",
                           allocation_priority=11, credit_limit_cents=399999)
    ok = _offer(api, season_id, exact["id"], model_id, 4)  # 4 x 100000 == 400000
    validate_success(ok, 201)
    over = _offer(api, season_id, short["id"], model_id, 4)  # 400000 > 399999 by one cent
    validate_error(over, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_allocation_capacity_exact_fit_passes(api):
    """PRD 3.4: "Capacity: after any same-tuple supersession recapture described
    below, the offered `allocated_units` — reckoned against the sum of the lot's
    active allocations — must not exceed the lot's `units_available`; an exact fit
    passes, and one unit over is `ERR_ALLOCATION_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/allocation_capacity_exact_fit_passes
    """
    bundle = setup_season_in_allocation(units_built=5)
    season_id, model_id = bundle["season"]["id"], bundle["model"]["id"]
    ch_a = create_channel(name="CH-A", channel_type="HOME_CENTER", allocation_priority=10, credit_limit_cents=100000000)
    ch_b = create_channel(name="CH-B", channel_type="HOME_CENTER", allocation_priority=20, credit_limit_cents=100000000)
    ch_c = create_channel(name="CH-C", channel_type="HOME_CENTER", allocation_priority=30, credit_limit_cents=100000000)
    validate_success(_offer(api, season_id, ch_a["id"], model_id, 3), 201)
    validate_success(_offer(api, season_id, ch_b["id"], model_id, 2), 201)
    # 3 + 2 == 5 units_built: the exact fit passed; the 6th unit must fail.
    over = _offer(api, season_id, ch_c["id"], model_id, 1)
    validate_error(over, ApiErrorId.ERR_ALLOCATION_CAPACITY_EXCEEDED)
    lots, _meta = validate_paginated(api.list_season_lots(season_id, headers=PLANNER))
    assert lots[0]["units_available"] == 0, f"lot must be fully reserved, got {lots[0]['units_available']}"


def test_declined_allocation_cannot_be_accepted(api):
    """PRD 3.4: "Each action has its own valid-from states — accept, decline, and
    revise belong to `OFFERED`, release belongs to `ACCEPTED` and `PARTIALLY_CONSUMED`
    — and any action attempted on an allocation in a state that does not offer it,
    such as accepting a `DECLINED`, `RELEASED`, `EXPIRED`, `SUPERSEDED`, or `CONSUMED`
    allocation, is `ERR_ALLOCATION_NOT_ACTIONABLE`."
    PRD 3.4: "A **decline** moves `OFFERED → DECLINED`, zeroes `allocated_units`,
    returns the offered units to the lot's `units_available`"

    Design: Corner/state_machines/declined_allocation_cannot_be_accepted
    """
    bundle = setup_offered_allocation(allocated_units=8, units_built=10)
    allocation = bundle["allocation"]
    channel = bundle["channel"]
    declined = respond_to_allocation(allocation, "DECLINE")
    assert declined["status"] == "DECLINED"
    fresh = refetch_allocation(allocation["id"])
    resp = api.respond_allocation(
        allocation["id"],
        respond_allocation_payload("ACCEPT", fresh["version"]),  # fresh version: the state gate, not OCC, must fire
        headers=make_channel_rep_headers(channel["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_ACTIONABLE)
    after = refetch_allocation(allocation["id"])
    assert after["status"] == "DECLINED"
    assert after["allocated_units"] == 0
    lots, _meta = validate_paginated(api.list_season_lots(bundle["season"]["id"], headers=PLANNER))
    assert lots[0]["units_available"] == 10, "the declined 8 units must stay with the lot"


def test_channel_exposure_reconciles_on_accept_and_release(api):
    """PRD 3.4: "The channel's `outstanding_exposure_cents` is likewise derived as the
    sum, over that channel's allocations in `ACCEPTED` or `PARTIALLY_CONSUMED`, of
    each allocation's uncommitted remainder — `allocated_units` minus `committed_units`
    — multiplied by the model's `base_price_cents`."
    PRD 3.4: "A **release** by the owning channel moves `ACCEPTED` or
    `PARTIALLY_CONSUMED → RELEASED`, collapsing `allocated_units` to `committed_units`
    so the unconsumed remainder returns to the lot."

    Design: Corner/cross_cutting_complexity_layers/channel_exposure_reconciles_on_accept_and_release
    """
    bundle = setup_offered_allocation(allocated_units=10, units_built=20)
    allocation, channel = bundle["allocation"], bundle["channel"]
    rep = make_channel_rep_headers(channel["id"])
    before = validate_success(api.get_channel(channel["id"], headers=PLANNER), 200)
    assert before["outstanding_exposure_cents"] == 0, "an OFFERED allocation carries no exposure"
    accepted = validate_success(api.respond_allocation(
        allocation["id"], respond_allocation_payload("ACCEPT", allocation["version"]), headers=rep), 200)
    mid = validate_success(api.get_channel(channel["id"], headers=PLANNER), 200)
    assert mid["outstanding_exposure_cents"] == 1000000, (
        f"(10 allocated - 0 committed) x 100000 base = 1000000, got {mid['outstanding_exposure_cents']}"
    )
    released = validate_success(api.respond_allocation(
        allocation["id"], respond_allocation_payload("RELEASE", accepted["version"]), headers=rep), 200)
    assert released["status"] == "RELEASED"
    after = validate_success(api.get_channel(channel["id"], headers=PLANNER), 200)
    assert after["outstanding_exposure_cents"] == 0, "RELEASE must return the reservation's exposure to zero"


def test_same_tuple_allocation_create_supersedes_and_recaptures(api):
    """PRD 3.4: "At most one allocation per (season, channel, model) tuple may be live
    — `OFFERED`, `ACCEPTED`, `PARTIALLY_CONSUMED`, or `CONSUMED` — so creating a
    second offer for a tuple that already has a live one supersedes the first: the old
    allocation goes to `SUPERSEDED`, its `allocated_units` collapses to its
    `committed_units` (zero for a never-accepted offer), and the freed units return to
    lot availability before the new offer's capacity check runs."

    Design: Corner/cross_cutting_complexity_layers/same_tuple_allocation_create_supersedes_and_recaptures
    """
    bundle = setup_season_in_allocation(units_built=10)
    season_id, model_id = bundle["season"]["id"], bundle["model"]["id"]
    channel = create_channel()
    first = create_allocation(season_id, channel["id"], model_id, 8)
    # Lot shows only 2 free; the recapture of the first offer must run before the
    # capacity check for the second offer of 5 to fit.
    second = validate_success(_offer(api, season_id, channel["id"], model_id, 5), 201)
    assert second["status"] == "OFFERED"
    old = refetch_allocation(first["id"])
    assert old["status"] == "SUPERSEDED"
    assert old["allocated_units"] == 0, "a never-accepted offer collapses to its committed_units (0)"
    lots, _meta = validate_paginated(api.list_season_lots(season_id, headers=PLANNER))
    assert lots[0]["units_available"] == 5, f"10 built - 5 newly reserved = 5, got {lots[0]['units_available']}"


def test_lot_units_conserved_across_allocate_and_release(api):
    """PRD 3.3: "A lot's `units_available` equals its `units_built`, minus the sum of
    `allocated_units` over all allocations of the same season and model in `OFFERED`,
    `ACCEPTED`, `PARTIALLY_CONSUMED`, or `CONSUMED`, minus the sum of `committed_units`
    over allocations of the same season and model in `RELEASED`, `EXPIRED`, or
    `SUPERSEDED`."
    PRD 3.4: "A **release** by the owning channel moves `ACCEPTED` or
    `PARTIALLY_CONSUMED → RELEASED`, collapsing `allocated_units` to `committed_units`
    so the unconsumed remainder returns to the lot."

    Design: Difficulty/compensating_invariant/lot_units_conserved_across_allocate_and_release
    """
    bundle = setup_offered_allocation(allocated_units=10, units_built=10)
    allocation, channel = bundle["allocation"], bundle["channel"]
    rep = make_channel_rep_headers(channel["id"])
    lots, _m1 = validate_paginated(api.list_season_lots(bundle["season"]["id"], headers=PLANNER))
    assert lots[0]["units_available"] == 0, "the forward action moved all 10 units into the reservation"
    accepted = validate_success(api.respond_allocation(
        allocation["id"], respond_allocation_payload("ACCEPT", allocation["version"]), headers=rep), 200)
    released = validate_success(api.respond_allocation(
        allocation["id"], respond_allocation_payload("RELEASE", accepted["version"]), headers=rep), 200)
    assert released["status"] == "RELEASED"
    assert released["allocated_units"] == 0, "allocated collapses to committed (0 for an unsold allocation)"
    lots, _m2 = validate_paginated(api.list_season_lots(bundle["season"]["id"], headers=PLANNER))
    lot = lots[0]
    assert lot["units_available"] == 10, "the compensation restored the pool exactly"
    assert_lot_units_conserved(lot, [refetch_allocation(allocation["id"])])
