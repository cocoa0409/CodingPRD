"""Seasonal retail allocations and the allocation waterfall."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    assert_retail_allocation, assert_lot_mass_balance, NON_EXISTENT_UUID,
)

ADMIN = fx.ADMIN
PLANNER = fx.PLANNER


def test_allocation_create_with_invalid_enum_tier_is_rejected(api):
    """PRD section 3.5: "a `priority_tier` of `PLATINUM`, `GOLD`, or
    `STANDARD`" and PRD section 2.8 stage 3: "Required fields are present, types and
    enum memberships are valid, and conditional-field rules are honored"
    and "Violations yield `ERR_INVALID_REQUEST` (HTTP 400)" — shape is
    checked before existence (stage 4).

    Design: Corner/entities/allocation_create_with_invalid_enum_tier_is_rejected
    """
    fx.reset_clock()
    resp = api_client.create_retail_allocation(
        {"assortment_spec_id": NON_EXISTENT_UUID, "retailer_name": "MegaMart",
         "priority_tier": "DIAMOND", "requested_boxes": 10,
         "requested_ship_date": "2027-07-15T00:00:00Z",
         "expected_assortment_spec_version": 1},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    assert resp.json()["data"]["error_id"] != "ERR_NOT_FOUND"


def test_allocation_ship_date_outside_season_returns_season_window(api):
    """PRD section 2.10: "every retail allocation's `requested_ship_date` must
    fall inside this closed interval or creation is rejected with
    `ERR_SEASON_WINDOW` (HTTP 422)" — the window runs from
    2027-06-01T00:00:00Z through 2027-08-31T23:59:59Z inclusive.

    Design: Corner/validations/allocation_ship_date_outside_season_returns_season_window
    """
    fx.reset_clock()
    env = fx.production_setup()
    spec_v = fx.get_spec_version(env["spec"]["id"])
    resp = api_client.create_retail_allocation(
        {"assortment_spec_id": env["spec"]["id"], "retailer_name": "MegaMart",
         "priority_tier": "GOLD", "requested_boxes": 10,
         "requested_ship_date": "2027-09-10T00:00:00Z",
         "expected_assortment_spec_version": spec_v},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_SEASON_WINDOW)
    assert resp.status_code == 422
    allocs = get_success_data(
        api_client.list_spec_allocations(env["spec"]["id"], PLANNER))
    assert allocs == []


def test_insufficient_inventory_on_commit_returns_error(api):
    """PRD section 3.5: "`COMMIT` moves `REQUESTED` to `COMMITTED` and computes
    the final share against physical stock only — projections are excluded — as
    the smaller of `requested_boxes` and the spec's `boxes_available`; a final
    share of 0 is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409)."

    Design: Corner/errors/insufficient_inventory_on_commit_returns_error
    """
    fx.reset_clock()
    env = fx.production_setup()  # no run ever completed: boxes_available == 0
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=10)
    assert alloc["allocated_boxes_provisional"] == 0  # empty pool is legal at request time
    assert alloc["status"] == "REQUESTED"
    resp = api_client.allocation_decision(alloc["id"], {"action": "COMMIT"}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
    assert resp.status_code == 409
    assert fx.get_allocation(alloc["id"])["status"] == "REQUESTED"


def test_allocation_commit_from_released_is_rejected(api):
    """PRD section 3.5: "A decision attempted from a state that does not allow
    it is rejected with `ERR_ALLOCATION_STATE` (HTTP 409); `FULFILLED`,
    `RELEASED`, `EXPIRED`, and `SHORTED` are the terminal states." and "Its
    `allocated_boxes_final` stays null until a commit fixes it."

    Design: Corner/state_machines/allocation_commit_from_released_is_rejected
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=10,
                               priority_tier="GOLD")
    fx.allocation_decision(alloc["id"], "RELEASE")
    resp = api_client.allocation_decision(alloc["id"], {"action": "COMMIT"}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_STATE)
    assert resp.status_code == 409
    frozen = fx.get_allocation(alloc["id"])
    assert frozen["status"] == "RELEASED"
    assert frozen["allocated_boxes_final"] is None
    lots = fx.list_lots(env["run"]["id"])
    assert lots[0]["boxes_on_hand"] == 125
    assert lots[0]["boxes_committed"] == 0


def test_allocation_request_expires_at_epoch_after_ship_date(api):
    """PRD section 3.5: "At the epoch, a `REQUESTED` allocation whose
    `requested_ship_date` is strictly before the logical clock becomes
    `EXPIRED`; its provisional reservation drops and the waterfall is re-run."

    Design: Corner/state_machines/allocation_request_expires_at_epoch_after_ship_date
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    a1 = fx.create_allocation(env["spec"]["id"], requested_boxes=10)
    a2 = fx.create_allocation(env["spec"]["id"], requested_boxes=20,
                              priority_tier="GOLD", retailer_name="ValueShop")
    fx.allocation_decision(a2["id"], "COMMIT")
    fx.set_clock("2027-07-16T00:00:00Z")
    tally = fx.run_epoch()
    assert tally["allocations_expired"] == 1
    assert fx.get_allocation(a1["id"])["status"] == "EXPIRED"
    assert fx.get_allocation(a2["id"])["status"] == "COMMITTED"


def test_lot_depletes_at_zero_and_revives_on_release(api):
    """PRD section 3.4: "When a deduction drives `boxes_on_hand` to 0, the lot
    flips automatically from `AVAILABLE` to `DEPLETED`; when a release returns
    boxes so that on-hand rises above 0, a `DEPLETED` lot flips back to
    `AVAILABLE`."

    Design: Corner/state_machines/lot_depletes_at_zero_and_revives_on_release
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=125)
    fx.allocation_decision(alloc["id"], "COMMIT")
    committed_lot = fx.list_lots(env["run"]["id"])[0]
    assert committed_lot["status"] == "DEPLETED"
    assert committed_lot["boxes_on_hand"] == 0
    assert committed_lot["boxes_committed"] == 125
    fx.allocation_decision(alloc["id"], "RELEASE")
    revived = fx.list_lots(env["run"]["id"])[0]
    assert revived["status"] == "AVAILABLE"
    assert revived["boxes_on_hand"] == 125
    assert revived["boxes_committed"] == 0


def test_spec_boxes_available_reconciles_after_commit_and_release(api):
    """PRD section 3.4: "Both are recomputed on run completion, on lot
    quarantine, on every allocation commit, fulfil, release, or expire, and on
    read, so the stored value always equals the lot-level sum with no drift."

    Design: Corner/calculations/spec_boxes_available_reconciles_after_commit_and_release
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    spec0 = fx.get_spec(env["spec"]["id"])
    assert spec0["boxes_available"] == 125
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=100)
    fx.allocation_decision(alloc["id"], "COMMIT")
    spec1 = fx.get_spec(env["spec"]["id"])
    assert spec1["boxes_available"] == 25
    assert spec1["boxes_reserved"] == 100
    fx.allocation_decision(alloc["id"], "RELEASE")
    spec2 = fx.get_spec(env["spec"]["id"])
    assert spec2["boxes_available"] == 125
    assert spec2["boxes_reserved"] == 0


def test_stale_spec_version_on_allocation_create_returns_412(api):
    """PRD section 2.7: "If the spec's current `version` has advanced past that
    value, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)." and "On
    success the allocation raises the spec's `boxes_reserved` and therefore
    increments the spec's `version`, so the next stale writer is rejected in
    turn."

    Design: Corner/validations/stale_spec_version_on_allocation_create_returns_412
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    spec_v = fx.get_spec_version(env["spec"]["id"])
    payload1 = {"assortment_spec_id": env["spec"]["id"], "retailer_name": "MegaMart",
                "priority_tier": "PLATINUM", "requested_boxes": 10,
                "requested_ship_date": "2027-07-15T00:00:00Z",
                "expected_assortment_spec_version": spec_v}
    first = api_client.create_retail_allocation(payload1, PLANNER)
    a1 = validate_success(first, 201)
    payload2 = dict(payload1, retailer_name="ValueShop", priority_tier="GOLD",
                    requested_boxes=5)
    resp = api_client.create_retail_allocation(payload2, PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412
    assert fx.get_allocation(a1["id"])["status"] == "REQUESTED"
    allocs = get_success_data(api_client.list_spec_allocations(env["spec"]["id"], PLANNER))
    assert len(allocs) == 1
    assert fx.get_spec(env["spec"]["id"])["version"] == spec_v + 1


def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD section 2.7: "creating a retail allocation requires the request to
    carry `expected_assortment_spec_version`, holding the `version` of the
    target assortment spec the client last observed" and "On success the
    allocation raises the spec's `boxes_reserved` and therefore increments the
    spec's `version`".

    Design: Corner/complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    fx.reset_clock()
    env = fx.production_setup()
    spec_v = fx.get_spec_version(env["spec"]["id"])
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=10)
    assert alloc["status"] == "REQUESTED"
    spec_now = fx.get_spec(env["spec"]["id"])
    assert spec_now["version"] == spec_v + 1
    assert spec_now["boxes_reserved"] == 0  # provisional share of an empty pool


def test_provisional_waterfall_excludes_runs_ending_after_season(api):
    """PRD section 3.5: "The pool is the spec's physical `boxes_available` plus
    its projected boxes, where the projection sums `planned_boxes` over the
    spec's runs whose stage is `PLANNED`, `MOLDING`, `LABELING`, `PACKING`, or
    `ON_HOLD` and whose `planned_end_date` falls on or before the season end and
    not before the current logical time."

    Design: Corner/calculations/provisional_waterfall_excludes_runs_ending_after_season
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=40,
                  planned_start_date="2027-08-20T00:00:00Z",
                  planned_end_date="2027-09-15T00:00:00Z")  # ends past season end
    fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=25)  # in-season
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=200)
    assert alloc["allocated_boxes_provisional"] == 150  # 125 on hand + 25 projected
    assert alloc["allocated_boxes_provisional"] != 190


def _setup_waterfall_divergence():
    """Color ACTIVE; spec {color:8} @1600; runs R1 COMPLETED 125 boxes,
    R2 COMPLETED 6 boxes (packed 50), R3 PLANNED 25 boxes in-season.
    boxes_available == 131; projected pool == 25."""
    env = fx.production_setup()
    r1 = fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=125)
    fx.advance_run_to_packing(r1["id"])
    env["r1"] = fx.complete_run(r1["id"], [{"color_id": env["color"]["id"], "count": 1000}])
    r2 = fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=6)
    fx.advance_run_to_packing(r2["id"])
    env["r2"] = fx.complete_run(r2["id"], [{"color_id": env["color"]["id"], "count": 50}])
    env["r3"] = fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=25)
    return env


def test_waterfall_provisional_share_includes_projected_production(api):
    """PRD section 3.5: "The pool is the spec's physical `boxes_available` plus
    its projected boxes" and "The walk then serves each allocation in rank order
    a provisional share equal to the smaller of its `requested_boxes` and the
    remaining pool". Physical 131 + projected 25 -> min(300, 156) = 156.

    Design: Difficulty/dual_variant_calc/allocation_waterfall_provisional_includes_projection_vs_final_physical_only
    """
    fx.reset_clock()
    env = _setup_waterfall_divergence()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=300)
    assert alloc["allocated_boxes_provisional"] == 156  # 131 physical + 25 projected
    assert alloc["status"] == "REQUESTED"
    assert alloc["allocated_boxes_final"] is None


def test_waterfall_final_share_uses_physical_on_hand_only(api):
    """PRD section 3.5: "`COMMIT` moves `REQUESTED` to `COMMITTED` and
    computes the final share against physical stock only — projections are
    excluded — as the smaller of `requested_boxes` and the spec's
    `boxes_available`" — min(300, 131) = 131, and the deduction
    "the physical deduction walks the spec's `AVAILABLE` and
    `DEPLETED` lots in first-in-first-out order — `created_at` ascending,
    then `lot_seq` ascending — moving boxes from `boxes_on_hand` into
    `boxes_committed` until the final amount is covered".

    Design: Difficulty/dual_variant_calc/allocation_waterfall_provisional_includes_projection_vs_final_physical_only
    """
    fx.reset_clock()
    env = _setup_waterfall_divergence()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=300)
    committed = fx.allocation_decision(alloc["id"], "COMMIT")
    assert committed["allocated_boxes_final"] == 131
    assert committed["allocated_boxes_provisional"] == 156  # the variants diverge
    assert committed["allocated_boxes_final"] != committed["allocated_boxes_provisional"]
    spec = fx.get_spec(env["spec"]["id"])
    assert spec["boxes_available"] == 0
    assert spec["boxes_reserved"] == 131
    lots1 = fx.list_lots(env["r1"]["id"])
    assert lots1[0]["boxes_committed"] == 125
    assert lots1[0]["boxes_on_hand"] == 0
    lots2 = fx.list_lots(env["r2"]["id"])
    assert lots2[0]["boxes_committed"] == 6
    assert lots2[0]["boxes_on_hand"] == 0


def test_lot_boxes_commit_then_release_restores_exactly(api):
    """PRD section 3.5: "from `COMMITTED` it returns `allocated_boxes_final` to
    the lots in first-in-first-out order, each lot regaining up to its own
    `boxes_committed` — the smaller of the remaining return and that
    lot's committed count — from committed back to on-hand, and any
    `DEPLETED` lot whose on-hand rises above 0 becomes `AVAILABLE` again;
    the lot-level mass balance must hold exactly afterwards."

    Design: Difficulty/compensating_invariant/lot_boxes_commit_release_mass_balance
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=100)
    fx.allocation_decision(alloc["id"], "COMMIT")
    lot = fx.list_lots(env["run"]["id"])[0]
    assert lot["boxes_on_hand"] == 25
    assert lot["boxes_committed"] == 100
    assert lot["boxes_shipped"] == 0
    assert_lot_mass_balance(lot)
    fx.allocation_decision(alloc["id"], "RELEASE")
    restored = fx.list_lots(env["run"]["id"])[0]
    assert restored["boxes_on_hand"] == 125
    assert restored["boxes_committed"] == 0
    assert restored["boxes_shipped"] == 0
    assert_lot_mass_balance(restored)


def test_lot_boxes_commit_fulfill_ships_and_reconciles(api):
    """PRD section 3.5: "`FULFILL` moves `COMMITTED` to `FULFILLED`, walking the
    spec's lots in `created_at` ascending order to move `allocated_boxes_final`
    boxes from `boxes_committed` to `boxes_shipped`." — after COMMIT 60 then
    FULFILL: on-hand 65, committed 0, shipped 60; 65 + 0 + 60 == 125.

    Design: Difficulty/compensating_invariant/lot_boxes_commit_release_mass_balance
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    a1 = fx.create_allocation(env["spec"]["id"], requested_boxes=100)
    fx.allocation_decision(a1["id"], "COMMIT")
    fx.allocation_decision(a1["id"], "RELEASE")
    a2 = fx.create_allocation(env["spec"]["id"], requested_boxes=60,
                              priority_tier="GOLD", retailer_name="ValueShop")
    fx.allocation_decision(a2["id"], "COMMIT")
    fx.allocation_decision(a2["id"], "FULFILL")
    lot = fx.list_lots(env["run"]["id"])[0]
    assert lot["boxes_on_hand"] == 65
    assert lot["boxes_committed"] == 0
    assert lot["boxes_shipped"] == 60
    assert_lot_mass_balance(lot)
    spec = fx.get_spec(env["spec"]["id"])
    assert spec["boxes_available"] == 65
    assert spec["boxes_reserved"] == 0
