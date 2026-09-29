"""Validation families taken as families: every uniqueness key against its own
duplicate code, the invoice period and scope rules, the visit-line coherence
rules, the conditional commitment floor and role partition, the posture gates in
their declared order, and the per-target-state transition fields.
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
    advance_work_order,
    cancel_account,
    complete_stop,
    create_account,
    create_asset,
    create_manual_par_line,
    create_product,
    create_second_route,
    create_site,
    create_work_order,
    list_par_lines,
    par_line_for,
    place_asset_at_site,
    plan_site,
    propose_adjustment,
    read_account,
    read_adjustment,
    read_asset,
    read_day_load,
    read_placement,
    read_route,
    read_site,
    read_visit,
    read_work_order,
    respond_adjustment,
    schedule_stop_with_lines,
    schedule_visit,
    set_clock,
    set_market_index,
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


def _total_count(response) -> int:
    """The honest row count behind a listing page."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_every_uniqueness_rule_answers_with_its_own_duplicate_code():
    """A repeated model code, serial number and SKU each answer with their own
    conflict code, and a manual par line cannot shadow the forecast line the server
    itself wrote for that break room and product.

    "A `ProgramAdmin` registers each physical brewer in the fleet with the `model_id`
    of its catalog model, a `serial_number` that is non-empty and unique across the
    fleet (a repeat yields `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409), and an
    `asset_role` of either `PLACEMENT` or `LOANER`."

    "At most one par line may exist per site-and-product pair whatever its source; a
    duplicate yields `ERR_DUPLICATE_PAR_LEVEL` (HTTP 409)."

    Design: Corner/validations/corner_every_uniqueness_rule_rejects_its_own_duplicate_key
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    coffee = base["products"]["COFFEE"]
    create_asset(base["model"]["id"], serial_number="URN30-0001")

    validate_error(
        api_client.create_equipment_model(
            f.create_equipment_model_payload(
                model_code=base["model"]["model_code"],
                brewer_class="AIRPOT",
                cups_per_hour_capacity=60,
                min_headcount=5,
                max_headcount=300,
                monthly_rent_cents=9900,
                descale_interval_days=60,
                list_value_cents=200000,
            ),
            PA,
        ),
        "ERR_DUPLICATE_MODEL_CODE",
        409,
    )
    assert _total_count(api_client.list_equipment_models(PA)) == 1
    assert validate_success(
        api_client.get_equipment_model(base["model"]["id"], PA)
    )["cups_per_hour_capacity"] == 30, "the rejected 60-cup values were never written"

    validate_error(
        api_client.create_equipment_asset(
            f.create_equipment_asset_payload(
                base["model"]["id"], serial_number="URN30-0001", asset_role="LOANER"
            ),
            PA,
        ),
        "ERR_DUPLICATE_SERIAL_NUMBER",
        409,
    )
    assert _total_count(api_client.list_equipment_assets(PA)) == 1

    validate_error(
        api_client.create_product_item(
            f.create_product_item_payload(
                sku=coffee["sku"],
                category="TEA",
                base_unit_price_micros=1500000,
                pack_units=100,
            ),
            PA,
        ),
        "ERR_DUPLICATE_SKU",
        409,
    )
    assert _total_count(api_client.list_product_items(PA)) == 1

    validate_error(
        api_client.create_par_level(
            f.create_par_level_payload(
                site_id, coffee["id"], par_units=10, reorder_point_units=5
            ),
            AM,
        ),
        "ERR_DUPLICATE_PAR_LEVEL",
        409,
    )
    survivor = par_line_for(site_id, coffee["id"])
    assert survivor["par_units"] == 65
    assert survivor["reorder_point_units"] == 26
    assert survivor["source"] == "FORECAST"
    assert len(list_par_lines(site_id)) == 1


def test_keys_that_genuinely_differ_are_all_accepted():
    """A different model code, serial number and SKU are all registered, and a
    manual par line for a different product survives a re-plan that rewrites the
    forecast line beside it.

    "Lines whose `source` is `MANUAL` are **never** touched by planning, no matter
    how many times it runs."

    "A site's demand attributes — `headcount`, `days_per_week`, `consumption_model`
    and `route_id` — may later be revised individually by an `AccountManager`; each
    supplied field replaces the stored value and the site's `version` increments by
    1, but revising them deliberately does **not** re-run the forecast:
    `forecast_cups_per_week`, `required_peak_cups_per_hour`, `recommended_model_id`
    and every existing par line are left exactly as they were until planning is run
    again."

    Design: Corner/validations/corner_keys_that_actually_differ_are_all_accepted
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]

    second_model = validate_success(
        api_client.create_equipment_model(
            f.create_equipment_model_payload(
                model_code="URN-60",
                brewer_class="AIRPOT",
                cups_per_hour_capacity=60,
                min_headcount=1,
                max_headcount=400,
                monthly_rent_cents=9900,
                descale_interval_days=60,
                list_value_cents=200000,
            ),
            PA,
        ),
        201,
    )
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")
    tea = create_product(
        sku="TEA-BLK-100",
        category="TEA",
        base_unit_price_micros=1500000,
        pack_units=100,
        green_coffee_linked=False,
    )
    assert second_model["model_code"] == "URN-60"
    assert second_asset["serial_number"] == "URN30-0002"

    tea_line = create_manual_par_line(
        site_id, tea["id"], par_units=10, reorder_point_units=4
    )
    assert tea_line["source"] == "MANUAL"
    assert tea_line["par_units"] == 10
    assert tea_line["reorder_point_units"] == 4

    revised = update_site(site_id, headcount=45)
    assert revised["headcount"] == 45
    assert revised["forecast_cups_per_week"] == 360, "revision alone never re-forecasts"

    replanned = plan_site(site_id)
    assert replanned["forecast_cups_per_week"] == 405
    assert replanned["required_peak_cups_per_hour"] == 29
    rewritten = par_line_for(site_id, coffee_id)
    assert rewritten["par_units"] == 73
    assert rewritten["reorder_point_units"] == 30
    assert rewritten["source"] == "FORECAST"

    untouched = par_line_for(site_id, tea["id"])
    assert untouched["par_units"] == 10
    assert untouched["reorder_point_units"] == 4
    assert untouched["source"] == "MANUAL"

    assert len(list_par_lines(site_id)) == 2, "the re-plan added no second tea row"
    assert len(list_par_lines(site_id, source="FORECAST")) == 1
    assert len(list_par_lines(site_id, source="MANUAL")) == 1


AUGUST = ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")


def _draft_attempt(account_id: str, period_start: str, period_end: str, **extra):
    """One draft assembly attempt against the account's current version."""
    version = read_account(account_id)["version"]
    return api_client.create_invoice(
        f.create_invoice_payload(
            account_id, period_start, period_end, version, **extra
        ),
        BS,
    )


def test_the_invoice_period_family_refuses_open_reversed_and_touching_windows():
    """A period running past the current instant and a reversed period are both
    malformed, while a period sharing a single endpoint instant with an existing
    draft is an overlap because the intervals are closed.

    "The period must be well-formed and must be **closed**: `period_end` must be
    strictly after `period_start`, and `period_end` must be at or before the current
    instant."

    "Periods are treated as closed intervals, so sharing even a single endpoint
    instant counts as an overlap; a violation yields `ERR_INVOICE_PERIOD_OVERLAP`
    (HTTP 409)."

    Design: Corner/validations/corner_invoice_period_family_rejects_unclosed_reversed_and_overlapping_windows
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    account_id = base["account"]["id"]
    stop = schedule_stop_with_lines(base, {"COFFEE": 20})
    complete_stop(base, stop, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")
    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        _draft_attempt(account_id, "2026-08-01T00:00:00Z", "2026-09-30T23:59:59Z"),
        "ERR_PERIOD_INVALID",
        422,
    )
    validate_error(
        _draft_attempt(account_id, "2026-08-31T23:59:59Z", "2026-08-01T00:00:00Z"),
        "ERR_PERIOD_INVALID",
        422,
    )
    assert _total_count(
        api_client.list_invoices(BS, params={"account_id": account_id})
    ) == 0, "neither malformed period wrote a row"

    august = validate_success(_draft_attempt(account_id, *AUGUST), 201)
    assert august["invoice_status"] == "DRAFT"
    assert august["period_start"] == AUGUST[0]
    assert august["period_end"] == AUGUST[1]

    version_after_august = read_account(account_id)["version"]
    validate_error(
        _draft_attempt(
            account_id, "2026-08-31T23:59:59Z", "2026-09-01T00:00:00Z"
        ),
        "ERR_INVOICE_PERIOD_OVERLAP",
        409,
    )
    assert _total_count(
        api_client.list_invoices(BS, params={"account_id": account_id})
    ) == 1
    assert read_account(account_id)["version"] == version_after_august


def test_the_price_protection_window_blocks_a_reproposal_until_it_lapses():
    """Accepting an adjustment arms the protection window, so a second proposal with
    an amply adjustable movement is refused while the window is still ahead of the
    clock, and accepted at the protection instant itself.

    "No new adjustment may be proposed while the account's `price_protection_until`
    is still ahead of the current instant; an attempt is rejected with
    `ERR_PRICE_PROTECTION_ACTIVE` (HTTP 422)."

    "The account's `price_protection_until` is set to the current instant advanced by
    the account's `price_protection_days`."

    Design: Corner/validations/corner_price_protection_window_blocks_a_reproposal_until_it_lapses
    """
    set_clock(ANCHOR_MONDAY)
    account = create_account(
        green_index_baseline_micros=2000000, price_protection_days=90
    )
    account_id = account["id"]
    assert account["price_protection_until"] is None

    set_market_index(2400000, headers=BS)
    first = propose_adjustment(account_id, effective_at="2026-09-01T00:00:00Z")
    accepted = respond_adjustment(first["id"], account_id, "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"
    assert accepted["accepted_at"] == ANCHOR_MONDAY

    protected = read_account(account_id)
    assert protected["green_price_factor_bps"] == 11200
    assert protected["green_index_baseline_micros"] == 2400000
    assert protected["price_protection_until"] == "2026-11-01T08:00:00Z"

    # A 200000-micro move off the re-based baseline is 833 bps, well past 800.
    set_market_index(2600000, headers=BS)
    validate_error(
        api_client.create_price_adjustment(
            f.create_price_adjustment_payload(
                account_id, effective_at="2026-09-01T00:00:00Z"
            ),
            BS,
        ),
        "ERR_PRICE_PROTECTION_ACTIVE",
        422,
    )

    # One second short of the protection instant the window is still ahead of the
    # clock, so the guard bites.
    set_clock("2026-11-01T07:59:59Z")
    validate_error(
        api_client.create_price_adjustment(
            f.create_price_adjustment_payload(
                account_id, effective_at="2026-11-15T00:00:00Z"
            ),
            BS,
        ),
        "ERR_PRICE_PROTECTION_ACTIVE",
        422,
    )

    # "No new adjustment may be proposed while the account's
    # `price_protection_until` is still **ahead of** the current instant" — at the
    # protection instant itself the window is no longer ahead of the clock, so the
    # proposal is admitted.
    set_clock("2026-11-01T08:00:00Z")
    second = validate_success(
        api_client.create_price_adjustment(
            f.create_price_adjustment_payload(
                account_id, effective_at="2026-11-15T00:00:00Z"
            ),
            BS,
        ),
        201,
    )
    assert second["movement_bps"] == 833
    assert second["adjustment_pct_bps"] == 500
    assert second["adj_status"] == "PROPOSED"
    assert _total_count(
        api_client.list_price_adjustments(BS, params={"account_id": account_id})
    ) == 2, "the two refused proposals created nothing"


def test_invoice_scope_must_match_the_billing_mode_and_own_the_break_room():
    """A consolidated programme refuses a break-room-scoped draft and a per-site one
    refuses an account-wide draft; naming somebody else's break room answers with the
    ownership gate, which is declared above the scope gate.

    "A `CONSOLIDATED` account is invoiced whole, so `site_id` must be **absent**; a
    `PER_SITE` account is invoiced one break room at a time, so `site_id` must be
    **present**."

    "31. through 36. **Referential coherence gates** — site planned, product stocked,
    duplicate visit line, credit target, site-in-account, billing-mode scope."

    Design: Corner/validations/corner_invoice_scope_must_match_the_accounts_billing_mode_and_own_the_site
    """
    whole = setup_planned_site(
        clock=ANCHOR_MONDAY,
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
        account_overrides={"legal_name": "Northgate Holdings LLC"},
    )
    tuesday_route = create_second_route(name="Uptown Tuesday Route", service_day="TUE")
    per_site_account = create_account(
        legal_name="Southgate Partners LLC", billing_mode="PER_SITE"
    )
    per_site_room = plan_site(
        create_site(
            per_site_account["id"],
            tuesday_route["id"],
            site_name="Southgate Ground Floor",
        )["id"]
    )
    per_site_base = dict(whole)
    per_site_base["route"] = tuesday_route
    per_site_base["site"] = per_site_room

    first_stop = schedule_stop_with_lines(whole, {"COFFEE": 20})
    complete_stop(whole, first_stop, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")
    second_stop = schedule_stop_with_lines(
        per_site_base,
        {"COFFEE": 20},
        window_start="2026-08-04T09:00:00Z",
        window_end="2026-08-04T09:45:00Z",
    )
    complete_stop(
        per_site_base, second_stop, {"COFFEE": 20}, complete_at="2026-08-04T09:30:00Z"
    )
    set_clock("2026-09-01T00:00:00Z")

    consolidated_id = whole["account"]["id"]
    per_site_id = per_site_account["id"]

    validate_error(
        _draft_attempt(consolidated_id, *AUGUST, site_id=whole["site"]["id"]),
        "ERR_BILLING_MODE_MISMATCH",
        422,
    )
    validate_error(
        _draft_attempt(per_site_id, *AUGUST), "ERR_BILLING_MODE_MISMATCH", 422
    )
    validate_error(
        _draft_attempt(per_site_id, *AUGUST, site_id=whole["site"]["id"]),
        "ERR_SITE_NOT_IN_ACCOUNT",
        422,
    )
    both_wrong = _draft_attempt(
        consolidated_id, *AUGUST, site_id=per_site_room["id"]
    )
    error = validate_error(both_wrong, "ERR_SITE_NOT_IN_ACCOUNT", 422)
    assert error["error_id"] != "ERR_BILLING_MODE_MISMATCH", (
        "site-in-account is declared above billing-mode scope"
    )

    account_wide = validate_success(_draft_attempt(consolidated_id, *AUGUST), 201)
    assert account_wide["site_id"] is None
    room_only = validate_success(
        _draft_attempt(per_site_id, *AUGUST, site_id=per_site_room["id"]), 201
    )
    assert room_only["site_id"] == per_site_room["id"]
    assert _total_count(api_client.list_invoices(BS)) == 2


def test_the_visit_line_family_checks_stocking_duplication_and_reported_units():
    """A product the break room does not stock cannot be requested, a product already
    on the stop cannot be requested twice, and a report that overshoots the request or
    names an unrequested product writes nothing at all.

    "Two coherence rules guard the append: the product must actually be stocked at the
    site, meaning a par line exists for that site-and-product pair (otherwise
    `ERR_PRODUCT_NOT_STOCKED`, HTTP 422), and a visit may carry at most one line per
    product (otherwise `ERR_DUPLICATE_VISIT_LINE`, HTTP 422)."

    "Only products already present on the visit's `lines` array may be reported, each
    reported quantity must be at least 0 and must not exceed that line's
    `requested_units`, and any violation of either — including naming a product absent
    from the visit's lines — is rejected with `ERR_DELIVERED_EXCEEDS_REQUESTED` (HTTP
    422)."

    Design: Corner/validations/corner_visit_line_family_checks_stocking_duplication_and_reported_quantities
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    # Catalogued after planning, so this break room has no par line for it.
    tea = create_product(
        sku="TEA-BLK-100",
        category="TEA",
        base_unit_price_micros=1500000,
        pack_units=100,
        green_coffee_linked=False,
    )
    technician = make_route_technician_headers(base["route"]["id"])
    visit = schedule_visit(site_id)

    validate_error(
        api_client.append_visit_line(
            visit["id"], f.append_visit_line_payload(tea["id"], 5), technician
        ),
        "ERR_PRODUCT_NOT_STOCKED",
        422,
    )
    assert read_visit(visit["id"])["lines"] == []

    appended = validate_success(
        api_client.append_visit_line(
            visit["id"], f.append_visit_line_payload(coffee_id, 20), technician
        ),
        200,
    )
    assert len(appended["lines"]) == 1
    assert appended["lines"][0]["requested_units"] == 20

    validate_error(
        api_client.append_visit_line(
            visit["id"], f.append_visit_line_payload(coffee_id, 5), technician
        ),
        "ERR_DUPLICATE_VISIT_LINE",
        422,
    )
    kept = read_visit(visit["id"])
    assert len(kept["lines"]) == 1
    assert kept["lines"][0]["requested_units"] == 20, "not overwritten with 5"

    set_clock("2026-08-03T09:30:00Z")
    validate_error(
        api_client.complete_visit(
            visit["id"],
            f.complete_visit_payload([f.delivered_line(coffee_id, 21)]),
            technician,
        ),
        "ERR_DELIVERED_EXCEEDS_REQUESTED",
        422,
    )
    assert read_visit(visit["id"])["visit_status"] == "SCHEDULED"
    assert par_line_for(site_id, coffee_id)["on_hand_units"] == 0

    validate_error(
        api_client.complete_visit(
            visit["id"],
            f.complete_visit_payload(
                [f.delivered_line(coffee_id, 20), f.delivered_line(tea["id"], 1)]
            ),
            technician,
        ),
        "ERR_DELIVERED_EXCEEDS_REQUESTED",
        422,
    )
    assert par_line_for(site_id, coffee_id)["on_hand_units"] == 0, (
        "a partially applied delivery is never written"
    )

    completed = validate_success(
        api_client.complete_visit(
            visit["id"],
            f.complete_visit_payload([f.delivered_line(coffee_id, 20)]),
            technician,
        ),
        200,
    )
    assert completed["visit_status"] == "COMPLETED"
    shelf = par_line_for(site_id, coffee_id)
    assert shelf["on_hand_units"] == 20
    assert shelf["cumulative_delivered_units"] == 20


def test_a_service_window_must_be_minute_aligned_and_land_on_the_service_day():
    """Seconds in the window and a Tuesday window on a Monday route are both refused,
    identically on creation and on reschedule, and a refused call never books a
    technician minute.

    "Window validity comes third: `window_end` must be strictly after `window_start`,
    both instants must be minute-aligned, and `window_start` must fall on the route's
    own `service_day` when evaluated in UTC."

    "Because `planned_minutes` is not changed by a reschedule, the route's
    `booked_minutes_total` is unchanged by the operation."

    Design: Corner/validations/corner_visit_window_must_be_minute_aligned_and_land_on_the_routes_service_day
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]

    validate_error(
        api_client.create_visit(
            f.create_visit_payload(
                site_id,
                window_start="2026-08-03T09:00:30Z",
                window_end="2026-08-03T09:45:00Z",
            ),
            AM,
        ),
        "ERR_VISIT_WINDOW_INVALID",
        422,
    )
    validate_error(
        api_client.create_visit(
            f.create_visit_payload(
                site_id,
                window_start="2026-08-04T09:00:00Z",
                window_end="2026-08-04T09:45:00Z",
            ),
            AM,
        ),
        "ERR_VISIT_WINDOW_INVALID",
        422,
    )
    assert _total_count(api_client.list_visits(AM, params={"site_id": site_id})) == 0
    assert read_route(route_id)["booked_minutes_total"] == 0

    visit = validate_success(
        api_client.create_visit(f.create_visit_payload(site_id), AM), 201
    )
    assert visit["visit_status"] == "SCHEDULED"
    assert visit["route_id"] == route_id, "copied from the site, never client-supplied"

    validate_error(
        api_client.reschedule_visit(
            visit["id"],
            f.reschedule_visit_payload(
                "2026-08-05T09:00:00Z", "2026-08-05T09:45:00Z"
            ),
            AM,
        ),
        "ERR_VISIT_WINDOW_INVALID",
        422,
    )
    assert read_visit(visit["id"])["window_start"] == "2026-08-03T09:00:00Z"

    moved = validate_success(
        api_client.reschedule_visit(
            visit["id"],
            f.reschedule_visit_payload(
                "2026-08-10T09:00:00Z", "2026-08-10T09:45:00Z"
            ),
            AM,
        ),
        200,
    )
    assert moved["window_start"] == "2026-08-10T09:00:00Z"

    vacated = read_day_load(route_id, "2026-08-03")
    assert vacated["booked_minutes_day"] == 0
    assert vacated["remaining_minutes"] == 480
    occupied = read_day_load(route_id, "2026-08-10")
    assert occupied["booked_minutes_day"] == 45
    assert occupied["remaining_minutes"] == 435
    assert occupied["capacity_minutes"] == 480
    assert read_route(route_id)["booked_minutes_total"] == 45


def test_the_loan_commitment_floor_and_the_role_partition_are_both_conditional():
    """The seven-hundred-fifty-dollar commitment floor binds a loan and not a rental,
    it binds at or above rather than above, and a loaner-role brewer may never be
    installed at a break room however healthy the commitment.

    "A `LOAN` placement's `minimum_purchase_cents` must be at least 75000 — seven
    hundred fifty dollars of trailing purchase per compliance window — and a `LOAN`
    placement declaring less is rejected with `ERR_MINIMUM_BELOW_LOAN_FLOOR` (HTTP
    422). `RENTAL` placements have no such floor and may declare a commitment of
    zero."

    "The role is a hard partition: only a `PLACEMENT` asset may be installed at a
    site, and only a `LOANER` asset may be attached to a work order as a substitute
    unit. Using an asset in the wrong capacity in either direction is rejected with
    `ERR_ASSET_ROLE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/corner_loan_floor_applies_only_to_loan_terms_and_only_placement_assets_may_be_placed
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    first_room = base["site"]
    second_room = setup_second_site(base)
    model_id = base["model"]["id"]
    first_asset = create_asset(model_id, serial_number="URN30-0001")
    second_asset = create_asset(model_id, serial_number="URN30-0002")
    loaner = create_asset(model_id, serial_number="LNR-0001", asset_role="LOANER")
    first_version = read_site(first_room["id"])["version"]

    validate_error(
        api_client.create_placement(
            f.create_placement_payload(
                first_room["id"],
                first_asset["id"],
                first_version,
                terms_type="LOAN",
                minimum_purchase_cents=74999,
                min_term_months=24,
            ),
            AM,
        ),
        "ERR_MINIMUM_BELOW_LOAN_FLOOR",
        422,
    )
    validate_error(
        api_client.create_placement(
            f.create_placement_payload(
                first_room["id"],
                loaner["id"],
                first_version,
                terms_type="LOAN",
                minimum_purchase_cents=75000,
                min_term_months=24,
            ),
            AM,
        ),
        "ERR_ASSET_ROLE_MISMATCH",
        422,
    )
    assert read_asset(loaner["id"])["asset_status"] == "IN_STOCK"
    assert read_site(first_room["id"])["version"] == first_version, (
        "a refused installation never consumes the expected version"
    )

    rental = validate_success(
        api_client.create_placement(
            f.create_placement_payload(
                first_room["id"],
                first_asset["id"],
                first_version,
                terms_type="RENTAL",
                minimum_purchase_cents=74999,
                min_term_months=12,
            ),
            AM,
        ),
        201,
    )
    assert rental["terms_type"] == "RENTAL"
    assert rental["minimum_purchase_cents"] == 74999

    loan = place_asset_at_site(
        second_room,
        second_asset["id"],
        terms_type="LOAN",
        minimum_purchase_cents=75000,
        min_term_months=24,
    )
    assert loan["minimum_purchase_cents"] == 75000, "the floor comparison is inclusive"
    assert _total_count(
        api_client.list_placements(AM, params={"placement_status": "ACTIVE"})
    ) == 2


def test_each_endpoint_reports_the_posture_gate_that_owns_it():
    """With the programme cancelling, the break room suspended, the stop cancelled and
    one installation superseded, every endpoint answers with the first gate that
    actually governs it rather than with whichever state happens to be worst.

    "Sites, placements and service visits may only be created while `program_posture`
    is `ONBOARDING`, `ACTIVE`, or `AT_RISK`. A `CANCELLATION_PENDING` or `CLOSED`
    account rejects all three with `ERR_ACCOUNT_NOT_OPERATING` (HTTP 409)."

    "Four gates precede the arithmetic, in this order: the technician must own the
    visit's route (`ERR_ACTOR_NOT_ON_ROUTE`); the site's service posture must be
    `ACTIVE` or `ESCALATED`, so a suspended site refuses completion with
    `ERR_SITE_NOT_SERVICEABLE` even for a visit that is otherwise perfectly
    schedulable; the visit must be `SCHEDULED`, otherwise `ERR_VISIT_STATE_INVALID`;
    and the window must have opened, meaning the current instant is at or after
    `window_start` — an earlier attempt is rejected with `ERR_VISIT_NOT_YET_STARTED`
    (HTTP 422)."

    Design: Corner/validations/corner_posture_gates_are_evaluated_in_priority_order_across_three_entities
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    account_id = base["account"]["id"]
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    rental_terms = {
        "terms_type": "RENTAL",
        "minimum_purchase_cents": 60000,
        "min_term_months": 12,
    }
    first_asset = create_asset(base["model"]["id"], serial_number="URN30-0001")
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")
    superseded = place_asset_at_site(base["site"], first_asset["id"], **rental_terms)
    live = place_asset_at_site(base["site"], second_asset["id"], **rental_terms)
    stop = schedule_stop_with_lines(base, {"COFFEE": 20})

    set_clock("2026-08-10T08:00:00Z")
    cancel_account(account_id, retrieval_due_by="2026-09-30T00:00:00Z")
    assert read_account(account_id)["program_posture"] == "CANCELLATION_PENDING"
    assert read_site(site_id)["service_posture"] == "SUSPENDED"
    assert read_placement(superseded["id"])["placement_status"] == "SUPERSEDED"
    assert read_placement(live["id"])["placement_status"] == "RETRIEVAL_SCHEDULED"
    assert read_visit(stop["id"])["visit_status"] == "CANCELLED"

    validate_error(
        api_client.create_site(
            f.create_site_payload(account_id, route_id, site_name="HQ Floor 9"), AM
        ),
        "ERR_ACCOUNT_NOT_OPERATING",
        409,
    )
    scheduling = api_client.create_visit(
        f.create_visit_payload(
            site_id,
            window_start="2026-08-17T09:00:00Z",
            window_end="2026-08-17T09:45:00Z",
        ),
        AM,
    )
    error = validate_error(scheduling, "ERR_ACCOUNT_NOT_OPERATING", 409)
    assert error["error_id"] != "ERR_SITE_NOT_SERVICEABLE", (
        "the account gate is declared above the site gate"
    )

    completion = api_client.complete_visit(
        stop["id"],
        f.complete_visit_payload([f.delivered_line(coffee_id, 20)]),
        make_route_technician_headers(route_id),
    )
    error = validate_error(completion, "ERR_SITE_NOT_SERVICEABLE", 409)
    assert error["error_id"] != "ERR_VISIT_STATE_INVALID", (
        "completion is not one of the three creations the account gate guards"
    )

    validate_error(
        api_client.retrieve_placement(
            superseded["id"], f.retrieve_placement_payload("SERVICEABLE"), AM
        ),
        "ERR_PLACEMENT_STATE_INVALID",
        409,
    )
    validate_error(
        api_client.evaluate_placement_compliance(superseded["id"], {}, BS),
        "ERR_PLACEMENT_STATE_INVALID",
        409,
    )

    recovered = validate_success(
        api_client.retrieve_placement(
            live["id"], f.retrieve_placement_payload("SERVICEABLE"), AM
        ),
        200,
    )
    assert recovered["placement_status"] == "RETRIEVED"
    assert read_account(account_id)["program_posture"] == "CLOSED"
    assert read_site(site_id)["service_posture"] == "CLOSED"
    assert read_visit(stop["id"])["visit_status"] == "CANCELLED"
    assert read_placement(superseded["id"])["placement_status"] == "SUPERSEDED"


def test_transition_fields_are_required_only_for_their_own_target_state():
    """A parts estimate is required only for the awaiting-parts hop, a resolution note
    only for the resolution hop, and a dispute reason only for a dispute — each refused
    when omitted and accepted the moment it is supplied.

    "The two conditionally-required transition fields are checked **after** the descale
    gate and after the cycle cap. `parts_eta` is required when the requested status is
    `AWAITING_PARTS` and `resolution_note` is required when it is `RESOLVED`; omitting
    either where the requested transition needs it yields
    `ERR_MISSING_TRANSITION_FIELD` (HTTP 422)."

    "A `DISPUTE` disposition additionally requires a `dispute_reason`; omitting it
    yields `ERR_MISSING_TRANSITION_FIELD` (HTTP 422), checked after the state gates."

    Design: Corner/validations/corner_conditionally_required_transition_fields_are_enforced_per_target_state
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        min_term_months=12,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    account_id = base["account"]["id"]
    route_id = base["route"]["id"]
    technician = make_route_technician_headers(route_id)
    work_order = create_work_order(base["asset"]["id"], route_id, "REPAIR")
    advance_work_order(work_order["id"], route_id, "IN_PROGRESS")

    set_market_index(2400000, headers=BS)
    proposal = propose_adjustment(account_id, effective_at="2026-09-01T00:00:00Z")
    assert proposal["adj_status"] == "PROPOSED"

    validate_error(
        api_client.advance_work_order(
            work_order["id"], f.advance_work_order_payload("AWAITING_PARTS"), technician
        ),
        "ERR_MISSING_TRANSITION_FIELD",
        422,
    )
    held = read_work_order(work_order["id"])
    assert held["wo_status"] == "IN_PROGRESS"
    assert held["awaiting_parts_cycles"] == 0

    waiting = advance_work_order(
        work_order["id"],
        route_id,
        "AWAITING_PARTS",
        parts_eta="2026-08-06T00:00:00Z",
    )
    assert waiting["wo_status"] == "AWAITING_PARTS"
    assert waiting["parts_eta"] == "2026-08-06T00:00:00Z"
    assert waiting["awaiting_parts_cycles"] == 1

    resumed = advance_work_order(work_order["id"], route_id, "IN_PROGRESS")
    assert resumed["wo_status"] == "IN_PROGRESS", "this hop needs no extra field"

    validate_error(
        api_client.advance_work_order(
            work_order["id"], f.advance_work_order_payload("RESOLVED"), technician
        ),
        "ERR_MISSING_TRANSITION_FIELD",
        422,
    )
    assert read_work_order(work_order["id"])["wo_status"] == "IN_PROGRESS"

    resolved = advance_work_order(
        work_order["id"], route_id, "RESOLVED", resolution_note="Brew head reseated"
    )
    assert resolved["wo_status"] == "RESOLVED"
    assert resolved["resolution_note"] == "Brew head reseated"

    validate_error(
        api_client.respond_price_adjustment(
            proposal["id"],
            f.respond_payload("DISPUTE"),
            make_customer_contact_headers(account_id),
        ),
        "ERR_MISSING_TRANSITION_FIELD",
        422,
    )
    pending = read_adjustment(proposal["id"])
    assert pending["adj_status"] == "PROPOSED"
    assert pending["dispute_reason"] is None

    disputed = respond_adjustment(
        proposal["id"],
        account_id,
        "DISPUTE",
        dispute_reason="Our roast blend was not affected by the index move",
    )
    assert disputed["adj_status"] == "DISPUTED"
    assert disputed["dispute_reason"] == (
        "Our roast blend was not affected by the index move"
    )
