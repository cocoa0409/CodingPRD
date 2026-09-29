"""Presort coverage is an equality, not a floor.

Three sibling drops of one approved plan carry mail streams that are one piece
short, one piece over and exactly right. The over-covered drop is refused as firmly
as the short one, which is what separates an equality check from a `>=` check. The
batches all have to be laid down before costing, because /presort demands an APPROVED
plan while creating a batch demands an editable one — so the repair the last call
attempts is impossible by construction.
"""
from test_helpers import (
    CLOCK_START,
    PLANNER,
    allocate,
    approve_plan,
    cost_plan,
    create_presort_batch_payload,
    fetch_drop,
    fetch_plan,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_presort_batch,
    new_season,
    new_segment,
    presort_drop,
    run_merge_purge,
    set_clock,
    submit_plan,
    validate_error,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

# (segment code, in-home date, requested quantity, batch piece count)
DROP_SPECS = (
    ("S_A", "2026-09-15", 10000, 10000),
    ("S_B", "2026-09-16", 8000, 7999),
    ("S_C", "2026-09-17", 6000, 6001),
)


def _three_approved_drops_covered_short_over_and_exactly() -> dict:
    """Each drop is allocated on its own, so each requested total sits below the
    40000-book rebate band and every provisional cost per book is 83 + 7 + 55 == 145.
    All three batches are recorded while the plan is still DRAFT."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)

    # PRD §3.3 builds the universe from the leaf segments that exist when the run
    # executes, and a run whose net_mailable_names is zero takes the FAILED
    # branch — so every segment is registered before merge-purge is run.
    segments = {
        code: new_segment(season["id"], segment_code=code, **SCORING)
        for code, _date, _quantity, _pieces in DROP_SPECS
    }
    run_merge_purge(plan["id"])

    drops = {}
    for number, (code, date, quantity, pieces) in enumerate(DROP_SPECS, start=1):
        segment = segments[code]
        drop = new_drop(
            plan["id"],
            drop_number=number,
            in_home_date=iso_utc(date),
            page_count=32,
        )
        new_housefile_line(drop["id"], segment["id"], requested_quantity=quantity)
        allocate(drop["id"])
        new_presort_batch(drop["id"], pieces, "FIVE_DIGIT")
        drops[code] = drop

    cost_plan(plan["id"])
    submit_plan(plan["id"])
    approved = approve_plan(plan["id"])
    return {"plan": approved, "exact": drops["S_A"], "short": drops["S_B"],
            "over": drops["S_C"]}


class TestCoverageMustMatchExactly:
    def test_both_a_shortfall_and_an_excess_are_refused(self, api):
        """PRD §3.7: "The drop's `planned_quantity` must be greater than zero. And
        the mail stream must cover the mailing exactly: the sum of `piece_count` across
        the drop's batches must equal the drop's `planned_quantity`, and any shortfall
        or excess is rejected with `ERR_PRESORT_COVERAGE_MISMATCH`."

        Design: Corner/validations/presort_batches_must_cover_the_planned_quantity_exactly
        """
        world = _three_approved_drops_covered_short_over_and_exactly()
        assert world["plan"]["status"] == "APPROVED"

        validate_error(
            api.presort_drop(world["short"]["id"], PLANNER),
            "ERR_PRESORT_COVERAGE_MISMATCH",
            422,
        )
        validate_error(
            api.presort_drop(world["over"]["id"], PLANNER),
            "ERR_PRESORT_COVERAGE_MISMATCH",
            422,
        )

        for key, quantity in (("short", 8000), ("over", 6000)):
            drop = fetch_drop(world[key]["id"])
            assert drop["planned_quantity"] == quantity
            assert drop["production_status"] == "PLANNED"
            assert drop["cost_basis"] == "ESTIMATED_POSTAGE"
            assert drop["postage_total_cents"] == 0
            assert drop["automation_qualified"] is False


class TestTheExactlyCoveredDropPresorts:
    def test_every_piece_counts_towards_the_automation_share(self, api):
        """PRD §3.7: "`automation_share_bps` is that automation piece count
        multiplied by ten thousand, divided by the drop's `planned_quantity`, floored.
        `automation_qualified` is true exactly when `automation_share_bps` is 9000 or
        greater."

        Design: Corner/validations/presort_batches_must_cover_the_planned_quantity_exactly
        """
        world = _three_approved_drops_covered_short_over_and_exactly()

        presorted = presort_drop(world["exact"]["id"])
        assert presorted["production_status"] == "PRESORTED"
        assert presorted["automation_share_bps"] == 10000
        assert presorted["automation_qualified"] is True

    def test_the_all_or_nothing_discount_is_two_cents_a_piece(self, api):
        """PRD §3.7: "The automation discount is all-or-nothing at exactly that line:
        when the drop qualifies, the discount is 2 cents for each automation-qualified
        piece, and when it does not qualify the discount is zero.
        `postage_total_cents` is the batch postage sum less that discount."

        Design: Corner/validations/presort_batches_must_cover_the_planned_quantity_exactly
        """
        world = _three_approved_drops_covered_short_over_and_exactly()

        presorted = presort_drop(world["exact"]["id"])
        assert presorted["postage_total_cents"] == 400000
        assert presorted["postage_total_cents"] == (10000 * 42) - (10000 * 2)

    def test_the_actual_postage_replaces_the_estimate_in_the_unit_cost(self, api):
        """PRD §3.7: "`printing_cents_per_book` and `paper_cents_per_book` are
        computed exactly as in §3.6, but `postage_cents_per_book` now becomes
        `postage_total_cents` divided by the drop's `planned_quantity`, rounded half up
        to whole cents, and the drop's `cost_basis` is set to `PRESORTED_ACTUAL`."

        Design: Corner/validations/presort_batches_must_cover_the_planned_quantity_exactly
        """
        world = _three_approved_drops_covered_short_over_and_exactly()

        presorted = presort_drop(world["exact"]["id"])
        assert presorted["cost_basis"] == "PRESORTED_ACTUAL"
        assert presorted["postage_cents_per_book"] == 40

    def test_the_unit_cost_is_the_sum_of_three_rounded_components(self, api):
        """PRD §3.7: "That substitution only happens when the drop actually has at
        least one presort batch; a drop with no batch falls back to the season's
        `default_postage_estimate_cents_per_piece` with `cost_basis`
        `ESTIMATED_POSTAGE`. `cost_per_book_cents` remains the sum of the three
        independently rounded components."

        Design: Corner/validations/presort_batches_must_cover_the_planned_quantity_exactly
        """
        world = _three_approved_drops_covered_short_over_and_exactly()

        presorted = presort_drop(world["exact"]["id"])
        assert presorted["printing_cents_per_book"] == 83
        assert presorted["paper_cents_per_book"] == 7
        assert presorted["cost_per_book_cents"] == 130
        assert presorted["cost_per_book_cents"] == (
            presorted["printing_cents_per_book"]
            + presorted["paper_cents_per_book"]
            + presorted["postage_cents_per_book"]
        )


class TestCoverageCannotBeRepairedAfterApproval:
    def test_a_late_batch_is_refused_because_the_plan_is_no_longer_editable(
        self, api
    ):
        """PRD §2.10: "**Owning plan editable** — its `status` is `DRAFT` or `COSTED`
        — for any structural mutation of its drops, lines, placements, presort batches
        or merge-purge runs: `POST /catalog-circulation/circulation-plans/{id}/drops`,
        `PATCH /catalog-circulation/drops/{id}`,
        `POST /catalog-circulation/drops/{id}/circulation-lines`,
        `POST /catalog-circulation/drops/{id}/allocate`,
        `POST /catalog-circulation/circulation-lines/{id}/void`,
        `POST /catalog-circulation/drops/{id}/page-placements`,
        `DELETE /catalog-circulation/page-placements/{id}`,
        `POST /catalog-circulation/drops/{id}/presort-batches` and
        `POST /catalog-circulation/circulation-plans/{id}/merge-purge-runs` — otherwise
        `ERR_PLAN_NOT_EDITABLE` (409)."

        Design: Corner/validations/presort_batches_must_cover_the_planned_quantity_exactly
        """
        world = _three_approved_drops_covered_short_over_and_exactly()

        response = api.create_presort_batch(
            world["short"]["id"], create_presort_batch_payload(1, "AADC"), PLANNER
        )
        validate_error(response, "ERR_PLAN_NOT_EDITABLE", 409)
        assert fetch_plan(world["plan"]["id"])["status"] == "APPROVED"
