"""Quantities that must balance across every exit path."""

from test_helpers import (
    ComplianceWorld,
    assert_cents,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_null,
    assert_provider_counters,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import (
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_SUSPENSION_CAUSE_NOT_SELF_CLEARABLE,
)
from test_helpers.constants import NUMBER_1, NUMBER_2, NUMBER_3
from test_helpers.factories import (
    enforcement_action_payload,
    origination_action_payload,
    payment_payload,
    traffic_observation_payload,
)


def _build_two_forfeitures(world: ComplianceWorld):
    """A gateway provider owing 2,500,000 cents across two proposed actions."""
    provider = world.register_provider(provider_type="GATEWAY")
    daily = expect_created(
        world.client.create_enforcement_action(
            enforcement_action_payload(
                provider["id"],
                basis="LATE_TRACEBACK",
                violation_count=1,
                violation_days=6,
                assessment_basis="CONTINUING_DAILY",
            ),
            world.regulator,
        )
    )
    per_violation = expect_created(
        world.client.create_enforcement_action(
            enforcement_action_payload(
                provider["id"],
                basis="FALSE_ATTESTATION",
                violation_count=1,
                violation_days=6,
                assessment_basis="PER_VIOLATION",
            ),
            world.regulator,
        )
    )
    assert_cents(daily, "total_forfeiture_cents", 1500000)
    assert_equals(daily, "assessment_tier", "TIER_1")
    assert_cents(per_violation, "total_forfeiture_cents", 1000000)
    assert_provider_counters(
        world.read_provider(provider["id"]), outstanding_forfeiture_cents=2500000
    )
    return provider["id"], daily, per_violation


class TestOutstandingForfeitureConservation:
    """Money leaves the outstanding set by dismissal or by payment, never twice."""

    def test_dismissal_removes_its_own_amount_and_rewrites_no_assessment(self, world):
        """Contesting holds 2,500,000; the dismissal leaves exactly 1,500,000 owed.

        PRD: "A `DISMISS` advances `CONTESTED → DISMISSED` and recomputes `outstanding_forfeiture_cents`, which restores the exact pre-assessment total — the compensating half of the monetary invariant of §2.10."

        Design: Difficulty/compensating_invariant/outstanding_forfeiture_conserved_across_dismissal_and_payment
        """
        provider_id, daily, per_violation = _build_two_forfeitures(world)

        world.contest_forfeiture(per_violation["id"])
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=2500000
        )

        dismissed = world.adjudicate_forfeiture(per_violation["id"], "DISMISS")

        assert_equals(dismissed, "status", "DISMISSED")
        assert_cents(dismissed, "total_forfeiture_cents", 1000000)
        assert_cents(
            world.read_enforcement_action(daily["id"]), "total_forfeiture_cents", 1500000
        )
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=1500000
        )

    def test_a_rejected_payment_moves_nothing_and_the_exact_one_clears_the_balance(
        self, world
    ):
        """1,000,000 tendered against 1,500,000 is refused; the exact figure pays it.

        PRD: "Neither a partial payment nor an overpayment is accepted, and a mismatch is refused with `ERR_PAYMENT_AMOUNT_MISMATCH` (422), a code raised by payment alone."

        Design: Difficulty/compensating_invariant/outstanding_forfeiture_conserved_across_dismissal_and_payment
        """
        provider_id, daily, per_violation = _build_two_forfeitures(world)
        world.contest_forfeiture(per_violation["id"])
        world.adjudicate_forfeiture(per_violation["id"], "DISMISS")

        expect_error(
            world.client.pay_enforcement_action(
                daily["id"],
                payment_payload(1000000),
                world.provider_admin(provider_id),
            ),
            ERR_PAYMENT_AMOUNT_MISMATCH,
        )
        assert_equals(
            world.read_enforcement_action(daily["id"]), "status", "PROPOSED"
        )
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=1500000
        )

        paid = expect_ok(
            world.client.pay_enforcement_action(
                daily["id"],
                payment_payload(1500000),
                world.provider_admin(provider_id),
            )
        )

        assert_equals(paid, "status", "PAID")
        assert_cents(paid, "paid_amount_cents", 1500000)
        assert_cents(paid, "total_forfeiture_cents", 1500000)
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=0
        )

        rows, _meta = expect_list_total(
            world.client.list_enforcement_actions(
                world.regulator, provider_id=provider_id
            ),
            2,
        )
        assert sum(row["total_forfeiture_cents"] for row in rows) == 2500000, (
            "the assessed amounts must survive both exits unchanged"
        )


def _build_risk_suspended_inventory(world: ComplianceWorld):
    """Three numbers on one customer, all suspended by a risk breach, one of
    them then revoked out of the suspended partition."""
    provider = world.register_provider()
    customer = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    first = world.assign_number(provider["id"], customer["id"], NUMBER_1)
    second = world.assign_number(
        provider["id"], customer["id"], NUMBER_2, ownership_evidence="PORTED_IN"
    )
    third = world.assign_number(
        provider["id"],
        customer["id"],
        NUMBER_3,
        ownership_evidence="LEASED_FROM_CARRIER",
    )
    assert_provider_counters(
        world.read_provider(provider["id"]), active_assigned_number_count=3
    )

    observation = expect_created(
        world.client.create_traffic_observation(
            traffic_observation_payload(
                provider["id"],
                customer["id"],
                total_call_count=100,
                short_duration_call_count=100,
                unanswered_call_count=100,
                complaint_count=1,
            ),
            world.provider_admin(provider["id"]),
        )
    )
    assert_decimal_4(observation, "resulting_risk_index", 0.9000)
    assert_equals(observation, "triggered_suspension", True)
    assert_provider_counters(
        world.read_provider(provider["id"]), active_assigned_number_count=0
    )

    world.revoke_assignment(third["id"], provider["id"])
    return provider["id"], customer["id"], first, second, third


class TestActiveNumberInventoryConservation:
    """Every assignment stays in exactly one partition across the whole episode."""

    def test_the_provider_cannot_clear_a_risk_suspension_it_did_not_cause(self, world):
        """The self-restore is refused 403 and the active count does not budge.

        PRD: "A `ProviderAdmin` may only clear a suspension whose `suspension_cause` is `PROVIDER_REQUEST`; suspensions caused by `NOTICE_EXPIRY`, `BLOCKING_ANALYTICS`, `TRAFFIC_RISK_THRESHOLD` or `REGULATOR_ORDER` are clearable only by a `Regulator`, who may clear any cause."

        Design: Difficulty/compensating_invariant/active_number_inventory_conserved_across_risk_suspension_and_restore
        """
        provider_id, customer_id, _first, _second, _third = (
            _build_risk_suspended_inventory(world)
        )

        expect_error(
            world.client.origination_action(
                customer_id,
                origination_action_payload("RESTORE"),
                world.provider_admin(provider_id),
            ),
            ERR_SUSPENSION_CAUSE_NOT_SELF_CLEARABLE,
        )

        assert_fields(
            world.read_customer(customer_id),
            origination_state="SUSPENDED",
            suspension_cause="TRAFFIC_RISK_THRESHOLD",
        )
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=0
        )

    def test_a_regulator_restore_returns_only_the_still_suspended_numbers(self, world):
        """Two numbers come back, the revoked one does not, and the count reads 2.

        PRD: "A successful restore nulls `suspension_cause` and `suspension_source_id`, moves every assignment of that customer whose `status` is `SUSPENDED_BY_CUSTOMER` back to `ACTIVE`, and recomputes the provider's `active_assigned_number_count` — which, because the counter is a full recompute over the active set, returns to exactly the value it held before the suspension."

        Design: Difficulty/compensating_invariant/active_number_inventory_conserved_across_risk_suspension_and_restore
        """
        provider_id, customer_id, first, second, third = (
            _build_risk_suspended_inventory(world)
        )
        expect_error(
            world.client.origination_action(
                customer_id,
                origination_action_payload("RESTORE"),
                world.provider_admin(provider_id),
            ),
            ERR_SUSPENSION_CAUSE_NOT_SELF_CLEARABLE,
        )

        restored = expect_ok(
            world.client.origination_action(
                customer_id, origination_action_payload("RESTORE"), world.regulator
            )
        )

        assert_equals(restored, "origination_state", "ENABLED")
        assert_null(restored, "suspension_cause")
        assert_null(restored, "suspension_source_id")

        assert_equals(world.read_assignment(first["id"]), "status", "ACTIVE")
        assert_equals(world.read_assignment(second["id"]), "status", "ACTIVE")
        assert_equals(world.read_assignment(third["id"]), "status", "REVOKED")
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=2
        )

        rows, _meta = expect_list_total(
            world.client.list_number_assignments(
                world.regulator, provider_id=provider_id
            ),
            3,
        )
        statuses = sorted(row["status"] for row in rows)
        assert statuses == ["ACTIVE", "ACTIVE", "REVOKED"], (
            f"every assignment must sit in exactly one partition, got {statuses}"
        )
