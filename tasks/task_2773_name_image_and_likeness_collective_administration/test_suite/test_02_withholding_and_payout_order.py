"""Composed formulas: the treaty withholding switch and the payout penalty order.

PRD s3.9 fixes both compositions: the treaty ceiling is an inclusive eligibility
filter on the requested amount, and the lateness penalty is applied strictly after
the share floor.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_deliverable_scoring,
    assert_release_money,
    read_data,
)
from test_helpers.factories import (
    athlete_tax_profile_payload,
    compliance_decision_payload,
    compliance_submission_payload,
    contribution_payload,
    deal_contract_payload,
    deliverable_payload,
    evidence_payload,
    payment_release_payload,
    review_payload,
    roster_allocation_payload,
    submission_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_open_tier,
    move_clock,
    read_athlete,
    read_collective,
    read_contract,
    read_deliverable,
)
from test_helpers.test_users import (
    make_compliance_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def _treaty_claiming_nonresident(api):
    """An ACTIVE 600001-cent advance-only contract for a treaty-claiming nonresident.

    The collective holds 682470 cents of settled UNRESTRICTED net funds, and the
    contract carries no deliverable at all, so the only rules in play on a release
    are the withholding rules of PRD s3.9.
    """
    collective = build_collective(
        api,
        "003300",
        name="Golden Bear NIL",
        institution_name="California Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T1", 25000, 1)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Nora Nra-Funder",
        email="nora@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                700000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        contribution,
        gross_amount_cents=700000,
        processing_fee_cents=17530,
        net_amount_cents=682470,
        status="SETTLED",
    )

    athlete = build_athlete(
        api,
        collective["id"],
        "ath-ivan",
        full_name="Ivan Import",
        sport="BASEBALL",
        class_year=2027,
        tax_person_kind="NONRESIDENT_ALIEN",
        as_compliance=True,
    )
    validate_success(
        api.patch_athlete_tax_profile(
            athlete["id"],
            athlete_tax_profile_payload("W8BEN", treaty_exempt_claimed=True),
            make_compliance_headers(),
        ),
        expected_status=200,
    )

    contract = validate_success(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                600001,
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
            compliance_submission_payload("CA-AB131", "NCAA-2024-12.5"),
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
    activated = validate_success(
        api.activate_deal_contract(contract["id"], {}, make_director_headers()),
        expected_status=200,
    )
    return {
        "collective_id": collective["id"],
        "athlete_id": athlete["id"],
        "contract_id": contract["id"],
        "version": activated["version"],
    }


def test_treaty_claiming_release_at_the_ceiling_is_fully_exempt(api):
    """Exactly 300000 cents to a treaty-claiming nonresident withholds nothing.

    PRD s3.9: "If the athlete's `tax_person_kind` is `NONRESIDENT_ALIEN`, then when
    `treaty_exempt_claimed` is true **and** the `requested_amount_cents` is at most
    300,000 cents ... the `withholding_basis` is `NONE` and `withholding_amount_cents`
    is 0", and "The treaty ceiling comparison is inclusive: a release of exactly three
    thousand dollars to a treaty-claiming nonresident is fully exempt". The athlete
    still requires FORM_1042_S, which PRD s3.7 owes "at any nonzero amount, with no
    threshold at all".

    Design: Difficulty/combinatorial_formula/nra_treaty_ceiling_withholding_switch
    """
    ctx = _treaty_claiming_nonresident(api)

    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                ctx["contract_id"],
                "CONTRACT_ADVANCE",
                300000,
                expected_deal_contract_version=ctx["version"],
            ),
            make_treasury_headers("treasury-1"),
        ),
        expected_status=201,
    )
    assert_release_money(
        release,
        status="RELEASED",
        requested_amount_cents=300000,
        withholding_basis="NONE",
        withholding_amount_cents=0,
        net_payable_cents=300000,
        initiated_by_user_id="treasury-1",
    )

    athlete = read_athlete(api, ctx["athlete_id"])
    assert_athlete_tax_ledger(
        athlete,
        tax_year_gross_paid_cents=300000,
        tax_year_withheld_cents=0,
        tax_form_required="FORM_1042_S",
    )

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(contract, released_total_cents=300000)
    assert_contract_dimensions(
        contract, lifecycle_status="ACTIVE", payment_status="PARTIALLY_PAID"
    )


def test_one_cent_past_the_ceiling_withholds_thirty_percent_of_the_whole_amount(api):
    """300001 cents leaves the exemption entirely, so 90000 is withheld, not 0.30 of a cent.

    PRD s3.9: "in every other nonresident case the `withholding_basis` is
    `NRA_STATUTORY` and `withholding_amount_cents` is the `requested_amount_cents`
    multiplied by 30, divided by 100, with the quotient rounded half up to a whole
    cent", and "one cent more is withheld on the **whole** amount rather than on the
    excess". The two advances differ by one cent and their withholding differs by
    90000. PRD s3.8 keeps the lifecycle at ACTIVE because the COMPLETED bubble-up
    needs the contract to hold "at least one deliverable".

    Design: Difficulty/combinatorial_formula/nra_treaty_ceiling_withholding_switch
    """
    ctx = _treaty_claiming_nonresident(api)

    exempt = read_data(
        api.create_payment_release(
            payment_release_payload(
                ctx["contract_id"],
                "CONTRACT_ADVANCE",
                300000,
                expected_deal_contract_version=ctx["version"],
            ),
            make_treasury_headers("treasury-1"),
        ),
        expected_status=201,
    )
    assert_release_money(
        exempt, withholding_basis="NONE", withholding_amount_cents=0
    )

    bumped_version = read_contract(api, ctx["contract_id"])["version"]
    withheld = read_data(
        api.create_payment_release(
            payment_release_payload(
                ctx["contract_id"],
                "CONTRACT_ADVANCE",
                300001,
                expected_deal_contract_version=bumped_version,
            ),
            make_treasury_headers("treasury-1"),
        ),
        expected_status=201,
    )
    assert_release_money(
        withheld,
        status="RELEASED",
        requested_amount_cents=300001,
        withholding_basis="NRA_STATUTORY",
        withholding_amount_cents=90000,
        net_payable_cents=210001,
    )
    assert (
        withheld["withholding_amount_cents"] - exempt["withholding_amount_cents"]
    ) == 90000, "One boundary cent must swing the withholding by the full 90000"

    athlete = read_athlete(api, ctx["athlete_id"])
    assert_athlete_tax_ledger(
        athlete,
        tax_year_gross_paid_cents=600001,
        tax_year_withheld_cents=90000,
        tax_form_required="FORM_1042_S",
    )

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(contract, released_total_cents=600001)
    assert_contract_dimensions(
        contract, lifecycle_status="ACTIVE", payment_status="FULLY_PAID"
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]),
        settled_net_funds_cents=682470,
        released_total_cents=600001,
    )


def _late_roster_share_post(api):
    """A 333333-cent ROSTER_SHARE contract whose 200000-cent post was performed late.

    The batch divides 1000000 cents equally over three enrolled footballers, so the
    second athlete by sequence_no holds exactly 333333 cents, and the contract's two
    deliverables put deliverable_value_total_cents at exactly 300000.
    """
    collective = build_collective(
        api,
        "004400",
        name="Scarlet Share Collective",
        institution_name="Ohio Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T4", 400000, 4)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Paula Pool",
        email="paula@example.com",
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
    assert_contribution_money(
        contribution,
        processing_fee_cents=42000,
        net_amount_cents=1958000,
        status="SETTLED",
    )

    build_athlete(
        api, collective["id"], "ath-delta", full_name="Dee Delta", class_year=2028
    )
    second = build_athlete(
        api, collective["id"], "ath-echo", full_name="Eli Echo", class_year=2028
    )
    build_athlete(
        api, collective["id"], "ath-foxtrot", full_name="Fay Foxtrot", class_year=2029
    )

    collective_version = read_collective(api, collective["id"])["version"]
    report = read_data(
        api.create_roster_allocation(
            roster_allocation_payload(
                collective["id"],
                "B1",
                "FOOTBALL",
                1000000,
                "EQUAL_SHARE",
                "2026-08-01T00:00:00Z",
                "2026-12-31T00:00:00Z",
                expected_collective_version=collective_version,
                funding_designation="ROSTER_POOL",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )

    listed = validate_success(
        api.list_deal_contracts(
            {"allocation_batch_code": "B1", "athlete_id": second["id"]},
            make_director_headers(),
        ),
        expected_status=200,
    )
    share_contract_id = listed[0]["id"]

    validate_success(
        api.submit_compliance_packet(
            share_contract_id,
            compliance_submission_payload("OH-3345.56", "NCAA-2026-12.5"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.decide_compliance(
            share_contract_id,
            compliance_decision_payload("ACCEPT"),
            make_reviewer_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.activate_deal_contract(share_contract_id, {}, make_director_headers()),
        expected_status=200,
    )

    post = validate_success(
        api.create_deliverable(
            share_contract_id,
            deliverable_payload("SOCIAL_POST", 200000, "2026-08-20T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    appearance = validate_success(
        api.create_deliverable(
            share_contract_id,
            deliverable_payload("APPEARANCE", 100000, "2026-08-20T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.add_evidence(
            post["id"],
            evidence_payload("ANALYTICS_SCREENSHOT", "late-post-metrics"),
            make_director_headers(),
        ),
        expected_status=201,
    )

    move_clock(api, "2026-09-15T00:00:00Z")
    validate_success(
        api.submit_deliverable(
            post["id"],
            submission_payload("2026-09-01T00:00:00Z", submission_note="posted late"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    return {
        "report": report,
        "contract_id": share_contract_id,
        "post_id": post["id"],
        "appearance_id": appearance["id"],
    }


def test_late_penalty_is_applied_after_the_share_floor(api):
    """The floored share 222222 less 33333 is 188889; penalising the face value first gives 188888.

    PRD s3.9 pins the base for a ROSTER_SHARE parent as "the contract's
    `total_value_cents` multiplied by this deliverable's `unit_value_cents`, divided by
    the contract's `deliverable_value_total_cents`, with the quotient floored to a whole
    cent", and then "the lateness penalty is applied to that base ... The penalty is
    applied strictly **after** the share floor, never before". floor(333333 * 200000 /
    300000) = 222222 and round_half_up(222222 * 15 / 100) = 33333, so the figure is
    188889 to the cent.

    Design: Difficulty/combinatorial_formula/payout_share_floor_before_late_penalty_order_pinned
    """
    ctx = _late_roster_share_post(api)
    assert ctx["report"]["created_contract_count"] == 3, (
        "Three enrolled footballers must each receive one contract"
    )

    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(
        contract, total_value_cents=333333, deliverable_value_total_cents=300000
    )

    verified = read_data(
        api.review_deliverable(
            ctx["post_id"], review_payload("VERIFY"), make_compliance_headers("compliance-9")
        ),
        expected_status=200,
    )
    assert_deliverable_scoring(
        verified,
        status="VERIFIED",
        payout_basis="CONTRACT_SHARE_BASIS",
        payout_eligible_cents=188889,
        late_flag=True,
        verified_by_user_id="compliance-9",
    )
    assert 222222 - verified["payout_eligible_cents"] == 33333, (
        "The 15 percent penalty must bite on the floored share of 222222, "
        "which yields 188889 rather than the 188888 of the reversed order"
    )

    assert_deliverable_scoring(
        read_deliverable(api, ctx["appearance_id"]),
        status="PENDING",
        payout_eligible_cents=0,
    )


def test_a_timely_sibling_keeps_the_unpenalised_floored_share(api):
    """The on-time appearance scores its bare floored share of 111111, isolating the penalty.

    PRD s3.9: "if the `late_flag` is false, the `payout_eligible_cents` is the base
    unchanged", and PRD s3.9 sets `late_flag` "to true exactly when the supplied
    `performed_at` is strictly after the deliverable's `due_at`". Both deliverables
    hang off the same 333333-cent contract with the same 300000-cent
    deliverable_value_total_cents, so floor(333333 * 100000 / 300000) = 111111 stands
    unpenalised while the late 200000-cent post is cut from 222222 to 188889.

    Design: Difficulty/combinatorial_formula/payout_share_floor_before_late_penalty_order_pinned
    """
    ctx = _late_roster_share_post(api)

    late_post = read_data(
        api.review_deliverable(
            ctx["post_id"], review_payload("VERIFY"), make_compliance_headers("compliance-9")
        ),
        expected_status=200,
    )
    assert_deliverable_scoring(
        late_post, late_flag=True, payout_eligible_cents=188889
    )

    validate_success(
        api.add_evidence(
            ctx["appearance_id"],
            evidence_payload("SIGNED_ATTENDANCE_SHEET", "on-time-appearance"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_deliverable(
            ctx["appearance_id"],
            submission_payload("2026-08-15T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    timely = read_data(
        api.review_deliverable(
            ctx["appearance_id"],
            review_payload("VERIFY"),
            make_compliance_headers("compliance-9"),
        ),
        expected_status=200,
    )
    assert_deliverable_scoring(
        timely,
        status="VERIFIED",
        payout_basis="CONTRACT_SHARE_BASIS",
        payout_eligible_cents=111111,
        late_flag=False,
    )
