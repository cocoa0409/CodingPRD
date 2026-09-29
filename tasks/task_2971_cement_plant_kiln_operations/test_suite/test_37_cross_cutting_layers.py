"""Breadth coverage of the four cross-cutting layers: the three optimistic-concurrency guards, whose
parents all bump their own version as a side effect of the very write the guard admits; the grinding
cascade that moves two silos and a plant aggregate in three requests; the two NOx intensity variants
that live side by side on two rows; and the draw-rate ceiling that is a rate multiplied by a duration.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_amount,
    assert_fields_absent,
    assert_int,
    assert_intensity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
)


def _cement_ready_to_sell(api):
    """A qualified TYPE_IL batch of 574.72 sellable tonnes in SM1, plus one buyer holding an issued
    certificate for the whole of it."""
    fx.reset_clock(api)
    env = fx.qualified_cement_environment(api)
    env["customer"] = fx.create_customer(api)
    env["certificate"] = fx.create_issued_certificate(
        api, env["batch"]["id"], env["customer"]["id"], env["batch"]["cement_tonnes"]
    )
    assert env["batch"]["status"] == "QUALIFIED"
    assert_amount(env["batch"]["cement_tonnes"], 574.72, "cement_tonnes")
    return env


def _order(api, env, tonnes, window_start, window_end, certificate_version):
    return api.create_loadout_order(
        f.loadout_order_payload(
            env["customer"]["id"],
            env["cement_silo"]["id"],
            env["certificate"]["id"],
            certificate_version,
            window_start=window_start,
            window_end=window_end,
            tonnes=tonnes,
        ),
        LOGISTICS_HEADERS,
    )


# ---------------------------------------------------------------------------
# optimistic concurrency: the design invalidates the caller's read itself
# ---------------------------------------------------------------------------
def test_a_second_pile_built_from_one_design_read_is_stale(api):
    """The guard is self-invalidating: opening the first bed recomputes the recipe's open-pile count
    and moves its version, so the second bed built from the same read is refused even though nobody
    else touched the design. Re-reading the version makes the identical payload succeed, and the two
    degenerate cases at the end show the rule is equality — a version from the future is refused just
    as a version from the past is, and the field cannot simply be left out.

    PRD: "Note that a successful pile creation itself recomputes the design's `active_pile_count` and
    increments the design's `version`, so a second pile created from the same read version is
    refused."

    Design: Corner/cross-cutting complexity layers/pile_create_refuses_a_stale_design_version
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(
        api, env["plant_id"], env["materials"], code="D6"
    )
    design_id = design["id"]
    read_version = design["version"]

    first = validate_success(
        api.create_pile(
            f.pile_payload(env["plant_id"], design_id, read_version, "P1"),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert first["status"] == "OPEN"

    moved = validate_success(api.get_design(design_id, ENGINEER_HEADERS))
    assert_int(moved["active_pile_count"], 1, "active_pile_count")
    assert moved["version"] > read_version

    validate_error(
        api.create_pile(
            f.pile_payload(env["plant_id"], design_id, read_version, "P2"),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_DESIGN_VERSION.value,
        412,
    )
    _rows, meta = validate_paginated(
        api.list_piles(ENGINEER_HEADERS, params={"raw_mix_design_id": design_id})
    )
    assert meta["total_count"] == 1, "the refused create left no pile behind"

    second = validate_success(
        api.create_pile(
            f.pile_payload(env["plant_id"], design_id, moved["version"], "P2"),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert second["status"] == "OPEN"
    after_second = validate_success(api.get_design(design_id, ENGINEER_HEADERS))
    assert_int(after_second["active_pile_count"], 2, "active_pile_count")

    validate_error(
        api.create_pile(
            {
                "plant_id": env["plant_id"],
                "raw_mix_design_id": design_id,
                "pile_code": "P3",
            },
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.create_pile(
            f.pile_payload(
                env["plant_id"], design_id, after_second["version"] + 100, "P3"
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_DESIGN_VERSION.value,
        412,
    )


# ---------------------------------------------------------------------------
# optimistic concurrency: the silo guard outranks the availability rule
# ---------------------------------------------------------------------------
def test_a_second_batch_built_from_one_silo_read_is_stale(api):
    """The first batch's own reservation moves the silo, so the caller's read is spent. The sharp
    case is the last one: a 900.00 tonne draw that the silo could never cover answers with the
    concurrency refusal rather than the availability refusal, because the version equality is checked
    first. Across all of it the silo's version moves exactly once per accepted batch.

    PRD: "A silo's `version` increments on every reservation, every physical draw, every credit, every
    withdrawal and every status change, so any intervening silo movement invalidates the caller's read
    and prevents a reservation from being computed against a balance that has already moved."

    Design: Corner/cross-cutting complexity layers/batch_create_refuses_a_stale_clinker_silo_version
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    silo_id = env["clinker_silo"]["id"]
    stale_version = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))["version"]

    first = validate_success(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"], silo_id, env["cement_silo"]["id"], stale_version
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert first["status"] == "PLANNED"
    reserved = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(reserved["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(reserved["available_tonnes"], 83.78, "available_tonnes")
    assert reserved["version"] > stale_version

    validate_error(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                silo_id,
                env["cement_silo"]["id"],
                stale_version,
                clinker_tonnes_drawn=50.00,
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_SILO_VERSION.value,
        412,
    )

    second = validate_success(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                silo_id,
                env["cement_silo"]["id"],
                reserved["version"],
                clinker_tonnes_drawn=50.00,
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert second["status"] == "PLANNED"
    twice_reserved = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(twice_reserved["reserved_tonnes"], 550.00, "reserved_tonnes")
    assert_amount(twice_reserved["available_tonnes"], 33.78, "available_tonnes")

    validate_error(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                silo_id,
                env["cement_silo"]["id"],
                stale_version,
                clinker_tonnes_drawn=900.00,
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_SILO_VERSION.value,
        412,
    )

    final = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert final["version"] == stale_version + 2, "one bump per accepted batch, no more"


# ---------------------------------------------------------------------------
# optimistic concurrency: consuming an allocation moves the certificate
# ---------------------------------------------------------------------------
def test_a_second_order_built_from_one_certificate_read_is_stale(api):
    """The first reservation consumes 120.00 of the certificate's tonnage and therefore bumps the
    certificate, so the planner's post-issue read is already spent. The refusal leaves the allocation
    exactly where the first order left it, and a re-read lets the identical order through — which is
    the mechanism that stops two appointments from both believing the whole certified tonnage is
    free.

    PRD: "A certificate's `version` increments on issue, on revoke, and on every order that consumes
    its `allocated_tonnes`, so an order can never be reserved against an allocation figure that has
    since been consumed or withdrawn."

    Design: Corner/cross-cutting complexity layers/loadout_order_create_refuses_a_stale_certificate_version
    """
    env = _cement_ready_to_sell(api)
    issue_version = env["certificate"]["version"]

    first = validate_success(
        _order(api, env, 120.00, "2026-08-05T06:00:00Z", "2026-08-05T08:00:00Z", issue_version),
        201,
    )
    assert first["status"] == "RESERVED"
    consumed = validate_success(
        api.get_mill_certificate(env["certificate"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(consumed["allocated_tonnes"], 120.00, "allocated_tonnes")
    assert consumed["version"] > issue_version

    validate_error(
        _order(api, env, 100.00, "2026-08-06T06:00:00Z", "2026-08-06T08:00:00Z", issue_version),
        ApiErrorId.ERR_STALE_CERTIFICATE_VERSION.value,
        412,
    )
    unmoved = validate_success(
        api.get_mill_certificate(env["certificate"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(unmoved["allocated_tonnes"], 120.00, "allocated_tonnes")
    assert unmoved["version"] == consumed["version"]

    second = validate_success(
        _order(
            api, env, 100.00, "2026-08-06T06:00:00Z", "2026-08-06T08:00:00Z",
            unmoved["version"],
        ),
        201,
    )
    assert second["status"] == "RESERVED"
    twice_consumed = validate_success(
        api.get_mill_certificate(env["certificate"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(twice_consumed["allocated_tonnes"], 220.00, "allocated_tonnes")
    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["reserved_tonnes"], 220.00, "reserved_tonnes")


# ---------------------------------------------------------------------------
# cascading side effects: one batch walk moves two silos and a plant aggregate
# ---------------------------------------------------------------------------
def test_grinding_walks_two_silos_and_the_cement_is_locked_until_it_qualifies(api):
    """Three requests, three different kinds of movement. Planning promises the clinker; starting the
    mill converts that promise into a physical draw; finishing credits the cement — but credits it as
    unreleased, so the silo shows 574.72 tonnes on hand and nothing available. Only the second passing
    laboratory branch unlocks it, which is what stops uncertified cement from being loaded out.

    PRD: "The finished cement is credited to the cement silo by growing `tonnes_on_hand` by
    `cement_tonnes` **and** growing `unreleased_tonnes` by the same amount, because ground cement is
    not sellable before the batch qualifies; the silo's `available_tonnes` is recomputed and its
    `version` increments."

    Design: Corner/cross-cutting complexity layers/finish_grinding_credits_the_cement_silo_within_the_same_request
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    clinker_silo_id = env["clinker_silo"]["id"]
    cement_silo_id = env["cement_silo"]["id"]

    batch = fx.create_planned_batch(api, env["plant_id"], clinker_silo_id, cement_silo_id)
    promised = validate_success(api.get_silo(clinker_silo_id, ENGINEER_HEADERS))
    assert_amount(promised["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(promised["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(promised["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(promised["available_tonnes"], 83.78, "available_tonnes")

    validate_success(api.start_grinding(batch["id"], OPERATOR_HEADERS))
    drawn = validate_success(api.get_silo(clinker_silo_id, ENGINEER_HEADERS))
    assert_amount(drawn["tonnes_on_hand"], 83.78, "tonnes_on_hand")
    assert_amount(drawn["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(drawn["available_tonnes"], 83.78, "available_tonnes")

    ground = validate_success(api.finish_grinding(batch["id"], OPERATOR_HEADERS))
    assert ground["status"] == "GROUND"
    assert ground["strength_branch_state"] == "PENDING"
    assert ground["fineness_branch_state"] == "PENDING"
    credited = validate_success(api.get_silo(cement_silo_id, ENGINEER_HEADERS))
    assert_amount(credited["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(credited["unreleased_tonnes"], 574.72, "unreleased_tonnes")
    assert_amount(credited["available_tonnes"], 0.00, "available_tonnes")

    fx.record_blaine(api, batch["id"], 400)
    fx.record_strength(api, batch["id"], 45.00)
    qualified = validate_success(api.get_cement_batch(batch["id"], ENGINEER_HEADERS))
    assert qualified["status"] == "QUALIFIED"
    unlocked = validate_success(api.get_silo(cement_silo_id, ENGINEER_HEADERS))
    assert_amount(unlocked["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(unlocked["available_tonnes"], 574.72, "available_tonnes")
    assert_amount(unlocked["tonnes_on_hand"], 574.72, "tonnes_on_hand")

    plant = validate_success(api.get_plant(env["plant_id"], ADMIN_HEADERS))
    assert_amount(
        plant["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )


# ---------------------------------------------------------------------------
# dual variant: the per-run intensity and the rolling one sit on separate rows
# ---------------------------------------------------------------------------
def test_the_per_run_intensity_and_the_rolling_one_are_two_separate_fields(api):
    """With a single completed run the two variants coincide at 0.370, which is exactly the case a
    one-variant implementation survives — so the test also insists each figure appears only on its own
    row, and that the plant's mass ledger is not confused with either intensity. The run's breach flag
    reads false because 0.370 is far under the 1.20 permit cap.

    PRD: "The run's own emission intensity, **`nox_intensity_kg_per_tonne`**, is `nox_emitted_kg`
    divided by `clinker_tonnes`, rounded half up to three decimals, and **`nox_intensity_breach`** is
    true when that intensity is strictly greater than the plant's
    `permit_nox_kg_per_tonne_clinker_cap`."

    Design: Corner/cross-cutting complexity layers/both_nox_intensity_variants_are_exposed_side_by_side
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)

    run = validate_success(api.get_kiln_run(env["run"]["id"], ENV_HEADERS))
    assert_amount(run["nox_emitted_kg"], 216.00, "nox_emitted_kg")
    assert_amount(run["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_intensity(run["nox_intensity_kg_per_tonne"], 0.370, "nox_intensity_kg_per_tonne")
    assert run["nox_intensity_breach"] is False
    assert_fields_absent(run, ["rolling_nox_intensity_kg_per_tonne"])

    plant = validate_success(api.get_plant(env["plant_id"], ENV_HEADERS))
    assert_intensity(
        plant["rolling_nox_intensity_kg_per_tonne"],
        0.370,
        "rolling_nox_intensity_kg_per_tonne",
    )
    assert_amount(
        plant["permit_nox_budget_remaining_kg"],
        1999784.00,
        "permit_nox_budget_remaining_kg",
    )
    assert_amount(
        plant["permit_nox_kg_per_tonne_clinker_cap"],
        1.20,
        "permit_nox_kg_per_tonne_clinker_cap",
    )
    assert_fields_absent(plant, ["nox_intensity_kg_per_tonne", "nox_intensity_breach"])


# ---------------------------------------------------------------------------
# rate thresholds: the ceiling is a rate multiplied by the appointment length
# ---------------------------------------------------------------------------
def test_the_draw_rate_ceiling_scales_with_the_appointment_length(api):
    """The same spout rate yields three different ceilings for three different appointment lengths —
    500.00 over two hours, 375.00 over ninety minutes, 250.00 over one — so the tonnage alone decides
    nothing. Equality is allowed, which is how the 250.00 tonne order lands. The final attempt breaks
    both the availability rule and the rate rule and answers with the availability code, placing the
    two rungs in order.

    PRD: "And the order's own `tonnes` must be no greater than the silo's `draw_rate_tonnes_per_hour`
    multiplied by the order's `scheduled_hours`, rounded half up to two decimals, else
    `ERR_DRAW_RATE_EXCEEDED`: a four-hour appointment on a 60-tonne-per-hour spout cannot promise more
    than 240.00 tonnes however much cement is standing in the silo."

    Design: Corner/cross-cutting complexity layers/the_draw_rate_ceiling_scales_with_the_window_length_and_admits_equality
    """
    env = _cement_ready_to_sell(api)
    version = env["certificate"]["version"]

    validate_error(
        _order(api, env, 500.01, "2026-08-05T06:00:00Z", "2026-08-05T08:00:00Z", version),
        ApiErrorId.ERR_DRAW_RATE_EXCEEDED.value,
        422,
    )
    validate_error(
        _order(api, env, 300.00, "2026-08-06T06:00:00Z", "2026-08-06T07:00:00Z", version),
        ApiErrorId.ERR_DRAW_RATE_EXCEEDED.value,
        422,
    )
    validate_error(
        _order(api, env, 375.01, "2026-08-07T06:00:00Z", "2026-08-07T07:30:00Z", version),
        ApiErrorId.ERR_DRAW_RATE_EXCEEDED.value,
        422,
    )

    accepted = validate_success(
        _order(api, env, 250.00, "2026-08-06T06:00:00Z", "2026-08-06T07:00:00Z", version),
        201,
    )
    assert accepted["status"] == "RESERVED"
    assert_amount(accepted["scheduled_hours"], 1.00, "scheduled_hours")
    assert_amount(accepted["tonnes"], 250.00, "tonnes")

    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["reserved_tonnes"], 250.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 324.72, "available_tonnes")

    fresh = validate_success(
        api.get_mill_certificate(env["certificate"]["id"], LOGISTICS_HEADERS)
    )
    validate_error(
        _order(
            api, env, 600.00, "2026-08-08T06:00:00Z", "2026-08-08T08:00:00Z",
            fresh["version"],
        ),
        ApiErrorId.ERR_INSUFFICIENT_CEMENT.value,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_loadout_orders(
            LOGISTICS_HEADERS, params={"customer_id": env["customer"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "only the equality case was ever reserved"
