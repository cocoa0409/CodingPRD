"""Consistency model: every derived figure is current in the write's own response.

PRD s3.5 resolves a contribution "inside the very same request", and PRD s2.6 fans the
settlement out to the collective and donor ledgers within it, so no read below needs a
retry.
"""

from test_helpers.assertions import (
    assert_collective_ledger,
    assert_contribution_money,
    assert_donor_ledger,
    read_data,
)
from test_helpers.factories import contribution_payload
from test_helpers.fixtures import (
    build_collective,
    build_donor,
    build_open_tier,
    read_collective,
    read_donor,
)
from test_helpers.test_users import make_treasury_headers


def test_the_second_gift_already_sees_the_ceiling_the_first_one_consumed(api):
    """Fee, net and ceiling-limited deductible are all present in the create response.

    PRD s3.5: "The `processor_outcome` is then resolved inside the very same request.
    `APPROVE` settles the contribution immediately, advancing it `PENDING → SETTLED`", and
    "A settling contribution fans out in four directions. Its `processing_fee_cents`,
    `net_amount_cents` and `deductible_amount_cents` are computed and its
    `deduction_variant` is stamped `AT_RECEIPT`. The collective's `settled_net_funds_cents`
    is re-derived and `funding_posture` re-derived from it. The owning donor member bubbles
    up to `ACTIVE` and both lifetime figures are re-derived." The INDIVIDUAL ceiling is
    floor(1000000 * 60 / 100) = 600000, so the second gift's own response already reports
    only the 100000 of headroom the first gift left.

    Design: Corner/consistency model/derived_deduction_and_ledger_totals_are_visible_in_the_same_response
    """
    collective = build_collective(
        api,
        "026500",
        name="Immediate Collective",
        institution_name="Immediate Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    assert collective["charitable_deduction_enabled"] is True
    tier = build_open_tier(api, collective["id"], "T4", 400000, 4)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Imm Donor",
        email="imm@example.com",
        donor_kind="INDIVIDUAL",
        annual_agi_cents=1000000,
    )

    first = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                512851,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        first,
        gross_amount_cents=512851,
        processing_fee_cents=12851,
        net_amount_cents=500000,
        deductible_amount_cents=500000,
        deduction_variant="AT_RECEIPT",
        status="SETTLED",
    )
    assert_collective_ledger(
        read_collective(api, collective["id"]),
        settled_net_funds_cents=500000,
        committed_unreleased_cents=0,
        funding_posture="OPEN",
    )

    second = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                410287,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        second,
        gross_amount_cents=410287,
        processing_fee_cents=10287,
        net_amount_cents=400000,
        deductible_amount_cents=100000,
        deduction_variant="AT_RECEIPT",
        status="SETTLED",
    )

    assert_donor_ledger(
        read_donor(api, donor["id"]),
        lifetime_settled_cents=900000,
        lifetime_deductible_cents=600000,
        status="ACTIVE",
    )
    assert_collective_ledger(
        read_collective(api, collective["id"]), settled_net_funds_cents=900000
    )
