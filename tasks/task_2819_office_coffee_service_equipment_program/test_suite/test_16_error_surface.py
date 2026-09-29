"""The error surface at its edges: thirteen distinct not-found codes, body foreign keys
answering with their own code from below the path check, the two ways planning can be
refused, the empty-invoice refusal, the status scoping and bounds of the negotiation
endpoints, and a refusal produced four hops away by two dry break rooms.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.constants import ANCHOR_MONDAY
from test_helpers.fixtures import (
    CATALOG_SPEC_COFFEE_CREAMER,
    CATALOG_SPEC_COFFEE_ONLY,
    complete_stop,
    create_account,
    create_site,
    list_par_lines,
    par_line_for,
    plan_site,
    propose_adjustment,
    read_account,
    read_adjustment,
    read_invoice,
    read_site,
    respond_adjustment,
    revise_adjustment,
    schedule_stop_with_lines,
    schedule_visit,
    set_clock,
    set_market_index,
    setup_catalog,
    setup_issued_invoice,
    setup_placed_site,
    setup_planned_site,
    setup_second_site,
    update_site,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_customer_contact_headers,
    make_route_technician_headers,
)

PA = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

RENTAL_TERMS = {
    "terms_type": "RENTAL",
    "minimum_purchase_cents": 60000,
    "min_term_months": 12,
}


def _ghost(tag: int) -> str:
    """A well-formed identifier that deliberately names no row at all."""
    return "00000000-0000-4000-8000-{:012d}".format(tag)


def _count(response) -> int:
    """The honest row count behind a listing page."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_every_templated_path_identifier_answers_with_its_own_not_found_code():
    """Thirteen unresolvable identifiers across thirteen resources produce thirteen
    different codes, and the same check fires on an action endpoint and on a computed
    read, above any rule that would have judged the body.

    "Each identifier has its own dedicated error: `account_id` yields
    `ERR_ACCOUNT_NOT_FOUND`, `site_id` yields `ERR_SITE_NOT_FOUND`, `route_id` yields
    `ERR_ROUTE_NOT_FOUND`, `model_id` yields `ERR_MODEL_NOT_FOUND`, `asset_id` yields
    `ERR_ASSET_NOT_FOUND`, `placement_id` yields `ERR_PLACEMENT_NOT_FOUND`, `product_id`
    yields `ERR_PRODUCT_NOT_FOUND`, `par_level_id` yields `ERR_PAR_LEVEL_NOT_FOUND`,
    `visit_id` yields `ERR_VISIT_NOT_FOUND`, `work_order_id` yields
    `ERR_WORK_ORDER_NOT_FOUND`, `invoice_id` yields `ERR_INVOICE_NOT_FOUND`, and
    `adjustment_id` yields `ERR_ADJUSTMENT_NOT_FOUND`."

    "A `line_id` naming a non-existent invoice line, and a `target_line_id` that resolves
    to nothing at all, both yield `ERR_INVOICE_LINE_NOT_FOUND` (HTTP 404); a
    `loaner_asset_id` that resolves to nothing yields `ERR_ASSET_NOT_FOUND`."

    Design: Corner/errors/corner_every_templated_path_identifier_has_its_own_not_found_code
    """
    set_clock(ANCHOR_MONDAY)

    seen = []
    for expected, response in [
        ("ERR_ACCOUNT_NOT_FOUND", api_client.get_account(_ghost(1), AM)),
        ("ERR_SITE_NOT_FOUND", api_client.get_site(_ghost(2), AM)),
        ("ERR_ROUTE_NOT_FOUND", api_client.get_route(_ghost(3), AM)),
        ("ERR_MODEL_NOT_FOUND", api_client.get_equipment_model(_ghost(4), AM)),
        ("ERR_ASSET_NOT_FOUND", api_client.get_equipment_asset(_ghost(5), AM)),
        ("ERR_PRODUCT_NOT_FOUND", api_client.get_product_item(_ghost(6), AM)),
        ("ERR_PAR_LEVEL_NOT_FOUND", api_client.get_par_level(_ghost(7), AM)),
        ("ERR_PLACEMENT_NOT_FOUND", api_client.get_placement(_ghost(8), AM)),
        ("ERR_VISIT_NOT_FOUND", api_client.get_visit(_ghost(9), AM)),
        ("ERR_WORK_ORDER_NOT_FOUND", api_client.get_work_order(_ghost(10), AM)),
        ("ERR_INVOICE_NOT_FOUND", api_client.get_invoice(_ghost(11), AM)),
        ("ERR_INVOICE_LINE_NOT_FOUND", api_client.get_invoice_line(_ghost(12), AM)),
        ("ERR_ADJUSTMENT_NOT_FOUND", api_client.get_price_adjustment(_ghost(13), AM)),
    ]:
        error = validate_error(response, expected, 404)
        seen.append(error["error_id"])
    assert len(set(seen)) == 13, "a shared generic not-found code would collapse these"

    on_action = validate_error(
        api_client.size_and_plan_site(_ghost(2), f.size_and_plan_payload("DRIP"), AM),
        "ERR_SITE_NOT_FOUND",
        404,
    )
    assert on_action["error_id"] != "ERR_VALIDATION", (
        "the path identifier is resolved before anything in the body is examined"
    )
    validate_error(
        api_client.get_route_day_load(
            _ghost(3), AM, params={"service_date": "2026-08-03"}
        ),
        "ERR_ROUTE_NOT_FOUND",
        404,
    )


def test_a_body_foreign_key_answers_with_its_own_code_but_below_the_path_check():
    """Four different body foreign keys each name the field that failed to resolve, a call
    carrying an unresolvable identifier in both the path and the body reports the path,
    and a body key that resolves to nothing outranks the state rule that would otherwise
    have refused the same call.

    "Identifiers embedded in a URL path are resolved before anything in the body is
    examined, and when a path carries more than one templated segment they are resolved
    strictly left to right."

    "6. **Body foreign-key existence** (see §2.9) — the corresponding not-found error."

    Design: Corner/errors/corner_body_foreign_keys_return_their_own_not_found_code_after_the_path_check
    """
    base = setup_issued_invoice(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
        requested={"COFFEE": 20},
        delivered={"COFFEE": 20},
        **RENTAL_TERMS,
    )
    account_id = base["account"]["id"]
    route_id = base["route"]["id"]
    invoice_id = base["invoice"]["id"]
    reported_stop = base["visit"]
    technician = make_route_technician_headers(route_id)
    fleet_before = _count(api_client.list_equipment_assets(PA, params={"limit": 100}))

    open_stop = schedule_visit(
        base["site"]["id"],
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )

    validate_error(
        api_client.create_equipment_asset(
            f.create_equipment_asset_payload(_ghost(4), serial_number="GHOST-0001"), PA
        ),
        "ERR_MODEL_NOT_FOUND",
        404,
    )
    assert (
        _count(api_client.list_equipment_assets(PA, params={"limit": 100}))
        == fleet_before
    )
    validate_error(
        api_client.create_site(
            f.create_site_payload(_ghost(1), route_id, site_name="Ghost A"), AM
        ),
        "ERR_ACCOUNT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_site(
            f.create_site_payload(account_id, _ghost(3), site_name="Ghost B"), AM
        ),
        "ERR_ROUTE_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_par_level(
            f.create_par_level_payload(_ghost(2), base["products"]["COFFEE"]["id"]), AM
        ),
        "ERR_SITE_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.append_visit_line(
            open_stop["id"], f.append_visit_line_payload(_ghost(6), 5), technician
        ),
        "ERR_PRODUCT_NOT_FOUND",
        404,
    )
    path_wins = validate_error(
        api_client.append_visit_line(
            _ghost(9), f.append_visit_line_payload(_ghost(6), 5), technician
        ),
        "ERR_VISIT_NOT_FOUND",
        404,
    )
    assert path_wins["error_id"] != "ERR_PRODUCT_NOT_FOUND", (
        "the path identifier is resolved before the body's"
    )
    key_beats_state = validate_error(
        api_client.append_visit_line(
            reported_stop["id"], f.append_visit_line_payload(_ghost(6), 5), technician
        ),
        "ERR_PRODUCT_NOT_FOUND",
        404,
    )
    assert key_beats_state["error_id"] != "ERR_VISIT_STATE_INVALID", (
        "foreign-key resolution sits above the visit-state rule"
    )
    validate_error(
        api_client.credit_invoice(
            invoice_id, f.credit_invoice_payload(_ghost(12), 100, "Ghost line"), BS
        ),
        "ERR_INVOICE_LINE_NOT_FOUND",
        404,
    )
    settled = read_invoice(invoice_id)
    assert settled["total_cents"] == base["invoice"]["total_cents"]
    assert settled["line_count"] == base["invoice"]["line_count"]


def test_planning_is_refused_both_when_no_brewer_fits_and_when_there_is_no_history():
    """Three unplanned break rooms fail planning for three different reasons — a peak the
    only catalogued brewer cannot serve, a headcount outside its band, and a
    trailing-usage room with nothing yet to trail — and the third one plans cleanly the
    moment its variant is switched.

    "The eligible candidates are the brewer models whose headcount band contains the
    site's headcount — that is, the model's minimum headcount is at or below the site's
    headcount and the model's maximum headcount is at or above it, both bounds inclusive —
    and whose cups-per-hour capacity is at or above the site's required peak throughput."

    "If the site has no completed visit at all inside that window, the site cannot be
    planned and the request is rejected with `ERR_NO_TRAILING_USAGE` (HTTP 422)."

    Design: Corner/errors/corner_planning_rejects_a_site_no_brewer_fits_and_a_trailing_site_with_no_history
    """
    base = setup_catalog(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    account = create_account()
    route_id = base["route"]["id"]
    model = base["model"]
    assert model["min_headcount"] == 1
    assert model["max_headcount"] == 250
    assert model["cups_per_hour_capacity"] == 30

    at_the_band_edge = create_site(
        account["id"], route_id, site_name="Atrium Cafe Point", headcount=250
    )
    past_the_band = create_site(
        account["id"], route_id, site_name="Stadium Concourse", headcount=300
    )
    without_history = create_site(
        account["id"],
        route_id,
        site_name="Annex Kitchenette",
        headcount=40,
        consumption_model="TRAILING_USAGE",
    )

    # 250 * 1.8 * 5 = 2250 cups a week, so ceil(2250 / 5 * 0.35) == 158 cups an hour.
    validate_error(
        api_client.size_and_plan_site(
            at_the_band_edge["id"], f.size_and_plan_payload("DRIP"), AM
        ),
        "ERR_NO_MODEL_FITS_HEADCOUNT",
        422,
    )
    validate_error(
        api_client.size_and_plan_site(
            past_the_band["id"], f.size_and_plan_payload("DRIP"), AM
        ),
        "ERR_NO_MODEL_FITS_HEADCOUNT",
        422,
    )
    for room in (at_the_band_edge, past_the_band):
        refused = read_site(room["id"])
        assert refused["recommended_model_id"] is None
        assert refused["brew_style"] is None
        assert refused["version"] == room["version"], "only success spends a version"

    validate_error(
        api_client.size_and_plan_site(
            without_history["id"], f.size_and_plan_payload("DRIP"), AM
        ),
        "ERR_NO_TRAILING_USAGE",
        422,
    )
    assert list_par_lines(without_history["id"]) == []
    assert read_site(without_history["id"])["recommended_model_id"] is None

    switched = update_site(without_history["id"], consumption_model="HEADCOUNT_MODEL")
    assert switched["consumption_model"] == "HEADCOUNT_MODEL"
    planned = plan_site(without_history["id"], "DRIP")
    assert planned["forecast_cups_per_week"] == 360
    assert planned["required_peak_cups_per_hour"] == 26
    assert planned["recommended_model_id"] == model["id"]
    coffee_row = par_line_for(without_history["id"], base["products"]["COFFEE"]["id"])
    assert (coffee_row["par_units"], coffee_row["reorder_point_units"]) == (65, 26)


def test_a_period_with_nothing_to_bill_is_refused_rather_than_written_empty():
    """A period in which the account did nothing produces no invoice at all rather than a
    zero-cent shell, and the very same start instant becomes billable once one reported
    stop falls inside a widened window — so the refusal was about the lines, not the
    window.

    "`line_count` is the number of invoice lines written. An assembly that produced zero
    lines is rejected with `ERR_NO_BILLABLE_LINES` (HTTP 422) — there is no such thing as
    an empty invoice."

    "`freight_cents` is 0 when `pre_freight_total_cents` is at or above 50000, and
    otherwise a flat 2500 cents."

    Design: Corner/errors/corner_an_invoice_period_with_no_activity_is_rejected_rather_than_written_empty
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    account_id = base["account"]["id"]
    assert base["account"]["billing_mode"] == "CONSOLIDATED"
    quiet_version = read_account(account_id)["version"]

    validate_error(
        api_client.create_invoice(
            f.create_invoice_payload(
                account_id,
                "2026-08-01T00:00:00Z",
                "2026-08-02T00:00:00Z",
                quiet_version,
            ),
            BS,
        ),
        "ERR_NO_BILLABLE_LINES",
        422,
    )
    assert _count(api_client.list_invoices(BS, params={"account_id": account_id})) == 0
    assert read_account(account_id)["version"] == quiet_version, (
        "the refused assembly wrote nothing to the account either"
    )

    stop = schedule_stop_with_lines(base, {"COFFEE": 20})
    complete_stop(base, stop, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")

    billed = validate_success(
        api_client.create_invoice(
            f.create_invoice_payload(
                account_id,
                "2026-08-01T00:00:00Z",
                "2026-08-03T09:30:00Z",
                read_account(account_id)["version"],
            ),
            BS,
        ),
        201,
    )
    assert billed["line_count"] == 2
    assert billed["pre_freight_total_cents"] == 9000
    assert billed["allied_category_count"] == 0, "COFFEE itself is not an allied category"
    assert billed["allied_discount_bps"] == 0
    assert billed["allied_discount_cents"] == 0
    assert billed["freight_cents"] == 2500
    assert billed["total_cents"] == 11500
    assert billed["invoice_status"] == "DRAFT"


def test_the_negotiation_endpoints_are_scoped_to_opposite_statuses_and_a_closed_bound():
    """Revision and response are refused outside their own status, the revised figure is
    held to the closed interval between zero and the standing figure so 1300 and -100 both
    fail while 1200 passes, and acceptance closes the row to both endpoints for good.

    "The revised figure may only move **toward** the customer: it must lie in the closed
    interval between 0 and the current `adjustment_pct_bps` inclusive — so for a current
    increase of 1200 basis points any value from 0 through 1200 is acceptable and 1201 is
    not, and for a current reduction of -1200 basis points the mirrored bound applies,
    admitting any value from -1200 through 0."

    "Revision requires the adjustment to be `DISPUTED`, otherwise
    `ERR_ADJUSTMENT_STATE_INVALID`."

    Design: Corner/errors/corner_revise_and_respond_are_refused_outside_their_own_status_and_bounds
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
        **RENTAL_TERMS,
    )
    account_id = base["account"]["id"]
    contact = make_customer_contact_headers(account_id)

    set_market_index(2400000, headers=BS)
    proposal = propose_adjustment(account_id, effective_at="2026-09-01T00:00:00Z")
    adjustment_id = proposal["id"]
    assert proposal["movement_bps"] == 2000
    assert proposal["adjustment_pct_bps"] == 1200
    assert proposal["revision_count"] == 0

    validate_error(
        api_client.revise_price_adjustment(adjustment_id, f.revise_payload(600), BS),
        "ERR_ADJUSTMENT_STATE_INVALID",
        409,
    )
    held = read_adjustment(adjustment_id)
    assert held["adj_status"] == "PROPOSED"
    assert held["adjustment_pct_bps"] == 1200
    assert held["revision_count"] == 0

    disputed = respond_adjustment(
        adjustment_id,
        account_id,
        "DISPUTE",
        dispute_reason="Our blend is not index linked",
    )
    assert disputed["adj_status"] == "DISPUTED"
    assert read_account(account_id)["green_price_factor_bps"] == 10000

    validate_error(
        api_client.revise_price_adjustment(adjustment_id, f.revise_payload(1300), BS),
        "ERR_REVISION_OUT_OF_BOUNDS",
        422,
    )
    validate_error(
        api_client.revise_price_adjustment(adjustment_id, f.revise_payload(-100), BS),
        "ERR_REVISION_OUT_OF_BOUNDS",
        422,
    )
    assert read_adjustment(adjustment_id)["adj_status"] == "DISPUTED"

    at_the_upper_endpoint = revise_adjustment(adjustment_id, 1200)
    assert at_the_upper_endpoint["adj_status"] == "PROPOSED"
    assert at_the_upper_endpoint["adjustment_pct_bps"] == 1200
    assert at_the_upper_endpoint["revision_count"] == 1

    accepted = respond_adjustment(adjustment_id, account_id, "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"
    repriced = read_account(account_id)
    assert repriced["green_price_factor_bps"] == 11200
    assert repriced["green_index_baseline_micros"] == 2400000
    assert repriced["price_protection_until"] == "2026-11-01T08:00:00Z"

    validate_error(
        api_client.respond_price_adjustment(
            adjustment_id, f.respond_payload("ACCEPT"), contact
        ),
        "ERR_ADJUSTMENT_STATE_INVALID",
        409,
    )
    validate_error(
        api_client.revise_price_adjustment(adjustment_id, f.revise_payload(0), BS),
        "ERR_ADJUSTMENT_STATE_INVALID",
        409,
    )
    final = read_adjustment(adjustment_id)
    assert final["adj_status"] == "ACCEPTED"
    assert final["revision_count"] == 1
    assert final["adjustment_pct_bps"] == 1200


def test_a_deferred_negotiation_cannot_be_answered_until_a_break_room_recovers():
    """The refusal is manufactured four hops away: two break rooms run dry on the same
    round, the account turns risky and freezes the negotiation, and one honest delivery
    later the identical acceptance body succeeds — with nothing about the adjustment's own
    figures having been touched in between.

    "When the account moves `ACTIVE` → `AT_RISK` because two or more of its break rooms are
    escalated, every adjustment of that account in `PROPOSED` moves to `DEFERRED`, and
    while deferred the customer may not respond."

    "Responding to one that is `DEFERRED` is refused with its own dedicated code,
    `ERR_ADJUSTMENT_DEFERRED` (HTTP 409), because the reason is different and worth telling
    the customer: the account is `AT_RISK` and the negotiation is frozen until service
    recovers."

    Design: Corner/errors/corner_a_deferred_adjustment_cannot_be_answered_until_the_account_recovers
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_CREAMER,
        **RENTAL_TERMS,
    )
    account_id = base["account"]["id"]
    room_a = base["site"]
    room_b = setup_second_site(base)
    contact = make_customer_contact_headers(account_id)
    one_of_each = {"COFFEE": 1, "CREAMER": 1}

    first_a = schedule_stop_with_lines(base, one_of_each)
    first_b = schedule_stop_with_lines(
        base,
        one_of_each,
        site=room_b,
        window_start="2026-08-03T11:00:00Z",
        window_end="2026-08-03T11:45:00Z",
    )
    complete_stop(base, first_a, one_of_each)
    complete_stop(base, first_b, one_of_each)
    assert read_site(room_a["id"])["escalation_score"] == 15.0
    assert read_site(room_b["id"])["escalation_score"] == 15.0

    second_a = schedule_stop_with_lines(
        base,
        one_of_each,
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    second_b = schedule_stop_with_lines(
        base,
        one_of_each,
        site=room_b,
        window_start="2026-08-10T11:00:00Z",
        window_end="2026-08-10T11:45:00Z",
    )
    third_a = schedule_stop_with_lines(
        base,
        one_of_each,
        window_start="2026-08-17T09:00:00Z",
        window_end="2026-08-17T09:45:00Z",
    )

    set_market_index(2400000, headers=BS)
    proposal = propose_adjustment(account_id, effective_at="2026-09-01T00:00:00Z")
    adjustment_id = proposal["id"]
    assert proposal["adj_status"] == "PROPOSED"
    assert proposal["adjustment_pct_bps"] == 1200

    complete_stop(base, second_a, complete_at="2026-08-10T09:30:00Z")
    escalated_a = read_site(room_a["id"])
    assert escalated_a["escalation_score"] == 40.0, "two stockouts weigh exactly 40.0"
    assert escalated_a["service_posture"] == "ESCALATED"
    one_room_down = read_account(account_id)
    assert one_room_down["escalated_site_count"] == 1
    assert one_room_down["program_posture"] == "ACTIVE"
    assert read_adjustment(adjustment_id)["adj_status"] == "PROPOSED"

    complete_stop(base, second_b, complete_at="2026-08-10T11:30:00Z")
    both_rooms_down = read_account(account_id)
    assert both_rooms_down["escalated_site_count"] == 2
    assert both_rooms_down["program_posture"] == "AT_RISK"
    frozen = read_adjustment(adjustment_id)
    assert frozen["adj_status"] == "DEFERRED"

    validate_error(
        api_client.respond_price_adjustment(
            adjustment_id, f.respond_payload("ACCEPT"), contact
        ),
        "ERR_ADJUSTMENT_DEFERRED",
        409,
    )
    still_frozen = read_adjustment(adjustment_id)
    assert still_frozen["adj_status"] == "DEFERRED"
    assert still_frozen["accepted_at"] is None
    assert read_account(account_id)["green_price_factor_bps"] == 10000

    complete_stop(base, third_a, one_of_each, complete_at="2026-08-17T09:30:00Z")
    recovered_a = read_site(room_a["id"])
    assert recovered_a["escalation_score"] == 15.0
    assert recovered_a["service_posture"] == "ACTIVE"
    recovered_account = read_account(account_id)
    assert recovered_account["escalated_site_count"] == 1
    assert recovered_account["program_posture"] == "ACTIVE"
    thawed = read_adjustment(adjustment_id)
    assert thawed["adj_status"] == "PROPOSED"
    assert thawed["adjustment_pct_bps"] == 1200, "a deferral round trip changes nothing"

    accepted = respond_adjustment(adjustment_id, account_id, "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"
    assert read_account(account_id)["green_price_factor_bps"] == 11200
