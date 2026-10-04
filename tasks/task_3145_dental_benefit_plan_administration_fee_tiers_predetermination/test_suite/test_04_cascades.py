"""Cascades: schedule activation ripples; void ripples into the accumulator.

Activating a successor schedule truncates the predecessor's window, and
that truncation recomputes every in-flight predetermination on the tier —
each recomputation bumping the predetermination's version without any
direct predetermination call.  Voiding a paid claim reverses the
accumulator and bumps its version in the same request.
"""

from test_helpers import factories as f
from test_helpers.assertions import validate_success
from test_helpers.constants import (
    CATEGORY_BASIC,
    CATEGORY_MAJOR,
    CDT_CROWN_MAJOR,
    CDT_FILING_BASIC,
    CLAIM_PAID,
    CLAIM_VOID,
    SCHEDULE_ACTIVE,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    assign_predetermination,
    create_active_fee_schedule,
    create_predetermination,
    pay_claim,
    read_fee_schedule,
    read_predetermination,
    standard_stack,
    subscriber_accumulators,
    void_claim,
)
from test_helpers.test_users import EXAMINER


class TestScheduleActivationCascade:
    """Activation truncates, truncation recomputes, recompute bumps."""

    def _tc1_stack(self, client):
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-TC1"},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=100000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-TC1", "full_name": "Gail Prime"},
        )
        predet = create_predetermination(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            submitted_amount_cents=110000,
            planned_service_date="2026-06-01T00:00:00Z",
        )
        under_review = assign_predetermination(client, predet["id"], "rev-1")
        return stack, under_review

    def _activate_v2(self, client):
        entries_v2 = [
            f.fee_schedule_entry_payload(
                cdt_code=CDT_CROWN_MAJOR, allowed_cents=80000,
                category=CATEGORY_MAJOR,
            ),
        ]
        return create_active_fee_schedule(
            client, entries=entries_v2, effective_from="2026-05-01T00:00:00Z"
        )

    def test_activation_truncates_the_overlapping_window(self, client):
        """The predecessor's window ends where the successor's begins.

        PRD 2.8: "When a `NetworkManager` activates a new schedule, any
        existing `ACTIVE` schedule for the same tier whose `effective_from`
        is on or before the new schedule's `effective_from` has its
        `effective_to` set to the new schedule's `effective_from` — its
        window is truncated but its status remains `ACTIVE`."

        Design: Difficulty/transitive_cascade/fee_schedule_activation_truncation_recompute_version_bump
        """
        stack, under_review = self._tc1_stack(client)
        schedule_v2 = self._activate_v2(client)

        refreshed_v1 = read_fee_schedule(client, stack["schedule"]["id"])
        assert refreshed_v1["effective_to"] == "2026-05-01T00:00:00Z", (
            "the truncation sets effective_to to the successor's start, got %r"
            % refreshed_v1["effective_to"]
        )
        assert refreshed_v1["status"] == SCHEDULE_ACTIVE, (
            "window truncation by a successor never changes a schedule's status"
        )
        assert schedule_v2["status"] == SCHEDULE_ACTIVE

    def test_truncation_recomputes_in_flight_predeterminations(self, client):
        """The recompute refreshes the estimate and bumps the version.

        PRD 3.4: "Because fee schedule activation recomputes every
        `UNDER_REVIEW` predetermination whose rendering provider's tier
        matches the schedule's tier — refreshing the `estimated_*` fields
        against the schedule now governing the planned service date and
        incrementing each recomputed predetermination's `version` — a
        reviewer approving after a schedule roll must re-read the estimate;
        the OCC check on approval exists precisely to catch a reviewer
        acting on a pre-recomputation view."

        Design: Difficulty/transitive_cascade/fee_schedule_activation_truncation_recompute_version_bump
        """
        stack, under_review = self._tc1_stack(client)
        assert under_review["estimated_allowed_cents"] == 100000
        assert under_review["estimated_plan_pay_cents"] == 50000
        pre_version = under_review["version"]

        self._activate_v2(client)

        refreshed = read_predetermination(client, under_review["id"])
        assert refreshed["estimated_allowed_cents"] == 80000, (
            "planned date 2026-06-01 is now governed by the cheaper schedule"
        )
        assert refreshed["estimated_plan_pay_cents"] == 40000
        assert refreshed["version"] == pre_version + 1, (
            "the cascade bumped the version with no direct predetermination call"
        )


class TestClaimVoidCascade:
    """Voiding reverses the accumulator and bumps its version."""

    def _tc2_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-TC2", "deductible_cents": 5000},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_FILING_BASIC, allowed_cents=10000,
                    category=CATEGORY_BASIC,
                ),
            ],
            subscriber_overrides={"member_id": "M-TC2", "full_name": "Hank Prime"},
        )

    def _paid_claim(self, client, stack):
        claim = adjudicated_claim(
            client,
            stack,
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_FILING_BASIC, tooth_number="19",
                    submitted_amount_cents=10000,
                )
            ],
        )
        return pay_claim(client, claim["id"])

    def test_void_reverses_the_deductible_and_maximum_draws(self, client):
        """The void subtracts exactly what adjudication added.

        PRD 3.9: "Voiding reverses the accumulator exactly: the voided
        claim's payable lines have their `deductible_applied_cents` sums
        subtracted from `deductible_met_cents` and their `plan_pay_cents`
        sums subtracted from `annual_max_used_cents`, and the accumulator's
        `version` increments."

        Design: Difficulty/transitive_cascade/claim_void_reverses_accumulator_and_bumps_its_version
        """
        stack = self._tc2_stack(client)
        paid = self._paid_claim(client, stack)
        assert paid["status"] == CLAIM_PAID

        before = subscriber_accumulators(client, stack["subscriber"]["id"])[0]
        assert before["deductible_met_cents"] == 5000
        assert before["annual_max_used_cents"] == 4000

        voided = void_claim(client, paid["id"], paid["version"])
        assert voided["status"] == CLAIM_VOID

        after = subscriber_accumulators(client, stack["subscriber"]["id"])[0]
        assert after["deductible_met_cents"] == 0
        assert after["annual_max_used_cents"] == 0

    def test_void_increments_the_accumulator_version(self, client):
        """The reversal is itself a mutation of the accumulator.

        PRD 2.11: "State changes propagate down the entity hierarchy so the
        system never holds a contradiction: terminating a subscriber
        terminates all of their dependents and withdraws their open
        predeterminations; activating a fee schedule recomputes every
        in-flight predetermination priced against the same tier; voiding a
        claim reverses the accumulator exactly. Each cascade-induced mutation
        refreshes the affected resource's `updated_at` and increments its
        `version`, and each cascade is described beside the workflow that
        triggers it in §3."

        Design: Difficulty/transitive_cascade/claim_void_reverses_accumulator_and_bumps_its_version
        """
        stack = self._tc2_stack(client)
        paid = self._paid_claim(client, stack)

        before = subscriber_accumulators(client, stack["subscriber"]["id"])[0]

        void_claim(client, paid["id"], paid["version"])

        after = subscriber_accumulators(client, stack["subscriber"]["id"])[0]
        assert after["version"] == before["version"] + 1, (
            "the accumulator version is incremented by the cascade, got %r -> %r"
            % (before["version"], after["version"])
        )
