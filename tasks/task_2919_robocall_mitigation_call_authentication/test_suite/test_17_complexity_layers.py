"""Version guards, multi-hop cascades and threshold-driven suspensions."""

from test_helpers import (
    CO_1,
    CO_2,
    FRAUD_1,
    KYC_1,
    KYC_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_null,
    assert_provider_counters,
    assert_version_advanced,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import (
    ERR_REPORT_STATE_INVALID,
    ERR_STALE_PROVIDER_VERSION,
)
from test_helpers.constants import CLOCK_DEFAULT, NUMBER_1, NUMBER_2
from test_helpers.factories import (
    blocking_event_payload,
    effectiveness_report_payload,
    mitigation_plan_payload,
    notice_mitigation_payload,
)


class TestPlanFilingVersionGuard:
    """The plan filing is guarded on the provider row it supersedes against."""

    def test_the_swept_provider_invalidates_a_filing_built_on_its_old_view(self, world):
        """The stale filing is a 412 and the identical body with a fresh version files.

        PRD: "If the value does not equal the target provider's current `version`, the request is rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/plan_filing_on_a_stale_provider_version_is_rejected_then_accepted
        """
        world.set_clock("2026-08-23T00:00:00Z")
        provider = world.register_provider()
        stale_version = provider["version"]
        swept = world.run_sweep(provider["id"])
        fresh_version = swept["version"]

        expect_error(
            world.client.create_mitigation_plan(
                mitigation_plan_payload(provider["id"], stale_version),
                world.officer(CO_1),
            ),
            ERR_STALE_PROVIDER_VERSION,
        )

        assert_equals(swept, "sweep_index", 1)
        assert_version_advanced(swept, provider)
        expect_list_total(
            world.client.list_mitigation_plans(
                world.regulator, provider_id=provider["id"]
            ),
            0,
        )

        plan = expect_created(
            world.client.create_mitigation_plan(
                mitigation_plan_payload(provider["id"], fresh_version),
                world.officer(CO_1),
            )
        )

        assert_fields(
            plan, filing_state="DRAFT", revision_count=0, deficiency_count=0
        )
        assert_fields(
            world.read_provider(provider["id"]),
            rmd_filing_status="UNFILED",
            auth_posture="SIGNING_SUSPENDED",
        )


class TestReportGenerationVersionGuard:
    """The same guard on a second endpoint, ahead of the period rule."""

    def test_the_stale_version_answers_before_the_unelapsed_period(self, world):
        """One request is both stale and premature, and only the 412 is reported.

        PRD: "Generating an effectiveness report likewise requires a non-optional `expected_provider_version` in its request body, and likewise rejects a mismatch against the provider's current `version` with `ERR_STALE_PROVIDER_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/report_generation_on_a_stale_provider_version_is_rejected_then_accepted
        """
        world.set_clock("2026-08-23T00:00:00Z")
        provider = world.register_provider()
        stale_version = provider["version"]
        swept = world.run_sweep(provider["id"])
        fresh_version = swept["version"]

        expect_error(
            world.client.create_effectiveness_report(
                effectiveness_report_payload(
                    provider["id"],
                    stale_version,
                    period_start="2026-07-01T00:00:00Z",
                    period_end="2026-12-01T00:00:00Z",
                    variant="PROVISIONAL",
                ),
                world.officer(CO_1),
            ),
            ERR_STALE_PROVIDER_VERSION,
        )
        expect_list_total(
            world.client.list_effectiveness_reports(
                world.regulator, provider_id=provider["id"]
            ),
            0,
        )

        report = expect_created(
            world.client.create_effectiveness_report(
                effectiveness_report_payload(
                    provider["id"],
                    fresh_version,
                    period_start="2026-07-01T00:00:00Z",
                    period_end="2026-08-01T00:00:00Z",
                    variant="PROVISIONAL",
                ),
                world.officer(CO_1),
            )
        )

        assert_fields(report, state="GENERATED", variant="PROVISIONAL")
        assert_null(report, "signed_off_at")
        assert_null(report, "filed_at")


class TestNoticeMitigationByTermination:
    """One mitigate call walks four hops without assessing a single point."""

    def test_terminating_the_customer_revokes_every_number_it_held(self, world):
        """The number the notice never named is revoked with the one it did.

        PRD: "With `CUSTOMER_TERMINATED`, the attributed customer's `origination_state` moves to `TERMINATED`, which revokes every one of that customer's assignments in `ACTIVE` or `SUSPENDED_BY_CUSTOMER` and then recomputes the provider's `active_assigned_number_count`."

        Design: Corner/complexity_layers/mitigation_by_termination_cascades_from_notice_to_provider_counters
        """
        world.set_clock("2026-08-24T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
        )
        world.kyc_verified(customer["id"], submitter_id=KYC_1, decider_id=KYC_2)
        world.enable_origination(customer["id"], provider["id"])
        named_number = world.assign_number(
            provider["id"],
            customer["id"],
            telephone_number=NUMBER_1,
            ownership_evidence="DIRECT_ALLOCATION",
            effective_from=CLOCK_DEFAULT,
        )
        other_number = world.assign_number(
            provider["id"],
            customer["id"],
            telephone_number=NUMBER_2,
            ownership_evidence="PORTED_IN",
            effective_from=CLOCK_DEFAULT,
        )
        notice = world.serve_notice(provider["id"], calling_number=NUMBER_1)
        world.investigate_notice(notice["id"], customer["id"], officer_id=CO_1)

        mitigated = expect_ok(
            world.client.mitigate_notice(
                notice["id"],
                notice_mitigation_payload("CUSTOMER_TERMINATED"),
                world.officer(CO_1),
            )
        )

        assert_fields(
            mitigated,
            state="MITIGATED",
            mitigation_action="CUSTOMER_TERMINATED",
            penalty_points_assessed=0,
        )
        assert_instant(mitigated, "resolved_at", "2026-08-24T00:00:00Z")

        terminated = world.read_customer(customer["id"])
        assert_fields(
            terminated, origination_state="TERMINATED", kyc_state="VERIFIED"
        )
        assert_null(terminated, "suspension_cause")

        for assignment in (named_number, other_number):
            revoked = world.read_assignment(assignment["id"])
            assert_equals(revoked, "status", "REVOKED")
            assert_instant(revoked, "revoked_at", "2026-08-24T00:00:00Z")

        refreshed = world.read_provider(provider["id"])
        assert_provider_counters(
            refreshed,
            active_assigned_number_count=0,
            open_notice_count=0,
            penalty_points=0,
        )
        assert_equals(refreshed, "auth_posture", "SIGNING_SUSPENDED")


class TestReportVariantSupersession:
    """Switching variant means a second generation, not an edit."""

    def test_the_overlapping_certified_generation_supersedes_the_provisional_row(
        self, world
    ):
        """The provisional row is superseded and can no longer be certified.

        PRD: "Generation is also a create-with-supersede operation: any report of the same provider in `state` `GENERATED` or `SIGNED_OFF` whose period overlaps the new report's period moves to `SUPERSEDED`."

        Design: Corner/complexity_layers/regenerating_the_period_as_certified_supersedes_the_provisional_report
        """
        world.set_clock("2026-08-25T00:00:00Z")
        provider = world.register_provider()
        world.accepted_plan(provider["id"], officer_id=CO_1)
        provisional = world.generate_report(
            provider["id"],
            variant="PROVISIONAL",
            officer_id=CO_1,
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        )

        certified = expect_created(
            world.client.create_effectiveness_report(
                effectiveness_report_payload(
                    provider["id"],
                    world.provider_version(provider["id"]),
                    period_start="2026-07-15T00:00:00Z",
                    period_end="2026-08-01T00:00:00Z",
                    variant="CERTIFIED",
                ),
                world.officer(CO_1),
            )
        )

        assert_fields(certified, variant="CERTIFIED", state="GENERATED")
        assert_instant(certified, "period_start", "2026-07-15T00:00:00Z")

        superseded = expect_ok(
            world.client.get_effectiveness_report(provisional["id"], world.regulator)
        )
        assert_fields(superseded, state="SUPERSEDED", variant="PROVISIONAL")

        expect_error(
            world.client.certify_effectiveness_report(
                provisional["id"], world.officer(CO_2)
            ),
            ERR_REPORT_STATE_INVALID,
        )

        for report in (superseded, certified):
            assert_equals(report, "data_sufficiency", "INSUFFICIENT")
            assert_decimal_4(report, "attestation_component", 0.0000)
            assert_null(report, "signed_off_by_user_id")

        items, _ = expect_list_total(
            world.client.list_effectiveness_reports(
                world.regulator, provider_id=provider["id"], state="GENERATED"
            ),
            1,
        )
        assert_ids_in_order(items, [certified["id"]])


class TestAnalyticsAutoSuspendBoundary:
    """The auto-suspend comparison is inclusive and sits well above the floor."""

    def test_the_block_at_exactly_the_threshold_suspends_and_names_itself(self, world):
        """0.9400 leaves origination alone; the next block at 0.9500 stops it.

        PRD: "Its `triggered_suspension` field is true exactly when the `reason` is `ANALYTICS_SCORE` **and** the `analytics_score` is 0.9500 or above, and in that case the customer travels `ENABLED → SUSPENDED` with `suspension_cause` `BLOCKING_ANALYTICS` and `suspension_source_id` set to this event's `id`, cascading to the customer's `ACTIVE` assignments and thence to the provider's `active_assigned_number_count`."

        Design: Corner/complexity_layers/analytics_score_exactly_at_the_auto_suspend_boundary_suspends_origination
        """
        world.set_clock("2026-08-26T00:00:00Z")
        provider = world.register_provider()
        customer = world.onboard_customer(
            provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
        )
        world.kyc_verified(customer["id"], submitter_id=KYC_1, decider_id=KYC_2)
        world.enable_origination(customer["id"], provider["id"])
        assignment = world.assign_number(
            provider["id"],
            customer["id"],
            telephone_number=NUMBER_1,
            ownership_evidence="DIRECT_ALLOCATION",
            effective_from=CLOCK_DEFAULT,
        )

        below = expect_created(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    customer["id"],
                    calling_number=NUMBER_1,
                    analytics_score=0.94,
                    reason="ANALYTICS_SCORE",
                ),
                world.fraud(FRAUD_1),
            )
        )

        assert_fields(below, status="BLOCKED", triggered_suspension=False)
        assert_decimal_4(below, "analytics_score", 0.9400)
        still_enabled = world.read_customer(customer["id"])
        assert_equals(still_enabled, "origination_state", "ENABLED")
        assert_null(still_enabled, "suspension_cause")

        at_threshold = expect_created(
            world.client.create_blocking_event(
                blocking_event_payload(
                    provider["id"],
                    customer["id"],
                    calling_number=NUMBER_1,
                    analytics_score=0.95,
                    reason="ANALYTICS_SCORE",
                ),
                world.fraud(FRAUD_1),
            )
        )

        assert_fields(at_threshold, status="BLOCKED", triggered_suspension=True)
        assert_decimal_4(at_threshold, "analytics_score", 0.9500)

        suspended = world.read_customer(customer["id"])
        assert_fields(
            suspended,
            origination_state="SUSPENDED",
            suspension_cause="BLOCKING_ANALYTICS",
            suspension_source_id=at_threshold["id"],
            kyc_state="VERIFIED",
        )
        assert_decimal_4(suspended, "traffic_risk_index", 0.0000)

        cascaded = world.read_assignment(assignment["id"])
        assert_equals(cascaded, "status", "SUSPENDED_BY_CUSTOMER")
        assert_null(cascaded, "revoked_at")

        refreshed = world.read_provider(provider["id"])
        assert_provider_counters(refreshed, active_assigned_number_count=0)
        assert_decimal_4(refreshed, "blocking_false_positive_rate", 0.0000)
