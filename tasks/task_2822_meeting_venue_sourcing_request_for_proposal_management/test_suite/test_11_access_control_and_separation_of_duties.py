"""Access control on the sourcing pipeline and separation of duties on a contract.

The authentication gate, the per-endpoint role gate, the entity-backed ownership
gate for a supplier's representative, and the four guards that fragment approval
authority on one contract.
"""

import pytest

from test_helpers import (
    APPROVER_ALT_HEADERS,
    APPROVER_ALT_USER_ID,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
    FINANCE_HEADERS,
    NO_HEADERS,
    PLANNER_HEADERS,
    PLANNER_USER_ID,
    PROGRAM_ADMIN_HEADERS,
    ROLE_CONTRACT_APPROVER,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_headers,
    make_venue_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert

SOURCING_CLOCK = "2026-08-05T09:00:00.000Z"
EVENT_CODE = "EVT-2822-A"


def _event_body():
    """The canonical meeting requirement body, identical on every attempt."""
    return factories.event_payload(event_code=EVENT_CODE)


def _venue_body():
    return factories.venue_payload()


def _benchmark_body():
    return factories.rate_benchmark_payload()


def _send_unauthorized_create(operation):
    """Send one create request under a role the endpoint does not authorize."""
    if operation == "event_as_venue_rep":
        return api_client.create_event(
            _event_body(), make_venue_rep_headers("venue-rep-unknown")
        )
    if operation == "venue_as_sourcing_manager":
        return api_client.create_venue(_venue_body(), PLANNER_HEADERS)
    return api_client.create_rate_benchmark(_benchmark_body(), FINANCE_HEADERS)


class TestAuthenticationGate:
    """The outermost gate fires before any business rule on the body."""

    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param(NO_HEADERS, id="no_identity_headers_at_all"),
            pytest.param(UNKNOWN_ROLE_HEADERS, id="role_outside_the_five_declared_names"),
        ],
    )
    def test_absent_or_unrecognized_role_is_rejected_with_401(
        self, sourcing_clock, headers
    ):
        """An otherwise perfectly valid meeting-event body is refused on the headers.

        "If either header is absent, or if `X-User-Role` is not one of the five recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_or_unknown_role_header_is_rejected_before_any_business_rule
        """
        response = api_client.create_event(_event_body(), headers)
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

    def test_neither_refusal_persists_an_event_and_the_planner_still_succeeds(
        self, sourcing_clock
    ):
        """Nothing is written by either refusal, and the same body lands as DRAFT.

        "The new event's `status` is `DRAFT`, `sourcing_owner_user_id` is set to the calling planner's `X-User-ID`, `budget_remaining_usd` equals `budget_ceiling_usd`, and `committed_spend_usd` and `cancellation_liability_usd` are both `0.00`."

        Design: Corner/rbac/missing_or_unknown_role_header_is_rejected_before_any_business_rule
        """
        validate_error(
            api_client.create_event(_event_body(), NO_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.create_event(_event_body(), UNKNOWN_ROLE_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        rows, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert rows == [], "a refused request must not persist a meeting event"
        assert meta["total_count"] == 0

        created = validate_success(
            api_client.create_event(_event_body(), PLANNER_HEADERS), 201
        )
        domain_assert.assert_fields_equal(
            created, {"event_code": EVENT_CODE, "status": "DRAFT"}
        )


class TestRoleExclusiveCreates:
    """Each create endpoint admits exactly the role that owns it."""

    @pytest.mark.parametrize(
        "operation",
        [
            pytest.param("event_as_venue_rep", id="venue_rep_cannot_open_a_meeting_event"),
            pytest.param(
                "venue_as_sourcing_manager", id="sourcing_manager_cannot_register_a_venue"
            ),
            pytest.param(
                "benchmark_as_finance_controller",
                id="finance_controller_cannot_publish_a_benchmark",
            ),
        ],
    )
    def test_a_role_outside_the_endpoint_list_is_refused_with_403(
        self, sourcing_clock, operation
    ):
        """The refusal is about the declared role, not about the payload.

        "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called (see the authorization column of the endpoint table in section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/each_role_is_locked_out_of_the_other_roles_exclusive_creates
        """
        response = _send_unauthorized_create(operation)
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE.value, 403)

    def test_nothing_is_persisted_and_each_owning_role_succeeds_unchanged(
        self, sourcing_clock
    ):
        """Three refusals leave the store empty; the same bodies land under their owners.

        "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called (see the authorization column of the endpoint table in section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/each_role_is_locked_out_of_the_other_roles_exclusive_creates
        """
        for operation in (
            "event_as_venue_rep",
            "venue_as_sourcing_manager",
            "benchmark_as_finance_controller",
        ):
            validate_error(
                _send_unauthorized_create(operation),
                ApiErrorId.FORBIDDEN_ROLE.value,
                403,
            )

        venue_rows, venue_meta = validate_paginated(
            api_client.list_venues(PROGRAM_ADMIN_HEADERS)
        )
        assert venue_rows == []
        assert venue_meta["total_count"] == 0
        event_rows, event_meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert event_rows == []
        assert event_meta["total_count"] == 0

        venue = validate_success(
            api_client.create_venue(_venue_body(), PROGRAM_ADMIN_HEADERS), 201
        )
        domain_assert.assert_fields_equal(
            venue, {"preferred_supplier_status": "PREFERRED"}
        )

        benchmark = validate_success(
            api_client.create_rate_benchmark(_benchmark_body(), PROGRAM_ADMIN_HEADERS), 201
        )
        domain_assert.assert_money_field(benchmark, "benchmark_adr_usd", 260.00)

        event = validate_success(
            api_client.create_event(_event_body(), PLANNER_HEADERS), 201
        )
        domain_assert.assert_fields_equal(event, {"status": "DRAFT"})


class TestVenueRepOwnership:
    """Authorization for the supplier-side role is data-dependent, not role-dependent."""

    def test_another_venues_representative_cannot_submit_the_invited_bid(self):
        """A legitimate VenueRep of a different venue is refused, and nothing moves.

        "A mismatch on any of those five operations is rejected with `ERR_VENUE_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/a_venue_rep_may_only_act_on_its_own_venues_bid
        """
        world = fixtures.build_issued_round()
        other_venue = fixtures.create_second_venue()

        response = api_client.submit_proposal(
            world["proposal_id"],
            factories.proposal_submission_payload(),
            make_venue_rep_headers(other_venue["id"]),
        )
        validate_error(response, ApiErrorId.VENUE_OWNERSHIP_MISMATCH.value, 403)

        proposal = fixtures.read_proposal(world["proposal_id"])
        domain_assert.assert_fields_equal(proposal, {"status": "INVITED"})
        domain_assert.assert_nulls(proposal, ["total_cost_contracted_usd", "submitted_at"])
        domain_assert.assert_integer(
            fixtures.read_rfp(world["rfp_id"])["submitted_count"], 0, "submitted_count"
        )

    def test_the_owning_venues_representative_submits_the_same_body_successfully(self):
        """The byte-identical grid from the bid's own venue is accepted and priced.

        "Concretely, a `VenueRep` submitting, declining, withdrawing or revising a bid must present an `X-User-ID` equal to that bid's `venue_id`, and a `VenueRep` countersigning a contract must present an `X-User-ID` equal to that contract's `venue_id`."

        Design: Corner/rbac/a_venue_rep_may_only_act_on_its_own_venues_bid
        """
        world = fixtures.build_issued_round()
        other_venue = fixtures.create_second_venue()
        grid = factories.proposal_submission_payload()

        validate_error(
            api_client.submit_proposal(
                world["proposal_id"], grid, make_venue_rep_headers(other_venue["id"])
            ),
            ApiErrorId.VENUE_OWNERSHIP_MISMATCH.value,
            403,
        )

        accepted = validate_success(
            api_client.submit_proposal(
                world["proposal_id"], grid, make_venue_rep_headers(world["venue_id"])
            ),
            200,
        )
        domain_assert.assert_fields_equal(accepted, {"status": "SUBMITTED"})
        domain_assert.assert_integer(
            accepted["paid_room_nights"], 587, "paid_room_nights"
        )
        domain_assert.assert_money_field(accepted, "total_cost_contracted_usd", 447844.84)

        domain_assert.assert_integer(
            fixtures.read_rfp(world["rfp_id"])["submitted_count"], 1, "submitted_count"
        )
        domain_assert.assert_money_field(
            fixtures.read_event(world["event_id"]), "best_total_cost_usd", 447844.84
        )


class TestApprovalChainOrderAndRole:
    """Two chain guards on one routed contract: sequence first, then required role."""

    def test_the_routed_chain_is_manager_then_vp_for_the_contract_approver(
        self, routed_contract
    ):
        """The generated chain records each level with the role that may decide it.

        "Each step records its `approval_level` and the `required_role` that may decide it: `ProgramAdmin` for `PROGRAM_COMPLIANCE`, and `ContractApprover` for `MANAGER`, `VP` and `LEGAL`."

        Design: Corner/rbac/approval_steps_must_be_decided_in_order_by_the_required_role
        """
        step_one, step_two = routed_contract["steps"]
        domain_assert.assert_fields_equal(
            step_one,
            {
                "step_seq": 1,
                "approval_level": "MANAGER",
                "required_role": "ContractApprover",
            },
        )
        domain_assert.assert_fields_equal(
            step_two,
            {"step_seq": 2, "approval_level": "VP", "required_role": "ContractApprover"},
        )

    def test_deciding_step_two_while_step_one_is_pending_is_out_of_order(
        self, routed_contract
    ):
        """Jumping the queue is refused even by a caller holding the required role.

        "Four further guards then apply in the order given in section 2.8: every step of the same contract with a lower `step_seq` must already be `APPROVED`, otherwise `ERR_APPROVAL_STEP_OUT_OF_ORDER`; the caller's `X-User-Role` must equal the step's `required_role`, otherwise `ERR_APPROVAL_LEVEL_ROLE_MISMATCH`; the caller's `X-User-ID` must not be the contract's `awarded_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; and the caller's `X-User-ID` must not already appear as the `approver_user_id` of another step on the same contract, otherwise `ERR_DUPLICATE_APPROVER`."

        Design: Corner/rbac/approval_steps_must_be_decided_in_order_by_the_required_role
        """
        step_two = routed_contract["steps"][1]
        response = api_client.decide_approval_step(
            step_two["id"],
            factories.decision_payload("APPROVED", decision_note="Jumping the queue."),
            APPROVER_ALT_HEADERS,
        )
        validate_error(response, ApiErrorId.APPROVAL_STEP_OUT_OF_ORDER.value, 409)

        reread = validate_success(
            api_client.get_approval_step(step_two["id"], PLANNER_HEADERS), 200
        )
        domain_assert.assert_fields_equal(reread, {"decision": "PENDING"})
        domain_assert.assert_nulls(reread, ["approver_user_id"])

    def test_a_program_admin_may_not_decide_a_contract_approver_step(
        self, routed_contract
    ):
        """A role that decides compliance controls elsewhere cannot substitute here.

        "First, a step may only be decided by a caller whose `X-User-Role` equals the step's own `required_role` — a `ProgramAdmin` clears the `PROGRAM_COMPLIANCE` control and a `ContractApprover` clears the `MANAGER`, `VP` and `LEGAL` controls, and no substitution is permitted in either direction."

        Design: Corner/rbac/approval_steps_must_be_decided_in_order_by_the_required_role
        """
        step_one = routed_contract["steps"][0]
        response = api_client.decide_approval_step(
            step_one["id"],
            factories.decision_payload(
                "APPROVED", decision_note="Program office signing off."
            ),
            PROGRAM_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.APPROVAL_LEVEL_ROLE_MISMATCH.value, 403)

        reread = validate_success(
            api_client.get_approval_step(step_one["id"], PLANNER_HEADERS), 200
        )
        domain_assert.assert_fields_equal(reread, {"decision": "PENDING"})
        domain_assert.assert_fields_equal(
            fixtures.read_contract(routed_contract["contract_id"]),
            {"approval_state": "IN_APPROVAL"},
        )

    def test_the_required_role_clears_step_one_and_the_chain_stays_in_approval(
        self, routed_contract
    ):
        """The decider and the instant are recorded, and the chain is not yet finished.

        "An `APPROVED` decision on any step other than the highest `step_seq` simply moves that step `PENDING → APPROVED` and leaves the contract in `IN_APPROVAL`, with the contract's `version` advancing by 1."

        Design: Corner/rbac/approval_steps_must_be_decided_in_order_by_the_required_role
        """
        step_one = routed_contract["steps"][0]
        decided = validate_success(
            api_client.decide_approval_step(
                step_one["id"],
                factories.decision_payload(
                    "APPROVED", decision_note="Within delegation."
                ),
                APPROVER_HEADERS,
            ),
            200,
        )
        domain_assert.assert_fields_equal(
            decided,
            {
                "decision": "APPROVED",
                "approver_user_id": APPROVER_USER_ID,
                "decided_at": SOURCING_CLOCK,
            },
        )
        domain_assert.assert_fields_equal(
            fixtures.read_contract(routed_contract["contract_id"]),
            {"approval_state": "IN_APPROVAL"},
        )

    def test_approving_the_highest_step_finishes_the_approval_dimension_alone(
        self, routed_contract
    ):
        """Walking both steps in order reaches APPROVED while the signature is untouched.

        "An `APPROVED` decision on the highest `step_seq` additionally moves the contract `approval_state` `IN_APPROVAL → APPROVED`."

        Design: Corner/rbac/approval_steps_must_be_decided_in_order_by_the_required_role
        """
        step_one, step_two = routed_contract["steps"]
        fixtures.decide_step(step_one["id"], "APPROVED", APPROVER_HEADERS)
        validate_success(
            api_client.decide_approval_step(
                step_two["id"],
                factories.decision_payload(
                    "APPROVED", decision_note="Within delegation."
                ),
                APPROVER_ALT_HEADERS,
            ),
            200,
        )
        domain_assert.assert_fields_equal(
            fixtures.read_contract(routed_contract["contract_id"]),
            {"approval_state": "APPROVED", "signature_state": "UNSIGNED"},
        )


class TestSegregationOfDuties:
    """Both duty-separation guards read X-User-ID, never the declared role."""

    def test_the_awarding_planner_may_not_decide_a_step_of_her_own_contract(
        self, routed_contract
    ):
        """Presenting the approver role does not lift the bar on the awarding identity.

        "Second, the planner who awarded the contract may never decide any of its steps: the `X-User-ID` recorded as the contract's `awarded_by_user_id` is barred from every step of that contract, regardless of what role that person also holds."

        Design: Corner/rbac/the_awarding_planner_and_a_repeat_approver_are_both_barred
        """
        contract = fixtures.read_contract(routed_contract["contract_id"])
        domain_assert.assert_fields_equal(
            contract, {"awarded_by_user_id": PLANNER_USER_ID}
        )

        step_one = routed_contract["steps"][0]
        response = api_client.decide_approval_step(
            step_one["id"],
            factories.decision_payload(
                "APPROVED", decision_note="Approving my own award."
            ),
            make_headers(PLANNER_USER_ID, ROLE_CONTRACT_APPROVER),
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        reread = validate_success(
            api_client.get_approval_step(step_one["id"], PLANNER_HEADERS), 200
        )
        domain_assert.assert_fields_equal(reread, {"decision": "PENDING"})
        domain_assert.assert_nulls(reread, ["approver_user_id"])

    def test_one_approver_may_not_clear_two_controls_of_the_same_contract(
        self, routed_contract
    ):
        """The approver of step 1 is barred from approving step 2 of that contract.

        "Third, no two steps of one contract may be **approved** by the same `X-User-ID`: once an identifier appears as `approver_user_id` on any step of a contract, it is barred from approving any other step of the same contract."

        Design: Corner/rbac/the_awarding_planner_and_a_repeat_approver_are_both_barred
        """
        step_one, step_two = routed_contract["steps"]
        first = fixtures.decide_step(step_one["id"], "APPROVED", APPROVER_HEADERS)
        domain_assert.assert_fields_equal(
            first, {"approver_user_id": APPROVER_USER_ID}
        )

        response = api_client.decide_approval_step(
            step_two["id"],
            factories.decision_payload("APPROVED", decision_note="Same approver again."),
            APPROVER_HEADERS,
        )
        validate_error(response, ApiErrorId.DUPLICATE_APPROVER.value, 409)

        reread = validate_success(
            api_client.get_approval_step(step_two["id"], PLANNER_HEADERS), 200
        )
        domain_assert.assert_fields_equal(reread, {"decision": "PENDING"})
        domain_assert.assert_fields_equal(
            fixtures.read_contract(routed_contract["contract_id"]),
            {"approval_state": "IN_APPROVAL"},
        )

    def test_two_distinct_approvers_neither_of_them_the_planner_close_the_chain(
        self, routed_contract
    ):
        """Only distinct approving identities carry the contract to APPROVED.

        "Together these mean a contract requiring four controls needs four distinct approving identities, none of which is the awarding planner's."

        Design: Corner/rbac/the_awarding_planner_and_a_repeat_approver_are_both_barred
        """
        step_one, step_two = routed_contract["steps"]
        fixtures.decide_step(step_one["id"], "APPROVED", APPROVER_HEADERS)
        second = validate_success(
            api_client.decide_approval_step(
                step_two["id"],
                factories.decision_payload(
                    "APPROVED", decision_note="Within delegation."
                ),
                APPROVER_ALT_HEADERS,
            ),
            200,
        )
        domain_assert.assert_fields_equal(
            second, {"approver_user_id": APPROVER_ALT_USER_ID}
        )

        contract = fixtures.read_contract(routed_contract["contract_id"])
        domain_assert.assert_fields_equal(contract, {"approval_state": "APPROVED"})

        deciders = [
            step["approver_user_id"]
            for step in fixtures.approval_steps(routed_contract["contract_id"])
        ]
        assert deciders == [APPROVER_USER_ID, APPROVER_ALT_USER_ID]
        assert len(set(deciders)) == 2, "each control step needs a distinct approver"
        assert PLANNER_USER_ID not in deciders
