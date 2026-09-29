"""Buyout pricing at title clearance and the fan-out of a closing.

The payoff variant is chosen by `transfer_type` alone, so two agreements with
byte-identical economics are quoted two very different figures. Closing then
propagates: the case closes, the agreement closes, every surviving lien is
terminated as a cascade, and the closed agreement stops accepting production.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_credit_counters
from test_helpers.fixtures import (
    activate,
    book_ppa,
    clear_title,
    close_transfer,
    make_buyer,
    make_filing,
    make_homeowner,
    make_tariff,
    open_assumption,
    open_prepayment,
    open_relocation,
    read_agreement,
    record_period,
    run_credit_review,
    set_clock,
)

# The priced terms. A 7.20 kW system at 320000 cents per kilowatt is worth
# 2304000 cents installed, and a 240-month term elapses 20 months by a
# 2026-09-01 closing.
PRICED_TERMS = {
    "term_years": 20,
    "contract_start_date": "2025-01-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "system_dc_kw": 7.2,
    "guarantee_band_pct": 0.05,
}
NPV_QUOTE_CENTS = 2090599
# What a single rounding of the summed buckets would have produced instead.
NPV_QUOTE_IF_ROUNDED_ONCE = 2090598
UNAMORTIZED_QUOTE_CENTS = 2962000
NEW_SITE = "440 Juniper Ct, Fremont, CA"


def _active_ppa(api, homeowner_id, tariff_id, **overrides):
    terms = dict(PRICED_TERMS)
    terms.update(overrides)
    agreement = book_ppa(api, homeowner_id, tariff_id, **terms)
    activate(api, agreement["id"])
    return read_agreement(api, agreement["id"])


def _one_active_ppa(api, clock="2026-08-01T00:00:00Z", **overrides):
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    return owner, _active_ppa(api, owner["id"], schedule["id"], **overrides)


def _two_active_ppas(api, clock="2026-08-01T00:00:00Z"):
    """Identically priced twins under one homeowner, differing only by address."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    first = _active_ppa(api, owner["id"], schedule["id"])
    second = _active_ppa(
        api,
        owner["id"],
        schedule["id"],
        site_address="922 Alder Way, Fremont, CA",
    )
    return owner, first, second


def _read_filing(api, ucc_filing_id):
    return validate_success(
        api.get_ucc_filing(ucc_filing_id, U.title_headers()), 200
    )


def test_two_identical_agreements_are_quoted_by_transfer_type_alone(api):
    """The same closing date and the same hardware, priced 871401 cents apart.

    §3.8: "The `payoff_method` a case uses is determined by its `transfer_type`
    and is not a caller choice: `ASSUMPTION` uses `NONE`, `PREPAYMENT` uses
    `NPV_REMAINING_PAYMENTS`, and `RELOCATION` uses `UNAMORTIZED_SYSTEM_COST`."
    §3.8: "The installed cost is the agreement's `system_dc_kw` multiplied by 320000
    cents per kilowatt and rounded to a whole cent. The unamortized fraction is one
    minus `elapsed_term_months` divided by the total term in months, floored at zero
    and carried at full precision with no intermediate rounding. `payoff_quote_cents`
    is the installed cost multiplied by that fraction, rounded to a whole cent, plus a
    flat relocation and re-permitting fee of 850000 cents." §3.8: "for a `RELOCATION`
    only — moves the agreement's asset dimension `IN_SERVICE → DECOMMISSION_PENDING`".

    Design: Difficulty/dual_variant_calc/payoff_npv_vs_unamortized_diverge_on_identical_terms
    """
    _, bought_out, relocating = _two_active_ppas(api)

    prepayment = clear_title(
        api, open_prepayment(api, bought_out["id"], "2026-09-01")["id"]
    )
    relocation = clear_title(
        api,
        open_relocation(
            api, relocating["id"], "2026-09-01", new_site_address=NEW_SITE
        )["id"],
    )

    assert prepayment["status"] == C.TRANSFER_TITLE_CLEARED
    assert prepayment["elapsed_term_months"] == 20
    assert prepayment["remaining_term_months"] == 220
    assert prepayment["payoff_method"] == C.PAYOFF_NPV
    assert prepayment["payoff_quote_cents"] == NPV_QUOTE_CENTS
    assert prepayment["buyer_homeowner_id"] is None
    assert prepayment["new_site_address"] is None

    assert relocation["status"] == C.TRANSFER_TITLE_CLEARED
    assert relocation["elapsed_term_months"] == 20
    assert relocation["remaining_term_months"] == 220
    assert relocation["payoff_method"] == C.PAYOFF_UNAMORTIZED
    assert relocation["payoff_quote_cents"] == UNAMORTIZED_QUOTE_CENTS

    assert (
        relocation["payoff_quote_cents"] - prepayment["payoff_quote_cents"] == 871401
    )
    assert (
        read_agreement(api, relocating["id"])["service_status"]
        == C.SERVICE_DECOMMISSION_PENDING
    )
    assert (
        read_agreement(api, bought_out["id"])["service_status"] == C.SERVICE_IN_SERVICE
    )


def test_the_npv_quote_rounds_each_bucket_before_it_sums(api):
    """Nineteen buckets, each rounded on its own, land one cent above the shortcut.

    §3.8: "Two term figures are derived from the `closing_date` at creation."
    §3.8: "Each gross bucket is then discounted at six percent per year by dividing
    it by 1.06 raised to the power of that bucket's number minus one ... and **each
    discounted bucket is rounded to a whole cent on its own** before anything is
    added up. `payoff_quote_cents` is the sum of those individually rounded buckets,
    so the rounding order is per bucket and then sum, never sum and then round."
    §3.8: "Buyouts are priced at title clearance rather than at intake, so that the
    figure quoted is the figure the closing table sees."

    Design: Difficulty/dual_variant_calc/payoff_npv_vs_unamortized_diverge_on_identical_terms
    """
    _, agreement = _one_active_ppa(api)

    opened = open_prepayment(api, agreement["id"], "2026-09-01")
    assert opened["status"] == C.TRANSFER_INITIATED
    assert opened["elapsed_term_months"] == 20
    assert opened["remaining_term_months"] == 220

    cleared = clear_title(api, opened["id"])

    assert cleared["payoff_method"] == C.PAYOFF_NPV
    assert cleared["payoff_quote_cents"] == NPV_QUOTE_CENTS
    assert cleared["payoff_quote_cents"] != NPV_QUOTE_IF_ROUNDED_ONCE
    assert cleared["title_cleared_by_user_id"] == U.TITLE_1
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_clearing_an_assumption_never_runs_a_payoff_variant(api):
    """Nothing is bought out, so the quote stays at zero through both steps.

    §3.8: "Under `NONE` the `payoff_quote_cents` is 0, because an assumption
    transfers the obligation instead of extinguishing it." §3.8: "On the assumption
    arm the case moves `CREDIT_APPROVED → TITLE_CLEARED`, and every `UccFiling`
    recorded against the agreement must be either `SUBORDINATED` or `TERMINATED`".
    §3.8: "Clearance stamps `title_cleared_by_user_id` with the acting `X-User-ID`".

    Design: Corner/calculations/assumption_selects_the_none_payoff_variant_and_quotes_zero
    """
    seller, agreement = _one_active_ppa(api)
    buyer = make_buyer(
        api, fico_score=760, dti_ratio=0.05, monthly_income_cents=3000000
    )

    opened = open_assumption(api, agreement["id"], "2026-09-01", buyer["id"])
    assert opened["payoff_method"] == C.PAYOFF_NONE
    assert opened["payoff_quote_cents"] == 0

    reviewed = run_credit_review(api, opened["id"])
    assert reviewed["status"] == C.TRANSFER_CREDIT_APPROVED
    assert float(reviewed["credit_composite_score"]) == 86.67
    assert reviewed["credit_decision"] == C.CREDIT_APPROVED

    cleared = clear_title(api, opened["id"])

    assert cleared["status"] == C.TRANSFER_TITLE_CLEARED
    assert cleared["title_cleared_by_user_id"] == U.TITLE_1
    assert cleared["payoff_method"] == C.PAYOFF_NONE
    assert cleared["payoff_quote_cents"] == 0

    parent = read_agreement(api, agreement["id"])
    assert parent["lifecycle_state"] == C.LIFECYCLE_TRANSFER_PENDING
    assert parent["homeowner_id"] == seller["id"]
    assert parent["service_status"] == C.SERVICE_IN_SERVICE


# January 2025 at 400 kWh: 74 kWh short of a 474 kWh floor at 14750 millicents
# earns 1092 cents, and its own invoice is 5900 net plus a 89-cent late fee.
JANUARY_CREDIT_CENTS = 1092
JANUARY_TOTAL_INVOICED_CENTS = 5989


def _cleared_prepayment_with_a_live_lien(api):
    """A TITLE_CLEARED buyout over an agreement holding credit and one filing."""
    owner, agreement = _one_active_ppa(api)
    january = record_period(
        api,
        agreement["id"],
        2025,
        1,
        400,
        auto_reconcile=True,
        auto_issue_credit=True,
    )
    filing = make_filing(api, agreement["id"], "2025-01-15")
    case = open_prepayment(api, agreement["id"], "2026-09-01")
    validate_success(
        api.request_termination(filing["id"], U.title_headers(U.TITLE_1)), 200
    )
    cleared = clear_title(api, case["id"], U.title_headers(U.TITLE_2))
    assert cleared["status"] == C.TRANSFER_TITLE_CLEARED
    assert cleared["payoff_quote_cents"] == NPV_QUOTE_CENTS
    assert january["status"] == C.PERIOD_CREDIT_ISSUED
    assert january["credit_cents"] == JANUARY_CREDIT_CENTS
    assert_credit_counters(
        read_agreement(api, agreement["id"]),
        earned=JANUARY_CREDIT_CENTS,
        applied=0,
        balance=JANUARY_CREDIT_CENTS,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    return owner, agreement, january, filing, cleared


def test_one_close_spends_the_credit_and_terminates_the_lien_by_itself(api):
    """Case, agreement, ledger and filing all move on the single close request.

    §3.8: "Any outstanding guarantee credit is spent against the buyout first: the
    smaller of the agreement's `credit_balance_cents` and the case's
    `payoff_quote_cents` is added to `credit_applied_cents` and subtracted from
    `credit_balance_cents`, so a balance larger than the payoff is only partly
    consumed and the payoff is never over-credited. Every `UccFiling` on the
    agreement that is not already `TERMINATED` is terminated as a cascade, whatever
    state it was in, with `terminated_date` stamped to the current clock date".
    §3.9: "A `PREPAYMENT` closing terminates filings out of `FILED`, `SUBORDINATED`
    and `TERMINATION_REQUESTED` alike, as described in §3.8."

    Design: Difficulty/transitive_cascade/prepayment_close_cascades_to_ucc_termination_and_child_write_lockout
    """
    _, agreement, _, filing, cleared = _cleared_prepayment_with_a_live_lien(api)
    assert _read_filing(api, filing["id"])["status"] == C.FILING_TERMINATION_REQUESTED

    closed = close_transfer(api, cleared["id"])

    assert closed["status"] == C.TRANSFER_CLOSED
    assert closed["payoff_method"] == C.PAYOFF_NPV
    assert closed["payoff_quote_cents"] == NPV_QUOTE_CENTS

    settled = read_agreement(api, agreement["id"])
    assert settled["lifecycle_state"] == C.LIFECYCLE_PREPAID_CLOSED
    assert settled["service_status"] == C.SERVICE_IN_SERVICE
    assert_credit_counters(
        settled,
        earned=JANUARY_CREDIT_CENTS,
        applied=JANUARY_CREDIT_CENTS,
        balance=0,
    )

    cascaded = _read_filing(api, filing["id"])
    assert cascaded["status"] == C.FILING_TERMINATED
    assert cascaded["terminated_date"] == "2026-09-01"
    assert cascaded["requested_by_transfer_case_id"] is not None


def test_the_closed_agreement_stops_accepting_metered_months(api):
    """The fourth level of the cascade is a lockout, and no month is re-settled.

    §3.3: "Recording a month against an agreement whose `lifecycle_state` is
    `DRAFT`, `PREPAID_CLOSED` or `PURCHASED_CLOSED` is refused with
    `ERR_AGREEMENT_NOT_ACTIVE`". §3.8: "Metered months still sitting in `RECORDED`
    are deliberately left alone — prepayment does not retroactively settle unsettled
    production."

    Design: Difficulty/transitive_cascade/prepayment_close_cascades_to_ucc_termination_and_child_write_lockout
    """
    _, agreement, january, _, cleared = _cleared_prepayment_with_a_live_lien(api)
    close_transfer(api, cleared["id"])

    validate_error(
        api.create_period(
            F.period_payload(agreement["id"], 2026, 6, 1000), U.agent_headers()
        ),
        E.ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    untouched = validate_success(
        api.get_period(january["id"], U.agent_headers()), 200
    )
    assert untouched["status"] == C.PERIOD_CREDIT_ISSUED
    assert untouched["credit_cents"] == JANUARY_CREDIT_CENTS
    assert untouched["total_invoiced_cents"] == JANUARY_TOTAL_INVOICED_CENTS
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_PREPAID_CLOSED
    )


def test_a_relocated_agreement_is_decommissioned_and_its_successor_takes_the_month(api):
    """The panels are gone from the old roof, so the old row reports the safety code.

    §3.8: "A `RELOCATION` moves the agreement `TRANSFER_PENDING →
    RELOCATED_CLOSED` and creates a successor `SolarAgreement` in `ACTIVE`, whose
    `relocated_from_agreement_id` points back at the predecessor and whose
    `successor_agreement_id` is recorded on the case." §3.8: "The successor's three
    credit counters start at 0 while the predecessor's are frozen at their closing
    values, and the predecessor's asset dimension moves `DECOMMISSION_PENDING →
    DECOMMISSIONED`." §2.10 rung 10: "`ERR_AGREEMENT_DECOMMISSIONED`, HTTP 409, when
    a new metered month, outage event, roof-work order, transfer case or end-of-term
    election is written against an agreement whose `service_status` is
    `DECOMMISSIONED`."

    Design: Corner/validations/production_period_against_a_relocation_closed_agreement_is_rejected
    """
    _, agreement = _one_active_ppa(api)
    case = open_relocation(
        api, agreement["id"], "2026-08-01", new_site_address=NEW_SITE
    )

    cleared = clear_title(api, case["id"])
    assert cleared["elapsed_term_months"] == 19
    assert cleared["remaining_term_months"] == 221
    assert cleared["payoff_method"] == C.PAYOFF_UNAMORTIZED
    assert cleared["payoff_quote_cents"] == 2971600
    assert (
        read_agreement(api, agreement["id"])["service_status"]
        == C.SERVICE_DECOMMISSION_PENDING
    )

    closed = close_transfer(api, case["id"])
    assert closed["status"] == C.TRANSFER_CLOSED
    assert closed["successor_agreement_id"] is not None

    predecessor = read_agreement(api, agreement["id"])
    assert predecessor["lifecycle_state"] == C.LIFECYCLE_RELOCATED_CLOSED
    assert predecessor["service_status"] == C.SERVICE_DECOMMISSIONED

    body = F.period_payload(agreement["id"], 2026, 6, 950)
    validate_error(
        api.create_period(body, U.agent_headers()),
        E.ERR_AGREEMENT_DECOMMISSIONED,
        409,
    )

    successor = read_agreement(api, closed["successor_agreement_id"])
    assert successor["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert successor["site_address"] == NEW_SITE
    assert successor["relocated_from_agreement_id"] == agreement["id"]
    assert successor["contract_start_date"] == "2025-01-01"
    assert_credit_counters(successor, earned=0, applied=0, balance=0)

    body["agreement_id"] = successor["id"]
    accepted = validate_success(api.create_period(body, U.agent_headers()), 201)
    assert accepted["status"] == C.PERIOD_RECORDED
    assert accepted["metered_kwh"] == 950
