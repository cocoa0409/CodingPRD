"""Boundary walks: the exact 75 percent coverage ratio and the empty eligible set.

PRD s2.10 cross-multiplies the coverage comparison in integers, and PRD s3.8 refuses a
roster batch whose eligible set resolves to no athlete at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_NO_ELIGIBLE_ATHLETES
from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contribution_money,
    assert_error_envelope_shape,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    contribution_payload,
    deal_contract_payload,
    eligibility_change_payload,
    roster_allocation_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_open_tier,
    read_athlete,
    read_collective,
)
from test_helpers.test_users import (
    make_compliance_headers,
    make_director_headers,
)


def _collective_with_exactly_three_hundred_thousand_available(api):
    """A collective whose only gift nets exactly 300000 cents of UNRESTRICTED funds.

    Nothing is committed yet, so PRD s2.10 leaves the posture at OPEN and the contract
    creations below are admitted.
    """
    collective = build_collective(
        api,
        "011100",
        name="Gator Boundary Fund",
        institution_name="Florida Institution B",
        home_state_code="FL",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T2", 75000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Pia Papa",
        email="pia@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                307723,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        contribution, processing_fee_cents=7723, net_amount_cents=300000
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-quin",
        full_name="Quin Quebec",
        sport="WOMENS_BASKETBALL",
        class_year=2030,
    )
    before = read_collective(api, collective["id"])
    assert_collective_ledger(
        before,
        settled_net_funds_cents=300000,
        released_total_cents=0,
        committed_unreleased_cents=0,
        funding_posture="OPEN",
    )
    return {"collective_id": collective["id"], "athlete_id": athlete["id"]}


def _commit(api, collective_id, athlete_id, total_value_cents):
    return read_data(
        api.create_deal_contract(
            deal_contract_payload(
                collective_id,
                athlete_id,
                total_value_cents,
                effective_start_at="2026-08-01T00:00:00Z",
                effective_end_at="2026-12-31T00:00:00Z",
                funding_designation="UNRESTRICTED",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )


def test_coverage_of_exactly_three_quarters_lands_on_restricted(api):
    """300000 * 100 == 400000 * 75, so the inclusive comparison yields RESTRICTED.

    PRD s2.10: "if the available balance multiplied by 100 is greater than or equal to
    the committed figure multiplied by 75, the posture is `RESTRICTED`", and "That
    comparison is performed in cross-multiplied integer form and never by dividing to
    produce a coverage percentage, so a collective whose available balance covers exactly
    three quarters of its commitments lands on `RESTRICTED` rather than on `FROZEN`."

    Design: Difficulty/boundary_precision_check/funding_posture_restricted_at_exact_seventy_five_percent
    """
    ctx = _collective_with_exactly_three_hundred_thousand_available(api)

    contract = _commit(api, ctx["collective_id"], ctx["athlete_id"], 400000)
    assert_contract_dimensions(contract, lifecycle_status="DRAFT")

    at_boundary = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(
        at_boundary,
        settled_net_funds_cents=300000,
        committed_unreleased_cents=400000,
        funding_posture="RESTRICTED",
    )


def test_one_further_cent_of_commitment_flips_the_posture_to_frozen(api):
    """Committing 400001 makes 30000000 < 30000075, so the next recomputation freezes.

    PRD s2.10: "In every remaining case the posture is `FROZEN`", and the posture "is
    re-derived and persisted at the end of every request that changes the collective's
    `settled_net_funds_cents` or its `committed_unreleased_cents`". PRD s2.10 also admits
    the second creation, since only a pre-request `FROZEN` posture refuses one and the
    pre-request posture here is still RESTRICTED.

    Design: Difficulty/boundary_precision_check/funding_posture_restricted_at_exact_seventy_five_percent
    """
    ctx = _collective_with_exactly_three_hundred_thousand_available(api)
    _commit(api, ctx["collective_id"], ctx["athlete_id"], 400000)
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), funding_posture="RESTRICTED"
    )

    one_cent_more = _commit(api, ctx["collective_id"], ctx["athlete_id"], 1)
    assert_contract_dimensions(one_cent_more, lifecycle_status="DRAFT")

    frozen = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(
        frozen,
        settled_net_funds_cents=300000,
        committed_unreleased_cents=400001,
        funding_posture="FROZEN",
    )


def _collective_with_no_eligible_footballer(api):
    """Two athletes, neither of whom qualifies for a FOOTBALL batch.

    One footballer has entered the transfer portal and the other athlete plays SOFTBALL,
    so the input set of PRD s3.8 — "every athlete of that collective whose `sport` equals
    the target sport and whose `eligibility_status` is `ENROLLED`" — is empty.
    """
    collective = build_collective(
        api,
        "012100",
        name="Empty Set Collective",
        institution_name="Texas Institution C",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T3", 120000, 3)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Ravi Romeo",
        email="ravi@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                2000000,
                designation="ROSTER_POOL",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(contribution, net_amount_cents=1958000)

    footballer = build_athlete(
        api,
        collective["id"],
        "ath-rita",
        full_name="Rita Romeo",
        sport="FOOTBALL",
        class_year=2028,
    )
    softballer = build_athlete(
        api,
        collective["id"],
        "ath-sam",
        full_name="Sam Sierra",
        sport="SOFTBALL",
        class_year=2028,
    )
    validate_success(
        api.change_athlete_eligibility(
            footballer["id"],
            eligibility_change_payload("ENTER_PORTAL"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )
    before = read_collective(api, collective["id"])
    assert_collective_ledger(before, funding_posture="OPEN")
    return {
        "collective_id": collective["id"],
        "footballer_id": footballer["id"],
        "softballer_id": softballer["id"],
        "version": before["version"],
    }


def _football_batch(collective_id, expected_collective_version):
    return roster_allocation_payload(
        collective_id,
        "B9",
        "FOOTBALL",
        1000000,
        "EQUAL_SHARE",
        "2026-08-01T00:00:00Z",
        "2026-12-31T00:00:00Z",
        expected_collective_version=expected_collective_version,
        funding_designation="ROSTER_POOL",
    )


def test_a_batch_whose_eligible_set_is_empty_is_refused_wholesale(api):
    """Neither athlete qualifies, so the batch is refused instead of dividing by zero.

    PRD s3.8: "The batch's input set is every athlete of that collective whose `sport`
    equals the target sport and whose `eligibility_status` is `ENROLLED`; athletes in
    `PORTAL_ENTERED`, `TRANSFERRED_OUT` or `INELIGIBLE` are excluded from the batch
    entirely and receive no contract. If the input set resolves to no athlete at all, the
    batch is refused with `ERR_NO_ELIGIBLE_ATHLETES`." PRD s3.8 also makes the batch
    "all-or-nothing", so nothing is minted and no committed figure moves.

    Design: Difficulty/boundary_precision_check/roster_batch_requires_nonempty_eligible_athlete_set
    """
    ctx = _collective_with_no_eligible_footballer(api)

    response = api.create_roster_allocation(
        _football_batch(ctx["collective_id"], ctx["version"]), make_director_headers()
    )
    validate_error(response, ERR_NO_ELIGIBLE_ATHLETES, expected_status=422)
    assert_error_envelope_shape(response)

    after = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(
        after, committed_unreleased_cents=0, funding_posture="OPEN"
    )
    assert after["version"] == ctx["version"], (
        "A refused batch does not bump the collective's version guard"
    )
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["footballer_id"]), annual_committed_value_cents=0
    )
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["softballer_id"]), annual_committed_value_cents=0
    )

    listed = api.list_deal_contracts(
        {"allocation_batch_code": "B9"}, make_director_headers()
    )
    validate_success(listed, expected_status=200)
    assert rows_of(listed) == [], "No contract may carry the refused batch code"


def test_the_same_batch_succeeds_once_one_footballer_is_enrolled_again(api):
    """Withdrawing from the portal restores the input set, and the identical batch mints one contract.

    PRD s3.7: "`WITHDRAW_FROM_PORTAL` moves `PORTAL_ENTERED -> ENROLLED`", which returns
    the footballer to the input set of PRD s3.8. The SOFTBALL athlete still does not match
    the requested sport, so the batch divides the whole 1000000-cent pool over exactly one
    athlete and reports an `allocated_total_cents` that "always equals the
    `pool_amount_cents`" (PRD s3.8).

    Design: Difficulty/boundary_precision_check/roster_batch_requires_nonempty_eligible_athlete_set
    """
    ctx = _collective_with_no_eligible_footballer(api)
    refused = api.create_roster_allocation(
        _football_batch(ctx["collective_id"], ctx["version"]), make_director_headers()
    )
    validate_error(refused, ERR_NO_ELIGIBLE_ATHLETES, expected_status=422)

    validate_success(
        api.change_athlete_eligibility(
            ctx["footballer_id"],
            eligibility_change_payload("WITHDRAW_FROM_PORTAL"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )

    report = read_data(
        api.create_roster_allocation(
            _football_batch(ctx["collective_id"], ctx["version"]),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert report["created_contract_count"] == 1
    assert report["allocated_total_cents"] == 1000000
    assert report["remainder_cents"] == 0
    assert report["min_share_cents"] == 1000000
    assert report["max_share_cents"] == 1000000

    assert_athlete_tax_ledger(
        read_athlete(api, ctx["footballer_id"]),
        annual_committed_value_cents=1000000,
        eligibility_status="ENROLLED",
    )
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["softballer_id"]), annual_committed_value_cents=0
    )
