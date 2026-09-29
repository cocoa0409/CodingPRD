"""The cancellation unwind, the fleet-stock gate on installing a brewer, and the
money ledger that a credit line has to restore exactly.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_account,
    assert_invoice,
    assert_invoice_line,
    assert_placement,
    assert_site,
)
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    assemble_invoice_for,
    cancel_account,
    complete_stop,
    create_asset,
    issue_invoice,
    lines_by_type,
    list_invoice_lines,
    list_placements,
    place_asset_at_site,
    read_account,
    read_asset,
    read_invoice,
    read_invoice_line,
    read_placement,
    read_route,
    read_site,
    read_visit,
    retrieve_placement,
    schedule_stop_with_lines,
    schedule_visit,
    set_clock,
    setup_placed_site,
    setup_second_site,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

RETRIEVAL_DUE_BY = "2026-08-31T00:00:00Z"
LATER_MONDAY_START = "2026-08-17T09:00:00Z"
LATER_MONDAY_END = "2026-08-17T09:45:00Z"


def test_cancellation_unwinds_placement_then_site_then_the_scheduled_stop():
    """One cancellation call schedules retrieval on the installed brewer, suspends
    the break room that holds it, cancels that room's scheduled stop and gives the
    booked minutes back to the route.

    "The account moves to `CANCELLATION_PENDING` from whichever of `ONBOARDING`,
    `ACTIVE` or `AT_RISK` it was in — the three source postures behave identically —
    and `cancel_reason`, `retrieval_due_by` and `cancelled_at` are stamped, the last
    with the current instant. Hop one: every equipment placement belonging to any
    site of this account whose installation state is `ACTIVE` moves to
    `RETRIEVAL_SCHEDULED`, and each such placement's own `retrieval_due_by` is
    copied from the account's. Hop two: each site owning one of those placements
    moves its service posture to `SUSPENDED`, whether it was `ACTIVE` or `ESCALATED`
    at the time — and when the suspended site had been `ESCALATED`, the account's
    `escalated_site_count` is recomputed in the same pass, because a suspended site no
    longer counts as escalated. Hop three: every service visit of those sites still in
    `SCHEDULED` moves to `CANCELLED`, and each cancellation releases that visit's
    booked minutes back to its route."

    Design: Difficulty/transitive_cascade/account_cancellation_cascades_placement_to_site_to_scheduled_visit
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    assert base["account"]["program_posture"] == "ACTIVE"
    assert base["site"]["service_posture"] == "ACTIVE"

    visit = schedule_visit(
        base["site"]["id"],
        window_start=LATER_MONDAY_START,
        window_end=LATER_MONDAY_END,
        planned_minutes=45,
    )
    assert visit["visit_status"] == "SCHEDULED"
    assert read_route(base["route"]["id"])["booked_minutes_total"] == 45

    cancelled = cancel_account(
        base["account"]["id"],
        cancel_reason="Customer consolidating vendors",
        retrieval_due_by=RETRIEVAL_DUE_BY,
    )
    assert_account(cancelled)
    assert cancelled["program_posture"] == "CANCELLATION_PENDING"
    assert cancelled["cancelled_at"] == ANCHOR_MONDAY
    assert cancelled["cancel_reason"] == "Customer consolidating vendors"
    assert cancelled["retrieval_due_by"] == RETRIEVAL_DUE_BY

    # Hop one.
    placement = read_placement(base["placement"]["id"])
    assert_placement(placement)
    assert placement["placement_status"] == "RETRIEVAL_SCHEDULED"
    assert placement["retrieval_due_by"] == RETRIEVAL_DUE_BY

    # Hop two.
    site = read_site(base["site"]["id"])
    assert_site(site)
    assert site["service_posture"] == "SUSPENDED"

    # Hop three.
    assert read_visit(visit["id"])["visit_status"] == "CANCELLED"
    assert read_route(base["route"]["id"])["booked_minutes_total"] == 0

    # Retrieval has been scheduled, not performed.
    assert read_asset(base["asset"]["id"])["asset_status"] == "PLACED"


def test_the_same_unwind_voids_the_draft_and_spares_the_completed_stop():
    """A stop already reported keeps its minutes and its status while only the
    still-scheduled one is cancelled, the open draft is voided in the same pass,
    and afterwards the programme accepts nothing new.

    "In the same pass, every consolidated invoice of the account still in `DRAFT`
    moves to `VOID`. The account's `version` increments by 1."

    "Sites, placements and service visits may only be created while
    `program_posture` is `ONBOARDING`, `ACTIVE`, or `AT_RISK`. A
    `CANCELLATION_PENDING` or `CLOSED` account rejects all three with
    `ERR_ACCOUNT_NOT_OPERATING` (HTTP 409). The same error and the same rule guard
    cancellation itself: cancellation is permitted from `ONBOARDING`, `ACTIVE` or
    `AT_RISK`, so a second cancellation attempt against an already-cancelling or
    closed account is refused with `ERR_ACCOUNT_NOT_OPERATING`."

    Design: Difficulty/transitive_cascade/account_cancellation_cascades_placement_to_site_to_scheduled_visit
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    served = schedule_stop_with_lines(base, {"COFFEE": 20})
    served = complete_stop(base, served, {"COFFEE": 20})
    assert served["visit_status"] == "COMPLETED"

    pending = schedule_visit(
        base["site"]["id"],
        window_start=LATER_MONDAY_START,
        window_end=LATER_MONDAY_END,
        planned_minutes=45,
    )
    assert read_route(base["route"]["id"])["booked_minutes_total"] == 90

    set_clock("2026-08-16T08:00:00Z")
    draft = assemble_invoice_for(
        base["account"]["id"], "2026-08-01T00:00:00Z", "2026-08-15T23:59:59Z"
    )
    assert draft["invoice_status"] == "DRAFT"

    cancelled = cancel_account(
        base["account"]["id"],
        cancel_reason="Site closing permanently",
        retrieval_due_by=RETRIEVAL_DUE_BY,
    )
    assert cancelled["program_posture"] == "CANCELLATION_PENDING"
    assert cancelled["cancelled_at"] == "2026-08-16T08:00:00Z"

    voided = read_invoice(draft["id"])
    assert_invoice(voided)
    assert voided["invoice_status"] == "VOID"

    # Only the still-scheduled stop is cancelled, and only its minutes come back.
    assert read_visit(served["id"])["visit_status"] == "COMPLETED"
    assert read_visit(pending["id"])["visit_status"] == "CANCELLED"
    assert read_route(base["route"]["id"])["booked_minutes_total"] == 45

    assert read_placement(base["placement"]["id"])["placement_status"] == (
        "RETRIEVAL_SCHEDULED"
    )
    assert read_site(base["site"]["id"])["service_posture"] == "SUSPENDED"

    # The programme is closed to new work, cancellation included.
    validate_error(
        api_client.cancel_account(
            base["account"]["id"],
            f.cancel_account_payload(retrieval_due_by=RETRIEVAL_DUE_BY),
            AM,
        ),
        "ERR_ACCOUNT_NOT_OPERATING",
        409,
    )
    validate_error(
        api_client.create_site(
            f.create_site_payload(
                base["account"]["id"],
                base["route"]["id"],
                site_name="Ninth Floor Break Room",
            ),
            AM,
        ),
        "ERR_ACCOUNT_NOT_OPERATING",
        409,
    )
    assert read_account(base["account"]["id"])["program_posture"] == (
        "CANCELLATION_PENDING"
    )


def _two_break_rooms_and_a_spare_brewer():
    """One break room already holding a brewer, a second planned room with none,
    and an untouched second brewer of the same model still in stock."""
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    base["site_b"] = setup_second_site(base, site_name="HQ Floor 4")
    base["asset_2"] = create_asset(base["model"]["id"], serial_number="URN30-0002")
    assert base["asset_2"]["asset_status"] == "IN_STOCK"
    return base


def _placement_body(site_id: str, asset_id: str, expected_site_version: int) -> dict:
    return f.create_placement_payload(
        site_id,
        asset_id,
        expected_site_version,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        min_term_months=12,
    )


def test_installing_a_brewer_depends_on_that_brewer_still_being_in_stock():
    """The brewer already installed at one break room cannot be installed at
    another, while a second brewer of the same model can; the refused write
    consumes no version and creates nothing.

    "Installing a brewer moves it `IN_STOCK` → `PLACED`, and requires the asset to
    be `IN_STOCK` and to carry the `PLACEMENT` role; an asset in any other fleet
    state is refused with `ERR_ASSET_NOT_AVAILABLE` (HTTP 409)."

    "Creation stamps `placed_at` with the current instant, starts
    `placement_status` at `ACTIVE` and `compliance_status` at `MEETING_MINIMUM`,
    sets `trailing_purchase_cents`, `shortfall_fee_cents`, `rent_charge_cents` and
    `unreturned_billed_cents` to 0, and leaves the placement's own
    `retrieval_due_by` null."

    Design: Difficulty/cross_entity_state_dependency/placement_creation_depends_on_equipment_asset_stock_state
    """
    base = _two_break_rooms_and_a_spare_brewer()
    site_b = base["site_b"]
    assert read_asset(base["asset"]["id"])["asset_status"] == "PLACED"

    refused = api_client.create_placement(
        _placement_body(site_b["id"], base["asset"]["id"], site_b["version"]), AM
    )
    validate_error(refused, "ERR_ASSET_NOT_AVAILABLE", 409)
    assert read_site(site_b["id"])["version"] == site_b["version"], (
        "a rejected version-guarded write does not consume the version"
    )
    assert list_placements(site_id=site_b["id"]) == []

    # The same request differing only in the brewer named is accepted.
    accepted = validate_success(
        api_client.create_placement(
            _placement_body(site_b["id"], base["asset_2"]["id"], site_b["version"]), AM
        ),
        201,
    )
    assert_placement(accepted)
    assert accepted["placement_status"] == "ACTIVE"
    assert accepted["compliance_status"] == "MEETING_MINIMUM"
    assert accepted["placed_at"] == ANCHOR_MONDAY
    assert accepted["retrieval_due_by"] is None
    for zeroed in (
        "trailing_purchase_cents",
        "shortfall_fee_cents",
        "rent_charge_cents",
        "unreturned_billed_cents",
    ):
        assert accepted[zeroed] == 0

    assert read_asset(base["asset_2"]["id"])["asset_status"] == "PLACED"
    still_installed = read_asset(base["asset"]["id"])
    assert still_installed["asset_status"] == "PLACED"
    bound = list_placements(asset_id=base["asset"]["id"])
    assert len(bound) == 1, "the first brewer is still bound to its original room"
    assert bound[0]["id"] == base["placement"]["id"]
    assert bound[0]["site_id"] == base["site"]["id"]


def test_a_superseded_brewer_returns_to_stock_and_is_immediately_reusable():
    """Swapping in a newer brewer retires the old contract and puts the old
    brewer back in stock, from where the very request that was refused a moment
    ago succeeds.

    "When the placement holding an asset is superseded, that asset returns
    `PLACED` → `IN_STOCK` and is immediately reusable."

    "Creation also **supersedes**. If the site already has a placement in
    `ACTIVE`, that prior placement moves `ACTIVE` → `SUPERSEDED` and its asset
    returns to `IN_STOCK`."

    Design: Difficulty/cross_entity_state_dependency/placement_creation_depends_on_equipment_asset_stock_state
    """
    base = _two_break_rooms_and_a_spare_brewer()
    site_b = base["site_b"]

    # While the first brewer is installed, room B cannot have it.
    validate_error(
        api_client.create_placement(
            _placement_body(site_b["id"], base["asset"]["id"], site_b["version"]), AM
        ),
        "ERR_ASSET_NOT_AVAILABLE",
        409,
    )

    # Upgrade room A, which supersedes the original contract.
    upgraded = place_asset_at_site(
        read_site(base["site"]["id"]),
        base["asset_2"]["id"],
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        min_term_months=12,
    )
    assert upgraded["placement_status"] == "ACTIVE"
    assert upgraded["site_id"] == base["site"]["id"]

    superseded = read_placement(base["placement"]["id"])
    assert superseded["placement_status"] == "SUPERSEDED"
    freed = read_asset(base["asset"]["id"])
    assert freed["asset_status"] == "IN_STOCK", "the retired brewer is back in stock"
    assert freed["asset_role"] == "PLACEMENT"

    # The identical request now succeeds without any further step.
    reused = validate_success(
        api_client.create_placement(
            _placement_body(site_b["id"], base["asset"]["id"], site_b["version"]), AM
        ),
        201,
    )
    assert_placement(reused)
    assert reused["placement_status"] == "ACTIVE"
    assert reused["asset_id"] == base["asset"]["id"]
    assert reused["site_id"] == site_b["id"]
    assert read_asset(base["asset"]["id"])["asset_status"] == "PLACED"

    history = list_placements(asset_id=base["asset"]["id"])
    assert len(history) == 2
    assert {row["placement_status"] for row in history} == {"SUPERSEDED", "ACTIVE"}


UNRETURNED_CHARGE_CENTS = 125700
RESIDUAL_VALUE_CENTS = 118200
INVOICE_CLOCK = "2026-09-05T12:00:00Z"
PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-08-31T23:59:59Z"


def _brewer_written_off_on_a_draft():
    """A loaned brewer never returned by its retrieval deadline, written off by a
    draft assembled thirty-three days after it was installed."""
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="LOAN",
        minimum_purchase_cents=100000,
        serial_number="URN30-0001",
    )
    assert base["account"]["receivable_balance_cents"] == 0
    assert base["placement"]["placed_at"] == ANCHOR_MONDAY

    set_clock("2026-08-03T09:00:00Z")
    cancel_account(
        base["account"]["id"],
        cancel_reason="Customer consolidating vendors",
        retrieval_due_by=RETRIEVAL_DUE_BY,
    )
    assert read_placement(base["placement"]["id"])["placement_status"] == (
        "RETRIEVAL_SCHEDULED"
    )

    set_clock(INVOICE_CLOCK)
    base["invoice"] = assemble_invoice_for(
        base["account"]["id"], PERIOD_START, PERIOD_END
    )
    return base


def test_an_unreturned_brewer_is_billed_and_retrieval_alone_credits_nothing():
    """The write-off is priced from one whole month of depreciation plus the trip
    fee, issuing loads it onto the receivable, and getting the equipment back
    afterwards leaves that receivable untouched.

    "The number of months in service is the elapsed time from the anchor to the
    current instant divided by 30 days, rounded down to a whole number. The
    depreciated proportion is 10000 basis points reduced by 150 basis points for
    each whole month in service — one and a half percent per month — but never
    allowed below a residual floor of 3000 basis points, so an asset never depreciates
    past thirty percent of its list value no matter how old it is. The asset's residual
    value in cents is the model's `list_value_cents` multiplied by that depreciated
    proportion, divided by 10000, rounded half up. The charge finally billed is that
    residual value plus a flat retrieval trip fee of 7500 cents, and the sum is what
    lands in the placement's `unreturned_billed_cents` and on the `UNRETURNED_ASSET`
    line."

    "One asymmetry is deliberate and must not be smoothed over: retrieving a
    placement that was already billed as unreturned does **not** automatically credit
    the issued charge. The `UNRETURNED_ASSET` line stays on the issued invoice, and a
    `BillingSpecialist` must post a compensating credit line explicitly."

    Design: Difficulty/compensating_invariant/credit_line_restores_account_receivable_after_an_unreturned_asset_writeoff
    """
    base = _brewer_written_off_on_a_draft()
    invoice = base["invoice"]
    assert_invoice(invoice)
    assert invoice["pre_freight_total_cents"] == UNRETURNED_CHARGE_CENTS
    assert invoice["allied_discount_bps"] == 0
    assert invoice["allied_discount_cents"] == 0
    assert invoice["freight_cents"] == 0, "the charge clears the free-freight floor"
    assert invoice["total_cents"] == UNRETURNED_CHARGE_CENTS
    assert invoice["line_count"] == 1
    assert invoice["invoice_status"] == "DRAFT"
    assert invoice["issued_at"] is None

    lines = list_invoice_lines(invoice["id"])
    assert len(lines) == 1
    writeoff = lines[0]
    assert_invoice_line(writeoff)
    assert writeoff["line_type"] == "UNRETURNED_ASSET"
    assert writeoff["amount_cents"] == RESIDUAL_VALUE_CENTS + 7500
    assert writeoff["amount_cents"] == UNRETURNED_CHARGE_CENTS
    assert writeoff["site_id"] == base["site"]["id"]
    assert writeoff["credits_applied_cents"] == 0

    billed = read_placement(base["placement"]["id"])
    assert billed["placement_status"] == "UNRETURNED_BILLED"
    assert billed["unreturned_billed_cents"] == UNRETURNED_CHARGE_CENTS
    assert read_asset(base["asset"]["id"])["asset_status"] == "UNRETURNED"

    issued = issue_invoice(invoice["id"])
    assert issued["invoice_status"] == "ISSUED"
    assert issued["issued_at"] == INVOICE_CLOCK
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == (
        UNRETURNED_CHARGE_CENTS
    )

    # The equipment turns up: the programme closes, the money does not move.
    retrieved = retrieve_placement(base["placement"]["id"], "SERVICEABLE")
    assert retrieved["placement_status"] == "RETRIEVED"
    assert read_asset(base["asset"]["id"])["asset_status"] == "RECONDITIONING"
    closed_account = read_account(base["account"]["id"])
    assert closed_account["program_posture"] == "CLOSED"
    assert read_site(base["site"]["id"])["service_posture"] == "CLOSED"
    assert closed_account["receivable_balance_cents"] == UNRETURNED_CHARGE_CENTS, (
        "retrieval never auto-credits the issued charge"
    )
    unchanged = read_invoice(invoice["id"])
    assert unchanged["invoice_status"] == "ISSUED"
    assert unchanged["total_cents"] == UNRETURNED_CHARGE_CENTS
    assert unchanged["line_count"] == 1
    assert read_invoice_line(writeoff["id"])["credits_applied_cents"] == 0


def test_the_credit_line_restores_the_receivable_to_zero_with_no_residue():
    """An explicit full credit is the compensating action: it negates the
    write-off line, empties the invoice, returns the receivable to where it
    started, and closes the invoice to any further credit.

    "A successful credit appends a new invoice line whose `line_type` is `CREDIT`,
    whose `amount_cents` is the **negation** of the requested amount, whose
    `target_line_id` points at the credited line, and whose `credit_reason` carries
    the supplied reason. The target line's `credits_applied_cents` increases by the
    requested amount. The invoice's `total_cents` is recomputed as the sum of all of
    its lines — with the negative `ALLIED_DISCOUNT` and `CREDIT` lines counted as
    negative — and its `line_count` increases by 1. The account's
    `receivable_balance_cents` decreases by the credited amount. The invoice then
    moves to `PARTIALLY_CREDITED` when the cumulative credits after this one are
    strictly less than the pre-credit total, and to `FULLY_CREDITED` when they
    exactly equal it, at which point the invoice's total is 0 and the invoice is
    terminal."

    "Issuance requires `DRAFT`; crediting requires `ISSUED` or
    `PARTIALLY_CREDITED`; `VOID` and `FULLY_CREDITED` accept neither. Any mismatch
    yields `ERR_INVOICE_STATE_INVALID` (HTTP 409)."

    Design: Difficulty/compensating_invariant/credit_line_restores_account_receivable_after_an_unreturned_asset_writeoff
    """
    base = _brewer_written_off_on_a_draft()
    invoice_id = base["invoice"]["id"]
    writeoff_id = list_invoice_lines(invoice_id)[0]["id"]

    issue_invoice(invoice_id)
    retrieve_placement(base["placement"]["id"], "SERVICEABLE")
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == (
        UNRETURNED_CHARGE_CENTS
    )

    credit = validate_success(
        api_client.credit_invoice(
            invoice_id,
            f.credit_invoice_payload(
                writeoff_id, UNRETURNED_CHARGE_CENTS, "Equipment recovered intact"
            ),
            BS,
        ),
        201,
    )
    assert_invoice_line(credit)
    assert credit["line_type"] == "CREDIT"
    assert credit["amount_cents"] == -UNRETURNED_CHARGE_CENTS
    assert credit["target_line_id"] == writeoff_id
    assert credit["credit_reason"] == "Equipment recovered intact"
    assert credit["invoice_id"] == invoice_id
    assert credit["qty_units"] == 0
    assert credit["unit_price_micros"] == 0
    assert credit["product_id"] is None
    assert credit["site_id"] == base["site"]["id"]

    settled = read_invoice(invoice_id)
    assert settled["invoice_status"] == "FULLY_CREDITED"
    assert settled["total_cents"] == 0
    assert settled["line_count"] == 2
    assert settled["pre_freight_total_cents"] == UNRETURNED_CHARGE_CENTS

    assert read_invoice_line(writeoff_id)["credits_applied_cents"] == (
        UNRETURNED_CHARGE_CENTS
    )
    by_type = lines_by_type(invoice_id)
    assert len(by_type["UNRETURNED_ASSET"]) == 1
    assert len(by_type["CREDIT"]) == 1

    # The money ledger is conserved end to end: 0 to +125700 to 0.
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 0

    # A fully credited invoice is terminal.
    validate_error(
        api_client.credit_invoice(
            invoice_id,
            f.credit_invoice_payload(writeoff_id, 1, "Second thoughts"),
            BS,
        ),
        "ERR_INVOICE_STATE_INVALID",
        409,
    )
    assert read_invoice(invoice_id)["line_count"] == 2
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 0
