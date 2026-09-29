"""Two shared bases with two deliberately disagreeing variants: the settlement
reconciliation of a partner invoice, and the standing score of a patron."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_agreement,
    create_bib_item,
    create_lending_charge,
    create_partner,
    create_patron,
    create_rota,
    draft_invoice,
    intake_request,
    load_infraction,
    partner_version,
    pickup_loan,
    read_loan,
    read_patron,
    read_request,
    receive_shipment,
    run_ops,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import (
    make_accountant_headers,
    make_admin_headers,
)
from test_helpers.types import (
    AgreementStatus,
    CustodyStatus,
    FeeWaiverMode,
    InfractionKind,
    InvoiceDirection,
    InvoiceStatus,
    ItemType,
    MaterialType,
    PatronStatus,
    RequestStatus,
    SettlementMode,
)


def _partner_with_two_borrow_lines_and_two_lend_lines(client, settlement_mode):
    """One partner, two fulfilled borrow lines of 2000 and 1200 cents, and two open
    lend lines of 2500 and 3333 cents, all inside the 2026-08 settlement period."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8001",
        full_name="Ada Faculty",
        email="ada@u.edu",
        patron_type="FACULTY",
        department="PHYS",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=100000,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    agreement = create_agreement(
        client,
        partner["id"],
        fee_waiver_mode=FeeWaiverMode.NONE,
        settlement_mode=settlement_mode,
        turnaround_guarantee_days=5,
        balance_tolerance_items=3,
        effective_from="2026-01-01T00:00:00.000Z",
        effective_to="2027-01-01T00:00:00.000Z",
    )
    bib_item = create_bib_item(
        client,
        title="Structural Dynamics",
        item_type=ItemType.BOOK,
        publication_year=2019,
        isbn="978-0-000-00001-1",
        list_price_cents=9000,
    )

    requests = []
    for quoted_fee_cents, rota_name in ((2000, "Monograph rota A"), (1200, "Monograph rota B")):
        rota = create_rota(
            client,
            name=rota_name,
            material_type=MaterialType.LOAN,
            max_attempts=3,
            auto_escalate_pod=False,
            offer_response_hours=48,
        )
        add_rota_entry(
            client,
            rota["id"],
            partner["id"],
            manual_rank=1,
            quoted_fee_cents=quoted_fee_cents,
            quoted_turnaround_days=4,
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
            client,
            offer["id"],
            partner["id"],
            carrier="UPS",
            insured_value_cents=9000,
        )
        receive_shipment(client, shipment["id"])
        requests.append(read_request(client, request["id"]))

    assert [request["committed_fee_cents"] for request in requests] == [2000, 1200]
    for request in requests:
        assert_same_instant(request["fulfilled_at"], CLOCK_START_ISO)

    set_clock(client, "2026-08-25T00:00:00.000Z")
    create_lending_charge(
        client,
        partner["id"],
        item_title="Fluid Mechanics vol 2",
        charge_cents=2500,
        incurred_at="2026-08-05T00:00:00.000Z",
    )
    create_lending_charge(
        client,
        partner["id"],
        item_title="Optics Letters scan",
        charge_cents=3333,
        incurred_at="2026-08-20T00:00:00.000Z",
    )
    return {
        "patron": patron,
        "partner": partner,
        "agreement": agreement,
        "bib_item": bib_item,
        "requests": requests,
    }


def test_the_net_settlement_variant_makes_the_partner_the_creditor_over_these_lines(
    client,
):
    """Over two borrow lines and two lend lines the netting variant subtracts the lend
    side, so the sign of the reported balance turns and the direction follows it.

    PRD: "Under the `NET` variant `net_amount_cents` is `payable_total_cents` minus
    `receivable_total_cents`, which may well be negative." And: "`direction` follows from
    that figure: `PAYABLE` when `net_amount_cents` is at or above 0, meaning we owe the
    partner, and `RECEIVABLE` when it is negative, meaning the partner owes us."

    Design: Difficulty/dual_variant_calc/invoice_net_variant_flips_direction_where_gross_variant_bills_the_borrower
    """
    world = _partner_with_two_borrow_lines_and_two_lend_lines(client, SettlementMode.NET)
    partner = world["partner"]

    invoice = draft_invoice(client, partner["id"], "2026-08")
    assert invoice["settlement_variant"] == SettlementMode.NET
    assert invoice["borrow_line_count"] == 2
    assert invoice["lend_line_count"] == 2
    assert invoice["payable_total_cents"] == 3440
    assert invoice["receivable_total_cents"] == 6271
    assert invoice["gross_amount_cents"] == 3440
    assert invoice["net_amount_cents"] == -2831
    assert invoice["direction"] == InvoiceDirection.RECEIVABLE
    assert invoice["status"] == InvoiceStatus.DRAFT
    assert (
        invoice["net_amount_cents"]
        == invoice["payable_total_cents"] - invoice["receivable_total_cents"]
    )


def test_the_gross_variant_bills_the_whole_borrow_total_over_the_identical_lines(client):
    """The same month of lines is redrafted under a superseding agreement whose only
    difference is the settlement mode, and the party that owes money changes.

    PRD: "Under the `GROSS` variant `net_amount_cents` is also `payable_total_cents`: the
    lend side is still reported in `receivable_total_cents` for information, but it is not
    netted off, so the borrower pays its full borrow total and the lending side is
    invoiced separately." And: "`gross_amount_cents` is **always**
    `payable_total_cents`, identically in both variants."

    Design: Difficulty/dual_variant_calc/invoice_net_variant_flips_direction_where_gross_variant_bills_the_borrower
    """
    world = _partner_with_two_borrow_lines_and_two_lend_lines(client, SettlementMode.NET)
    partner = world["partner"]

    net_invoice = draft_invoice(client, partner["id"], "2026-08")
    assert net_invoice["settlement_variant"] == SettlementMode.NET

    gross_agreement = create_agreement(
        client,
        partner["id"],
        supersedes_agreement_id=world["agreement"]["id"],
        fee_waiver_mode=FeeWaiverMode.NONE,
        settlement_mode=SettlementMode.GROSS,
        turnaround_guarantee_days=5,
        balance_tolerance_items=3,
        effective_from="2026-01-01T00:00:00.000Z",
        effective_to="2027-01-01T00:00:00.000Z",
    )
    assert gross_agreement["status"] == AgreementStatus.ACTIVE

    gross_invoice = draft_invoice(
        client, partner["id"], "2026-08", partner_version(client, partner["id"])
    )
    assert gross_invoice["settlement_variant"] == SettlementMode.GROSS
    assert gross_invoice["borrow_line_count"] == 2
    assert gross_invoice["lend_line_count"] == 2
    assert gross_invoice["payable_total_cents"] == 3440
    assert gross_invoice["receivable_total_cents"] == 6271
    assert gross_invoice["gross_amount_cents"] == 3440
    assert gross_invoice["net_amount_cents"] == 3440
    assert gross_invoice["direction"] == InvoiceDirection.PAYABLE
    assert gross_invoice["status"] == InvoiceStatus.DRAFT

    superseded = validate_success(
        client.get_invoice(net_invoice["id"], headers=make_accountant_headers())
    )
    assert superseded["status"] == InvoiceStatus.SUPERSEDED
    assert superseded["gross_amount_cents"] == gross_invoice["gross_amount_cents"]
    assert (
        gross_invoice["net_amount_cents"] - superseded["net_amount_cents"]
        == superseded["receivable_total_cents"]
    )

    replaced = validate_success(
        client.get_agreement(world["agreement"]["id"], headers=make_admin_headers())
    )
    assert replaced["status"] == AgreementStatus.SUPERSEDED


def _patron_with_migrated_history(client):
    """A patron carrying one migrated loss, one migrated late return and 5000 cents of
    migrated unpaid charges, sitting exactly on the fiscal cap."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8002",
        full_name="Ben Grad",
        email="ben@u.edu",
        patron_type="GRAD",
        department="CHEM",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    load_infraction(client, patron["id"], InfractionKind.LOST, count=1)
    load_infraction(client, patron["id"], InfractionKind.LATE_RETURN, count=1)
    loaded = load_infraction(
        client, patron["id"], InfractionKind.UNPAID_CHARGE, unpaid_amount_cents=5000
    )
    return loaded


def test_the_provisional_standing_variant_admits_an_intake_at_thirty_six_points(client):
    """The shared base is 36 over one loss, one late return and 5000 cents unpaid, and the
    variant intake consults is exactly that base, so the request is taken in.

    PRD: "The base is the sum of five terms: 25 points for each entry in `lost_count`, 12
    points for each entry in `damaged_count`, 6 points for each entry in
    `late_return_count`, 8 points for each entry in `unclaimed_count`, and one further
    point for each whole 1000 cents — each whole ten dollars — of `unpaid_balance_cents`,
    taking the floor of that division so that a balance of 1999 cents contributes exactly
    one point." And: "It is stored on the patron as `provisional_risk_score`, and intake is
    refused with `ERR_PATRON_STANDING_BLOCKED` when it reaches 40 or more."

    Design: Difficulty/dual_variant_calc/patron_standing_provisional_admits_intake_that_final_variant_blocks
    """
    patron = _patron_with_migrated_history(client)
    assert patron["lost_count"] == 1
    assert patron["late_return_count"] == 1
    assert patron["damaged_count"] == 0
    assert patron["unclaimed_count"] == 0
    assert patron["unpaid_balance_cents"] == 5000
    assert patron["provisional_risk_score"] == 36
    assert patron["final_risk_score"] == 36
    assert patron["status"] == PatronStatus.ACTIVE

    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Structural Dynamics",
        item_type=ItemType.BOOK,
        publication_year=2019,
        isbn="978-0-000-00001-1",
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
    assert request["status"] == RequestStatus.SOURCING

    after_intake = read_patron(client, patron["id"])
    assert after_intake["provisional_risk_score"] == 36
    assert after_intake["status"] == PatronStatus.ACTIVE
    assert after_intake["open_request_count"] == 1


def test_the_final_standing_variant_scores_the_same_data_at_forty_two_and_blocks(client):
    """Nothing about the stored history changes, but the sweep's variant adds the in-flight
    overdue term for the item the patron is still holding, which crosses the threshold.

    PRD: "The **final** variant is evaluated by the operational sweep, after every billing
    side effect of the night has landed, and takes the base, adds 6 points for each of that
    patron's loans that is still in custody `WITH_PATRON` with the logical clock strictly
    past its `due_at`, subtracts 4 points for each of that patron's loans in custody
    `RETURNED_TO_LENDER` whose `overdue_fine_cents` is exactly 0, and clamps the result
    into 0 to 100 inclusive after those two adjustments have been applied." And: "It is
    stored as `final_risk_score`, and a patron whose `final_risk_score` reaches 40 or more
    has their `status` set to `BLOCKED`."

    Design: Difficulty/dual_variant_calc/patron_standing_provisional_admits_intake_that_final_variant_blocks
    """
    patron = _patron_with_migrated_history(client)
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Structural Dynamics",
        item_type=ItemType.BOOK,
        publication_year=2019,
        isbn="978-0-000-00001-1",
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
        client, offer["id"], partner["id"], carrier="UPS", insured_value_cents=9000
    )
    loan = receive_shipment(client, shipment["id"])
    loan = pickup_loan(client, loan["id"])
    assert loan["custody_status"] == CustodyStatus.WITH_PATRON
    assert_same_instant(loan["due_at"], "2026-08-29T00:00:00.000Z")

    set_clock(client, "2026-09-05T00:00:00.000Z")
    summary = run_ops(client)
    assert summary["patrons_blocked"] == 1

    scored = read_patron(client, patron["id"])
    assert scored["lost_count"] == 1
    assert scored["late_return_count"] == 1
    assert scored["unpaid_balance_cents"] == 5000
    assert scored["provisional_risk_score"] == 36
    assert scored["final_risk_score"] == 42
    assert scored["final_risk_score"] - scored["provisional_risk_score"] == 6
    assert scored["status"] == PatronStatus.BLOCKED

    still_out = read_loan(client, loan["id"])
    assert still_out["custody_status"] == CustodyStatus.WITH_PATRON
    assert read_request(client, request["id"])["status"] == RequestStatus.WITH_PATRON
