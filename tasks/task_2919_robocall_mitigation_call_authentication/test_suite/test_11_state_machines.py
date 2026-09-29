"""Declared transitions, their side effects, their refusals and their cascades."""

from test_helpers import (
    OFFICER_1,
    assert_equals,
    assert_fields,
    assert_instant,
    assert_null,
    assert_provider_counters,
    assert_versioned_row,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import ERR_CERTIFICATE_STATE_INVALID
from test_helpers.constants import (
    MINIMUM_COMPLIANT_PRACTICES,
    NUMBER_1,
    NUMBER_2,
)
from test_helpers.factories import (
    certificate_renewal_payload,
    mitigation_plan_payload,
    origination_action_payload,
    plan_decision_payload,
    revocation_payload,
)


class TestCertificateTransitions:
    """Issuance, activation and the terminal lockdown of a revoked credential."""

    def test_issue_moves_a_requested_certificate_to_issued(self, world):
        """Issuance stamps issued_at from the clock, bumps the version and leaves activation open.

        PRD: "Issuance advances `REQUESTED → ISSUED` and stamps `issued_at` with the current logical clock."

        Design: Corner/state_machines/certificate_request_moves_to_issued_on_issue_trigger
        """
        world.set_clock("2026-08-02T09:00:00Z")
        provider = world.register_provider()
        certificate = world.request_certificate(provider["id"])

        issued = expect_ok(
            world.client.issue_certificate(certificate["id"], world.policy_admin)
        )

        assert_equals(issued, "status", "ISSUED")
        assert_instant(issued, "issued_at", "2026-08-02T09:00:00Z")
        assert_null(issued, "activated_at")
        assert_versioned_row(issued, 2)

        refreshed = world.read_provider(provider["id"])
        assert_null(refreshed, "active_certificate_id")
        assert_equals(refreshed, "auth_posture", "SIGNING_SUSPENDED")

    def test_activating_a_second_certificate_is_refused_while_one_is_active(
        self, world
    ):
        """An in-window ISSUED certificate cannot displace the provider's live credential.

        PRD: "Activation additionally requires that the current logical clock lie inside the closed validity interval — at or after `not_before` and at or before `not_after` — and that the provider hold no other certificate already in `ACTIVE`."

        Design: Corner/state_machines/second_certificate_activation_rejected_while_one_is_active
        """
        world.set_clock("2026-08-02T00:00:00Z")
        provider = world.register_provider()
        first = world.request_certificate(provider["id"])
        world.issue_certificate(first["id"])
        world.activate_certificate(first["id"], provider["id"])
        second = world.request_certificate(provider["id"])
        world.issue_certificate(second["id"])

        expect_error(
            world.client.activate_certificate(
                second["id"], world.provider_admin(provider["id"])
            ),
            ERR_CERTIFICATE_STATE_INVALID,
        )

        blocked = world.read_certificate(second["id"])
        assert_equals(blocked, "status", "ISSUED")
        assert_null(blocked, "activated_at")
        assert_equals(world.read_certificate(first["id"]), "status", "ACTIVE")
        assert_equals(
            world.read_provider(provider["id"]), "active_certificate_id", first["id"]
        )

    def test_activating_a_requested_certificate_is_an_invalid_transition(self, world):
        """Skipping issuance is refused and leaves the provider without a signing pointer.

        PRD: "Any of those preconditions failing yields `ERR_CERTIFICATE_STATE_INVALID` (409), which is also the code for issuing, renewing or revoking from a status the transition does not permit."

        Design: Corner/state_machines/activating_a_requested_certificate_is_an_invalid_transition
        """
        world.set_clock("2026-08-02T00:00:00Z")
        provider = world.register_provider(provider_type="GATEWAY")
        certificate = world.request_certificate(provider["id"])

        expect_error(
            world.client.activate_certificate(
                certificate["id"], world.provider_admin(provider["id"])
            ),
            ERR_CERTIFICATE_STATE_INVALID,
        )

        unchanged = world.read_certificate(certificate["id"])
        assert_equals(unchanged, "status", "REQUESTED")
        assert_versioned_row(unchanged, 1)
        assert_null(world.read_provider(provider["id"]), "active_certificate_id")

    def test_issuing_the_same_certificate_twice_fails_on_the_second_call(self, world):
        """The replayed issue call is refused and issued_at keeps its original instant.

        PRD: "It is refused unless the certificate is still `REQUESTED` and its `not_after` lies strictly after the current logical clock — there is no point issuing a credential that has already lapsed."

        Design: Corner/state_machines/issuing_the_same_certificate_twice_fails_on_the_second_call
        """
        world.set_clock("2026-08-05T00:00:00Z")
        provider = world.register_provider()
        certificate = world.request_certificate(provider["id"])
        world.issue_certificate(certificate["id"])
        world.set_clock("2026-08-06T00:00:00Z")

        expect_error(
            world.client.issue_certificate(certificate["id"], world.policy_admin),
            ERR_CERTIFICATE_STATE_INVALID,
        )

        unchanged = world.read_certificate(certificate["id"])
        assert_equals(unchanged, "status", "ISSUED")
        assert_instant(unchanged, "issued_at", "2026-08-05T00:00:00Z")
        assert_versioned_row(unchanged, 2)

    def test_a_revoked_certificate_is_locked_against_issue_and_renew(self, world):
        """Both later triggers are refused and no successor row is ever created.

        PRD: "`SUPERSEDED`, `REVOKED` and `EXPIRED` are all terminal — no further transition is available out of any of them."

        Design: Corner/state_machines/revoked_certificate_is_locked_against_issue_and_renew
        """
        world.set_clock("2026-08-04T00:00:00Z")
        provider = world.register_provider()
        certificate = world.request_certificate(provider["id"])
        world.issue_certificate(certificate["id"])
        expect_ok(
            world.client.revoke_certificate(
                certificate["id"],
                revocation_payload("KEY_COMPROMISE"),
                world.policy_admin,
            )
        )

        expect_error(
            world.client.issue_certificate(certificate["id"], world.policy_admin),
            ERR_CERTIFICATE_STATE_INVALID,
        )
        expect_error(
            world.client.renew_certificate(
                certificate["id"],
                certificate_renewal_payload(
                    not_before="2026-08-04T00:00:00Z", not_after="2027-08-04T00:00:00Z"
                ),
                world.policy_admin,
            ),
            ERR_CERTIFICATE_STATE_INVALID,
        )

        locked = world.read_certificate(certificate["id"])
        assert_fields(locked, status="REVOKED", revocation_reason="KEY_COMPROMISE")
        assert_instant(locked, "revoked_at", "2026-08-04T00:00:00Z")
        expect_list_total(
            world.client.list_certificates(
                world.policy_admin, predecessor_certificate_id=certificate["id"]
            ),
            0,
        )


def _provider_with_active_certificate(world):
    """A provider holding one ACTIVE certificate and no mitigation plan."""
    provider = world.register_provider()
    certificate = world.request_certificate(provider["id"])
    world.issue_certificate(certificate["id"])
    world.activate_certificate(certificate["id"], provider["id"])
    return provider["id"]


class TestMitigationPlanTransitions:
    """Drafting, acceptance and the deficiency revision loop."""

    def test_a_new_plan_starts_in_draft_and_leaves_the_provider_unfiled(self, world):
        """Drafting is not filing: the plan is DRAFT and the provider stays suspended.

        PRD: "A newly drafted plan lands in `filing_state` `DRAFT`, with `filed_by_user_id`, `submitted_at` and `decided_at` all null, `deficiency_reasons` an empty list, and `deficiency_count` and `revision_count` both 0."

        Design: Corner/state_machines/mitigation_plan_starts_in_draft_and_leaves_provider_unfiled
        """
        world.set_clock("2026-08-03T00:00:00Z")
        provider_id = _provider_with_active_certificate(world)

        plan = expect_created(
            world.client.create_mitigation_plan(
                mitigation_plan_payload(
                    provider_id,
                    world.provider_version(provider_id),
                    prevention_practices=list(MINIMUM_COMPLIANT_PRACTICES),
                ),
                world.officer(OFFICER_1),
            )
        )

        assert_equals(plan, "filing_state", "DRAFT")
        assert_null(plan, "submitted_at")
        assert_null(plan, "decided_at")
        assert_null(plan, "filed_by_user_id")
        assert_equals(plan, "revision_count", 0)

        provider = world.read_provider(provider_id)
        assert_fields(
            provider,
            rmd_filing_status="UNFILED",
            auth_posture="SIGNING_SUSPENDED",
        )

    def test_acceptance_flips_the_filing_status_and_the_posture(self, world):
        """One decision stamps decided_at, completes the filing and reaches full attestation.

        PRD: "An acceptance advances `SUBMITTED → ACCEPTED`, stamps `decided_at`, and drives `rmd_filing_status` to `COMPLETE` when the provider also holds an `ACTIVE` certificate — or to `PARTIAL` when it does not — before the posture ladder runs again."

        Design: Corner/state_machines/plan_acceptance_side_effects_flip_filing_status_and_posture
        """
        world.set_clock("2026-08-03T00:00:00Z")
        provider_id = _provider_with_active_certificate(world)
        plan = world.draft_plan(
            provider_id,
            practices=[
                "KYC_ONBOARDING",
                "TRACEBACK_COOPERATION",
                "CALL_BLOCKING_ANALYTICS",
            ],
        )
        world.submit_plan(plan["id"])

        accepted = expect_ok(
            world.client.decide_mitigation_plan(
                plan["id"], plan_decision_payload("ACCEPT"), world.regulator
            )
        )

        assert_equals(accepted, "filing_state", "ACCEPTED")
        assert_instant(accepted, "decided_at", "2026-08-03T00:00:00Z")
        assert_equals(accepted, "deficiency_count", 0)

        provider = world.read_provider(provider_id)
        assert_fields(
            provider,
            rmd_filing_status="COMPLETE",
            auth_posture="FULL_ATTESTATION",
        )
        assert_provider_counters(provider, penalty_points=0)

    def test_the_deficiency_loop_resubmits_and_keeps_its_penalty_points(self, world):
        """Resubmitting from DEFICIENT refiles the plan without refunding the 2 points.

        PRD: "The revision cycle `SUBMITTED → DEFICIENT → SUBMITTED` may repeat without bound: `deficiency_count` keeps accruing across the whole life of the plan while `revision_count` tracks how many times the loop has been travelled."

        Design: Corner/state_machines/plan_deficiency_cycle_resubmits_and_accumulates_revisions
        """
        world.set_clock("2026-08-05T00:00:00Z")
        provider_id = _provider_with_active_certificate(world)
        plan = world.draft_plan(provider_id)
        world.submit_plan(plan["id"])
        world.decide_plan(
            plan["id"],
            decision="DEFICIENT",
            deficiency_reasons=["KYC_PROCEDURE_TOO_WEAK"],
        )

        resubmitted = expect_ok(
            world.client.submit_mitigation_plan(plan["id"], world.officer(OFFICER_1))
        )

        assert_equals(resubmitted, "filing_state", "SUBMITTED")
        assert_equals(resubmitted, "deficiency_count", 1)

        provider = world.read_provider(provider_id)
        assert_provider_counters(provider, penalty_points=2)
        assert_fields(
            provider,
            rmd_filing_status="PARTIAL",
            auth_posture="GATEWAY_LIMITED",
        )


def _customer_with_two_numbers(world, second_evidence="PORTED_IN"):
    """A verified, enabled customer holding two ACTIVE assignments."""
    provider = world.register_provider()
    customer = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="CONTRACT_ONLY"
    )
    first = world.assign_number(
        provider["id"],
        customer["id"],
        telephone_number=NUMBER_1,
        ownership_evidence="DIRECT_ALLOCATION",
        effective_from="2026-08-01T00:00:00Z",
    )
    second = world.assign_number(
        provider["id"],
        customer["id"],
        telephone_number=NUMBER_2,
        ownership_evidence=second_evidence,
        effective_from="2026-08-01T00:00:00Z",
    )
    return provider["id"], customer["id"], first["id"], second["id"]


class TestOriginationCascades:
    """What a termination, a revocation and a suspension do to number inventory."""

    def test_terminating_a_customer_revokes_every_live_assignment(self, world):
        """One TERMINATE revokes both numbers and empties the provider's inventory count.

        PRD: "Termination moves `origination_state` to `TERMINATED`, clears `suspension_cause` and `suspension_source_id`, and revokes number inventory rather than merely suspending it: every assignment of that customer whose `status` is `ACTIVE` or `SUSPENDED_BY_CUSTOMER` moves to `REVOKED` with `revoked_at` stamped at the current logical clock, after which the provider's `active_assigned_number_count` is recomputed."

        Design: Corner/state_machines/terminating_a_customer_revokes_every_live_assignment
        """
        world.set_clock("2026-08-07T00:00:00Z")
        provider_id, customer_id, first_id, second_id = _customer_with_two_numbers(world)

        terminated = expect_ok(
            world.client.origination_action(
                customer_id,
                origination_action_payload("TERMINATE"),
                world.provider_admin(provider_id),
            )
        )

        assert_fields(
            terminated, origination_state="TERMINATED", kyc_state="VERIFIED"
        )
        for assignment_id in (first_id, second_id):
            assignment = world.read_assignment(assignment_id)
            assert_equals(assignment, "status", "REVOKED")
            assert_instant(assignment, "revoked_at", "2026-08-07T00:00:00Z")

        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=0
        )

    def test_revoking_one_assignment_syncs_the_provider_inventory_ledger(self, world):
        """The count is a full recount: two ACTIVE rows become one, the customer is untouched.

        PRD: "An assignment can be revoked by a `ProviderAdmin` from either `ACTIVE` or `SUSPENDED_BY_CUSTOMER`, which stamps `revoked_at` at the current logical clock, moves `status` to `REVOKED`, and recomputes the provider's `active_assigned_number_count` — the compensating half of the number-inventory invariant."

        Design: Corner/state_machines/revoking_one_assignment_syncs_the_provider_inventory_ledger
        """
        world.set_clock("2026-08-07T00:00:00Z")
        provider_id, customer_id, first_id, second_id = _customer_with_two_numbers(
            world, second_evidence="DIRECT_ALLOCATION"
        )
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=2
        )

        revoked = expect_ok(
            world.client.revoke_number_assignment(
                first_id, world.provider_admin(provider_id)
            )
        )

        assert_equals(revoked, "status", "REVOKED")
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=1
        )
        assert_equals(world.read_assignment(second_id), "status", "ACTIVE")
        assert_equals(world.read_customer(customer_id), "origination_state", "ENABLED")

    def test_the_suspension_cascade_skips_assignments_already_revoked(self, world):
        """Only the live assignment is suspended; the revoked one stays terminal.

        PRD: "A successful suspension writes the supplied value into `suspension_cause`, leaves `suspension_source_id` null because no artifact drove it, then cascades: every number assignment of that customer whose `status` is `ACTIVE` moves to `SUSPENDED_BY_CUSTOMER`, and because those assignments left the active set, the provider's `active_assigned_number_count` is recomputed."

        Design: Corner/state_machines/suspension_cascade_skips_assignments_already_revoked
        """
        world.set_clock("2026-08-07T00:00:00Z")
        provider_id, customer_id, live_id, dead_id = _customer_with_two_numbers(
            world, second_evidence="LEASED_FROM_CARRIER"
        )
        world.revoke_assignment(dead_id, provider_id)

        suspended = expect_ok(
            world.client.origination_action(
                customer_id,
                origination_action_payload("SUSPEND", "PROVIDER_REQUEST"),
                world.provider_admin(provider_id),
            )
        )

        assert_fields(
            suspended,
            origination_state="SUSPENDED",
            suspension_cause="PROVIDER_REQUEST",
        )
        assert_null(suspended, "suspension_source_id")
        assert_equals(
            world.read_assignment(live_id), "status", "SUSPENDED_BY_CUSTOMER"
        )
        assert_equals(world.read_assignment(dead_id), "status", "REVOKED")
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=0
        )
