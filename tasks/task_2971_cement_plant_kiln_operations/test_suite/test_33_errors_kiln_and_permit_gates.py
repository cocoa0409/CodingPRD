"""Breadth coverage of the refusals that guard the kiln: the two gates on lighting, the two
geometries of the outage-clearance rule, the trial-burn authorisation a charge needs, the annual
NOx budget it spends, and the clinker capacity a completion has to fit into.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals, assert_int
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    OPERATOR_HEADERS,
)


def _sealed_bed(api):
    """Plant, catalogue, kiln, clinker silo and one `SEALED` 1000.00 dry tonne bed, with the
    clock parked on the opening instant of the reference firing window."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    env["design"] = fx.create_approved_design(api, env["plant_id"], env["materials"])
    env["pile"] = fx.create_sealed_pile(
        api, env["plant_id"], env["design"]["id"], env["materials"]
    )
    assert env["pile"]["status"] == "SEALED"
    return env


def _burning_run_on_gas(api, env=None):
    """The canonical burning run: 45.00 tonnes of natural gas, 2160.00 GJ, no substitution."""
    env = env if env is not None else _sealed_bed(api)
    run = fx.create_burning_run(
        api, env["kiln"]["id"], env["pile"]["id"], env["clinker_silo"]["id"]
    )
    assert run["process_state"] == "BURNING"
    charged = validate_success(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["gas"]["id"], 45.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(charged["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(charged["tsr_pct"], 0.00, "tsr_pct")
    env["run"] = charged
    return env


# ---------------------------------------------------------------------------
# errors: the firing window is entered inclusively and left exclusively
# ---------------------------------------------------------------------------
def test_lighting_before_the_firing_window_opens_is_refused(api):
    """A run booked for the tenth cannot be lit on the first, and the refusal must leave the feed
    alone: lighting is what consumes a pile, so a bed that is still `SEALED` afterwards is the
    proof that nothing partial was applied. The run whose window opens at this very instant then
    lights, because the window is entered inclusively.

    PRD: "And the logical clock must be inside the half-open firing window, at or after
    `window_start` and strictly before `window_end`, else `ERR_RUN_WINDOW_NOT_ACTIVE`."

    Design: Corner/errors/lighting_a_kiln_outside_its_window_or_while_unavailable_is_rejected
    """
    env = _sealed_bed(api)
    later = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        env["pile"]["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-10T12:00:00Z",
    )
    assert later["process_state"] == "SCHEDULED"

    validate_error(
        api.light_kiln_run(later["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_RUN_WINDOW_NOT_ACTIVE.value,
        422,
    )

    unmoved = validate_success(api.get_kiln_run(later["id"], OPERATOR_HEADERS))
    assert unmoved["process_state"] == "SCHEDULED"
    assert unmoved["lit_at"] is None
    intact = validate_success(api.get_pile(env["pile"]["id"], ENGINEER_HEADERS))
    assert intact["status"] == "SEALED"

    now = fx.create_scheduled_run(
        api, env["kiln"]["id"], env["pile"]["id"], env["clinker_silo"]["id"]
    )
    lit = validate_success(api.light_kiln_run(now["id"], OPERATOR_HEADERS))
    assert lit["process_state"] == "BURNING"
    assert_instant_equals(lit["lit_at"], "2026-08-01T00:00:00Z", "lit_at")

    consumed = validate_success(api.get_pile(env["pile"]["id"], ENGINEER_HEADERS))
    assert consumed["status"] == "CONSUMED"


def test_a_kiln_already_burning_refuses_the_next_light_before_the_window_is_read(api):
    """Two faults are true of the second run at once — the kiln is occupied and the clock is
    nowhere near its window — and the busy kiln must answer, because that gate is the earlier one.
    Freeing the kiln by aborting the first run does not make the second one legal; it merely lets
    the later gate speak, which is what proves the ordering rather than a coincidence.

    PRD: "The kiln's `availability_state` must be `AVAILABLE` and no other run on that kiln may be
    `BURNING`, else `ERR_KILN_UNAVAILABLE` — this is where a `RELINE_DUE` or `IN_OUTAGE` kiln
    refuses work."

    Design: Corner/errors/lighting_a_kiln_outside_its_window_or_while_unavailable_is_rejected
    """
    env = _sealed_bed(api)
    burning = fx.create_burning_run(
        api, env["kiln"]["id"], env["pile"]["id"], env["clinker_silo"]["id"]
    )
    assert burning["process_state"] == "BURNING"

    # Lighting the first run consumed the first bed and aborting never returns it
    # (PRD 3.5), so the queued run is fed from a second sealed pile. That keeps the
    # pile rung at priority 67 satisfied and leaves the window rung as the only
    # remaining fault once the kiln is free.
    second_bed = fx.create_sealed_pile(
        api, env["plant_id"], env["design"]["id"], env["materials"], pile_code="PB"
    )
    assert second_bed["status"] == "SEALED"

    queued = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        second_bed["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T12:00:00Z",
    )
    validate_error(
        api.light_kiln_run(queued["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_KILN_UNAVAILABLE.value,
        409,
    )

    waiting = validate_success(api.get_kiln_run(queued["id"], OPERATOR_HEADERS))
    assert waiting["process_state"] == "SCHEDULED"
    assert waiting["lit_at"] is None

    _rows, meta = validate_paginated(
        api.list_kiln_runs(
            OPERATOR_HEADERS,
            params={"kiln_id": env["kiln"]["id"], "process_state": "BURNING"},
        )
    )
    assert meta["total_count"] == 1, "one kiln fires one run at a time"

    aborted = validate_success(
        api.abort_kiln_run(
            burning["id"], {"abort_reason": "preheater tower blockage"}, OPERATOR_HEADERS
        )
    )
    assert aborted["process_state"] == "ABORTED"

    validate_error(
        api.light_kiln_run(queued["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_RUN_WINDOW_NOT_ACTIVE.value,
        422,
    )


# ---------------------------------------------------------------------------
# errors: the outage-clearance rule has two geometries and one code
# ---------------------------------------------------------------------------
def test_an_outage_inside_a_scheduled_runs_cooldown_shadow_is_refused(api):
    """The run ends at noon and the kiln needs twelve hours to cool, so a window opening at six
    in the evening is inside the shadow the run casts and is refused. The refusal is the window
    conflict and not the peak-season objection, even though August is a peak month and the caller
    is an engineer carrying an override they are not entitled to use: the clearance rule sits
    higher up the ladder. Nothing is booked.

    PRD: "Both at planning time and again at approval time, the outage window must keep
    `cooldown_buffer_hours` of clearance from the window of every run on that kiln whose
    `process_state` is `SCHEDULED` or `BURNING`, and must not overlap — on a half-open comparison,
    so windows that merely touch are fine — the window of any other outage on that kiln whose
    `status` is `PLANNED`, `APPROVED` or `IN_PROGRESS`. Either failure is reported as
    `ERR_OUTAGE_WINDOW_CONFLICT`."

    Design: Corner/errors/an_outage_window_colliding_with_a_run_or_another_outage_is_rejected
    """
    env = _sealed_bed(api)
    assert_int(env["kiln"]["cooldown_buffer_hours"], 12, "cooldown_buffer_hours")
    scheduled = fx.create_scheduled_run(
        api, env["kiln"]["id"], env["pile"]["id"], env["clinker_silo"]["id"]
    )
    assert scheduled["process_state"] == "SCHEDULED"

    validate_error(
        api.create_outage(
            f.outage_payload(
                env["kiln"]["id"],
                "2026-08-01T18:00:00Z",
                "2026-08-02T06:00:00Z",
                scope="REFRACTORY",
                peak_season_override=True,
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_OUTAGE_WINDOW_CONFLICT.value,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_outages(ENGINEER_HEADERS, params={"kiln_id": env["kiln"]["id"]})
    )
    assert meta["total_count"] == 0

    # Clear of the twelve-hour shadow, the same shape is accepted.
    clear = validate_success(
        api.create_outage(
            f.outage_payload(
                env["kiln"]["id"],
                "2026-08-03T00:00:00Z",
                "2026-08-03T12:00:00Z",
                scope="REFRACTORY",
                peak_season_override=True,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert clear["status"] == "PLANNED"


def test_outages_that_merely_touch_are_accepted_and_overlapping_ones_are_not(api):
    """Three October windows in a row test the second limb's geometry: the first is booked, the
    second overlaps it and is refused — a `PLANNED` outage blocks before anybody approves it —
    and the third starts at the very instant the first ends and is accepted, because a half-open
    comparison does not call touching windows an overlap. The refused window is then booked on a
    second kiln, since the rule is scoped per kiln.

    PRD: "Both at planning time and again at approval time, the outage window must keep
    `cooldown_buffer_hours` of clearance from the window of every run on that kiln whose
    `process_state` is `SCHEDULED` or `BURNING`, and must not overlap — on a half-open comparison,
    so windows that merely touch are fine — the window of any other outage on that kiln whose
    `status` is `PLANNED`, `APPROVED` or `IN_PROGRESS`."

    Design: Corner/errors/an_outage_window_colliding_with_a_run_or_another_outage_is_rejected
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    kiln_id = env["kiln"]["id"]

    first = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z", scope="REFRACTORY"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert first["status"] == "PLANNED"
    assert first["demand_season_class"] == "SHOULDER"

    validate_error(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-02T00:00:00Z", "2026-10-04T00:00:00Z", scope="MECHANICAL"
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_OUTAGE_WINDOW_CONFLICT.value,
        409,
    )

    touching = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-03T00:00:00Z", "2026-10-05T00:00:00Z", scope="MECHANICAL"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert touching["status"] == "PLANNED"

    _rows, meta = validate_paginated(
        api.list_outages(ENGINEER_HEADERS, params={"kiln_id": kiln_id})
    )
    assert meta["total_count"] == 2

    second_kiln = fx.create_kiln(api, env["plant_id"], code="K2")
    elsewhere = validate_success(
        api.create_outage(
            f.outage_payload(
                second_kiln["id"],
                "2026-10-02T00:00:00Z",
                "2026-10-04T00:00:00Z",
                scope="MECHANICAL",
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert elsewhere["status"] == "PLANNED"
    assert elsewhere["kiln_id"] == second_kiln["id"]


# ---------------------------------------------------------------------------
# errors: an alternative fuel needs its own authorisation, per plant and fuel
# ---------------------------------------------------------------------------
def test_an_unauthorized_alternative_fuel_cannot_be_charged(api):
    """Five tonnes of refuse-derived fuel would take the run to a 4.00 percent substitution rate,
    far under the 35.00 percent permit ceiling, so no arithmetic can explain the refusal: what is
    missing is a trial burn for this plant and this fuel. Authorising the *other* alternative fuel
    does not help the refused one — the authorisation is per pair — while that other fuel's own
    charge goes straight through and collapses the ceiling to its granted 10.00 percent.

    PRD: "Before the ceiling is computed at all, every alternative fuel in the charge must
    actually be authorised: if no `AUTHORIZED` trial burn exists for that plant and fuel, the
    charge is refused with `ERR_BURN_TEST_NOT_AUTHORIZED`; if such a row exists but the clock has
    reached or passed its `valid_until`, the charge is refused with `ERR_BURN_TEST_EXPIRED`."

    Design: Corner/errors/charging_an_unauthorized_alternative_fuel_is_rejected
    """
    env = _burning_run_on_gas(api)
    run_id = env["run"]["id"]
    rdf_charge = f.fuel_charge_payload(env["fuels"]["rdf"]["id"], 5.00)

    validate_error(
        api.charge_fuel(run_id, rdf_charge, OPERATOR_HEADERS),
        ApiErrorId.ERR_BURN_TEST_NOT_AUTHORIZED.value,
        422,
    )
    unchanged = validate_success(api.get_kiln_run(run_id, OPERATOR_HEADERS))
    assert_amount(unchanged["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(unchanged["tsr_pct"], 0.00, "tsr_pct")

    authorized = fx.create_authorized_burn_test(
        api,
        env["plant_id"],
        env["fuels"]["tdf"]["id"],
        requested_max_tsr_pct=10.00,
        authorized_max_tsr_pct=10.00,
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["fuel_id"] == env["fuels"]["tdf"]["id"]
    assert_instant_equals(authorized["valid_from"], "2026-08-01T00:00:00Z", "valid_from")
    assert_instant_equals(
        authorized["valid_until"], "2026-08-31T00:00:00Z", "valid_until"
    )

    validate_error(
        api.charge_fuel(run_id, rdf_charge, OPERATOR_HEADERS),
        ApiErrorId.ERR_BURN_TEST_NOT_AUTHORIZED.value,
        422,
    )

    accepted = validate_success(
        api.charge_fuel(
            run_id,
            f.fuel_charge_payload(env["fuels"]["tdf"]["id"], 5.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(accepted["gross_energy_gj"], 2310.00, "gross_energy_gj")
    assert_amount(accepted["tsr_pct"], 6.49, "tsr_pct")


def test_a_conventional_fuel_never_consults_a_trial_burn(api):
    """Coal is charged into the same run with no trial burn anywhere in the plant's records, and
    it is accepted: authorisation is an alternative-fuel concern only. The coal also contributes
    nothing to the alternative energy total, so the substitution rate stays at zero even though
    the gross energy has almost doubled.

    PRD: "Conventional fuels — those with `is_alternative` false — require no authorisation and
    contribute nothing to the alternative energy total."

    Design: Corner/errors/charging_an_unauthorized_alternative_fuel_is_rejected
    """
    env = _burning_run_on_gas(api)
    assert env["fuels"]["coal"]["is_alternative"] is False

    _rows, meta = validate_paginated(
        api.list_burn_tests(ENV_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0, "no trial burn exists for this plant at all"

    charged = validate_success(
        api.charge_fuel(
            env["run"]["id"],
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 79.00),
            OPERATOR_HEADERS,
        )
    )
    assert_amount(charged["gross_energy_gj"], 4293.00, "gross_energy_gj")
    assert_amount(charged["tsr_pct"], 0.00, "tsr_pct")
    assert_amount(charged["chlorine_input_kg"], 15.80, "chlorine_input_kg")
    assert_amount(charged["nox_emitted_kg"], 962.55, "nox_emitted_kg")


# ---------------------------------------------------------------------------
# errors: the annual NOx budget is checked prospectively
# ---------------------------------------------------------------------------
def test_a_charge_that_would_overdraw_the_annual_nox_budget_is_refused(api):
    """The check is on the figure the plant *would* be left with, so an absurd 500000 tonne
    delivery is refused before it is ever recorded — and the ledger has to read exactly what it
    read beforehand, which an implementation that debited first and validated afterwards could not
    manage. The delivery is natural gas, whose `chlorine_pct` is 0.00 and which is conventional,
    so the safety rung at priority 70 and the substitution and authorisation rungs above the
    budget all stay satisfied and the budget rung at priority 100 is the only fault left. The
    honest 79 tonne coal charge then draws its 746.55 kilograms.

    PRD: "Fourth, budget: the plant's `permit_nox_budget_remaining_kg` after the charge must be at
    least 0.00, with exactly 0.00 allowed, else `ERR_NOX_BUDGET_EXCEEDED`."

    Design: Corner/errors/a_charge_that_would_overdraw_the_annual_nox_budget_is_rejected
    """
    env = _burning_run_on_gas(api)
    before = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_amount(
        before["permit_nox_budget_remaining_kg"],
        1999784.00,
        "permit_nox_budget_remaining_kg",
    )

    validate_error(
        api.charge_fuel(
            env["run"]["id"],
            f.fuel_charge_payload(env["fuels"]["gas"]["id"], 500000.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_NOX_BUDGET_EXCEEDED.value,
        422,
    )

    untouched = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_amount(
        untouched["permit_nox_budget_remaining_kg"],
        1999784.00,
        "permit_nox_budget_remaining_kg",
    )
    run = validate_success(api.get_kiln_run(env["run"]["id"], OPERATOR_HEADERS))
    assert_amount(run["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(run["nox_emitted_kg"], 216.00, "nox_emitted_kg")

    validate_success(
        api.charge_fuel(
            env["run"]["id"],
            f.fuel_charge_payload(env["fuels"]["coal"]["id"], 79.00),
            OPERATOR_HEADERS,
        )
    )
    after = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_amount(
        after["permit_nox_budget_remaining_kg"],
        1999037.45,
        "permit_nox_budget_remaining_kg",
    )


def test_a_charge_that_lands_the_budget_at_exactly_zero_is_accepted(api):
    """A plant permitted only 405.00 kilograms for the year makes the boundary reachable: the gas
    spends 216.00 and a 20 tonne coal delivery spends the remaining 189.00 exactly, which the rule
    allows. One tonne more is then refused, so the ceiling really is at zero and not below it.

    PRD: "`permit_nox_budget_remaining_kg` is the annual allowance minus the sum of
    `nox_emitted_kg` over all kiln runs on kilns of that plant whose `process_state` is
    `SCHEDULED`, `BURNING` or `COMPLETED`, rounded to two decimals."

    Design: Corner/errors/a_charge_that_would_overdraw_the_annual_nox_budget_is_rejected
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api, permit_annual_nox_budget_kg=405.00)
    materials = fx.create_raw_materials(api)
    fuels = fx.create_fuels(api)
    kiln = fx.create_kiln(api, plant["id"])
    silo = fx.create_clinker_silo(api, plant["id"])
    design = fx.create_approved_design(api, plant["id"], materials)
    pile = fx.create_sealed_pile(api, plant["id"], design["id"], materials)
    assert_amount(
        plant["permit_nox_budget_remaining_kg"], 405.00, "permit_nox_budget_remaining_kg"
    )

    run = fx.create_burning_run(api, kiln["id"], pile["id"], silo["id"])
    validate_success(
        api.charge_fuel(
            run["id"], f.fuel_charge_payload(fuels["gas"]["id"], 45.00), OPERATOR_HEADERS
        )
    )
    midway = validate_success(api.get_plant(plant["id"], ENV_HEADERS))
    assert_amount(
        midway["permit_nox_budget_remaining_kg"], 189.00, "permit_nox_budget_remaining_kg"
    )

    exhausting = validate_success(
        api.charge_fuel(
            run["id"], f.fuel_charge_payload(fuels["coal"]["id"], 20.00), OPERATOR_HEADERS
        )
    )
    assert_amount(exhausting["nox_emitted_kg"], 405.00, "nox_emitted_kg")

    spent = validate_success(api.get_plant(plant["id"], ENV_HEADERS))
    assert_amount(
        spent["permit_nox_budget_remaining_kg"], 0.00, "permit_nox_budget_remaining_kg"
    )

    validate_error(
        api.charge_fuel(
            run["id"], f.fuel_charge_payload(fuels["coal"]["id"], 1.00), OPERATOR_HEADERS
        ),
        ApiErrorId.ERR_NOX_BUDGET_EXCEEDED.value,
        422,
    )


# ---------------------------------------------------------------------------
# errors: the clinker has to fit in the silo that was nominated for it
# ---------------------------------------------------------------------------
def _run_into_a_silo_of_capacity(api, capacity_tonnes):
    """A burning run on 45.00 tonnes of gas — 583.78 clinker tonnes to come — nominated into a
    second clinker silo whose capacity is the figure under test, with the clock advanced to the
    end of the firing window so that completion is the only remaining question."""
    env = _sealed_bed(api)
    env["small_silo"] = fx.create_clinker_silo(
        api,
        env["plant_id"],
        code="SC2",
        capacity_tonnes=capacity_tonnes,
        draw_rate_tonnes_per_hour=300.00,
    )
    assert env["small_silo"]["status"] == "OPEN"
    assert_amount(env["small_silo"]["tonnes_on_hand"], 0.00, "tonnes_on_hand")

    run = fx.create_burning_run(
        api, env["kiln"]["id"], env["pile"]["id"], env["small_silo"]["id"]
    )
    validate_success(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["gas"]["id"], 45.00),
            OPERATOR_HEADERS,
        )
    )
    fx.set_clock(api, "2026-08-01T12:00:00Z")
    env["run"] = validate_success(api.get_kiln_run(run["id"], OPERATOR_HEADERS))
    return env


def test_clinker_that_will_not_fit_the_nominated_silo_cannot_be_credited(api):
    """The burn is finished and the meal was ample — 904.86 of the bed's 1000.00 dry tonnes —
    so the only thing standing in the way is the 500.00 tonne silo the operator nominated for
    583.78 tonnes of clinker. The refusal has to be total: no partial fill of the silo, the run
    still `BURNING` with no completion stamp, and the kiln's service hours not yet accrued.

    PRD: "And the receiving clinker silo must be `OPEN`, else `ERR_SILO_BLOCKED`, with room for
    the delivery — its `tonnes_on_hand` plus the clinker tonnage must be no greater than its
    `capacity_tonnes`, with equality allowed, else `ERR_SILO_CAPACITY_EXCEEDED`."

    Design: Corner/errors/crediting_more_clinker_than_the_silo_can_hold_is_rejected
    """
    env = _run_into_a_silo_of_capacity(api, 500.00)

    validate_error(
        api.complete_kiln_run(env["run"]["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_SILO_CAPACITY_EXCEEDED.value,
        422,
    )

    silo = validate_success(api.get_silo(env["small_silo"]["id"], OPERATOR_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 0.00, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 0.00, "available_tonnes")

    run = validate_success(api.get_kiln_run(env["run"]["id"], OPERATOR_HEADERS))
    assert run["process_state"] == "BURNING"
    assert run["quality_state"] == "PENDING_LAB"
    assert run["completed_at"] is None
    assert run["version"] == env["run"]["version"]

    kiln = validate_success(api.get_kiln(env["kiln"]["id"], ADMIN_HEADERS))
    assert kiln["availability_state"] == "AVAILABLE"
    assert_int(
        kiln["refractory_hours_since_reline"], 0, "refractory_hours_since_reline"
    )

    pile = validate_success(api.get_pile(env["pile"]["id"], ENGINEER_HEADERS))
    assert pile["status"] == "CONSUMED"
    assert_amount(pile["consumed_dry_tonnes"], 0.00, "consumed_dry_tonnes")


def test_clinker_that_fills_the_silo_to_the_brim_is_credited(api):
    """A capacity of exactly 583.78 tonnes is the boundary the rule admits, and completing there
    proves it: the whole delivery lands, all of it unreleased because nothing has been tested yet,
    and the silo reports no availability at all rather than a negative figure.

    PRD: "The clinker silo's `tonnes_on_hand` grows by the clinker tonnage **and** its
    `unreleased_tonnes` grows by the same amount, because the clinker is now physically present
    but not yet sellable or usable; its `available_tonnes` is recomputed and its `version`
    increments."

    Design: Corner/errors/crediting_more_clinker_than_the_silo_can_hold_is_rejected
    """
    env = _run_into_a_silo_of_capacity(api, 583.78)
    before_version = env["small_silo"]["version"]

    completed = validate_success(
        api.complete_kiln_run(env["run"]["id"], OPERATOR_HEADERS)
    )
    assert completed["process_state"] == "COMPLETED"
    assert_amount(completed["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_instant_equals(
        completed["completed_at"], "2026-08-01T12:00:00Z", "completed_at"
    )

    silo = validate_success(api.get_silo(env["small_silo"]["id"], OPERATOR_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 583.78, "unreleased_tonnes")
    assert_amount(silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 0.00, "available_tonnes")
    assert silo["version"] == before_version + 1
    assert_amount(silo["capacity_tonnes"], 583.78, "capacity_tonnes")

    pile = validate_success(api.get_pile(env["pile"]["id"], ENGINEER_HEADERS))
    assert_amount(pile["consumed_dry_tonnes"], 904.86, "consumed_dry_tonnes")
