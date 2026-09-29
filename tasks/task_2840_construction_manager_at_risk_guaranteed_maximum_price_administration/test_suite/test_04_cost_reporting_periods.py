"""Monthly cost reporting: per-line rounding, and the half-open reporting period.

Each line's extended amount is rounded before it enters any subtotal, and a reporting
period may abut another period of the same project but never overlap one.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CM_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_cost_report_totals,
    assert_fields,
    assert_money,
    assert_money_fields,
    factories,
    fixtures,
    ids_of,
    line_by_seq,
    to_decimal,
)
from test_helpers.types import JsonObject


def _report_with_three_awkward_lines(api: ApiClient) -> JsonObject:
    """An August report whose three lines each round differently at the second place."""
    priced = fixtures.executed_project(api)
    report = fixtures.cost_report(
        api,
        priced.id,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )
    fixtures.append_line(
        api,
        report["id"],
        quantity=Decimal("3.0000"),
        unit_rate=Decimal("101.0050"),
        markup_pct=Decimal("0.0500"),
        disputed=False,
    )
    fixtures.append_line(
        api,
        report["id"],
        quantity=Decimal("7.0000"),
        unit_rate=Decimal("12.3450"),
        markup_pct=Decimal("0.0750"),
        disputed=True,
    )
    fixtures.append_line(
        api,
        report["id"],
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("1000.0010"),
        markup_pct=Decimal("0.0000"),
        disputed=False,
    )
    return fixtures.read_cost_report(api, report["id"])


def _lakeshore_with_an_open_august(api: ApiClient) -> Tuple[str, JsonObject]:
    """A renovation project whose August report carries a single 120,000.00 line."""
    priced = fixtures.executed_project(
        api,
        project_kwargs={
            "name": "Lakeshore Library Renovation",
            "precon_fee_amount": Decimal("30000.00"),
        },
    )
    august = fixtures.cost_report(
        api,
        priced.id,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )
    fixtures.append_line(
        api,
        august["id"],
        quantity=Decimal("1200.0000"),
        unit_rate=Decimal("100.0000"),
    )
    return priced.id, august

def test_each_cost_line_is_rounded_before_it_enters_any_subtotal(
    api: ApiClient,
) -> None:
    """Three awkward extensions that betray a single late rounding at the end.

    PRD: "**The rounding order on a cost line is normative and is not an implementation detail.** Each line's extended amount is computed and rounded to 2 decimal places, half-up, *before it enters any total*:"

    PRD: "`line_amount = round(quantity × unit_rate × (1 + markup_pct), 2)`"

    PRD: "Summing the exact unrounded products and rounding once at the end produces a different number, and that number is wrong."

    PRD: "The appended line object exposes `line_seq` set to the report's `line_count` plus 1, together with `work_package_id`, `quantity`, `unit_rate`, `markup_pct`, the computed `line_amount` and `disputed`."

    Design: Difficulty/combinatorial_formula/cost_report_per_line_rounding_before_subtotal_aggregation
    """
    report = _report_with_three_awkward_lines(api)

    assert_money(
        line_by_seq(report, 1)["line_amount"], Decimal("318.17"), "line 1 line_amount"
    )
    assert_money(
        line_by_seq(report, 2)["line_amount"], Decimal("92.90"), "line 2 line_amount"
    )
    assert_money(
        line_by_seq(report, 3)["line_amount"], Decimal("1000.00"), "line 3 line_amount"
    )
    assert_money(
        report["reported_cost_total"], Decimal("1411.07"), "reported_cost_total"
    )
    assert to_decimal(report["reported_cost_total"]) != Decimal("1411.06"), (
        "the exact unrounded products were summed and rounded once at the end"
    )


def test_the_disputed_partition_sums_the_same_rounded_line_amounts(
    api: ApiClient,
) -> None:
    """Both partitions are built from the published line amounts, so no cent is left over.

    PRD: "The report's `reported_cost_total` is then the sum of `line_amount` over every line, `undisputed_cost_total` is the sum of `line_amount` over lines whose `disputed` is false, `disputed_cost_total` is the sum over lines whose `disputed` is true, and `line_count` is the number of entries in `lines`."

    PRD: "Every subtotal the response exposes must be a sum of the **same** rounded `line_amount` values the response exposes, which guarantees the invariant that `reported_cost_total` equals `undisputed_cost_total` plus `disputed_cost_total` exactly, with no residual cent."

    Design: Difficulty/combinatorial_formula/cost_report_per_line_rounding_before_subtotal_aggregation
    """
    report = _report_with_three_awkward_lines(api)

    assert_money_fields(
        report,
        {
            "reported_cost_total": Decimal("1411.07"),
            "undisputed_cost_total": Decimal("1318.17"),
            "disputed_cost_total": Decimal("92.90"),
        },
    )
    assert_cost_report_totals(report)
    assert_fields(report, {"line_count": 3, "status": "OPEN"})
    assert_fields(line_by_seq(report, 2), {"disputed": True})
    assert_fields(line_by_seq(report, 1), {"disputed": False})
    assert_fields(line_by_seq(report, 3), {"disputed": False})


def test_abutting_periods_tile_while_a_one_second_overlap_is_refused(
    api: ApiClient,
) -> None:
    """September starts exactly where August ends, so the two tile without gaps.

    PRD: "because the interval is half-open, **adjacency is explicitly allowed** — a period whose `period_start` equals another period's `period_end` abuts it and is not an overlap, so consecutive monthly periods tile without gaps"

    PRD: "A genuine overlap is rejected with `ERR_COST_PERIOD_OVERLAP` (HTTP 409)."

    PRD: "A new report is minted with `status` `OPEN`, an empty `lines` array, `line_count` 0, all three of `reported_cost_total`, `undisputed_cost_total` and `disputed_cost_total` at 0.00, `buyout_savings_to_date` 0.00, and `held_reason`, `reconciled_at` and `reconciliation_note` all null."

    Design: Difficulty/resource_temporal_overlap/cost_report_half_open_periods_abut_but_never_overlap
    """
    project_id, _august = _lakeshore_with_an_open_august(api)

    september = validate_success(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-10-01T00:00:00Z",
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_fields(
        september,
        {
            "status": "OPEN",
            "lines": [],
            "line_count": 0,
            "held_reason": None,
            "reconciled_at": None,
            "reconciliation_note": None,
        },
    )
    assert_money_fields(
        september,
        {
            "reported_cost_total": Decimal("0.00"),
            "undisputed_cost_total": Decimal("0.00"),
            "disputed_cost_total": Decimal("0.00"),
            "buyout_savings_to_date": Decimal("0.00"),
        },
    )

    validate_error(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-08-31T23:59:59Z",
                period_end="2026-09-30T23:59:59Z",
            ),
            CM_HEADERS,
        ),
        ApiErrorId.COST_PERIOD_OVERLAP,
        409,
    )


def test_containment_in_either_direction_is_a_genuine_overlap(api: ApiClient) -> None:
    """A period swallowed by August and a period that swallows August both collide.

    PRD: "The new period must not overlap the period of **any** existing report of the same project in **any** status, including reports already at `RECONCILED`, `DISPUTED` or `RECONCILIATION_HELD`; because the interval is half-open, **adjacency is explicitly allowed** — a period whose `period_start` equals another period's `period_end` abuts it and is not an overlap, so consecutive monthly periods tile without gaps."

    PRD: "The `ConstructionManager` opens a monthly report against a `project_id` over a **half-open** period `[period_start, period_end)`: `period_start` is an inclusive ISO 8601 UTC instant and `period_end` is the exclusive end, which must be strictly after `period_start`."

    Design: Difficulty/resource_temporal_overlap/cost_report_half_open_periods_abut_but_never_overlap
    """
    project_id, august = _lakeshore_with_an_open_august(api)

    validate_error(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-08-10T00:00:00Z",
                period_end="2026-08-20T00:00:00Z",
            ),
            CM_HEADERS,
        ),
        ApiErrorId.COST_PERIOD_OVERLAP,
        409,
    )
    validate_error(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-11-01T00:00:00Z",
            ),
            CM_HEADERS,
        ),
        ApiErrorId.COST_PERIOD_OVERLAP,
        409,
    )

    rows, meta = validate_paginated(
        api.list_cost_reports(CM_HEADERS, {"project_id": project_id})
    )
    assert meta["total_count"] == 1, "a refused period was opened as a report anyway"
    assert ids_of(rows) == [august["id"]], (
        "a refused period was opened as a report anyway"
    )


def test_a_reconciled_period_still_occupies_its_interval(api: ApiClient) -> None:
    """The overlap test is status-blind, so reconciling August does not free it up.

    PRD: "The new period must not overlap the period of **any** existing report of the same project in **any** status, including reports already at `RECONCILED`, `DISPUTED` or `RECONCILIATION_HELD`; because the interval is half-open, **adjacency is explicitly allowed** — a period whose `period_start` equals another period's `period_end` abuts it and is not an overlap, so consecutive monthly periods tile without gaps."

    PRD: "A `RECONCILE` decision is permitted from `OPEN` or from `DISPUTED` — the latter being how a dispute is resolved after the parties settle it — and requires the report's `line_count` to be at least 1; it advances the report to `RECONCILED` and stamps `reconciled_at` from the logical clock."

    Design: Difficulty/resource_temporal_overlap/cost_report_half_open_periods_abut_but_never_overlap
    """
    project_id, august = _lakeshore_with_an_open_august(api)
    september = validate_success(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-10-01T00:00:00Z",
            ),
            CM_HEADERS,
        ),
        201,
    )

    reconciled = validate_success(
        api.reconcile_cost_report(
            august["id"],
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        )
    )
    assert_fields(reconciled, {"status": "RECONCILED"})
    assert_money(
        reconciled["reported_cost_total"], Decimal("120000.00"), "reported_cost_total"
    )

    validate_error(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-08-15T00:00:00Z",
                period_end="2026-08-25T00:00:00Z",
            ),
            CM_HEADERS,
        ),
        ApiErrorId.COST_PERIOD_OVERLAP,
        409,
    )

    october = validate_success(
        api.create_cost_report(
            factories.cost_report_payload(
                project_id,
                period_start="2026-10-01T00:00:00Z",
                period_end="2026-11-01T00:00:00Z",
            ),
            CM_HEADERS,
        ),
        201,
    )

    all_rows, all_meta = validate_paginated(
        api.list_cost_reports(CM_HEADERS, {"project_id": project_id})
    )
    assert all_meta["total_count"] == 3, "the three tiled periods were not all opened"
    assert set(ids_of(all_rows)) == {august["id"], september["id"], october["id"]}
    open_rows, open_meta = validate_paginated(
        api.list_cost_reports(
            CM_HEADERS, {"project_id": project_id, "status": "OPEN"}
        )
    )
    assert open_meta["total_count"] == 2, (
        "the reconciled August report is still being listed as OPEN"
    )
    assert set(ids_of(open_rows)) == {september["id"], october["id"]}
