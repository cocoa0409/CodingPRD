"""Crew calls: the two costing variants, the union gates and the labor ledger.

Every test builds its own preconditions from scratch: the database is empty and
the logical clock sits at its startup value when the test begins.
"""

from test_helpers import (
    assert_crew_call,
    assert_crew_member,
    assert_labor_ledger,
    assert_readiness,
    assert_status,
    make_crew_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_crew_call_payload,
    crew_call_response_payload,
    release_crew_call_payload,
)
from test_helpers.fixtures import (
    create_accepted_call,
    decline_call,
    new_crew_member,
    new_production,
    offer_call,
    production_version,
    read_crew_call,
    read_crew_member,
    read_production,
)


# ---------------------------------------------------------------------------
# The two costing variants of one call row
# ---------------------------------------------------------------------------
def test_provisional_total_reads_the_scheduled_release_with_a_pessimistic_meal_penalty(
    api, pm_headers
):
    """A 720-minute scheduled call reserves straight time, overtime and 4 meal units.

    PRD: "The **provisional variant** is computed at offer time and is written to `provisional_total_cents`; it is the figure reserved against the production's labor budget."
    PRD: "It reads `scheduled_release_utc` as the release reference, and it charges meal penalties **pessimistically**, on the assumption that no meal break will be taken at all: when the worked minutes are no more than 360, no units are charged; otherwise the unit count is the worked minutes less 360, divided by 30 and rounded **up** to a whole number, capped at 4."
    PRD: "The number of units charged on a call is recorded in `meal_penalty_units` and is capped at **4 units** no matter how large the delay."
    Design: Difficulty/dual_variant_calc/crew_call_provisional_versus_settled_labor_cost_diverge
    """
    production = new_production(api)
    member = new_crew_member(api)

    response = api.create_crew_call(
        create_crew_call_payload(
            production["id"],
            member["id"],
            production["version"],
            call_time_utc="2026-08-15T16:00:00Z",
            scheduled_release_utc="2026-08-16T04:00:00Z",
        ),
        pm_headers,
    )

    call = validate_success(response, 201)
    assert_crew_call(call)
    assert_status(call, "OFFERED", "call status")
    assert call["effective_rate_cents"] == 9000, (
        "a STAFF member is costed at their own card rate"
    )
    # 600 straight minutes at 9000/h = 90000, 120 overtime minutes at 1.5x = 27000,
    # plus 4 capped meal units at 3500 = 14000.
    assert call["provisional_total_cents"] == 131_000
    assert call["meal_penalty_units"] == 4
    assert_labor_ledger(read_production(api, production["id"]), 131_000, 1_869_000)


def test_settled_total_reads_the_actual_release_and_a_timely_break_charges_no_units(
    api, pm_headers
):
    """The same call settles far below its reserve once the real release is known.

    PRD: "The **settled variant** is computed when the call reaches `RELEASED` — whether an operator released it or the production wrap auto-released it — and is written to `settled_total_cents`."
    PRD: "When `meal_break_start_utc` is present, the penalty is keyed on how late the break was: take the whole minutes from `call_time_utc` to `meal_break_start_utc` and subtract 360; if that delay is zero or negative the break was timely and no units are charged; otherwise the unit count is that delay divided by 30, rounded up to a whole number, capped at 4."
    PRD: "A call released early with a timely meal break therefore settles strictly below its provisional reserve, and that difference is what lands in the production's `labor_variance_cents` at settlement."
    Design: Difficulty/dual_variant_calc/crew_call_provisional_versus_settled_labor_cost_diverge
    """
    production = new_production(api)
    member = new_crew_member(api)
    call = create_accepted_call(
        api,
        production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-16T04:00:00Z",
    )
    assert call["provisional_total_cents"] == 131_000

    response = api.release_crew_call(
        call["id"],
        release_crew_call_payload(
            "2026-08-16T02:30:00Z", meal_break_start_utc="2026-08-15T21:00:00Z"
        ),
        pm_headers,
    )

    released = validate_success(response, 200)
    assert_status(released, "RELEASED", "call status")
    # 630 worked minutes: 90000 straight plus 30 overtime minutes at 1.5x = 6750,
    # and a break taken 300 minutes in is timely, so no meal units at all.
    assert released["settled_total_cents"] == 96_750
    assert released["meal_penalty_units"] == 0
    assert released["provisional_total_cents"] == 131_000, (
        "the reserve figure is kept on the row alongside the settled figure"
    )
    assert released["settled_total_cents"] < released["provisional_total_cents"]
    assert_labor_ledger(read_production(api, production["id"]), 96_750, 1_903_250)
    assert read_crew_member(api, member["id"])["lifetime_meal_penalty_units"] == 0


# ---------------------------------------------------------------------------
# Three priced bands and the rate that feeds them
# ---------------------------------------------------------------------------
def test_double_time_band_is_priced_at_twice_the_negotiated_offer_rate(api, pm_headers):
    """A 780-minute call splits 600/120/60 across the three bands at 1x, 1.5x and 2x.

    PRD: "Each band is priced separately from `effective_rate_cents`, which is an hourly figure: the straight-time amount is the effective rate multiplied by the straight-time minutes divided by 60; the overtime amount is the effective rate multiplied by 1.5, multiplied by the overtime minutes, divided by 60; the double-time amount is the effective rate multiplied by 2.0, multiplied by the double-time minutes, divided by 60."
    PRD: "**Double time** is everything beyond 720 minutes, that is, everything past the twelfth hour."
    PRD: "From that the server derives `effective_rate_cents`: the negotiated `offer_rate_cents` when one is present, and otherwise the member's own `hourly_rate_cents`."
    Design: Difficulty/combinatorial_formula/crew_call_double_time_band_crossing_nonlinear_rate_selection
    """
    production = new_production(api)
    member = new_crew_member(
        api,
        full_name="Kai Moreno",
        position="REPLAY_OP",
        employment_type="FREELANCE",
        hourly_rate_cents=5000,
    )

    response = api.create_crew_call(
        create_crew_call_payload(
            production["id"],
            member["id"],
            production["version"],
            call_time_utc="2026-08-15T16:00:00Z",
            scheduled_release_utc="2026-08-16T05:00:00Z",
            offer_rate_cents=9000,
        ),
        pm_headers,
    )

    call = validate_success(response, 201)
    assert_crew_call(call)
    assert call["effective_rate_cents"] == 9000, (
        "the negotiated rate displaces the 5000 card rate"
    )
    # 90000 straight + 27000 overtime + 18000 double time = 135000 labor,
    # plus 4 capped meal units at 3500 = 14000.
    assert call["provisional_total_cents"] == 149_000
    assert call["meal_penalty_units"] == 4
    assert_labor_ledger(read_production(api, production["id"]), 149_000, 1_851_000)


def test_double_time_band_amount_is_rounded_half_up_to_whole_cents(api, pm_headers):
    """An odd hourly rate makes the double-time band land on a half cent.

    PRD: "Each of the three band amounts is rounded half up to whole cents *first*, on its own, and only then are the three rounded amounts added together to give the labor component."
    PRD: "**Overtime** is the worked minutes beyond 600 up to a second cap of 720 minutes — the eleventh and twelfth hours, so at most 120 minutes."
    PRD: "The call's total is the labor component plus that penalty amount."
    Design: Difficulty/combinatorial_formula/crew_call_double_time_band_crossing_nonlinear_rate_selection
    """
    production = new_production(api)
    member = new_crew_member(
        api,
        full_name="Noor Adeyemi",
        position="A1",
        employment_type="FREELANCE",
        hourly_rate_cents=5000,
    )

    response = api.create_crew_call(
        create_crew_call_payload(
            production["id"],
            member["id"],
            production["version"],
            call_time_utc="2026-08-15T16:00:00Z",
            scheduled_release_utc="2026-08-16T04:45:00Z",
            offer_rate_cents=9005,
        ),
        pm_headers,
    )

    call = validate_success(response, 201)
    assert call["effective_rate_cents"] == 9005
    # 765 worked minutes: straight 90050, overtime 27015, and the 45 double-time
    # minutes give 13507.5 cents, which rounds half up to 13508 on its own.
    assert call["provisional_total_cents"] == 144_573
    assert call["meal_penalty_units"] == 4
    assert_labor_ledger(read_production(api, production["id"]), 144_573, 1_855_427)


# ---------------------------------------------------------------------------
# The meal entitlement boundary at 360 worked minutes
# ---------------------------------------------------------------------------
def test_exactly_360_worked_minutes_charge_no_meal_penalty_unit(api, pm_headers):
    """360 worked minutes is inside the entitlement, so no unit is charged.

    PRD: "A member is entitled to a meal break within **6 hours** — 360 minutes — of their call time, and every further **30 minutes** of delay beyond that entitlement, rounded up to the next whole increment, charges one penalty unit."
    PRD: "When `meal_break_start_utc` is null, no break was taken and the penalty is computed exactly as in the provisional variant: no units when the worked minutes are no more than 360, otherwise the worked minutes less 360, divided by 30, rounded up, capped at 4."
    Design: Difficulty/boundary_precision_check/worked_minutes_at_exactly_360_versus_361_meal_window
    """
    production = new_production(api)
    member = new_crew_member(api)
    call = create_accepted_call(
        api,
        production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T22:00:00Z",
    )
    assert call["provisional_total_cents"] == 54_000, "360 minutes of straight time"
    assert call["meal_penalty_units"] == 0

    response = api.release_crew_call(
        call["id"], release_crew_call_payload("2026-08-15T22:00:00Z"), pm_headers
    )

    released = validate_success(response, 200)
    assert_status(released, "RELEASED", "call status")
    assert released["settled_total_cents"] == 54_000
    assert released["meal_penalty_units"] == 0
    assert_labor_ledger(read_production(api, production["id"]), 54_000, 1_946_000)
    member_after = read_crew_member(api, member["id"])
    assert_crew_member(member_after)
    assert member_after["lifetime_meal_penalty_units"] == 0


def test_361_worked_minutes_charge_a_single_meal_penalty_unit(api, pm_headers):
    """One minute past the entitlement rounds up to a whole 3500-cent unit.

    PRD: "A member is entitled to a meal break within **6 hours** — 360 minutes — of their call time, and every further **30 minutes** of delay beyond that entitlement, rounded up to the next whole increment, charges one penalty unit."
    PRD: "Each unit is worth **3,500 cents**, and on a `TIER_1` event every unit is charged at a **1.5 multiplier** while `TIER_2` and `TIER_3` events charge units at face value."
    PRD: "`lifetime_meal_penalty_units` opens at 0 and accumulates only from calls that reach `RELEASED`."
    Design: Difficulty/boundary_precision_check/worked_minutes_at_exactly_360_versus_361_meal_window
    """
    production = new_production(api)
    member = new_crew_member(api)
    assert member["lifetime_meal_penalty_units"] == 0
    call = create_accepted_call(
        api,
        production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T22:01:00Z",
    )
    # 54150 cents of straight time for 361 minutes plus one 3500-cent unit.
    assert call["provisional_total_cents"] == 57_650
    assert call["meal_penalty_units"] == 1

    response = api.release_crew_call(
        call["id"], release_crew_call_payload("2026-08-15T22:01:00Z"), pm_headers
    )

    released = validate_success(response, 200)
    assert released["settled_total_cents"] == 57_650
    assert released["meal_penalty_units"] == 1
    assert_labor_ledger(read_production(api, production["id"]), 57_650, 1_942_350)
    assert read_crew_member(api, member["id"])["lifetime_meal_penalty_units"] == 1


# ---------------------------------------------------------------------------
# Cancellation restores the reserve to the cent
# ---------------------------------------------------------------------------
def test_cancelling_an_offered_call_restores_the_labor_budget_to_the_cent(
    api, pm_headers
):
    """The exact provisional reserve comes back off committed and onto available.

    PRD: "The call moves to `CANCELLED` and exactly its `provisional_total_cents` is subtracted from the production's `labor_committed_cents`, restoring `labor_available_cents` to its pre-offer value to the cent."
    PRD: "The production's `labor_committed_cents` is always the sum of `provisional_total_cents` over its calls in `OFFERED` or `ACCEPTED` plus the sum of `settled_total_cents` over its calls in `RELEASED`, summed in `created_at` ascending order, with `DECLINED` and `CANCELLED` calls contributing nothing; `labor_available_cents` is always `labor_budget_total_cents` less that committed figure."
    Design: Difficulty/compensating_invariant/crew_call_cancellation_restores_labor_budget_exactly
    """
    production = new_production(api)
    assert_labor_ledger(production, 0, 2_000_000)
    member = new_crew_member(api)
    call = offer_call(api, production["id"], member["id"])
    assert call["provisional_total_cents"] == 104_000
    assert_labor_ledger(read_production(api, production["id"]), 104_000, 1_896_000)

    response = api.cancel_crew_call(call["id"], pm_headers)

    cancelled = validate_success(response, 200)
    assert_status(cancelled, "CANCELLED", "call status")
    assert cancelled["provisional_total_cents"] == 104_000, (
        "the reserve figure stays on the row after it stops counting"
    )
    assert_labor_ledger(read_production(api, production["id"]), 0, 2_000_000)


def test_cancelling_an_accepted_call_also_drops_the_certified_crew_component(
    api, pm_headers
):
    """Cancelling after acceptance restores the budget and removes the crew credit.

    PRD: "Cancelling an `ACCEPTED` call has a second, less obvious consequence: the certified crew component falls, which through the derivation can demote the production `REHEARSED → PROVISIONED`, which in turn sets `readiness_hold` on any show execution of that production still in `PRE_SHOW`."
    PRD: "The **crew component** is worth up to 15 points and is proportional: take the variant's crew numerator divided by `required_crew_positions`, cap that ratio at 1 so surplus crew never earns extra credit, multiply by 15, and round half up to two decimal places."
    Design: Difficulty/compensating_invariant/crew_call_cancellation_restores_labor_budget_exactly
    """
    production = new_production(api)
    member = new_crew_member(api)
    call = create_accepted_call(api, production["id"], member["id"])
    assert_status(call, "ACCEPTED", "call status")
    accepted_view = read_production(api, production["id"])
    assert accepted_view["required_crew_positions"] == 2
    # One accepted call out of two required positions earns half of 15 points.
    assert_readiness(accepted_view, preflight=7.50, certified=7.50)
    assert_labor_ledger(accepted_view, 104_000, 1_896_000)

    response = api.cancel_crew_call(call["id"], pm_headers)

    cancelled = validate_success(response, 200)
    assert_status(cancelled, "CANCELLED", "call status")
    production_after = read_production(api, production["id"])
    assert_readiness(production_after, preflight=0.00, certified=0.00)
    assert_labor_ledger(production_after, 0, 2_000_000)


# ---------------------------------------------------------------------------
# A declined call leaves both the ledger and the readiness input sets
# ---------------------------------------------------------------------------
def test_declined_call_leaves_both_the_labor_ledger_and_the_readiness_input_sets(
    api, pm_headers
):
    """Declining releases the reserve in full and drops the call from the numerator.

    PRD: "A decline moves the call `OFFERED → DECLINED`, at which point the call stops contributing to `labor_committed_cents` and its provisional reserve is released in full; the derivation runs again."
    PRD: "Neither variant ever counts a `TEST_FAILED`, `RELEASED` or `FAILED_OVER` booking, a `FAILED` preparation, or a `DECLINED` or `CANCELLED` call."
    PRD: "Its crew numerator is the number of the production's calls in `OFFERED` or `ACCEPTED`."
    Design: Corner/calculations/declined_crew_call_is_excluded_from_labor_and_readiness_input_sets
    """
    production = new_production(api)
    first_member = new_crew_member(api)
    second_member = new_crew_member(api, full_name="Ellis Park", position="EIC")
    first_call = offer_call(api, production["id"], first_member["id"])
    second_call = offer_call(api, production["id"], second_member["id"])
    both_offered = read_production(api, production["id"])
    assert_labor_ledger(both_offered, 208_000, 1_792_000)
    assert_readiness(both_offered, preflight=15.00, certified=0.00)

    response = api.respond_to_crew_call(
        second_call["id"],
        crew_call_response_payload("DECLINE"),
        make_crew_member_headers(second_member["id"]),
    )

    declined = validate_success(response, 200)
    assert_status(declined, "DECLINED", "call status")
    assert declined["provisional_total_cents"] == 104_000, (
        "the reserve figure is retained on the declined row"
    )
    production_after = read_production(api, production["id"])
    assert_labor_ledger(production_after, 104_000, 1_896_000)
    assert_readiness(production_after, preflight=7.50, certified=0.00)
    assert_status(read_crew_call(api, first_call["id"]), "OFFERED", "call status")
    rows, meta = validate_paginated(
        api.list_crew_calls(pm_headers, params={"production_id": production["id"]})
    )
    assert meta["total_count"] == 2, "the declined call is still a row on the production"
    assert {row["id"] for row in rows} == {first_call["id"], second_call["id"]}
    declined_rows, declined_meta = validate_paginated(
        api.list_crew_calls(
            pm_headers,
            params={"production_id": production["id"], "status": "DECLINED"},
        )
    )
    assert declined_meta["total_count"] == 1
    assert declined_rows[0]["id"] == second_call["id"]


# ---------------------------------------------------------------------------
# One live call per member per production
# ---------------------------------------------------------------------------
def test_duplicate_crew_call_blocked_while_live_and_allowed_after_a_decline(
    api, pm_headers
):
    """The second offer is refused until the first call ends in DECLINED.

    PRD: "A member may hold only one live call per production: if a call to the same member on the same production already exists in `OFFERED`, `ACCEPTED` or `RELEASED`, the new offer is refused with `ERR_DUPLICATE_CREW_CALL`."
    PRD: "Calls that ended in `DECLINED` or `CANCELLED` do not block a re-offer."
    PRD: "When the candidate set is empty no turnaround rule applies at all and `turnaround_minutes_before_call` is written as null."
    Design: Corner/validations/duplicate_crew_call_rejected_until_the_first_is_declined
    """
    production = new_production(api)
    member = new_crew_member(api)
    first = offer_call(api, production["id"], member["id"])

    duplicate = api.create_crew_call(
        create_crew_call_payload(
            production["id"], member["id"], production_version(api, production["id"])
        ),
        pm_headers,
    )

    validate_error(duplicate, "ERR_DUPLICATE_CREW_CALL")
    assert_labor_ledger(read_production(api, production["id"]), 104_000, 1_896_000)
    declined = decline_call(api, first["id"], member["id"])
    assert_status(declined, "DECLINED", "call status")
    assert_labor_ledger(read_production(api, production["id"]), 0, 2_000_000)

    reoffer = validate_success(
        api.create_crew_call(
            create_crew_call_payload(
                production["id"],
                member["id"],
                production_version(api, production["id"]),
            ),
            pm_headers,
        ),
        201,
    )
    assert_crew_call(reoffer)
    assert_status(reoffer, "OFFERED", "call status")
    assert reoffer["provisional_total_cents"] == 104_000
    assert reoffer["turnaround_minutes_before_call"] is None, (
        "the declined call is not a turnaround candidate"
    )
    assert_labor_ledger(read_production(api, production["id"]), 104_000, 1_896_000)
    rows, meta = validate_paginated(
        api.list_crew_calls(pm_headers, params={"crew_member_id": member["id"]})
    )
    assert meta["total_count"] == 2, "the declined row and the re-offer both persist"
    assert {row["status"] for row in rows} == {"DECLINED", "OFFERED"}


# ---------------------------------------------------------------------------
# Craft certification against the event tier
# ---------------------------------------------------------------------------
def test_offer_refused_when_the_member_is_not_certified_for_the_event_tier(
    api, pm_headers
):
    """A TIER_3-only card is refused on a TIER_1 event; a TIER_1 card is accepted.

    PRD: "**Craft certification**: the production's `event_tier` must appear in the member's `certified_tiers`, or the offer is refused with `ERR_CREW_TIER_NOT_CERTIFIED`."
    PRD: "Each unit is worth **3,500 cents**, and on a `TIER_1` event every unit is charged at a **1.5 multiplier** while `TIER_2` and `TIER_3` events charge units at face value."
    PRD: "`required_crew_positions` — the count of *accepted* crew calls a certified crew component demands — is 12 for a `TIER_1` event, 4 for a `TIER_2` event and 2 for a `TIER_3` event."
    Design: Corner/validations/crew_member_must_be_certified_for_the_event_tier
    """
    production = new_production(
        api,
        event_tier="TIER_1",
        venue_name="Grand Coliseum",
        venue_power_capacity_amps=1200,
        venue_roof_type="RETRACTABLE",
        labor_budget_total_cents=9_000_000,
    )
    assert production["required_crew_positions"] == 12
    assert production["required_validated_preps"] == 3
    tier_three_only = new_crew_member(api)
    tier_one_certified = new_crew_member(
        api,
        full_name="Ines Vela",
        position="EIC",
        certified_tiers=["TIER_1", "TIER_3"],
        home_base_code="ATL",
    )
    version = production["version"]

    refused = api.create_crew_call(
        create_crew_call_payload(production["id"], tier_three_only["id"], version),
        pm_headers,
    )

    validate_error(refused, "ERR_CREW_TIER_NOT_CERTIFIED")
    assert_labor_ledger(read_production(api, production["id"]), 0, 9_000_000)
    accepted = validate_success(
        api.create_crew_call(
            create_crew_call_payload(
                production["id"], tier_one_certified["id"], version
            ),
            pm_headers,
        ),
        201,
    )
    # 600 straight minutes at 9000/h plus 4 meal units at 3500 with the TIER_1
    # multiplier of 1.5, so 90000 + 21000.
    assert accepted["provisional_total_cents"] == 111_000
    assert accepted["meal_penalty_units"] == 4
    production_after = read_production(api, production["id"])
    assert_labor_ledger(production_after, 111_000, 8_889_000)
    # One offered call against 12 required positions: 15 * 1/12 = 1.25 points.
    assert_readiness(production_after, preflight=1.25, certified=0.00)


# ---------------------------------------------------------------------------
# The release window and the meal break inside it
# ---------------------------------------------------------------------------
def test_meal_break_outside_the_worked_interval_is_refused(api, pm_headers):
    """A break before the call time, and a release before it, are both refused.

    PRD: "The release instant must be strictly later than `call_time_utc`, and when a meal break is supplied it must lie within the closed interval from `call_time_utc` to `actual_release_utc` inclusive; either violation is `ERR_INVALID_TIME_WINDOW`."
    PRD: "On success the call moves `ACCEPTED → RELEASED`, its `settled_total_cents` and `meal_penalty_units` are computed by the settled variant, the member's `lifetime_meal_penalty_units` rises by exactly those units, the production's `labor_committed_cents` swaps this call's provisional reserve for its settled total, and the derivation runs."
    Design: Corner/validations/meal_break_outside_the_worked_interval_rejected
    """
    production = new_production(api)
    member = new_crew_member(api)
    call = create_accepted_call(api, production["id"], member["id"])
    assert call["provisional_total_cents"] == 104_000

    break_too_early = api.release_crew_call(
        call["id"],
        release_crew_call_payload(
            "2026-08-15T21:00:00Z", meal_break_start_utc="2026-08-15T13:00:00Z"
        ),
        pm_headers,
    )
    validate_error(break_too_early, "ERR_INVALID_TIME_WINDOW")

    release_before_call = api.release_crew_call(
        call["id"], release_crew_call_payload("2026-08-15T13:00:00Z"), pm_headers
    )
    validate_error(release_before_call, "ERR_INVALID_TIME_WINDOW")

    assert_status(read_crew_call(api, call["id"]), "ACCEPTED", "call status")
    assert_labor_ledger(read_production(api, production["id"]), 104_000, 1_896_000)

    released = validate_success(
        api.release_crew_call(
            call["id"],
            release_crew_call_payload(
                "2026-08-15T21:00:00Z", meal_break_start_utc="2026-08-15T18:00:00Z"
            ),
            pm_headers,
        ),
        200,
    )
    assert_status(released, "RELEASED", "call status")
    # 420 worked minutes of straight time and a break taken 240 minutes in.
    assert released["settled_total_cents"] == 63_000
    assert released["meal_penalty_units"] == 0
    assert_labor_ledger(read_production(api, production["id"]), 63_000, 1_937_000)
    assert read_crew_member(api, member["id"])["lifetime_meal_penalty_units"] == 0


# ---------------------------------------------------------------------------
# Employment type decides which rate field may appear
# ---------------------------------------------------------------------------
def test_offer_rate_is_required_for_freelance_and_forbidden_for_staff(api, pm_headers):
    """The same optional field is mandatory on one employment type and banned on the other.

    PRD: "Employment type decides the rate field: `offer_rate_cents` is **required** when the named member's `employment_type` is `FREELANCE` and **forbidden** when it is `STAFF`, and it must be at least 1 when present — a violation of either rule is `ERR_INVALID_REQUEST`."
    PRD: "From that the server derives `effective_rate_cents`: the negotiated `offer_rate_cents` when one is present, and otherwise the member's own `hourly_rate_cents`."
    Design: Corner/validations/freelance_offer_rate_is_required_and_staff_offer_rate_is_forbidden
    """
    production = new_production(api)
    freelancer = new_crew_member(
        api,
        full_name="Rae Lund",
        position="REPLAY_OP",
        employment_type="FREELANCE",
    )
    staffer = new_crew_member(api)
    version = production["version"]

    missing_rate = api.create_crew_call(
        create_crew_call_payload(production["id"], freelancer["id"], version),
        pm_headers,
    )
    validate_error(missing_rate, "ERR_INVALID_REQUEST")

    forbidden_rate = api.create_crew_call(
        create_crew_call_payload(
            production["id"], staffer["id"], version, offer_rate_cents=12_000
        ),
        pm_headers,
    )
    validate_error(forbidden_rate, "ERR_INVALID_REQUEST")

    assert_labor_ledger(read_production(api, production["id"]), 0, 2_000_000)
    accepted = validate_success(
        api.create_crew_call(
            create_crew_call_payload(
                production["id"], freelancer["id"], version, offer_rate_cents=12_000
            ),
            pm_headers,
        ),
        201,
    )
    assert_crew_call(accepted)
    assert accepted["effective_rate_cents"] == 12_000
    # 600 straight minutes at 12000/h plus 4 capped meal units at 3500.
    assert accepted["provisional_total_cents"] == 134_000
    assert_labor_ledger(read_production(api, production["id"]), 134_000, 1_866_000)


# ---------------------------------------------------------------------------
# Money is the last gate, and equality with the budget is accepted
# ---------------------------------------------------------------------------
def test_labor_budget_equality_accepted_then_the_next_offer_is_refused(api, pm_headers):
    """A reserve that exactly exhausts the budget is booked; the next cent is refused.

    PRD: "The offer is refused with `ERR_LABOR_BUDGET_EXCEEDED` when the production's current `labor_committed_cents` plus the candidate call's `provisional_total_cents` would be strictly greater than its `labor_budget_total_cents`; a total exactly equal to the budget is accepted."
    PRD: "Money is checked last of everything."
    Design: Corner/validations/labor_budget_equality_accepted_then_next_offer_rejected
    """
    production = new_production(api, labor_budget_total_cents=104_000)
    first_member = new_crew_member(api)
    second_member = new_crew_member(api, full_name="Ellis Park", position="EIC")

    exact = validate_success(
        api.create_crew_call(
            create_crew_call_payload(
                production["id"], first_member["id"], production["version"]
            ),
            pm_headers,
        ),
        201,
    )

    assert exact["provisional_total_cents"] == 104_000
    assert_status(exact, "OFFERED", "call status")
    at_the_ceiling = read_production(api, production["id"])
    assert_labor_ledger(at_the_ceiling, 104_000, 0)

    refused = api.create_crew_call(
        create_crew_call_payload(
            production["id"],
            second_member["id"],
            production_version(api, production["id"]),
        ),
        pm_headers,
    )

    validate_error(refused, "ERR_LABOR_BUDGET_EXCEEDED")
    assert_labor_ledger(read_production(api, production["id"]), 104_000, 0)
    rows, meta = validate_paginated(
        api.list_crew_calls(pm_headers, params={"production_id": production["id"]})
    )
    assert meta["total_count"] == 1, "the refused offer wrote no call row"
    assert rows[0]["id"] == exact["id"]
