"""Demand modelling: the two consumption variants, and planning as a hard
prerequisite for field work.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_par_level,
    assert_par_unit_invariant,
    assert_service_visit,
    assert_site,
)
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    append_line,
    complete_visit,
    create_account,
    create_site,
    par_lines_by_label,
    plan_site,
    read_route,
    read_site,
    schedule_visit,
    set_clock,
    setup_catalog,
    setup_planned_site,
    update_site,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]


def _serve_twenty_coffee(base, site):
    """Deliver twenty units of coffee to one break room on the anchor Monday.

    The stop is the site's only completed visit, so it is the site's entire
    trailing history when the trailing-usage variant is later asked to plan.
    """
    visit = schedule_visit(
        site["id"],
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T09:45:00Z",
        planned_minutes=45,
    )
    visit = append_line(visit["id"], base["route"]["id"], base["products"]["COFFEE"]["id"], 20)
    set_clock("2026-08-03T09:00:00Z")
    return complete_visit(
        visit["id"],
        base["route"]["id"],
        [f.delivered_line(base["products"]["COFFEE"]["id"], 20)],
    )


def test_headcount_model_and_trailing_usage_diverge_on_par_units():
    """Two break rooms with identical attributes are planned under the two
    consumption variants and land on materially different par quantities.

    "Under the **`HEADCOUNT_MODEL`** variant, the weekly cup forecast is the
    site's headcount multiplied by 1.8 cups per person per day, multiplied by
    the number of occupied days per week, multiplied by the brew-style factor,
    with the product rounded up to a whole number of cups."

    "Each product's par quantity is then the weekly cup forecast multiplied by
    a two-week cover period, multiplied by that product's per-cup unit factor,
    rounded up to a whole number of sales units."

    "Otherwise, the product's weekly rate is its observed delivery divided by
    4, carried as an exact rational value with no intermediate rounding, and
    the product's par quantity is that weekly rate multiplied by the two-week
    cover period, multiplied by a safety uplift of 11000 basis points (a ten
    percent cushion), divided by 10000, rounded up to a whole number of sales
    units."

    "Identical site attributes therefore produce materially different par
    quantities under the two variants, which is the point: a trailing-usage
    site is planned from its own history, and a site with no history in the
    window cannot be planned at all."

    Design: Difficulty/dual_variant_calc/site_par_sizing_headcount_model_vs_trailing_usage_divergence
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY)
    site_a = base["site"]
    assert_site(site_a)

    # Forty people, five days, DRIP: 40 * 1.8 * 5 * 1.00 = 360 cups a week.
    assert site_a["forecast_cups_per_week"] == 360
    # 360 / 5 * 0.35 = 25.2 cups an hour, ceiling 26.
    assert site_a["required_peak_cups_per_hour"] == 26
    assert site_a["recommended_model_id"] == base["model"]["id"]
    assert site_a["brew_style"] == "DRIP"

    forecast_rows = par_lines_by_label(site_a["id"], base["products"])
    # 360 * 2 * per-cup factor, each ceiling taken individually.
    assert forecast_rows["COFFEE"]["par_units"] == 65
    assert forecast_rows["CREAMER"]["par_units"] == 360
    assert forecast_rows["TEA"]["par_units"] == 36
    assert forecast_rows["WATER"]["par_units"] == 8
    assert forecast_rows["PANTRY"]["par_units"] == 288
    # Reorder point is forty percent of par, ceiling taken.
    assert forecast_rows["COFFEE"]["reorder_point_units"] == 26
    assert forecast_rows["CREAMER"]["reorder_point_units"] == 144
    assert forecast_rows["TEA"]["reorder_point_units"] == 15
    assert forecast_rows["WATER"]["reorder_point_units"] == 4
    assert forecast_rows["PANTRY"]["reorder_point_units"] == 116

    site_b = create_site(
        base["account"]["id"],
        base["route"]["id"],
        site_name="Second Floor Break Room",
    )
    site_b = plan_site(site_b["id"], "DRIP")
    _serve_twenty_coffee(base, site_b)

    update_site(site_b["id"], consumption_model="TRAILING_USAGE")
    replanned = plan_site(site_b["id"], "DRIP")

    # The forecast arithmetic is shared, so the cup figures are identical.
    assert replanned["forecast_cups_per_week"] == 360
    assert replanned["required_peak_cups_per_hour"] == 26
    assert replanned["consumption_model"] == "TRAILING_USAGE"

    trailing_rows = par_lines_by_label(site_b["id"], base["products"])
    # Twenty units observed: weekly rate 20/4 = 5, par ceil(5 * 2 * 1.1) = 11,
    # reorder ceil(11 * 0.4) = 5. The headcount variant asked for 65 and 26.
    assert trailing_rows["COFFEE"]["par_units"] == 11
    assert trailing_rows["COFFEE"]["reorder_point_units"] == 5
    assert trailing_rows["COFFEE"]["par_units"] != forecast_rows["COFFEE"]["par_units"]
    # Products the site never took have no observed delivery at all.
    for label in ("CREAMER", "TEA", "WATER", "PANTRY"):
        assert trailing_rows[label]["par_units"] == 0
        assert trailing_rows[label]["reorder_point_units"] == 0

    # The headcount-planned break room is untouched by its neighbour's replan.
    still_forecast = par_lines_by_label(site_a["id"], base["products"])
    assert still_forecast["COFFEE"]["par_units"] == 65
    assert still_forecast["COFFEE"]["reorder_point_units"] == 26


def test_replan_under_the_other_variant_rewrites_only_par_and_reorder():
    """A revised consumption model does not itself re-forecast, and the replan
    that follows it leaves the shelf ledger of the existing forecast line
    exactly as the last stop left it.

    "A site's demand attributes — `headcount`, `days_per_week`,
    `consumption_model` and `route_id` — may later be revised individually by
    an `AccountManager`; each supplied field replaces the stored value and the
    site's `version` increments by 1, but revising them deliberately does
    **not** re-run the forecast: `forecast_cups_per_week`,
    `required_peak_cups_per_hour`, `recommended_model_id` and every existing
    par line are left exactly as they were until planning is run again."

    "If a `FORECAST` line already exists for that product and site, planning
    overwrites **only** its `par_units` and `reorder_point_units` and leaves
    every other member alone."

    "The observation window is the 28 days ending at the current instant,
    inclusive of both endpoints."

    Design: Difficulty/dual_variant_calc/site_par_sizing_headcount_model_vs_trailing_usage_divergence
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY)
    site = create_site(
        base["account"]["id"],
        base["route"]["id"],
        site_name="Second Floor Break Room",
    )
    site = plan_site(site["id"], "DRIP")
    _serve_twenty_coffee(base, site)

    served = par_lines_by_label(site["id"], base["products"])["COFFEE"]
    assert_par_level(served)
    assert served["source"] == "FORECAST"
    assert served["on_hand_units"] == 20
    assert served["cumulative_delivered_units"] == 20
    assert served["cumulative_consumed_units"] == 0
    assert served["last_service_at"] == "2026-08-03T09:00:00Z"
    # "`LOW` when `on_hand_units` is above 0 and at or below
    # `reorder_point_units`" — twenty on hand against the headcount variant's
    # reorder point of twenty-six is a low shelf.
    assert served["reorder_point_units"] == 26
    assert served["stock_status"] == "LOW"

    # A full day later, so the current instant can be told apart from the
    # instant the last stop wrote onto the line.
    set_clock("2026-08-04T08:00:00Z")
    # "each supplied field replaces the stored value and the site's `version`
    # increments by 1" — measured against the version standing immediately before
    # the revision, since the stop that ran in between recomputed the site's own
    # escalation score.
    before_revision = read_site(site["id"])
    revised = update_site(site["id"], consumption_model="TRAILING_USAGE")
    assert revised["version"] == before_revision["version"] + 1
    assert revised["consumption_model"] == "TRAILING_USAGE"
    # The revision alone re-forecasts nothing.
    assert revised["forecast_cups_per_week"] == 360
    assert revised["required_peak_cups_per_hour"] == 26
    assert revised["recommended_model_id"] == base["model"]["id"]
    untouched = par_lines_by_label(site["id"], base["products"])["COFFEE"]
    assert untouched["par_units"] == 65
    assert untouched["reorder_point_units"] == 26
    assert untouched["version"] == served["version"]

    plan_site(site["id"], "DRIP")
    rewritten = par_lines_by_label(site["id"], base["products"])["COFFEE"]
    assert_par_level(rewritten)
    assert_par_unit_invariant(rewritten)
    assert rewritten["id"] == served["id"]
    # Only the two planning outputs moved.
    assert rewritten["par_units"] == 11
    assert rewritten["reorder_point_units"] == 5
    # Everything the ledger owns is exactly where the stop left it.
    assert rewritten["source"] == "FORECAST"
    assert rewritten["on_hand_units"] == 20
    assert rewritten["cumulative_delivered_units"] == 20
    assert rewritten["cumulative_consumed_units"] == 0
    assert rewritten["last_service_at"] == "2026-08-03T09:00:00Z"
    # Twenty on hand against a reorder point of five is not a low shelf.
    assert rewritten["stock_status"] == "IN_STOCK"

    # A line the replan wrote to zero keeps the planning instant it was born
    # with rather than picking up the current instant.
    creamer = par_lines_by_label(site["id"], base["products"])["CREAMER"]
    assert creamer["par_units"] == 0
    assert creamer["last_service_at"] == ANCHOR_MONDAY


def test_unplanned_site_refuses_a_stop_and_books_no_minutes():
    """A break room that has never been planned cannot receive a stop, and the
    refusal leaves the route's booked minutes untouched.

    "Planning is a hard prerequisite for field work. Neither a brewer placement
    nor a service visit may be created for a site whose `recommended_model_id`
    is still null; both are refused with `ERR_SITE_NOT_PLANNED` (HTTP 422)."

    "A new route starts with `booked_minutes_total` at 0."

    Design: Difficulty/cross_entity_state_dependency/visit_scheduling_depends_on_site_planning_state
    """
    base = setup_catalog(clock=ANCHOR_MONDAY)
    account = create_account()
    site = create_site(account["id"], base["route"]["id"])
    assert site["recommended_model_id"] is None
    assert site["service_posture"] == "ACTIVE"

    response = api_client.create_visit(f.create_visit_payload(site["id"]), AM)
    validate_error(response, "ERR_SITE_NOT_PLANNED", 422)

    assert read_route(base["route"]["id"])["booked_minutes_total"] == 0
    assert read_site(site["id"])["version"] == site["version"]


def test_planning_the_site_admits_the_identical_stop_request():
    """The same scheduling request that was refused before planning is accepted
    afterwards, and planning has meanwhile stocked the break room.

    "Planning writes one par line with `source` `FORECAST` for **every**
    product in the catalog, at that site."

    "The visit's `route_id` is **copied from the site's own route** and is never
    client-supplied; nor is `visit_status`, which starts at `SCHEDULED`, nor
    `lines`, which starts as an empty array."

    "Scheduling adds the visit's `planned_minutes` to the route's
    `booked_minutes_total`."

    Design: Difficulty/cross_entity_state_dependency/visit_scheduling_depends_on_site_planning_state
    """
    base = setup_catalog(clock=ANCHOR_MONDAY)
    account = create_account()
    site = create_site(account["id"], base["route"]["id"])
    payload = f.create_visit_payload(site["id"])
    validate_error(api_client.create_visit(payload, AM), "ERR_SITE_NOT_PLANNED", 422)

    planned = plan_site(site["id"], "DRIP")
    assert planned["recommended_model_id"] == base["model"]["id"]

    visit = validate_success(api_client.create_visit(payload, AM), 201)
    assert_service_visit(visit)
    assert visit["site_id"] == site["id"]
    assert visit["route_id"] == base["route"]["id"]
    assert visit["visit_status"] == "SCHEDULED"
    assert visit["lines"] == []
    assert visit["planned_minutes"] == 45

    assert read_route(base["route"]["id"])["booked_minutes_total"] == 45

    rows = par_lines_by_label(site["id"], base["products"])
    assert len(rows) == 5
    assert all(row["source"] == "FORECAST" for row in rows.values())
