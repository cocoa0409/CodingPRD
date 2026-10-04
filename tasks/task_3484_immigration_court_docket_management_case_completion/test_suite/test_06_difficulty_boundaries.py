"""Difficulty probes: boundary precision on counts and timestamps.

The detained continuance cap is inclusive-at-cap: filings are allowed while
the granted count is 0 or 1 and rejected when it already equals 2. The appeal
window is inclusive at the deadline instant: a filing at exactly
`appeal_deadline` succeeds, and one a second later fails.
"""

from test_helpers import (
    ApiErrorId,
    grant_continuances,
    list_case_hearings,
    make_appeal_payload,
    make_continuance_payload,
    read_case,
    read_decision,
    same_instant,
    schedule_hearing,
    scheduled_hearing_of,
    set_clock,
    setup_decided_case,
    setup_docketed_case,
    validate_error,
    validate_success,
)


def test_detained_continuance_filings_below_cap_allowed():
    """PRD §3.4: "Second, the system caps granted continuances at 2 for a `DETAINED` case and 5 for a `NON_DETAINED` case, evaluated at filing time against the case's current `continuance_count`: a filing made when the granted count already equals the cap — the one that would become grant number three for a detained case, or number six for a non-detained one — is rejected with `ERR_CONTINUANCE_CAP_REACHED`, while a filing made when the count sits one below the cap is allowed."
    PRD §3.4: "the same case, hearing type, judge, and `is_remote` flag; `auto_created` true; `supersedes_hearing_id` pointing at the continued hearing; and a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one".

    Design: Difficulty/boundary_precision_check/detained_continuance_cap_rejects_at_exactly_two
    """
    ctx = setup_docketed_case(custody_status="DETAINED")
    # Detained master within the 14-day expedited deadline and remote, as the
    # detained docket requires; the scheduling helper sets is_remote for it.
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")
    assert hearing["is_remote"] is True
    # Two filings made while the granted count is 0 and then 1 are allowed.
    grants = grant_continuances(ctx["case"]["id"], ctx["judge"]["id"], 2)
    case = grants["case"]
    assert case["continuance_count"] == 2
    hearings = list_case_hearings(ctx["case"]["id"])
    assert len(hearings) == 3, "two superseded hearings plus the live one"
    statuses = sorted(h["status"] for h in hearings)
    assert statuses == ["CONTINUED", "CONTINUED", "SCHEDULED"]
    live = scheduled_hearing_of(ctx["case"]["id"])
    # Each grant bumped the hearing +7 days: 2026-09-10 -> 09-17 -> 09-24.
    assert same_instant(live["scheduled_start"], "2026-09-24T10:00:00Z")
    assert live["is_remote"] is True, "the replacement copies the remote flag"


def test_detained_continuance_filing_rejected_at_exactly_cap(api, admin_headers):
    """PRD §3.4: "a filing made when the granted count already equals the cap — the one that would become grant number three for a detained case, or number six for a non-detained one — is rejected with `ERR_CONTINUANCE_CAP_REACHED`, while a filing made when the count sits one below the cap is allowed."

    Design: Difficulty/boundary_precision_check/detained_continuance_cap_rejects_at_exactly_two
    """
    ctx = setup_docketed_case(custody_status="DETAINED")
    schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")
    grant_continuances(ctx["case"]["id"], ctx["judge"]["id"], 2)
    live = scheduled_hearing_of(ctx["case"]["id"])
    # The count is exactly at the cap (2), so this filing is the one that
    # would become grant number three: rejected.
    resp = api.create_continuance_request(
        make_continuance_payload(ctx["case"]["id"], live["id"], "OTHER"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_CAP_REACHED)
    assert read_case(ctx["case"]["id"])["continuance_count"] == 2


def test_appeal_filed_at_exact_deadline_succeeds(api, admin_headers):
    """PRD §3.6: "The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`."
    PRD §3.6: "A filed appeal copies its `case_id` from the decision, records its `filed_at` at the clock, starts `FILED` with `decided_by_board_member_id` and `decided_at` null, moves the decision from `ISSUED` to `APPEAL_PENDING`, moves the case from its `DECIDED` or `IN_ABSENTIA` posture to `APPEALED`, and increments the case's `version` by 1."

    Design: Difficulty/boundary_precision_check/appeal_window_inclusive_at_exact_deadline
    """
    # Decision issued at 2026-09-04T12:00Z; appeal_deadline 2026-10-04T12:00Z.
    ctx = setup_decided_case()
    decision = ctx["decision"]
    assert same_instant(decision["appeal_deadline"], "2026-10-04T12:00:00Z")
    # Clock exactly equal to the deadline is inside the inclusive window.
    set_clock("2026-10-04T12:00:00Z")
    resp = api.create_appeal(make_appeal_payload(decision["id"]), headers=admin_headers)
    appeal = validate_success(resp, 201)
    assert appeal["status"] == "FILED"
    assert read_decision(decision["id"])["status"] == "APPEAL_PENDING"
    assert read_case(ctx["case"]["id"])["status"] == "APPEALED"


def test_appeal_filed_one_second_past_deadline_rejected(api, admin_headers):
    """PRD §3.6: "the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/appeal_window_inclusive_at_exact_deadline
    """
    ctx = setup_decided_case()
    # One second strictly past the 2026-10-04T12:00Z deadline.
    set_clock("2026-10-04T12:00:01Z")
    resp = api.create_appeal(
        make_appeal_payload(ctx["decision"]["id"]), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
    # Nothing was written: the decision and the case keep their postures.
    assert read_decision(ctx["decision"]["id"])["status"] == "ISSUED"
    assert read_case(ctx["case"]["id"])["status"] == "DECIDED"
