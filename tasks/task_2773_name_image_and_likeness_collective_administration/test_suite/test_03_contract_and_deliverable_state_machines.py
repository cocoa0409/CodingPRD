"""Non-linear state machines: three parallel contract dimensions and a submit/reject loop.

PRD s3.8 carries three independent dimensions on one contract row, and PRD s3.9 runs a
SUBMITTED/REJECTED loop whose exit is governed by an accumulated counter.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_RESUBMISSION_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_deliverable_scoring,
    assert_error_envelope_shape,
    assert_release_money,
    assert_timestamp_equals,
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
    submission_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_open_tier,
    read_contract,
    read_deliverable,
)
from test_helpers.test_users import (
    make_compliance_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def _returned_then_accepted_contract(api):
    """A 100000-cent contract whose disclosure was returned once and then accepted.

    The collective holds 194970 cents of settled UNRESTRICTED net funds, and the
    athlete has a W9 on file, so a later release withholds nothing and only the
    payment dimension can move.
    """
    collective = build_collective(
        api,
        "005500",
        name="Sunshine Collective",
        institution_name="Florida Institution",
        home_state_code="FL",
        association_ruleset="NAIA",
    )
    tier = build_open_tier(api, collective["id"], "T2", 60000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Gus Giver",
        email="gus@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                200000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        contribution,
        processing_fee_cents=5030,
        net_amount_cents=194970,
        status="SETTLED",
    )

    athlete = build_athlete(
        api,
        collective["id"],
        "ath-gia",
        full_name="Gia Golf",
        sport="MENS_BASKETBALL",
        class_year=2029,
    )
    documented = validate_success(
        api.patch_athlete_tax_profile(
            athlete["id"],
            athlete_tax_profile_payload("W9"),
            make_treasury_headers(),
        ),
        expected_status=200,
    )
    assert documented["taxpayer_doc_on_file"] == "W9"

    contract = read_data(
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
    return {"collective_id": collective["id"], "contract": contract}


def test_disclosure_loop_advances_only_its_own_dimension(api):
    """A return, a refiling and an acceptance move disclosure while lifecycle stays DRAFT.

    PRD s3.8: "A `RETURN` advances `DISCLOSURE_PENDING -> DISCLOSURE_RETURNED` ... and
    increments `disclosure_return_count` by 1", a refiling "returns to from
    `DISCLOSURE_RETURNED`" the `DISCLOSURE_PENDING` position, and an "`ACCEPT` advances
    `DISCLOSURE_PENDING -> DISCLOSURE_ACCEPTED`". Throughout the loop the lifecycle
    dimension is untouched, because only activation "advanc[es] `DRAFT -> ACTIVE`".

    Design: Difficulty/non_linear_state_machine/deal_contract_three_dimensions_evolve_independently
    """
    ctx = _returned_then_accepted_contract(api)
    contract = ctx["contract"]
    assert_contract_dimensions(
        contract,
        lifecycle_status="DRAFT",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_PENDING",
    )
    assert contract["disclosure_return_count"] == 0
    assert_timestamp_equals(contract["disclosure_due_at"], "2026-08-08T00:00:00Z")

    validate_success(
        api.submit_compliance_packet(
            contract["id"],
            compliance_submission_payload("FL-1006.74", "NAIA-2024-A"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    returned = validate_success(
        api.decide_compliance(
            contract["id"],
            compliance_decision_payload(
                "RETURN", reviewer_note="missing state law citation detail"
            ),
            make_reviewer_headers(),
        ),
        expected_status=200,
    )
    assert_contract_dimensions(
        returned,
        lifecycle_status="DRAFT",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_RETURNED",
    )
    assert returned["disclosure_return_count"] == 1

    refiled = validate_success(
        api.submit_compliance_packet(
            contract["id"],
            compliance_submission_payload("FL-1006.74(2)(b)", "NAIA-2024-A"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    assert_contract_dimensions(
        refiled, lifecycle_status="DRAFT", disclosure_status="DISCLOSURE_PENDING"
    )
    assert refiled["disclosure_return_count"] == 1, (
        "Refiling does not reset the return counter"
    )

    accepted = validate_success(
        api.decide_compliance(
            contract["id"], compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        ),
        expected_status=200,
    )
    assert_contract_dimensions(
        accepted,
        lifecycle_status="DRAFT",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_ACCEPTED",
    )

    activated = validate_success(
        api.activate_deal_contract(contract["id"], {}, make_director_headers()),
        expected_status=200,
    )
    assert_contract_dimensions(
        activated,
        lifecycle_status="ACTIVE",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_ACCEPTED",
    )
    assert activated["disclosure_return_count"] == 1


def test_a_release_advances_only_the_payment_dimension(api):
    """The combined state (ACTIVE, PARTIALLY_PAID, DISCLOSURE_ACCEPTED) is reachable.

    PRD s3.9: "The contract's `payment_status` advances: from `UNPAID` to
    `PARTIALLY_PAID` when the contract's `released_total_cents` now stands strictly
    between zero and its `total_value_cents`", and PRD s3.8 keeps the lifecycle at
    ACTIVE because the COMPLETED bubble-up needs the contract to hold "at least one
    deliverable". The disclosure dimension is terminal at `DISCLOSURE_ACCEPTED`, so the
    release perturbs neither it nor the return counter.

    Design: Difficulty/non_linear_state_machine/deal_contract_three_dimensions_evolve_independently
    """
    ctx = _returned_then_accepted_contract(api)
    contract_id = ctx["contract"]["id"]

    validate_success(
        api.submit_compliance_packet(
            contract_id,
            compliance_submission_payload("FL-1006.74", "NAIA-2024-A"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.decide_compliance(
            contract_id,
            compliance_decision_payload(
                "RETURN", reviewer_note="missing state law citation detail"
            ),
            make_reviewer_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.submit_compliance_packet(
            contract_id,
            compliance_submission_payload("FL-1006.74(2)(b)", "NAIA-2024-A"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.decide_compliance(
            contract_id, compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        ),
        expected_status=200,
    )
    before = validate_success(
        api.activate_deal_contract(contract_id, {}, make_director_headers()),
        expected_status=200,
    )
    assert_contract_dimensions(
        before,
        lifecycle_status="ACTIVE",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_ACCEPTED",
    )

    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract_id,
                "CONTRACT_ADVANCE",
                60000,
                expected_deal_contract_version=before["version"],
            ),
            make_treasury_headers("treasury-2"),
        ),
        expected_status=201,
    )
    assert_release_money(
        release,
        status="RELEASED",
        withholding_basis="NONE",
        withholding_amount_cents=0,
        net_payable_cents=60000,
        initiated_by_user_id="treasury-2",
    )

    after = read_contract(api, contract_id)
    assert_contract_dimensions(
        after,
        lifecycle_status="ACTIVE",
        payment_status="PARTIALLY_PAID",
        disclosure_status="DISCLOSURE_ACCEPTED",
    )
    assert_contract_money(after, released_total_cents=60000)
    assert after["disclosure_return_count"] == before["disclosure_return_count"] == 1, (
        "A release must not perturb the disclosure dimension"
    )
    assert_timestamp_equals(after["disclosure_due_at"], before["disclosure_due_at"])


def _active_softball_deliverable(api):
    """One 50000-cent SOCIAL_POST on an ACTIVE contract that needed no disclosure.

    A face value of 50000 cents is below the disclosure threshold, so PRD s3.8 starts
    the contract in DISCLOSURE_NOT_REQUIRED and it activates without a packet.
    """
    collective = build_collective(
        api,
        "006600",
        name="Crimson Collective",
        institution_name="Alabama Institution",
        home_state_code="AL",
        association_ruleset="NCAA_2024",
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-hana",
        full_name="Hana Hotel",
        sport="SOFTBALL",
        class_year=2028,
        as_compliance=True,
    )
    contract = read_data(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                50000,
                effective_start_at="2026-08-01T00:00:00Z",
                effective_end_at="2026-12-31T00:00:00Z",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contract_dimensions(contract, disclosure_status="DISCLOSURE_NOT_REQUIRED")
    validate_success(
        api.activate_deal_contract(contract["id"], {}, make_director_headers()),
        expected_status=200,
    )
    deliverable = validate_success(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("SOCIAL_POST", 50000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.add_evidence(
            deliverable["id"],
            evidence_payload("ANALYTICS_SCREENSHOT", "post-v1"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    return {"contract_id": contract["id"], "deliverable_id": deliverable["id"]}


def _submit_then_reject(api, deliverable_id, performed_at, review_note):
    """One full lap of the loop: a submission followed by a rejection."""
    submitted = validate_success(
        api.submit_deliverable(
            deliverable_id,
            submission_payload(performed_at),
            make_director_headers(),
        ),
        expected_status=200,
    )
    rejected = validate_success(
        api.review_deliverable(
            deliverable_id,
            review_payload("REJECT", review_note=review_note),
            make_compliance_headers("compliance-3"),
        ),
        expected_status=200,
    )
    return submitted, rejected


def test_each_lap_of_the_submit_reject_loop_advances_only_the_counter(api):
    """Three laps leave the deliverable REJECTED with submission_count 3 and no payout.

    PRD s3.9: "Submission advances `PENDING -> SUBMITTED` or `REJECTED -> SUBMITTED`" and
    "increases `submission_count` by 1"; "`REJECT` advances `SUBMITTED -> REJECTED` ...
    it sets `payout_eligible_cents` to 0 and sends the work back for another attempt
    within the three-submission budget", and "A resubmission overwrites `performed_at`".

    Design: Difficulty/non_linear_state_machine/deliverable_submit_reject_cycle_hits_resubmission_limit
    """
    ctx = _active_softball_deliverable(api)
    deliverable_id = ctx["deliverable_id"]

    for lap, (performed_at, note) in enumerate(
        (
            ("2026-08-05T00:00:00Z", "image unreadable"),
            ("2026-08-06T00:00:00Z", "wrong platform"),
            ("2026-08-07T00:00:00Z", "still non-compliant"),
        ),
        start=1,
    ):
        submitted, rejected = _submit_then_reject(api, deliverable_id, performed_at, note)
        assert_deliverable_scoring(
            submitted, status="SUBMITTED", submission_count=lap, late_flag=False
        )
        assert_timestamp_equals(submitted["performed_at"], performed_at)
        assert_deliverable_scoring(
            rejected,
            status="REJECTED",
            submission_count=lap,
            payout_eligible_cents=0,
            evidence_count=1,
        )

    final = read_deliverable(api, deliverable_id)
    assert_deliverable_scoring(final, status="REJECTED", submission_count=3)
    assert_timestamp_equals(final["performed_at"], "2026-08-07T00:00:00Z")


def test_a_fourth_submission_is_refused_by_the_resubmission_limit(api):
    """The same trigger that worked on laps one to three is refused on lap four.

    PRD s3.9: "`submission_count` must be strictly below three, so a deliverable may be
    submitted at most three times counting the first: a fourth attempt is refused with
    `ERR_RESUBMISSION_LIMIT_REACHED` and the deliverable stays `REJECTED`." The state
    check passes here, since REJECTED is a legal from-state, so the counter is the only
    rule that can fire.

    Design: Difficulty/non_linear_state_machine/deliverable_submit_reject_cycle_hits_resubmission_limit
    """
    ctx = _active_softball_deliverable(api)
    deliverable_id = ctx["deliverable_id"]
    _submit_then_reject(api, deliverable_id, "2026-08-05T00:00:00Z", "image unreadable")
    _submit_then_reject(api, deliverable_id, "2026-08-06T00:00:00Z", "wrong platform")
    _submit_then_reject(api, deliverable_id, "2026-08-07T00:00:00Z", "still non-compliant")

    response = api.submit_deliverable(
        deliverable_id,
        submission_payload("2026-08-08T00:00:00Z"),
        make_director_headers(),
    )
    validate_error(response, ERR_RESUBMISSION_LIMIT_REACHED, expected_status=422)
    assert_error_envelope_shape(response)

    unchanged = read_deliverable(api, deliverable_id)
    assert_deliverable_scoring(
        unchanged,
        status="REJECTED",
        submission_count=3,
        evidence_count=1,
        payout_eligible_cents=0,
    )
    assert_timestamp_equals(unchanged["performed_at"], "2026-08-07T00:00:00Z")
    assert_contract_dimensions(
        read_contract(api, ctx["contract_id"]), payment_status="UNPAID"
    )
