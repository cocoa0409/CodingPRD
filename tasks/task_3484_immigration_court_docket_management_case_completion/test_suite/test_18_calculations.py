"""Calculation probes: priority-score caps and floor, selector ranking and
empty pools, and the inclusive detained-deadline / judge-minute boundaries.

The continuance drag caps at four grants and the score floors at zero; the
age term caps at 720 days; interpreter selection ranks by same-day load then
earliest created_at and rejects on a language gap; reassignment selection
compares load ratios exactly with a created_at tie-break and rejects when
every candidate is saturated; the detained master deadline and the judge's
120-minute daily cap are both inclusive upper bounds.
"""

from test_helpers import (
    ApiErrorId,
    assert_case_reassignment,
    assert_hearing,
    assign_case_to_judge,
    case_version,
    create_case,
    create_court,
    create_interpreter,
    create_judge,
    get_success_data,
    grant_continuances,
    list_case_hearings,
    make_continuance_payload,
    make_hearing_payload,
    make_reassignment_payload,
    read_case,
    same_instant,
    schedule_hearing,
    scheduled_hearing_of,
    set_clock,
    setup_docketed_case,
    validate_error,
    validate_success,
    CONTINUANCE_HEARING_START_ISO,
)


def test_priority_score_drag_capped_at_four_and_floored_at_zero(api, admin_headers):
    """PRD §3.2: "The score starts from a base of 1000 points for a `DETAINED` case and 0 otherwise; it adds 2 points per calendar day of age as measured by `days_pending_calendar`, with the age term capped at 720 days; and it subtracts a drag of 25 points per granted continuance as measured by `continuance_count`, with the drag capped at 4 continuances — so a case with five granted continuances sheds the same 100 points as one with four. The total is floored at 0: a score never goes negative."
    PRD §3.4: "Second, the system caps granted continuances at 2 for a `DETAINED` case and 5 for a `NON_DETAINED` case, evaluated at filing time against the case's current `continuance_count`: a filing made when the granted count already equals the cap — the one that would become grant number three for a detained case, or number six for a non-detained one — is rejected with `ERR_CONTINUANCE_CAP_REACHED`, while a filing made when the count sits one below the cap is allowed."
    PRD §3.4: "a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one"

    Design: Corner/calculations/priority_score_drag_cap_and_floor
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    schedule_hearing(ctx["case"], "MASTER_CALENDAR", CONTINUANCE_HEARING_START_ISO)
    # Five grants, each bumping the live hearing +28 days (non-detained).
    grant_continuances(case_id, ctx["judge"]["id"], 5)

    # The sixth filing would become grant number six -> the cap rejects it.
    live = scheduled_hearing_of(case_id)
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, live["id"], "OTHER"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_CAP_REACHED)

    case = read_case(case_id)
    assert case["continuance_count"] == 5
    # Non-detained base 0; at the 2026-09-01 clock the age term is 0; the drag
    # is 25 * min(5, 4) = 100 (cap binds); max(0, -100) floors the score at 0.
    assert case["days_pending_calendar"] == 0
    assert case["priority_score"] == 0
    # 2026-09-10 + five 28-day bumps: 10-08 -> 11-05 -> 12-03 -> 12-31 -> 01-28.
    assert same_instant(
        scheduled_hearing_of(case_id)["scheduled_start"], "2027-01-28T10:00:00Z"
    )


def test_priority_score_age_term_capped_at_720_days():
    """PRD §3.2: "The score starts from a base of 1000 points for a `DETAINED` case and 0 otherwise; it adds 2 points per calendar day of age as measured by `days_pending_calendar`, with the age term capped at 720 days; and it subtracts a drag of 25 points per granted continuance as measured by `continuance_count`, with the drag capped at 4 continuances — so a case with five granted continuances sheds the same 100 points as one with four. The total is floored at 0: a score never goes negative."
    PRD §3.2: "The calendar variant alone drives the case's past-goal posture: `is_past_goal` is true only when `days_pending_calendar` strictly exceeds the custody-specific target."

    Design: Corner/calculations/priority_score_age_cap_binds_at_720_days
    """
    court = create_court()
    case = create_case(court["id"], custody_status="DETAINED")
    # 800 days after the 2026-09-01 filing instant is 2028-11-09.
    set_clock("2028-11-09T00:00:00Z")

    case = read_case(case["id"])
    assert case["days_pending_calendar"] == 800
    # 1000 + 2 * min(800, 720) - 0 = 2440: the cap removes exactly 160 points.
    assert case["priority_score"] == 2440
    assert case["is_past_goal"] is True, "800 days strictly exceeds the 60-day target"


def test_interpreter_selector_ranks_by_load_then_created_at(api, admin_headers):
    """PRD §3.3: "Among the candidates the system selects the interpreter with the fewest `SCHEDULED` hearings on that date, breaking ties by earliest `created_at`; the interpreter's `id` and any random property play no role in selection."

    Design: Corner/calculations/interpreter_selector_ranks_by_load_then_created_at
    """
    court = create_court()
    judge = create_judge(court["id"])
    interp_first = create_interpreter(
        court["id"], full_name="Interp One", language_codes=["spa"], daily_hearing_cap=4
    )
    # Advance the logical clock one second so the second interpreter's
    # created_at is strictly later — the tie-break reads that field.
    set_clock("2026-09-01T00:00:01Z")
    interp_second = create_interpreter(
        court["id"], full_name="Interp Two", language_codes=["spa"], daily_hearing_cap=4
    )
    case1 = assign_case_to_judge(
        create_case(
            court["id"], primary_language_code="spa", interpreter_required=True
        )["id"],
        judge["id"],
    )
    case2 = assign_case_to_judge(
        create_case(
            court["id"], primary_language_code="spa", interpreter_required=True
        )["id"],
        judge["id"],
    )

    # Both candidates sit at 0 hearings that day: the 0-0 tie resolves by
    # earliest created_at, landing on the first-created interpreter.
    resp = api.create_hearing(
        make_hearing_payload(
            case1["id"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z",
            case_version(case1["id"]),
        ),
        headers=admin_headers,
    )
    hearing1 = validate_success(resp, expected_status=201)
    assert hearing1["interpreter_id"] == interp_first["id"]

    # Now the first interpreter carries load 1 on 2026-09-03 and the second
    # carries 0: fewest-load ranking lands on the second interpreter.
    resp = api.create_hearing(
        make_hearing_payload(
            case2["id"], "MASTER_CALENDAR", "2026-09-03T12:00:00Z",
            case_version(case2["id"]),
        ),
        headers=admin_headers,
    )
    hearing2 = validate_success(resp, expected_status=201)
    assert hearing2["interpreter_id"] == interp_second["id"]


def test_interpreter_selector_empty_pool_on_language_gap(api, admin_headers):
    """PRD §3.3: "An interpreter is a candidate only when all four conditions hold: they belong to the case's court; their `language_codes` contain the case's `primary_language_code`; the number of their `SCHEDULED` hearings on the new hearing's UTC date is still below their `daily_hearing_cap`; and they satisfy a buffer rule against every one of their existing `SCHEDULED` hearings — the candidate is disqualified only if an existing hearing both ends strictly after a point 15 minutes before the new hearing's start and begins strictly before a point 15 minutes after the new hearing's end."
    PRD §3.3: "If the candidate pool is empty, creation fails with `ERR_NO_INTERPRETER_AVAILABLE` (HTTP 422)."

    Design: Corner/calculations/interpreter_selector_empty_pool_on_language_gap
    """
    ctx = setup_docketed_case(primary_language_code="spa", interpreter_required=True)
    # The court's only interpreter covers French, not the case's Spanish.
    create_interpreter(ctx["court"]["id"], language_codes=["fra"])

    resp = api.create_hearing(
        make_hearing_payload(
            ctx["case"]["id"], "MASTER_CALENDAR", "2026-09-03T10:00:00Z",
            case_version(ctx["case"]["id"]),
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_INTERPRETER_AVAILABLE)
    assert list_case_hearings(ctx["case"]["id"]) == [], "the failed creation persisted no hearing"


def test_reassignment_tiebreak_prefers_earliest_created_court(api, admin_headers):
    """PRD §3.7: "The candidate pool is every court other than the case's current one whose `pending_case_count` is strictly below its `annual_completion_goal`; the winner is the candidate with the smallest ratio of `pending_case_count` to `annual_completion_goal`, with ties broken by earliest `created_at`; and the ratios are compared exactly — pending cases of one court times the other's goal against the other's pending times the one's goal — so floating-point drift can never reorder two near-equal candidates. The court's `id` plays no role in ranking."
    PRD §3.7: "Execution writes an immutable `CaseReassignment` record: its `from_court_id` is the source court, its `to_court_id` the selected destination, its `reason` is always `BACKLOG_REBALANCE`, and its `executed_at` is the clock."

    Design: Corner/calculations/reassignment_selector_tiebreak_prefers_earliest_created_court
    """
    # Source goal 4 -> threshold ceil(0.25 * 4) = 1, so its single case makes
    # it backlog-critical. Both candidates sit at load ratio 0/100; the tie
    # breaks by earliest created_at.
    source = create_court(annual_completion_goal=4)
    set_clock("2026-09-01T00:00:01Z")
    court_b = create_court(annual_completion_goal=100)
    set_clock("2026-09-01T00:00:02Z")
    court_c = create_court(annual_completion_goal=100)
    case = create_case(source["id"], custody_status="NON_DETAINED")

    resp = api.create_case_reassignment(
        make_reassignment_payload(case["id"], case["version"]),
        headers=admin_headers,
    )
    record = validate_success(resp, expected_status=201)
    assert_case_reassignment(record)
    assert record["from_court_id"] == source["id"]
    assert record["to_court_id"] == court_b["id"], (
        "equal 0/100 load ratios break by created_at: the earlier-created court wins"
    )
    assert record["to_court_id"] != court_c["id"]
    assert record["reason"] == "BACKLOG_REBALANCE"
    assert read_case(case["id"])["court_id"] == court_b["id"]


def test_reassignment_empty_pool_when_all_candidates_saturated(api, admin_headers):
    """PRD §3.7: "The candidate pool is every court other than the case's current one whose `pending_case_count` is strictly below its `annual_completion_goal`; the winner is the candidate with the smallest ratio of `pending_case_count` to `annual_completion_goal`, with ties broken by earliest `created_at`; and the ratios are compared exactly — pending cases of one court times the other's goal against the other's pending times the one's goal — so floating-point drift can never reorder two near-equal candidates. The court's `id` plays no role in ranking. An empty pool — every other court at or above its completion goal — rejects the operation with `ERR_NO_ELIGIBLE_COURT` (HTTP 422)."

    Design: Corner/calculations/reassignment_selector_empty_pool_when_all_saturated
    """
    source = create_court(annual_completion_goal=4)
    court_z = create_court(annual_completion_goal=1)
    # Court Z sits at exactly its goal: 1 < 1 is false, so equality is not
    # eligible and the pool is empty.
    create_case(court_z["id"])
    case = create_case(source["id"], custody_status="NON_DETAINED")

    resp = api.create_case_reassignment(
        make_reassignment_payload(case["id"], case["version"]),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_COURT)

    assert read_case(case["id"])["court_id"] == source["id"]
    records = get_success_data(
        api.list_case_reassignments(
            headers=admin_headers, params={"case_id": case["id"], "limit": 100}
        )
    )
    assert records == [], "the rejected reassignment wrote no record"


def test_detained_master_deadline_inclusive_boundary(api, admin_headers):
    """PRD §3.3: "A master-calendar hearing for a `DETAINED` case must start no later than 14 days after filing, and an individual-merits hearing no later than 30 days after filing; both deadlines are inclusive, and a `scheduled_start` even one second beyond them is rejected with `ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE`."
    PRD §3.3: "Remote hearing technology is mandatory on the detained docket: `is_remote` must be true, otherwise `ERR_DETAINED_REQUIRES_REMOTE`."

    Design: Corner/calculations/detained_expedited_deadline_inclusive_boundary
    """
    court = create_court()
    judge = create_judge(court["id"])
    det1 = assign_case_to_judge(
        create_case(court["id"], custody_status="DETAINED")["id"], judge["id"]
    )
    det2 = assign_case_to_judge(
        create_case(court["id"], custody_status="DETAINED")["id"], judge["id"]
    )

    # filed_at 2026-09-01T00:00:00Z + 14 days = 2026-09-15T00:00:00Z exactly:
    # the inclusive deadline admits it.
    resp = api.create_hearing(
        make_hearing_payload(
            det1["id"], "MASTER_CALENDAR", "2026-09-15T00:00:00Z",
            case_version(det1["id"]), is_remote=True,
        ),
        headers=admin_headers,
    )
    hearing1 = validate_success(resp, expected_status=201)
    assert_hearing(hearing1)
    assert hearing1["status"] == "SCHEDULED"

    # One second beyond the deadline is rejected.
    resp = api.create_hearing(
        make_hearing_payload(
            det2["id"], "MASTER_CALENDAR", "2026-09-15T00:00:01Z",
            case_version(det2["id"]), is_remote=True,
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE)
    assert list_case_hearings(det2["id"]) == []


def test_judge_daily_minute_cap_allows_exactly_120(api, admin_headers):
    """PRD §3.3: "The system totals the already-rounded `duration_minutes` of the judge's `SCHEDULED` hearings falling on the new hearing's UTC calendar date, adds the new hearing's rounded duration, and requires the sum to be at most 120 minutes; a sum of exactly 120 is allowed, and anything above it rejects the hearing with `ERR_JUDGE_DAILY_MINUTES_EXCEEDED`."
    PRD §3.3: "Adjacency is allowed, so a hearing that ends exactly when another begins is not a conflict; a genuine overlap is rejected with `ERR_JUDGE_SCHEDULE_CONFLICT`."

    Design: Corner/calculations/judge_daily_minute_cap_allows_exactly_120
    """
    court = create_court()
    judge = create_judge(court["id"])
    cases = [
        assign_case_to_judge(create_case(court["id"])["id"], judge["id"])
        for _ in range(5)
    ]

    # Four adjacent 30-minute master blocks: 30+30+30+30 == 120 == the cap,
    # and equality is allowed (adjacent half-open intervals never overlap).
    starts = [
        "2026-09-03T10:00:00Z",
        "2026-09-03T10:30:00Z",
        "2026-09-03T11:00:00Z",
        "2026-09-03T11:30:00Z",
    ]
    for case, start in zip(cases[:4], starts):
        resp = api.create_hearing(
            make_hearing_payload(
                case["id"], "MASTER_CALENDAR", start, case_version(case["id"])
            ),
            headers=admin_headers,
        )
        hearing = validate_success(resp, expected_status=201)
        assert hearing["duration_minutes"] == 30

    # The fifth block would push the day to 150 > 120.
    resp = api.create_hearing(
        make_hearing_payload(
            cases[4]["id"], "MASTER_CALENDAR", "2026-09-03T12:00:00Z",
            case_version(cases[4]["id"]),
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_JUDGE_DAILY_MINUTES_EXCEEDED)
    assert list_case_hearings(cases[4]["id"]) == []
