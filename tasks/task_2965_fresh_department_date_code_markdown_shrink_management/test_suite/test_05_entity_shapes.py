"""Entity creation, retrieval, listing, defaults, computed fields and identity."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories
from test_helpers import fixtures as F
from test_helpers.constants import MEAT_TWO_RUNGS, MISSING_ID
from test_helpers.test_users import (
    admin_headers,
    clerk_headers,
    manager_headers,
)


def test_store_create_echoes_every_supplied_field_in_a_201_envelope(api):
    """A create answers 201 with the full row in data and version 1.

    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`." and "The `response_type` is either "object" for a
    single resource or "array" for a list of resources."

    PRD 3.1: "Three optional attributes round out the row. `dock_door_codes` is an
    array of between 1 and 8 receiving-dock identifiers [...] `donation_program_enabled`
    is a boolean that defaults to true [...] `status` is either `ACTIVE` or `SUSPENDED`,
    defaulting to `ACTIVE`."

    PRD 2.4: "`version`, an integer that begins at 1 when the resource is created".

    Design: Corner/entities/store_create_with_every_input_field_returns_201_envelope
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    response = api.create_store(
        factories.create_store_payload(
            dock_door_codes=["D1", "D2"], donation_program_enabled=True, status="ACTIVE"
        ),
        admin_headers(),
    )
    store = validate_success(response, expected_status=201)

    assert response.json()["response_type"] == "object"
    A.assert_fields(
        store,
        store_number="0412",
        name="Fresh Market 0412",
        region_code="MID-ATL",
        dock_door_codes=["D1", "D2"],
        donation_program_enabled=True,
        status="ACTIVE",
        version=1,
    )
    A.assert_common_fields(store, expected_version=1)
    A.assert_instant_equals(store["updated_at"], store["created_at"], "updated_at")


def test_store_read_returns_exactly_what_the_write_persisted(api):
    """GET by id re-derives nothing: same id, same created_at, still version 1.

    PRD 2.4: "Every resource is identified by an `id` that the server mints as a UUID."
    and "Every resource also carries a `created_at` timestamp recording the instant it
    came into existence, formatted as an ISO 8601 UTC instant with exactly three
    fractional-second digits".

    PRD 2.4: "`version`, an integer that begins at 1 when the resource is created and
    increases by exactly 1 on every successful mutation of that resource."  No mutation
    happened between the write and the read.

    Design: Corner/entities/store_retrieval_returns_the_stored_row_unchanged
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    written = F.build_store(api, dock_door_codes=["D1", "D2"])

    read = validate_success(api.get_store(written["id"], clerk_headers()))

    A.assert_fields(
        read,
        id=written["id"],
        store_number="0412",
        dock_door_codes=["D1", "D2"],
        version=1,
    )
    A.assert_instant_equals(read["created_at"], written["created_at"], "created_at")


def test_item_listing_filtered_by_department_pages_with_a_filtered_total_count(api):
    """total_count counts the filtered set, and the two pages partition it exactly.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, must be at
    least 1, and must be at most 100. `offset` controls the starting position: it
    defaults to 0 when omitted".

    PRD 2.3: "The `meta` block of a list response carries `limit` and `offset` echoing
    the effective values in force for the page, `total_count` giving the number of rows
    matching the filters before pagination is applied, and `has_more` set true when rows
    remain beyond the current page."

    PRD 2.3: "List results are ordered by `created_at` ascending, oldest first, and
    that ordering is stable across pages".

    Design: Corner/entities/items_list_filtered_by_department_paginates_with_total_count
    """
    chain = F.build_meat_chain(api, with_lot=False)
    item_b = F.build_item(
        api,
        chain.department["id"],
        upc="000111222334",
        description="Ground Chuck 1lb",
        base_retail_cents=499,
        unit_cost_cents=350,
        daily_forecast_units=6.00,
    )
    item_c = F.build_item(
        api,
        chain.department["id"],
        upc="000111222335",
        description="Pork Loin 2lb",
        base_retail_cents=899,
        unit_cost_cents=600,
        daily_forecast_units=2.00,
    )
    department_id = chain.department["id"]

    first, first_meta = validate_paginated(
        api.list_items(
            clerk_headers(), params={"department_id": department_id, "limit": 2, "offset": 0}
        )
    )
    second, second_meta = validate_paginated(
        api.list_items(
            clerk_headers(), params={"department_id": department_id, "limit": 2, "offset": 2}
        )
    )
    unpaged, unpaged_meta = validate_paginated(
        api.list_items(clerk_headers(), params={"department_id": department_id})
    )

    assert len(first) == 2
    A.assert_fields(first_meta, total_count=3, limit=2, offset=0, has_more=True)
    assert len(second) == 1
    A.assert_fields(second_meta, total_count=3, limit=2, offset=2, has_more=False)
    A.assert_fields(unpaged_meta, limit=10, offset=0, total_count=3, has_more=False)
    assert len(unpaged) == 3

    paged_ids = [row["id"] for row in first] + [row["id"] for row in second]
    assert len(set(paged_ids)) == 3, f"pages must not repeat a row: {paged_ids}"
    assert set(paged_ids) == {chain.item["id"], item_b["id"], item_c["id"]}


def test_reading_an_unknown_lot_answers_the_lot_specific_not_found_code(api):
    """A well-formed but unknown lot id resolves to ERR_LOT_NOT_FOUND, not a generic 404.

    PRD 2.5: "Where a path does carry identifiers, they are validated strictly left to
    right, and the first identifier that does not resolve decides the response with its
    own dedicated 404 code: `ERR_STORE_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_LADDER_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`".

    PRD 2.11: "Path-identifier existence, validated left to right -- the matching 404
    code from 2.5."

    Design: Corner/entities/lot_get_with_unknown_id_returns_lot_not_found
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    response = api.get_lot(MISSING_ID, clerk_headers())

    body = response.json()
    assert body["response_type"] == "error"
    validate_error(response, "ERR_LOT_NOT_FOUND", expected_status=404)
    assert body["data"]["message"].strip()


def test_creating_an_item_without_unit_cost_cents_fails_the_shape_gate(api):
    """A required field with no default is a priority-3 refusal, and nothing is written.

    PRD 3.1: "Pricing rests on two integers: `base_retail_cents`, the undiscounted
    shelf price, which must be greater than 0, and `unit_cost_cents`, the landed unit
    cost, which must be greater than 0 **and strictly less than** `base_retail_cents`".

    PRD 2.11: "Request shape on every endpoint that takes input: required fields
    present, JSON types correct, enum members drawn from the declared sets, integers
    inside their documented ranges [...] -- `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/item_create_missing_unit_cost_cents_is_invalid_request
    """
    chain = F.build_meat_chain(api, with_lot=False, item_overrides=None)
    department_id = chain.department["id"]

    response = api.create_item(
        {
            "department_id": department_id,
            "upc": "000111222336",
            "description": "Ribeye Steak 16oz",
            "base_retail_cents": 599,
            "daily_forecast_units": 4.00,
        },
        manager_headers(),
    )

    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    rows, meta = validate_paginated(
        api.list_items(clerk_headers(), params={"department_id": department_id, "limit": 100})
    )
    assert meta["total_count"] == 1, "the refused item must not have been persisted"
    A.assert_ids_equal(rows, [chain.item["id"]])


def test_omitted_optional_attributes_take_their_declared_department_and_item_defaults(api):
    """Nine documented defaults are supplied by the server, not by the caller.

    PRD 3.1: "Three optional policy knobs carry defaults: `past_date_tolerance_hours`,
    an integer from 0 to 72 defaulting to 4 [...] `shrink_budget_pct`, greater than 0 and
    at most 100 with two decimal places and defaulting to 2.50 [...] and
    `markdown_policy_profile`, one of `STANDARD`, `AGGRESSIVE` or `CONSERVATIVE` and
    defaulting to `STANDARD`".

    PRD 3.1: "Five server-maintained values complete the department, all starting at
    their neutral value: `compliance_status` at `COMPLIANT`, `markdown_liability_cents`
    at 0, `shrink_cost_ratio_pct` at 0, `sweep_epoch` at 0, and `open_finding_count`
    at 0."

    PRD 3.1: "`shelf_life_days`, either null or an integer from 1 to 60 and defaulting
    to null [...] `donation_eligible`, defaulting to true [...] and `sampling_allowed`,
    defaulting to false" and "`status` is `ACTIVE` or `DISCONTINUED`, defaulting to
    `ACTIVE`".

    Design: Corner/entities/department_and_item_defaults_applied_when_optional_fields_omitted
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    store = F.build_store(api)
    ladder = F.build_ladder(api, rungs=MEAT_TWO_RUNGS)

    department = validate_success(
        api.create_department(
            factories.create_department_payload(store["id"], ladder["id"]),
            admin_headers(),
        ),
        expected_status=201,
    )
    item = validate_success(
        api.create_item(factories.create_item_payload(department["id"]), manager_headers()),
        expected_status=201,
    )

    A.assert_fields(
        department,
        past_date_tolerance_hours=4,
        markdown_policy_profile="STANDARD",
        compliance_status="COMPLIANT",
        sweep_epoch=0,
        open_finding_count=0,
    )
    A.assert_percent(department["shrink_budget_pct"], 2.50, "shrink_budget_pct")
    A.assert_percent(department["shrink_cost_ratio_pct"], 0, "shrink_cost_ratio_pct")
    A.assert_money_cents(
        department["markdown_liability_cents"], 0, "markdown_liability_cents"
    )

    A.assert_fields(item, donation_eligible=True, sampling_allowed=False, status="ACTIVE")
    A.assert_absent_or_none(item, "shelf_life_days")


def test_lot_receipt_derives_sell_by_and_opening_price_from_item_and_department(api):
    """Sell-by comes from the department default, and every counter opens neutral.

    PRD 3.2: "The effective shelf life is the item's own `shelf_life_days` when that
    value is present, and the owning department's `shelf_life_days_default` when the
    item's value is null. The sell-by instant is then midnight UTC at the start of the
    `production_date`, advanced by that many days, each day counted as 86,400 seconds".

    PRD 3.2: "An optional `production_batch_code` -- either null or 1 to 24 characters,
    null by default -- records the plant batch code printed on the case label."

    PRD 2.9: "For every lot, at every instant, `quantity_original` equals
    `quantity_on_hand` plus `units_sold` plus `units_shrunk` plus `units_donated` --
    exactly, in integers, with no tolerance."

    The item leaves `shelf_life_days` null so the MEAT department's default of 10 days
    applies: a lot packed 2026-08-05 sells by 2026-08-15T00:00:00.000Z.  At the parked
    clock that is 4 whole days remaining, so 4.00 forecast units times the STANDARD
    multiplier 1.00 times 4 days is 16 projected units over 24 on hand, which is 66.67
    percent once rounded half up.

    Design: Corner/entities/lot_computed_fields_derive_sell_by_and_opening_price_from_item_and_department
    """
    chain = F.build_meat_chain(
        api, with_lot=False, item_overrides={"daily_forecast_units": 4.00}
    )
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    lot = F.build_lot(
        api,
        chain.item["id"],
        production_date="2026-08-05",
        quantity_original=24,
        production_batch_code="B-0805-A",
    )

    A.assert_instant_equals(lot["sell_by_at"], "2026-08-15T00:00:00.000Z", "sell_by_at")
    A.assert_fields(
        lot,
        item_id=chain.item["id"],
        production_batch_code="B-0805-A",
        quantity_original=24,
        quantity_on_hand=24,
        units_sold=0,
        units_shrunk=0,
        units_donated=0,
        past_date_flag=False,
    )
    A.assert_lot_units_conservation(lot)
    A.assert_fresh_unpriced_lot(lot, 599)
    A.assert_percent(lot["expected_sell_through_pct"], 66.67, "expected_sell_through_pct")
    A.assert_common_fields(lot, expected_version=1)


def test_a_new_ladder_is_born_draft_with_server_owned_caps_and_no_activation_stamp(api):
    """The caller supplies name, code and rungs; the server owns status and the caps.

    PRD 3.1: "Two policy caps complete the ladder: `sell_through_floor_pct`, defaulting
    to 60 [...] `max_total_discount_pct`, defaulting to 75, caps the cumulative discount
    any markdown may produce on a lot".

    PRD 3.1: "A ladder is born in `DRAFT` with `activated_at` null, and it cannot price
    anything in that state."

    PRD 2.4: "`version`, an integer that begins at 1 when the resource is created".

    Design: Corner/entities/ladder_system_fields_are_server_owned_at_creation
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    response = api.create_markdown_ladder(
        factories.create_markdown_ladder_payload(
            name="MEAT-STD-2026", department_code="MEAT", rungs=MEAT_TWO_RUNGS
        ),
        admin_headers(),
    )
    ladder = validate_success(response, expected_status=201)

    A.assert_fields(
        ladder,
        name="MEAT-STD-2026",
        department_code="MEAT",
        status="DRAFT",
        sell_through_floor_pct=60,
        max_total_discount_pct=75,
        version=1,
    )
    A.assert_absent_or_none(ladder, "activated_at")
    assert len(ladder["rungs"]) == 2
    A.assert_common_fields(ladder, expected_version=1)
    A.assert_instant_equals(ladder["updated_at"], ladder["created_at"], "updated_at")


def test_an_off_enum_department_code_and_an_over_max_limit_both_fail_the_shape_gate(api):
    """Enum membership and the limit ceiling are both priority-3 refusals.

    PRD 3.1: "A ladder has a `name` of 1 to 60 characters that must be globally unique
    [...] and a `department_code` drawn from the same six-member set".

    PRD 3.1 names that set: "`MEAT`, `DELI`, `BAKERY`, `PRODUCE`, `SEAFOOD` and
    `DAIRY`".

    PRD 2.11: "Request shape on every endpoint that takes input: required fields
    present, JSON types correct, enum members drawn from the declared sets, integers
    inside their documented ranges [...] `limit` between 1 and 100 and `offset` at least
    0 -- `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/ladder_department_code_outside_enum_and_limit_above_max_are_rejected
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    off_enum = api.create_markdown_ladder(
        factories.create_markdown_ladder_payload(
            name="FLORAL-STD-2026", department_code="FLORAL", rungs=MEAT_TWO_RUNGS
        ),
        admin_headers(),
    )
    validate_error(off_enum, "ERR_INVALID_REQUEST", expected_status=400)

    over_max = api.list_markdown_ladders(admin_headers(), params={"limit": 101})
    validate_error(over_max, "ERR_INVALID_REQUEST", expected_status=400)

    at_max = api.list_markdown_ladders(admin_headers(), params={"limit": 100})
    rows, meta = validate_paginated(at_max)
    A.assert_fields(meta, limit=100, total_count=0, has_more=False)
    assert rows == [], f"the refused ladder must not have been persisted: {rows}"


def test_a_scan_price_check_is_written_once_with_no_version_or_updated_at_surface(api):
    """A matching scan snapshots the applied barcode and exposes no mutation surface.

    PRD 3.4: "The check captures `expected_price_cents` as the lot's
    `current_price_cents` at check time, and `variance_cents` as the scanned price minus
    the expected price, retaining the sign. It also snapshots `label_barcode_snapshot`,
    the `barcode` of the lot's `APPLIED` label if one exists, and null otherwise.
    `outcome` classifies the sign: `MATCH` when the variance is exactly zero".

    PRD 3.4: "When the outcome is `MATCH`, the action is `NONE`."

    PRD 3.4: "A scan-price check is append-only: it is written once, carries no
    `updated_at` and no `version`, and there is no endpoint that can revise or delete
    one."

    Design: Corner/entities/scan_price_check_is_append_only_with_no_version_or_update_surface
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label = F.cut_and_apply_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers()
    )
    assert label["status"] == "APPLIED"
    assert label["to_price_cents"] == 509

    written = validate_success(
        api.create_scan_price_check(
            chain.lot["id"],
            factories.create_scan_price_check_payload(509, register_lane_code="L07"),
            clerk_headers(),
        ),
        expected_status=201,
    )

    A.assert_append_only_shape(written)
    A.assert_fields(
        written,
        lot_id=chain.lot["id"],
        register_lane_code="L07",
        scanned_price_cents=509,
        expected_price_cents=509,
        variance_cents=0,
        outcome="MATCH",
        enforcement_action="NONE",
        label_barcode_snapshot=A.expected_barcode("000111222333", 509),
    )

    fetched = validate_success(api.get_scan_price_check(written["id"], clerk_headers()))
    assert set(fetched) == set(written), (
        f"read-back field set differs: {sorted(set(fetched) ^ set(written))}"
    )
    assert fetched == written
    assert F.reload_lot(api, chain.lot["id"])["status"] == "MARKED_DOWN"


def test_a_store_id_in_the_item_id_slot_resolves_to_the_item_not_found_code(api):
    """A body foreign key is checked against its own collection, not against any row.

    PRD 2.11: "Body foreign-key existence for `store_id`, `partner_id`,
    `markdown_ladder_id`, `department_id`, `item_id` and `lot_id` on department creation,
    item creation, lot creation, pickup creation, manifest-line creation, shrink
    recording, audit opening and recommendation creation -- the matching 404 code."

    PRD 2.5 names that code: "`ERR_ITEM_NOT_FOUND`".

    PRD 3.2: "The payload names the `item_id`, the `production_date` as a plain
    `YYYY-MM-DD` calendar date, and `quantity_original`, the number of units received,
    which must be greater than 0."

    Design: Corner/entities/lot_create_with_a_store_id_in_the_item_id_slot_returns_item_not_found
    """
    chain = F.build_meat_chain(api, with_lot=False)

    wrong_collection = api.create_lot(
        factories.create_lot_payload(
            chain.store["id"], production_date="2026-08-05", quantity_original=24
        ),
        clerk_headers(),
    )
    validate_error(wrong_collection, "ERR_ITEM_NOT_FOUND", expected_status=404)

    accepted = validate_success(
        api.create_lot(
            factories.create_lot_payload(
                chain.item["id"], production_date="2026-08-05", quantity_original=24
            ),
            clerk_headers(),
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_lots(clerk_headers(), params={"item_id": chain.item["id"]})
    )
    assert meta["total_count"] == 1
    A.assert_ids_equal(rows, [accepted["id"]])
