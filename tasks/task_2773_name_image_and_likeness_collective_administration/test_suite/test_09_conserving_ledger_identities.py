"""Compensating operations must leave derived ledgers exactly where they started.

PRD s2.9 states that derived figures "are always recomputed from the underlying rows
rather than adjusted incrementally, so a compensating operation such as a refund or a
reversal leaves exactly the figures a fresh computation would produce."
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_donor_ledger,
    assert_release_money,
    read_data,
)
from test_helpers.factories import (
    billing_run_payload,
    contribution_payload,
    payment_release_payload,
    reversal_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_open_tier,
    build_settled_contribution,
    clear_disclosure,
    build_draft_contract,
    activate_contract,
    read_athlete,
    read_collective,
    read_contract,
    read_donor,
    read_release,
    record_taxpayer_doc,
)
from test_helpers.test_users import make_director_headers, make_treasury_headers


def _contract_ready_for_an_advance(api):
    """487470 of settled net funds against one ACTIVE 200000-cent contract."""
    collective = build_collective(
        api,
        "017100",
        name="Ledger Identity Collective",
        institution_name="Ohio Institution D",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T3", 90000, 3)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Abe Alpha",
        email="abe@example.com",
    )
    contribution = build_settled_contribution(
        api, donor["id"], 500000, designation="UNRESTRICTED"
    )
    assert_contribution_money(
        contribution, processing_fee_cents=12530, net_amount_cents=487470, status="SETTLED"
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-bea",
        full_name="Bea Bravo",
        sport="FOOTBALL",
        class_year=2028,
    )
    profile = record_taxpayer_doc(api, athlete["id"], "W9")
    assert profile["taxpayer_doc_on_file"] == "W9"

    contract = build_draft_contract(
        api, collective["id"], athlete["id"], 200000, funding_designation="UNRESTRICTED"
    )
    clear_disclosure(api, contract["id"])
    activated = activate_contract(api, contract["id"])

    before = read_collective(api, collective["id"])
    assert_collective_ledger(
        before,
        settled_net_funds_cents=487470,
        released_total_cents=0,
        reversed_total_cents=0,
        committed_unreleased_cents=200000,
        funding_posture="OPEN",
    )
    return {
        "collective_id": collective["id"],
        "athlete_id": athlete["id"],
        "contract_id": contract["id"],
        "contract_version": activated["version"],
    }


def _advance_of_one_hundred_fifty_thousand(api, ctx):
    return read_data(
        api.create_payment_release(
            payment_release_payload(
                ctx["contract_id"],
                "CONTRACT_ADVANCE",
                150000,
                expected_deal_contract_version=ctx["contract_version"],
            ),
            make_treasury_headers("treasury-5"),
        ),
        expected_status=201,
    )


def test_the_advance_itself_draws_the_spendable_identity_down(api):
    """The release is the withdrawal half of the pair and moves every derived figure.

    PRD s3.9: "when the athlete's `eligibility_status` is `ENROLLED`, the row advances
    `QUEUED -> RELEASED` in the very same request", and with a W9 on file "the
    `withholding_basis` is `NONE` and `withholding_amount_cents` is 0", so
    net_payable_cents is the full 150000. PRD s2.10 derives
    committed_unreleased_cents as "the contract's `total_value_cents` less that
    contract's own released total", which is 200000 - 150000 here.

    Design: Difficulty/compensating_invariant/release_then_reversal_conserves_collective_funds_identity
    """
    ctx = _contract_ready_for_an_advance(api)

    release = _advance_of_one_hundred_fifty_thousand(api, ctx)
    assert_release_money(
        release,
        status="RELEASED",
        requested_amount_cents=150000,
        withholding_basis="NONE",
        withholding_amount_cents=0,
        net_payable_cents=150000,
        reversal_reason="NONE",
        initiated_by_user_id="treasury-5",
    )
    assert release["released_at"] is not None

    collective = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(
        collective,
        settled_net_funds_cents=487470,
        released_total_cents=150000,
        reversed_total_cents=0,
        committed_unreleased_cents=50000,
        funding_posture="OPEN",
    )
    assert (
        collective["settled_net_funds_cents"] - collective["released_total_cents"] == 337470
    )

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(contract, released_total_cents=150000)
    assert_contract_dimensions(contract, payment_status="PARTIALLY_PAID")
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]),
        tax_year_gross_paid_cents=150000,
        tax_year_withheld_cents=0,
        tax_form_required="FORM_1099_NEC",
    )


def test_the_reversal_restores_the_identity_and_only_adds_an_audit_counter(api):
    """After the compensation the spendable identity is bit-for-bit what it was.

    PRD s3.9: "A reversal advances `RELEASED -> REVERSED`, records the
    `reversal_reason` ... The collective's `released_total_cents`,
    `reversed_total_cents`, `committed_unreleased_cents` and `funding_posture` are all
    re-derived, and so are the athlete's `tax_year_gross_paid_cents`,
    `tax_year_withheld_cents` and `tax_form_required` — a reversed release contributes
    nothing to either figure". PRD s2.10 adds that reversed_total_cents is its own sum
    "over releases with status `REVERSED`", which is why it rises to 150000 while
    released_total_cents returns to zero.

    Design: Difficulty/compensating_invariant/release_then_reversal_conserves_collective_funds_identity
    """
    ctx = _contract_ready_for_an_advance(api)
    release = _advance_of_one_hundred_fifty_thousand(api, ctx)

    reversed_release = read_data(
        api.reverse_payment_release(
            release["id"],
            reversal_payload("ERRONEOUS_PAYMENT"),
            make_treasury_headers("treasury-5"),
        )
    )
    assert_release_money(
        reversed_release,
        status="REVERSED",
        requested_amount_cents=150000,
        reversal_reason="ERRONEOUS_PAYMENT",
    )
    assert read_release(api, release["id"])["status"] == "REVERSED"

    collective = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(
        collective,
        settled_net_funds_cents=487470,
        released_total_cents=0,
        reversed_total_cents=150000,
        committed_unreleased_cents=200000,
        funding_posture="OPEN",
    )
    assert (
        collective["settled_net_funds_cents"] - collective["released_total_cents"] == 487470
    )

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(contract, released_total_cents=0)
    assert_contract_dimensions(contract, lifecycle_status="ACTIVE", payment_status="UNPAID")
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]),
        tax_year_gross_paid_cents=0,
        tax_year_withheld_cents=0,
        tax_form_required="NONE",
    )


def _donor_with_five_hundred_thousand_of_headroom_consumed(api):
    """A charitable donor whose 600000-cent ceiling is 500000 spent by one settled gift."""
    collective = build_collective(
        api,
        "018100",
        name="Deduction Ledger Fund",
        institution_name="California Institution E",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    assert collective["charitable_deduction_enabled"] is True
    tier = build_open_tier(api, collective["id"], "T5", 450000, 5)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Cal Charlie",
        email="cal@example.com",
        donor_kind="INDIVIDUAL",
        annual_agi_cents=1000000,
    )
    first = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                512851,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        first,
        net_amount_cents=500000,
        deductible_amount_cents=500000,
        status="SETTLED",
    )
    assert_donor_ledger(
        read_donor(api, donor["id"]),
        lifetime_settled_cents=500000,
        lifetime_deductible_cents=500000,
        status="ACTIVE",
    )
    return {
        "collective_id": collective["id"],
        "donor_id": donor["id"],
        "first_id": first["id"],
    }


def _second_gift(api, donor_id):
    return read_data(
        api.create_contribution(
            contribution_payload(
                donor_id, 410287, designation="UNRESTRICTED", processor_outcome="APPROVE"
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )


def test_the_second_gift_consumes_the_last_of_the_agi_headroom(api):
    """The settle half of the pair spends the remaining 100000 of the ceiling.

    PRD s3.6: "for each row in turn the row's `deductible_amount_cents` is set to
    whichever is smaller — that row's `net_amount_cents`, or the remaining headroom —
    after which the remaining headroom is reduced by the amount just assigned." The
    ceiling is floor(1000000 * 60 / 100) = 600000, so this 400000-cent net gift is
    capped at the 100000 that is left.

    Design: Difficulty/compensating_invariant/contribution_settle_then_refund_conserves_donor_deduction_ledger
    """
    ctx = _donor_with_five_hundred_thousand_of_headroom_consumed(api)

    second = _second_gift(api, ctx["donor_id"])
    assert_contribution_money(
        second,
        gross_amount_cents=410287,
        processing_fee_cents=10287,
        net_amount_cents=400000,
        deductible_amount_cents=100000,
        status="SETTLED",
    )

    assert_donor_ledger(
        read_donor(api, ctx["donor_id"]),
        lifetime_settled_cents=900000,
        lifetime_deductible_cents=600000,
        status="ACTIVE",
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), settled_net_funds_cents=900000
    )


def test_the_refund_and_recompute_return_the_headroom_without_drift(api):
    """Refunding the second gift frees exactly its share and leaves the survivor alone.

    PRD s3.5: "A refunded row is excluded from deductibility entirely, which frees its
    share of the donor's ceiling for the remaining rows the next time attribution is
    computed." PRD s3.6 adds that deduction_delta_cents is "the signed sum of the
    per-row changes the recompute produced, which nets to zero across a donor even when
    individual rows move by large amounts", and only the one surviving settled row is
    in scope, so recomputed_contribution_count is 1.

    Design: Difficulty/compensating_invariant/contribution_settle_then_refund_conserves_donor_deduction_ledger
    """
    ctx = _donor_with_five_hundred_thousand_of_headroom_consumed(api)
    second = _second_gift(api, ctx["donor_id"])

    refunded = read_data(
        api.refund_contribution(second["id"], {}, make_treasury_headers())
    )
    assert_contribution_money(refunded, status="REFUNDED", net_amount_cents=400000)

    report = read_data(
        api.create_billing_run(
            ctx["collective_id"],
            billing_run_payload("YEAR_END_TAX_RECOMPUTE"),
            make_treasury_headers(),
        )
    )
    assert report["recomputed_contribution_count"] == 1
    assert report["deduction_delta_cents"] == 0

    survivor = read_data(api.get_contribution(ctx["first_id"], make_treasury_headers()))
    assert_contribution_money(
        survivor,
        status="SETTLED",
        net_amount_cents=500000,
        deductible_amount_cents=500000,
    )
    assert_donor_ledger(
        read_donor(api, ctx["donor_id"]),
        lifetime_settled_cents=500000,
        lifetime_deductible_cents=500000,
        status="ACTIVE",
    )
    collective = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(collective, settled_net_funds_cents=500000)
    assert collective["charitable_deduction_enabled"] is True
