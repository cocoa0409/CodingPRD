"""Entity contracts: what a creation echoes, what the server stamps, what an
omitted optional field falls back to, and how a bad one is refused.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_account,
    assert_catalog_fields,
    assert_equipment_asset,
    assert_par_level,
    assert_product_item,
    assert_site,
)
from test_helpers.constants import (
    ANCHOR_MONDAY,
    DEFAULT_PRICE_PROTECTION_DAYS,
    DEFAULT_TRAVEL_BUFFER_MINUTES,
    EXPECTED_FORECAST_CUPS_PER_WEEK,
    EXPECTED_PAR_ROWS,
    EXPECTED_REQUIRED_PEAK_CUPS_PER_HOUR,
    PAGINATION,
)
from test_helpers.fixtures import (
    CATALOG_SPEC_COFFEE_ONLY,
    assemble_invoice_for,
    complete_stop,
    create_account,
    create_model,
    create_product,
    create_site,
    issue_invoice,
    lines_by_type,
    list_par_lines,
    list_placements,
    list_sites,
    par_line_for,
    plan_site,
    read_account,
    read_invoice,
    read_invoice_line,
    read_site,
    schedule_stop_with_lines,
    set_clock,
    setup_catalog,
    setup_planned_site,
)
from test_helpers.test_users import TEST_USERS

PA = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

# A syntactically well-formed identifier that names no row anywhere.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_account_creation_echoes_every_input_and_stamps_the_system_fields():
    """Registering a customer returns 201 with the four supplied fields echoed
    back, every computed field at its birth value, and identity plus revision
    counters minted by the server rather than the client.

    "The registration payload carries the customer's `legal_name` (non-empty, at
    most 200 characters), a `billing_mode` of either `CONSOLIDATED` or `PER_SITE`
    that decides whether one invoice may span several of the account's break
    rooms, and a `green_index_baseline_micros` value of at least 1 — the green
    coffee index in micro-dollars per pound, locked at contract signing, against
    which all future market movement is measured for this customer and this
    customer only."

    "The new account is born in `program_posture` `ONBOARDING` with
    `green_price_factor_bps` at `10000` (meaning green-linked prices are
    unmodified), `receivable_balance_cents` at 0, `escalated_site_count` at 0,
    `allied_attachment_bps` at 0, `price_protection_until` null, and `version` 1."

    "The three cancellation fields `cancel_reason`, `retrieval_due_by` and
    `cancelled_at` are all null until the program is cancelled."

    "Clients never supply an `id` on creation, and no endpoint accepts one in a
    request body."

    Design: Corner/entities/corner_account_creation_persists_every_input_field_and_stamps_system_fields
    """
    set_clock(ANCHOR_MONDAY)
    payload = f.create_account_payload(
        legal_name="Northgate Holdings LLC",
        billing_mode="CONSOLIDATED",
        green_index_baseline_micros=2000000,
        price_protection_days=60,
    )
    assert "id" not in payload

    created = validate_success(api_client.create_account(payload, AM), 201)
    assert_account(created)

    # Every supplied field comes back unaltered.
    assert created["legal_name"] == "Northgate Holdings LLC"
    assert created["billing_mode"] == "CONSOLIDATED"
    assert created["green_index_baseline_micros"] == 2000000
    assert created["price_protection_days"] == 60

    # Every computed field sits at its declared birth value.
    assert created["program_posture"] == "ONBOARDING"
    assert created["green_price_factor_bps"] == 10000
    assert created["receivable_balance_cents"] == 0
    assert created["escalated_site_count"] == 0
    assert created["allied_attachment_bps"] == 0
    assert created["price_protection_until"] is None
    assert created["cancel_reason"] is None
    assert created["retrieval_due_by"] is None
    assert created["cancelled_at"] is None
    assert created["version"] == 1

    # The read is the same row, not a second projection of it.
    fetched = read_account(created["id"])
    for field in (
        "id",
        "legal_name",
        "billing_mode",
        "green_index_baseline_micros",
        "price_protection_days",
        "program_posture",
        "green_price_factor_bps",
        "receivable_balance_cents",
        "escalated_site_count",
        "allied_attachment_bps",
        "price_protection_until",
        "cancel_reason",
        "retrieval_due_by",
        "cancelled_at",
        "created_at",
        "updated_at",
        "version",
    ):
        assert fetched[field] == created[field], field


def test_omitted_optional_fields_take_their_declared_defaults():
    """Three creations that each leave out one optional field are accepted, and
    each omitted field lands on the value the specification names for it.

    "An optional `price_protection_days` may be supplied; it defaults to 90 and
    must not be negative."

    "and an optional `green_coffee_linked` flag defaulting to false that decides
    whether the account's green-coffee factor applies to this product's price."

    "and an optional `travel_buffer_minutes` between 0 and 120 inclusive that
    defaults to 30."

    Design: Corner/entities/corner_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(ANCHOR_MONDAY)

    account_payload = f.create_account_payload(
        legal_name="Southgate Partners LLC",
        billing_mode="PER_SITE",
        green_index_baseline_micros=2000000,
    )
    assert "price_protection_days" not in account_payload
    account = validate_success(api_client.create_account(account_payload, AM), 201)
    assert_account(account)
    assert account["price_protection_days"] == DEFAULT_PRICE_PROTECTION_DAYS
    assert account["price_protection_days"] == 90

    product_payload = f.create_product_item_payload(
        sku="TEA-BLK-100",
        category="TEA",
        base_unit_price_micros=1500000,
        pack_units=100,
    )
    assert "green_coffee_linked" not in product_payload
    product = validate_success(api_client.create_product_item(product_payload, PA), 201)
    assert_product_item(product)
    assert product["green_coffee_linked"] is False

    route_payload = {"name": "TUE-NOBUF", "service_day": "TUE", "capacity_minutes": 300}
    assert "travel_buffer_minutes" not in route_payload
    route = validate_success(api_client.create_route(route_payload, PA), 201)
    assert isinstance(route["travel_buffer_minutes"], int)
    assert route["travel_buffer_minutes"] == DEFAULT_TRAVEL_BUFFER_MINUTES
    assert route["travel_buffer_minutes"] == 30
    assert route["booked_minutes_total"] == 0


def test_planning_a_break_room_computes_the_forecast_peak_and_its_par_row():
    """A forty-person break room supplies only headcount and occupancy; the
    server derives the weekly cup forecast, the required peak throughput, the
    recommended brewer and the product's par row from them.

    "The site starts in service posture `ACTIVE`, with `escalation_score` at 0.0,
    `forecast_cups_per_week` at 0, `required_peak_cups_per_hour` at 0,
    `consecutive_shortfall_visit_count` at 0, `recommended_model_id` null,
    `brew_style` null, and `version` 1."

    "Under the **`HEADCOUNT_MODEL`** variant, the weekly cup forecast is the
    site's headcount multiplied by 1.8 cups per person per day, multiplied by the
    number of occupied days per week, multiplied by the brew-style factor, with
    the product rounded up to a whole number of cups."

    "Each product's par quantity is then the weekly cup forecast multiplied by a
    two-week cover period, multiplied by that product's per-cup unit factor,
    rounded up to a whole number of sales units."

    "Each product's reorder point is its par quantity multiplied by 4000 basis
    points (forty percent of par), divided by 10000, rounded up to a whole number
    of units. The site's required peak throughput is the weekly cup forecast
    divided by the number of occupied days per week, multiplied by a peak factor
    of 0.35, rounded up to a whole number of cups per hour; intermediate products
    are exact decimals and are not rounded before the final ceiling."

    "If the line is newly created, it starts with `on_hand_units` 0, both
    `cumulative_delivered_units` and `cumulative_consumed_units` 0,
    `last_service_at` set to the current instant, and `stock_status` `STOCKOUT`."

    "The first candidate's identifier is written to the site's
    `recommended_model_id`."

    Design: Corner/entities/corner_site_planning_computes_forecast_peak_and_par_rows_from_headcount
    """
    base = setup_catalog(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    account = create_account()
    unplanned = create_site(
        account["id"],
        base["route"]["id"],
        site_name="HQ Floor 3",
        headcount=40,
        days_per_week=5,
        consumption_model="HEADCOUNT_MODEL",
    )
    assert_site(unplanned)
    assert unplanned["forecast_cups_per_week"] == 0
    assert unplanned["required_peak_cups_per_hour"] == 0
    assert unplanned["recommended_model_id"] is None
    assert unplanned["brew_style"] is None
    assert list_par_lines(unplanned["id"]) == []

    planned = plan_site(unplanned["id"], "DRIP")
    assert_site(planned)
    assert planned["forecast_cups_per_week"] == EXPECTED_FORECAST_CUPS_PER_WEEK == 360
    assert planned["required_peak_cups_per_hour"] == EXPECTED_REQUIRED_PEAK_CUPS_PER_HOUR == 26
    assert planned["recommended_model_id"] == base["model"]["id"]
    assert planned["brew_style"] == "DRIP"
    assert read_site(unplanned["id"])["forecast_cups_per_week"] == 360

    par = par_line_for(planned["id"], base["products"]["COFFEE"]["id"])
    assert_par_level(par)
    assert par["par_units"] == EXPECTED_PAR_ROWS["COFFEE"]["par_units"] == 65
    assert (
        par["reorder_point_units"] == EXPECTED_PAR_ROWS["COFFEE"]["reorder_point_units"] == 26
    )
    assert par["source"] == "FORECAST"
    assert par["on_hand_units"] == 0
    assert par["cumulative_delivered_units"] == 0
    assert par["cumulative_consumed_units"] == 0
    assert par["stock_status"] == "STOCKOUT"
    assert par["last_service_at"] == ANCHOR_MONDAY


def test_a_catalogued_brewer_model_carries_no_revision_counter_to_mutate():
    """The brewer model is written once and read back unchanged: it exposes
    neither an update timestamp nor a version, and repeated reads are identical.

    "Two resource types are deliberately immutable catalog records and carry
    **only** `id` and `created_at`: `EquipmentModel` and `ProductItem`. Neither
    exposes `updated_at` and neither exposes `version`, because neither has an
    update endpoint."

    "A brewer model cannot be edited once registered, and a catalog product cannot
    be repriced by editing it — repricing happens through the account-level
    green-coffee factor described in §3.9, never by mutating the product row."

    Design: Corner/entities/corner_equipment_model_is_immutable_with_no_update_endpoint
    """
    set_clock(ANCHOR_MONDAY)
    created = validate_success(
        api_client.create_equipment_model(f.create_equipment_model_payload(), PA), 201
    )
    assert_catalog_fields(created)
    assert created["model_code"] == "URN-30"
    assert created["list_value_cents"] == 120000
    assert "version" not in created
    assert "updated_at" not in created

    first_read = get_success_data(api_client.get_equipment_model(created["id"], PA), 200)
    assert first_read["model_code"] == "URN-30"
    assert first_read["list_value_cents"] == 120000
    assert "version" not in first_read
    assert "updated_at" not in first_read

    # No mutating route exists, so a second read is byte-identical to the first.
    second_read = get_success_data(api_client.get_equipment_model(created["id"], PA), 200)
    assert second_read == first_read

    matching, meta = validate_paginated(
        api_client.list_equipment_models(PA, {"brewer_class": "THERMAL"})
    )
    assert [row["id"] for row in matching] == [created["id"]]
    assert meta["total_count"] == 1

    other, other_meta = validate_paginated(
        api_client.list_equipment_models(PA, {"brewer_class": "ESPRESSO"})
    )
    assert other == []
    assert other_meta["total_count"] == 0


def test_the_catalog_listing_pages_and_filters_with_an_honest_total_count():
    """Three catalogued products are walked two at a time: the first page reports
    more to come, the second reports none, and a category filter narrows the
    total rather than merely the page.

    "`limit` controls page size: it defaults to 10 when omitted, its minimum
    accepted value is 1, and its maximum accepted value is 100. `offset` controls
    the starting position: it defaults to 0 and its minimum accepted value is 0,
    with no upper bound."

    "Unless a list endpoint's description in §4 says otherwise, results are ordered
    by `created_at` ascending — oldest first."

    "List responses set `response_type` to `"array"` and populate four pagination
    members inside `meta`: `limit` (the effective page size), `offset` (the
    effective starting position), `total_count` (the number of records matching
    the filters before pagination is applied), and `has_more` (true when records
    remain beyond the current page)."

    Design: Corner/entities/corner_product_item_listing_paginates_with_total_count_and_has_more
    """
    set_clock(ANCHOR_MONDAY)
    coffee = create_product(sku="COF-HSE-001", category="COFFEE", base_unit_price_micros=4500000)
    creamer = create_product(
        sku="CRM-LIQ-001", category="CREAMER", base_unit_price_micros=1250000
    )
    tea = create_product(sku="TEA-BLK-001", category="TEA", base_unit_price_micros=2000000)

    first_page, first_meta = validate_paginated(
        api_client.list_product_items(PA, {"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in first_page] == [coffee["id"], creamer["id"]]
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_product_items(PA, {"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in second_page] == [tea["id"]]
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api_client.list_product_items(PA, {"category": "CREAMER"})
    )
    assert [row["id"] for row in filtered] == [creamer["id"]]
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False

    everything, default_meta = validate_paginated(api_client.list_product_items(PA))
    assert [row["id"] for row in everything] == [coffee["id"], creamer["id"], tea["id"]]
    assert default_meta["limit"] == PAGINATION["DEFAULT_LIMIT"] == 10
    assert default_meta["offset"] == PAGINATION["DEFAULT_OFFSET"] == 0
    assert default_meta["total_count"] == 3
    assert default_meta["has_more"] is False


def test_an_unknown_par_line_identifier_answers_with_its_own_not_found_code():
    """Reading a par line that was never written is a 404 carrying the par-line
    specific code and a populated error envelope, not an empty success body.

    "Each identifier has its own dedicated error: `account_id` yields
    `ERR_ACCOUNT_NOT_FOUND`, `site_id` yields `ERR_SITE_NOT_FOUND`, `route_id`
    yields `ERR_ROUTE_NOT_FOUND`, `model_id` yields `ERR_MODEL_NOT_FOUND`,
    `asset_id` yields `ERR_ASSET_NOT_FOUND`, `placement_id` yields
    `ERR_PLACEMENT_NOT_FOUND`, `product_id` yields `ERR_PRODUCT_NOT_FOUND`,
    `par_level_id` yields `ERR_PAR_LEVEL_NOT_FOUND`, `visit_id` yields
    `ERR_VISIT_NOT_FOUND`, `work_order_id` yields `ERR_WORK_ORDER_NOT_FOUND`,
    `invoice_id` yields `ERR_INVOICE_NOT_FOUND`, and `adjustment_id` yields
    `ERR_ADJUSTMENT_NOT_FOUND`. All twelve are HTTP 404."

    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/corner_par_level_get_with_unknown_id_returns_not_found
    """
    set_clock(ANCHOR_MONDAY)
    response = api_client.get_par_level(MISSING_UUID, AM)
    error = validate_error(response, "ERR_PAR_LEVEL_NOT_FOUND", 404)
    assert isinstance(error["message"], str) and error["message"].strip() != ""

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"] != ""
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    rows, meta = validate_paginated(api_client.list_par_levels(AM))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_break_room_without_a_headcount_is_refused_and_nothing_is_written():
    """`headcount` has no declared default, so leaving it out is a request-shape
    failure that persists no half-built site; adding it back is accepted.

    "An `AccountManager` adds a break room by supplying the owning `account_id`,
    the `route_id` of the replenishment route that will service it, a `site_name`
    (non-empty, at most 200 characters), the on-site `headcount` (at least 1), the
    number of occupied `days_per_week` (between 1 and 7 inclusive), a
    `consumption_model` of either `HEADCOUNT_MODEL` or `TRAILING_USAGE`, and a
    `service_minutes_estimate` between 1 and 480 inclusive recording how many
    technician minutes a standard visit to this site consumes."

    "**Request shape** — `ERR_VALIDATION`. Every input field declared without a
    default must be present; declared types must match; enum-typed values must be
    members of their declared value set; integers must respect their declared
    ranges; ISO 8601 instants must parse; and `limit` and `offset` must respect
    the pagination bounds of §2.3."

    Design: Corner/entities/corner_site_creation_missing_required_headcount_returns_validation_error
    """
    base = setup_catalog(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    account = create_account()
    incomplete = {
        "account_id": account["id"],
        "route_id": base["route"]["id"],
        "site_name": "HQ Floor 3",
        "days_per_week": 5,
        "consumption_model": "HEADCOUNT_MODEL",
        "service_minutes_estimate": 45,
    }
    validate_error(api_client.create_site(incomplete, AM), "ERR_VALIDATION", 400)
    assert list_sites(account_id=account["id"]) == []

    complete = dict(incomplete, headcount=40)
    created = validate_success(api_client.create_site(complete, AM), 201)
    assert_site(created)
    assert created["headcount"] == 40
    assert created["site_name"] == "HQ Floor 3"
    assert len(list_sites(account_id=account["id"])) == 1


def test_an_undeclared_asset_role_is_refused_and_frees_the_serial_for_reuse():
    """`SPARE` is not a member of the role partition, so the registration is a
    shape failure that writes nothing — the same serial is still free for the
    declared role that follows it.

    "A `ProgramAdmin` registers each physical brewer in the fleet with the
    `model_id` of its catalog model, a `serial_number` that is non-empty and unique
    across the fleet (a repeat yields `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409), and
    an `asset_role` of either `PLACEMENT` or `LOANER`."

    "A newly registered asset starts with `asset_status` `IN_STOCK`,
    `reconditioning_until` null, and `last_descale_at` stamped with the current
    instant — which is why a test that needs a descale-overdue asset registers it
    at an earlier clock position and then advances the clock."

    "**Request shape** — `ERR_VALIDATION`. Every input field declared without a
    default must be present; declared types must match; enum-typed values must be
    members of their declared value set; integers must respect their declared
    ranges; ISO 8601 instants must parse; and `limit` and `offset` must respect
    the pagination bounds of §2.3."

    Design: Corner/entities/corner_equipment_asset_role_enum_rejects_an_undeclared_value
    """
    set_clock(ANCHOR_MONDAY)
    model = create_model()

    refused = api_client.create_equipment_asset(
        f.create_equipment_asset_payload(
            model["id"], serial_number="URN30-0001", asset_role="SPARE"
        ),
        PA,
    )
    validate_error(refused, "ERR_VALIDATION", 400)
    empty_fleet, empty_meta = validate_paginated(api_client.list_equipment_assets(PA))
    assert empty_fleet == []
    assert empty_meta["total_count"] == 0

    # The serial the refused request named was never consumed.
    accepted = validate_success(
        api_client.create_equipment_asset(
            f.create_equipment_asset_payload(
                model["id"], serial_number="URN30-0001", asset_role="LOANER"
            ),
            PA,
        ),
        201,
    )
    assert_equipment_asset(accepted)
    assert accepted["serial_number"] == "URN30-0001"
    assert accepted["asset_role"] == "LOANER"
    assert accepted["asset_status"] == "IN_STOCK"
    assert accepted["last_descale_at"] == ANCHOR_MONDAY
    assert accepted["reconditioning_until"] is None

    fleet, meta = validate_paginated(api_client.list_equipment_assets(PA))
    assert [row["id"] for row in fleet] == [accepted["id"]]
    assert meta["total_count"] == 1


def test_a_placement_naming_an_unknown_brewer_is_a_body_foreign_key_not_found():
    """The site resolves and the asset does not, so the installation answers with
    the asset's own not-found code — and the site's revision counter is not spent
    on the attempt.

    "Foreign keys carried in a request body are resolved after all path
    identifiers, and among themselves in the order the fields are declared on the
    owning resource. Placement creation therefore checks `site_id` before
    `asset_id`, and visit scheduling checks `site_id` before `route_id`. Each body
    foreign key raises the same error identifier its path counterpart would."

    "**Body foreign-key existence** (see §2.9) — the corresponding not-found
    error."

    "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on each mutation of that row; it is the value the
    stale-read protection of §2.7 compares against."

    Design: Corner/entities/corner_placement_body_fk_that_does_not_resolve_returns_asset_not_found
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    site = base["site"]
    site_version = site["version"]

    # The fleet is empty, so no asset identifier can resolve.
    fleet, fleet_meta = validate_paginated(api_client.list_equipment_assets(PA))
    assert fleet == []
    assert fleet_meta["total_count"] == 0

    refused = api_client.create_placement(
        f.create_placement_payload(
            site["id"],
            MISSING_UUID,
            site_version,
            terms_type="RENTAL",
            minimum_purchase_cents=60000,
            min_term_months=12,
        ),
        AM,
    )
    validate_error(refused, "ERR_ASSET_NOT_FOUND", 404)

    assert read_site(site["id"])["version"] == site_version
    assert list_placements(site_id=site["id"]) == []


def test_a_credit_line_is_discoverable_from_the_line_it_was_posted_against():
    """The credit line's self-referential foreign key is a working reverse index:
    filtering the line listing by the credited line's identifier finds exactly the
    one credit posted against it, and the money moves in step.

    "A `BillingSpecialist` posts a credit against exactly one line by supplying
    that line's `target_line_id`, a positive `amount_cents`, and a
    `credit_reason`."

    "A successful credit appends a new invoice line whose `line_type` is `CREDIT`,
    whose `amount_cents` is the **negation** of the requested amount, whose
    `target_line_id` points at the credited line, and whose `credit_reason` carries
    the supplied reason. The target line's `credits_applied_cents` increases by the
    requested amount. The invoice's `total_cents` is recomputed as the sum of all
    of its lines — with the negative `ALLIED_DISCOUNT` and `CREDIT` lines counted
    as negative — and its `line_count` increases by 1. The account's
    `receivable_balance_cents` decreases by the credited amount. The invoice then
    moves to `PARTIALLY_CREDITED` when the cumulative credits after this one are
    strictly less than the pre-credit total, and to `FULLY_CREDITED` when they
    exactly equal it, at which point the invoice's total is 0 and the invoice is
    terminal."

    "Everything below `PRODUCT`, `RENT`, `SHORTFALL`, `UNRETURNED_ASSET`,
    `ALLIED_DISCOUNT` and `FREIGHT` is synthesized rather than posted by a client,
    so the invoice-line listing — filterable by `invoice_id`, by `site_id`, by
    `target_line_id`, by `line_type` and by `product_id` — is the only discovery
    channel for them."

    Design: Corner/entities/corner_credit_line_is_reverse_reachable_from_the_line_it_credits
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    visit = schedule_stop_with_lines(base, {"COFFEE": 20})
    complete_stop(base, visit, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")

    set_clock("2026-09-01T00:00:00Z")
    draft = assemble_invoice_for(
        base["account"]["id"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"
    )
    invoice = issue_invoice(draft["id"])
    assert invoice["invoice_status"] == "ISSUED"
    assert invoice["total_cents"] == 11500
    assert invoice["line_count"] == 2
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 11500

    product_line = lines_by_type(invoice["id"])["PRODUCT"][0]
    assert product_line["amount_cents"] == 9000
    assert product_line["target_line_id"] is None
    assert product_line["credits_applied_cents"] == 0

    credit_line = validate_success(
        api_client.credit_invoice(
            invoice["id"],
            f.credit_invoice_payload(
                product_line["id"], 1000, credit_reason="Two bags short on the delivery"
            ),
            BS,
        ),
        201,
    )
    assert credit_line["line_type"] == "CREDIT"
    assert credit_line["amount_cents"] == -1000
    assert credit_line["target_line_id"] == product_line["id"]
    assert credit_line["credit_reason"] == "Two bags short on the delivery"

    # The reverse lookup on the self-referential key finds exactly that credit.
    reverse, reverse_meta = validate_paginated(
        api_client.list_invoice_lines(BS, {"target_line_id": product_line["id"]})
    )
    assert [row["id"] for row in reverse] == [credit_line["id"]]
    assert reverse_meta["total_count"] == 1

    credited = read_invoice_line(product_line["id"])
    assert credited["credits_applied_cents"] == 1000
    assert credited["target_line_id"] is None
    assert credited["amount_cents"] == 9000

    after = read_invoice(invoice["id"])
    assert after["invoice_status"] == "PARTIALLY_CREDITED"
    assert after["total_cents"] == 10500
    assert after["line_count"] == 3
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 10500
