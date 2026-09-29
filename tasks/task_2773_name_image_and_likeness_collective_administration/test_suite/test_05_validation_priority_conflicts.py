"""Two requests that violate two rules at once, where the ladder of PRD s2.8 decides.

Contract lifecycle state sits at priority 17 and the payout ceiling at 45; the
child-belongs-to-parent check sits at priority 9 and the contract face value at 37.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CONTRACT_TERMINAL,
    ERR_DELIVERABLE_CONTRACT_MISMATCH,
    ERR_RELEASE_EXCEEDS_CONTRACT_VALUE,
    ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE,
)
from test_helpers.assertions import (
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_deliverable_scoring,
    assert_error_envelope_shape,
    read_data,
)
from test_helpers.factories import (
    compliance_decision_payload,
    compliance_submission_payload,
    contribution_payload,
    deal_contract_payload,
    deliverable_payload,
    evidence_payload,
    payment_release_payload,
    review_payload,
    submission_payload,
    termination_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_open_tier,
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


def _verified_sixty_thousand_deliverable(api):
    """An ACTIVE 100000-cent contract carrying one VERIFIED 60000-cent post.

    The post is scored on the strict unit basis of PRD s3.9, so its
    payout_eligible_cents is exactly its own 60000-cent unit value.
    """
    collective = build_collective(
        api,
        "009900",
        name="Buckeye Fiscal Trust",
        institution_name="Ohio Institution B",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T1", 20000, 1)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Lena Lima",
        email="lena@example.com",
    )
    validate_success(
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
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-milo",
        full_name="Milo Mike",
        sport="BASEBALL",
        class_year=2028,
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
            compliance_submission_payload("OH-3345.56", "NCAA-2024-12.5"),
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
    deliverable = validate_success(
        api.create_deliverable(
            contract["id"],
            deliverable_payload("SOCIAL_POST", 60000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.add_evidence(
            deliverable["id"],
            evidence_payload("ANALYTICS_SCREENSHOT", "post-ok"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_deliverable(
            deliverable["id"],
            submission_payload("2026-08-05T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    verified = validate_success(
        api.review_deliverable(
            deliverable["id"], review_payload("VERIFY"), make_compliance_headers("compliance-1")
        ),
        expected_status=200,
    )
    assert_deliverable_scoring(
        verified,
        status="VERIFIED",
        payout_basis="STRICT_UNIT_BASIS",
        payout_eligible_cents=60000,
        verified_by_user_id="compliance-1",
    )
    return {
        "collective_id": collective["id"],
        "contract_id": contract["id"],
        "deliverable_id": deliverable["id"],
    }


def _terminate_for_breach(api, contract_id):
    terminated = validate_success(
        api.terminate_deal_contract(
            contract_id, termination_payload("BREACH"), make_director_headers()
        ),
        expected_status=200,
    )
    assert_contract_dimensions(terminated, lifecycle_status="TERMINATED")
    return terminated


def test_a_terminal_contract_outranks_the_payout_ceiling(api):
    """One request breaks both rules; priority 17 answers before priority 45.

    PRD s2.8 orders "17. Contract lifecycle state — ... `ERR_CONTRACT_TERMINAL`, on ...
    payment release creation" ahead of "45. A deliverable payout stays inside the
    deliverable's eligible amount — `ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE`", and PRD s3.8
    states that "any operation attempted against a contract in one of them reports
    `ERR_CONTRACT_TERMINAL`". The 100000-cent request also exceeds the deliverable's
    60000-cent eligible amount, so the answer must still be the 409.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payment_release_against_terminated_contract
    """
    ctx = _verified_sixty_thousand_deliverable(api)
    terminated = _terminate_for_breach(api, ctx["contract_id"])

    response = api.create_payment_release(
        payment_release_payload(
            ctx["contract_id"],
            "DELIVERABLE_PAYOUT",
            100000,
            expected_deal_contract_version=terminated["version"],
            deliverable_id=ctx["deliverable_id"],
        ),
        make_treasury_headers("treasury-1"),
    )
    validate_error(response, ERR_CONTRACT_TERMINAL, expected_status=409)
    assert_error_envelope_shape(response)

    assert_deliverable_scoring(
        read_deliverable(api, ctx["deliverable_id"]),
        status="VERIFIED",
        payout_eligible_cents=60000,
    )
    contract = read_contract(api, ctx["contract_id"])
    assert_contract_money(contract, released_total_cents=0, clawback_amount_cents=0)
    assert_contract_dimensions(
        contract, lifecycle_status="TERMINATED", payment_status="UNPAID"
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), released_total_cents=0
    )


def test_both_the_state_rule_and_the_payout_ceiling_were_genuinely_violated(api):
    """The ceiling answers on an ACTIVE contract; the terminal state answers even within it.

    PRD s3.9 refuses a payout above the eligible amount — "the `requested_amount_cents`
    must not exceed the named deliverable's `payout_eligible_cents`, or the request is
    `ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE`" — which is what the very same 100000-cent
    request draws while the contract is still ACTIVE. Once the contract is TERMINATED,
    even a request of exactly 60000 that satisfies the ceiling reports
    `ERR_CONTRACT_TERMINAL` (PRD s3.8).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payment_release_against_terminated_contract
    """
    ctx = _verified_sixty_thousand_deliverable(api)
    active = read_contract(api, ctx["contract_id"])
    assert_contract_dimensions(active, lifecycle_status="ACTIVE")

    over_ceiling = api.create_payment_release(
        payment_release_payload(
            ctx["contract_id"],
            "DELIVERABLE_PAYOUT",
            100000,
            expected_deal_contract_version=active["version"],
            deliverable_id=ctx["deliverable_id"],
        ),
        make_treasury_headers("treasury-1"),
    )
    validate_error(over_ceiling, ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE, expected_status=422)

    terminated = _terminate_for_breach(api, ctx["contract_id"])
    within_ceiling = api.create_payment_release(
        payment_release_payload(
            ctx["contract_id"],
            "DELIVERABLE_PAYOUT",
            60000,
            expected_deal_contract_version=terminated["version"],
            deliverable_id=ctx["deliverable_id"],
        ),
        make_treasury_headers("treasury-1"),
    )
    validate_error(within_ceiling, ERR_CONTRACT_TERMINAL, expected_status=409)

    assert_contract_money(
        read_contract(api, ctx["contract_id"]), released_total_cents=0
    )


def _two_contracts_one_verified_on_the_second(api):
    """One athlete holding contract A (100000) and contract B (50000, with a VERIFIED post).

    Both contracts declare exclusivity_category NONE, so the window rule of PRD s3.8
    cannot fire, and the collective holds 979000 cents of settled UNRESTRICTED net funds.
    """
    collective = build_collective(
        api,
        "010100",
        name="Bay Area NIL",
        institution_name="California Institution C",
        home_state_code="CA",
        association_ruleset="NAIA",
    )
    tier = build_open_tier(api, collective["id"], "T5", 500000, 5)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Nils November",
        email="nils@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                1000000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert contribution["net_amount_cents"] == 979000
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-otis",
        full_name="Otis Oscar",
        sport="FOOTBALL",
        class_year=2029,
    )

    contract_a = validate_success(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                100000,
                effective_start_at="2026-08-01T00:00:00Z",
                effective_end_at="2026-12-31T00:00:00Z",
                funding_designation="UNRESTRICTED",
                exclusivity_category="NONE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_compliance_packet(
            contract_a["id"],
            compliance_submission_payload("CA-AB131", "NAIA-2024-A"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    validate_success(
        api.decide_compliance(
            contract_a["id"], compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        ),
        expected_status=200,
    )
    validate_success(
        api.activate_deal_contract(contract_a["id"], {}, make_director_headers()),
        expected_status=200,
    )

    contract_b = validate_success(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                50000,
                effective_start_at="2026-08-01T00:00:00Z",
                effective_end_at="2026-12-31T00:00:00Z",
                funding_designation="UNRESTRICTED",
                exclusivity_category="NONE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.activate_deal_contract(contract_b["id"], {}, make_director_headers()),
        expected_status=200,
    )
    deliverable_b = validate_success(
        api.create_deliverable(
            contract_b["id"],
            deliverable_payload("SOCIAL_POST", 50000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.add_evidence(
            deliverable_b["id"],
            evidence_payload("ANALYTICS_SCREENSHOT", "b-post"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_deliverable(
            deliverable_b["id"],
            submission_payload("2026-08-05T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    verified_b = validate_success(
        api.review_deliverable(
            deliverable_b["id"],
            review_payload("VERIFY"),
            make_compliance_headers("compliance-2"),
        ),
        expected_status=200,
    )
    assert_deliverable_scoring(
        verified_b, status="VERIFIED", payout_eligible_cents=50000
    )
    return {
        "collective_id": collective["id"],
        "contract_a_id": contract_a["id"],
        "contract_b_id": contract_b["id"],
        "deliverable_b_id": deliverable_b["id"],
    }


def test_a_foreign_deliverable_outranks_the_contract_face_value(api):
    """Naming contract B's deliverable on a release against contract A answers with the mismatch.

    PRD s2.8 orders "9. A named child belongs to the named parent —
    `ERR_DELIVERABLE_CONTRACT_MISMATCH` ... on payment release creation" well ahead of
    "37. A release stays inside the contract's face value —
    `ERR_RELEASE_EXCEEDS_CONTRACT_VALUE`", and PRD s3.9 requires that a supplied
    `deliverable_id` "must name a deliverable belonging to the named contract, or the
    request is `ERR_DELIVERABLE_CONTRACT_MISMATCH`". The 200000-cent request also breaks
    contract A's 100000-cent face value, so the referential answer must come first.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_release_with_foreign_deliverable
    """
    ctx = _two_contracts_one_verified_on_the_second(api)
    contract_a = read_contract(api, ctx["contract_a_id"])

    response = api.create_payment_release(
        payment_release_payload(
            ctx["contract_a_id"],
            "DELIVERABLE_PAYOUT",
            200000,
            expected_deal_contract_version=contract_a["version"],
            deliverable_id=ctx["deliverable_b_id"],
        ),
        make_treasury_headers("treasury-2"),
    )
    validate_error(response, ERR_DELIVERABLE_CONTRACT_MISMATCH, expected_status=409)
    assert_error_envelope_shape(response)

    assert_contract_money(read_contract(api, ctx["contract_a_id"]), released_total_cents=0)
    assert_contract_dimensions(
        read_contract(api, ctx["contract_a_id"]), payment_status="UNPAID"
    )
    assert_contract_money(read_contract(api, ctx["contract_b_id"]), released_total_cents=0)
    assert_deliverable_scoring(
        read_deliverable(api, ctx["deliverable_b_id"]), status="VERIFIED"
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), released_total_cents=0
    )


def test_both_the_referential_rule_and_the_face_value_rule_were_genuinely_violated(api):
    """A cheaper amount still reports the mismatch; a local deliverable reports the amount.

    PRD s3.9 refuses an over-value release — "the `requested_amount_cents` plus the
    contract's `released_total_cents` ... must not exceed the contract's
    `total_value_cents`, or the request is `ERR_RELEASE_EXCEEDS_CONTRACT_VALUE`" — which
    is what the same 200000-cent request draws once its `deliverable_id` names a
    VERIFIED deliverable of contract A itself, while a 50000-cent request against
    contract B's deliverable still reports `ERR_DELIVERABLE_CONTRACT_MISMATCH` (PRD s2.8
    priority 9).

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_release_with_foreign_deliverable
    """
    ctx = _two_contracts_one_verified_on_the_second(api)
    contract_a = read_contract(api, ctx["contract_a_id"])

    cheaper = api.create_payment_release(
        payment_release_payload(
            ctx["contract_a_id"],
            "DELIVERABLE_PAYOUT",
            50000,
            expected_deal_contract_version=contract_a["version"],
            deliverable_id=ctx["deliverable_b_id"],
        ),
        make_treasury_headers("treasury-2"),
    )
    validate_error(cheaper, ERR_DELIVERABLE_CONTRACT_MISMATCH, expected_status=409)

    own_deliverable = validate_success(
        api.create_deliverable(
            ctx["contract_a_id"],
            deliverable_payload("APPEARANCE", 100000, "2026-09-01T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.add_evidence(
            own_deliverable["id"],
            evidence_payload("SIGNED_ATTENDANCE_SHEET", "a-appearance"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_deliverable(
            own_deliverable["id"],
            submission_payload("2026-08-05T00:00:00Z"),
            make_director_headers(),
        ),
        expected_status=200,
    )
    verified = read_data(
        api.review_deliverable(
            own_deliverable["id"],
            review_payload("VERIFY"),
            make_compliance_headers("compliance-2"),
        ),
        expected_status=200,
    )
    assert_deliverable_scoring(
        verified, status="VERIFIED", payout_eligible_cents=100000
    )

    over_value = api.create_payment_release(
        payment_release_payload(
            ctx["contract_a_id"],
            "DELIVERABLE_PAYOUT",
            200000,
            expected_deal_contract_version=read_contract(api, ctx["contract_a_id"])["version"],
            deliverable_id=own_deliverable["id"],
        ),
        make_treasury_headers("treasury-2"),
    )
    validate_error(over_value, ERR_RELEASE_EXCEEDS_CONTRACT_VALUE, expected_status=422)

    assert_contract_money(read_contract(api, ctx["contract_a_id"]), released_total_cents=0)
