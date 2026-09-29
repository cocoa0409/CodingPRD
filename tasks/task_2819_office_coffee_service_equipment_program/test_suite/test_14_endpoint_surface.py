"""The endpoint surface where one call's effect must be read back through another:
a partial revision that deliberately leaves the plan stale, a substitute-brewer
link observable from both ends and through both reverse filters, and a recompute
that only spends a version when the posture genuinely flips.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.constants import ANCHOR_MONDAY
from test_helpers.fixtures import (
    CATALOG_SPEC_COFFEE_CREAMER,
    CATALOG_SPEC_COFFEE_ONLY,
    complete_stop,
    evaluate_posture,
    list_work_orders,
    loaner_swap,
    par_line_for,
    plan_site,
    read_account,
    read_asset,
    read_site,
    read_work_order,
    schedule_stop_with_lines,
    set_clock,
    setup_placed_site,
    setup_planned_site,
    setup_work_order_in_progress,
    update_site,
)
from test_helpers.test_users import TEST_USERS, make_route_technician_headers

PA = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]


def _rows(response) -> list:
    """The rows of one listing page, discarding the pagination metadata."""
    rows, _meta = validate_paginated(response)
    return rows


def test_a_partial_site_update_writes_only_its_own_keys_and_leaves_the_plan_stale():
    """Two successive partial revisions each write exactly the key they carry, spend a
    version, and leave the forecast, the recommendation and the par row frozen at the
    numbers the first plan produced; only a second planning call moves them.

    "A site's demand attributes — `headcount`, `days_per_week`, `consumption_model` and
    `route_id` — may later be revised individually by an `AccountManager`; each supplied
    field replaces the stored value and the site's `version` increments by 1, but
    revising them deliberately does **not** re-run the forecast:
    `forecast_cups_per_week`, `required_peak_cups_per_hour`, `recommended_model_id` and
    every existing par line are left exactly as they were until planning is run again."

    "If a `FORECAST` line already exists for that product and site, planning overwrites
    **only** its `par_units` and `reorder_point_units` and leaves every other member
    alone."

    Design: Corner/endpoints/corner_site_patch_replaces_only_the_supplied_keys_and_never_replans
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]

    planned = read_site(site_id)
    assert planned["forecast_cups_per_week"] == 360
    assert planned["required_peak_cups_per_hour"] == 26
    assert planned["recommended_model_id"] == base["model"]["id"]
    planned_version = planned["version"]
    first_row = par_line_for(site_id, coffee_id)
    assert (first_row["par_units"], first_row["reorder_point_units"]) == (65, 26)
    assert first_row["source"] == "FORECAST"
    row_created_at = first_row["created_at"]

    headcount_revision = update_site(site_id, headcount=45)
    assert headcount_revision["headcount"] == 45
    assert headcount_revision["days_per_week"] == 5, "an absent key is not cleared"
    assert headcount_revision["consumption_model"] == "HEADCOUNT_MODEL"
    assert headcount_revision["route_id"] == route_id
    assert headcount_revision["site_name"] == base["site"]["site_name"]
    assert headcount_revision["version"] == planned_version + 1

    stale = read_site(site_id)
    assert stale["forecast_cups_per_week"] == 360, "a revision never re-runs the forecast"
    assert stale["required_peak_cups_per_hour"] == 26
    assert stale["recommended_model_id"] == base["model"]["id"]

    days_revision = update_site(site_id, days_per_week=4)
    assert days_revision["days_per_week"] == 4
    assert days_revision["headcount"] == 45, "the earlier revision is not reverted"
    assert days_revision["version"] == planned_version + 2

    untouched_row = par_line_for(site_id, coffee_id)
    assert (untouched_row["par_units"], untouched_row["reorder_point_units"]) == (65, 26)
    assert untouched_row["version"] == first_row["version"]

    replanned = plan_site(site_id, "DRIP")
    assert replanned["forecast_cups_per_week"] == 324
    assert replanned["required_peak_cups_per_hour"] == 29
    rewritten_row = par_line_for(site_id, coffee_id)
    assert rewritten_row["par_units"] == 59
    assert rewritten_row["reorder_point_units"] == 24
    assert rewritten_row["id"] == first_row["id"], "the existing line is overwritten"
    assert rewritten_row["created_at"] == row_created_at
    assert rewritten_row["source"] == "FORECAST"
    assert rewritten_row["on_hand_units"] == 0


def test_a_loaner_swap_is_visible_from_both_rows_and_through_both_reverse_filters():
    """A substitute brewer is attached by naming an existing asset: an unknown identifier
    is a 404 that writes nothing, and the accepted swap is readable from the work order,
    from the asset, and through the reverse filters on both asset columns.

    "A successful swap stamps `loaner_asset_id`, `loaner_out_date` and
    `loaner_due_back_date`, moves `loaner_status` to `OUT`, and moves the loaner asset to
    `ON_LOAN` — passing lazily through `IN_STOCK` first when the asset was
    `RECONDITIONING` with an expired hold."

    "A `line_id` naming a non-existent invoice line, and a `target_line_id` that resolves
    to nothing at all, both yield `ERR_INVOICE_LINE_NOT_FOUND` (HTTP 404); a
    `loaner_asset_id` that resolves to nothing yields `ERR_ASSET_NOT_FOUND`."

    Design: Corner/endpoints/corner_loaner_swap_links_the_work_order_and_the_loaner_asset_in_both_directions
    """
    base = setup_work_order_in_progress(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        min_term_months=12,
        serial_number="URN30-0001",
        loaner_serial="LNR-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    work_order_id = base["work_order"]["id"]
    route_id = base["route"]["id"]
    site_id = base["site"]["id"]
    broken_asset_id = base["asset"]["id"]
    loaner_id = base["loaner_asset"]["id"]
    technician = make_route_technician_headers(route_id)

    validate_error(
        api_client.loaner_swap(
            work_order_id,
            f.loaner_swap_payload(
                NON_EXISTENT_UUID, "2026-08-03T00:00:00Z", "2026-08-17T00:00:00Z"
            ),
            technician,
        ),
        "ERR_ASSET_NOT_FOUND",
        404,
    )
    untouched = read_work_order(work_order_id)
    assert untouched["loaner_asset_id"] is None
    assert untouched["loaner_status"] == "NONE"
    assert read_asset(loaner_id)["asset_status"] == "IN_STOCK"

    swapped = loaner_swap(
        work_order_id,
        route_id,
        loaner_id,
        "2026-08-03T00:00:00Z",
        "2026-08-17T00:00:00Z",
    )
    assert swapped["loaner_asset_id"] == loaner_id
    assert swapped["loaner_out_date"] == "2026-08-03T00:00:00Z"
    assert swapped["loaner_due_back_date"] == "2026-08-17T00:00:00Z"
    assert swapped["loaner_status"] == "OUT"
    assert swapped["wo_status"] == "IN_PROGRESS", (
        "the substitute dimension moved, the repair dimension did not"
    )

    assert read_asset(loaner_id)["asset_status"] == "ON_LOAN"
    assert read_asset(broken_asset_id)["asset_status"] == "PLACED"

    by_loaner = list_work_orders(loaner_asset_id=loaner_id)
    assert [row["id"] for row in by_loaner] == [work_order_id]
    by_asset = list_work_orders(asset_id=broken_asset_id)
    assert [row["id"] for row in by_asset] == [work_order_id]
    assert by_asset[0]["site_id"] == site_id, (
        "the work order's site was copied from the asset's installation"
    )

    on_loan = _rows(
        api_client.list_equipment_assets(PA, params={"asset_status": "ON_LOAN"})
    )
    assert [row["id"] for row in on_loan] == [loaner_id]


def test_a_direct_posture_recompute_spends_a_version_only_on_a_real_flip():
    """The same break room is recomputed three times with nothing changing but the
    calendar: the first call re-derives 27.5 and is a no-op, an overdue descale then
    carries it to 42.5 and escalates it for one version, and the immediate repeat
    re-derives 42.5 and must spend nothing.

    "Doing so writes the freshly computed `escalation_score`, applies the `ACTIVE` ↔
    `ESCALATED` transition in whichever direction the score demands, leaves the posture
    unchanged when neither direction applies (an idempotent no-op), recomputes the
    account's `escalated_site_count`, and may therefore move the account `ACTIVE` →
    `AT_RISK` — deferring its `PROPOSED` adjustments — or `AT_RISK` → `ACTIVE`, restoring
    them."

    "The site's `version` increments by 1 **only** when the service posture actually
    changed."

    Design: Corner/endpoints/corner_evaluate_service_posture_recomputes_the_score_and_only_bumps_version_on_a_real_flip
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        min_term_months=12,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_CREAMER,
    )
    site_id = base["site"]["id"]
    account_id = base["account"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    creamer_id = base["products"]["CREAMER"]["id"]

    assert par_line_for(site_id, coffee_id)["par_units"] == 65
    assert par_line_for(site_id, creamer_id)["par_units"] == 360

    first_stop = schedule_stop_with_lines(base, {"COFFEE": 20, "CREAMER": 10})
    complete_stop(base, first_stop, {"COFFEE": 20, "CREAMER": 10})
    assert par_line_for(site_id, coffee_id)["stock_status"] == "LOW"
    assert par_line_for(site_id, creamer_id)["stock_status"] == "LOW"
    assert read_site(site_id)["escalation_score"] == 15.0

    second_stop = schedule_stop_with_lines(
        base,
        {"COFFEE": 20, "CREAMER": 10},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    complete_stop(base, second_stop, {"COFFEE": 20})

    coffee_row = par_line_for(site_id, coffee_id)
    assert coffee_row["cumulative_consumed_units"] == 20, "the shelf clamped the draw"
    assert coffee_row["on_hand_units"] == 20
    assert coffee_row["stock_status"] == "LOW"
    creamer_row = par_line_for(site_id, creamer_id)
    assert creamer_row["cumulative_delivered_units"] == 10
    assert creamer_row["on_hand_units"] == 0
    assert creamer_row["stock_status"] == "STOCKOUT"

    after_visits = read_site(site_id)
    assert after_visits["escalation_score"] == 27.5
    assert after_visits["service_posture"] == "ACTIVE"
    assert after_visits["consecutive_shortfall_visit_count"] == 1
    settled_version = after_visits["version"]

    no_op = evaluate_posture(site_id, headers=BS)
    assert no_op["escalation_score"] == 27.5
    assert no_op["service_posture"] == "ACTIVE"
    assert no_op["version"] == settled_version, "nothing changed, so nothing was spent"

    set_clock("2026-11-03T08:00:00Z")
    escalated = evaluate_posture(site_id, headers=BS)
    assert escalated["escalation_score"] == 42.5, "the overdue descale added 15.0"
    assert escalated["service_posture"] == "ESCALATED"
    assert escalated["version"] == settled_version + 1

    repeated = evaluate_posture(site_id, headers=BS)
    assert repeated["escalation_score"] == 42.5
    assert repeated["service_posture"] == "ESCALATED"
    assert repeated["version"] == settled_version + 1, (
        "a recompute that changes nothing must not bump version"
    )

    account = read_account(account_id)
    assert account["escalated_site_count"] == 1
    assert account["program_posture"] == "ACTIVE", "one escalated site is below two"
