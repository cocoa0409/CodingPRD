"""Gates that read another entity's live status rather than the request payload.

Two entity pairs are exercised.  A bond issuance is gated on the treatment
plan it is written against having reached ``COMPLETED``, and a claim
verification is gated on the offered graph being ``GRAPHED`` at the instant of
the call — a single acceptable middle state, so the gate closes from both ends
of the graph lifecycle.
"""

from test_helpers import (
    BOND_ACTIVE,
    CLAIM_SUBMITTED,
    CLAIM_UNDER_ADJUDICATION,
    CLOCK_STARTUP_INSTANT,
    ERR_INSPECTION_NOT_GRAPHED,
    ERR_PLAN_NOT_COMPLETED,
    EXCLUSION_AGGREGATE_PRORATION,
    INSPECTION_DRAFT,
    INSPECTION_GRAPHED,
    INSPECTION_SUPERSEDED,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PLAN_APPROVED,
    PLAN_COMPLETED,
    PLAN_PROPOSED,
    PURPOSE_INITIAL,
    PURPOSE_RENEWAL,
    TIER_REPAIR_AND_RETREAT,
    assert_bond_money,
    assert_claim_money,
    assert_money,
    assert_status,
    bond_payload,
    damage_finding_payload,
    make_field_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
)
from test_helpers.fixtures import (
    add_finding,
    approve_plan,
    bonded_property,
    clean_initial_graph,
    complete_plan,
    file_claim,
    open_graph,
    propose_plan,
    record_application,
    register_inspector,
    register_property_and_inspector,
    set_clock,
    sign_graph,
)

BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
CLAIM_INSTANT = "2026-10-01T00:00:00Z"
SUPERSEDE_INSTANT = "2026-10-05T00:00:00Z"

# P1: FL SLAB, 2000 sq ft, 180 linear ft.  A LIQUID_BARRIER plan on it is
# quoted 1080.00, so the bond's base premium is 194.40 and its REPAIR_AND_RETREAT
# ceiling is 11664.00 with an annual premium of 241.06.
EXPECTED_BASE_PREMIUM = 194.40
EXPECTED_REPAIR_CAP = 11664.00
EXPECTED_ANNUAL_PREMIUM = 241.06
EXPECTED_TARGET_GALLONS = 190.0

CLAIMED_DAMAGE = 4000.00
EXPECTED_ELIGIBLE = 3000.00
EXPECTED_EXCLUDED = 1000.00
EXPECTED_DEDUCTIBLE = 210.00
EXPECTED_PROJECTED = 2790.00
EXPECTED_REMAINING_AFTER_RESERVE = 8874.00


def _proposed_plan_chain(api):
    """A GRAPHED INITIAL graph on P1 and one PROPOSED liquid-barrier plan."""
    set_clock(api, CLOCK_STARTUP_INSTANT)
    prop, inspector = register_property_and_inspector(api, state_code="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])
    plan = propose_plan(api, prop["id"], graph["id"], inspector["id"])
    return prop, inspector, graph, plan


def _issue_bond_response(api, property_id, treatment_plan_id):
    """The one issuance request that is replayed unchanged at every plan status."""
    payload = bond_payload(
        property_id,
        treatment_plan_id,
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        conducive_waiver_codes=[],
    )
    return api.create_bond(payload, MANAGER_HEADERS)


def _discharge_and_complete(api, plan, applicator_id):
    """Discharge the plan's whole volume target and close it out."""
    record_application(
        api,
        plan["id"],
        applicator_id,
        plan["version"],
        gallons_applied=EXPECTED_TARGET_GALLONS,
        concentration_pct=0.06,
    )
    return complete_plan(api, plan["id"], applicator_id)


def _bond_count_for(api, property_id):
    """The number of bonds recorded against one structure."""
    rows, meta = validate_paginated(api.list_bonds(MANAGER_HEADERS, property_id=property_id))
    return meta["total_count"]


class TestBondIssuanceGatedOnPlanCompletion:
    """The same issuance body is refused twice and accepted once."""

    def test_issuance_refused_while_the_bonded_plan_is_still_proposed(self, api):
        """A plan that has only been proposed cannot be bonded.

        PRD 3.7: the named plan "must be in status `COMPLETED`; a `PROPOSED`,
        `APPROVED` or `ABANDONED` plan cannot be bonded, and the refusal is
        `ERR_PLAN_NOT_COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/bond_issuance_gated_on_treatment_plan_reaching_completed
        """
        prop, _inspector, _graph, plan = _proposed_plan_chain(api)
        assert_status(plan, PLAN_PROPOSED, "treatment_plan")

        response = _issue_bond_response(api, prop["id"], plan["id"])
        validate_error(response, ERR_PLAN_NOT_COMPLETED)

        assert _bond_count_for(api, prop["id"]) == 0, (
            "a refused issuance must not leave a bond behind"
        )
        after = validate_success(api.get_treatment_plan(plan["id"], MANAGER_HEADERS))
        assert_status(after, PLAN_PROPOSED, "treatment_plan")
        assert after["version"] == plan["version"], (
            "a rejected issuance must not advance the plan's version"
        )

    def test_issuance_refused_while_the_bonded_plan_is_only_approved(self, api):
        """Approval authorises field work but is not completion.

        PRD 3.7: "Only a completed treatment earns a bond." The named plan
        "must be in status `COMPLETED`; a `PROPOSED`, `APPROVED` or
        `ABANDONED` plan cannot be bonded."

        Design: Difficulty/cross_entity_state_dependency/bond_issuance_gated_on_treatment_plan_reaching_completed
        """
        prop, _inspector, _graph, plan = _proposed_plan_chain(api)
        approved = approve_plan(api, plan["id"])
        assert_status(approved, PLAN_APPROVED, "treatment_plan")

        response = _issue_bond_response(api, prop["id"], plan["id"])
        validate_error(response, ERR_PLAN_NOT_COMPLETED)

        assert _bond_count_for(api, prop["id"]) == 0, (
            "an approved-but-incomplete plan must not yield a bond"
        )
        after = validate_success(api.get_treatment_plan(plan["id"], MANAGER_HEADERS))
        assert_status(after, PLAN_APPROVED, "treatment_plan")
        assert after["version"] == approved["version"], (
            "a rejected issuance must not advance the plan's version"
        )

    def test_issuance_succeeds_once_the_bonded_plan_reaches_completed(self, api):
        """The identical body that was refused twice is accepted at COMPLETED.

        PRD 3.7: "Only a completed treatment earns a bond." Its money follows:
        "`base_premium_usd` is the bonded plan's `quoted_price_usd` multiplied
        by 0.18" and for `REPAIR_AND_RETREAT` the cap multiplier "is 60, so the
        ceiling is sixty times the base premium."

        Design: Difficulty/cross_entity_state_dependency/bond_issuance_gated_on_treatment_plan_reaching_completed
        """
        prop, inspector, _graph, plan = _proposed_plan_chain(api)
        approved = approve_plan(api, plan["id"])
        completed = _discharge_and_complete(api, approved, inspector["id"])
        assert_status(completed, PLAN_COMPLETED, "treatment_plan")

        bond = validate_success(
            _issue_bond_response(api, prop["id"], plan["id"]), 201
        )
        assert_status(bond, BOND_ACTIVE, "bond")
        assert_bond_money(
            bond,
            base_premium_usd=EXPECTED_BASE_PREMIUM,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            annual_premium_usd=EXPECTED_ANNUAL_PREMIUM,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
        )
        assert _bond_count_for(api, prop["id"]) == 1, (
            "the accepted issuance is the structure's first and only bond"
        )

    def test_only_the_plan_status_distinguishes_the_three_identical_requests(self, api):
        """Nothing but the other entity's status changes across the three calls.

        PRD 3.7: "Only a completed treatment earns a bond," and the graph
        justifying the plan "must have reached `GRAPHED` ... and its `purpose`
        must be `INITIAL`" — conditions that hold unchanged throughout here.

        Design: Difficulty/cross_entity_state_dependency/bond_issuance_gated_on_treatment_plan_reaching_completed
        """
        prop, inspector, graph, plan = _proposed_plan_chain(api)

        validate_error(
            _issue_bond_response(api, prop["id"], plan["id"]), ERR_PLAN_NOT_COMPLETED
        )
        assert _bond_count_for(api, prop["id"]) == 0

        approved = approve_plan(api, plan["id"])
        validate_error(
            _issue_bond_response(api, prop["id"], plan["id"]), ERR_PLAN_NOT_COMPLETED
        )
        assert _bond_count_for(api, prop["id"]) == 0

        completed = _discharge_and_complete(api, approved, inspector["id"])
        bond = validate_success(
            _issue_bond_response(api, prop["id"], plan["id"]), 201
        )
        assert bond["treatment_plan_id"] == completed["id"]
        assert _bond_count_for(api, prop["id"]) == 1

        justifying = validate_success(api.get_inspection(graph["id"], OFFICER_HEADERS))
        assert_status(justifying, INSPECTION_GRAPHED, "inspection")
        assert justifying["purpose"] == PURPOSE_INITIAL, (
            "the justifying graph's purpose was INITIAL for all three attempts"
        )


def _claim_awaiting_verification(api):
    """A bonded structure, an unsigned damage graph and one SUBMITTED claim.

    The graph is opened by a second licensee, so the applicator who treated the
    structure never certifies the damage claimed against that treatment.
    """
    set_clock(api, CLOCK_STARTUP_INSTANT)
    chain = bonded_property(api, state_code="FL", issue_instant=BOND_ISSUE_INSTANT)
    prop = chain["property"]
    verifier = register_inspector(
        api, license_state="FL", full_name="Marisol Kane"
    )
    set_clock(api, CLAIM_INSTANT)
    graph = open_graph(api, prop["id"], verifier["id"])
    add_finding(
        api,
        graph["id"],
        verifier["id"],
        damage_finding_payload("A2", 3000.00, pre_existing=False, severity=3),
    )
    add_finding(
        api,
        graph["id"],
        verifier["id"],
        damage_finding_payload("A3", 1000.00, pre_existing=True, severity=1),
    )
    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    claim = file_claim(api, bond, prop["id"], CLAIMED_DAMAGE)
    return {
        "property": prop,
        "bond": bond,
        "verifier": verifier,
        "verifying_inspection": graph,
        "claim": claim,
    }


def _verify(api, claim_id, inspection_id, inspector_id):
    """Offer one graph as verification of a claim, returning the raw response."""
    return api.attach_verification(
        claim_id,
        verification_payload(inspection_id),
        make_field_inspector_headers(inspector_id),
    )


class TestClaimVerificationGatedOnGraphStatus:
    """GRAPHED is the single acceptable status, so DRAFT and SUPERSEDED both fail."""

    def test_verification_refused_while_the_verifying_graph_is_still_draft(self, api):
        """Notations alone are not evidence; the graph must have been signed.

        PRD 2.6 stage 20: "A graph consumed as evidence is `GRAPHED`", reported
        as `ERR_INSPECTION_NOT_GRAPHED` (409); PRD 3.10 requires the verifying
        graph to "be in status `GRAPHED` (`ERR_INSPECTION_NOT_GRAPHED`)."

        Design: Difficulty/cross_entity_state_dependency/claim_verification_gated_on_inspection_being_currently_graphed
        """
        setup = _claim_awaiting_verification(api)
        claim = setup["claim"]
        graph = setup["verifying_inspection"]
        assert_status(graph, INSPECTION_DRAFT, "inspection")

        response = _verify(api, claim["id"], graph["id"], setup["verifier"]["id"])
        validate_error(response, ERR_INSPECTION_NOT_GRAPHED)

        unchanged = validate_success(api.get_damage_claim(claim["id"], MANAGER_HEADERS))
        assert_status(unchanged, CLAIM_SUBMITTED, "damage_claim")
        assert unchanged["verifying_inspection_id"] is None, (
            "a refused verification must not record a verifying graph"
        )
        assert_claim_money(
            unchanged,
            eligible_damage_usd=0.00,
            excluded_pre_existing_usd=0.00,
            deductible_usd=0.00,
            projected_payout_usd=0.00,
        )
        bond = validate_success(api.get_bond(setup["bond"]["id"], MANAGER_HEADERS))
        assert_bond_money(
            bond,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
        )

    def test_verification_succeeds_once_the_verifying_graph_is_signed(self, api):
        """The identical call is accepted the moment the graph reaches GRAPHED.

        PRD 3.10: "When it supersedes nothing, the basis is
        `AGGREGATE_PRORATION`" and `eligible_damage_usd` is "`claimed_damage_usd`
        multiplied by the first sum divided by the second"; the bond then
        "reserves the money: `reserved_claim_amount_usd` rises by
        `projected_payout_usd` and `remaining_repair_cap_usd` falls by exactly
        the same amount."

        Design: Difficulty/cross_entity_state_dependency/claim_verification_gated_on_inspection_being_currently_graphed
        """
        setup = _claim_awaiting_verification(api)
        claim = setup["claim"]
        graph = setup["verifying_inspection"]
        signed = sign_graph(api, graph["id"], setup["verifier"]["id"])
        assert_status(signed, INSPECTION_GRAPHED, "inspection")

        verified = validate_success(
            _verify(api, claim["id"], graph["id"], setup["verifier"]["id"])
        )
        assert_status(verified, CLAIM_UNDER_ADJUDICATION, "damage_claim")
        assert verified["exclusion_basis"] == EXCLUSION_AGGREGATE_PRORATION, (
            "a verifying graph that supersedes nothing prorates by severity"
        )
        assert_claim_money(
            verified,
            eligible_damage_usd=EXPECTED_ELIGIBLE,
            excluded_pre_existing_usd=EXPECTED_EXCLUDED,
            deductible_usd=EXPECTED_DEDUCTIBLE,
            projected_payout_usd=EXPECTED_PROJECTED,
        )
        bond = validate_success(api.get_bond(setup["bond"]["id"], MANAGER_HEADERS))
        assert_bond_money(
            bond,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=EXPECTED_PROJECTED,
            remaining_repair_cap_usd=EXPECTED_REMAINING_AFTER_RESERVE,
        )

    def test_verification_refused_once_the_verifying_graph_is_superseded(self, api):
        """The very graph accepted a moment ago is refused after supersession.

        PRD 3.3: "`SUPERSEDED` is terminal — a retired graph never returns to
        service, and it is not evidence for anything." PRD 2.6 evaluates that
        stage-20 check ahead of the stage-21 `ERR_CLAIM_ALREADY_RESERVED`.

        Design: Difficulty/cross_entity_state_dependency/claim_verification_gated_on_inspection_being_currently_graphed
        """
        setup = _claim_awaiting_verification(api)
        prop = setup["property"]
        verifier = setup["verifier"]
        first_claim = setup["claim"]
        graph = setup["verifying_inspection"]

        sign_graph(api, graph["id"], verifier["id"])
        priced = validate_success(
            _verify(api, first_claim["id"], graph["id"], verifier["id"])
        )
        assert_status(priced, CLAIM_UNDER_ADJUDICATION, "damage_claim")

        set_clock(api, SUPERSEDE_INSTANT)
        open_graph(
            api,
            prop["id"],
            verifier["id"],
            purpose=PURPOSE_RENEWAL,
            supersedes_inspection_id=graph["id"],
        )
        retired = validate_success(api.get_inspection(graph["id"], OFFICER_HEADERS))
        assert_status(retired, INSPECTION_SUPERSEDED, "inspection")

        bond = validate_success(api.get_bond(setup["bond"]["id"], MANAGER_HEADERS))
        second_claim = file_claim(api, bond, prop["id"], 1000.00)
        response = _verify(api, second_claim["id"], graph["id"], verifier["id"])
        validate_error(response, ERR_INSPECTION_NOT_GRAPHED)

        still_submitted = validate_success(
            api.get_damage_claim(second_claim["id"], MANAGER_HEADERS)
        )
        assert_status(still_submitted, CLAIM_SUBMITTED, "damage_claim")

        after = validate_success(api.get_bond(setup["bond"]["id"], MANAGER_HEADERS))
        assert_bond_money(
            after,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            reserved_claim_amount_usd=EXPECTED_PROJECTED,
            remaining_repair_cap_usd=EXPECTED_REMAINING_AFTER_RESERVE,
        )
        settled = validate_success(
            api.get_damage_claim(first_claim["id"], MANAGER_HEADERS)
        )
        assert_money(settled["eligible_damage_usd"], EXPECTED_ELIGIBLE)
        assert_money(settled["projected_payout_usd"], EXPECTED_PROJECTED)
