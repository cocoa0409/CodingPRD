"""Validation probes: hearing scheduling and hearing-day guards.

The clock gates hearing creation from below (no past starts) and completion
from above (no early completions); creation is stage-locked to docketed cases
holding at most one SCHEDULED hearing; the detained docket adds mandatory
remote technology and a per-court daily capacity cap; and the no-show path
stacks a notice-safety gate ahead of the pending-continuance constraint.
"""

from test_helpers import (
    ApiErrorId,
    assign_case_to_judge,
    case_version,
    create_case,
    create_court,
    create_judge,
    file_continuance,
    list_case_hearings,
    make_hearing_payload,
    make_judge_headers,
    make_notice_payload,
    read_hearing,
    schedule_hearing,
    serve_notice,
    set_clock,
    setup_docketed_case,
    validate_error,
    validate_success,
)


def test_hearing_in_past_and_not_yet_due_rejections(api, admin_headers):
    """PRD §3.3: "The `scheduled_start` must not be earlier than the current clock (`ERR_HEARING_IN_PAST`)."
    PRD §3.4: "Completing a hearing requires it to be `SCHEDULED` (otherwise `ERR_HEARING_NOT_SCHEDULED`), requires the clock to have reached its `scheduled_start` (earlier attempts fail with `ERR_HEARING_NOT_YET_DUE`), and requires the caller to be the hearing's own judge — `X-User-ID` equal to the hearing's `judge_id`, otherwise `ERR_NOT_HEARING_JUDGE`."

    Design: Corner/validations/hearing_clock_position_rejections
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    # At this clock a 2026-09-01 start is in the past and a 2026-09-03 start is
    # still in the future.
    set_clock("2026-09-02T00:00:00Z")

    # A start earlier than the current clock is rejected at creation.
    resp = api.create_hearing(
        make_hearing_payload(
            case_id, "MASTER_CALENDAR", "2026-09-01T10:00:00Z", case_version(case_id)
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_IN_PAST)
    assert list_case_hearings(case_id) == []

    # A future start is accepted...
    resp = api.create_hearing(
        make_hearing_payload(
            case_id, "MASTER_CALENDAR", "2026-09-03T10:00:00Z", case_version(case_id)
        ),
        headers=admin_headers,
    )
    hearing = validate_success(resp, expected_status=201)
    assert hearing["status"] == "SCHEDULED"

    # ...but it cannot be completed before its scheduled start arrives.
    resp = api.complete_hearing(
        hearing["id"], headers=make_judge_headers(ctx["judge"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_YET_DUE)
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"


def test_hearing_creation_case_state_and_single_scheduled_guards(api, admin_headers):
    """PRD §3.3: "The case must be in `CALENDAR` or `MERITS` — any other posture is rejected with `ERR_CASE_STATE_FORBIDS_HEARING`."
    PRD §3.3: "And a case may hold at most one `SCHEDULED` hearing at a time — a second attempt while one stands fails with `ERR_CASE_HAS_SCHEDULED_HEARING`."
    PRD §2.6: "Two ordering rules apply within this tier. First, the acting entity's own phase is checked before gates that look past it — on decision issuance, for example, whether the case is `MERITS` is evaluated before whether a completed merits hearing exists."

    Design: Corner/validations/hearing_creation_case_guards
    """
    court = create_court()
    judge = create_judge(court["id"])
    case = create_case(court["id"])

    # State gate: a FILED (not yet docketed) case forbids hearing creation.
    resp = api.create_hearing(
        make_hearing_payload(
            case["id"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z", case["version"]
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_STATE_FORBIDS_HEARING)
    assert list_case_hearings(case["id"]) == []

    # Once docketed the case is CALENDAR and the master hearing is created.
    case = assign_case_to_judge(case["id"], judge["id"])
    resp = api.create_hearing(
        make_hearing_payload(
            case["id"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z", case["version"]
        ),
        headers=admin_headers,
    )
    first = validate_success(resp, expected_status=201)
    assert first["status"] == "SCHEDULED"

    # Cardinality gate: a second hearing while one stands SCHEDULED fails.
    resp = api.create_hearing(
        make_hearing_payload(
            case["id"], "MASTER_CALENDAR", "2026-09-04T10:00:00Z",
            case_version(case["id"]),
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_HAS_SCHEDULED_HEARING)
    assert len(list_case_hearings(case["id"])) == 1


def test_detained_hearing_without_remote_flag_rejected(api, admin_headers):
    """PRD §3.3: "Remote hearing technology is mandatory on the detained docket: `is_remote` must be true, otherwise `ERR_DETAINED_REQUIRES_REMOTE`."
    PRD §3.3: "Once a case is docketed, a `CourtAdministrator` schedules hearings for it, supplying the `case_id`, a `hearing_type` of `MASTER_CALENDAR` or `INDIVIDUAL_MERITS`, a `scheduled_start`, and optionally `is_remote` (which defaults to false), together with the concurrency guard `expected_case_version` described in §2.7."

    Design: Corner/validations/detained_hearing_requires_remote
    """
    ctx = setup_docketed_case(custody_status="DETAINED")
    case_id = ctx["case"]["id"]
    # `is_remote` omitted: the server default (false) applies, and false is
    # forbidden on the detained docket.  Every other gate passes — the start is
    # within the 14-day expedited window and the court's capacity is open.
    resp = api.create_hearing(
        make_hearing_payload(
            case_id, "MASTER_CALENDAR", "2026-09-10T10:00:00Z", case_version(case_id)
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DETAINED_REQUIRES_REMOTE)
    assert list_case_hearings(case_id) == []


def test_detained_daily_capacity_reached_on_second_hearing(api, admin_headers):
    """PRD §3.3: "And the court's detained throughput is capped per UTC calendar day — if the court already hosts `detained_daily_hearing_capacity` `SCHEDULED` hearings of detained cases on the new hearing's date, the count has reached the cap and creation is rejected with `ERR_DETAINED_DAILY_CAPACITY_REACHED`."
    PRD §3.3: "Adjacency is allowed, so a hearing that ends exactly when another begins is not a conflict; a genuine overlap is rejected with `ERR_JUDGE_SCHEDULE_CONFLICT`."

    Design: Corner/validations/detained_daily_capacity_reached
    """
    court = create_court(detained_daily_hearing_capacity=1)
    judge = create_judge(court["id"])
    case1 = assign_case_to_judge(
        create_case(court["id"], custody_status="DETAINED")["id"], judge["id"]
    )
    case2 = assign_case_to_judge(
        create_case(court["id"], custody_status="DETAINED")["id"], judge["id"]
    )

    # The first detained hearing on 2026-09-10 succeeds.
    resp = api.create_hearing(
        make_hearing_payload(
            case1["id"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z",
            case_version(case1["id"]), is_remote=True,
        ),
        headers=admin_headers,
    )
    first = validate_success(resp, expected_status=201)
    assert first["is_remote"] is True

    # The second is adjacent (no judge overlap, 60 minutes total under the 120
    # cap) but the court already hosts one detained hearing on that UTC date.
    resp = api.create_hearing(
        make_hearing_payload(
            case2["id"], "MASTER_CALENDAR", "2026-09-10T10:30:00Z",
            case_version(case2["id"]), is_remote=True,
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DETAINED_DAILY_CAPACITY_REACHED)
    assert list_case_hearings(case2["id"]) == []


def test_no_show_notice_safety_then_pending_continuance_then_notice_uniqueness(
    api, admin_headers
):
    """PRD §3.5: "a `HearingNotice` must exist for the hearing (`ERR_NOTICE_NOT_SERVED`); that notice must be `SERVED` rather than `DEFECTIVE` — an in absentia order may not rest on defective notice, so a defective one blocks the recording with `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA`; no `PENDING` continuance may target the hearing (`ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW`); and the caller must be the hearing's judge (`ERR_NOT_HEARING_JUDGE`)."
    PRD §3.4: "Each hearing carries at most one notice — a second recording against the same hearing is rejected with `ERR_NOTICE_ALREADY_RECORDED` — and a notice begins life `SERVED`."
    PRD §2.6 tier 7 is: "7. **Due process (HTTP 409).** Notice requirements around in absentia practice: `ERR_NOTICE_NOT_SERVED`, `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA`, and `ERR_NOTICE_NOT_DEFECTIVE`." — and tier 9 names `ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW` among the capacity and cardinality constraints.

    Design: Corner/validations/no_show_guard_family
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-05T10:00:00Z")
    # Filed at the default clock, days ahead of the start: a clean PENDING
    # continuance targeting the hearing.
    file_continuance(case_id, hearing["id"], "EVIDENCE_GATHERING")
    set_clock("2026-09-05T11:00:00Z")

    # Safety gate first: no notice exists yet, so the no-show fails
    # ERR_NOTICE_NOT_SERVED (tier 7) even though the pending continuance
    # (tier 9) would also block it — the earlier tier wins.
    resp = api.record_no_show(
        hearing["id"], headers=make_judge_headers(ctx["judge"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_SERVED)
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"

    # With a SERVED notice recorded, the pending-continuance constraint is the
    # only remaining failing gate.
    serve_notice(hearing["id"])
    resp = api.record_no_show(
        hearing["id"], headers=make_judge_headers(ctx["judge"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW)
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"

    # One notice per hearing: a second recording against it is rejected.
    resp = api.create_notice(
        make_notice_payload(
            hearing["id"], service_method="PERSONAL_SERVICE",
            served_at="2026-08-21T00:00:00Z",
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_RECORDED)
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"
