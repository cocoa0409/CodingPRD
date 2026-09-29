"""Endpoint behaviour: action verbs, computed reads, bulk sweeps and round trips."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    FRAUD_1,
    OFFICER_1,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_null,
    assert_provider_counters,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import (
    ERR_BLOCKING_EVENT_NOT_FOUND,
    ERR_SCORE_BELOW_BLOCKING_THRESHOLD,
)
from test_helpers.constants import CLOCK_DEFAULT, NUMBER_1, NUMBER_2, NUMBER_CALLED
from test_helpers.factories import (
    blocking_dispute_payload,
    blocking_event_payload,
    certificate_renewal_payload,
    notice_mitigation_payload,
    number_assignment_payload,
)


class TestCertificateRenewalEndpoint:
    """Renewal returns a different row than the one addressed."""

    def test_renewal_opens_a_signing_gap_until_the_successor_is_activated(self, world):
        """The successor arrives ISSUED at generation 2 and the pointer goes null.

        PRD: "Critically, the provider's `active_certificate_id` is set to null in the same operation, because the successor has not been activated yet — so the posture ladder stops at its first step and the provider reads `SIGNING_SUSPENDED` for the whole gap between renewal and activation, while `rmd_filing_status` keeps whatever the operative plan dictates."

        Design: Corner/endpoints/certificate_renewal_supersedes_and_opens_a_signing_gap
        """
        world.set_clock("2026-08-10T00:00:00Z")
        provider = world.register_provider()
        world.accepted_plan(provider["id"], officer_id=OFFICER_1)
        predecessor = world.request_certificate(
            provider["id"],
            not_before="2026-08-01T00:00:00Z",
            not_after="2027-08-01T00:00:00Z",
        )
        world.issue_certificate(predecessor["id"])
        world.activate_certificate(predecessor["id"], provider["id"])

        successor = expect_created(
            world.client.renew_certificate(
                predecessor["id"],
                certificate_renewal_payload(
                    not_before="2026-08-10T00:00:00Z",
                    not_after="2027-08-10T00:00:00Z",
                ),
                world.policy_admin,
            )
        )

        assert_fields(
            successor,
            status="ISSUED",
            renewal_generation=2,
            predecessor_certificate_id=predecessor["id"],
        )
        assert_instant(successor, "issued_at", "2026-08-10T00:00:00Z")
        assert_equals(world.read_certificate(predecessor["id"]), "status", "SUPERSEDED")

        in_the_gap = world.read_provider(provider["id"])
        assert_null(in_the_gap, "active_certificate_id")
        assert_fields(
            in_the_gap,
            auth_posture="SIGNING_SUSPENDED",
            rmd_filing_status="COMPLETE",
        )

        world.activate_certificate(successor["id"], provider["id"])
        after_activation = world.read_provider(provider["id"])
        assert_fields(
            after_activation,
            active_certificate_id=successor["id"],
            auth_posture="FULL_ATTESTATION",
        )
        items, _ = expect_list_total(
            world.client.list_certificates(
                world.policy_admin, predecessor_certificate_id=predecessor["id"]
            ),
            1,
        )
        assert_ids_in_order(items, [successor["id"]])


class TestProviderComputedRead:
    """The provider read recomputes its derived counters rather than storing them."""

    def test_the_open_notice_count_follows_the_notice_states(self, world):
        """An investigated notice is still open; only mitigation closes it.

        PRD: "`open_notice_count` is the count of the provider's illegal-traffic notices whose `state` is `NOTIFIED` or `UNDER_INVESTIGATION`."

        Design: Corner/endpoints/provider_read_returns_recomputed_open_notice_count
        """
        world.set_clock("2026-08-10T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="CONTRACT_ONLY"
        )
        untouched = world.serve_notice(provider["id"], calling_number=NUMBER_1)
        investigated = world.serve_notice(provider["id"], calling_number=NUMBER_2)
        world.investigate_notice(investigated["id"], customer["id"])

        while_both_open = expect_ok(
            world.client.get_provider(provider["id"], world.regulator)
        )

        assert_provider_counters(
            while_both_open,
            open_notice_count=2,
            penalty_points=0,
            overdue_traceback_count=0,
            sweep_index=0,
        )
        assert_decimal_4(while_both_open, "blocking_false_positive_rate", 0.0)

        mitigated = expect_ok(
            world.client.mitigate_notice(
                investigated["id"],
                notice_mitigation_payload("NUMBERS_REVOKED"),
                world.officer(OFFICER_1),
            )
        )

        assert_equals(mitigated, "state", "MITIGATED")
        assert_instant(mitigated, "resolved_at", "2026-08-10T00:00:00Z")
        after = world.read_provider(provider["id"])
        assert_provider_counters(after, open_notice_count=1, penalty_points=0)

        still_open = world.read_notice(untouched["id"])
        assert_equals(still_open, "state", "NOTIFIED")
        assert_instant(
            still_open, "mitigation_deadline_at", "2026-08-12T00:00:00Z"
        )


class TestComplianceSweepEndpoint:
    """One call, three entity families, and only the lapsed rows move."""

    def test_the_sweep_skips_the_rows_still_inside_their_window(self, world):
        """The stale certificate, traceback and notice transition; their siblings do not.

        PRD: "It performs, for that one provider, every deadline-driven transition described above: certificates whose `not_after` has passed are expired, traceback requests past their response deadline are marked overdue, notices past their mitigation deadline are expired, and every downstream cascade those transitions cause is applied."

        Design: Corner/endpoints/compliance_sweep_expires_only_the_rows_whose_deadline_has_passed
        """
        provider = world.register_provider()
        world.accepted_plan(provider["id"], officer_id=OFFICER_1)
        live = world.request_certificate(
            provider["id"],
            not_before="2026-08-01T00:00:00Z",
            not_after="2027-08-01T00:00:00Z",
        )
        world.issue_certificate(live["id"])
        world.activate_certificate(live["id"], provider["id"])
        stale = world.request_certificate(
            provider["id"],
            not_before="2026-07-01T00:00:00Z",
            not_after="2026-08-05T00:00:00Z",
        )
        world.issue_certificate(stale["id"])
        stale_traceback = world.open_traceback(
            provider["id"],
            calling_number=NUMBER_1,
            called_number=NUMBER_CALLED,
            origination_time="2026-07-31T12:00:00Z",
        )
        stale_notice = world.serve_notice(provider["id"], calling_number=NUMBER_1)
        world.set_clock("2026-08-06T00:00:00Z")
        fresh_traceback = world.open_traceback(
            provider["id"],
            calling_number=NUMBER_2,
            called_number=NUMBER_CALLED,
            origination_time="2026-08-05T12:00:00Z",
        )
        fresh_notice = world.serve_notice(provider["id"], calling_number=NUMBER_2)

        swept = expect_ok(world.client.run_sweep(provider["id"], world.regulator))

        assert_equals(swept, "sweep_index", 1)
        assert_equals(world.read_certificate(stale["id"]), "status", "EXPIRED")
        assert_equals(world.read_certificate(live["id"]), "status", "ACTIVE")
        assert_equals(swept, "active_certificate_id", live["id"])
        assert_equals(world.read_traceback(stale_traceback["id"]), "state", "OVERDUE")
        assert_equals(world.read_traceback(fresh_traceback["id"]), "state", "RECEIVED")

        expired_notice = world.read_notice(stale_notice["id"])
        assert_fields(
            expired_notice,
            state="EXPIRED_UNMITIGATED",
            penalty_points_assessed=5,
        )
        untouched_notice = world.read_notice(fresh_notice["id"])
        assert_fields(
            untouched_notice, state="NOTIFIED", penalty_points_assessed=0
        )

        assert_provider_counters(
            swept,
            penalty_points=8,
            overdue_traceback_count=1,
            open_notice_count=1,
            active_assigned_number_count=0,
        )
        assert_fields(
            swept, auth_posture="GATEWAY_LIMITED", rmd_filing_status="COMPLETE"
        )


class TestBlockingDisputeEndpoint:
    """The dispute joins a body reference to an identity-derived one."""

    def test_the_dispute_takes_its_customer_from_the_calling_identity(self, world):
        """An unknown event is a 404; the accepted filing stores the caller's own id.

        PRD: "Only a `Caller` may do so, supplying the `blocking_event_id` of the block it contests and a `claim_note` stating why its traffic is legitimate; the dispute's `customer_id` is taken from the caller's own `X-User-ID` rather than from the body."

        Design: Corner/endpoints/dispute_links_the_calling_customer_to_the_blocked_event
        """
        world.set_clock("2026-08-12T00:00:00Z")
        provider = world.register_provider()
        customer = world.verified_enabled_customer(provider["id"])
        world.assign_number(
            provider["id"],
            customer["id"],
            telephone_number=NUMBER_1,
            ownership_evidence="DIRECT_ALLOCATION",
            effective_from=CLOCK_DEFAULT,
        )
        event = world.block_calls(
            provider["id"],
            customer["id"],
            calling_number=NUMBER_1,
            analytics_score=0.71,
            reason="ANALYTICS_SCORE",
        )

        expect_error(
            world.client.create_blocking_dispute(
                blocking_dispute_payload(
                    NON_EXISTENT_UUID,
                    claim_note="Dispute against an event that was never recorded",
                ),
                world.caller(customer["id"]),
            ),
            ERR_BLOCKING_EVENT_NOT_FOUND,
        )

        dispute = expect_created(
            world.client.create_blocking_dispute(
                blocking_dispute_payload(
                    event["id"],
                    claim_note="Outbound appointment reminders placed with consent",
                ),
                world.caller(customer["id"]),
            )
        )

        assert_fields(
            dispute,
            blocking_event_id=event["id"],
            customer_id=customer["id"],
            state="FILED",
            resolved_late=False,
        )
        assert_instant(dispute, "filed_at", "2026-08-12T00:00:00Z")
        assert_instant(
            dispute, "resolution_deadline_at", "2026-08-13T00:00:00Z"
        )
        for field in ("resolved_at", "resolved_by_user_id", "resolution_note"):
            assert_null(dispute, field)

        refreshed_event = world.read_blocking_event(event["id"])
        assert_fields(refreshed_event, status="BLOCKED", triggered_suspension=False)
        assert_equals(
            world.read_customer(customer["id"]), "origination_state", "ENABLED"
        )
        refreshed_provider = world.read_provider(provider["id"])
        assert_decimal_4(refreshed_provider, "blocking_false_positive_rate", 0.0)
        assert_provider_counters(refreshed_provider, active_assigned_number_count=1)
        items, _ = expect_list_total(
            world.client.list_blocking_disputes(
                world.regulator, blocking_event_id=event["id"]
            ),
            1,
        )
        assert_ids_in_order(items, [dispute["id"]])


class TestBlockingEventEndpoint:
    """The analytics floor is conditional on the reason it is recorded under."""

    def test_the_score_floor_binds_only_the_analytics_reason(self, world):
        """0.5000 is refused under ANALYTICS_SCORE, accepted under NOTICE_MANDATE.

        PRD: "When the `reason` is `ANALYTICS_SCORE` the score must be at least 0.6500, and a lower score is refused with `ERR_SCORE_BELOW_BLOCKING_THRESHOLD` (422); the threshold does not apply to the other two reasons, which are mandated rather than scored."

        Design: Corner/endpoints/blocking_threshold_applies_only_to_the_analytics_reason
        """
        world.set_clock("2026-08-13T00:00:00Z")
        provider = world.register_provider()
        customer = world.verified_enabled_customer(provider["id"])

        expect_error(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    customer["id"],
                    calling_number=NUMBER_1,
                    analytics_score=0.5,
                    reason="ANALYTICS_SCORE",
                ),
                world.fraud(FRAUD_1),
            ),
            ERR_SCORE_BELOW_BLOCKING_THRESHOLD,
        )

        mandated = expect_created(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    customer["id"],
                    calling_number=NUMBER_1,
                    analytics_score=0.5,
                    reason="NOTICE_MANDATE",
                ),
                world.fraud(FRAUD_1),
            )
        )
        at_the_floor = expect_created(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    customer["id"],
                    calling_number=NUMBER_1,
                    analytics_score=0.65,
                    reason="ANALYTICS_SCORE",
                ),
                world.fraud(FRAUD_1),
            )
        )

        assert_fields(
            mandated,
            status="BLOCKED",
            reason="NOTICE_MANDATE",
            triggered_suspension=False,
        )
        assert_decimal_4(mandated, "analytics_score", 0.5000)
        assert_fields(at_the_floor, status="BLOCKED", triggered_suspension=False)
        assert_decimal_4(at_the_floor, "analytics_score", 0.6500)
        for event in (mandated, at_the_floor):
            assert_instant(event, "blocked_at", "2026-08-13T00:00:00Z")
            assert_equals(event, "blocked_by_user_id", FRAUD_1)

        expect_list_total(
            world.client.list_blocking_events(
                world.regulator, customer_id=customer["id"]
            ),
            2,
        )
        assert_equals(
            world.read_customer(customer["id"]), "origination_state", "ENABLED"
        )
        assert_decimal_4(
            world.read_provider(provider["id"]), "blocking_false_positive_rate", 0.0
        )


class TestNumberAssignmentRoundTrip:
    """Create, read, list and revoke — the assignment has no update verb."""

    def test_the_assignment_leaves_the_active_filter_when_it_is_revoked(self, world):
        """The row round-trips by id, by filter, and out of the active inventory.

        PRD: "An assignment can be revoked by a `ProviderAdmin` from either `ACTIVE` or `SUSPENDED_BY_CUSTOMER`, which stamps `revoked_at` at the current logical clock, moves `status` to `REVOKED`, and recomputes the provider's `active_assigned_number_count` — the compensating half of the number-inventory invariant."

        Design: Corner/endpoints/number_assignment_create_read_list_and_revoke_round_trip
        """
        world.set_clock("2026-08-14T00:00:00Z")
        provider = world.register_provider()
        customer = world.verified_enabled_customer(provider["id"])

        created = expect_created(
            world.client.create_number_assignment(
                number_assignment_payload(
                    provider["id"],
                    customer["id"],
                    telephone_number=NUMBER_1,
                    ownership_evidence="PORTED_IN",
                    effective_from=CLOCK_DEFAULT,
                    effective_to="2026-09-01T00:00:00Z",
                ),
                world.provider_admin(provider["id"]),
            )
        )

        assert_fields(created, status="ACTIVE", ownership_evidence="PORTED_IN")
        assert_instant(created, "effective_to", "2026-09-01T00:00:00Z")
        assert_null(created, "revoked_at")

        fetched = expect_ok(
            world.client.get_number_assignment(
                created["id"], world.provider_admin(provider["id"])
            )
        )
        assert_fields(
            fetched,
            id=created["id"],
            status="ACTIVE",
            ownership_evidence="PORTED_IN",
            telephone_number=NUMBER_1,
        )

        active_page, _ = expect_list_total(
            world.client.list_number_assignments(
                world.provider_admin(provider["id"]),
                provider_id=provider["id"],
                status="ACTIVE",
            ),
            1,
        )
        assert_ids_in_order(active_page, [created["id"]])
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=1
        )

        revoked = expect_ok(
            world.client.revoke_number_assignment(
                created["id"], world.provider_admin(provider["id"])
            )
        )

        assert_equals(revoked, "status", "REVOKED")
        assert_instant(revoked, "revoked_at", "2026-08-14T00:00:00Z")
        expect_list_total(
            world.client.list_number_assignments(
                world.provider_admin(provider["id"]),
                provider_id=provider["id"],
                status="ACTIVE",
            ),
            0,
        )
        expect_list_total(
            world.client.list_number_assignments(
                world.provider_admin(provider["id"]),
                provider_id=provider["id"],
                status="REVOKED",
            ),
            1,
        )
        assert_provider_counters(
            world.read_provider(provider["id"]), active_assigned_number_count=0
        )
        assert_equals(
            world.read_customer(customer["id"]), "origination_state", "ENABLED"
        )
