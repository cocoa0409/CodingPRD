"""Propagation chains in which each hop is caused by the hop before it."""

from test_helpers import (
    ComplianceWorld,
    FRAUD_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_not_null,
    assert_null,
    assert_provider_counters,
    build_provider_with_customer,
    build_signing_ready_provider,
    expect_ok,
)
from test_helpers.constants import NUMBER_1, NUMBER_2, NUMBER_CALLED
from test_helpers.factories import dispute_resolution_payload


def _build_unmitigated_notice(world: ComplianceWorld):
    """A provider holding two numbers, one notice under investigation and one
    traceback, all left to run past their deadlines."""
    setup = build_signing_ready_provider(world)
    second = world.assign_number(
        setup.provider_id,
        setup.customer_id,
        NUMBER_2,
        ownership_evidence="PORTED_IN",
    )
    assert_provider_counters(
        world.read_provider(setup.provider_id),
        active_assigned_number_count=2,
        auth_posture="FULL_ATTESTATION",
    )

    world.set_clock("2026-08-10T00:00:00Z")
    notice = world.serve_notice(setup.provider_id, calling_number=NUMBER_1)
    world.investigate_notice(notice["id"], setup.customer_id)
    traceback = world.open_traceback(
        setup.provider_id,
        calling_number=NUMBER_1,
        called_number=NUMBER_CALLED,
        origination_time="2026-08-05T00:00:00Z",
    )
    return setup, second, notice, traceback


class TestNoticeExpiryCascade:
    """The deadline sweep, and the four hops it sets off."""

    def test_expiry_suspends_the_customer_and_empties_its_number_inventory(
        self, world
    ):
        """Hops one to three: notice, customer, assignments, and the recomputed count.

        PRD: "If the notice had already been attributed to a customer and that customer's `origination_state` is `ENABLED`, expiry additionally drives that customer `ENABLED → SUSPENDED` with `suspension_cause` `NOTICE_EXPIRY` and `suspension_source_id` set to this notice's `id`; because the customer was suspended, every one of its `ACTIVE` assignments moves to `SUSPENDED_BY_CUSTOMER`; and because those assignments left the active set, the provider's `active_assigned_number_count` is recomputed alongside the posture recomputed from the new `penalty_points`."

        Design: Difficulty/transitive_cascade/notice_expiry_cascades_four_hops_to_provider_posture
        """
        setup, second, notice, _traceback = _build_unmitigated_notice(world)

        world.set_clock("2026-08-12T00:00:01Z")
        world.run_sweep(setup.provider_id)

        expired = world.read_notice(notice["id"])
        assert_fields(expired, state="EXPIRED_UNMITIGATED", penalty_points_assessed=5)

        customer = world.read_customer(setup.customer_id)
        assert_fields(
            customer,
            origination_state="SUSPENDED",
            suspension_cause="NOTICE_EXPIRY",
            suspension_source_id=notice["id"],
        )

        assert_equals(
            world.read_assignment(setup.assignment_id),
            "status",
            "SUSPENDED_BY_CUSTOMER",
        )
        assert_equals(
            world.read_assignment(second["id"]), "status", "SUSPENDED_BY_CUSTOMER"
        )
        assert_provider_counters(
            world.read_provider(setup.provider_id), active_assigned_number_count=0
        )

    def test_expiry_and_overdue_traceback_together_drive_the_posture(self, world):
        """Hop four: eight penalty points move the posture to GATEWAY_LIMITED.

        PRD: "The canonical chain is four hops deep: an illegal-traffic notice expires unmitigated, which suspends the attributed customer's origination, which suspends that customer's active number assignments, which forces a recompute of the provider's `active_assigned_number_count` and — through the new `penalty_points` — of its `auth_posture`."

        Design: Difficulty/transitive_cascade/notice_expiry_cascades_four_hops_to_provider_posture
        """
        setup, _second, _notice, traceback = _build_unmitigated_notice(world)

        world.set_clock("2026-08-12T00:00:01Z")
        sweep = world.run_sweep(setup.provider_id)

        assert_equals(sweep, "id", setup.provider_id)
        assert_equals(world.read_traceback(traceback["id"]), "state", "OVERDUE")

        provider = world.read_provider(setup.provider_id)
        assert_provider_counters(
            provider,
            overdue_traceback_count=1,
            penalty_points=8,
            open_notice_count=0,
            rmd_filing_status="COMPLETE",
            auth_posture="GATEWAY_LIMITED",
            sweep_index=1,
        )
        assert_equals(world.read_certificate(setup.certificate_id), "status", "ACTIVE")


def _build_disputed_block(world: ComplianceWorld):
    """A customer auto-suspended by an analytics block whose dispute is under
    review by an analyst other than the one who blocked."""
    setup = build_provider_with_customer(
        world, kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    first = world.assign_number(setup.provider_id, setup.customer_id, NUMBER_1)
    second = world.assign_number(
        setup.provider_id,
        setup.customer_id,
        NUMBER_2,
        ownership_evidence="PORTED_IN",
    )
    event = world.block_calls(
        setup.provider_id,
        setup.customer_id,
        calling_number=NUMBER_1,
        analytics_score=0.96,
        reason="ANALYTICS_SCORE",
    )
    dispute = world.file_dispute(event["id"], setup.customer_id)
    world.review_dispute(dispute["id"], FRAUD_2)
    return setup, first, second, event, dispute


def _reverse(world: ComplianceWorld, dispute_id: str):
    return expect_ok(
        world.client.resolve_blocking_dispute(
            dispute_id,
            dispute_resolution_payload(
                "REVERSE", resolution_note="Consent records verified; block was erroneous"
            ),
            world.fraud(FRAUD_2),
        )
    )


class TestDisputeReversalCascade:
    """A reversal running the block's chain backwards."""

    def test_reversal_moves_the_event_and_lifts_the_false_positive_rate(self, world):
        """The dispute, the event and both false-positive figures all move together.

        PRD: "A `REVERSE` advances the dispute `UNDER_REVIEW → REVERSED` and the disputed event `BLOCKED → REVERSED`, stamping the event's `reversed_at` at the current logical clock, and then unwinds the whole chain the block set in motion."

        Design: Difficulty/transitive_cascade/dispute_reversal_cascades_back_to_number_inventory
        """
        setup, _first, _second, event, dispute = _build_disputed_block(world)

        resolved = _reverse(world, dispute["id"])

        assert_fields(resolved, state="REVERSED", resolved_by_user_id=FRAUD_2)
        assert_equals(resolved, "resolved_late", False)

        reversed_event = world.read_blocking_event(event["id"])
        assert_equals(reversed_event, "status", "REVERSED")
        assert_not_null(reversed_event, "reversed_at")

        assert_equals(
            world.read_customer(setup.customer_id), "false_positive_count", 1
        )
        assert_decimal_4(
            world.read_provider(setup.provider_id),
            "blocking_false_positive_rate",
            1.0000,
        )

    def test_reversal_re_enables_the_customer_and_restores_its_assignments(self, world):
        """The suspended customer and both of its numbers return to the active set.

        PRD: "If — and only if — that customer's `suspension_cause` is `BLOCKING_ANALYTICS` and its `suspension_source_id` names this very event, the customer travels `SUSPENDED → ENABLED` with both `suspension_cause` and `suspension_source_id` cleared to null; because the customer was re-enabled, every assignment of that customer whose `status` is `SUSPENDED_BY_CUSTOMER` returns to `ACTIVE`; and because those assignments re-entered the active set, the provider's `active_assigned_number_count` and `blocking_false_positive_rate` are both recomputed."

        Design: Difficulty/transitive_cascade/dispute_reversal_cascades_back_to_number_inventory
        """
        setup, first, second, event, dispute = _build_disputed_block(world)
        blocked = world.read_customer(setup.customer_id)
        assert_fields(
            blocked,
            origination_state="SUSPENDED",
            suspension_cause="BLOCKING_ANALYTICS",
            suspension_source_id=event["id"],
        )
        assert_provider_counters(
            world.read_provider(setup.provider_id), active_assigned_number_count=0
        )

        _reverse(world, dispute["id"])

        restored = world.read_customer(setup.customer_id)
        assert_equals(restored, "origination_state", "ENABLED")
        assert_null(restored, "suspension_cause")
        assert_null(restored, "suspension_source_id")

        assert_equals(world.read_assignment(first["id"]), "status", "ACTIVE")
        assert_equals(world.read_assignment(second["id"]), "status", "ACTIVE")
        assert_provider_counters(
            world.read_provider(setup.provider_id), active_assigned_number_count=2
        )
