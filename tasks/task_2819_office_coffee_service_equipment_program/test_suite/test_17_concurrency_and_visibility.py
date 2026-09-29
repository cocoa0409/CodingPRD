"""Optimistic concurrency and immediate visibility: the site token invalidated by a
revision no client saw, the account token invalidated by an accepted price adjustment,
and every derived aggregate legible in the very next request.
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
    CATALOG_SPEC_COFFEE_ONLY,
    append_line,
    complete_stop,
    complete_visit,
    create_asset,
    list_invoice_lines,
    list_placements,
    par_line_for,
    propose_adjustment,
    read_account,
    read_asset,
    read_day_load,
    read_site,
    read_visit,
    respond_adjustment,
    schedule_stop_with_lines,
    schedule_visit,
    set_clock,
    set_market_index,
    setup_placed_site,
    setup_planned_site,
    update_site,
)
from test_helpers.test_users import TEST_USERS

PA = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

RENTAL_TERMS = {
    "terms_type": "RENTAL",
    "minimum_purchase_cents": 60000,
    "min_term_months": 12,
}


def _count(response) -> int:
    """The honest row count behind a listing page."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_a_placement_is_refused_on_a_stale_site_token_and_accepted_after_a_re_read():
    """The guard token is the break room's version, and a revision that touched only the
    headcount is enough to invalidate it. The refusal consumes no asset and writes no row,
    the identical body succeeds once the site is re-read, and the success spends the very
    token it was accepted with — so a second installation on the same token fails in turn.

    "Creating an equipment placement requires a non-optional `expected_site_version` field
    carrying the client's last observed `version` of the target `Site`. If it does not
    equal the site's current `version`, the request is rejected with
    `ERR_STALE_SITE_VERSION` (HTTP 412)."

    "In the same operation the asset moves to `PLACED`, the site's `version` increments by
    1, and — if this is the first installed equipment on the account — the account leaves
    `ONBOARDING` for `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/corner_placement_creation_rejects_a_stale_site_version_and_succeeds_after_a_re_read
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    account_id = base["account"]["id"]
    first_asset = create_asset(base["model"]["id"], serial_number="URN30-0001")
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")

    stale_version = read_site(site_id)["version"]
    update_site(site_id, headcount=45)
    fresh_version = read_site(site_id)["version"]
    assert fresh_version == stale_version + 1, (
        "the revision the installer never saw spent exactly one version"
    )
    assert read_account(account_id)["program_posture"] == "ONBOARDING"

    stale_body = f.create_placement_payload(
        site_id, first_asset["id"], stale_version, **RENTAL_TERMS
    )
    validate_error(
        api_client.create_placement(stale_body, AM),
        "ERR_STALE_SITE_VERSION",
        412,
    )
    assert list_placements(site_id=site_id) == [], "the refusal wrote no row"
    assert read_asset(first_asset["id"])["asset_status"] == "IN_STOCK", (
        "the refusal consumed no fleet unit"
    )
    assert read_site(site_id)["version"] == fresh_version, (
        "a rejected write does not itself move the version it complained about"
    )

    fresh_body = f.create_placement_payload(
        site_id, first_asset["id"], fresh_version, **RENTAL_TERMS
    )
    installed = validate_success(api_client.create_placement(fresh_body, AM), 201)
    assert installed["placement_status"] == "ACTIVE"
    assert installed["compliance_status"] == "MEETING_MINIMUM"
    assert installed["site_id"] == site_id
    assert read_asset(first_asset["id"])["asset_status"] == "PLACED"
    assert read_account(account_id)["program_posture"] == "ACTIVE"

    assert read_site(site_id)["version"] == fresh_version + 1, (
        "the accepted installation spent the token it was accepted with"
    )
    validate_error(
        api_client.create_placement(
            f.create_placement_payload(
                site_id, second_asset["id"], fresh_version, **RENTAL_TERMS
            ),
            AM,
        ),
        "ERR_STALE_SITE_VERSION",
        412,
    )
    assert len(list_placements(site_id=site_id)) == 1
    assert read_asset(second_asset["id"])["asset_status"] == "IN_STOCK"


def test_invoice_assembly_is_refused_on_a_stale_account_token_and_still_bills_the_snapshot():
    """The token is invalidated by an accepted price adjustment — a write the invoicing
    client never saw and cannot have caused — and the retry proves the two facts are
    independent: the account now carries an 11200 factor, yet the billed line is still the
    4500000 micros snapshotted onto the visit line at completion.

    "Creating a consolidated invoice draft requires a non-optional
    `expected_account_version` field carrying the client's last observed `version` of the
    target `Account`. If it does not equal the account's current `version`, the request is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    "Each such line carries the `product_id`, a `qty_units` equal to the delivered
    quantity, and a `unit_price_micros` copied straight from the
    `effective_unit_price_micros` snapshotted on the visit line at completion — never
    recomputed at invoice time."

    Design: Corner/cross_cutting_complexity_layers/corner_invoice_assembly_rejects_a_stale_account_version_and_still_honours_the_price_snapshot
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    account_id = base["account"]["id"]
    site_id = base["site"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]

    stop = schedule_stop_with_lines(base, {"COFFEE": 20})
    complete_stop(base, stop, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")
    served_line = read_visit(stop["id"])["lines"][0]
    assert served_line["delivered_units"] == 20
    assert served_line["effective_unit_price_micros"] == 4500000, (
        "the price was snapshotted while the factor was still neutral"
    )

    stale_version = read_account(account_id)["version"]
    set_market_index(2400000, headers=BS)
    proposal = propose_adjustment(account_id, effective_at="2026-09-01T00:00:00Z")
    assert proposal["adjustment_pct_bps"] == 1200
    accepted = respond_adjustment(proposal["id"], account_id, "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"

    repriced = read_account(account_id)
    assert repriced["version"] == stale_version + 1, (
        "the acceptance the invoicing client never saw spent exactly one version"
    )
    assert repriced["green_price_factor_bps"] == 11200

    period_start = "2026-08-01T00:00:00Z"
    period_end = "2026-08-03T09:30:00Z"
    validate_error(
        api_client.create_invoice(
            f.create_invoice_payload(
                account_id, period_start, period_end, stale_version
            ),
            BS,
        ),
        "ERR_STALE_ACCOUNT_VERSION",
        412,
    )
    assert _count(api_client.list_invoices(BS, params={"account_id": account_id})) == 0
    assert read_account(account_id)["version"] == repriced["version"]

    invoice = validate_success(
        api_client.create_invoice(
            f.create_invoice_payload(
                account_id, period_start, period_end, repriced["version"]
            ),
            BS,
        ),
        201,
    )
    assert invoice["line_count"] == 2
    assert invoice["pre_freight_total_cents"] == 9000, (
        "20 units at the snapshotted 450 cents each, not at the repriced 504"
    )
    assert invoice["allied_discount_cents"] == 0
    assert invoice["freight_cents"] == 2500
    assert invoice["total_cents"] == 11500
    assert invoice["invoice_status"] == "DRAFT"

    product_lines = list_invoice_lines(invoice["id"], line_type="PRODUCT")
    assert len(product_lines) == 1
    assert product_lines[0]["product_id"] == coffee_id
    assert product_lines[0]["qty_units"] == 20
    assert product_lines[0]["unit_price_micros"] == 4500000
    assert product_lines[0]["amount_cents"] == 9000
    assert product_lines[0]["site_id"] == site_id
    assert read_account(account_id)["version"] == repriced["version"] + 1


def test_every_derived_aggregate_is_readable_in_the_very_next_request():
    """Nine calls in a row, each one reading back what the call before it derived: the
    route's day load after a stop is booked, the visit's line array after a line is
    appended, the four stamped members in the completion response itself, the shelf ledger
    immediately after, and the invoice's children as soon as the invoice exists.

    "The same day-load arithmetic is exposed as a computed read for a `ProgramAdmin`,
    `AccountManager` or `RouteTechnician`: supplying a `service_date` returns that date's
    `service_date`, `booked_minutes_day`, `remaining_minutes` and the route's
    `capacity_minutes`, where the remaining minutes are the route's capacity minus the
    day's booked minutes."

    "**Each line element is then stamped** with four computed members. `consumed_units`
    receives the modelled consumption above. `delivered_units` receives the reported
    quantity, or 0 when the product was absent from `delivered_lines`.
    `effective_unit_price_micros` receives the effective price described below.
    `resulting_on_hand_units` receives the par line's shelf quantity **after** the write."

    Design: Corner/consistency_model/corner_every_derived_aggregate_is_readable_in_the_very_next_request
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    account_id = base["account"]["id"]
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]

    booked = schedule_visit(site_id)
    assert booked["route_id"] == route_id, (
        "the stop already knows its route from the break room"
    )
    assert booked["visit_status"] == "SCHEDULED"
    load = read_day_load(route_id, "2026-08-03")
    assert load["service_date"] == "2026-08-03"
    assert load["capacity_minutes"] == 480
    assert load["booked_minutes_day"] == 45, "the stop booked one request earlier"
    assert load["remaining_minutes"] == 435

    appended = append_line(booked["id"], route_id, coffee_id, 20)
    assert len(appended["lines"]) == 1
    echoed = read_visit(booked["id"])
    assert len(echoed["lines"]) == 1
    assert echoed["lines"][0]["product_id"] == coffee_id
    assert echoed["lines"][0]["requested_units"] == 20
    assert echoed["lines"][0]["delivered_units"] is None, "nothing has been served yet"

    set_clock("2026-08-03T09:30:00Z")
    served = complete_visit(booked["id"], route_id, [f.delivered_line(coffee_id, 20)])
    assert served["visit_status"] == "COMPLETED"
    stamped = served["lines"][0]
    assert stamped["consumed_units"] == 0, "no whole day elapsed since the last service"
    assert stamped["delivered_units"] == 20
    assert stamped["effective_unit_price_micros"] == 4500000
    assert stamped["resulting_on_hand_units"] == 20

    shelf = par_line_for(site_id, coffee_id)
    assert shelf["on_hand_units"] == 20
    assert shelf["cumulative_delivered_units"] == 20
    assert shelf["cumulative_consumed_units"] == 0
    assert shelf["last_service_at"] == "2026-08-03T09:00:00Z"
    assert shelf["stock_status"] == "LOW"

    account_version = read_account(account_id)["version"]
    invoice = validate_success(
        api_client.create_invoice(
            f.create_invoice_payload(
                account_id,
                "2026-08-01T00:00:00Z",
                "2026-08-03T09:30:00Z",
                account_version,
            ),
            BS,
        ),
        201,
    )
    assert invoice["line_count"] == 2
    assert invoice["total_cents"] == 11500

    children = list_invoice_lines(invoice["id"])
    assert len(children) == 2, "the children are visible as soon as the parent is"
    amounts = {row["line_type"]: row["amount_cents"] for row in children}
    assert amounts == {"PRODUCT": 9000, "FREIGHT": 2500}
    for row in children:
        assert row["invoice_id"] == invoice["id"]
        assert row["credits_applied_cents"] == 0
