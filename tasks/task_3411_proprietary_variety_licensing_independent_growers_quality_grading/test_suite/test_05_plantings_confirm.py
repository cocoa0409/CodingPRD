"""Plantings: confirm-time computed fields, quota/lot/window-capacity gates,
temporal gates, ownership, and the state-vs-quota priority pair."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    confirm_planting_payload,
    CLOCK_PLANT, PLANTED_ON,
    set_clock, create_grower, create_active_agreement, create_released_variety,
    create_plant_lot, plan_planting, confirm_planting, get_planting,
    get_agreement, get_plant_lot, get_harvest_window, create_harvest_window,
    setup_active_agreement, setup_planting_planned, setup_planting_confirmed,
    suspend_grower, make_grower_principal_headers, get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_planting_confirm_computes_yield_harvest_date_and_window(api):
    """PRD section 3.5: "The `expected_first_harvest` is `planted_on` advanced by
    the maturation period of the lot's berry type: 60 days for `STRAWBERRY`".
    PRD section 3.5: "The `expected_yield_kg` is `plants_planted_actual`
    multiplied by the per-plant yield of that berry type: 2.5 kg for
    `STRAWBERRY`".
    PRD section 3.5: "the planting's `harvest_window_id` is set to the booked
    window, whose `booked_volume_kg` increases by `expected_yield_kg`".

    Design: Corner/entities/planting_confirm_computes_yield_harvest_date_and_window
    """
    bundle = setup_planting_confirmed()  # 1500 strawberry plants on 2026-08-01
    planting = bundle["planting"]
    assert planting["status"] == "PLANTED"
    assert planting["expected_first_harvest"].startswith("2026-09-30T00:00:00")
    assert planting["expected_yield_kg"] == 3750.0
    assert planting["harvest_window_id"] == bundle["window"]["id"]
    window = get_harvest_window(bundle["window"]["id"])
    assert window["booked_volume_kg"] == 3750.0
    lot = get_plant_lot(bundle["lot"]["id"])
    assert lot["plants_reserved"] == 0
    assert lot["plants_planted"] == 1500
    assert lot["plants_available"] == 500
    assert lot["status"] == "PLANTED"


def test_confirm_without_covering_window_rejected(api):
    """PRD section 3.5: "the window-overlap rule guarantees at most one such
    window exists, and when none exists the confirmation is rejected with
    `ERR_NO_HARVEST_WINDOW`."

    Design: Corner/validations/confirm_without_covering_window_rejected
    """
    bundle = setup_planting_planned()  # no harvest window exists
    set_clock(CLOCK_PLANT)
    resp = api.confirm_planting(
        bundle["planting"]["id"], confirm_planting_payload(),
        make_grower_principal_headers(bundle["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_HARVEST_WINDOW)
    planting = get_planting(bundle["planting"]["id"])
    assert planting["status"] == "PLANNED"
    lot = get_plant_lot(bundle["lot"]["id"])
    assert lot["plants_reserved"] == 1500


def test_planted_on_outside_agreement_window_rejected(api):
    """PRD section 3.5: "`planted_on` must fall inside the agreement window —
    on or after `effective_from` and on or before `effective_to`
    (`ERR_PLANTING_WINDOW_VIOLATION`)".

    Design: Corner/validations/planted_on_outside_agreement_window_rejected
    """
    bundle = setup_planting_planned()  # agreement [2026-01-01, 2027-12-31]
    create_harvest_window(bundle["variety"],
                          week_start="2028-03-01T00:00:00Z",
                          week_end="2028-03-08T00:00:00Z",
                          target_volume_kg=100000)
    set_clock("2028-01-10T00:00:00Z")
    resp = api.confirm_planting(
        bundle["planting"]["id"],
        confirm_planting_payload(planted_on="2028-01-05T00:00:00Z"),
        make_grower_principal_headers(bundle["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PLANTING_WINDOW_VIOLATION)
    planting = get_planting(bundle["planting"]["id"])
    assert planting["status"] == "PLANNED"


def test_quota_boundary_exactly_max_then_over(api):
    """PRD section 3.5: "The quota gate requires `plants_planted_actual` to be
    no greater than `max_planting_units` minus `units_planted`
    (`ERR_PLANTING_QUOTA_EXCEEDED`)".

    Design: Corner/errors/quota_boundary_exactly_max_then_over
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    agreement = create_active_agreement(grower, variety, max_planting_units=100,
                                        cultural_practice_codes=["ORGANIC"])
    lot = create_plant_lot(agreement, variety, quantity_plants=200)
    create_harvest_window(variety)
    p1 = plan_planting(agreement, lot, grower, planned_plants=100)
    p2 = plan_planting(agreement, lot, grower, planned_plants=1)
    set_clock(CLOCK_PLANT)
    confirmed = confirm_planting(p1, grower, 100)
    assert confirmed["status"] == "PLANTED"
    current = get_agreement(agreement["id"])
    assert current["units_planted"] == 100 == current["max_planting_units"]
    resp = api.confirm_planting(
        p2["id"], confirm_planting_payload(plants_planted_actual=1),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_PLANTING_QUOTA_EXCEEDED)
    assert get_planting(p2["id"])["status"] == "PLANNED"
    assert get_agreement(agreement["id"])["units_planted"] == 100


def test_window_capacity_cap_boundary(api):
    """PRD section 3.5: "the capacity gate requires the window's
    `booked_volume_kg` plus the planting's `expected_yield_kg` to stay within
    120% of the window's `target_volume_kg` — an inclusive bound, so landing
    exactly on the oversubscription limit passes —
    (`ERR_WINDOW_CAPACITY_EXCEEDED`)".

    Design: Corner/calculations/window_capacity_cap_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement(
        agreement_overrides={"max_planting_units": 10000})
    lot = create_plant_lot(agreement, variety, quantity_plants=2000)
    window = create_harvest_window(variety, target_volume_kg=1000)
    pa = plan_planting(agreement, lot, grower, planned_plants=480)
    pb = plan_planting(agreement, lot, grower, planned_plants=80)
    set_clock(CLOCK_PLANT)
    confirmed = confirm_planting(pa, grower, 480)  # 480 x 2.5 = 1200.0 == cap
    assert confirmed["status"] == "PLANTED"
    assert get_harvest_window(window["id"])["booked_volume_kg"] == 1200.0
    resp = api.confirm_planting(
        pb["id"], confirm_planting_payload(plants_planted_actual=80),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED)
    assert get_planting(pb["id"])["status"] == "PLANNED"
    assert get_harvest_window(window["id"])["booked_volume_kg"] == 1200.0


def _setup_suspended_agreement_with_oversized_planting(api):
    """A7 max 100 approved then SUSPENDED via grower suspend; lot 500; P7
    planned 150 (creation does not check the quota — only confirm does)."""
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="Half Moon Bay Fruit")
    agreement = create_active_agreement(grower, variety, max_planting_units=100,
                                        cultural_practice_codes=["CONVENTIONAL"])
    lot = create_plant_lot(agreement, variety, quantity_plants=500)
    planting = plan_planting(agreement, lot, grower, planned_plants=150)
    suspend_grower(grower["id"], reason="audit hold")
    set_clock(CLOCK_PLANT)
    return grower, agreement, planting


def test_confirm_state_gate_beats_quota_gate(api):
    """PRD section 2.8: "the system evaluates the following tiers in order and
    reports the first failure encountered" — state gates (tier 7, HTTP 409)
    precede quotas and aggregate gates (tier 11).
    PRD section 3.5: "The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_gate_beats_quota_gate
    """
    grower, agreement, planting = _setup_suspended_agreement_with_oversized_planting(api)
    resp = api.confirm_planting(
        planting["id"],
        confirm_planting_payload(plants_planted_actual=150),
        make_grower_principal_headers(grower["id"]))
    err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert err["error_id"] != "ERR_PLANTING_QUOTA_EXCEEDED"
    assert get_planting(planting["id"])["status"] == "PLANNED"
    assert get_agreement(agreement["id"])["units_planted"] == 0


def test_confirm_quota_gate_fires_alone_when_agreement_active(api):
    """PRD section 3.5: "The quota gate requires `plants_planted_actual` to be
    no greater than `max_planting_units` minus `units_planted`
    (`ERR_PLANTING_QUOTA_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_gate_beats_quota_gate
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="Half Moon Bay Fruit")
    agreement = create_active_agreement(grower, variety, max_planting_units=100,
                                        cultural_practice_codes=["CONVENTIONAL"])
    lot = create_plant_lot(agreement, variety, quantity_plants=500)
    create_harvest_window(variety, target_volume_kg=100000)
    planting = plan_planting(agreement, lot, grower, planned_plants=150)
    set_clock(CLOCK_PLANT)
    resp = api.confirm_planting(
        planting["id"],
        confirm_planting_payload(plants_planted_actual=150),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_PLANTING_QUOTA_EXCEEDED)
    assert get_planting(planting["id"])["status"] == "PLANNED"


def test_grower_confirming_another_growers_planting_rejected(api):
    """PRD section 2.1: "ownership checks on any resource that references a
    `Grower` — an agreement, a planting through its agreement, a harvest lot
    through its planting's agreement, or a settlement statement — compare the
    resource chain's grower foreign key to `X-User-ID`, and a mismatch is
    rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403)."

    Design: Corner/validations/grower_confirming_another_growers_planting_rejected
    """
    bundle = setup_planting_planned()
    other = create_grower(legal_name="Coastal Berry Co")
    set_clock(CLOCK_PLANT)
    resp = api.confirm_planting(
        bundle["planting"]["id"], confirm_planting_payload(),
        make_grower_principal_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWN_RESOURCE)
    assert get_planting(bundle["planting"]["id"])["status"] == "PLANNED"
