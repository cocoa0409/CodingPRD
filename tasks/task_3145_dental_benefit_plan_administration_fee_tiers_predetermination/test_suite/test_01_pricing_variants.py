"""Two price variants of the same charge.

A claim priced under an approved predetermination's pin can disagree with
the same claim priced freely against the schedule governing the service
date, and a predetermination's estimate at assign time can disagree with
its re-run estimate at approve time.
"""

from test_helpers import factories as f
from test_helpers.api_client import same_instant
from test_helpers.assertions import get_success_data, validate_success
from test_helpers.constants import (
    CATEGORY_MAJOR,
    CDT_CROWN_MAJOR,
    PREDET_APPROVED,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    approve_predetermination,
    assign_predetermination,
    claim_lines,
    create_active_fee_schedule,
    create_claim,
    create_predetermination,
    read_claim,
    read_predetermination,
    set_clock,
    standard_stack,
)
from test_helpers.test_users import EXAMINER, make_provider_headers


def _dv1_stack(client):
    """Plan, PPO provider, and schedule v1 (D2740 at 100000) governing 2026-01."""
    entries = [
        f.fee_schedule_entry_payload(
            cdt_code=CDT_CROWN_MAJOR, allowed_cents=100000, category=CATEGORY_MAJOR
        ),
    ]
    stack = standard_stack(
        client,
        plan_overrides={"plan_code": "DD-DV1", "deductible_cents": 5000},
        entries=entries,
        subscriber_overrides={"member_id": "M-DV1", "full_name": "Alice Prime"},
    )
    return stack


def _dv1_pinned_predetermination(client, stack):
    """An APPROVED predetermination for D2740 that pins schedule v1."""
    predet = create_predetermination(
        client,
        stack["subscriber"]["id"],
        stack["provider"],
        submitted_amount_cents=110000,
        planned_service_date="2026-04-15T00:00:00Z",
    )
    under_review = assign_predetermination(client, predet["id"], "rev-1")
    return approve_predetermination(client, predet["id"], under_review["version"], "rev-1")


def _dv1_roll_to_v2(client):
    """Activate schedule v2 (D2740 at 80000) from 2026-04-01, truncating v1."""
    entries = [
        f.fee_schedule_entry_payload(
            cdt_code=CDT_CROWN_MAJOR, allowed_cents=80000, category=CATEGORY_MAJOR
        ),
    ]
    return create_active_fee_schedule(
        client, entries=entries, effective_from="2026-04-01T00:00:00Z"
    )


class TestPinnedVersusServiceDatePricing:
    """One claim pinned by an approved quote, one priced free."""

    def test_pinned_claim_keeps_the_quoted_allowed_amount(self, client):
        """The approved predetermination's schedule governs the claim's price.

        PRD 3.6: "when the claim's `predetermination_id` references an
        `APPROVED` predetermination that has not expired, the schedule named
        by that predetermination's `version_pin_fee_schedule_id` governs
        instead — regardless of which schedule is currently `ACTIVE` — so a
        member treated under an approved quote pays exactly what they were
        quoted even if schedules have since rolled."

        Design: Difficulty/dual_variant_calc/claim_pricing_pinned_vs_free_by_service_date
        """
        stack = _dv1_stack(client)
        approved = _dv1_pinned_predetermination(client, stack)
        _dv1_roll_to_v2(client)

        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            predetermination_id=approved["id"],
            service_date="2026-04-15T00:00:00Z",
            received_date="2026-04-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="14",
                    submitted_amount_cents=110000,
                )
            ],
        )

        line = claim_lines(client, claim["id"])[0]
        assert claim["status"] == "ADJUDICATED"
        assert line["allowed_cents"] == 100000, (
            "pinned claim must price at the quoted schedule's 100000, got %r"
            % line["allowed_cents"]
        )

    def test_free_claim_prices_against_the_schedule_governing_service_date(self, client):
        """Without a pin, the same charge resolves by service date.

        PRD 3.6: "Pricing resolves the fee schedule as §2.8 describes: the
        schedule whose tier matches the rendering provider's `tier` at the
        moment of pricing, whose window contains the claim's `service_date`."
        PRD 3.6: "A claim referencing an expired or never-approved
        predetermination ignores the pin and prices by service date."

        Design: Difficulty/dual_variant_calc/claim_pricing_pinned_vs_free_by_service_date
        """
        stack = _dv1_stack(client)
        approved = _dv1_pinned_predetermination(client, stack)
        _dv1_roll_to_v2(client)

        claim_a = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            predetermination_id=approved["id"],
            service_date="2026-04-15T00:00:00Z",
            received_date="2026-04-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="14",
                    submitted_amount_cents=110000,
                )
            ],
        )
        claim_b = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            service_date="2026-04-15T00:00:00Z",
            received_date="2026-04-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="15",
                    submitted_amount_cents=110000,
                )
            ],
        )

        line_a = claim_lines(client, claim_a["id"])[0]
        line_b = claim_lines(client, claim_b["id"])[0]
        assert claim_b["status"] == "ADJUDICATED"
        assert line_b["allowed_cents"] == 80000, (
            "free claim must price at the schedule governing 2026-04-15, got %r"
            % line_b["allowed_cents"]
        )
        assert line_a["allowed_cents"] - line_b["allowed_cents"] == 20000, (
            "identical inputs diverge by exactly the schedule delta"
        )


class TestEstimateAtAssignVersusApprove:
    """The estimate re-runs at each variant's trigger."""

    def _dv2_stack_and_predet(self, client):
        entries = [
            f.fee_schedule_entry_payload(
                cdt_code=CDT_CROWN_MAJOR, allowed_cents=100000, category=CATEGORY_MAJOR
            ),
        ]
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-DV2"},
            entries=entries,
            subscriber_overrides={"member_id": "M-DV2", "full_name": "Bob Prime"},
        )
        predet = create_predetermination(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            submitted_amount_cents=110000,
            planned_service_date="2026-06-01T00:00:00Z",
        )
        return stack, predet

    def test_assign_computes_the_estimate_against_the_current_schedule(self, client):
        """Assignment prices the estimate against the schedule in force now.

        PRD 3.4: "Assignment moves the predetermination `SUBMITTED →
        UNDER_REVIEW`, records the reviewer, and computes the estimate: the
        system resolves the fee schedule `ACTIVE` for the rendering
        provider's tier at the `planned_service_date`, and sets
        `estimated_allowed_cents`, `estimated_plan_pay_cents`, and
        `estimated_patient_pay_cents` exactly as the claim adjudication
        pipeline would."

        Design: Difficulty/dual_variant_calc/predet_estimate_at_assign_vs_at_approve
        """
        stack, predet = self._dv2_stack_and_predet(client)

        assigned = assign_predetermination(client, predet["id"], "rev-1")

        assert assigned["status"] == "UNDER_REVIEW"
        assert assigned["estimated_allowed_cents"] == 100000
        assert assigned["estimated_plan_pay_cents"] == 50000, (
            "floor(100000 * 50/100) == 50000, got %r"
            % assigned["estimated_plan_pay_cents"]
        )

    def test_approve_reruns_the_estimate_and_pins_the_new_schedule(self, client):
        """Approval re-runs the estimate and locks the governing schedule.

        PRD 3.4: "The approval re-runs the estimate against current state,
        then freezes it: `version_pin_fee_schedule_id` is locked to the fee
        schedule used for the final estimate, the `estimated_*` fields are
        locked, and `expires_on` is set to the logical clock plus ninety
        days — the predetermination validity window."
        PRD 3.4: "activating a fee schedule recomputes every in-flight
        predetermination priced against the same tier" (see §2.11).

        Design: Difficulty/dual_variant_calc/predet_estimate_at_assign_vs_at_approve
        """
        stack, predet = self._dv2_stack_and_predet(client)
        assigned = assign_predetermination(client, predet["id"], "rev-1")
        assert assigned["estimated_allowed_cents"] == 100000

        entries_v2 = [
            f.fee_schedule_entry_payload(
                cdt_code=CDT_CROWN_MAJOR, allowed_cents=80000, category=CATEGORY_MAJOR
            ),
        ]
        schedule_v2 = create_active_fee_schedule(
            client, entries=entries_v2, effective_from="2026-05-01T00:00:00Z"
        )

        refreshed = read_predetermination(client, predet["id"])
        approved = approve_predetermination(
            client, predet["id"], refreshed["version"], "rev-1"
        )

        assert approved["status"] == PREDET_APPROVED
        assert approved["estimated_allowed_cents"] == 80000
        assert approved["estimated_plan_pay_cents"] == 40000
        assert approved["version_pin_fee_schedule_id"] == schedule_v2["id"]
