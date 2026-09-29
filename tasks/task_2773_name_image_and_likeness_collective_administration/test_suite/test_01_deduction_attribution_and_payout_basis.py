"""Two-variant calculations: deduction attribution and deliverable payout basis.

PRD s3.6 states that the AT_RECEIPT and YEAR_END_RECOMPUTE variants differ only in
the walk order, and PRD s3.9 states that the payout basis is selected from the
parent contract's deal_kind.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_collective_ledger,
    assert_contribution_money,
    assert_deliverable_scoring,
    assert_donor_ledger,
    read_data,
)
from test_helpers.factories import (
    billing_run_payload,
    compliance_decision_payload,
    compliance_submission_payload,
    contribution_payload,
    deal_contract_payload,
    deliverable_payload,
    evidence_payload,
    review_payload,
    roster_allocation_payload,
    submission_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_donor,
    build_funded_collective,
    build_open_tier,
    build_collective,
    move_clock,
    read_collective,
    read_contract,
    read_deliverable,
    read_donor,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def _backdated_gift_pair(api):
    """A charitable collective with two gifts keyed in reverse chronological order.

    Gift A is recorded first at clock 2026-08-20; the clock is then moved back to
    2026-08-10 and gift B is recorded, so sequence_no order and received_at order
    disagree (PRD s2.5 permits moving the clock backward).
    """
    collective = build_collective(
        api,
        "001100",
        name="Buckeye NIL Trust",
        institution_name="Ohio State Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    tier = build_open_tier(api, collective["id"], "T3", 100000, 3)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Dana Donor",
        email="dana@example.com",
        donor_kind="INDIVIDUAL",
        annual_agi_cents=1000000,
    )

    move_clock(api, "2026-08-20T00:00:00Z")
    gift_a = validate_success(
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

    move_clock(api, "2026-08-10T00:00:00Z")
    gift_b = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                410287,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    return {
        "collective_id": collective["id"],
        "donor_id": donor["id"],
        "gift_a": gift_a,
        "gift_b": gift_b,
    }


def test_at_receipt_attribution_consumes_the_ceiling_in_sequence_no_order(api):
    """The AT_RECEIPT variant walks the donor's settled gifts by ascending sequence_no.

    PRD s3.6: "The `AT_RECEIPT` variant runs whenever a contribution settles, and it
    walks the donor's qualifying rows in ascending contribution `sequence_no` — the
    order in which this server recorded them." The INDIVIDUAL ceiling is
    floor(1000000 * 60 / 100) = 600000, so the first-keyed gift takes its whole
    500000 net and the second-keyed gift takes only the remaining 100000.

    Design: Difficulty/dual_variant_calc/deduction_attribution_diverges_between_at_receipt_and_year_end
    """
    state = _backdated_gift_pair(api)

    assert_contribution_money(
        state["gift_a"],
        gross_amount_cents=512851,
        processing_fee_cents=12851,
        net_amount_cents=500000,
        deductible_amount_cents=500000,
        deduction_variant="AT_RECEIPT",
        status="SETTLED",
    )
    assert_contribution_money(
        state["gift_b"],
        gross_amount_cents=410287,
        processing_fee_cents=10287,
        net_amount_cents=400000,
        deductible_amount_cents=100000,
        deduction_variant="AT_RECEIPT",
        status="SETTLED",
    )

    gift_a = read_data(api.get_contribution(state["gift_a"]["id"], make_treasury_headers()))
    assert gift_a["deductible_amount_cents"] == 500000
    assert gift_a["sequence_no"] < state["gift_b"]["sequence_no"]

    donor = read_donor(api, state["donor_id"])
    assert_donor_ledger(
        donor,
        lifetime_settled_cents=900000,
        lifetime_deductible_cents=600000,
        status="ACTIVE",
    )


def test_year_end_recompute_reattributes_the_same_ceiling_by_received_at(api):
    """The YEAR_END_RECOMPUTE variant restates attribution against the true chronology.

    PRD s3.6: "The `YEAR_END_RECOMPUTE` variant runs only during a year-end tax
    recompute, and it walks the same rows in ascending `received_at`, using ascending
    `sequence_no` as the tie-break". The backdated gift B is therefore reached first
    and takes its whole 400000, leaving 200000 of the 600000 ceiling for gift A,
    while "the variants always agree on the donor's total deductible amount", which
    is why deduction_delta_cents nets to zero.

    Design: Difficulty/dual_variant_calc/deduction_attribution_diverges_between_at_receipt_and_year_end
    """
    state = _backdated_gift_pair(api)

    report = read_data(
        api.create_billing_run(
            state["collective_id"],
            billing_run_payload("YEAR_END_TAX_RECOMPUTE"),
            make_treasury_headers(),
        )
    )
    assert report["run_kind"] == "YEAR_END_TAX_RECOMPUTE"
    assert report["recomputed_contribution_count"] == 2
    assert report["deduction_delta_cents"] == 0

    gift_a = read_data(api.get_contribution(state["gift_a"]["id"], make_treasury_headers()))
    gift_b = read_data(api.get_contribution(state["gift_b"]["id"], make_treasury_headers()))
    assert_contribution_money(
        gift_a,
        net_amount_cents=500000,
        deductible_amount_cents=200000,
        deduction_variant="YEAR_END_RECOMPUTE",
    )
    assert_contribution_money(
        gift_b,
        net_amount_cents=400000,
        deductible_amount_cents=400000,
        deduction_variant="YEAR_END_RECOMPUTE",
    )
    assert gift_a["deductible_amount_cents"] + gift_b["deductible_amount_cents"] == 600000

    donor = read_donor(api, state["donor_id"])
    assert_donor_ledger(
        donor, lifetime_settled_cents=900000, lifetime_deductible_cents=600000
    )


def _roster_and_individual_posts(api):
    """One ROSTER_SHARE contract worth 333333 and one INDIVIDUAL contract worth 200000.

    Both carry an identical 200000-cent SOCIAL_POST with one evidence record,
    submitted on time, so only the parent contract's deal_kind differs.
    """
    funded = build_funded_collective(
        api,
        "002200",
        2000000,
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        designation="ROSTER_POOL",
        tier_code="T2",
        annual_dues_cents=50000,
        benefit_rank=2,
        email="rex@example.com",
        name="Lone Star Collective",
        institution_name="Texas Institution",
    )
    validate_success(
        api.create_contribution(
            contribution_payload(
                funded["donor_id"],
                512851,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )

    athlete_one = build_athlete(
        api, funded["collective_id"], "ath-alpha", full_name="Ann Alpha", sport="FOOTBALL"
    )
    athlete_two = build_athlete(
        api, funded["collective_id"], "ath-bravo", full_name="Bo Bravo", sport="FOOTBALL"
    )
    build_athlete(
        api,
        funded["collective_id"],
        "ath-charlie",
        full_name="Cy Charlie",
        sport="FOOTBALL",
        class_year=2029,
    )

    collective = read_collective(api, funded["collective_id"])
    batch = read_data(
        api.create_roster_allocation(
            roster_allocation_payload(
                funded["collective_id"],
                "B1",
                "FOOTBALL",
                1000000,
                "EQUAL_SHARE",
                "2026-08-01T00:00:00Z",
                "2026-12-31T00:00:00Z",
                expected_collective_version=collective["version"],
                funding_designation="ROSTER_POOL",
                exclusivity_category="NONE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )

    # An allocation_batch_code together with an athlete_id addresses one share of a
    # batch without treating any identifier as a business selector (PRD s3.8).
    listed = read_data(
        api.list_deal_contracts(
            {"allocation_batch_code": "B1", "athlete_id": athlete_two["id"]},
            make_director_headers(),
        )
    )
    roster_contract_id = listed[0]["id"]

    validate_success(
        api.submit_compliance_packet(
            roster_contract_id,
            compliance_submission_payload("TX-NIL-51.9246", "NCAA-2024-12.5"),
            make_director_headers(),
        )
    )
    validate_success(
        api.decide_compliance(
            roster_contract_id, compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        )
    )
    validate_success(api.activate_deal_contract(roster_contract_id, {}, make_director_headers()))

    roster_post = validate_success(
        api.create_deliverable(
            roster_contract_id,
            deliverable_payload("SOCIAL_POST", 200000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    roster_appearance = validate_success(
        api.create_deliverable(
            roster_contract_id,
            deliverable_payload("APPEARANCE", 100000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )

    individual_contract = validate_success(
        api.create_deal_contract(
            deal_contract_payload(
                funded["collective_id"],
                athlete_one["id"],
                200000,
                funding_designation="UNRESTRICTED",
                exclusivity_category="NONE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_compliance_packet(
            individual_contract["id"],
            compliance_submission_payload("TX-NIL-51.9246", "NCAA-2024-12.5"),
            make_director_headers(),
        )
    )
    validate_success(
        api.decide_compliance(
            individual_contract["id"],
            compliance_decision_payload("ACCEPT"),
            make_reviewer_headers(),
        )
    )
    validate_success(
        api.activate_deal_contract(individual_contract["id"], {}, make_director_headers())
    )
    individual_post = validate_success(
        api.create_deliverable(
            individual_contract["id"],
            deliverable_payload("SOCIAL_POST", 200000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )

    for deliverable_id, label in (
        (roster_post["id"], "roster-post-metrics"),
        (individual_post["id"], "individual-post-metrics"),
    ):
        validate_success(
            api.add_evidence(
                deliverable_id,
                evidence_payload("ANALYTICS_SCREENSHOT", label),
                make_director_headers(),
            ),
            expected_status=201,
        )
        validate_success(
            api.submit_deliverable(
                deliverable_id,
                submission_payload("2026-08-05T00:00:00Z"),
                make_director_headers(),
            )
        )

    return {
        "batch": batch,
        "roster_contract_id": roster_contract_id,
        "roster_post_id": roster_post["id"],
        "roster_appearance_id": roster_appearance["id"],
        "individual_contract_id": individual_contract["id"],
        "individual_post_id": individual_post["id"],
    }


def test_roster_share_post_is_scored_on_a_contract_share_basis(api):
    """A ROSTER_SHARE parent selects CONTRACT_SHARE_BASIS and a floored proportional share.

    PRD s3.9: "When the parent contract's `deal_kind` is `ROSTER_SHARE`, the
    `payout_basis` is `CONTRACT_SHARE_BASIS` and the base is a proportional share of
    the contract's face value: the contract's `total_value_cents` multiplied by this
    deliverable's `unit_value_cents`, divided by the contract's
    `deliverable_value_total_cents`, with the quotient floored to a whole cent."
    Here that is floor(333333 * 200000 / 300000) = 222222 on an on-time submission.

    Design: Difficulty/dual_variant_calc/roster_share_payout_diverges_from_strict_unit_basis
    """
    state = _roster_and_individual_posts(api)

    batch = state["batch"]
    assert batch["created_contract_count"] == 3
    assert batch["min_share_cents"] == 333333
    assert batch["max_share_cents"] == 333334
    assert batch["remainder_cents"] == 1

    contract = read_contract(api, state["roster_contract_id"])
    assert contract["deal_kind"] == "ROSTER_SHARE"
    assert contract["total_value_cents"] == 333333
    assert contract["deliverable_value_total_cents"] == 300000

    verified = read_data(
        api.review_deliverable(
            state["roster_post_id"], review_payload("VERIFY"), make_compliance_headers("compliance-1")
        )
    )
    assert_deliverable_scoring(
        verified,
        status="VERIFIED",
        payout_basis="CONTRACT_SHARE_BASIS",
        payout_eligible_cents=222222,
        late_flag=False,
    )
    assert verified["unit_value_cents"] == 200000

    appearance = read_deliverable(api, state["roster_appearance_id"])
    assert_deliverable_scoring(appearance, status="PENDING", payout_eligible_cents=0)


def test_individual_post_of_identical_unit_value_is_scored_on_a_strict_unit_basis(api):
    """An INDIVIDUAL parent selects STRICT_UNIT_BASIS and pays the unit value itself.

    PRD s3.9: "When the parent contract's `deal_kind` is `INDIVIDUAL`, the
    `payout_basis` is `STRICT_UNIT_BASIS` and the base is simply the deliverable's own
    `unit_value_cents`." The same 200000-cent social post therefore pays 200000 here
    while its roster-share twin pays 222222, and the only difference is the parent's
    deal_kind.

    Design: Difficulty/dual_variant_calc/roster_share_payout_diverges_from_strict_unit_basis
    """
    state = _roster_and_individual_posts(api)

    individual = read_contract(api, state["individual_contract_id"])
    assert individual["deal_kind"] == "INDIVIDUAL"
    assert individual["deliverable_value_total_cents"] == 200000

    verified_individual = read_data(
        api.review_deliverable(
            state["individual_post_id"],
            review_payload("VERIFY"),
            make_compliance_headers("compliance-1"),
        )
    )
    assert_deliverable_scoring(
        verified_individual,
        status="VERIFIED",
        payout_basis="STRICT_UNIT_BASIS",
        payout_eligible_cents=200000,
        late_flag=False,
    )

    verified_roster = read_data(
        api.review_deliverable(
            state["roster_post_id"],
            review_payload("VERIFY"),
            make_compliance_headers("compliance-1"),
        )
    )
    assert verified_roster["unit_value_cents"] == verified_individual["unit_value_cents"]
    assert (
        verified_roster["payout_eligible_cents"]
        - verified_individual["payout_eligible_cents"]
        == 22222
    )

    collective = read_collective(api, individual["collective_id"])
    assert_collective_ledger(collective, settled_net_funds_cents=2458000)
