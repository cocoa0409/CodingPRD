"""Role authorization: exclusive operations, per-transition pins, entity-backed ownership (PRD §2.1, §3)."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    FIELD_SERVICE_REP_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_PLUS_2,
    factories,
    family_spec,
    make_dealer_rep_headers,
    make_retail_designer_headers,
)
from test_helpers import fixtures


def test_platform_admin_cannot_create_program(api):
    """Program creation is exclusive to ProgramManager; the PlatformAdmin role
    is refused.

    PRD §2.1: "A request whose role is not authorized for the target operation — or that fails an entity-ownership check — is rejected with `ERR_FORBIDDEN`; a claims decision that violates segregation of duties is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.1: "A `ProgramManager` staffs the program office: programs, program lines, disposition actions, order acknowledgement and financial transitions, and display-reset waivers."
    Design: Corner/rbac/platform_admin_cannot_create_program
    """
    account = fixtures.create_account(api, name="Dealer U", credit_limit_cents=1000000)

    refused = api.create_program(
        factories.program_payload(account["id"], name="PX"), PLATFORM_ADMIN_HEADERS
    )
    validate_error(refused, "ERR_FORBIDDEN")


def test_dealer_rep_cannot_acknowledge_order(api):
    """The ACKNOWLEDGED transition is pinned to ProgramManager; the
    order-owning DealerRep is refused even on their own account's order.

    PRD §3.4: "An order moves from `SUBMITTED` to `ACKNOWLEDGED` only on a `ProgramManager`'s acknowledgement, gated on an `ACTIVE` account and a program in `ACTIVE` or `TRANSITIONING`."
    PRD §2.1: "A request whose role is not authorized for the target operation — or that fails an entity-ownership check — is rejected with `ERR_FORBIDDEN`; a claims decision that violates segregation of duties is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/rbac/dealer_rep_cannot_acknowledge_order
    """
    world = fixtures.setup_submitted_order(api)

    refused = api.transition_order(
        world["order"]["id"], {"to_status": "ACKNOWLEDGED"},
        make_dealer_rep_headers(world["account"]["id"]),
    )
    validate_error(refused, "ERR_FORBIDDEN")
    assert fixtures.get_order(api, world["order"]["id"])["status"] == "SUBMITTED"


def test_dealer_rep_cannot_cancel_other_accounts_order(api):
    """Entity-backed identity: a DealerRep's X-User-ID is their account id, so
    another account's order is out of reach.

    PRD §2.1: "When `X-User-Role` is `DealerRep`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` — placing a direct order, cancelling an order, filing a damage claim — compare the resource's `account_id` field to `X-User-ID`."
    PRD §3.6: "It is available to a `ProgramManager`, or to the `DealerRep` who owns the order's account (`ERR_FORBIDDEN` for anyone else), and only from `SUBMITTED`, `ACKNOWLEDGED`, or `SCHEDULED`; from `IN_PRODUCTION`, `MFG_COMPLETE`, `SHIPPED`, `DELIVERED`, or `CANCELLED` the request is rejected with `ERR_ORDER_NOT_CANCELLABLE`."
    Design: Corner/rbac/dealer_rep_cannot_cancel_other_accounts_order
    """
    fixtures.reset_clock(api)
    account_a = fixtures.create_account(api, name="Dealer A2")
    account_b = fixtures.create_account(api, name="Dealer B2")
    program_b = fixtures.create_program(api, account_b["id"], name="PB")
    fixtures.create_first_line(api, program_b["id"])
    fixtures.activate_program(api, program_b["id"])
    order_b = fixtures.place_order(api, account_b, program_b)

    refused = api.cancel_order(order_b["id"], make_dealer_rep_headers(account_a["id"]))
    validate_error(refused, "ERR_FORBIDDEN")
    assert fixtures.get_order(api, order_b["id"])["status"] == "SUBMITTED"

    # Control: the owning DealerRep cancels their own account's order.
    cancelled = api.cancel_order(order_b["id"], make_dealer_rep_headers(account_b["id"]))
    assert validate_success(cancelled, 200)["status"] == "CANCELLED"


def test_field_service_rep_cannot_waive_display_reset(api):
    """WAIVED is pinned to ProgramManager; the field crew that schedules and
    completes resets cannot waive one.

    PRD §3.7: "A `ProgramManager` may instead waive a reset from `PLANNED` or `SCHEDULED`, moving it to `WAIVED`."
    PRD §2.9: "The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`)."
    Design: Corner/rbac/field_service_rep_cannot_waive_display_reset
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1"])
    fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=11000, base_lead_weeks=2)],
        include_disposition_qty=True,
    )
    resets = fixtures.list_display_resets(api, {"program_id": world["program"]["id"]})
    assert len(resets) == 1
    reset = resets[0]

    refused = api.transition_display_reset(
        reset["id"], {"to_status": "WAIVED"}, FIELD_SERVICE_REP_HEADERS
    )
    validate_error(refused, "ERR_FORBIDDEN")
    assert fixtures.get_display_reset(api, reset["id"])["status"] == "PLANNED"


def test_retail_designer_cannot_drive_another_designers_job(api):
    """Design-job transitions are owned through designer_user_id; a different
    designer is refused.

    PRD §3.2: "The booking designer's `X-User-ID` is captured as the job's `designer_user_id`, and every later transition of that job requires the caller's `X-User-ID` to equal it (`ERR_FORBIDDEN`)."
    Design: Corner/rbac/retail_designer_cannot_drive_another_designers_job
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1"])
    job = fixtures.create_design_job(api, world["account"], world["program"], "des-1")
    assert job["designer_user_id"] == "des-1"

    refused = api.transition_design_job(
        job["id"], {"to_status": "MEASURED"}, make_retail_designer_headers("des-2")
    )
    validate_error(refused, "ERR_FORBIDDEN")

    after = fixtures.get_design_job(api, job["id"], PROGRAM_MANAGER_HEADERS)
    assert after["status"] == "REQUESTED"
