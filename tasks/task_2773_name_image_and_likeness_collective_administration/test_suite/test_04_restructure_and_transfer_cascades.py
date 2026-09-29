"""Transitive cascades along two different spines.

PRD s3.2 runs Collective -> MembershipTier -> Commitment -> DonorMember on an
entity-structure change, and PRD s3.7 runs Athlete -> DealContract -> Deliverable ->
PaymentRelease on a completed transfer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_deliverable_scoring,
    assert_donor_ledger,
    assert_release_money,
    read_data,
)
from test_helpers.factories import (
    commitment_payload,
    compliance_decision_payload,
    compliance_submission_payload,
    contribution_payload,
    deal_contract_payload,
    deliverable_payload,
    eligibility_change_payload,
    entity_structure_payload,
    payment_release_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_open_tier,
    read_athlete,
    read_collective,
    read_contract,
    read_deliverable,
    read_donor,
    read_release,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def _charitable_collective_with_one_recurring_donor(api):
    """A NONPROFIT_501C3 collective whose single donor is ACTIVE on one subscription.

    The 50000-cent subscription charge settles inline, so the donor holds one ACTIVE
    commitment and one SETTLED contribution before the conversion is recorded.
    """
    collective = build_collective(
        api,
        "007700",
        name="Charitable NIL Fund",
        institution_name="California Institution B",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    assert collective["charitable_deduction_enabled"] is True
    tier = build_open_tier(api, collective["id"], "T2", 50000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Iris Ivy",
        email="iris@example.com",
        donor_kind="INDIVIDUAL",
        annual_agi_cents=1000000,
    )
    commitment = read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "RECURRING_SUBSCRIPTION",
                50000,
                "MONTHLY",
                expected_donor_member_version=donor["version"],
                installments_total=12,
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    contribution = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                50000,
                source_kind="SUBSCRIPTION_CHARGE",
                commitment_id=commitment["id"],
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        contribution,
        processing_fee_cents=1480,
        net_amount_cents=48520,
        deductible_amount_cents=48520,
        status="SETTLED",
    )
    assert_donor_ledger(read_donor(api, donor["id"]), status="ACTIVE")
    return {
        "collective_id": collective["id"],
        "tier_id": tier["id"],
        "donor_id": donor["id"],
        "commitment_id": commitment["id"],
        "contribution_id": contribution["id"],
    }


def _convert_to_for_profit(api, collective_id):
    """Record the conversion under a fresh version guard."""
    current = read_collective(api, collective_id)
    return validate_success(
        api.patch_entity_structure(
            collective_id,
            entity_structure_payload(
                "FOR_PROFIT_LLC", expected_collective_version=current["version"]
            ),
            make_admin_headers(),
        ),
        expected_status=200,
    )


def test_a_conversion_closes_the_tier_pauses_the_commitment_and_lapses_the_donor(api):
    """One structure change walks all three cascade levels in order.

    PRD s3.2: "**Level 1.** Every membership tier of the collective whose `tier_status`
    is `DRAFT` or `OPEN` becomes `CLOSED`"; "**Level 2.** Every commitment whose owning
    donor member's `membership_tier_id` is one of those tiers and whose `status` is
    `ACTIVE` or `PAST_DUE` becomes `PAUSED`, with `pause_reason` set to
    `STRUCTURE_RESTRUCTURE`"; "**Level 3.** Every donor member that is left holding at
    least one commitment, all of whose commitments are now in `PAUSED`, `CANCELLED` or
    `FULFILLED`, becomes `LAPSED`". The flag itself "is true if and only if
    `entity_structure` is `NONPROFIT_501C3`" (PRD s3.2).

    Design: Difficulty/transitive_cascade/restructure_closes_tiers_pauses_commitments_lapses_donor
    """
    ctx = _charitable_collective_with_one_recurring_donor(api)

    converted = _convert_to_for_profit(api, ctx["collective_id"])
    assert converted["entity_structure"] == "FOR_PROFIT_LLC"
    assert converted["charitable_deduction_enabled"] is False
    assert converted["structure_change_count"] == 1

    tier = validate_success(
        api.get_membership_tier(ctx["tier_id"], make_director_headers()),
        expected_status=200,
    )
    assert tier["tier_status"] == "CLOSED", (
        "Level 1 closes an OPEN tier of the converted collective"
    )

    commitment = validate_success(
        api.get_commitment(ctx["commitment_id"], make_director_headers()),
        expected_status=200,
    )
    assert commitment["status"] == "PAUSED"
    assert commitment["pause_reason"] == "STRUCTURE_RESTRUCTURE", (
        "Only the restructure path pauses a commitment for this reason"
    )

    assert_donor_ledger(read_donor(api, ctx["donor_id"]), status="LAPSED")


def test_a_conversion_leaves_settled_deduction_history_alone(api):
    """The cascade stops short of rewriting a settled contribution's deductible amount.

    PRD s3.2: "One thing a restructure explicitly does **not** do is rewrite history.
    Deductible amounts already stored on settled contributions are left exactly as they
    are, even though the collective's deductibility flag may have just flipped; only the
    year-end tax recompute described in s3.6 rewrites those figures."

    Design: Difficulty/transitive_cascade/restructure_closes_tiers_pauses_commitments_lapses_donor
    """
    ctx = _charitable_collective_with_one_recurring_donor(api)

    _convert_to_for_profit(api, ctx["collective_id"])

    contribution = validate_success(
        api.get_contribution(ctx["contribution_id"], make_director_headers()),
        expected_status=200,
    )
    assert_contribution_money(
        contribution,
        status="SETTLED",
        net_amount_cents=48520,
        deductible_amount_cents=48520,
    )
    assert_donor_ledger(
        read_donor(api, ctx["donor_id"]),
        lifetime_settled_cents=48520,
        lifetime_deductible_cents=48520,
        status="LAPSED",
    )


def _portal_athlete_with_a_queued_release(api):
    """An ACTIVE 100000-cent contract with two PENDING deliverables and one QUEUED release.

    The athlete is in the transfer portal when the release is requested, so PRD s3.7
    parks the row in QUEUED instead of releasing it.
    """
    collective = build_collective(
        api,
        "008800",
        name="Longhorn Transfer Fund",
        institution_name="Texas Institution B",
        home_state_code="TX",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T3", 150000, 3)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Jo Juliet",
        email="jo@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                500000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        contribution, processing_fee_cents=12530, net_amount_cents=487470
    )

    athlete = build_athlete(
        api,
        collective["id"],
        "ath-kip",
        full_name="Kip Kilo",
        sport="FOOTBALL",
        class_year=2027,
    )
    contract = validate_success(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                100000,
                effective_start_at="2026-08-01T00:00:00Z",
                effective_end_at="2026-12-31T00:00:00Z",
                funding_designation="UNRESTRICTED",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_compliance_packet(
            contract["id"],
            compliance_submission_payload("TX-51.9246", "NCAA-2026-12.5"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.decide_compliance(
            contract["id"], compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        ),
        expected_status=200,
    )
    validate_success(
        api.activate_deal_contract(contract["id"], {}, make_director_headers()),
        expected_status=200,
    )

    appearance = validate_success(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("APPEARANCE", 60000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    post = validate_success(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("SOCIAL_POST", 40000, "2026-09-15T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )

    entered = validate_success(
        api.change_athlete_eligibility(
            athlete["id"],
            eligibility_change_payload("ENTER_PORTAL"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )
    assert entered["eligibility_status"] == "PORTAL_ENTERED"

    version = read_contract(api, contract["id"])["version"]
    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                50000,
                expected_deal_contract_version=version,
            ),
            make_treasury_headers("treasury-3"),
        ),
        expected_status=201,
    )
    assert_release_money(
        release,
        status="QUEUED",
        withholding_basis="BACKUP",
        withholding_amount_cents=12000,
        initiated_by_user_id="treasury-3",
    )
    return {
        "collective_id": collective["id"],
        "athlete_id": athlete["id"],
        "contract_id": contract["id"],
        "appearance_id": appearance["id"],
        "post_id": post["id"],
        "release_id": release["id"],
    }


def test_completing_a_transfer_terminates_the_contract_and_forfeits_its_deliverables(api):
    """TRANSFERRED_OUT reaches the contract, and the contract reaches its deliverables.

    PRD s3.7: "`COMPLETE_TRANSFER` moves `PORTAL_ENTERED -> TRANSFERRED_OUT` ... Every
    contract of the athlete whose `lifecycle_status` is `DRAFT` or `ACTIVE` is terminated
    with `termination_reason` `TRANSFER_OUT` ... and each of those terminations then runs
    its own deliverable-forfeit and release-void cascade". PRD s3.9 forfeits "every
    deliverable of the contract whose `status` is `PENDING`, `SUBMITTED` or `REJECTED` ...
    with `payout_eligible_cents` set to 0" and re-derives
    `deliverable_value_total_cents` "with those forfeited rows excluded".

    Design: Difficulty/transitive_cascade/athlete_transfer_terminates_contract_forfeits_deliverables_voids_queued_release
    """
    ctx = _portal_athlete_with_a_queued_release(api)

    transferred = validate_success(
        api.change_athlete_eligibility(
            ctx["athlete_id"],
            eligibility_change_payload("COMPLETE_TRANSFER"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )
    assert transferred["eligibility_status"] == "TRANSFERRED_OUT"

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_dimensions(contract, lifecycle_status="TERMINATED")
    assert_contract_money(
        contract, termination_reason="TRANSFER_OUT", deliverable_value_total_cents=0
    )

    for deliverable_id in (ctx["appearance_id"], ctx["post_id"]):
        assert_deliverable_scoring(
            read_deliverable(api, deliverable_id),
            status="FORFEITED",
            payout_eligible_cents=0,
        )


def test_the_transfer_voids_the_queued_release_and_demands_no_clawback(api):
    """A voided release moves no money, so the clawback figure evaluates to 0.

    PRD s3.9: "then every payment release of the contract still in `QUEUED` becomes
    `VOIDED`", and "a `VOIDED` release moves no money at all: neither the collective
    ledger nor the athlete's tax ledger is affected by one." With `released_total_cents`
    at zero the cap "is the `released_total_cents` multiplied by that percentage" and the
    clawback "is then the smaller of the unearned figure and the cap, and never below
    zero" (PRD s3.9), while PRD s2.10 drops the terminated contract out of
    `committed_unreleased_cents`.

    Design: Difficulty/transitive_cascade/athlete_transfer_terminates_contract_forfeits_deliverables_voids_queued_release
    """
    ctx = _portal_athlete_with_a_queued_release(api)

    validate_success(
        api.change_athlete_eligibility(
            ctx["athlete_id"],
            eligibility_change_payload("COMPLETE_TRANSFER"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )

    assert_release_money(read_release(api, ctx["release_id"]), status="VOIDED")

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(
        contract, released_total_cents=0, clawback_amount_cents=0
    )
    assert_contract_dimensions(contract, payment_status="UNPAID")

    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]),
        tax_year_gross_paid_cents=0,
        annual_committed_value_cents=0,
        eligibility_status="TRANSFERRED_OUT",
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]),
        settled_net_funds_cents=487470,
        committed_unreleased_cents=0,
        released_total_cents=0,
        funding_posture="OPEN",
    )
