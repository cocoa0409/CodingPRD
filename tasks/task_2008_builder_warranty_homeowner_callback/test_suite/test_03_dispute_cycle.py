"""Denial, dispute, arbitration resolution, and the cyclic re-assessment loop."""
from test_helpers import (
    ApiErrorId,
    assess_request,
    assert_instant_equal,
    create_denied_request,
    create_homeowner,
    dispute_request,
    resolve_dispute,
    set_clock,
    setup_closed_request,
    setup_home,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import assess_warrantable_payload
from test_helpers.test_users import TEST_USERS, make_homeowner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]


def test_dispute_deadline_inclusive_then_passed(api):
    """PRD §3.5: "Within thirty days of denial — the `dispute_deadline_at` boundary
    is inclusive, so a dispute filed exactly at the deadline is accepted and one
    instant later is `ERR_DISPUTE_DEADLINE_PASSED` — the owning homeowner files a
    dispute with their `dispute_reason`, moving the request from `DENIED` to
    `DISPUTED`."

    Design: Corner/validations/dispute_deadline_inclusive_then_passed
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    sr1 = create_denied_request(
        home["id"],
        homeowner["id"],
        item_category="DRYWALL_PAINT",
        description="Issue 1",
        denial_reason_code="NORMAL_MAINTENANCE",
        education_packet_code="EDU-CAULK-01",
    )
    sr2 = create_denied_request(
        home["id"],
        homeowner["id"],
        item_category="DRYWALL_PAINT",
        description="Issue 2",
        denial_reason_code="NORMAL_MAINTENANCE",
        education_packet_code="EDU-CAULK-01",
    )
    # Both denied at the 2026-08-01T00:00:00Z default clock: deadline 2026-08-31T00:00:00Z.
    set_clock("2026-08-31T00:00:00Z")
    disputed = dispute_request(sr1["id"], homeowner["id"], "At the wire")
    assert disputed["status"] == "DISPUTED", "dispute exactly at the deadline is accepted"

    set_clock("2026-08-31T00:00:01Z")
    resp = api.dispute_service_request(
        sr2["id"],
        {"dispute_reason": "One second late"},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_DEADLINE_PASSED)


def test_dispute_by_non_owner_rejected(api):
    """PRD §2.1: "An entity-backed caller acting on a resource it does not own is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.5: "Within thirty days of denial — the `dispute_deadline_at` boundary
    is inclusive, so a dispute filed exactly at the deadline is accepted and one
    instant later is `ERR_DISPUTE_DEADLINE_PASSED` — the owning homeowner files a
    dispute with their `dispute_reason`, moving the request from `DENIED` to
    `DISPUTED`."

    Design: Corner/validations/dispute_by_non_owner_rejected
    """
    owner, home = setup_home(closing_date="2026-06-01")
    other = create_homeowner(full_name="Sam Wren", email="sam@example.com")
    request = create_denied_request(
        home["id"],
        owner["id"],
        item_category="DRYWALL_PAINT",
        description="Scuffed wall",
    )
    resp = api.dispute_service_request(
        request["id"],
        {"dispute_reason": "Not fair"},
        make_homeowner_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    after = validate_success(api.get_service_request(request["id"], REP), 200)
    assert after["status"] == "DENIED", "rejected dispute leaves the request DENIED"


def test_sr_closed_terminal_lockdown(api):
    """PRD §3.2: "Triage is the `WarrantyRep`'s assess action, allowed only from
    `RECEIVED` or `REOPENED`; any other non-terminal state draws
    `ERR_INVALID_STATE`, and a `CLOSED` request draws `ERR_ALREADY_TERMINAL`."
    PRD §2.7: "If the target sits in a terminal state for its lifecycle — a
    `CLOSED` service request; an `ACCEPTED` or `CANCELLED` work order; a `PAID`,
    `WAIVED`, or `VOID` chargeback; a `PAID` or `DENIED` claim — the rejection is
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/sr_closed_terminal_lockdown
    """
    ctx = setup_closed_request()
    assert ctx["request"]["status"] == "CLOSED", "follow-up closed the request"

    resp = api.assess_service_request(
        ctx["request"]["id"], assess_warrantable_payload(), REP
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    resp2 = api.dispute_service_request(
        ctx["request"]["id"],
        {"dispute_reason": "Changed my mind"},
        make_homeowner_headers(ctx["homeowner"]["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestDenialDisputeReopenCycle:
    def _drive_through_reopen(self, api):
        """RECEIVED -> DENIED -> DISPUTED -> REOPENED, all at the default clock."""
        homeowner, home = setup_home(closing_date="2026-06-01")
        denied = create_denied_request(
            home["id"],
            homeowner["id"],
            item_category="DRYWALL_PAINT",
            description="Hairline drywall crack at stairwell",
        )
        assert denied["status"] == "DENIED"
        disputed = dispute_request(
            denied["id"],
            homeowner["id"],
            "Crack is at a tape joint, present since walkthrough",
        )
        assert disputed["status"] == "DISPUTED"
        reopened = resolve_dispute(
            denied["id"], "HOMEOWNER_PREVAILS", "Arbitrator finds workmanship defect"
        )
        return homeowner, home, reopened

    def test_cycle_returns_to_approved_on_reassess(self, api):
        """PRD §3.5: "`HOMEOWNER_PREVAILS` reopens the request: `dispute_outcome` is
        recorded, `reopened_count` increments, the response deadline re-anchors to
        the reopen instant plus the severity's response hours with
        `response_breached` cleared and `escalation_level` raised to at least 1, and
        the coverage fields — `completion_due_at`, `approved_at`, and
        `determined_tier` — are wiped, because coverage must be re-assessed from
        scratch against the original `reported_at`."
        PRD §3.2: "For a reopened request, these same coverage checks are evaluated
        against the original `reported_at`, never a new intake time."

        Design: Difficulty/non_linear_state_machine/service_request_denial_dispute_reopen_cycle
        """
        _homeowner, _home, reopened = self._drive_through_reopen(api)
        assert reopened["status"] == "REOPENED"

        assessed = assess_request(reopened["id"], assess_warrantable_payload())
        assert assessed["status"] == "APPROVED", (
            "the machine is cyclic: REOPENED re-enters assessment and can approve"
        )
        assert assessed["determined_tier"] == "WORKMANSHIP", (
            "re-assessed against the original reported_at (2026-08-01), inside the "
            "workmanship window for the 2026-06-01 closing"
        )

    def test_cycle_counters_and_dispute_history(self, api):
        """PRD §3.5: "`HOMEOWNER_PREVAILS` reopens the request: `dispute_outcome` is
        recorded, `reopened_count` increments, the response deadline re-anchors to
        the reopen instant plus the severity's response hours with
        `response_breached` cleared and `escalation_level` raised to at least 1, and
        the coverage fields — `completion_due_at`, `approved_at`, and
        `determined_tier` — are wiped, because coverage must be re-assessed from
        scratch against the original `reported_at`."

        Design: Difficulty/non_linear_state_machine/service_request_denial_dispute_reopen_cycle
        """
        _homeowner, _home, reopened = self._drive_through_reopen(api)
        assert reopened["reopened_count"] == 1, "the loop was traversed exactly once"
        assert reopened["dispute_outcome"] == "HOMEOWNER_PREVAILS", (
            "dispute history is recorded"
        )
        assert reopened["response_breached"] is False, "breach flag cleared on reopen"
        assert reopened["escalation_level"] >= 1
        assert reopened.get("determined_tier") is None
        assert reopened.get("approved_at") is None
        assert reopened.get("completion_due_at") is None
        assert_instant_equal(
            reopened["response_due_at"], "2026-08-04T00:00:00Z", "response_due_at"
        )

        assessed = assess_request(reopened["id"], assess_warrantable_payload())
        assert assessed["reopened_count"] == 1
        assert assessed["dispute_outcome"] == "HOMEOWNER_PREVAILS", (
            "dispute history is retained through the cycle"
        )
