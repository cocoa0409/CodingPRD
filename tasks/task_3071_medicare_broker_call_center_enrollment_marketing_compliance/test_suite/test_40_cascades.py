"""Cascading side effects: one trigger walks a chain of hops, each caused by the
previous one rather than by the original request.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, validate_success,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    setup_submitted_enrollment, create_coaching_assignment_payload,
    open_call, connect_call, capture_scope, create_member_for_agent,
    create_reconciliation_payload, set_clock, get_call,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
COACH = TEST_USERS["coach_headers"]


class TestOverdueCoachingCascade:
    """One overdue coaching assignment walks four hops down to a dropped live call."""

    def _live_call_scenario(self):
        """Master data + active agent + a manual coaching due 2026-10-15 + a live call."""
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        agent_id = scn["agent"]["id"]

        coaching = get_success_data(api_client.create_coaching_assignment(
            create_coaching_assignment_payload(agent_id), COACH))

        # A second member, scope and live call so the drop hop has something to hit.
        member_two, version = create_member_for_agent(
            scn["agency"]["id"], agent_id, full_name="Hollis Pike",
            medicare_beneficiary_id="3GH6-VG7-PM94",
            date_of_birth="1952-11-19T00:00:00Z")
        scope_two = capture_scope(member_two["id"], agent_id, version)
        call_two = open_call(agent_id, member_two["id"], scope_two["id"],
                             started_at="2026-10-01T10:00:00Z",
                             scheduled_end_at="2026-10-01T10:30:00Z",
                             recording_id="REC-1002")
        connect_call(agent_id, call_two["id"], recording_id="REC-1002")

        scn.update({"coaching": coaching, "member_two": member_two,
                    "scope_two": scope_two, "call_two": call_two})
        return scn

    def test_overdue_coaching_assignment_alone_crosses_the_restricted_branch(self):
        """PRD §2.7: "Otherwise, if any coaching assignment belonging to any of the
        agency's agents has an overdue day count of at least 1, the posture is `RESTRICTED`."

        Design: Difficulty/transitive_cascade/cascade_overdue_coaching_restricts_agency_and_drops_live_call
        """
        scn = self._live_call_scenario()
        assert scn["coaching"]["status"] == "ASSIGNED"
        assert scn["coaching"]["assigned_on"] == utc("2026-10-01T00:00:00Z")

        set_clock("2026-10-16T00:00:00Z")
        before = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
        assert before["compliance_posture"] == "OPEN"
        assert before["substantiated_complaint_rate"] == pytest.approx(0.0, abs=1e-9)

        result = validate_success(api_client.recompute_compliance_posture(
            scn["agency"]["id"], ADMIN), 200)
        assert result["compliance_posture"] == "RESTRICTED", (
            "the overdue coaching alone crosses the posture branch with no complaints on file"
        )

    def test_the_assignment_reads_overdue_one_day_past_its_due_date(self):
        """PRD §3.9: "the `due_on` date is `assigned_on` plus 14 days, and if the logical
        clock is at or before `due_on` the figure is 0, while a clock strictly past `due_on`
        yields the whole number of days from `due_on` to the clock."

        Design: Difficulty/transitive_cascade/cascade_overdue_coaching_restricts_agency_and_drops_live_call
        """
        scn = self._live_call_scenario()
        set_clock("2026-10-16T00:00:00Z")
        coaching = get_success_data(api_client.get_coaching_assignment(
            scn["coaching"]["id"], COACH))
        assert coaching["due_on"] == utc("2026-10-15T00:00:00Z")
        assert coaching["status"] == "OVERDUE"
        assert coaching["overdue_days"] == 1

    def test_the_restricted_cascade_suspends_the_agent_and_drops_the_live_call(self):
        """PRD §3.11: "Every agent of the agency in status `ACTIVE` is moved to
        `SUSPENDED`. Every call session belonging to any of the agency's agents that is in
        status `RINGING` or `IN_PROGRESS` is moved to `DROPPED` with `actual_end_at` set to
        the logical clock".

        Design: Difficulty/transitive_cascade/cascade_overdue_coaching_restricts_agency_and_drops_live_call
        """
        scn = self._live_call_scenario()
        set_clock("2026-10-16T00:00:00Z")
        api_client.recompute_compliance_posture(scn["agency"]["id"], ADMIN)

        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["status"] == "SUSPENDED"
        assert agent["live_call_count"] == 0

        call = get_call(scn["agent"]["id"], scn["call_two"]["id"])
        assert call["status"] == "DROPPED"
        assert call["actual_end_at"] == utc("2026-10-16T00:00:00Z")


class TestWithdrawalReversalCascade:
    """A withdrawal posts a reversal which itself moves the reconciliation variance."""

    def _scenario(self):
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_submitted_enrollment(scn)
        recon = get_success_data(api_client.create_reconciliation(
            create_reconciliation_payload(scn["carrier"]["id"],
                                          period_month="2026-10",
                                          carrier_reported_total_cents=5000,
                                          internal_total_variant="PROVISIONAL"),
            DIRECTOR))
        scn["reconciliation"] = recon
        return scn

    def test_open_period_reports_the_initial_entry_as_its_internal_total(self):
        """PRD §2.8: "Its `internal_total_cents` is the sum of the ledger amounts presented
        in that period, its `variance_cents` is the carrier-reported total minus the internal
        total".

        Design: Difficulty/transitive_cascade/cascade_withdrawal_reversal_moves_reconciliation_variance
        """
        scn = self._scenario()
        recon = get_success_data(
            api_client.get_reconciliation(scn["reconciliation"]["id"], DIRECTOR))
        assert recon["internal_total_cents"] == pytest.approx(3600.00, abs=0.01)
        assert recon["variance_cents"] == pytest.approx(1400.00, abs=0.01)

    def test_withdrawal_posts_a_reversal_against_the_non_reversed_entries(self):
        """PRD §3.8: "A `REVERSAL` entry takes the negated sum of `amount_cents` over every
        entry of that same enrollment whose status is not `REVERSED`."

        Design: Difficulty/transitive_cascade/cascade_withdrawal_reversal_moves_reconciliation_variance
        """
        scn = self._scenario()
        result = validate_success(withdraw_enrollment_response(scn), 200)
        assert result["submission_status"] == "WITHDRAWN"

        rows, _meta = validate_paginated(api_client.list_ledger_entries(
            DIRECTOR, params={"enrollment_id": scn["enrollment"]["id"]}))
        reversals = [r for r in rows if r["entry_type"] == "REVERSAL"]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == pytest.approx(-3600.00, abs=0.01)

    def test_the_reversal_posting_recomputes_the_period(self):
        """PRD §3.8: "Reversal moves the entry to `REVERSED` and recomputes the agency's
        `commission_balance_cents`, the reconciliation period's `internal_total_cents` and
        `variance_cents`, and the agency's `loss_ratio`."

        Design: Difficulty/transitive_cascade/cascade_withdrawal_reversal_moves_reconciliation_variance
        """
        scn = self._scenario()
        withdraw_enrollment_response(scn)

        recon = get_success_data(
            api_client.get_reconciliation(scn["reconciliation"]["id"], DIRECTOR))
        assert recon["internal_total_cents"] == pytest.approx(0.00, abs=0.01), (
            "the INITIAL 3600.00 and its REVERSAL -3600.00 net out"
        )
        assert recon["variance_cents"] == pytest.approx(5000.00, abs=0.01), (
            "the reversal posting itself recomputed the period, moving the variance"
        )

    def test_the_dispute_edge_becomes_reachable_on_the_recomputed_variance(self):
        """PRD §2.8: "disputing the month requires a non-zero variance and is refused with
        `ERR_RECONCILIATION_VARIANCE_ZERO` when the variance is exactly zero."

        Design: Difficulty/transitive_cascade/cascade_withdrawal_reversal_moves_reconciliation_variance
        """
        scn = self._scenario()
        withdraw_enrollment_response(scn)

        result = validate_success(api_client.dispute_reconciliation(
            scn["reconciliation"]["id"],
            {"dispute_note": "Carrier under-reported"}, DIRECTOR), 200)
        assert result["status"] == "DISPUTED"


def withdraw_enrollment_response(scn):
    """Withdraw the scenario enrollment as the acting agent; return the raw response."""
    from test_helpers import make_licensed_agent_headers
    headers = make_licensed_agent_headers(scn["agent"]["id"])
    return api_client.withdraw_enrollment(
        scn["enrollment"]["id"], {"reason": "BENEFICIARY_CHANGED_MIND"}, headers)