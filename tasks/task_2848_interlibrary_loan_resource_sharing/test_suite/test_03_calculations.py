"""Pinned arithmetic: landed cost, royalty, subsidy tiers, fines, waterfalls and
settlement periods."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_agreement,
    create_article_bib_item,
    create_bib_item,
    create_lending_charge,
    create_partner,
    create_patron,
    create_rota,
    draft_invoice,
    intake_copy_request,
    intake_request,
    lender_confirm,
    list_request_shipments,
    load_infraction,
    partner_version,
    pickup_loan,
    read_loan,
    read_partner,
    read_patron,
    read_request,
    receive_shipment,
    return_loan,
    run_rota_round,
    set_clock,
    settle_loan_charge,
    ship_item,
)
from test_helpers.test_users import (
    ILL_STAFF_ALT_USER_ID,
    make_accountant_headers,
    make_ill_staff_headers,
)
from test_helpers.types import (
    BillingStatus,
    ClearanceMethod,
    InvoiceDirection,
    InvoiceStatus,
    ItemType,
    LicensedAccessStatus,
    LocalHoldingStatus,
    MaterialType,
    PatronStatus,
    RecallStatus,
    RequestStatus,
    SelectionPolicy,
    ServiceType,
    SettlementMode,
    ShipmentCondition,
    ShipmentDirection,
)
import test_helpers.factories as F


def test_landed_cost_ranking_overturns_the_cheapest_quote(client):
    """Once the day penalty is applied the lowest quoted fee becomes the most
    expensive candidate, and the offer goes to the best landed cost.

    PRD: "The landed cost of a candidate is therefore its effective fee, plus 250
    cents multiplied by its late days, plus the imbalance penalty where it
    applies."

    Design: Corner/calculations/landed_cost_ranking_reorders_the_rota_once_the_day_penalty_is_applied
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9020",
        full_name="Pat Reader",
        email="pat@u.edu",
        patron_type="FACULTY",
        department="HIST",
    )
    southc = create_partner(
        client,
        code="SOUTHC",
        name="South Coast Library",
        base_lending_fee_cents=1200,
        avg_turnaround_days=9,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    westa = create_partner(
        client,
        code="WESTA",
        name="West Annex Library",
        base_lending_fee_cents=2500,
        avg_turnaround_days=2,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    northu = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        material_type=MaterialType.LOAN,
        selection_policy=SelectionPolicy.LANDED_COST,
        max_attempts=3,
    )
    add_rota_entry(
        client,
        rota["id"],
        southc["id"],
        manual_rank=1,
        quoted_fee_cents=1200,
        quoted_turnaround_days=9,
    )
    add_rota_entry(
        client,
        rota["id"],
        westa["id"],
        manual_rank=2,
        quoted_fee_cents=2500,
        quoted_turnaround_days=2,
    )
    add_rota_entry(
        client,
        rota["id"],
        northu["id"],
        manual_rank=3,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Atlantic Trade Routes",
        item_type=ItemType.BOOK,
        publication_year=2005,
        isbn="978-0-000-00040-0",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-04T00:00:00.000Z",
        max_supply_fee_cents=9000,
    )

    offer = run_rota_round(client, request["id"])

    assert offer["partner_id"] == northu["id"]
    assert offer["effective_fee_cents"] == 2000
    assert offer["landed_cost_cents"] == 2250
    assert offer["imbalance_penalty_cents"] == 0
    assert offer["attempt_seq"] == 1

    sourced = read_request(client, request["id"])
    assert sourced["days_available_at_source"] == 3
    assert sourced["attempt_count"] == 1
    assert sourced["status"] == RequestStatus.OFFER_PENDING
    assert sourced["rush_surcharge_cents"] == 0

    _offers, offer_meta = validate_paginated(
        client.list_supply_offers(
            headers=make_ill_staff_headers(), params={"request_id": request["id"]}
        )
    )
    assert offer_meta["total_count"] == 1


def test_royalty_and_subsidy_are_recomputed_at_clearance_and_at_commitment(client):
    """The royalty term feeds the gross, so the request is priced once when the
    clearance lands and again when the lender commits.

    PRD: "The same pricing rule runs again, unchanged, whenever a paid-royalty
    clearance is recorded on a request that was already priced or is priced later,
    because the royalty term feeds the gross and therefore the tier."

    Design: Corner/calculations/royalty_fee_and_subsidy_are_recomputed_when_the_clearance_and_the_commitment_land
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9021",
        full_name="Rae Reader",
        email="rae@u.edu",
        patron_type="FACULTY",
        department="CHEM",
        max_open_requests=10,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=1500,
        avg_turnaround_days=2,
        supplies_electronic=True,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.COPY, max_attempts=3)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=1500,
        quoted_turnaround_days=2,
    )
    bib_item = create_article_bib_item(
        client,
        issn="3333-0001",
        title="Catalysis at low pressure",
        publication_year=2024,
        journal_title="Chemical Reports",
        list_price_cents=4000,
    )

    for _ in range(5):
        filled = intake_copy_request(
            client,
            patron["id"],
            bib_item["id"],
            rota["id"],
            pages_requested=12,
            needed_by="2026-08-20T00:00:00.000Z",
            max_supply_fee_cents=9000,
        )
        assert filled["status"] == RequestStatus.SOURCING

    request = intake_copy_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        pages_requested=40,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=9000,
    )
    assert request["status"] == RequestStatus.COPYRIGHT_HOLD

    clearance = validate_success(
        client.create_copyright_clearance(
            request["id"],
            F.royalty_clearance_payload(3400),
            headers=make_ill_staff_headers(ILL_STAFF_ALT_USER_ID),
        ),
        expected_status=201,
    )
    assert clearance["method"] == ClearanceMethod.ROYALTY_PAID
    assert clearance["royalty_cents"] == 3400
    assert clearance["sequence_in_year"] == 0
    assert clearance["approved_by_user_id"] == ILL_STAFF_ALT_USER_ID

    priced_once = read_request(client, request["id"])
    assert priced_once["status"] == RequestStatus.SOURCING
    assert priced_once["royalty_cents"] == 3400

    offer = run_rota_round(client, request["id"])
    accept_offer(client, offer["id"], partner["id"])

    priced_twice = read_request(client, request["id"])
    assert priced_twice["committed_fee_cents"] == 1500
    assert priced_twice["rush_surcharge_cents"] == 0
    assert priced_twice["royalty_cents"] == 3400
    assert priced_twice["gross_charge_cents"] == 4900
    assert priced_twice["subsidy_cents"] == 2940
    assert priced_twice["net_patron_charge_cents"] == 1960

    usage = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "3333-0001", "calendar_year": 2026},
        )
    )
    assert usage["counted_fill_count"] == 5
    assert usage["free_fills_remaining"] == 0
    assert usage["royalty_paid_count"] == 1


def test_overdue_fine_is_clamped_to_the_declared_cap(client):
    """Fifty-eight billable days raw-compute past the ceiling, so the written fine
    is the cap and nothing else is charged.

    PRD: "The fine is the raw amount multiplied by that multiplier, and only then
    capped at 6000 cents: **the cap is applied after the multiplier, never before
    it**, so a raw fine of 3000 cents on a breached recall yields 6000 cents rather
    than 3000."

    Design: Corner/calculations/overdue_fine_stops_at_the_declared_cap_after_fifty_eight_billable_days
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9022",
        full_name="Sam Reader",
        email="sam@u.edu",
        patron_type="GRAD",
        department="MUSI",
        unpaid_balance_cap_cents=20000,
    )
    partner = create_partner(
        client,
        code="SHORTL",
        name="Short Loan Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=7,
        max_renewals=1,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Counterpoint Studies",
        item_type=ItemType.BOOK,
        publication_year=2004,
        isbn="978-0-000-00041-7",
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    accept_offer(client, offer["id"], partner["id"])
    shipment = ship_item(
        client, offer["id"], partner["id"], carrier="UPS", tracking_code="1Z-SL-0093"
    )
    loan = receive_shipment(client, shipment["id"])
    assert_same_instant(loan["due_at"], "2026-08-08T00:00:00.000Z")
    assert loan["replacement_cost_cents"] == 9000
    pickup_loan(client, loan["id"])

    set_clock(client, "2026-10-07T00:00:00Z")
    returned = return_loan(client, loan["id"])

    assert_same_instant(returned["return_prepared_at"], "2026-10-07T00:00:00.000Z")
    assert returned["overdue_fine_cents"] == 6000
    assert returned["damage_fee_cents"] == 0
    assert returned["lost_replacement_cents"] == 0
    assert returned["lender_processing_fee_cents"] == 0
    assert returned["total_charge_cents"] == 6000
    assert returned["outstanding_cents"] == 6000
    assert returned["billing_status"] == BillingStatus.FINE_ACCRUED
    assert returned["recall_status"] == RecallStatus.NONE

    fined_patron = read_patron(client, patron["id"])
    assert fined_patron["unpaid_balance_cents"] == 6000
    assert fined_patron["late_return_count"] == 1


def test_subsidy_tier_boundary_at_six_thousand_and_six_thousand_and_one(client):
    """A gross of exactly 6000 stays in the middle tier while 6001 crosses into the
    next one, so one extra cent of gross costs the patron far more.

    PRD: "**Fifth**, the departmental subsidy rate is looked up **from the gross
    figure, never from the net**: a gross at or below 2000 cents subsidises at 0.80,
    a gross from 2001 through 6000 cents at 0.60, a gross from 6001 through 12000
    cents at 0.40, and a gross strictly above 12000 cents at 0.25."

    Design: Corner/calculations/subsidy_tier_boundary_at_six_thousand_and_six_thousand_and_one
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9023",
        full_name="Tom Reader",
        email="tom@u.edu",
        patron_type="FACULTY",
        department="LAWS",
        max_open_requests=5,
        unpaid_balance_cap_cents=20000,
    )
    partner = create_partner(
        client,
        code="BIGLE",
        name="Big Lender Research Library",
        base_lending_fee_cents=6000,
        avg_turnaround_days=4,
        supplies_electronic=False,
        loan_period_days=28,
        max_renewals=2,
    )
    six_rota = create_rota(
        client, name="SIX rota", material_type=MaterialType.LOAN, max_attempts=3
    )
    add_rota_entry(
        client,
        six_rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=6000,
        quoted_turnaround_days=4,
    )
    sixone_rota = create_rota(
        client, name="SIXONE rota", material_type=MaterialType.LOAN, max_attempts=3
    )
    add_rota_entry(
        client,
        sixone_rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=6001,
        quoted_turnaround_days=4,
    )
    bib_a = create_bib_item(
        client,
        title="Comparative Constitutional Law",
        item_type=ItemType.BOOK,
        publication_year=2021,
        isbn="978-0-000-00042-4",
        list_price_cents=15000,
    )
    bib_b = create_bib_item(
        client,
        title="Comparative Administrative Law",
        item_type=ItemType.BOOK,
        publication_year=2021,
        isbn="978-0-000-00043-1",
        list_price_cents=15000,
    )

    request_a = intake_request(
        client,
        patron["id"],
        bib_a["id"],
        six_rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=9000,
    )
    offer_a = run_rota_round(client, request_a["id"])
    request_b = intake_request(
        client,
        patron["id"],
        bib_b["id"],
        sixone_rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=9000,
    )
    offer_b = run_rota_round(client, request_b["id"])

    accept_offer(client, offer_a["id"], partner["id"])
    priced_a = read_request(client, request_a["id"])
    assert priced_a["gross_charge_cents"] == 6000
    assert priced_a["subsidy_cents"] == 3600
    assert priced_a["net_patron_charge_cents"] == 2400
    assert priced_a["rush_surcharge_cents"] == 0

    accept_offer(client, offer_b["id"], partner["id"])
    priced_b = read_request(client, request_b["id"])
    assert priced_b["gross_charge_cents"] == 6001
    assert priced_b["subsidy_cents"] == 2400
    assert priced_b["net_patron_charge_cents"] == 3601
    assert priced_b["rush_surcharge_cents"] == 0

    assert read_patron(client, patron["id"])["pending_charge_cents"] == 6001


def test_partial_payment_walks_the_pinned_bucket_order_and_refuses_overpayment(client):
    """A partial payment fills overdue before damage, an excessive payment writes
    nothing at all, and an exact payment settles the loan.

    PRD: "If `payment_cents` exceeds that total remaining, the call fails with
    `ERR_OVERPAYMENT` and **nothing whatever is written**: no bucket is partially
    filled, no field changes, and the caller must re-send a correct amount."

    Design: Corner/calculations/partial_payment_fills_the_overdue_bucket_before_the_damage_bucket_and_rejects_overpayment
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9024",
        full_name="Uma Reader",
        email="uma@u.edu",
        patron_type="GRAD",
        department="ARCH",
        unpaid_balance_cap_cents=20000,
    )
    partner = create_partner(
        client,
        code="SHORTL",
        name="Short Loan Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=7,
        max_renewals=1,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Timber Frame Details",
        item_type=ItemType.BOOK,
        publication_year=2012,
        isbn="978-0-000-00044-8",
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    accept_offer(client, offer["id"], partner["id"])
    shipment = ship_item(
        client, offer["id"], partner["id"], carrier="UPS", tracking_code="1Z-SL-0094"
    )
    loan = receive_shipment(client, shipment["id"])
    pickup_loan(client, loan["id"])

    set_clock(client, "2026-08-15T00:00:00Z")
    returned = return_loan(client, loan["id"])
    assert returned["overdue_fine_cents"] == 750

    parcels = list_request_shipments(
        client, request["id"], params={"direction": ShipmentDirection.RETURN}
    )
    return_parcel = parcels[0]

    set_clock(client, "2026-08-16T00:00:00Z")
    lender_confirm(
        client,
        return_parcel["id"],
        partner["id"],
        condition=ShipmentCondition.DAMAGED,
        damage_fee_cents=3000,
    )

    billed = read_loan(client, loan["id"])
    assert billed["damage_fee_cents"] == 3000
    assert billed["lender_processing_fee_cents"] == 2500
    assert billed["lost_replacement_cents"] == 0
    assert billed["total_charge_cents"] == 6250

    first = settle_loan_charge(client, loan["id"], F.pay_settlement_payload(1000))
    assert first["paid_overdue_cents"] == 750
    assert first["paid_damage_cents"] == 250
    assert first["paid_processing_cents"] == 0
    assert first["outstanding_cents"] == 5250
    assert first["billing_status"] == BillingStatus.DAMAGE_BILLED

    validate_error(
        client.create_charge_settlement(
            loan["id"],
            F.pay_settlement_payload(5251),
            headers=make_accountant_headers(),
        ),
        ApiErrorId.OVERPAYMENT,
        expected_status=422,
    )

    untouched = read_loan(client, loan["id"])
    assert untouched["paid_overdue_cents"] == 750
    assert untouched["paid_damage_cents"] == 250
    assert untouched["outstanding_cents"] == 5250

    final = settle_loan_charge(client, loan["id"], F.pay_settlement_payload(5250))
    assert final["outstanding_cents"] == 0
    assert final["total_paid_cents"] == 6250
    assert final["billing_status"] == BillingStatus.CHARGE_SETTLED
    assert final["paid_damage_cents"] == 3000
    assert final["paid_processing_cents"] == 2500

    settled_patron = read_patron(client, patron["id"])
    assert settled_patron["unpaid_balance_cents"] == 0
    assert settled_patron["damaged_count"] == 1


def test_invoice_period_window_is_half_open_on_the_charge_instant(client):
    """Only the charge on the lower edge of the month is drafted; the one on the
    upper edge belongs to the following period.

    PRD: "The period window is **half-open**: `period_start` is the first instant of
    that month in UTC and `period_end` is the first instant of the following month,
    and a line qualifies when its instant is at or after `period_start` and strictly
    before `period_end`."

    Design: Corner/calculations/invoice_period_window_is_half_open_on_the_lending_charge_instant
    """
    set_clock(client, CLOCK_START_ISO)
    set_clock(client, "2026-09-01T00:00:00Z")
    partner = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    charge_before = create_lending_charge(
        client,
        partner["id"],
        item_title="Before the window",
        service_type=ServiceType.LOAN,
        charge_cents=3000,
        incurred_at="2026-07-31T00:00:00.000Z",
    )
    create_lending_charge(
        client,
        partner["id"],
        item_title="On the lower edge",
        service_type=ServiceType.LOAN,
        charge_cents=2000,
        incurred_at="2026-08-01T00:00:00.000Z",
    )
    charge_after = create_lending_charge(
        client,
        partner["id"],
        item_title="On the upper edge",
        service_type=ServiceType.COPY,
        charge_cents=1200,
        incurred_at="2026-09-01T00:00:00.000Z",
    )

    assert read_partner(client, partner["id"])["lend_receivable_cents"] == 6200

    invoice = draft_invoice(client, partner["id"], "2026-08")

    assert invoice["lend_line_count"] == 1
    assert invoice["borrow_line_count"] == 0
    assert invoice["receivable_total_cents"] == 2150
    assert invoice["payable_total_cents"] == 0
    assert invoice["gross_amount_cents"] == 0
    assert invoice["settlement_variant"] == SettlementMode.GROSS
    assert invoice["net_amount_cents"] == 0
    assert invoice["direction"] == InvoiceDirection.PAYABLE
    assert invoice["status"] == InvoiceStatus.DRAFT
    assert invoice["period_month"] == "2026-08"

    for excluded in (charge_before, charge_after):
        row = validate_success(
            client.get_lending_charge(excluded["id"], headers=make_accountant_headers())
        )
        assert row["status"] == "OPEN"


def test_redrafting_an_invoice_supersedes_the_first_and_adds_the_line_delta(client):
    """A second draft for the same month replaces the first and carries the newly
    surcharged line, with the negative net flipping the direction.

    PRD: "Drafting is guarded by optimistic concurrency on the parent partner as
    §2.7 requires, and it supersedes rather than duplicates: any existing invoice for
    the same partner and the same `period_month` that is still at `DRAFT` moves to
    `SUPERSEDED`, and the new draft replaces it."

    Design: Corner/calculations/regenerating_a_draft_invoice_supersedes_the_first_and_reapplies_the_new_line_delta
    """
    set_clock(client, CLOCK_START_ISO)
    partner = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    agreement = create_agreement(
        client,
        partner["id"],
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2026-10-01T00:00:00.000Z",
        fee_waiver_mode="NONE",
        settlement_mode=SettlementMode.NET,
        turnaround_guarantee_days=7,
        balance_tolerance_items=3,
    )
    assert agreement["status"] == "ACTIVE"

    create_lending_charge(
        client,
        partner["id"],
        item_title="First lend line",
        service_type=ServiceType.LOAN,
        charge_cents=2000,
        incurred_at="2026-08-05T00:00:00.000Z",
    )
    set_clock(client, "2026-09-01T00:00:00Z")

    version_one = partner_version(client, partner["id"])
    first = draft_invoice(client, partner["id"], "2026-08", version_one)
    assert first["settlement_variant"] == SettlementMode.NET
    assert first["lend_line_count"] == 1
    assert first["receivable_total_cents"] == 2150
    assert first["net_amount_cents"] == -2150
    assert first["direction"] == InvoiceDirection.RECEIVABLE

    create_lending_charge(
        client,
        partner["id"],
        item_title="Second lend line",
        service_type=ServiceType.COPY,
        charge_cents=1200,
        incurred_at="2026-08-06T00:00:00.000Z",
    )
    version_two = partner_version(client, partner["id"])
    assert version_two == version_one + 2

    second = draft_invoice(client, partner["id"], "2026-08", version_two)
    assert second["lend_line_count"] == 2
    assert second["receivable_total_cents"] == 3440
    assert second["net_amount_cents"] == -3440
    assert second["direction"] == InvoiceDirection.RECEIVABLE
    assert second["status"] == InvoiceStatus.DRAFT

    superseded = validate_success(
        client.get_invoice(first["id"], headers=make_accountant_headers())
    )
    assert superseded["status"] == InvoiceStatus.SUPERSEDED

    rows, meta = validate_paginated(
        client.list_partner_invoices(
            partner["id"],
            headers=make_accountant_headers(),
            params={"period_month": "2026-08"},
        )
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows].count(InvoiceStatus.DRAFT) == 1

    assert read_partner(client, partner["id"])["lend_receivable_cents"] == 3200


def test_standing_score_blocks_at_forty_and_admits_at_thirty_nine(client):
    """The weighted base is compared inclusively against the block threshold, so a
    score of exactly 40 is refused while 39 is admitted.

    PRD: "The base is the sum of five terms: 25 points for each entry in
    `lost_count`, 12 points for each entry in `damaged_count`, 6 points for each
    entry in `late_return_count`, 8 points for each entry in `unclaimed_count`, and
    one further point for each whole 1000 cents — each whole ten dollars — of
    `unpaid_balance_cents`, taking the floor of that division so that a balance of
    1999 cents contributes exactly one point."

    Design: Corner/calculations/standing_score_blocks_intake_at_forty_and_admits_at_thirty_nine
    """
    set_clock(client, CLOCK_START_ISO)
    blocky = create_patron(
        client,
        external_id="P-BLOCKY",
        full_name="Vic Blocky",
        email="vic@u.edu",
        patron_type="UNDERGRAD",
        department="PSYC",
        unpaid_balance_cap_cents=20000,
    )
    load_infraction(client, blocky["id"], "LOST", count=1)
    load_infraction(client, blocky["id"], "DAMAGED", count=1)
    scored_blocky = load_infraction(
        client, blocky["id"], "UNPAID_CHARGE", unpaid_amount_cents=3000
    )
    assert scored_blocky["provisional_risk_score"] == 40
    assert scored_blocky["final_risk_score"] == 40
    assert scored_blocky["status"] == PatronStatus.ACTIVE

    admity = create_patron(
        client,
        external_id="P-ADMITY",
        full_name="Wes Admity",
        email="wes@u.edu",
        patron_type="UNDERGRAD",
        department="PSYC",
        unpaid_balance_cap_cents=20000,
    )
    load_infraction(client, admity["id"], "LOST", count=1)
    load_infraction(client, admity["id"], "DAMAGED", count=1)
    scored_admity = load_infraction(
        client, admity["id"], "UNPAID_CHARGE", unpaid_amount_cents=2000
    )
    assert scored_admity["provisional_risk_score"] == 39

    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Cognition and Memory",
        item_type=ItemType.BOOK,
        publication_year=2017,
        isbn="978-0-000-00045-5",
        list_price_cents=9000,
    )

    validate_error(
        client.create_request(
            F.request_payload(
                blocky["id"],
                bib_item["id"],
                rota["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.PATRON_STANDING_BLOCKED,
        expected_status=403,
    )

    assert read_patron(client, blocky["id"])["open_request_count"] == 0
    _rows, blocked_meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(), params={"patron_id": blocky["id"]}
        )
    )
    assert blocked_meta["total_count"] == 0

    admitted = intake_request(
        client,
        admity["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert admitted["status"] == RequestStatus.SOURCING

    admitted_patron = read_patron(client, admity["id"])
    assert admitted_patron["open_request_count"] == 1
    assert admitted_patron["provisional_risk_score"] == 39


def test_licensed_access_covers_the_work_only_once_the_embargo_has_lapsed(client):
    """A twelve-month embargo converts to one whole year, so the previous year's
    article is already covered while this year's is not.

    PRD: "That second test reads the record's licensed-access state: a record at
    `NONE` is not covered; a record at `LICENSED_FULL` is covered outright; and a
    record at `LICENSED_EMBARGOED` is covered when its `publication_year` is at or
    before the current calendar year of the logical clock minus the embargo expressed
    in whole years, where the embargo in years is `embargo_months` divided by 12 and
    rounded **up** to a whole year — so an embargo of anywhere from 1 to 12 months
    costs one year, 13 to 24 months costs two, and so on."

    Design: Corner/calculations/licensed_electronic_access_blocks_a_request_only_once_the_embargo_has_lapsed
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9026",
        full_name="Xan Reader",
        email="xan@u.edu",
        patron_type="FACULTY",
        department="BIOL",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=1500,
        avg_turnaround_days=2,
        supplies_electronic=True,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.COPY, max_attempts=3)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=1500,
        quoted_turnaround_days=2,
    )
    lapsed = create_article_bib_item(
        client,
        issn="4444-0001",
        title="Ribosome assembly in vitro",
        publication_year=2025,
        journal_title="Cell Reports Weekly",
        licensed_access_status=LicensedAccessStatus.LICENSED_EMBARGOED,
        embargo_months=12,
        list_price_cents=4000,
    )
    still_embargoed = create_article_bib_item(
        client,
        issn="4444-0002",
        title="Ribosome assembly in vivo",
        publication_year=2026,
        journal_title="Cell Reports Weekly",
        licensed_access_status=LicensedAccessStatus.LICENSED_EMBARGOED,
        embargo_months=12,
        list_price_cents=4000,
    )

    validate_error(
        client.create_request(
            F.copy_request_payload(
                patron["id"],
                lapsed["id"],
                rota["id"],
                pages_requested=10,
                needed_by="2026-08-20T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.LICENSED_ACCESS_AVAILABLE,
        expected_status=422,
    )

    admitted = intake_copy_request(
        client,
        patron["id"],
        still_embargoed["id"],
        rota["id"],
        pages_requested=10,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert admitted["status"] == RequestStatus.SOURCING

    refused_usage = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "4444-0001", "calendar_year": 2026},
        )
    )
    assert refused_usage["counted_fill_count"] == 0

    admitted_usage = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "4444-0002", "calendar_year": 2026},
        )
    )
    assert admitted_usage["counted_fill_count"] == 1
    assert admitted_usage["free_fills_remaining"] == 4

    rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(), params={"patron_id": patron["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [admitted["id"]]
    assert read_patron(client, patron["id"])["open_request_count"] == 1
