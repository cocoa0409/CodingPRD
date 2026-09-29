"""Filing fee assessment across submission, registry acceptance and withdrawal.

The provisional variant is assessed when the filing is submitted and ignores the
coverage period; the final variant is assessed at acceptance and prorates the
same disclosure set by coverage_days / 365 with a single rounding step. Both
variants move money only between the committed and uncommitted halves of the
broker's filing-fee account.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    add_disclosures,
    api_client,
    assert_broker_ledger_conserved,
    assert_cents_equals,
    assert_instant_equals,
    assert_score_equals,
    fetch_broker,
    fetch_registration,
    make_platform_admin_headers,
    onboard_broker,
    open_draft_registration,
    setup_accepted_registration,
    submit_registration,
    validate_success,
)

COVERAGE_START = "2026-09-01T00:00:00Z"
ALL_SIX_CATEGORIES = (
    "SOURCES",
    "RECIPIENTS",
    "RETENTION",
    "OPT_OUT_MECHANISM",
    "SENSITIVE_CATEGORIES",
    "MINORS_DATA",
)
SENSITIVE_FLAGGED_CATEGORIES = ("SENSITIVE_CATEGORIES", "MINORS_DATA")


def _submitted_filing_with_all_six_disclosures(coverage_period_end):
    """One CA filing carrying all six disclosure categories at full content
    length, SENSITIVE_CATEGORIES and MINORS_DATA filed with
    covers_sensitive_categories true, submitted against 500000 cents of credit.

    Returns the broker context extended with registration_id, disclosures and
    the submitted registration projection.
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=500000, clock=CLOCK_TEST_INSTANT
    )
    registration = open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code="CA",
        coverage_period_start=COVERAGE_START,
        coverage_period_end=coverage_period_end,
    )
    ctx["registration_id"] = registration["id"]
    ctx["disclosures"] = add_disclosures(
        registration["id"],
        ctx["broker_headers"],
        categories=ALL_SIX_CATEGORIES,
        sensitive_categories=SENSITIVE_FLAGGED_CATEGORIES,
    )
    ctx["registration"] = submit_registration(
        registration["id"], ctx["broker_headers"]
    )
    return ctx


def _disclosure_by_category(disclosures, category):
    for item in disclosures:
        if item["category"] == category:
            return item
    raise AssertionError(f"Setup expected a {category} disclosure item, found none")


def test_final_filing_fee_prorates_the_provisional_assessment_at_acceptance():
    """PRD §3.2: "The provisional fee is the base of 40000 cents plus the plain
    sum of those already-rounded per-item surcharges, with **no proration
    whatsoever**."
    PRD §3.2: "Acceptance recomputes `coverage_days` as the whole number of days
    in the half-open interval and then runs the final variant of the fee
    calculation, which prorates."
    PRD §3.2: "The proration ratio is `coverage_days` divided by 365, capped at
    1.0 so that a coverage period longer than a year is never charged more than a
    full year."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount
    and `charged_fee_cents` is reset to it."
    PRD §3.2: "Whenever `coverage_days` is below 365, the final fee is strictly
    smaller than the provisional fee computed from identical disclosure data."
    PRD §3.2: "Those six weights total exactly 100.00, so a filing that answers
    every category at full length scores exactly 100.00 and no clamp is needed."

    Design: Difficulty/dual_variant_calc/filing_fee_provisional_at_submit_versus_final_at_acceptance
    """
    ctx = _submitted_filing_with_all_six_disclosures("2027-03-01T00:00:00Z")

    registration = validate_success(
        api_client.accept_registration(
            ctx["registration_id"], make_platform_admin_headers()
        )
    )

    assert registration["status"] == "ACCEPTED", (
        f"Expected the filing to be ACCEPTED, got {registration['status']}"
    )
    assert registration["coverage_days"] == 181, (
        f"Expected coverage_days 181, got {registration['coverage_days']}"
    )
    assert_score_equals(
        registration["disclosure_completeness_score"],
        100.00,
        "disclosure_completeness_score",
    )
    assert_cents_equals(
        registration["provisional_filing_fee_cents"],
        65225,
        "provisional_filing_fee_cents",
    )
    assert_cents_equals(
        registration["final_filing_fee_cents"], 32344, "final_filing_fee_cents"
    )
    assert_cents_equals(registration["charged_fee_cents"], 32344, "charged_fee_cents")
    assert (
        registration["final_filing_fee_cents"]
        != registration["provisional_filing_fee_cents"]
    ), "A 181-day filing must settle below its un-prorated provisional assessment"


def test_acceptance_settlement_returns_the_overcharge_to_broker_fee_credit():
    """PRD §3.2: "The settlement delta is the final fee minus the provisional
    fee: when that delta is negative, the broker's `fee_paid_cents` decreases by
    its magnitude and `fee_credit_cents` increases by the same magnitude (the
    over-charge is refunded to credit); when it is positive, the movement runs
    the other way, from credit into paid."
    PRD §3.2: "`fee_deposited_cents` never changes during settlement."
    PRD §2.7: "The broker's filing-fee account obeys a conservation law that must
    hold after every deposit, every submission, every acceptance settlement, and
    every withdrawal, rejection, or expiry refund: `fee_deposited_cents` always
    equals `fee_paid_cents` plus `fee_credit_cents`."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of
    `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or
    before the current clock instant while its `coverage_period_end` is strictly
    after it, the standing is `COMPLIANT`."
    PRD §3.1: "On a transition into `COMPLIANT`, `delinquent_since` is cleared to
    null."

    Design: Difficulty/dual_variant_calc/filing_fee_provisional_at_submit_versus_final_at_acceptance
    """
    ctx = _submitted_filing_with_all_six_disclosures("2027-03-01T00:00:00Z")

    validate_success(
        api_client.accept_registration(
            ctx["registration_id"], make_platform_admin_headers()
        )
    )

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 32344, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 467656, "fee_credit_cents")
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert_broker_ledger_conserved(broker)
    assert broker["registry_standing"] == "COMPLIANT", (
        f"Expected registry_standing COMPLIANT, got {broker['registry_standing']}"
    )
    assert broker["delinquent_since"] is None, (
        f"Expected delinquent_since null, got {broker['delinquent_since']!r}"
    )


def test_final_fee_rounds_exactly_once_after_aggregating_then_prorating():
    """PRD §3.2: "The final fee is computed by first aggregating the base 40000
    cents with the same sum of per-item surcharges (re-read as the disclosure set
    stands **at acceptance time**, so a disclosure added during a
    rejection-and-revision loop changes the final fee relative to the provisional
    fee frozen at the earlier submission), then multiplying that aggregate by a
    proration ratio, and only then rounding half up to a whole cent — exactly one
    rounding step, applied at the very end."
    PRD §3.2: "Prorating each category separately and then summing is wrong and
    produces a different number of cents; the aggregate-then-prorate-then-round-once
    order is mandatory."
    PRD §3.2: "`coverage_days` is computed from the half-open interval as the
    whole number of days it spans."

    Design: Difficulty/combinatorial_formula/filing_fee_nested_rounding_order_aggregate_then_prorate
    """
    ctx = _submitted_filing_with_all_six_disclosures("2026-12-30T00:00:00Z")

    registration = validate_success(
        api_client.accept_registration(
            ctx["registration_id"], make_platform_admin_headers()
        )
    )

    assert registration["coverage_days"] == 120, (
        f"Expected coverage_days 120, got {registration['coverage_days']}"
    )
    assert_cents_equals(
        registration["provisional_filing_fee_cents"],
        65225,
        "provisional_filing_fee_cents",
    )
    assert_cents_equals(
        registration["final_filing_fee_cents"], 21444, "final_filing_fee_cents"
    )
    assert registration["final_filing_fee_cents"] != 21445, (
        "21445 is the per-category prorate-then-sum answer; the aggregate-then-"
        "prorate-then-round-once order yields 21444"
    )
    assert_cents_equals(registration["charged_fee_cents"], 21444, "charged_fee_cents")


def test_per_item_surcharges_are_rounded_before_the_aggregate_is_prorated():
    """PRD §3.2: "Each item's `surcharge_cents` was fixed once when the item was
    inserted: it is that category's surcharge — 1500 cents for `SOURCES`, 2500 for
    `RECIPIENTS`, 1200 for `RETENTION`, 6000 for `SENSITIVE_CATEGORIES`, 1800 for
    `OPT_OUT_MECHANISM`, and 7500 for `MINORS_DATA` — multiplied by 1.35 when that
    item's `covers_sensitive_categories` is true and by 1.0 when it is false, with
    the product rounded half up to a whole cent at that point."
    PRD §3.2: "Prorating each category separately and then summing is wrong and
    produces a different number of cents; the aggregate-then-prorate-then-round-once
    order is mandatory."
    PRD §2.7: "The broker's filing-fee account obeys a conservation law that must
    hold after every deposit, every submission, every acceptance settlement, and
    every withdrawal, rejection, or expiry refund: `fee_deposited_cents` always
    equals `fee_paid_cents` plus `fee_credit_cents`."

    Design: Difficulty/combinatorial_formula/filing_fee_nested_rounding_order_aggregate_then_prorate
    """
    ctx = _submitted_filing_with_all_six_disclosures("2026-12-30T00:00:00Z")

    assert_cents_equals(
        _disclosure_by_category(ctx["disclosures"], "SOURCES")["surcharge_cents"],
        1500,
        "SOURCES surcharge_cents",
    )
    assert_cents_equals(
        _disclosure_by_category(ctx["disclosures"], "SENSITIVE_CATEGORIES")[
            "surcharge_cents"
        ],
        8100,
        "SENSITIVE_CATEGORIES surcharge_cents",
    )
    assert_cents_equals(
        _disclosure_by_category(ctx["disclosures"], "MINORS_DATA")["surcharge_cents"],
        10125,
        "MINORS_DATA surcharge_cents",
    )

    validate_success(
        api_client.accept_registration(
            ctx["registration_id"], make_platform_admin_headers()
        )
    )

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 21444, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 478556, "fee_credit_cents")
    assert_broker_ledger_conserved(broker)


def test_fee_ledger_reconciles_after_the_acceptance_settlement():
    """PRD §2.7: "The broker's filing-fee account obeys a conservation law that
    must hold after every deposit, every submission, every acceptance settlement,
    and every withdrawal, rejection, or expiry refund: `fee_deposited_cents`
    always equals `fee_paid_cents` plus `fee_credit_cents`."
    PRD §3.2: "Both `provisional_filing_fee_cents` and `charged_fee_cents` are set
    to that amount, `fee_credit_cents` decreases by it while `fee_paid_cents`
    increases by the same amount (`fee_deposited_cents` does not move),
    `submitted_at` is set to the current clock instant, the parent broker's
    `version` increases by one, and a `REGISTRATION_SUBMITTED` audit event is
    appended."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount
    and `charged_fee_cents` is reset to it."

    Design: Difficulty/compensating_invariant/broker_fee_ledger_reconciles_across_submit_accept_and_withdraw
    """
    ctx = setup_accepted_registration()

    registration = fetch_registration(ctx["registration_id"], ctx["broker_headers"])
    assert_cents_equals(
        registration["provisional_filing_fee_cents"],
        47000,
        "provisional_filing_fee_cents",
    )
    assert_cents_equals(
        registration["final_filing_fee_cents"], 23307, "final_filing_fee_cents"
    )

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert_cents_equals(broker["fee_paid_cents"], 23307, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 476693, "fee_credit_cents")
    assert_broker_ledger_conserved(broker)


def test_withdrawal_refunds_the_settled_charge_and_leaves_the_ledger_whole():
    """PRD §3.2: "Withdrawal moves the filing to `WITHDRAWN`, which is terminal,
    and runs the identical four-link cascade as rejection: refund
    `charged_fee_cents` from `fee_paid_cents` into `fee_credit_cents` and zero it;
    re-derive standing, setting `delinquent_since` and appending
    `STANDING_CHANGED` on a flip from `COMPLIANT` to `DELINQUENT`; on a genuine
    standing change, suspend every `ACTIVE` recipient of the broker whose
    `contract_propagation_required` is true and append a
    `RECIPIENT_STATUS_CHANGED` event for each; and for each recipient so
    suspended, defer its `PENDING` and `DISPATCHED` tasks with `deferral_reason`
    `BROKER_DELINQUENT`, appending a `PROPAGATION_DEFERRED` event for each."
    PRD §2.7: "The broker's filing-fee account obeys a conservation law that must
    hold after every deposit, every submission, every acceptance settlement, and
    every withdrawal, rejection, or expiry refund: `fee_deposited_cents` always
    equals `fee_paid_cents` plus `fee_credit_cents`."
    PRD §3.1: "On a transition into `DELINQUENT` or `SUSPENDED` from `COMPLIANT`,
    `delinquent_since` is set to the current clock instant."

    Design: Difficulty/compensating_invariant/broker_fee_ledger_reconciles_across_submit_accept_and_withdraw
    """
    ctx = setup_accepted_registration()

    registration = validate_success(
        api_client.withdraw_registration(
            ctx["registration_id"], ctx["broker_headers"]
        )
    )

    assert registration["status"] == "WITHDRAWN", (
        f"Expected the filing to be WITHDRAWN, got {registration['status']}"
    )
    assert_cents_equals(registration["charged_fee_cents"], 0, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert_cents_equals(broker["fee_paid_cents"], 0, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 500000, "fee_credit_cents")
    assert_broker_ledger_conserved(broker)
    assert broker["registry_standing"] == "DELINQUENT", (
        f"Expected registry_standing DELINQUENT, got {broker['registry_standing']}"
    )
    assert_instant_equals(
        broker["delinquent_since"], CLOCK_TEST_INSTANT, "delinquent_since"
    )
