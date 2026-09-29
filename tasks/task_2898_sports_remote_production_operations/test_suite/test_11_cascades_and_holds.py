"""Transitive cascades: one write that walks prep, production, rehearsal and show.

Every test builds its own preconditions from an empty database with the logical
clock at its startup value, through the shared helpers in ``test_helpers``.
"""

from test_helpers import (
    assert_labor_ledger,
    assert_readiness,
    assert_status,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AIR_CLOCK, CANONICAL_PROVISIONAL_TOTAL_CENTS
from test_helpers.fixtures import (
    read_crew_member,
    read_prep,
    read_production,
    read_rehearsal,
    read_show,
    schedule_rehearsal,
    set_clock,
    setup_show_pre_show,
)

#: A second session, booked strictly before air time and left open.
SECOND_REHEARSAL_START = "2026-08-15T16:30:00Z"

#: Two staff calls of 600 worked minutes each are reserved against the budget.
COMMITTED_WITH_TWO_CALLS = 2 * CANONICAL_PROVISIONAL_TOTAL_CENTS


def _setup_pre_show_with_an_open_rehearsal(api):
    """A fully certified remote with its show open at PRE_SHOW, one COMPLETED
    session behind it and a second session still SCHEDULED ahead of it."""
    context = setup_show_pre_show(api)
    context["open_rehearsal"] = schedule_rehearsal(
        api,
        context["production"]["id"],
        scheduled_start_utc=SECOND_REHEARSAL_START,
    )
    return context


def _assert_fully_certified_baseline(context):
    """The shared precondition every cascade in this file starts from."""
    production = context["production"]
    assert_status(production, "REHEARSED", "production stage")
    assert_readiness(production, preflight=100.00, certified=100.00)
    assert_labor_ledger(
        production,
        COMMITTED_WITH_TWO_CALLS,
        production["labor_budget_total_cents"] - COMMITTED_WITH_TWO_CALLS,
    )
    assert context["show"]["readiness_hold"] is False
    assert_status(context["show"], "PRE_SHOW", "air status", "air_status")
    assert_status(context["rehearsal"], "COMPLETED", "rehearsal status")
    assert_status(context["open_rehearsal"], "SCHEDULED", "rehearsal status")


def test_feed_suspension_reverts_the_prep_demotes_the_stage_aborts_and_holds(
    api, lo_headers, td_headers
):
    """One league write walks four entities: the preparation, the production stage,
    the open rehearsal and the show's readiness hold.

    PRD: "On success the feed moves `ACTIVE → SUSPENDED`, and **every** preparation bound to that feed which sits at `VALIDATED` is reverted `VALIDATED → PENDING` with its `feed_validated_at` cleared to null."
    PRD: "The derivation of §2.9 then runs on each affected production, and for any production whose validated-preparation count has now fallen below `required_validated_preps` the consequences are the full cascade: the stage drops from `PROVISIONED` or `REHEARSED` back to `SURVEYED`, every rehearsal of that production still in `SCHEDULED` is driven to `ABORTED`, and `readiness_hold` is set on every show execution of that production still in `PRE_SHOW`."
    Design: Difficulty/transitive_cascade/feed_suspension_cascades_prep_then_production_then_rehearsal_and_show_hold
    """
    context = _setup_pre_show_with_an_open_rehearsal(api)
    production_id = context["production"]["id"]
    budget = context["production"]["labor_budget_total_cents"]
    _assert_fully_certified_baseline(context)

    suspended = validate_success(
        api.suspend_data_feed(context["feed"]["id"], lo_headers)
    )

    assert_status(suspended, "SUSPENDED", "feed status")
    assert suspended["active_consumer_count"] == 0, (
        "the reverted consumer was decremented off the feed"
    )
    prep = read_prep(api, context["prep"]["id"])
    assert_status(prep, "PENDING", "prep status")
    assert prep["feed_validated_at"] is None
    production = read_production(api, production_id)
    assert_status(production, "SURVEYED", "production stage")
    assert_status(
        read_rehearsal(api, context["open_rehearsal"]["id"]),
        "ABORTED",
        "rehearsal status",
    )
    assert_status(
        read_rehearsal(api, context["rehearsal"]["id"]),
        "COMPLETED",
        "rehearsal status",
    )
    show = read_show(api, context["show"]["id"])
    assert show["readiness_hold"] is True
    assert_status(show, "PRE_SHOW", "air status", "air_status")
    rows, meta = validate_paginated(
        api.list_production_rehearsals(
            production_id, td_headers, params={"status": "ABORTED"}
        )
    )
    assert meta["total_count"] == 1, "only the open session was abandoned"
    assert rows[0]["id"] == context["open_rehearsal"]["id"]
    assert_labor_ledger(production, COMMITTED_WITH_TWO_CALLS, budget - COMMITTED_WITH_TWO_CALLS)


def test_feed_suspension_splits_the_two_readiness_figures_and_bars_the_show(
    api, lo_headers, td_headers
):
    """The pulled feed costs the certified figure its systems component while the
    forward-looking projection is untouched, and the show can no longer go on air.

    PRD: "Its validated-preparation count is the number of the production's preparations in `PENDING` or `VALIDATED`."
    PRD: "The production must stand at `PROVISIONED` or `REHEARSED` — note that a merely `PROVISIONED` production is admitted at this rung on purpose, so that a production which a cascade demoted lands on the readiness rung rather than on the stage rung."
    PRD: "**Production stage** permits the operation: `ERR_PRODUCTION_STATE_INVALID`."
    Design: Difficulty/transitive_cascade/feed_suspension_cascades_prep_then_production_then_rehearsal_and_show_hold
    """
    context = _setup_pre_show_with_an_open_rehearsal(api)
    _assert_fully_certified_baseline(context)
    validate_success(api.suspend_data_feed(context["feed"]["id"], lo_headers))
    demoted = read_production(api, context["production"]["id"])
    assert_readiness(demoted, preflight=100.00, certified=80.00)
    set_clock(api, AIR_CLOCK)

    response = api.set_air_status(context["show"]["id"], "ON_AIR", td_headers)

    validate_error(response, "ERR_PRODUCTION_STATE_INVALID")
    show = read_show(api, context["show"]["id"])
    assert_status(show, "PRE_SHOW", "air status", "air_status")
    assert show["on_air_at_utc"] is None
    assert show["readiness_hold"] is True
    assert_status(
        read_production(api, context["production"]["id"]), "SURVEYED", "production stage"
    )


def test_cancelling_an_accepted_call_releases_the_reserve_and_demotes_the_stage(
    api, pm_headers
):
    """One cancellation returns the money, halves the crew component, drops the stage
    one rung and holds the show — and leaves the open session alone.

    PRD: "The call moves to `CANCELLED` and exactly its `provisional_total_cents` is subtracted from the production's `labor_committed_cents`, restoring `labor_available_cents` to its pre-offer value to the cent."
    PRD: "Cancelling an `ACCEPTED` call has a second, less obvious consequence: the certified crew component falls, which through the derivation can demote the production `REHEARSED → PROVISIONED`, which in turn sets `readiness_hold` on any show execution of that production still in `PRE_SHOW`."
    PRD: "The **crew component** is worth up to 15 points and is proportional: take the variant's crew numerator divided by `required_crew_positions`, cap that ratio at 1 so surplus crew never earns extra credit, multiply by 15, and round half up to two decimal places."
    Design: Difficulty/transitive_cascade/accepted_crew_call_cancellation_cascades_to_stage_demotion_then_show_hold
    """
    context = _setup_pre_show_with_an_open_rehearsal(api)
    production_id = context["production"]["id"]
    budget = context["production"]["labor_budget_total_cents"]
    _assert_fully_certified_baseline(context)
    doomed_call = context["calls"][0]
    surviving_call = context["calls"][1]

    cancelled = validate_success(api.cancel_crew_call(doomed_call["id"], pm_headers))

    assert_status(cancelled, "CANCELLED", "crew-call status")
    assert cancelled["provisional_total_cents"] == CANONICAL_PROVISIONAL_TOTAL_CENTS
    assert_status(
        validate_success(api.get_crew_call(surviving_call["id"], pm_headers)),
        "ACCEPTED",
        "crew-call status",
    )
    production = read_production(api, production_id)
    assert_labor_ledger(
        production,
        CANONICAL_PROVISIONAL_TOTAL_CENTS,
        budget - CANONICAL_PROVISIONAL_TOTAL_CENTS,
    )
    assert_status(production, "PROVISIONED", "production stage")
    assert_readiness(production, preflight=92.50, certified=92.50)
    show = read_show(api, context["show"]["id"])
    assert show["readiness_hold"] is True
    assert_status(show, "PRE_SHOW", "air status", "air_status")
    assert_status(
        read_rehearsal(api, context["open_rehearsal"]["id"]),
        "SCHEDULED",
        "rehearsal status",
    )
    assert_status(
        read_rehearsal(api, context["rehearsal"]["id"]),
        "COMPLETED",
        "rehearsal status",
    )
    member = read_crew_member(api, context["crew_members"][0]["id"])
    assert member["lifetime_meal_penalty_units"] == 0, (
        "a cancelled call never charges the member a penalty unit"
    )


def test_cancelling_an_accepted_call_lands_the_show_on_the_readiness_rung(
    api, pm_headers, td_headers
):
    """The demoted production is still admitted at the stage rung, so the refusal
    names readiness rather than the stage.

    PRD: "Then certified readiness is checked: the show's `readiness_hold` must be false, the production must stand specifically at `REHEARSED`, and `readiness_score_certified` must equal exactly 100 — the certified figure, never the preflight projection."
    PRD: "Any of those three failing is reported as `ERR_READINESS_NOT_CERTIFIED`."
    Design: Difficulty/transitive_cascade/accepted_crew_call_cancellation_cascades_to_stage_demotion_then_show_hold
    """
    context = _setup_pre_show_with_an_open_rehearsal(api)
    _assert_fully_certified_baseline(context)
    validate_success(api.cancel_crew_call(context["calls"][0]["id"], pm_headers))
    demoted = read_production(api, context["production"]["id"])
    assert_status(demoted, "PROVISIONED", "production stage")
    set_clock(api, AIR_CLOCK)

    response = api.set_air_status(context["show"]["id"], "ON_AIR", td_headers)

    validate_error(response, "ERR_READINESS_NOT_CERTIFIED")
    show = read_show(api, context["show"]["id"])
    assert_status(show, "PRE_SHOW", "air status", "air_status")
    assert show["on_air_at_utc"] is None
    assert show["air_minutes_total"] == 0
    assert show["readiness_hold"] is True
    still_provisioned = read_production(api, context["production"]["id"])
    assert_status(still_provisioned, "PROVISIONED", "production stage")
    assert_readiness(still_provisioned, certified=92.50)
