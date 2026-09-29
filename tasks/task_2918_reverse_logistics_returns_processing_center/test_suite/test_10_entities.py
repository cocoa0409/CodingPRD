"""Entity-level claims: declared inputs, defaults, system fields and parents."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LINE_RMA_MISMATCH,
)
from test_helpers.assertions import (
    assert_append_only_resource,
    assert_instant_equals,
    assert_line_states,
    assert_money,
    assert_page_meta,
    assert_pct_equals,
    assert_unit_buckets,
    assert_versioned_resource,
)
from test_helpers.constants import (
    BAY_STATUS_ACTIVE,
    BAY_TYPE_GENERAL,
    BAY_BUFFER_MINUTES_CEILING,
    CLIENT_STATUS_ACTIVE,
    CLOCK_STARTUP_INSTANT,
    DEFAULT_DESTROY_REQUIRES_DUAL_SIGNOFF,
    DEFAULT_DONATION_ALLOWED,
    DEFAULT_FRAUD_TOLERANCE_CENTS,
    DEFAULT_LIQUIDATION_FLOOR_PCT,
    DEFAULT_MAX_REFUND_EXPOSURE_CENTS,
    DEFAULT_REFUND_HOLD_HOURS,
    DEFAULT_RESTOCK_GRADE_FLOOR,
    DISPOSITION_PENDING,
    DS_RECEIVED_UNGRADED,
    ENTRY_RECEIPT_VARIANCE,
    FS_HOLD_PENDING_DISPOSITION,
    GRADE_C,
    GRADE_UNGRADED,
    HAZARD_NONE,
    OWNERSHIP_CENTER_OWNED,
    RECALL_NONE,
    REASON_DEFECTIVE,
    RMA_VOID,
    SL_PRIORITY,
    STANDARD_DAYS_SINCE_ORDER,
    UNDECLARED_SERVICE_LEVEL,
    USER_CLERK,
)
from test_helpers.test_users import ADMIN, CLERK


def test_client_registration_echoes_its_rule_set_and_zeroes_every_aggregate(api):
    """PRD §3.1: "At registration a client's `status` is `ACTIVE` and every
    derived figure is zero: `units_received`, `units_in_process`,
    `units_reserved_for_disposition`, `units_dispositioned`,
    `shrink_ledger_cents`, `settlement_balance_cents`,
    `projected_settlement_balance_cents` and `open_rma_count`."

    Design: Corner/entities/corner_client_create_returns_declared_fields_and_zeroed_aggregates
    """
    response = api.create_client(
        f.client_payload(
            name="Corner Retail",
            client_code="CRN1",
            service_level=SL_PRIORITY,
            inventory_ownership=OWNERSHIP_CENTER_OWNED,
            restock_grade_floor=GRADE_C,
            refund_hold_hours=24,
            liquidation_floor_pct=0.25,
            fraud_tolerance_cents=4000,
            donation_allowed=True,
            destroy_requires_dual_signoff=True,
            max_refund_exposure_cents=250000,
        ),
        ADMIN,
    )
    client = validate_success(response, 201)

    assert client["client_code"] == "CRN1"
    assert client["service_level"] == SL_PRIORITY
    assert client["inventory_ownership"] == OWNERSHIP_CENTER_OWNED
    assert client["restock_grade_floor"] == GRADE_C
    assert client["refund_hold_hours"] == 24
    assert_pct_equals(client["liquidation_floor_pct"], 0.25, "liquidation_floor_pct")
    assert_money(client["fraud_tolerance_cents"], 4000, "fraud_tolerance_cents")
    assert client["donation_allowed"] is True
    assert client["destroy_requires_dual_signoff"] is True
    assert_money(
        client["max_refund_exposure_cents"], 250000, "max_refund_exposure_cents"
    )

    assert client["status"] == CLIENT_STATUS_ACTIVE
    assert client["version"] == 1
    assert_unit_buckets(client, received=0, in_process=0, reserved=0, dispositioned=0)
    assert client["open_rma_count"] == 0
    assert_money(client["shrink_ledger_cents"], 0, "shrink_ledger_cents")
    assert_money(client["settlement_balance_cents"], 0, "settlement_balance_cents")
    assert_money(
        client["projected_settlement_balance_cents"], 0, "projected balance"
    )

    assert_versioned_resource(client, "client")
    assert_instant_equals(client["created_at"], CLOCK_STARTUP_INSTANT, "created_at")


def test_reading_a_client_back_returns_exactly_what_was_persisted(api):
    """PRD §2.4: "Every resource carries a server-minted `id` that is a UUID
    string with no type prefix and no client-supplied component, plus a
    `created_at` timestamp formatted as an ISO 8601 UTC instant with exactly
    three fractional digits (for example `2026-08-01T00:00:00.000Z`)."

    Design: Corner/entities/corner_client_get_returns_stored_entity
    """
    created = fx.make_client(api, name="Read Back Retail", client_code="CRN2")
    read_back = validate_success(api.get_client(created["id"], ADMIN), 200)

    assert read_back["id"] == created["id"]
    assert read_back["client_code"] == "CRN2"
    assert read_back["status"] == CLIENT_STATUS_ACTIVE
    assert read_back["version"] == 1, "a read never advances the version"
    assert_versioned_resource(read_back, "client")
    assert_money(read_back["settlement_balance_cents"], 0, "settlement_balance_cents")
    assert_money(
        read_back["projected_settlement_balance_cents"], 0, "projected balance"
    )


def test_client_listing_pages_report_total_count_and_whether_more_remain(api):
    """PRD §2.3: "List responses set `response_type` to "array", carry the page
    of rows in `data`, and populate all four pagination fields in `meta`:
    `limit` and `offset` echo the effective values used, `total_count` reports
    how many rows matched the filter before the page was cut, and `has_more` is
    true when rows remain beyond the current page."

    Design: Corner/entities/corner_clients_list_pagination_total_count_and_has_more
    """
    codes = ["CRN3A", "CRN3B", "CRN3C"]
    for index, code in enumerate(codes):
        fx.make_client(api, name=f"Page {index}", client_code=code)

    first_rows, first_meta = validate_paginated(
        api.list_clients(ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert_page_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_rows, second_meta = validate_paginated(
        api.list_clients(ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert_page_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    seen = sorted(row["client_code"] for row in first_rows + second_rows)
    assert seen == codes, "the two pages together hold each client exactly once"


def test_omitting_every_optional_client_rule_applies_the_declared_defaults(api):
    """PRD §3.1: "`donation_allowed` defaults to false, so donation is opt-in
    per client."

    Design: Corner/entities/corner_client_defaults_applied_when_optional_rules_omitted
    """
    client = validate_success(
        api.create_client(
            f.client_payload(name="Bare Minimum Retail", client_code="CRN4"),
            ADMIN,
        ),
        201,
    )
    assert client["restock_grade_floor"] == DEFAULT_RESTOCK_GRADE_FLOOR
    assert client["refund_hold_hours"] == DEFAULT_REFUND_HOLD_HOURS
    assert_pct_equals(
        client["liquidation_floor_pct"],
        DEFAULT_LIQUIDATION_FLOOR_PCT,
        "liquidation_floor_pct",
    )
    assert_money(
        client["fraud_tolerance_cents"],
        DEFAULT_FRAUD_TOLERANCE_CENTS,
        "fraud_tolerance_cents",
    )
    assert client["donation_allowed"] is DEFAULT_DONATION_ALLOWED
    assert (
        client["destroy_requires_dual_signoff"]
        is DEFAULT_DESTROY_REQUIRES_DUAL_SIGNOFF
    )
    assert_money(
        client["max_refund_exposure_cents"],
        DEFAULT_MAX_REFUND_EXPOSURE_CENTS,
        "max_refund_exposure_cents",
    )


def test_a_catalogue_item_defaults_to_unhazardous_unregulated_and_unrecalled(api):
    """PRD §3.1: "`recall_status` is never supplied at registration — it starts
    at `NONE` and moves only when a recall notice is filed, taking one of
    `NONE`, `ADVISORY` or `MANDATORY`."

    Design: Corner/entities/corner_catalog_item_defaults_hazard_none_regulated_false_recall_none
    """
    client = fx.make_client(api, name="Catalog Defaults Retail", client_code="CRN5")
    item = validate_success(
        api.create_catalog_item(
            f.catalog_item_payload(
                client["id"],
                sku="PLAIN-1",
                description="Ordinary SKU",
                declared_value_cents=20000,
                unit_weight_grams=1200,
                secondary_market_floor_cents=1000,
            ),
            ADMIN,
        ),
        201,
    )
    assert item["hazard_class"] == HAZARD_NONE
    assert item["regulated_flag"] is False
    assert item["recall_status"] == RECALL_NONE
    assert_money(item["declared_value_cents"], 20000, "declared_value_cents")
    assert item["unit_weight_grams"] == 1200


def test_a_client_without_a_service_level_is_refused_and_persists_nothing(api):
    """PRD §2.6: "Priority 4 applies to every write endpoint and checks request
    shape: the body parses, every non-optional input field for that endpoint is
    present, enum-typed fields carry a declared member, integer-typed fields are
    integers, `quantity` and `authorized_quantity` are at least 1, percentage
    fields fall inside their declared range, and ISO-8601 instant fields parse
    as UTC instants."

    Design: Corner/entities/corner_client_create_missing_required_service_level_invalid_request
    """
    response = api.create_client(
        {"name": "No Service Level", "client_code": "CRN6",
         "inventory_ownership": OWNERSHIP_CENTER_OWNED},
        ADMIN,
    )
    validate_error(response, ERR_INVALID_REQUEST, 422)

    rows, meta = validate_paginated(api.list_clients(ADMIN, {"limit": 100}))
    assert rows == []
    assert meta["total_count"] == 0, "the rejected request created nothing"


def test_a_service_level_outside_the_declared_enum_is_refused(api):
    """PRD §3.1: "Two contractual attributes shape almost everything downstream:
    `service_level`, one of `SL_STANDARD`, `SL_PRIORITY` or `SL_WHITE_GLOVE`,
    and `inventory_ownership`, either `CLIENT_OWNED` or `CENTER_OWNED`."

    Design: Corner/entities/corner_client_create_undeclared_enum_member_invalid_request
    """
    response = api.create_client(
        f.client_payload(
            name="Bad Enum Retail",
            client_code="CRN7",
            service_level=UNDECLARED_SERVICE_LEVEL,
        ),
        ADMIN,
    )
    validate_error(response, ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(api.list_clients(ADMIN, {"limit": 100}))
    assert meta["total_count"] == 0


def test_a_bay_buffer_of_two_hundred_forty_one_minutes_is_refused(api):
    """PRD §3.1: "A bay's `buffer_minutes` is the mandatory decontamination gap
    the center keeps between two refurbishment tests in the same bay; it
    defaults to 0 and may not exceed 240 minutes, a four-hour ceiling."

    Design: Corner/entities/corner_processing_bay_buffer_minutes_above_ceiling_invalid_request
    """
    on_the_ceiling = validate_success(
        api.create_processing_bay(
            f.processing_bay_payload(
                bay_code="GB240",
                bay_type=BAY_TYPE_GENERAL,
                buffer_minutes=BAY_BUFFER_MINUTES_CEILING,
            ),
            ADMIN,
        ),
        201,
    )
    assert on_the_ceiling["buffer_minutes"] == BAY_BUFFER_MINUTES_CEILING, (
        "the 240-minute ceiling is inclusive"
    )

    response = api.create_processing_bay(
        f.processing_bay_payload(
            bay_code="GB241",
            bay_type=BAY_TYPE_GENERAL,
            buffer_minutes=BAY_BUFFER_MINUTES_CEILING + 1,
        ),
        ADMIN,
    )
    validate_error(response, ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(api.list_processing_bays(ADMIN, {"limit": 100}))
    assert meta["total_count"] == 1, "only the on-the-ceiling bay was created"


def test_a_bay_without_a_buffer_opens_at_zero_minutes_and_active(api):
    """PRD §3.1: "A `ProcessingBay` is a physical station with a `bay_code`, a
    `bay_type` of `GENERAL`, `HAZMAT` or `QUARANTINE`, and a `status` of `ACTIVE`
    or `OUT_OF_SERVICE`."

    Design: Corner/entities/corner_processing_bay_buffer_minutes_default_zero
    """
    bay = validate_success(
        api.create_processing_bay(
            f.processing_bay_payload(bay_code="GB0", bay_type=BAY_TYPE_GENERAL),
            ADMIN,
        ),
        201,
    )
    assert bay["buffer_minutes"] == 0
    assert bay["status"] == BAY_STATUS_ACTIVE
    assert bay["bay_type"] == BAY_TYPE_GENERAL
    assert bay["version"] == 1
    assert_versioned_resource(bay, "processing bay")


def test_days_since_order_is_computed_from_the_authorizations_own_dates(api):
    """PRD §3.3: "The system stamps `days_since_order` once, and only once, as
    the number of whole days between the authorization's `order_placed_at` and
    the receipt's `received_at` — the elapsed interval divided by 86400 seconds
    and truncated downward to an integer."

    Design: Corner/entities/corner_return_line_days_since_order_computed_from_logical_clock
    """
    world = fx.received_scenario(
        api,
        client_kwargs={
            "name": "Elapsed Days Retail",
            "client_code": "CRN8",
        },
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-2001",
    )
    line = world["line"]

    # The order was placed seven whole days before the startup clock.
    assert line["days_since_order"] == STANDARD_DAYS_SINCE_ORDER
    assert_line_states(
        line,
        disposition_state=DS_RECEIVED_UNGRADED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
        condition_grade=GRADE_UNGRADED,
        disposition=DISPOSITION_PENDING,
    )
    assert_money(line["recovery_value_cents"], 0, "recovery before grading")
    assert line["fraud_score_receipt"] == 0, (
        "the carton weighed exactly what was expected and the SKU is not serialized"
    )


def test_a_receipt_stamps_its_own_instant_and_scanning_clerk(api):
    """PRD §3.3: "The system stamps `received_at` from the logical clock and
    `scanned_by_user_id` from the caller's `X-User-ID`."

    Design: Corner/entities/corner_receipt_system_fields_generated_by_server
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "System Fields Retail", "client_code": "CRN9"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        scan=False,
    )
    receipt = validate_success(
        api.create_receipt(
            f.receipt_payload(
                world["rma"]["id"],
                tracking_reference="TRK-2002",
                gross_weight_grams=world["expected_weight_grams"],
            ),
            CLERK,
        ),
        201,
    )
    assert_instant_equals(
        receipt["received_at"], CLOCK_STARTUP_INSTANT, "received_at"
    )
    assert receipt["scanned_by_user_id"] == USER_CLERK, (
        "the dock records the operator who presented the header"
    )
    assert receipt["expected_weight_grams"] == 1400
    assert receipt["empty_box_suspected"] is False
    assert receipt["version"] == 1
    assert_versioned_resource(receipt, "receipt")


def test_a_ledger_entry_carries_no_version_and_cannot_be_edited(api):
    """PRD §2.4: "Four resource types are append-only records of something that
    already happened, and they deliberately carry neither `updated_at` nor
    `version` — only `id` and `created_at`."

    Design: Corner/entities/corner_shrink_ledger_entry_is_immutable_and_has_no_version
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Immutable Ledger Retail", "client_code": "CRN10"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        scan=False,
    )
    voided = get_success_data(
        api.void_rma(
            world["rma"]["id"], ADMIN, {"void_reason": "Customer never shipped"}
        )
    )
    assert voided["status"] == RMA_VOID

    rows, meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"client_id": world["client"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1
    entry = rows[0]
    assert entry["entry_type"] == ENTRY_RECEIPT_VARIANCE
    # One authorized unit, none received, at 20000 cents of declared value.
    assert_money(entry["amount_cents"], -20000, "RECEIPT_VARIANCE amount_cents")
    assert entry["sequence_no"] == 1

    single = validate_success(
        api.get_shrink_ledger_entry(entry["id"], ADMIN), 200
    )
    assert single["id"] == entry["id"]
    assert_append_only_resource(single, "shrink ledger entry")

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["shrink_ledger_cents"], -20000, "shrink_ledger_cents")
    assert_money(client["settlement_balance_cents"], -20000, "settlement_balance_cents")
    assert client["status"] == CLIENT_STATUS_ACTIVE, (
        "-20000 is well above the negated 500000-cent exposure cap"
    )


def test_a_catalogue_item_needs_a_client_that_exists(api):
    """PRD §2.6: "Priority 5 resolves every foreign key the request names —
    `client_id`, `catalog_item_id`, `rma_id`, `rma_line_id`, `receipt_id`,
    `return_line_id`, `bay_id`, `channel_id`, `work_order_id` — and returns the
    matching `ERR_*_NOT_FOUND` at 404 when one of them names nothing."

    Design: Corner/entities/corner_catalog_item_requires_existing_client_parent
    """
    fx.make_client(api, name="Real Parent Retail", client_code="CRN11")

    response = api.create_catalog_item(
        f.catalog_item_payload(
            NON_EXISTENT_UUID,
            sku="ORPHAN-1",
            description="Orphan SKU",
            secondary_market_floor_cents=1000,
        ),
        ADMIN,
    )
    validate_error(response, ERR_CLIENT_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_catalog_items(ADMIN, {"limit": 100}))
    assert meta["total_count"] == 0, "no orphan SKU was persisted"


def test_a_scanned_line_must_belong_to_the_receipts_own_authorization(api):
    """PRD §3.3: "Each unit inside the carton is registered as a `ReturnLine`
    against a `receipt_id` and an `rma_line_id`, and the `rma_line_id` must
    belong to the same authorization as the receipt or the scan fails with
    `ERR_LINE_RMA_MISMATCH`."

    Design: Corner/entities/corner_receipt_line_rejects_rma_line_belonging_to_another_rma
    """
    client = fx.make_client(api, name="Mismatch Retail", client_code="CRN12")
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    line_spec = [
        {
            "catalog_item_id": item["id"],
            "authorized_quantity": 1,
            "reason_code": REASON_DEFECTIVE,
        }
    ]
    first = fx.make_issued_rma(
        api, client["id"], line_spec, order_reference="ORD-2004A",
        customer_reference="CUST-2004A",
    )
    second = fx.make_issued_rma(
        api, client["id"], line_spec, order_reference="ORD-2004B",
        customer_reference="CUST-2004B",
    )
    receipt = fx.make_receipt(
        api, first["rma"]["id"], 1400, tracking_reference="TRK-2004"
    )

    response = api.create_receipt_line(
        receipt["id"],
        f.receipt_line_payload(
            second["lines"][0]["id"], quantity=1, reason_code=REASON_DEFECTIVE
        ),
        CLERK,
    )
    validate_error(response, ERR_LINE_RMA_MISMATCH, 409)

    _, meta = validate_paginated(
        api.list_return_lines(ADMIN, {"receipt_id": receipt["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "the mismatched scan created no unit line"
    other = fx.read_rma(api, second["rma"]["id"])
    assert other["received_unit_total"] == 0, (
        "nothing was credited to the other authorization"
    )
