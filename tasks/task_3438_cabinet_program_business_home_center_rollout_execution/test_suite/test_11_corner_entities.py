"""Entity surface: creation defaults, required fields, computed fields, reads (PRD §2.5, §3.1, §3.7)."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    PLATFORM_ADMIN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_PLUS_2,
    assert_account,
    assert_program_line,
    canonical_instant,
    factories,
    family_spec,
    make_dealer_rep_headers,
)
from test_helpers import fixtures


def test_account_creation_applies_defaults_and_system_fields(api):
    """A minimal account create echoes the system fields and the declared
    defaults.

    PRD §3.1: "A new account starts with its `status` field `ACTIVE` and `open_exposure_cents` at zero."
    PRD §3.1: "A `PlatformAdmin` onboards a channel partner by creating an account with its legal `name`; a `channel` of `RETAIL`, `DEALER`, or `BUILDER`; a `pricing_class` of `STANDARD`, `VOLUME`, or `NATIONAL`, which drives the channel price multiplier of §3.3; a `lead_time_class` of `STANDARD` or `EXTENDED`, which drives the promised-lead-time table of §3.3; a non-negative `credit_limit_cents` ceiling; and, for a `RETAIL` account, the `store_codes` the partner operates — an array that defaults to empty and stays empty for `DEALER` and `BUILDER` accounts."
    PRD §2.5: "The `id` is a server-minted UUID with no type prefix."
    PRD §4: "Operations that create a new resource return `201 Created`: account creation, program creation, program-line creation, finish-batch registration, production-slot opening, design-job booking, direct order placement, damage-claim filing, disposition-action appends, and the design-job conversion that produces an order."
    Design: Corner/entities/account_creation_applies_defaults_and_system_fields
    """
    fixtures.reset_clock(api)
    payload = {
        "name": "Dealer A",
        "channel": "DEALER",
        "pricing_class": "STANDARD",
        "lead_time_class": "STANDARD",
        "credit_limit_cents": 50000,
        # store_codes deliberately omitted: it defaults to [].
    }
    resp = api.create_account(payload, PLATFORM_ADMIN_HEADERS)
    account = validate_success(resp, 201)
    assert_account(account)
    assert account["version"] == 1
    assert account["created_at"] == account["updated_at"]
    assert canonical_instant(account["created_at"]) == canonical_instant("2026-09-01T00:00:00Z")
    assert account["status"] == "ACTIVE"
    assert account["open_exposure_cents"] == 0
    assert account["store_codes"] == []


def test_account_missing_required_field_rejected(api):
    """Omitting credit_limit_cents fails request validation; the error envelope
    carries the request id and a message.

    PRD §3.1: "A `PlatformAdmin` onboards a channel partner by creating an account with its legal `name`; a `channel` of `RETAIL`, `DEALER`, or `BUILDER`; a `pricing_class` of `STANDARD`, `VOLUME`, or `NATIONAL`, which drives the channel price multiplier of §3.3; a `lead_time_class` of `STANDARD` or `EXTENDED`, which drives the promised-lead-time table of §3.3; a non-negative `credit_limit_cents` ceiling; and, for a `RETAIL` account, the `store_codes` the partner operates — an array that defaults to empty and stays empty for `DEALER` and `BUILDER` accounts."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    Design: Corner/entities/account_missing_required_field_rejected
    """
    resp = api.create_account(
        {
            "name": "Dealer B",
            "channel": "DEALER",
            "pricing_class": "STANDARD",
            "lead_time_class": "STANDARD",
        },
        PLATFORM_ADMIN_HEADERS,
    )
    error = validate_error(resp, "ERR_INVALID_REQUEST")
    assert error["message"].strip()
    body = resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)


def test_account_computed_field_input_ignored(api):
    """A client-supplied open_exposure_cents is not stored: the account reads
    back the system-maintained derivation.

    PRD §2.8: "Each account's `open_exposure_cents` is a system-maintained derivation over its orders: every order not in `CANCELLED` contributes its `quoted_total_cents` while its `payment_status` is `UNINVOICED` or `CREDIT_HOLD`, its `invoiced_total_cents` once `INVOICED`, and nothing once `PAID`."
    PRD §3.1: "A new account starts with its `status` field `ACTIVE` and `open_exposure_cents` at zero."
    Design: Corner/entities/account_computed_field_input_ignored
    """
    account = fixtures.create_account(
        api, name="Dealer C", credit_limit_cents=50000, open_exposure_cents=999999
    )
    reread = fixtures.get_account(api, account["id"], PLATFORM_ADMIN_HEADERS)
    assert reread["open_exposure_cents"] == 0


def test_account_get_not_found_returns_404(api):
    """A well-formed but absent account id is answered with ERR_NOT_FOUND.

    PRD §2.9: "The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`)."
    Design: Corner/entities/account_get_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS)
    validate_error(resp, "ERR_NOT_FOUND")
    assert resp.json()["response_type"] == "error"


def test_program_line_self_referential_supersedes_link(api):
    """The superseding line points at the line it replaced, and the reverse
    filter finds exactly it.

    PRD §3.7: "The new line starts `ACTIVE` with `supersedes_line_id` pointing at the line it replaces, and its `original_disposition_qty` records the disposition input (zero when the input is omitted)."
    PRD §3.7: "The previously `ACTIVE` line moves to `SUNSETTING`, and its `remaining_disposition_qty` is initialized from that same input."
    Design: Corner/entities/program_line_self_referential_supersedes_link
    """
    world = fixtures.setup_active_program(api)
    line2 = fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=11000, base_lead_weeks=2)],
        include_disposition_qty=True,
    )

    reread2 = fixtures.get_line(api, line2["id"])
    assert_program_line(reread2)
    assert reread2["status"] == "ACTIVE"
    assert reread2["supersedes_line_id"] == world["line"]["id"]

    data, meta = validate_paginated(
        api.list_lines(
            PROGRAM_MANAGER_HEADERS,
            params={"supersedes_line_id": world["line"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == line2["id"]

    line1 = fixtures.get_line(api, world["line"]["id"])
    assert line1["status"] == "SUNSETTING"


def test_order_destination_invalid_enum_rejected(api):
    """A destination_type outside the declared pair fails request validation
    and persists nothing.

    PRD §3.2: "The conversion payload carries the `destination_type` — `JOB_SITE` or `STORE` — a `requested_delivery_week`, and the destination detail, `store_code` or `jobsite_address`, following the destination rules of §3.3."
    PRD §3.3: "Destination rules apply identically at direct placement and at design-job conversion."
    Design: Corner/entities/order_destination_invalid_enum_rejected
    """
    world = fixtures.setup_active_program(api)
    resp = api.create_order(
        factories.order_payload(
            world["account"]["id"], world["program"]["id"], destination_type="PALLET"
        ),
        make_dealer_rep_headers(world["account"]["id"]),
    )
    validate_error(resp, "ERR_INVALID_REQUEST")

    data, meta = validate_paginated(
        api.list_orders(
            PROGRAM_MANAGER_HEADERS, params={"account_id": world["account"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert data == []
