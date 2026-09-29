"""Union turnaround: the directional rest gap on a member across all productions.

Every test builds its own preconditions from scratch: the database is empty and
the logical clock sits at its startup value when the test begins.
"""

from test_helpers import (
    assert_crew_call,
    assert_labor_ledger,
    assert_status,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_crew_call_payload
from test_helpers.fixtures import (
    create_accepted_call,
    new_crew_member,
    new_production,
    production_version,
    read_crew_call,
    read_production,
)

SECOND_VENUE = {
    "venue_name": "Harbor Dome",
    "venue_roof_type": "DOMED",
    "scheduled_start_utc": "2026-08-17T18:00:00Z",
    "scheduled_end_utc": "2026-08-17T22:00:00Z",
    "venue_curfew_utc": "2026-08-18T06:00:00Z",
}

THIRD_VENUE = {
    "venue_name": "Summit Field",
    "venue_roof_type": "RETRACTABLE",
    "scheduled_start_utc": "2026-08-19T18:00:00Z",
    "scheduled_end_utc": "2026-08-19T22:00:00Z",
    "venue_curfew_utc": "2026-08-20T06:00:00Z",
}


# ---------------------------------------------------------------------------
# The gap is measured from the latest reference release, across all productions
# ---------------------------------------------------------------------------
def test_first_call_records_a_null_turnaround_and_a_599_minute_gap_is_refused(
    api, pm_headers
):
    """With no prior call the gap is null; a 599-minute gap on another production fails.

    PRD: "When the candidate set is empty no turnaround rule applies at all and `turnaround_minutes_before_call` is written as null."
    PRD: "The offer is refused with `ERR_CREW_TURNAROUND_VIOLATION` whenever the gap is strictly less than 600 minutes — a gap of exactly 600 minutes is accepted, and a negative gap is how a genuinely overlapping call is caught."
    PRD: "The rule is evaluated against the member's calls **across every production**, not just this one: the candidate set is that member's calls in `OFFERED`, `ACCEPTED` or `RELEASED`, with `DECLINED` and `CANCELLED` calls excluded, which is precisely what makes cancelling a call free the member immediately."
    Design: Difficulty/resource_temporal_overlap/crew_member_turnaround_directional_gap_from_latest_reference_release
    """
    first_production = new_production(api)
    second_production = new_production(api, **SECOND_VENUE)
    member = new_crew_member(api)

    first_call = create_accepted_call(
        api,
        first_production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T20:00:00Z",
    )
    assert_crew_call(first_call)
    assert first_call["turnaround_minutes_before_call"] is None, (
        "the member's very first call has no prior reference release"
    )
    assert first_call["provisional_total_cents"] == 36_000, "240 straight minutes"

    response = api.create_crew_call(
        create_crew_call_payload(
            second_production["id"],
            member["id"],
            second_production["version"],
            call_time_utc="2026-08-16T05:59:00Z",
            scheduled_release_utc="2026-08-16T09:59:00Z",
        ),
        pm_headers,
    )

    validate_error(response, "ERR_CREW_TURNAROUND_VIOLATION")
    assert_labor_ledger(read_production(api, second_production["id"]), 0, 2_000_000)
    assert_labor_ledger(read_production(api, first_production["id"]), 36_000, 1_964_000)
    assert_status(read_crew_call(api, first_call["id"]), "ACCEPTED", "call status")


def test_a_gap_of_exactly_600_minutes_is_accepted_and_recorded_on_the_new_call(
    api, pm_headers
):
    """Exactly 600 minutes clears the rest rule and is written onto the new call.

    PRD: "**Turnaround**: a member must be given a minimum rest gap of **10 hours** — 600 minutes — between finishing one call and being called to the next."
    PRD: "The new call's `turnaround_minutes_before_call` is then the number of whole minutes from that prior reference release to the new `call_time_utc`, and it may be negative when the new call would begin before the prior one ends."
    PRD: "Each candidate contributes a *reference release*: its `actual_release_utc` when the candidate is `RELEASED`, and its `scheduled_release_utc` otherwise."
    Design: Difficulty/resource_temporal_overlap/crew_member_turnaround_directional_gap_from_latest_reference_release
    """
    first_production = new_production(api)
    second_production = new_production(api, **SECOND_VENUE)
    member = new_crew_member(api)
    create_accepted_call(
        api,
        first_production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T20:00:00Z",
    )

    response = api.create_crew_call(
        create_crew_call_payload(
            second_production["id"],
            member["id"],
            second_production["version"],
            call_time_utc="2026-08-16T06:00:00Z",
            scheduled_release_utc="2026-08-16T10:00:00Z",
        ),
        pm_headers,
    )

    accepted = validate_success(response, 201)
    assert_crew_call(accepted)
    assert_status(accepted, "OFFERED", "call status")
    assert accepted["turnaround_minutes_before_call"] == 600, (
        "20:00 to 06:00 the next day is exactly ten hours of rest"
    )
    assert accepted["provisional_total_cents"] == 36_000
    assert_labor_ledger(read_production(api, second_production["id"]), 36_000, 1_964_000)
    assert_labor_ledger(read_production(api, first_production["id"]), 36_000, 1_964_000)


def test_cancelling_the_latest_call_moves_the_reference_release_back_in_time(
    api, pm_headers
):
    """A third call fails against the latest release and succeeds once it is cancelled.

    PRD: "The prior call is the candidate with the **latest** reference release; when two candidates share the same reference release, the one with the earlier `created_at` wins the tie, never the one with the lower `id`."
    PRD: "Cancellation also removes the call from the member's turnaround candidate set immediately, freeing them to be called elsewhere."
    PRD: "This is a directional minimum-rest gap on the member, not a symmetric overlap test."
    Design: Difficulty/resource_temporal_overlap/crew_member_turnaround_directional_gap_from_latest_reference_release
    """
    first_production = new_production(api)
    second_production = new_production(api, **SECOND_VENUE)
    third_production = new_production(api, **THIRD_VENUE)
    member = new_crew_member(api)
    create_accepted_call(
        api,
        first_production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T20:00:00Z",
    )
    middle_call = create_accepted_call(
        api,
        second_production["id"],
        member["id"],
        call_time_utc="2026-08-16T06:00:00Z",
        scheduled_release_utc="2026-08-16T10:00:00Z",
    )
    assert middle_call["turnaround_minutes_before_call"] == 600

    third_payload = create_crew_call_payload(
        third_production["id"],
        member["id"],
        third_production["version"],
        call_time_utc="2026-08-16T16:00:00Z",
        scheduled_release_utc="2026-08-16T20:00:00Z",
    )
    blocked = api.create_crew_call(third_payload, pm_headers)

    # 10:00 is the latest reference release, so the gap is 360 minutes, not the
    # 1200 minutes the earlier call would have allowed.
    validate_error(blocked, "ERR_CREW_TURNAROUND_VIOLATION")
    assert_labor_ledger(read_production(api, third_production["id"]), 0, 2_000_000)

    cancelled = validate_success(
        api.cancel_crew_call(middle_call["id"], pm_headers), 200
    )
    assert_status(cancelled, "CANCELLED", "call status")
    assert_labor_ledger(read_production(api, second_production["id"]), 0, 2_000_000)

    retried = validate_success(
        api.create_crew_call(
            create_crew_call_payload(
                third_production["id"],
                member["id"],
                production_version(api, third_production["id"]),
                call_time_utc="2026-08-16T16:00:00Z",
                scheduled_release_utc="2026-08-16T20:00:00Z",
            ),
            pm_headers,
        ),
        201,
    )
    assert_status(retried, "OFFERED", "call status")
    assert retried["turnaround_minutes_before_call"] == 1200, (
        "the reference release falls back to the surviving candidate at 20:00"
    )
    assert retried["provisional_total_cents"] == 36_000
    assert_labor_ledger(read_production(api, third_production["id"]), 36_000, 1_964_000)


# ---------------------------------------------------------------------------
# The union rung outranks the money rung
# ---------------------------------------------------------------------------
def test_turnaround_violation_is_reported_ahead_of_a_labor_budget_shortfall(
    api, pm_headers
):
    """One request breaks both rules and is reported at the union rung.

    PRD: "A union turnaround violation is therefore reported even when the very same request would also blow the labor budget."
    PRD: "A rejected request returns exactly one error: the surviving violation with the **lowest** priority number in the ordering below."
    PRD: "Two union rules then apply, and both are reported ahead of any money."
    Design: Difficulty/priority_pair_validation_conflict/crew_turnaround_violation_outranks_labor_budget_exceeded
    """
    funded_production = new_production(api)
    starved_production = new_production(
        api, labor_budget_total_cents=10_000, **SECOND_VENUE
    )
    member = new_crew_member(api)
    first_call = create_accepted_call(
        api,
        funded_production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T20:00:00Z",
    )
    assert first_call["provisional_total_cents"] == 36_000

    response = api.create_crew_call(
        create_crew_call_payload(
            starved_production["id"],
            member["id"],
            starved_production["version"],
            call_time_utc="2026-08-16T05:59:00Z",
            scheduled_release_utc="2026-08-16T09:59:00Z",
        ),
        pm_headers,
    )

    # The 599-minute gap and the 36000-cent reserve against a 10000-cent budget
    # both fail; only the union rung is reported.
    validate_error(response, "ERR_CREW_TURNAROUND_VIOLATION")
    assert_labor_ledger(read_production(api, starved_production["id"]), 0, 10_000)
    assert_status(read_crew_call(api, first_call["id"]), "ACCEPTED", "call status")
    assert_labor_ledger(read_production(api, funded_production["id"]), 36_000, 1_964_000)


def test_labor_budget_shortfall_surfaces_only_once_the_rest_gap_is_satisfied(
    api, pm_headers
):
    """Moving the call one minute later clears the union rung and exposes the money rung.

    PRD: "The offer is refused with `ERR_LABOR_BUDGET_EXCEEDED` when the production's current `labor_committed_cents` plus the candidate call's `provisional_total_cents` would be strictly greater than its `labor_budget_total_cents`; a total exactly equal to the budget is accepted."
    PRD: "Evaluation proceeds strictly down the ladder and stops at the first violation, so a request that breaks several rules is always reported at its earliest rung."
    PRD: "Money is checked last of everything."
    Design: Difficulty/priority_pair_validation_conflict/crew_turnaround_violation_outranks_labor_budget_exceeded
    """
    funded_production = new_production(api)
    starved_production = new_production(
        api, labor_budget_total_cents=10_000, **SECOND_VENUE
    )
    member = new_crew_member(api)
    create_accepted_call(
        api,
        funded_production["id"],
        member["id"],
        call_time_utc="2026-08-15T16:00:00Z",
        scheduled_release_utc="2026-08-15T20:00:00Z",
    )

    response = api.create_crew_call(
        create_crew_call_payload(
            starved_production["id"],
            member["id"],
            starved_production["version"],
            call_time_utc="2026-08-16T06:00:00Z",
            scheduled_release_utc="2026-08-16T10:00:00Z",
        ),
        pm_headers,
    )

    validate_error(response, "ERR_LABOR_BUDGET_EXCEEDED")
    assert_labor_ledger(read_production(api, starved_production["id"]), 0, 10_000)
    assert_labor_ledger(read_production(api, funded_production["id"]), 36_000, 1_964_000)
