"""Authentication, role authorisation, row ownership and the duty gates."""

from test_helpers import (
    CO_1,
    CO_2,
    FRAUD_1,
    FRAUD_2,
    KYC_1,
    KYC_2,
    REGULATOR_1,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_ids_in_order,
    assert_null,
    assert_provider_counters,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_unknown_role,
)
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import CLOCK_DEFAULT, NUMBER_1, ROLE_REGULATOR
from test_helpers.factories import (
    blocking_dispute_payload,
    blocking_event_payload,
    certificate_payload,
    customer_payload,
    dispute_resolution_payload,
    enforcement_action_payload,
    kyc_decision_payload,
    mitigation_plan_payload,
    number_assignment_payload,
    origination_action_payload,
    provider_payload,
)


class TestAuthenticationHeaderShape:
    """Header shape is decided before anything else about the request."""

    def test_blank_and_undeclared_role_headers_are_all_unauthenticated(self, world):
        """An empty role, an empty user id and an undeclared role are each 401.

        PRD: "Both headers present and non-empty, and `X-User-Role` one of the seven declared roles — otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_or_unknown_role_headers_are_unauthenticated
        """
        world.set_clock("2026-08-19T00:00:00Z")
        rejected_bundles = (
            headers_with_blank_role(REGULATOR_1),
            headers_with_blank_user_id(ROLE_REGULATOR),
            headers_with_unknown_role(),
        )

        for headers in rejected_bundles:
            expect_error(
                world.client.create_provider(
                    provider_payload(provider_type="FACILITIES_BASED"), headers
                ),
                ERR_UNAUTHENTICATED,
            )
        expect_error(
            world.client.list_providers(headers_with_unknown_role()),
            ERR_UNAUTHENTICATED,
        )

        expect_list_total(world.client.list_providers(world.regulator), 0)


class TestExclusiveOperations:
    """Seven roles, seven operations each owned exclusively by another role."""

    def test_no_role_including_the_regulator_is_a_super_role(self, world):
        """Every attempt outside the role's own operations is refused with 403.

        PRD: "The acting role appears on the target operation's authorised-role list — otherwise `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/each_role_is_unauthorized_on_another_roles_exclusive_operation
        """
        world.set_clock("2026-08-19T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        version = world.provider_version(provider["id"])

        expect_error(
            world.client.create_certificate(
                certificate_payload(
                    provider["id"],
                    not_before="2026-08-01T00:00:00Z",
                    not_after="2027-08-01T00:00:00Z",
                ),
                world.regulator,
            ),
            ERR_UNAUTHORIZED,
        )
        expect_error(
            world.client.create_provider(
                provider_payload(provider_type="GATEWAY"), world.policy_admin
            ),
            ERR_UNAUTHORIZED,
        )
        expect_error(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    customer["id"],
                    calling_number=NUMBER_1,
                    analytics_score=0.9,
                    reason="ANALYTICS_SCORE",
                ),
                world.officer(CO_1),
            ),
            ERR_UNAUTHORIZED,
        )
        expect_error(
            world.client.create_mitigation_plan(
                mitigation_plan_payload(provider["id"], version), world.kyc(KYC_1)
            ),
            ERR_UNAUTHORIZED,
        )
        expect_error(
            world.client.create_customer(
                customer_payload(provider["id"], kyc_evidence_level="SELF_ATTESTED"),
                world.fraud(FRAUD_1),
            ),
            ERR_UNAUTHORIZED,
        )
        expect_error(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    provider["id"],
                    basis="UNFILED_PLAN",
                    violation_count=1,
                    violation_days=1,
                    assessment_basis="PER_VIOLATION",
                ),
                world.provider_admin(provider["id"]),
            ),
            ERR_UNAUTHORIZED,
        )
        expect_error(
            world.client.kyc_decision(
                customer["id"],
                kyc_decision_payload("VERIFY"),
                world.caller(customer["id"]),
            ),
            ERR_UNAUTHORIZED,
        )

        for listing in (
            world.client.list_certificates(
                world.regulator, provider_id=provider["id"]
            ),
            world.client.list_mitigation_plans(
                world.regulator, provider_id=provider["id"]
            ),
            world.client.list_blocking_events(
                world.regulator, provider_id=provider["id"]
            ),
            world.client.list_enforcement_actions(
                world.regulator, provider_id=provider["id"]
            ),
        ):
            expect_list_total(listing, 0)
        expect_list_total(world.client.list_providers(world.regulator), 1)
        expect_list_total(
            world.client.list_customers(world.regulator, provider_id=provider["id"]), 1
        )
        assert_equals(world.read_customer(customer["id"]), "kyc_state", "PENDING")


class TestRowOwnership:
    """Ownership is identity-to-row, not role-to-endpoint."""

    def test_the_wrong_owner_is_refused_where_the_rightful_owner_succeeds(self, world):
        """Provider B cannot assign provider A's number, and customer B cannot dispute A's block.

        PRD: "For the two entity-backed roles, the acting identity must own the target row: a `ProviderAdmin`'s `X-User-ID` equals the target row's `provider_id`, and a `Caller`'s `X-User-ID` equals the target row's `customer_id` — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/rbac/provider_admin_and_caller_are_forbidden_outside_their_own_rows
        """
        world.set_clock("2026-08-20T00:00:00Z")
        first = world.register_provider()
        second = world.register_provider(provider_type="NON_FACILITIES_RESELLER")
        own_customer = world.verified_enabled_customer(first["id"])
        foreign_customer = world.onboard_customer(second["id"])
        event = world.block_calls(
            first["id"],
            own_customer["id"],
            analyst_id=FRAUD_1,
            calling_number=NUMBER_1,
            analytics_score=0.7,
            reason="ANALYTICS_SCORE",
        )
        assignment_payload = number_assignment_payload(
            first["id"],
            own_customer["id"],
            telephone_number=NUMBER_1,
            ownership_evidence="DIRECT_ALLOCATION",
            effective_from=CLOCK_DEFAULT,
        )

        expect_error(
            world.client.create_number_assignment(
                assignment_payload, world.provider_admin(second["id"])
            ),
            ERR_NOT_RESOURCE_OWNER,
        )
        expect_error(
            world.client.create_blocking_dispute(
                blocking_dispute_payload(
                    event["id"],
                    claim_note="Filed by a caller who does not own the blocked number",
                ),
                world.caller(foreign_customer["id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
        )

        assignment = expect_created(
            world.client.create_number_assignment(
                assignment_payload, world.provider_admin(first["id"])
            )
        )
        dispute = expect_created(
            world.client.create_blocking_dispute(
                blocking_dispute_payload(
                    event["id"],
                    claim_note="Filed by the caller the block was recorded against",
                ),
                world.caller(own_customer["id"]),
            )
        )

        assert_equals(assignment, "status", "ACTIVE")
        assert_fields(dispute, state="FILED", customer_id=own_customer["id"])
        assert_provider_counters(
            world.read_provider(first["id"]), active_assigned_number_count=1
        )
        assert_provider_counters(
            world.read_provider(second["id"]), active_assigned_number_count=0
        )
        items, _ = expect_list_total(
            world.client.list_blocking_disputes(
                world.regulator, blocking_event_id=event["id"]
            ),
            1,
        )
        assert_ids_in_order(items, [dispute["id"]])


class TestSegregationOfDuties:
    """All three paired steps are keyed on the acting user identifier."""

    def test_the_second_actor_of_each_pair_must_be_a_different_user(self, world):
        """Each first actor is refused its own second step; a colleague then succeeds.

        PRD: "Three points in the system require two different human operators, and all three compare the acting `X-User-ID` against a user identifier the system recorded at the earlier step."

        Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_id_at_all_three_pairs
        """
        world.set_clock("2026-08-21T00:00:00Z")
        provider = world.register_provider()
        plan = world.draft_plan(provider["id"], officer_id=CO_1)
        world.submit_plan(plan["id"], CO_1)
        world.decide_plan(plan["id"], decision="ACCEPT")
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
        )
        world.kyc_submit(customer["id"], submitter_id=KYC_1)
        event = world.block_calls(
            provider["id"],
            customer["id"],
            analyst_id=FRAUD_1,
            calling_number=NUMBER_1,
            analytics_score=0.7,
            reason="ANALYTICS_SCORE",
        )
        dispute = world.file_dispute(
            event["id"],
            customer["id"],
            claim_note="Consented reminder calls, please review",
        )
        world.review_dispute(dispute["id"], FRAUD_2)
        report = world.generate_report(
            provider["id"],
            variant="CERTIFIED",
            officer_id=CO_2,
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        )

        expect_error(
            world.client.kyc_decision(
                customer["id"], kyc_decision_payload("VERIFY"), world.kyc(KYC_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )
        assert_equals(
            world.read_customer(customer["id"]), "kyc_state", "UNDER_REVIEW"
        )
        verified = expect_ok(
            world.client.kyc_decision(
                customer["id"], kyc_decision_payload("VERIFY"), world.kyc(KYC_2)
            )
        )
        assert_fields(
            verified,
            kyc_state="VERIFIED",
            kyc_submitted_by_user_id=KYC_1,
            kyc_decided_by_user_id=KYC_2,
        )

        resolution = dispute_resolution_payload(
            "UPHOLD", "Analytics score independently confirmed"
        )
        expect_error(
            world.client.resolve_blocking_dispute(
                dispute["id"], resolution, world.fraud(FRAUD_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )
        assert_equals(world.read_dispute(dispute["id"]), "state", "UNDER_REVIEW")
        resolved = expect_ok(
            world.client.resolve_blocking_dispute(
                dispute["id"], resolution, world.fraud(FRAUD_2)
            )
        )
        assert_fields(resolved, state="UPHELD", resolved_by_user_id=FRAUD_2)
        assert_fields(
            world.read_blocking_event(event["id"]),
            status="UPHELD",
            blocked_by_user_id=FRAUD_1,
        )

        expect_error(
            world.client.certify_effectiveness_report(
                report["id"], world.officer(CO_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )
        signed_off = expect_ok(
            world.client.certify_effectiveness_report(
                report["id"], world.officer(CO_2)
            )
        )
        assert_fields(signed_off, state="SIGNED_OFF", signed_off_by_user_id=CO_2)
        assert_equals(world.read_plan(plan["id"]), "filed_by_user_id", CO_1)
        assert_decimal_4(
            world.read_provider(provider["id"]), "blocking_false_positive_rate", 0.0
        )


class TestSharedOriginationOperation:
    """One endpoint, two roles, one cascade."""

    def test_the_regulator_restores_what_the_provider_admin_suspended(self, world):
        """Both roles drive the same action endpoint and the same assignment cascade.

        PRD: "The origination dimension is driven through a single action-bearing operation shared by `ProviderAdmin` and `Regulator`."

        Design: Corner/rbac/origination_actions_is_shared_by_regulator_and_provider_admin
        """
        world.set_clock("2026-08-22T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
        )
        world.kyc_verified(customer["id"])

        enabled = expect_ok(
            world.client.origination_action(
                customer["id"],
                origination_action_payload("ENABLE"),
                world.provider_admin(provider["id"]),
            )
        )
        assert_equals(enabled, "origination_state", "ENABLED")

        assignment = expect_created(
            world.client.create_number_assignment(
                number_assignment_payload(
                    provider["id"],
                    customer["id"],
                    telephone_number=NUMBER_1,
                    ownership_evidence="DIRECT_ALLOCATION",
                    effective_from=CLOCK_DEFAULT,
                ),
                world.provider_admin(provider["id"]),
            )
        )

        suspended = expect_ok(
            world.client.origination_action(
                customer["id"],
                origination_action_payload("SUSPEND", "PROVIDER_REQUEST"),
                world.provider_admin(provider["id"]),
            )
        )

        assert_fields(
            suspended,
            origination_state="SUSPENDED",
            suspension_cause="PROVIDER_REQUEST",
        )
        assert_null(suspended, "suspension_source_id")
        assert_equals(
            world.read_assignment(assignment["id"]), "status", "SUSPENDED_BY_CUSTOMER"
        )
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=0
        )

        restored = expect_ok(
            world.client.origination_action(
                customer["id"],
                origination_action_payload("RESTORE"),
                world.regulator,
            )
        )

        assert_equals(restored, "origination_state", "ENABLED")
        assert_null(restored, "suspension_cause")
        assert_null(restored, "suspension_source_id")
        reactivated = world.read_assignment(assignment["id"])
        assert_equals(reactivated, "status", "ACTIVE")
        assert_null(reactivated, "revoked_at")
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=1
        )
        assert_equals(world.read_customer(customer["id"]), "kyc_state", "VERIFIED")
