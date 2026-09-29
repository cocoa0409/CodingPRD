"""The same in-home date is legal, then illegal, for the same drop.

2026-08-25 is accepted by PATCH under the 2026-08-01 clock and refused by an
identical PATCH once the clock stands at 2026-09-01, so the rule is evaluated against
the clock at request time rather than frozen at creation. The fresh edge is pinned
too: a date equal to the clock's own instant is accepted, so the comparison is
"not earlier than", not "strictly later than". And a body that never mentions
in_home_date is not subjected to the rule at all.
"""
from test_helpers import (
    ADMIN,
    CLOCK_START,
    PLANNER,
    assert_instant_equals,
    fetch_drop,
    iso_utc,
    new_plan,
    new_season,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

LATER_CLOCK = iso_utc("2026-09-01")


def _a_drop_whose_date_falls_behind_the_clock(api) -> dict:
    """Created under the 2026-08-01 clock at exactly that instant, moved forward to
    2026-08-25 while that is still ahead of the clock, and then left behind when the
    clock jumps to 2026-09-01."""
    set_clock(CLOCK_START, ADMIN)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)

    rejected_create = api.create_drop(
        plan["id"],
        {"drop_number": 1, "in_home_date": iso_utc("2026-07-31"), "page_count": 64},
        PLANNER,
    )
    created = validate_success(
        api.create_drop(
            plan["id"],
            {"drop_number": 1, "in_home_date": iso_utc("2026-08-01"),
             "page_count": 64},
            PLANNER,
        ),
        201,
    )
    moved = validate_success(
        api.update_drop(
            created["id"], {"in_home_date": iso_utc("2026-08-25")}, PLANNER
        ),
        200,
    )

    set_clock(LATER_CLOCK, ADMIN)
    rejected_patch = api.update_drop(
        created["id"], {"in_home_date": iso_utc("2026-08-25")}, PLANNER
    )
    repaged = validate_success(
        api.update_drop(created["id"], {"page_count": 32}, PLANNER), 200
    )
    redated = validate_success(
        api.update_drop(
            created["id"], {"in_home_date": iso_utc("2026-09-01")}, PLANNER
        ),
        200,
    )
    return {
        "plan": plan,
        "rejected_create": rejected_create,
        "created": created,
        "moved": moved,
        "rejected_patch": rejected_patch,
        "repaged": repaged,
        "redated": redated,
    }


class TestTheBoundaryAtCreation:
    def test_a_date_before_the_clock_is_refused_and_leaves_no_drop(self, api):
        """PRD §3.4: "The `in_home_date` may not be earlier than the logical clock's
        current value, and a date in the past is rejected with
        `ERR_INHOME_DATE_IN_PAST`. The drop is created with `production_status`
        `PLANNED` and `measurement_status` `PENDING`, and the two dimensions advance
        entirely independently of one another thereafter."

        Design: Corner/validations/in_home_date_must_not_precede_the_logical_clock_at_create_or_patch
        """
        set_clock(CLOCK_START, ADMIN)
        season = new_season(season_code="FW26", fiscal_year=2026)
        plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)

        response = api.create_drop(
            plan["id"],
            {"drop_number": 1, "in_home_date": iso_utc("2026-07-31"),
             "page_count": 64},
            PLANNER,
        )
        validate_error(response, "ERR_INHOME_DATE_IN_PAST", 422)

        _, meta = validate_paginated(api.list_plan_drops(plan["id"], PLANNER))
        assert meta["total_count"] == 0

    def test_a_date_equal_to_the_clock_is_accepted(self, api):
        """PRD §3.4: "The `in_home_date` may not be earlier than the logical clock's
        current value, and a date in the past is rejected with
        `ERR_INHOME_DATE_IN_PAST`. The drop is created with `production_status`
        `PLANNED` and `measurement_status` `PENDING`, and the two dimensions advance
        entirely independently of one another thereafter."

        Design: Corner/validations/in_home_date_must_not_precede_the_logical_clock_at_create_or_patch
        """
        world = _a_drop_whose_date_falls_behind_the_clock(api)
        created = world["created"]

        validate_error(world["rejected_create"], "ERR_INHOME_DATE_IN_PAST", 422)
        assert_instant_equals(
            created["in_home_date"], iso_utc("2026-08-01"), "in_home_date"
        )
        assert created["production_status"] == "PLANNED"
        assert created["measurement_status"] == "PENDING"


class TestTheSameDateLaterBecomesIllegal:
    def test_the_identical_patch_is_refused_once_the_clock_has_moved(self, api):
        """PRD §2.10: "**In-home date not in the past**, on
        `POST /catalog-circulation/circulation-plans/{id}/drops` and
        `PATCH /catalog-circulation/drops/{id}` — otherwise `ERR_INHOME_DATE_IN_PAST`
        (422)."

        Design: Corner/validations/in_home_date_must_not_precede_the_logical_clock_at_create_or_patch
        """
        world = _a_drop_whose_date_falls_behind_the_clock(api)

        assert_instant_equals(
            world["moved"]["in_home_date"], iso_utc("2026-08-25"), "in_home_date"
        )
        assert world["moved"]["version"] == world["created"]["version"] + 1

        validate_error(world["rejected_patch"], "ERR_INHOME_DATE_IN_PAST", 422)
        assert_instant_equals(
            world["repaged"]["in_home_date"], iso_utc("2026-08-25"), "in_home_date"
        )
        assert_instant_equals(
            world["redated"]["in_home_date"], iso_utc("2026-09-01"), "in_home_date"
        )

    def test_a_page_count_only_amendment_is_not_subjected_to_the_rule(self, api):
        """PRD §3.4: "Changing `page_count` recomputes `weight_oz_milli`,
        `square_inch_capacity` and `unallocated_square_inches`, then re-runs the drop's
        cost per book at the drop's *current* `cost_basis`, then recomputes the owning
        plan's `planned_cost_cents`, `planned_demand_cents` and
        `planned_contribution_cents`; a plan sitting in `COSTED` falls back to `DRAFT` as
        a result.
        The drop's `version` increments by one."

        Design: Corner/validations/in_home_date_must_not_precede_the_logical_clock_at_create_or_patch
        """
        world = _a_drop_whose_date_falls_behind_the_clock(api)
        repaged = world["repaged"]

        assert repaged["page_count"] == 32
        assert repaged["weight_oz_milli"] == 1280
        assert repaged["square_inch_capacity"] == 2816
        assert repaged["unallocated_square_inches"] == 2816
        assert repaged["version"] == world["moved"]["version"] + 1

        # The rejected PATCH between them consumed no version at all.
        assert fetch_drop(world["created"]["id"])["version"] == (
            world["created"]["version"] + 3
        )
