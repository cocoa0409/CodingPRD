"""Order of operations inside two aggregates: the subsidy tier lookup inside the patron
charge, and the surcharge rounding inside the partner invoice."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_bib_item,
    create_lending_charge,
    create_partner,
    create_patron,
    create_rota,
    draft_invoice,
    intake_request,
    read_partner,
    read_patron,
    read_request,
    run_rota_round,
    set_clock,
)
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.test_users import make_accountant_headers
from test_helpers.types import (
    InvoiceDirection,
    InvoiceStatus,
    ItemType,
    LendingChargeStatus,
    MaterialType,
    OfferStatus,
    RequestStatus,
    SettlementMode,
)


def _rush_request_offered_at_two_thousand_cents(client):
    """A committed-fee-2000 offer standing open against a deadline three days out."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8003",
        full_name="Cara Undergrad",
        email="cara@u.edu",
        patron_type="UNDERGRAD",
        department="HIST",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
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
        needed_by="2026-08-04T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    return {"patron": patron, "partner": partner, "request": request, "offer": offer}


def test_the_subsidy_tier_is_read_from_the_gross_figure_and_not_from_the_net(client):
    """A 2000-cent fee plus a 1200-cent rush grosses at 3200, which sits in the second
    tier; reading the same table off the resulting net would subsidise 640 cents more.

    PRD: "**Fifth**, the departmental subsidy rate is looked up **from the gross figure,
    never from the net**: a gross at or below 2000 cents subsidises at 0.80, a gross from
    2001 through 6000 cents at 0.60, a gross from 6001 through 12000 cents at 0.40, and a
    gross strictly above 12000 cents at 0.25." And: "**Seventh and last**,
    `net_patron_charge_cents` is `gross_charge_cents` minus `subsidy_cents`."

    Design: Difficulty/combinatorial_formula/charge_assembly_subsidy_tier_keyed_on_gross_not_on_post_subsidy_net
    """
    world = _rush_request_offered_at_two_thousand_cents(client)
    accepted = accept_offer(client, world["offer"]["id"], world["partner"]["id"])
    assert accepted["status"] == OfferStatus.ACCEPTED

    priced = read_request(client, world["request"]["id"])
    assert priced["committed_fee_cents"] == 2000
    assert priced["rush_surcharge_cents"] == 1200
    assert priced["royalty_cents"] == 0
    assert priced["gross_charge_cents"] == 3200
    assert priced["subsidy_cents"] == 1920
    assert priced["net_patron_charge_cents"] == 1280
    assert priced["net_patron_charge_cents"] != 640
    assert priced["subsidy_cents"] != 2560
    assert (
        priced["net_patron_charge_cents"]
        == priced["gross_charge_cents"] - priced["subsidy_cents"]
    )
    assert priced["status"] == RequestStatus.SUPPLY_COMMITTED

    charged = read_patron(client, world["patron"]["id"])
    assert charged["pending_charge_cents"] == 1280


def test_the_three_terms_that_build_the_gross_figure_are_each_visible_on_the_way(client):
    """The base, the rush term and the royalty term are each observable before the tier is
    chosen, and the lateness penalty that ranked the lender is not one of them.

    PRD: "**Second**, the rush surcharge: when the request's `days_available_at_source` is
    at most 3 days, `rush_surcharge_cents` is 1200 cents, and otherwise it is 0 — a request
    accepted with three days of runway is a rush, one with four days is not." And: "The
    landed cost of a candidate is therefore its effective fee, plus 250 cents multiplied by
    its late days, plus the imbalance penalty where it applies." And: "**Fourth**,
    `gross_charge_cents` is the sum of those three: base plus rush plus royalty."

    Design: Difficulty/combinatorial_formula/charge_assembly_subsidy_tier_keyed_on_gross_not_on_post_subsidy_net
    """
    world = _rush_request_offered_at_two_thousand_cents(client)
    offer = world["offer"]
    assert offer["status"] == OfferStatus.OFFERED
    assert offer["quoted_fee_cents"] == 2000
    assert offer["effective_fee_cents"] == 2000
    assert offer["imbalance_penalty_cents"] == 0
    assert offer["landed_cost_cents"] == 2250

    sourced = read_request(client, world["request"]["id"])
    assert sourced["days_available_at_source"] == 3
    assert sourced["gross_charge_cents"] == 0
    assert sourced["subsidy_cents"] == 0

    accept_offer(client, offer["id"], world["partner"]["id"])
    priced = read_request(client, world["request"]["id"])
    assert priced["days_available_at_source"] == 3
    assert priced["committed_fee_cents"] == offer["effective_fee_cents"]
    assert (
        priced["gross_charge_cents"]
        == priced["committed_fee_cents"]
        + priced["rush_surcharge_cents"]
        + priced["royalty_cents"]
    )
    assert priced["gross_charge_cents"] == 3200
    assert priced["gross_charge_cents"] != offer["landed_cost_cents"]
    assert priced["subsidy_cents"] == 1920
    assert priced["subsidy_cents"] < 4000


def _partner_with_three_lend_lines(client):
    """Three open lend lines of 2000, 2500 and 3333 cents inside 2026-08, no agreement."""
    set_clock(client, "2026-08-25T00:00:00.000Z")
    partner = create_partner(
        client,
        code="SOUTHC",
        name="South College Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=1200,
        avg_turnaround_days=9,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    lines = (
        ("Thermodynamics 4e", 2000, "2026-08-02T00:00:00.000Z"),
        ("Journal of Optics scan", 2500, "2026-08-11T00:00:00.000Z"),
        ("Rare Maps folio", 3333, "2026-08-19T00:00:00.000Z"),
    )
    charges = [
        create_lending_charge(
            client,
            partner["id"],
            item_title=title,
            charge_cents=charge_cents,
            incurred_at=incurred_at,
        )
        for title, charge_cents, incurred_at in lines
    ]
    return {"partner": partner, "charges": charges}


def test_each_lend_line_is_surcharged_and_rounded_before_the_lines_are_summed(client):
    """Lines of 2000, 2500 and 3333 cents surcharge to 2150, 2688 and 3583, which total
    8421; surcharging the 7833-cent sum once and rounding that would report 8420.

    PRD: "Each line is then surcharged by the 7.5 percent consortium administration levy:
    the surcharged value of a line is the line amount plus that amount multiplied by 0.075,
    rounded half up to whole cents." And: "**The rounding order is pinned: round each line,
    then sum the rounded values.**"

    Design: Difficulty/combinatorial_formula/invoice_consortium_surcharge_rounded_per_line_before_summation
    """
    world = _partner_with_three_lend_lines(client)
    invoice = draft_invoice(client, world["partner"]["id"], "2026-08")
    assert invoice["lend_line_count"] == 3
    assert invoice["borrow_line_count"] == 0
    assert invoice["receivable_total_cents"] == 8421
    assert invoice["receivable_total_cents"] != 8420
    assert invoice["receivable_total_cents"] - (2000 + 2500 + 3333) == 588
    assert invoice["status"] == InvoiceStatus.DRAFT


def test_the_untaxed_lend_receivable_is_conserved_while_the_invoice_reports_the_levy(
    client,
):
    """The invoice reports the surcharged figure, the partner keeps reporting the raw one,
    and with no agreement on file the draft defaults to the gross variant with no borrow
    side at all.

    PRD: "Which variant produced the amounts is recorded in `settlement_variant`, taken
    from the `settlement_mode` of the partner's applicable active agreement selected by
    §3.2's rule, defaulting to `GROSS` when no agreement applies." And:
    "`lend_receivable_cents` is the sum of `charge_cents` over that partner's lending
    charges whose `status` is still `OPEN`."

    Design: Difficulty/combinatorial_formula/invoice_consortium_surcharge_rounded_per_line_before_summation
    """
    world = _partner_with_three_lend_lines(client)
    partner = world["partner"]
    before = read_partner(client, partner["id"])
    assert before["lend_receivable_cents"] == 7833
    assert before["lent_to_count"] == 3

    invoice = draft_invoice(client, partner["id"], "2026-08")
    assert invoice["settlement_variant"] == SettlementMode.GROSS
    assert invoice["payable_total_cents"] == 0
    assert invoice["gross_amount_cents"] == 0
    assert invoice["net_amount_cents"] == 0
    assert invoice["direction"] == InvoiceDirection.PAYABLE
    assert invoice["receivable_total_cents"] == 8421

    after = read_partner(client, partner["id"])
    assert after["lend_receivable_cents"] == 7833
    assert after["lend_receivable_cents"] != invoice["receivable_total_cents"]

    rows, meta = validate_paginated(
        client.list_partner_lending_charges(
            partner["id"],
            headers=make_accountant_headers(),
            params={"status": LendingChargeStatus.OPEN},
        )
    )
    assert meta["total_count"] == 3
    assert sum(row["charge_cents"] for row in rows) == 7833
