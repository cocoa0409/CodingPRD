"""A branching lifecycle whose two exits carry different side effects."""

from test_helpers import (
    ComplianceWorld,
    assert_cents,
    assert_equals,
    assert_fields,
    assert_not_null,
    assert_provider_counters,
    expect_created,
    expect_ok,
)
from test_helpers.factories import (
    adjudication_payload,
    enforcement_action_payload,
    payment_payload,
)


def _assess(world: ComplianceWorld, provider_id: str, **body):
    return expect_created(
        world.client.create_enforcement_action(
            enforcement_action_payload(provider_id, **body), world.regulator
        )
    )


def _build_two_assessments(world: ComplianceWorld):
    """One gateway provider carrying two freshly proposed forfeitures."""
    provider = world.register_provider(provider_type="GATEWAY")
    per_violation = _assess(
        world,
        provider["id"],
        basis="UNFILED_PLAN",
        violation_count=3,
        violation_days=10,
        assessment_basis="PER_VIOLATION",
    )
    continuing = _assess(
        world,
        provider["id"],
        basis="UNMITIGATED_NOTICE",
        violation_count=3,
        violation_days=10,
        assessment_basis="CONTINUING_DAILY",
    )
    return provider["id"], per_violation, continuing


def _read_action(world: ComplianceWorld, action_id: str):
    return expect_ok(world.client.get_enforcement_action(action_id, world.regulator))


class TestEnforcementForkJoin:
    """The contest fork, its dismissal branch and its sustain-then-pay branch."""

    def test_contest_holds_the_amount_and_dismissal_releases_only_its_own(self, world):
        """Contesting moves no money; dismissing one action releases 3,000,000 cents.

        PRD: "The provider's `ComplianceOfficer` may contest a `PROPOSED` action, which advances `PROPOSED → CONTESTED` and stamps `contested_at`; the outstanding total does **not** change, because a contested amount is still owed unless and until it is dismissed."

        Design: Difficulty/non_linear_state_machine/enforcement_fork_join_dismiss_and_sustain_branches_diverge
        """
        provider_id, per_violation, continuing = _build_two_assessments(world)
        assert_fields(per_violation, score_band="NONE", assessment_tier="TIER_2")
        assert_cents(per_violation, "mitigation_credit_cents", 0)
        assert_cents(per_violation, "total_forfeiture_cents", 3000000)
        assert_cents(continuing, "total_forfeiture_cents", 2500000)

        contested = expect_ok(
            world.client.contest_enforcement_action(
                per_violation["id"], world.officer_1
            )
        )
        expect_ok(
            world.client.contest_enforcement_action(continuing["id"], world.officer_1)
        )
        assert_equals(contested, "status", "CONTESTED")
        assert_not_null(contested, "contested_at")
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=5500000
        )

        dismissed = expect_ok(
            world.client.adjudicate_enforcement_action(
                per_violation["id"], adjudication_payload("DISMISS"), world.regulator
            )
        )

        assert_equals(dismissed, "status", "DISMISSED")
        assert_cents(dismissed, "total_forfeiture_cents", 3000000)
        assert_equals(_read_action(world, continuing["id"]), "status", "CONTESTED")
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=2500000
        )

    def test_sustained_branch_stays_outstanding_until_the_exact_amount_is_paid(
        self, world
    ):
        """A sustained action still owes 2,500,000 cents; payment clears it to zero.

        PRD: "A successful payment advances the action to `PAID`, stamps `paid_at` at the current logical clock, records the tendered figure as `paid_amount_cents`, and recomputes `outstanding_forfeiture_cents` with the action removed from the set."

        Design: Difficulty/non_linear_state_machine/enforcement_fork_join_dismiss_and_sustain_branches_diverge
        """
        provider_id, per_violation, continuing = _build_two_assessments(world)
        world.contest_forfeiture(per_violation["id"])
        world.contest_forfeiture(continuing["id"])
        world.adjudicate_forfeiture(per_violation["id"], "DISMISS")

        sustained = expect_ok(
            world.client.adjudicate_enforcement_action(
                continuing["id"], adjudication_payload("SUSTAIN"), world.regulator
            )
        )
        assert_equals(sustained, "status", "SUSTAINED")
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=2500000
        )

        paid = expect_ok(
            world.client.pay_enforcement_action(
                continuing["id"],
                payment_payload(2500000),
                world.provider_admin(provider_id),
            )
        )

        assert_equals(paid, "status", "PAID")
        assert_cents(paid, "paid_amount_cents", 2500000)
        assert_not_null(paid, "paid_at")
        assert_equals(_read_action(world, per_violation["id"]), "status", "DISMISSED")
        assert_provider_counters(
            world.read_provider(provider_id), outstanding_forfeiture_cents=0
        )
