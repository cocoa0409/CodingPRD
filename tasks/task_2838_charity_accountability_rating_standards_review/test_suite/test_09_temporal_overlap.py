"""Two contended intervals with opposite endpoint polarities."""
from test_helpers import (
    adopt_methodology_payload,
    assert_instant,
    create_comment_closed_methodology,
    create_organization,
    create_rating_cycle_payload,
    read_cycle,
    set_clock,
    setup_scored_cycle,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_cycle,
)


def _cycle_response(api, scenario, fiscal_year, period_start, period_end):
    return api.create_rating_cycle(
        create_rating_cycle_payload(
            scenario["organization"]["id"],
            scenario["methodology"]["id"],
            fiscal_year=fiscal_year,
            period_start=period_start,
            period_end=period_end,
        ),
        scenario["analyst_headers"],
    )


def test_a_cycle_starting_exactly_where_another_ends_is_admissible_with_no_buffer(
    api, analyst_headers
):
    """The review timeline is half-open, so a prior-year review that ends the instant
    the current one begins does not collide with it, while a six-month shift does.

    PRD §2.8: "**Cycle period overlap.** A new rating cycle's half-open interval from `period_start` up to but excluding `period_end` does not overlap the interval of any non-`WITHDRAWN` cycle of the same organization; adjacency, where a previous cycle's `period_end` equals the new `period_start`, is allowed with no buffer."

    Design: Difficulty/resource_temporal_overlap/rating_cycle_period_half_open_adjacency_allowed
    """
    scenario = setup_scored_cycle(filings=[], evaluate=False, score=False)
    assert_instant(scenario["cycle"]["period_end"], "2026-01-01T00:00:00Z", "period_end")

    adjacent = validate_success(
        _cycle_response(
            api, scenario, 2024, "2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"
        ),
        201,
    )
    assert_instant(adjacent["period_end"], "2025-01-01T00:00:00Z", "adjacent period_end")

    overlapping = _cycle_response(
        api, scenario, 2023, "2024-06-01T00:00:00Z", "2025-06-01T00:00:00Z"
    )
    validate_error(overlapping, "ERR_CYCLE_PERIOD_OVERLAP", 409)

    rows, meta = validate_paginated(
        api.list_rating_cycles(
            analyst_headers, params={"organization_id": scenario["organization"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_withdrawing_a_cycle_releases_its_interval_for_a_replacement_review(
    api, analyst_headers
):
    """Occupancy follows state rather than existence: once the duplicate engagement is
    withdrawn, the very same interval can be claimed again by a new cycle.

    PRD §3.5: "A new interval may not overlap the interval of any non-`WITHDRAWN` cycle of the same organization, though pure adjacency — a new `period_start` exactly equal to an earlier cycle's `period_end` — is permitted with no buffer; an overlap is `ERR_CYCLE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rating_cycle_period_half_open_adjacency_allowed
    """
    scenario = setup_scored_cycle(filings=[], evaluate=False, score=False)
    adjacent = validate_success(
        _cycle_response(
            api, scenario, 2024, "2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"
        ),
        201,
    )
    withdrawn = withdraw_cycle(
        adjacent["id"], withdrawal_reason="duplicate engagement, timeline released"
    )
    assert withdrawn["status"] == "WITHDRAWN"

    reused = validate_success(
        _cycle_response(
            api, scenario, 2024, "2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"
        ),
        201,
    )
    assert reused["id"] != adjacent["id"]
    assert_instant(reused["period_start"], "2024-01-01T00:00:00Z", "period_start")
    assert_instant(reused["period_end"], "2025-01-01T00:00:00Z", "period_end")
    assert read_cycle(adjacent["id"])["status"] == "WITHDRAWN"

    rows, meta = validate_paginated(
        api.list_rating_cycles(
            analyst_headers, params={"organization_id": scenario["organization"]["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert len([row for row in rows if row["status"] == "WITHDRAWN"]) == 1


def test_adoption_needs_a_full_thirty_days_of_notice_and_accepts_exactly_thirty(
    api, admin_headers
):
    """One second short of thirty days' notice is refused; the thirtieth day itself is
    admissible, and the adoption instant is the clock rather than the start of the window.

    PRD §2.8: "**Methodology window conflict.** At adoption, `effective_from` is at least 30 days after the logical clock; `effective_until`, when supplied, is strictly after `effective_from`; and the closed interval from `effective_from` to `effective_until` does not overlap the interval of any other `ADOPTED` version except the one named by `supersedes_version_id`, which this adoption is closing at `effective_from`."

    Design: Difficulty/resource_temporal_overlap/methodology_effectivity_closed_interval_with_thirty_day_buffer
    """
    methodology = create_comment_closed_methodology()

    refused = api.adopt_methodology_version(
        methodology["id"],
        adopt_methodology_payload("2026-08-30T23:59:59Z", "2026-12-31T00:00:00Z"),
        admin_headers,
    )
    validate_error(refused, "ERR_METHODOLOGY_WINDOW_CONFLICT", 409)

    still_closed = validate_success(
        api.get_methodology_version(methodology["id"], admin_headers)
    )
    assert still_closed["status"] == "COMMENT_CLOSED"
    assert still_closed["effective_from"] is None
    assert still_closed["adopted_at"] is None

    adopted = validate_success(
        api.adopt_methodology_version(
            methodology["id"],
            adopt_methodology_payload("2026-08-31T00:00:00Z", "2026-12-31T00:00:00Z"),
            admin_headers,
        )
    )
    assert adopted["status"] == "ADOPTED"
    assert_instant(adopted["effective_from"], "2026-08-31T00:00:00Z", "effective_from")
    assert_instant(adopted["adopted_at"], "2026-08-01T00:00:00Z", "adopted_at")


def test_the_effectivity_window_is_closed_at_its_upper_end(api, analyst_headers, admin_headers):
    """A cycle may still pin the version at the exact instant its window ends, and is
    refused one second after it.

    PRD §2.8: "**Methodology effectivity.** The `MethodologyVersion` pinned to a new rating cycle is effective at the logical clock: its `effective_from` is at or before the clock, and either its `effective_until` is null or the clock is at or before it."

    Design: Difficulty/resource_temporal_overlap/methodology_effectivity_closed_interval_with_thirty_day_buffer
    """
    methodology = create_comment_closed_methodology()
    validate_success(
        api.adopt_methodology_version(
            methodology["id"],
            adopt_methodology_payload("2026-08-31T00:00:00Z", "2026-12-31T00:00:00Z"),
            admin_headers,
        )
    )
    organization = create_organization()

    set_clock("2026-12-31T00:00:00Z")
    at_upper_bound = validate_success(
        api.create_rating_cycle(
            create_rating_cycle_payload(organization["id"], methodology["id"]),
            analyst_headers,
        ),
        201,
    )
    assert at_upper_bound["methodology_version_id"] == methodology["id"]

    set_clock("2026-12-31T00:00:01Z")
    too_late = api.create_rating_cycle(
        create_rating_cycle_payload(
            organization["id"],
            methodology["id"],
            fiscal_year=2024,
            period_start="2024-01-01T00:00:00Z",
            period_end="2025-01-01T00:00:00Z",
        ),
        analyst_headers,
    )
    validate_error(too_late, "ERR_METHODOLOGY_NOT_EFFECTIVE", 409)

    rows, meta = validate_paginated(
        api.list_rating_cycles(
            analyst_headers, params={"organization_id": organization["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == at_upper_bound["id"]
