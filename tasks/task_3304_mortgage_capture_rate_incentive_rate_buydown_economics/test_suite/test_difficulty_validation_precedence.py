"""The validation ladder: which rung of the twenty-five ordered checks fires first."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import ADMIN_HEADERS, BANKER_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def test_a_state_failure_outranks_the_compliance_gate_on_approval(api):
    """Approving a still-pending contract fails at the state rung, not at the pricing rung.

    The contract carries a reserved rate-buydown allocation, so an approval that did
    reach the business rules would have to clear them; the contract's own posture is
    PENDING, which declares no move to APPROVED, so the state rung is what reports.

    PRD §2.10: "The ordering is normative and not merely conventional: when more
    than one check would fail on the same request, the lowest-numbered failing check
    is the one whose error the caller receives."
    PRD §2.10: "Priority 4 requires that the target row be in a state that declares
    the requested transition in its state machine; failure yields `ERR_INVALID_STATE`
    at HTTP 409, and this check applies to every state-changing endpoint."
    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_approve_and_qualify
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    # The affiliated-business form is delivered and acknowledged so the rate-buydown
    # allocation itself clears priority 6 (PRD section 3.7); the contract's own PENDING
    # posture is then the only rung left to fail.
    aba = fixtures.deliver_disclosure(api, world["ct1"])
    world["d0"] = aba["id"]
    fixtures.acknowledge(api, world["d0"], world["b1"])

    allocation = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("RATE_BUYDOWN", 6_000_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    assert allocation["allocation_status"] == "RESERVED", allocation["allocation_status"]

    before = fixtures.read_contract(api, world["ct1"])
    assert before["contract_status"] == "PENDING", before["contract_status"]

    refused = api.approve_contract(world["ct1"], COMPLIANCE_HEADERS)
    validate_error(refused, "ERR_INVALID_STATE", 409)

    after = fixtures.read_contract(api, world["ct1"])
    assert after["contract_status"] == "PENDING", (
        "a rejected approval must leave the posture untouched"
    )


def test_a_state_failure_outranks_the_scoring_rules_when_qualifying_a_denied_application(api):
    """Qualifying a denied application fails at priority 4, not at the score or ratio gate.

    PRD §2.10: "Priority 4 requires that the target row be in a state that declares
    the requested transition in its state machine; failure yields `ERR_INVALID_STATE`
    at HTTP 409".
    PRD §2.10: "Priority 8 requires that the application's `dti_bps` not exceed the
    qualifying ceiling of 4500 basis points; failure yields `ERR_DTI_CEILING_EXCEEDED`
    at HTTP 422".
    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_approve_and_qualify
    """
    world = fixtures.build_deal(
        api, qualify=False, qualifying_income_cents=2_000_000, monthly_debt_cents=980_000
    )
    # Denial is legal from SUBMITTED, and the ratio would also breach the ceiling.
    get_success_data(api.deny_loan_application(world["la1"], BANKER_HEADERS))
    before = fixtures.read_application(api, world["la1"])
    assert before["application_status"] == "DENIED", before["application_status"]
    assert before["dti_bps"] > 4500, before["dti_bps"]

    refused = api.qualify_loan_application(world["la1"], BANKER_HEADERS)
    validate_error(refused, "ERR_INVALID_STATE", 409)

    after = fixtures.read_application(api, world["la1"])
    assert after["application_status"] == "DENIED", (
        "the denied posture is unchanged by the refused call"
    )


def test_the_disclosure_gate_outranks_the_budget_gate_when_allocating(api):
    """An allocation that breaches both priority 6 and priority 19 surfaces the safety error.

    PRD §2.10: "Priority 6 requires that any contract carrying a rate-buydown
    allocation in `RESERVED` or `APPLIED` status also hold at least one
    `ACKNOWLEDGED` `AFFILIATED_BUSINESS_ARRANGEMENT` disclosure; failure yields
    `ERR_ABA_DISCLOSURE_MISSING` at HTTP 403".
    PRD §2.10: "Priority 19 requires that an allocation's `requested_cents` not
    exceed the sum of the three remaining bucket caps of the contract's community
    policy; failure yields `ERR_INCENTIVE_BUDGET_EXHAUSTED` at HTTP 422".
    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_allocate
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    # A price-reduction allocation leaves a contract that carries no rate-buydown
    # obligation, so the disclosure rung is genuinely the one that fires.
    first = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 1_000_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    assert first["allocation_status"] == "RESERVED", first["allocation_status"]

    # A form is on file but has never been acknowledged, so the safety rung fails;
    # the request is also far past the sum of the three caps.
    delivered = fixtures.deliver_disclosure(api, world["ct1"])
    assert delivered["disclosure_status"] == "ISSUED", delivered["disclosure_status"]

    refreshed = fixtures.read_contract(api, world["ct1"])
    refused = api.create_incentive_allocation(
        world["ct1"],
        f.incentive_allocation_payload("RATE_BUYDOWN", 99_999_999, refreshed["version"]),
        SALES_HEADERS,
    )
    validate_error(refused, "ERR_ABA_DISCLOSURE_MISSING", 403)


def test_the_winning_gate_leaves_the_earlier_allocation_and_contract_total_intact(api):
    """The refused allocation writes nothing, so the reserved split is untouched.

    PRD §2.10: "Authentication is settled before authorization, authorization before
    existence, existence before state, state before the business rules, and the
    business rules before the syntactic and envelope checks".
    PRD §3.7: "It computes each bucket's remaining cap as the policy cap for that
    bucket minus the total already granted to that bucket by allocations sitting in
    `RESERVED` or `APPLIED` status".
    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_allocate
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    first = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 1_000_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    fixtures.deliver_disclosure(api, world["ct1"])
    refreshed = fixtures.read_contract(api, world["ct1"])

    api.create_incentive_allocation(
        world["ct1"],
        f.incentive_allocation_payload("RATE_BUYDOWN", 99_999_999, refreshed["version"]),
        SALES_HEADERS,
    )

    rows, _ = fixtures.rows(
        api.list_contract_incentive_allocations(world["ct1"], world["sales_headers"])
    )
    assert len(rows) == 1, f"the refused request created no extra row, got {len(rows)}"
    assert rows[0]["id"] == first["id"], rows[0]["id"]

    again = fixtures.read_contract(api, world["ct1"])
    assert again["version"] == refreshed["version"], (
        "a rejected write must not bump the contract's version"
    )