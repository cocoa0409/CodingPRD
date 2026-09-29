"""Depth scenarios over cross-entity state gates, the two opposite interval
conventions, and the two explicitly compensating operations: a light gated on a
pile it does not own, grinding gated on a verdict the laboratory owns, closed
kiln-run windows against half-open loadout windows, and the exact restoration of
the cement balance and the NOx budget.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_intensity
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_lighting_a_kiln_requires_the_blended_pile_to_be_sealed(api):
    """Nothing about the run itself is wrong — it is SCHEDULED on an AVAILABLE kiln inside
    its own window — yet the light is refused because the bed it will consume is still
    OPEN; sealing that other entity makes the identical call succeed and flips the pile
    straight to CONSUMED.

    PRD: "Lighting requires the run's pile to be `SEALED`, else `ERR_INVALID_PILE_STATE`
    (409)."

    Design: Difficulty/cross_entity_state_dependency/lighting_a_kiln_requires_the_blended_pile_to_be_sealed
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_open_pile(api, env["plant_id"], design["id"], pile_code="PA")
    fx.add_reference_additions(api, pile["id"], env["materials"])
    run = fx.create_scheduled_run(
        api, env["kiln"]["id"], pile["id"], env["clinker_silo"]["id"]
    )
    run_id = run["id"]

    unsealed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert unsealed["status"] == "OPEN"
    assert_amount(unsealed["as_received_tonnes"], 1041.28, "as_received_tonnes")
    assert_amount(unsealed["dry_tonnes"], 1000.00, "dry_tonnes")

    assert run["process_state"] == "SCHEDULED"
    assert run["quality_state"] == "PENDING_LAB"
    kiln_before = validate_success(api.get_kiln(env["kiln"]["id"], OPERATOR_HEADERS))
    assert kiln_before["availability_state"] == "AVAILABLE"

    validate_error(
        api.light_kiln_run(run_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_INVALID_PILE_STATE.value,
        409,
    )

    untouched = validate_success(api.get_kiln_run(run_id, OPERATOR_HEADERS))
    assert untouched["process_state"] == "SCHEDULED"
    assert untouched["lit_at"] is None
    kiln_after = validate_success(api.get_kiln(env["kiln"]["id"], OPERATOR_HEADERS))
    assert kiln_after["availability_state"] == "AVAILABLE"

    sealed = validate_success(api.seal_pile(pile["id"], ENGINEER_HEADERS))
    assert sealed["status"] == "SEALED"

    lit = validate_success(api.light_kiln_run(run_id, OPERATOR_HEADERS))
    assert lit["process_state"] == "BURNING"

    consumed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert consumed["status"] == "CONSUMED"


def test_grinding_is_gated_on_a_feed_state_owned_by_another_entitys_quality_verdict(api):
    """The clinker is physically in the silo and the silo is OPEN, so neither
    ERR_INSUFFICIENT_CLINKER nor ERR_SILO_BLOCKED can be the answer: what stops grinding is
    the batch's own feed_state, which a free-lime reading on a kiln run three entities away
    pushed to FEED_SHORT.

    PRD: "It requires `feed_state` to be `FEED_READY`, else `ERR_BATCH_FEED_SHORT` — this is
    the check that stops a batch whose clinker was quietly pulled out from under it — and
    requires both the clinker and the cement silo to be `OPEN`, else `ERR_SILO_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/grinding_is_gated_on_a_feed_state_owned_by_a_different_entitys_quality_verdict
    """
    env = fx.released_clinker_environment(api)
    silo_id = env["clinker_silo"]["id"]
    run_id = env["run"]["id"]
    batch = fx.create_planned_batch(
        api,
        env["plant_id"],
        silo_id,
        env["cement_silo"]["id"],
        clinker_tonnes_drawn=500.00,
    )
    batch_id = batch["id"]
    assert batch["feed_state"] == "FEED_READY"
    assert batch["status"] == "PLANNED"

    withdrawal = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.62, kiln_run_id=run_id), LAB_HEADERS
        ),
        201,
    )
    assert withdrawal["in_spec"] is False

    stranded = validate_success(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert stranded["feed_state"] == "FEED_SHORT"
    assert stranded["status"] == "PLANNED"
    assert_amount(stranded["clinker_tonnes_drawn"], 500.00, "clinker_tonnes_drawn")

    silo = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert silo["status"] == "OPEN"
    assert_amount(silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")

    validate_error(
        api.start_grinding(batch_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_BATCH_FEED_SHORT.value,
        409,
    )

    fx.record_free_lime(api, run_id, 1.40)
    validate_success(api.release_clinker(run_id, QUALITY_HEADERS))

    recovered = validate_success(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert recovered["feed_state"] == "FEED_READY"

    ground = validate_success(api.start_grinding(batch_id, OPERATOR_HEADERS))
    assert ground["status"] == "GRINDING"


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_kiln_run_windows_are_closed_intervals_so_touching_windows_conflict(api):
    """A second run on K1 starting at exactly the instant R0 ends shares only that single
    instant, and is still refused; one second later it is accepted, and the same touching
    window on a different kiln is accepted too, so the rule is a closed-interval rule
    scoped to one kiln rather than a blanket ban on adjacency.

    PRD: "For this comparison, and for this comparison only, run windows are treated as
    **closed on both ends**: two runs that merely touch at a single instant still conflict,
    because a rotary kiln cannot be emptied and recharged instantaneously."

    Design: Difficulty/resource_temporal_overlap/kiln_run_windows_are_closed_intervals_so_touching_windows_conflict
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    kiln_id = env["kiln"]["id"]
    silo_id = env["clinker_silo"]["id"]
    other_kiln = fx.create_kiln(api, env["plant_id"], code="K2")
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile_a = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PA"
    )
    pile_b = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PB"
    )
    pile_c = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PC"
    )

    first = fx.create_scheduled_run(
        api,
        kiln_id,
        pile_a["id"],
        silo_id,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    assert first["process_state"] == "SCHEDULED"
    assert_amount(first["scheduled_hours"], 12.00, "scheduled_hours")

    validate_error(
        api.create_kiln_run(
            f.kiln_run_payload(
                kiln_id,
                pile_b["id"],
                silo_id,
                "2026-08-01T12:00:00Z",
                "2026-08-02T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_KILN_WINDOW_CONFLICT.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_kiln_runs(OPERATOR_HEADERS, params={"kiln_id": kiln_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]

    # The very same touching window is free on another kiln: the resource is the kiln.
    on_other_kiln = validate_success(
        api.create_kiln_run(
            f.kiln_run_payload(
                other_kiln["id"],
                pile_b["id"],
                silo_id,
                "2026-08-01T12:00:00Z",
                "2026-08-02T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert on_other_kiln["process_state"] == "SCHEDULED"

    # One second of clearance on K1 is enough, which pins the closed upper end.
    clear = validate_success(
        api.create_kiln_run(
            f.kiln_run_payload(
                kiln_id,
                pile_c["id"],
                silo_id,
                "2026-08-01T12:00:01Z",
                "2026-08-02T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert clear["process_state"] == "SCHEDULED"


def test_a_completed_run_still_blocks_a_window_that_touches_it(api):
    """The overlap comparison reads COMPLETED runs as well as live ones, so the touching
    window is still refused after R0 has finished burning and its kiln is idle again.

    PRD: "Second, the new window must not overlap the window of any other run on the same
    kiln whose `process_state` is `SCHEDULED`, `BURNING` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/kiln_run_windows_are_closed_intervals_so_touching_windows_conflict
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    kiln_id = env["kiln"]["id"]
    silo_id = env["clinker_silo"]["id"]
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile_a = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PA"
    )
    pile_b = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PB"
    )

    finished = fx.create_completed_run(
        api, kiln_id, pile_a["id"], silo_id, env["fuels"]["gas"]["id"], 45.00
    )
    assert finished["process_state"] == "COMPLETED"

    validate_error(
        api.create_kiln_run(
            f.kiln_run_payload(
                kiln_id,
                pile_b["id"],
                silo_id,
                "2026-08-01T12:00:00Z",
                "2026-08-02T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_KILN_WINDOW_CONFLICT.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_kiln_runs(OPERATOR_HEADERS, params={"kiln_id": kiln_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_adjacent_loadout_windows_are_free_but_a_straddling_one_exhausts_the_spouts(api):
    """Loadout windows are compared half-open, so an appointment beginning exactly when
    another ends is accepted on the same two-spout silo; an appointment that straddles both
    of them overlaps two live orders and is refused. Voiding one of them frees the spout and
    the identical straddling request then succeeds.

    PRD: "the overlap count must stay strictly below the silo's `loadout_spouts`, else
    `ERR_SILO_SPOUT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/loadout_windows_are_half_open_and_spout_capacity_is_an_aggregate_over_overlaps
    """
    env = fx.certificate_chain(api)
    silo_id = env["cement_silo"]["id"]
    customer_id = env["customer"]["id"]
    certificate_id = env["certificate"]["id"]

    def reserve(window_start: str, window_end: str, tonnes: float):
        """Reserve an appointment, echoing the certificate version read just beforehand."""
        certificate = fx.data_of(
            api.get_mill_certificate(certificate_id, LOGISTICS_HEADERS)
        )
        return api.create_loadout_order(
            f.loadout_order_payload(
                customer_id,
                silo_id,
                certificate_id,
                certificate["version"],
                window_start=window_start,
                window_end=window_end,
                tonnes=tonnes,
            ),
            LOGISTICS_HEADERS,
        )

    first = validate_success(api.get_loadout_order(env["order"]["id"], LOGISTICS_HEADERS))
    assert first["status"] == "RESERVED"
    assert_amount(first["scheduled_hours"], 2.00, "scheduled_hours")

    # [08:00, 10:00) begins exactly where [06:00, 08:00) ends, so they do not overlap.
    second = validate_success(
        reserve("2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z", 120.00), 201
    )
    assert second["status"] == "RESERVED"
    assert_amount(second["scheduled_hours"], 2.00, "scheduled_hours")

    silo = validate_success(api.get_silo(silo_id, LOGISTICS_HEADERS))
    assert_amount(silo["reserved_tonnes"], 240.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 334.72, "available_tonnes")

    customer = validate_success(api.get_customer(customer_id, LOGISTICS_HEADERS))
    assert_amount(customer["open_reserved_tonnes"], 240.00, "open_reserved_tonnes")

    # [07:00, 09:00) genuinely overlaps both, so the overlap count reaches the spout count.
    validate_error(
        reserve("2026-08-05T07:00:00Z", "2026-08-05T09:00:00Z", 120.00),
        ApiErrorId.ERR_SILO_SPOUT_CAPACITY.value,
    )

    rows, meta = validate_paginated(
        api.list_loadout_orders(LOGISTICS_HEADERS, params={"cement_silo_id": silo_id})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2

    unchanged = validate_success(api.get_silo(silo_id, LOGISTICS_HEADERS))
    assert_amount(unchanged["reserved_tonnes"], 240.00, "reserved_tonnes")

    voided = validate_success(
        api.void_loadout_order(
            second["id"],
            {"void_reason": "customer cancelled the second truck"},
            LOGISTICS_HEADERS,
        )
    )
    assert voided["status"] == "VOIDED"

    # A VOIDED order is no longer counted, so the same straddling window is now free.
    third = validate_success(
        reserve("2026-08-05T07:00:00Z", "2026-08-05T09:00:00Z", 120.00), 201
    )
    assert third["status"] == "RESERVED"


def test_a_loadout_order_over_the_hourly_draw_rate_is_refused(api):
    """The second limb of the terminal capacity rung is arithmetic rather than
    combinatorial: a one-hour appointment on a 250 tonne-per-hour spout cannot promise
    300.00 tonnes, however much cement is standing available in the silo.

    PRD: "And the order's own `tonnes` must be no greater than the silo's
    `draw_rate_tonnes_per_hour` multiplied by the order's `scheduled_hours`, rounded half up
    to two decimals, else `ERR_DRAW_RATE_EXCEEDED`"

    Design: Difficulty/resource_temporal_overlap/loadout_windows_are_half_open_and_spout_capacity_is_an_aggregate_over_overlaps
    """
    env = fx.certificate_chain(api)
    silo_id = env["cement_silo"]["id"]
    certificate = fx.data_of(
        api.get_mill_certificate(env["certificate"]["id"], LOGISTICS_HEADERS)
    )

    silo = validate_success(api.get_silo(silo_id, LOGISTICS_HEADERS))
    assert_amount(silo["draw_rate_tonnes_per_hour"], 250.00, "draw_rate_tonnes_per_hour")
    assert_amount(silo["available_tonnes"], 454.72, "available_tonnes")

    # 300.00 is comfortably covered by the 454.72 available and by the certificate's
    # remaining 454.72, but 250.00 * 1.00 = 250.00 is all one hour can move.
    validate_error(
        api.create_loadout_order(
            f.loadout_order_payload(
                env["customer"]["id"],
                silo_id,
                env["certificate"]["id"],
                certificate["version"],
                window_start="2026-08-05T07:00:00Z",
                window_end="2026-08-05T08:00:00Z",
                tonnes=300.00,
            ),
            LOGISTICS_HEADERS,
        ),
        ApiErrorId.ERR_DRAW_RATE_EXCEEDED.value,
    )

    rows, meta = validate_paginated(
        api.list_loadout_orders(LOGISTICS_HEADERS, params={"cement_silo_id": silo_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------
def test_voiding_a_completed_loadout_restores_the_plant_cement_balance_with_no_drift(api):
    """574.72 tonnes of cement stay 574.72 tonnes through the whole shipment: standing in
    the silo before loading, split 454.72 in the silo plus 120.00 shipped after completion,
    and back to 574.72 in the silo once the completed order is voided — with the customer's
    lifetime ledger and the certificate's allocation walked back too.

    PRD: "Completing a loadout order leaves this balance unchanged because it moves tonnes
    from silo stock into shipped stock, and voiding a completed order leaves it unchanged
    because it moves them back"

    Design: Difficulty/compensating_invariant/voiding_a_completed_loadout_restores_the_plant_cement_balance_with_no_drift
    """
    env = fx.certificate_chain(api)
    plant_id = env["plant_id"]
    silo_id = env["cement_silo"]["id"]
    order_id = env["order"]["id"]
    customer_id = env["customer"]["id"]

    before = validate_success(api.get_plant(plant_id, LOGISTICS_HEADERS))
    assert_amount(
        before["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )

    fx.set_clock(api, "2026-08-05T06:00:00Z")
    loading = validate_success(api.start_loading(order_id, LOGISTICS_HEADERS))
    assert loading["status"] == "LOADING"

    completed = validate_success(
        api.complete_loadout_order(order_id, {"loaded_tonnes": 120.00}, LOGISTICS_HEADERS)
    )
    assert completed["status"] == "COMPLETED"
    assert_amount(completed["loaded_tonnes"], 120.00, "loaded_tonnes")

    shipped_silo = validate_success(api.get_silo(silo_id, LOGISTICS_HEADERS))
    assert_amount(shipped_silo["tonnes_on_hand"], 454.72, "tonnes_on_hand")
    assert_amount(shipped_silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(shipped_silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(shipped_silo["available_tonnes"], 454.72, "available_tonnes")

    shipped_customer = validate_success(api.get_customer(customer_id, LOGISTICS_HEADERS))
    assert_amount(
        shipped_customer["open_reserved_tonnes"], 0.00, "open_reserved_tonnes"
    )
    assert_amount(
        shipped_customer["lifetime_loaded_tonnes"], 120.00, "lifetime_loaded_tonnes"
    )

    mid = validate_success(api.get_plant(plant_id, LOGISTICS_HEADERS))
    assert_amount(
        mid["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )

    voided = validate_success(
        api.void_loadout_order(
            order_id,
            {"void_reason": "truck rejected at the customer gate"},
            LOGISTICS_HEADERS,
        )
    )
    assert voided["status"] == "VOIDED"
    assert_amount(voided["loaded_tonnes"], 0.00, "loaded_tonnes")

    restored_silo = validate_success(api.get_silo(silo_id, LOGISTICS_HEADERS))
    assert_amount(restored_silo["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(restored_silo["available_tonnes"], 574.72, "available_tonnes")

    restored_customer = validate_success(api.get_customer(customer_id, LOGISTICS_HEADERS))
    assert_amount(
        restored_customer["lifetime_loaded_tonnes"], 0.00, "lifetime_loaded_tonnes"
    )

    after = validate_success(api.get_plant(plant_id, LOGISTICS_HEADERS))
    assert_amount(
        after["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )

    # The voided order leaves the {RESERVED, LOADING, COMPLETED} input set.
    certificate = validate_success(
        api.get_mill_certificate(env["certificate"]["id"], QUALITY_HEADERS)
    )
    assert_amount(certificate["allocated_tonnes"], 0.00, "allocated_tonnes")


def test_aborting_a_burning_run_returns_the_annual_nox_budget_to_its_pre_charge_value(api):
    """80 tonnes of coal draw 756.00 kilograms out of the annual allowance the instant they
    are charged; aborting the run gives every kilogram back exactly, leaves the fuel record
    standing as evidence, credits no clinker at all, and returns the rolling intensity to
    0.000 — while the raw meal stays gone.

    PRD: "The compensation is exact: the run's `nox_emitted_kg` is set to 0 and its
    `clinker_tonnes` is set to 0"

    Design: Difficulty/compensating_invariant/aborting_a_burning_run_returns_the_annual_nox_budget_to_its_pre_charge_value
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    plant_id = env["plant_id"]
    silo_id = env["clinker_silo"]["id"]
    design = fx.create_approved_design(api, plant_id, env["materials"])
    pile = fx.create_sealed_pile(api, plant_id, design["id"], env["materials"])

    opening = validate_success(api.get_plant(plant_id, OPERATOR_HEADERS))
    assert_amount(
        opening["permit_nox_budget_remaining_kg"],
        2000000.00,
        "permit_nox_budget_remaining_kg",
    )

    run = fx.create_burning_run(api, env["kiln"]["id"], pile["id"], silo_id)
    run_id = run["id"]

    charged = validate_success(
        api.charge_fuel(
            run_id,
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 80.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(charged["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(charged["nox_emitted_kg"], 756.00, "nox_emitted_kg")
    assert_amount(charged["clinker_tonnes"], 583.78, "clinker_tonnes")

    spent = validate_success(api.get_plant(plant_id, OPERATOR_HEADERS))
    assert_amount(
        spent["permit_nox_budget_remaining_kg"],
        1999244.00,
        "permit_nox_budget_remaining_kg",
    )

    aborted = validate_success(
        api.abort_kiln_run(
            run_id, {"abort_reason": "preheater tower blockage"}, OPERATOR_HEADERS
        )
    )
    assert aborted["process_state"] == "ABORTED"
    assert aborted["abort_reason"] == "preheater tower blockage"
    assert_amount(aborted["nox_emitted_kg"], 0.00, "nox_emitted_kg")
    assert_amount(aborted["clinker_tonnes"], 0.00, "clinker_tonnes")
    # The fuel record itself survives the compensation.
    assert_amount(aborted["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert len(aborted["fuel_charges"]) == 1

    restored = validate_success(api.get_plant(plant_id, OPERATOR_HEADERS))
    assert_amount(
        restored["permit_nox_budget_remaining_kg"],
        2000000.00,
        "permit_nox_budget_remaining_kg",
    )
    assert_intensity(
        restored["rolling_nox_intensity_kg_per_tonne"], 0.000, "rolling_nox_intensity"
    )

    silo = validate_success(api.get_silo(silo_id, OPERATOR_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 0.00, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")

    # The permit ledger is restored; the raw meal is not.
    consumed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert consumed["status"] == "CONSUMED"
