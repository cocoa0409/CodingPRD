"""Two gates that read another entity's state: an athlete's eligibility and an ancestor's posture.

PRD s3.8 refuses a contract while the athlete is not ENROLLED, and PRD s2.10 refuses a
release while the owning collective's pre-request posture is FROZEN.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ATHLETE_NOT_ENROLLED,
    ERR_COLLECTIVE_FUNDING_FROZEN,
)
from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_error_envelope_shape,
    assert_release_money,
    read_data,
)
from test_helpers.factories import (
    compliance_decision_payload,
    compliance_submission_payload,
    contribution_payload,
    deal_contract_payload,
    eligibility_change_payload,
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
)
from test_helpers.test_users import (
    make_compliance_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def _ineligible_athlete(api):
    """One athlete moved out of ENROLLED into INELIGIBLE, on an unfunded collective."""
    collective = build_collective(
        api,
        "013100",
        name="Tide Compliance Fund",
        institution_name="Alabama Institution B",
        home_state_code="AL",
        association_ruleset="NAIA",
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-tia",
        full_name="Tia Tango",
        sport="BASEBALL",
        class_year=2027,
        as_compliance=True,
    )
    declared = validate_success(
        api.change_athlete_eligibility(
            athlete["id"],
            eligibility_change_payload("DECLARE_INELIGIBLE"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )
    assert declared["eligibility_status"] == "INELIGIBLE"
    return {"collective_id": collective["id"], "athlete_id": athlete["id"]}


def _contract_body(collective_id, athlete_id):
    """The one contract body used for both the refused and the accepted attempt."""
    return deal_contract_payload(
        collective_id,
        athlete_id,
        100000,
        effective_start_at="2026-08-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )


def test_contract_creation_is_refused_while_the_athlete_is_ineligible(api):
    """The contract depends on the athlete's declared state, not on anything in its body.

    PRD s3.8: "The athlete's `eligibility_status` must be `ENROLLED`, or the request is
    `ERR_ATHLETE_NOT_ENROLLED` — a collective may not sign an athlete who is in the
    portal, has transferred out, or has been declared ineligible." Nothing is committed,
    so PRD s2.10 leaves the posture at OPEN and the posture gate cannot be the reason.

    Design: Difficulty/cross_entity_state_dependency/contract_creation_requires_athlete_enrolled
    """
    ctx = _ineligible_athlete(api)

    response = api.create_deal_contract(
        _contract_body(ctx["collective_id"], ctx["athlete_id"]), make_director_headers()
    )
    validate_error(response, ERR_ATHLETE_NOT_ENROLLED, expected_status=409)
    assert_error_envelope_shape(response)

    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]),
        annual_committed_value_cents=0,
        eligibility_status="INELIGIBLE",
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]),
        committed_unreleased_cents=0,
        funding_posture="OPEN",
    )


def test_the_identical_body_is_accepted_once_the_athlete_is_reinstated(api):
    """Only the athlete's state changed between the refusal and the acceptance.

    PRD s3.7: "`REINSTATE` moves `INELIGIBLE -> ENROLLED`", after which PRD s3.8 admits
    the creation and starts the row "at `version` 1 in `lifecycle_status` `DRAFT`". Its
    face value of 100000 cents is at or above the disclosure threshold, so PRD s3.8 starts
    it in `DISCLOSURE_PENDING`, and PRD s3.7 counts it into
    `annual_committed_value_cents`.

    Design: Difficulty/cross_entity_state_dependency/contract_creation_requires_athlete_enrolled
    """
    ctx = _ineligible_athlete(api)
    refused = api.create_deal_contract(
        _contract_body(ctx["collective_id"], ctx["athlete_id"]), make_director_headers()
    )
    validate_error(refused, ERR_ATHLETE_NOT_ENROLLED, expected_status=409)

    reinstated = validate_success(
        api.change_athlete_eligibility(
            ctx["athlete_id"],
            eligibility_change_payload("REINSTATE"),
            make_compliance_headers(),
        ),
        expected_status=200,
    )
    assert reinstated["eligibility_status"] == "ENROLLED"

    contract = read_data(
        api.create_deal_contract(
            _contract_body(ctx["collective_id"], ctx["athlete_id"]),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contract_dimensions(
        contract,
        lifecycle_status="DRAFT",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_PENDING",
    )
    assert_contract_money(contract, total_value_cents=100000)

    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]),
        annual_committed_value_cents=100000,
        eligibility_status="ENROLLED",
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), committed_unreleased_cents=100000
    )


def _frozen_collective_with_an_active_contract(api):
    """116970 cents of settled funds against a 200000-cent commitment, so the posture freezes.

    Activation still succeeds, because PRD s3.8 leaves it "deliberately **not** gated on
    the posture".
    """
    collective = build_collective(
        api,
        "014100",
        name="Frozen Posture Collective",
        institution_name="Ohio Institution C",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T1", 10000, 1)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Uma Uniform",
        email="uma@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                120000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        contribution, processing_fee_cents=3030, net_amount_cents=116970
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-vic",
        full_name="Vic Victor",
        sport="FOOTBALL",
        class_year=2028,
    )
    contract = validate_success(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                200000,
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
            compliance_submission_payload("OH-3345.56", "NCAA-2026-12.5"),
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
    assert_contract_dimensions(activated, lifecycle_status="ACTIVE")

    posture = read_collective(api, collective["id"])
    assert_collective_ledger(
        posture,
        settled_net_funds_cents=116970,
        committed_unreleased_cents=200000,
        funding_posture="FROZEN",
    )
    return {
        "collective_id": collective["id"],
        "athlete_id": athlete["id"],
        "donor_id": donor["id"],
        "contract_id": contract["id"],
        "version": activated["version"],
    }


def test_a_release_is_refused_while_the_owning_collective_is_frozen(api):
    """Every contract-local precondition passes; only the ancestor's posture refuses.

    PRD s2.10: "Creating a payment release is refused with
    `ERR_COLLECTIVE_FUNDING_FROZEN` while the pre-request posture is `FROZEN`." The
    contract is ACTIVE with disclosure accepted, and the requested 50000 sits inside both
    its 200000-cent face value and the 116970-cent UNRESTRICTED pool, so PRD s3.9's own
    ceilings are satisfied.

    Design: Difficulty/cross_entity_state_dependency/payment_release_blocked_while_collective_frozen
    """
    ctx = _frozen_collective_with_an_active_contract(api)

    response = api.create_payment_release(
        payment_release_payload(
            ctx["contract_id"],
            "CONTRACT_ADVANCE",
            50000,
            expected_deal_contract_version=ctx["version"],
        ),
        make_treasury_headers("treasury-4"),
    )
    validate_error(response, ERR_COLLECTIVE_FUNDING_FROZEN, expected_status=409)
    assert_error_envelope_shape(response)

    contract = read_contract(api, ctx["contract_id"])
    assert contract["version"] == ctx["version"], (
        "A refused release does not bump the parent contract's version"
    )
    assert_contract_money(contract, released_total_cents=0)
    assert_contract_dimensions(contract, payment_status="UNPAID")
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]),
        released_total_cents=0,
        funding_posture="FROZEN",
    )
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]), tax_year_gross_paid_cents=0
    )


def test_the_same_release_succeeds_once_new_funds_thaw_the_posture(api):
    """Funding the collective back to full coverage is the only change the release needs.

    PRD s2.10: "if the available balance is greater than or equal to the committed figure,
    the posture is `OPEN`", and the posture "is re-derived and persisted at the end of
    every request that changes the collective's `settled_net_funds_cents`". With the
    posture OPEN the release runs, and PRD s3.9 withholds on the backup basis because the
    US-person athlete has no W9 on file: 50000 * 24 / 100 = 12000.

    Design: Difficulty/cross_entity_state_dependency/payment_release_blocked_while_collective_frozen
    """
    ctx = _frozen_collective_with_an_active_contract(api)
    refused = api.create_payment_release(
        payment_release_payload(
            ctx["contract_id"],
            "CONTRACT_ADVANCE",
            50000,
            expected_deal_contract_version=ctx["version"],
        ),
        make_treasury_headers("treasury-4"),
    )
    validate_error(refused, ERR_COLLECTIVE_FUNDING_FROZEN, expected_status=409)

    validate_success(
        api.create_contribution(
            contribution_payload(
                ctx["donor_id"],
                200000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    thawed = read_collective(api, ctx["collective_id"])
    assert_collective_ledger(
        thawed,
        settled_net_funds_cents=311940,
        committed_unreleased_cents=200000,
        funding_posture="OPEN",
    )

    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                ctx["contract_id"],
                "CONTRACT_ADVANCE",
                50000,
                expected_deal_contract_version=ctx["version"],
            ),
            make_treasury_headers("treasury-4"),
        ),
        expected_status=201,
    )
    assert_release_money(
        release,
        status="RELEASED",
        withholding_basis="BACKUP",
        withholding_amount_cents=12000,
        net_payable_cents=38000,
    )
    assert_contract_money(read_contract(api, ctx["contract_id"]), released_total_cents=50000)
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]),
        tax_year_gross_paid_cents=50000,
        tax_year_withheld_cents=12000,
    )
