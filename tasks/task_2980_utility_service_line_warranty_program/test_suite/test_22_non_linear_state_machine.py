"""Lifecycles that are neither linear nor single-threaded.

The claim's denial/appeal loop is a genuine cycle terminated by a counter rather
than by an absorbing state, and a policy carries three status words that advance
on their own schedules.
"""

from test_helpers import factories, fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.api_errors import ERR_APPEAL_LIMIT_REACHED
from test_helpers.assertions import assert_refused
from test_helpers.test_users import (
    APPEALS_OFFICER,
    BILLING_OPS,
    PLATFORM_ADMIN,
    make_policyholder_headers,
)


class TestAppealRemandCycle:
    """DENIED to APPEAL_OPEN and back, twice, then refused by the counter."""

    def test_denial_appeal_remand_cycle_bounded_by_the_appeal_limit(self, api):
        """Two remands refresh denied_at, and only the third appeal is refused.

        PRD: "A remand moves `APPEAL_OPEN → DENIED` and **refreshes `denied_at` to the logical clock**, which restarts the 30-day appeal window from scratch — the cycle `DENIED → APPEAL_OPEN → DENIED` is therefore genuinely repeatable, bounded only by the two-appeal limit."

        Design: Difficulty/non_linear_state_machine/claim_denial_appeal_remand_cycle_bounded_by_appeal_limit
        """
        world = fixtures.active_coverage(api)
        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Curb stop leaking at the sidewalk joint.",
        )

        # The denial is a segment judgement, not an intake eligibility failure.
        assert claim["eligibility_assessment"] == "ELIGIBLE"

        denied = fixtures.deny_claim(
            api,
            claim["id"],
            "NOT_COVERED_SEGMENT",
            coverage_note="Adjuster reads the failure as outside the insured segment.",
        )
        assert denied["status"] == "DENIED"
        assert canonical_instant(denied["denied_at"]) == "2026-09-10T08:00:00.000Z"

        # ── first pass round the loop ──
        fixtures.set_clock(api, "2026-09-12T00:00:00.000Z")
        appeal_1 = fixtures.open_appeal(
            api,
            claim["id"],
            world["premises_id"],
            appeal_reason="The excavation photo shows the break on the house side of the curb stop.",
        )
        assert appeal_1["status"] == "APPEAL_OPEN"
        assert appeal_1["appeal_count"] == 1

        fixtures.set_clock(api, "2026-09-15T00:00:00.000Z")
        remand_1 = fixtures.decide_appeal(
            api,
            claim["id"],
            "REMAND",
            rationale="Send it back to triage for a second segment review.",
        )
        assert remand_1["status"] == "DENIED"
        # A remand closes the appeal without consuming another one.
        assert remand_1["appeal_count"] == 1
        assert canonical_instant(remand_1["denied_at"]) == "2026-09-15T00:00:00.000Z"

        # ── second pass, admissible only because the remand moved the anchor ──
        # 2026-10-10 is 43 days after the original denial but 25 after the remand.
        fixtures.set_clock(api, "2026-10-10T00:00:00.000Z")
        appeal_2 = fixtures.open_appeal(
            api,
            claim["id"],
            world["premises_id"],
            appeal_reason="Second appeal: the utility's own locate map contradicts the adjuster.",
        )
        assert appeal_2["status"] == "APPEAL_OPEN"
        assert appeal_2["appeal_count"] == 2

        fixtures.set_clock(api, "2026-10-12T00:00:00.000Z")
        remand_2 = fixtures.decide_appeal(
            api,
            claim["id"],
            "REMAND",
            rationale="Denial stands on the current record; back to DENIED.",
        )
        assert remand_2["status"] == "DENIED"
        assert canonical_instant(remand_2["denied_at"]) == "2026-10-12T00:00:00.000Z"

        # ── the counter, not an absorbing state, ends the cycle ──
        refused = api.create_appeal(
            claim["id"],
            factories.appeal_payload(appeal_reason="Third appeal attempt."),
            make_policyholder_headers(world["premises_id"]),
        )
        assert_refused(refused, ERR_APPEAL_LIMIT_REACHED, 409)

        final = fixtures.refresh_claim(api, claim["id"])
        # Still in the loop's low state, not in a terminal one.
        assert final["status"] == "DENIED"
        assert final["appeal_count"] == 2
        assert final["appeal_source"] == "POLICYHOLDER"
        assert final["appeal_decided_by_user_id"] == APPEALS_OFFICER["X-User-ID"]


class TestParallelStatusDimensions:
    """Three status words on one policy, moving on three schedules."""

    def test_coverage_billing_and_cap_dimensions_advance_independently(self, api):
        """Across four writes each dimension moves only when its own rule fires.

        PRD: "An accepted enrollment opens with `version` 1 and three status dimensions that thereafter advance independently: `coverage_status` at `PENDING_WAITING_PERIOD`, `billing_status` at `CURRENT`, and `cap_status` at `WITHIN_CAP`."

        Design: Difficulty/non_linear_state_machine/enrollment_coverage_billing_and_cap_dimensions_advance_independently
        """
        world = fixtures.enrolled_premises(api)
        enrollment_id = world["enrollment_id"]
        at_create = world["enrollment"]
        assert at_create["coverage_status"] == "PENDING_WAITING_PERIOD"
        assert at_create["billing_status"] == "CURRENT"
        assert at_create["cap_status"] == "WITHIN_CAP"

        world = fixtures.activate_coverage(api, world, clock="2026-09-10T00:00:00.000Z")
        assert enrollment_id in world["nightly_report"]["activated_enrollment_ids"]
        assert world["enrollment"]["coverage_status"] == "ACTIVE"

        # A missed payment moves the billing dimension alone.
        missed = fixtures.billing_event(
            api,
            enrollment_id,
            "MISSED_PAYMENT",
            "2026-09-10",
            memo="Autopay returned NSF.",
        )
        assert missed["coverage_status"] == "ACTIVE"
        assert missed["billing_status"] == "PAST_DUE"
        assert missed["past_due_since"] == "2026-09-10"
        assert missed["cap_status"] == "WITHIN_CAP"

        # Thirty days of arrears move the coverage dimension alone.
        fixtures.set_clock(api, "2026-10-10T00:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert enrollment_id in report["suspended_enrollment_ids"]
        assert enrollment_id not in report["lapsed_enrollment_ids"]

        after_sweep = fixtures.refresh_enrollment(api, enrollment_id, BILLING_OPS)
        assert after_sweep["coverage_status"] == "SUSPENDED_NONPAY"
        # The coverage sweep does not repair the billing dimension.
        assert after_sweep["billing_status"] == "PAST_DUE"
        assert after_sweep["cap_status"] == "WITHIN_CAP"

        # One payment is the single place the two dimensions couple.
        paid = fixtures.billing_event(
            api,
            enrollment_id,
            "PREMIUM_PAYMENT",
            "2026-10-10",
            amount_cents=2499,
            memo="Arrears cleared by card.",
        )
        assert paid["coverage_status"] == "ACTIVE"
        assert paid["billing_status"] == "CURRENT"
        assert paid["past_due_since"] is None
        # The cap dimension never moved across any of the four writes.
        assert paid["cap_status"] == "WITHIN_CAP"
        assert paid["annual_benefit_used_cents"] == 0

        # The missed payment moved no money, so only the payment is on the ledger.
        cash = fixtures.ledger_entries(
            api, PLATFORM_ADMIN, enrollment_id=enrollment_id, ledger_kind="CASH"
        )
        assert len(cash) == 1
        assert cash[0]["entry_type"] == "PREMIUM_PAYMENT"
        assert cash[0]["amount_cents"] == 2499
