"""Wrap and settlement: the overrun-fee bracket and the settle segregation pair.

Every test builds its own remote from scratch through the helper chains, because
each test starts against an empty database with the logical clock at its startup
value.
"""

from test_helpers import (
    TEST_USERS,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import release_crew_call_payload
from test_helpers.test_users import PRODUCTION_MANAGER_ID, make_union_steward_headers

#: The operator identity that wraps every remote in this file.
PM = TEST_USERS["production_manager_headers"]

# The crew window used by the settlement scenarios: a 600-minute call.
WRAP_CALL_TIME = "2026-08-15T16:00:00Z"
WRAP_CALL_RELEASE = "2026-08-16T02:00:00Z"
#: A break taken 300 minutes into the call, so it is timely and charges no units.
WRAP_MEAL_BREAK = "2026-08-15T21:00:00Z"

# The two fee-bearing contingencies logged against the show.
WEATHER_HOLD_MINUTES = 8
EXTENDED_PLAY_MINUTES = 12
OVERRUN_MINUTES = WEATHER_HOLD_MINUTES + EXTENDED_PLAY_MINUTES

OFF_AIR_CLOCK = "2026-08-15T21:00:00Z"


def _crew_roster(hourly_rate_cents):
    """Two distinct TIER_3-certified staff members on the same card rate."""
    return [
        {
            "full_name": "Dana Reyes",
            "position": "TD",
            "hourly_rate_cents": hourly_rate_cents,
        },
        {
            "full_name": "Ellis Park",
            "position": "EIC",
            "hourly_rate_cents": hourly_rate_cents,
        },
    ]


def _wrapped_remote_with_overrun(api, hourly_rate_cents):
    """A TIER_3 remote taken on air, given 8 weather-hold and 12 extended-play
    minutes, whose two calls are released with a timely meal break, then taken off
    air and wrapped by the canonical ProductionManager operator.
    """
    ctx = fixtures.setup_show_on_air(
        api,
        roster=_crew_roster(hourly_rate_cents),
        call_time_utc=WRAP_CALL_TIME,
        scheduled_release_utc=WRAP_CALL_RELEASE,
    )
    show_id = ctx["show"]["id"]
    fixtures.log_incident(
        api,
        show_id,
        kind="WEATHER_HOLD",
        started_at_utc="2026-08-15T18:10:00Z",
        duration_minutes=WEATHER_HOLD_MINUTES,
        severity="MINOR",
    )
    fixtures.log_incident(
        api,
        show_id,
        kind="EXTENDED_PLAY",
        started_at_utc="2026-08-15T20:50:00Z",
        duration_minutes=EXTENDED_PLAY_MINUTES,
        severity="MINOR",
    )
    for call in ctx["calls"]:
        get_success_data(
            api.release_crew_call(
                call["id"],
                release_crew_call_payload(WRAP_CALL_RELEASE, WRAP_MEAL_BREAK),
                PM,
            )
        )
    fixtures.set_clock(api, OFF_AIR_CLOCK)
    ctx["show"] = fixtures.set_air_status(api, show_id, "OFF_AIR")
    ctx["production"] = get_success_data(
        api.wrap_production(ctx["production"]["id"], PM)
    )
    return ctx


def test_overrun_fee_uses_the_low_bracket_when_the_labor_subtotal_is_below_500000(
    api, us_headers
):
    """Two calls settling at 240,000 cents each price the 20 overrun minutes at the
    low bracket rate, because the 480,000-cent subtotal — not the 504,000-cent total
    — selects the bracket.

    PRD: "The overrun minutes are the show's `weather_hold_minutes` plus its `extended_play_minutes`; `technical_downtime_minutes` is deliberately **excluded** from the fee base, because the network does not bill the league for its own equipment failures."
    PRD: "The per-minute rate is then selected by bracket **on the step-one labor subtotal**: **1,200 cents per minute** when the labor subtotal is strictly below **500,000 cents**, **1,800 cents per minute** when the subtotal is at least 500,000 cents but strictly below **2,000,000 cents**, and **2,400 cents per minute** when the subtotal is at or above 2,000,000 cents."
    PRD: "`overrun_fee_cents` is that rate multiplied by the overrun minutes."
    PRD: "Note carefully that the bracket in step two is keyed on the labor subtotal and **never** on this settlement total, even though the settlement total is the figure the invoice shows."
    Design: Difficulty/combinatorial_formula/settlement_overrun_bracket_keyed_on_labor_subtotal_not_total
    """
    ctx = _wrapped_remote_with_overrun(api, 24_000)

    show = fixtures.read_show(api, ctx["show"]["id"])
    assert show["weather_hold_minutes"] == WEATHER_HOLD_MINUTES, (
        f"Expected weather_hold_minutes {WEATHER_HOLD_MINUTES}, "
        f"got {show['weather_hold_minutes']}"
    )
    assert show["extended_play_minutes"] == EXTENDED_PLAY_MINUTES, (
        f"Expected extended_play_minutes {EXTENDED_PLAY_MINUTES}, "
        f"got {show['extended_play_minutes']}"
    )
    assert show["technical_downtime_minutes"] == 0, (
        "no technical failure was logged, so technical downtime must stand at 0"
    )

    settled = validate_success(
        api.settle_production(ctx["production"]["id"], us_headers)
    )
    assert settled["overrun_fee_cents"] == 1200 * OVERRUN_MINUTES, (
        f"Expected overrun_fee_cents {1200 * OVERRUN_MINUTES} "
        f"(20 minutes at the low bracket rate), got {settled['overrun_fee_cents']}"
    )
    assert settled["overrun_fee_cents"] != 1800 * OVERRUN_MINUTES, (
        "the bracket must be keyed on the 480000-cent labor subtotal, not on the "
        "504000-cent settlement total"
    )


def test_overrun_fee_steps_to_the_mid_bracket_when_the_labor_subtotal_reaches_500000(
    api, us_headers
):
    """Two calls settling at 250,000 cents each put the labor subtotal exactly on the
    mid bracket boundary, which prices the same 20 overrun minutes at 1,800 cents a
    minute and lands a 536,000-cent settlement total.

    PRD: "The overrun minutes are the show's `weather_hold_minutes` plus its `extended_play_minutes`; `technical_downtime_minutes` is deliberately **excluded** from the fee base, because the network does not bill the league for its own equipment failures."
    PRD: "The per-minute rate is then selected by bracket **on the step-one labor subtotal**: **1,200 cents per minute** when the labor subtotal is strictly below **500,000 cents**, **1,800 cents per minute** when the subtotal is at least 500,000 cents but strictly below **2,000,000 cents**, and **2,400 cents per minute** when the subtotal is at or above 2,000,000 cents."
    PRD: "`overrun_fee_cents` is that rate multiplied by the overrun minutes."
    PRD: "*Step three* writes `settlement_total_cents` as the labor subtotal plus `overrun_fee_cents`."
    Design: Difficulty/combinatorial_formula/settlement_overrun_bracket_keyed_on_labor_subtotal_not_total
    """
    ctx = _wrapped_remote_with_overrun(api, 25_000)

    settled = validate_success(
        api.settle_production(ctx["production"]["id"], us_headers)
    )
    assert settled["overrun_fee_cents"] == 1800 * OVERRUN_MINUTES, (
        f"Expected overrun_fee_cents {1800 * OVERRUN_MINUTES} (20 minutes at the mid "
        f"bracket rate), got {settled['overrun_fee_cents']}"
    )
    assert settled["settlement_total_cents"] == 500_000 + 1800 * OVERRUN_MINUTES, (
        f"Expected settlement_total_cents {500_000 + 1800 * OVERRUN_MINUTES}, "
        f"got {settled['settlement_total_cents']}"
    )
    assert (
        settled["settlement_total_cents"] - settled["overrun_fee_cents"] == 500_000
    ), (
        "the settlement total less the overrun fee must be the 500000-cent labor "
        "subtotal that selected the bracket"
    )


def test_labor_variance_is_the_settled_subtotal_less_the_provisional_reserves(
    api, us_headers
):
    """Calls released early with a timely meal break settle below their pessimistic
    reserves, so the variance step writes a negative figure.

    PRD: "*Step one* computes the labor subtotal: the sum of `settled_total_cents` over the production's calls in `RELEASED` status only, summed in `created_at` ascending order."
    PRD: "*Step four* writes `labor_variance_cents` as the labor subtotal less the sum of `provisional_total_cents` over that same set of `RELEASED` calls."
    Design: Difficulty/combinatorial_formula/settlement_overrun_bracket_keyed_on_labor_subtotal_not_total
    """
    ctx = _wrapped_remote_with_overrun(api, 24_000)

    calls, _ = validate_paginated(
        api.list_crew_calls(us_headers, {"production_id": ctx["production"]["id"]})
    )
    released = [call for call in calls if call["status"] == "RELEASED"]
    assert len(released) == 2, (
        f"Expected both calls to be RELEASED before settlement, got {len(released)}"
    )
    subtotal = sum(call["settled_total_cents"] for call in released)
    reserves = sum(call["provisional_total_cents"] for call in released)

    settled = validate_success(
        api.settle_production(ctx["production"]["id"], us_headers)
    )
    assert subtotal == 480_000, (
        f"Expected a 480000-cent labor subtotal from the two settled calls, "
        f"got {subtotal}"
    )
    assert settled["labor_variance_cents"] == subtotal - reserves, (
        f"Expected labor_variance_cents {subtotal - reserves}, "
        f"got {settled['labor_variance_cents']}"
    )
    assert settled["labor_variance_cents"] == -28_000, (
        f"Expected labor_variance_cents -28000, "
        f"got {settled['labor_variance_cents']}"
    )


def test_settlement_by_the_operator_who_wrapped_the_production_is_refused(
    api, us_headers
):
    """The steward whose operator identifier is the one recorded at wrap cannot close
    the ledger, while a distinct steward can.

    PRD: "Second, it stamps `wrapped_by_user_id` on the production with the wrapping operator's `X-User-ID`."
    PRD: "The operator who submitted a venue survey may not be the operator who records its review decision, and the operator who wrapped a production may not be the operator who settles it."
    PRD: "The production must stand at `WRAPPED`, or `ERR_PRODUCTION_STATE_INVALID`, and the settling operator's `X-User-ID` must differ from the production's `wrapped_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/rbac/settlement_requires_a_different_operator_than_the_wrap
    """
    ctx = fixtures.setup_wrapped_production(api, wrap_headers=PM)
    production_id = ctx["production"]["id"]
    assert ctx["production"]["wrapped_by_user_id"] == PRODUCTION_MANAGER_ID, (
        f"Expected wrapped_by_user_id {PRODUCTION_MANAGER_ID}, "
        f"got {ctx['production']['wrapped_by_user_id']}"
    )
    assert ctx["production"]["status"] == "WRAPPED", (
        f"Expected status WRAPPED after the wrap, got {ctx['production']['status']}"
    )

    refused = api.settle_production(
        production_id, make_union_steward_headers(PRODUCTION_MANAGER_ID)
    )
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES")
    held = fixtures.read_production(api, production_id)
    assert held["status"] == "WRAPPED", (
        f"the refused settle must leave the production WRAPPED, got {held['status']}"
    )

    settled = validate_success(api.settle_production(production_id, us_headers))
    assert settled["status"] == "SETTLED", (
        f"Expected status SETTLED once a distinct steward settles, "
        f"got {settled['status']}"
    )


def test_settled_production_refuses_a_further_wrap_because_settled_is_terminal(api):
    """`SETTLED` is terminal, so the wrap that produced the ledger cannot be replayed
    against the closed remote.

    PRD: "Wrapping requires the production to stand at `ON_AIR` **and** its show execution to have reached `OFF_AIR`; a production that never went on air, or one whose show is still live, is refused with `ERR_PRODUCTION_STATE_INVALID`."
    PRD: "The production then rests at `SETTLED`, which is terminal: nothing further can be done to it, and every operation that requires a stage below it is thereafter refused."
    Design: Corner/rbac/settlement_requires_a_different_operator_than_the_wrap
    """
    ctx = fixtures.setup_settled_production(api, wrap_headers=PM)
    production_id = ctx["production"]["id"]
    assert ctx["production"]["status"] == "SETTLED", (
        f"Expected status SETTLED, got {ctx['production']['status']}"
    )

    validate_error(
        api.wrap_production(production_id, PM), "ERR_PRODUCTION_STATE_INVALID"
    )
    assert fixtures.read_production(api, production_id)["status"] == "SETTLED", (
        "the refused wrap must leave the production SETTLED"
    )
