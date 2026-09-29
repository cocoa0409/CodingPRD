"""Refusals: per-family 404 codes, format ladders and state guards."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    FRAUD_1,
    FRAUD_2,
    KYC_2,
    OFFICER_1,
    assert_cents,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_instant,
    assert_null,
    assert_provider_counters,
    build_signing_ready_provider,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_NOT_ACTIVE,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_ATTESTATION_NOT_FOUND,
    ERR_CALL_DETAIL_INCOMPLETE,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_CUSTOMER_KYC_STATE_INVALID,
    ERR_DISPUTE_NOT_FOUND,
    ERR_DISPUTE_STATE_INVALID,
    ERR_DUPLICATE_DISPUTE,
    ERR_ENFORCEMENT_NOT_FOUND,
    ERR_ENFORCEMENT_STATE_INVALID,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_NUMBER_FORMAT,
    ERR_NOTICE_ALREADY_CLOSED,
    ERR_NOTICE_NOT_FOUND,
    ERR_OBSERVATION_NOT_FOUND,
    ERR_ORIGINATION_STATE_INVALID,
    ERR_PLAN_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_STATE_INVALID,
    ERR_TRACEBACK_ALREADY_CLOSED,
)
from test_helpers.constants import CLOCK_DEFAULT, NUMBER_1, NUMBER_CALLED
from test_helpers.factories import (
    adjudication_payload,
    blocking_dispute_payload,
    certificate_payload,
    dispute_resolution_payload,
    kyc_decision_payload,
    notice_investigation_payload,
    number_assignment_payload,
    origination_action_payload,
    traceback_response_payload,
)

# A bare ten-digit string: well-formed as a national number, invalid as E.164.
BARE_TEN_DIGIT_NUMBER = "2025550111"


class TestPerFamilyNotFoundCodes:
    """Ten reads against ten unknown identifiers, ten different codes."""

    def test_each_unknown_path_identifier_names_its_own_entity(self, world):
        """No shared ERR_NOT_FOUND exists: every resource family owns its own code.

        PRD: "Every identifier embedded in the URL path must resolve to a row, validated strictly left to right, with the 404 code naming the entity that failed: `ERR_PROVIDER_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_TRACEBACK_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BLOCKING_EVENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_ENFORCEMENT_NOT_FOUND` or `ERR_REPORT_NOT_FOUND`."

        Design: Corner/errors/path_ids_that_match_nothing_each_return_their_own_not_found
        """
        world.set_clock("2026-08-15T00:00:00Z")
        client = world.client
        reads = [
            (client.get_provider, ERR_PROVIDER_NOT_FOUND),
            (client.get_certificate, ERR_CERTIFICATE_NOT_FOUND),
            (client.get_mitigation_plan, ERR_PLAN_NOT_FOUND),
            (client.get_number_assignment, ERR_ASSIGNMENT_NOT_FOUND),
            (client.get_call_attestation, ERR_ATTESTATION_NOT_FOUND),
            (client.get_traffic_observation, ERR_OBSERVATION_NOT_FOUND),
            (client.get_illegal_traffic_notice, ERR_NOTICE_NOT_FOUND),
            (client.get_blocking_dispute, ERR_DISPUTE_NOT_FOUND),
            (client.get_enforcement_action, ERR_ENFORCEMENT_NOT_FOUND),
            (client.get_effectiveness_report, ERR_REPORT_NOT_FOUND),
        ]

        for read, expected_error in reads:
            expect_error(read(NON_EXISTENT_UUID, world.regulator), expected_error)

        expect_list_total(client.list_providers(world.regulator), 0)


class TestInputLadderOrder:
    """Number format is decided before interval well-ordering."""

    def test_the_number_format_refusal_masks_the_reversed_interval(self, world):
        """One request violates both rules and reports only the earlier one.

        PRD: "Every `telephone_number`, `calling_number` and `called_number` supplied is E.164: a leading `+` followed by 11 to 15 digits — otherwise `ERR_INVALID_NUMBER_FORMAT` (422)."

        Design: Corner/errors/malformed_numbers_and_intervals_are_rejected_in_priority_order
        """
        world.set_clock("2026-08-15T00:00:00Z")
        provider = world.register_provider()
        customer = world.verified_enabled_customer(provider["id"])

        expect_error(
            world.client.create_number_assignment(
                number_assignment_payload(
                    provider["id"],
                    customer["id"],
                    telephone_number=BARE_TEN_DIGIT_NUMBER,
                    ownership_evidence="DIRECT_ALLOCATION",
                    effective_from="2026-09-01T00:00:00Z",
                    effective_to="2026-08-01T00:00:00Z",
                ),
                world.provider_admin(provider["id"]),
            ),
            ERR_INVALID_NUMBER_FORMAT,
        )
        expect_error(
            world.client.create_number_assignment(
                number_assignment_payload(
                    provider["id"],
                    customer["id"],
                    telephone_number=NUMBER_1,
                    ownership_evidence="DIRECT_ALLOCATION",
                    effective_from="2026-09-01T00:00:00Z",
                    effective_to="2026-08-01T00:00:00Z",
                ),
                world.provider_admin(provider["id"]),
            ),
            ERR_INVALID_INTERVAL,
        )
        expect_error(
            world.client.create_certificate(
                certificate_payload(
                    provider["id"],
                    not_before="2026-09-01T00:00:00Z",
                    not_after="2026-09-01T00:00:00Z",
                ),
                world.policy_admin,
            ),
            ERR_INVALID_INTERVAL,
        )

        expect_list_total(
            world.client.list_number_assignments(
                world.regulator, provider_id=provider["id"]
            ),
            0,
        )
        expect_list_total(
            world.client.list_certificates(
                world.policy_admin, provider_id=provider["id"]
            ),
            0,
        )
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=0
        )


class TestStateGuardsOnTheCustomerLifecycles:
    """Three lifecycles, three distinct 409 identifiers."""

    def test_each_lifecycle_refuses_the_step_its_state_does_not_offer(self, world):
        """A decision, a suspension and a second revocation are each refused in turn.

        PRD: "Submitting a package for a customer already `UNDER_REVIEW` is refused with `ERR_CUSTOMER_KYC_STATE_INVALID` (409); that same code refuses a decision on a customer that is not `UNDER_REVIEW`, and those two operations — package submission and package decision — are the only ones it guards."

        Design: Corner/errors/out_of_order_customer_and_assignment_calls_are_rejected
        """
        world.set_clock("2026-08-16T00:00:00Z")
        provider = world.register_provider()
        untouched = world.onboard_customer(
            provider["id"], kyc_evidence_level="SELF_ATTESTED"
        )
        cleared = world.verified_enabled_customer(provider["id"])
        assignment = world.assign_number(
            provider["id"],
            cleared["id"],
            telephone_number=NUMBER_1,
            ownership_evidence="DIRECT_ALLOCATION",
            effective_from=CLOCK_DEFAULT,
        )
        world.revoke_assignment(assignment["id"], provider["id"])

        expect_error(
            world.client.kyc_decision(
                untouched["id"], kyc_decision_payload("VERIFY"), world.kyc(KYC_2)
            ),
            ERR_CUSTOMER_KYC_STATE_INVALID,
        )
        expect_error(
            world.client.origination_action(
                untouched["id"],
                origination_action_payload("SUSPEND", "PROVIDER_REQUEST"),
                world.provider_admin(provider["id"]),
            ),
            ERR_ORIGINATION_STATE_INVALID,
        )
        expect_error(
            world.client.revoke_number_assignment(
                assignment["id"], world.provider_admin(provider["id"])
            ),
            ERR_ASSIGNMENT_NOT_ACTIVE,
        )

        unchanged_customer = world.read_customer(untouched["id"])
        assert_fields(
            unchanged_customer, kyc_state="PENDING", origination_state="DISABLED"
        )
        unchanged_assignment = world.read_assignment(assignment["id"])
        assert_equals(unchanged_assignment, "status", "REVOKED")
        assert_instant(unchanged_assignment, "revoked_at", "2026-08-16T00:00:00Z")
        assert_provider_counters(
            world.read_provider(provider["id"]),
            active_assigned_number_count=0,
            penalty_points=0,
        )


class TestTracebackResponseGuards:
    """Completeness is about number inventory, not about payload shape."""

    def test_an_unowning_customer_is_incomplete_and_a_closed_request_is_locked(
        self, world
    ):
        """A perfectly matching attestation still fails when its customer owns no number.

        PRD: "Separately, the identified customer must hold at least one number assignment covering the traced `calling_number` at `origination_time`; a response that omits either identifier, or whose identified customer has no such assignment, is refused with `ERR_CALL_DETAIL_INCOMPLETE` (422)."

        Design: Corner/errors/traceback_response_rejects_incomplete_call_detail_and_a_second_response
        """
        world.set_clock("2026-08-16T12:00:00Z")
        setup = build_signing_ready_provider(world)
        bare = world.verified_enabled_customer(setup.provider_id)
        holder_call = world.sign_call(
            setup.provider_id,
            setup.customer_id,
            NUMBER_1,
            NUMBER_CALLED,
            "2026-08-16T06:00:00Z",
        )
        bare_call = world.sign_call(
            setup.provider_id,
            bare["id"],
            NUMBER_1,
            NUMBER_CALLED,
            "2026-08-16T06:00:00Z",
        )
        traceback = world.open_traceback(
            setup.provider_id,
            calling_number=NUMBER_1,
            called_number=NUMBER_CALLED,
            origination_time="2026-08-16T06:00:00Z",
        )

        expect_error(
            world.client.respond_traceback_request(
                traceback["id"],
                traceback_response_payload(bare["id"], bare_call["id"]),
                world.officer(OFFICER_1),
            ),
            ERR_CALL_DETAIL_INCOMPLETE,
        )
        still_open = world.read_traceback(traceback["id"])
        assert_fields(
            still_open, state="RECEIVED", call_detail_complete=False
        )
        assert_null(still_open, "responded_at")
        assert_instant(
            still_open, "response_deadline_at", "2026-08-17T12:00:00Z"
        )

        answered = expect_ok(
            world.client.respond_traceback_request(
                traceback["id"],
                traceback_response_payload(setup.customer_id, holder_call["id"]),
                world.officer(OFFICER_1),
            )
        )

        assert_fields(
            answered,
            state="RESPONDED",
            lateness_seconds=0,
            call_detail_complete=True,
            identified_customer_id=setup.customer_id,
        )
        assert_instant(answered, "responded_at", "2026-08-16T12:00:00Z")

        expect_error(
            world.client.respond_traceback_request(
                traceback["id"],
                traceback_response_payload(setup.customer_id, holder_call["id"]),
                world.officer(OFFICER_1),
            ),
            ERR_TRACEBACK_ALREADY_CLOSED,
        )
        assert_equals(
            world.read_traceback(traceback["id"]),
            "identified_customer_id",
            setup.customer_id,
        )

        provider = world.read_provider(setup.provider_id)
        assert_provider_counters(
            provider, overdue_traceback_count=0, penalty_points=0
        )
        assert_equals(provider, "auth_posture", "FULL_ATTESTATION")


class TestClosedArtifactGuards:
    """Four regulatory lifecycles, four distinct conflict identifiers."""

    def test_each_artifact_family_refuses_its_premature_repeat_step(self, world):
        """A repeat investigation, an early resolution, adjudication and filing all conflict.

        PRD: "**State preconditions**, one code per artifact family: `ERR_CERTIFICATE_STATE_INVALID`, `ERR_NO_ACTIVE_CERTIFICATE`, `ERR_PLAN_STATE_INVALID`, `ERR_CUSTOMER_KYC_STATE_INVALID`, `ERR_ORIGINATION_STATE_INVALID`, `ERR_ASSIGNMENT_NOT_ACTIVE`, `ERR_TRACEBACK_ALREADY_CLOSED`, `ERR_NOTICE_ALREADY_CLOSED`, `ERR_DISPUTE_STATE_INVALID`, `ERR_ENFORCEMENT_STATE_INVALID` and `ERR_REPORT_STATE_INVALID` — all 409, in that relative order, and all before any business rule below."

        Design: Corner/errors/closed_regulatory_artifacts_are_rejected_on_repeat_transitions
        """
        world.set_clock("2026-08-17T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        notice = world.serve_notice(provider["id"], calling_number=NUMBER_1)
        world.investigate_notice(notice["id"], customer["id"])
        event = world.block_calls(
            provider["id"],
            customer["id"],
            analyst_id=FRAUD_1,
            calling_number=NUMBER_1,
            analytics_score=0.8,
            reason="NOTICE_MANDATE",
        )
        dispute = world.file_dispute(
            event["id"],
            customer["id"],
            claim_note="Survey calls placed to opted-in respondents",
        )
        action = world.assess_forfeiture(
            provider["id"],
            basis="UNMITIGATED_NOTICE",
            violation_count=2,
            violation_days=5,
            assessment_basis="PER_VIOLATION",
        )
        report = world.generate_report(
            provider["id"],
            variant="CERTIFIED",
            officer_id=OFFICER_1,
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        )

        expect_error(
            world.client.investigate_notice(
                notice["id"],
                notice_investigation_payload(customer["id"]),
                world.officer(OFFICER_1),
            ),
            ERR_NOTICE_ALREADY_CLOSED,
        )
        expect_error(
            world.client.resolve_blocking_dispute(
                dispute["id"],
                dispute_resolution_payload(
                    "UPHOLD", "Resolved before review was ever opened"
                ),
                world.fraud(FRAUD_2),
            ),
            ERR_DISPUTE_STATE_INVALID,
        )
        expect_error(
            world.client.adjudicate_enforcement_action(
                action["id"], adjudication_payload("SUSTAIN"), world.regulator
            ),
            ERR_ENFORCEMENT_STATE_INVALID,
        )
        expect_error(
            world.client.file_effectiveness_report(
                report["id"], world.officer(OFFICER_1)
            ),
            ERR_REPORT_STATE_INVALID,
        )

        assert_equals(
            world.read_notice(notice["id"]), "state", "UNDER_INVESTIGATION"
        )
        assert_equals(world.read_dispute(dispute["id"]), "state", "FILED")
        unchanged_action = world.read_enforcement_action(action["id"])
        assert_equals(unchanged_action, "status", "PROPOSED")
        assert_cents(unchanged_action, "total_forfeiture_cents", 2000000)
        unchanged_report = expect_ok(
            world.client.get_effectiveness_report(report["id"], world.regulator)
        )
        assert_equals(unchanged_report, "state", "GENERATED")
        assert_null(unchanged_report, "signed_off_at")

        refreshed = world.read_provider(provider["id"])
        assert_provider_counters(
            refreshed, outstanding_forfeiture_cents=2000000, open_notice_count=1
        )


class TestDisputeUniquenessGuard:
    """The uniqueness guard is scoped to the live dispute states."""

    def test_the_event_can_be_disputed_again_once_the_first_is_withdrawn(self, world):
        """A second live filing conflicts; the same filing succeeds after a withdrawal.

        PRD: "A block may carry only one live dispute: if the event already has a dispute in `FILED`, `UNDER_REVIEW`, `UPHELD` or `REVERSED`, the filing is refused with `ERR_DUPLICATE_DISPUTE` (409). A `WITHDRAWN` dispute is the exception — it leaves the event free to be disputed again."

        Design: Corner/errors/second_dispute_on_one_event_is_rejected_until_the_first_is_withdrawn
        """
        world.set_clock("2026-08-18T00:00:00Z")
        provider = world.register_provider()
        customer = world.verified_enabled_customer(provider["id"])
        event = world.block_calls(
            provider["id"],
            customer["id"],
            analyst_id=FRAUD_1,
            calling_number=NUMBER_1,
            analytics_score=0.7,
            reason="ANALYTICS_SCORE",
        )
        first = world.file_dispute(
            event["id"], customer["id"], claim_note="First claim of legitimacy"
        )

        expect_error(
            world.client.create_blocking_dispute(
                blocking_dispute_payload(
                    event["id"], claim_note="Second claim while the first is live"
                ),
                world.caller(customer["id"]),
            ),
            ERR_DUPLICATE_DISPUTE,
        )
        expect_list_total(
            world.client.list_blocking_disputes(
                world.regulator, blocking_event_id=event["id"]
            ),
            1,
        )

        withdrawn = expect_ok(
            world.client.withdraw_blocking_dispute(
                first["id"], world.caller(customer["id"])
            )
        )
        refiled = expect_created(
            world.client.create_blocking_dispute(
                blocking_dispute_payload(
                    event["id"],
                    claim_note="Refiled after withdrawing the first claim",
                ),
                world.caller(customer["id"]),
            )
        )

        assert_equals(withdrawn, "state", "WITHDRAWN")
        assert_fields(refiled, state="FILED", customer_id=customer["id"])
        assert_instant(
            refiled, "resolution_deadline_at", "2026-08-19T00:00:00Z"
        )
        assert_equals(world.read_blocking_event(event["id"]), "status", "BLOCKED")
        expect_list_total(
            world.client.list_blocking_disputes(
                world.regulator, blocking_event_id=event["id"]
            ),
            2,
        )
        assert_decimal_4(
            world.read_provider(provider["id"]), "blocking_false_positive_rate", 0.0
        )
