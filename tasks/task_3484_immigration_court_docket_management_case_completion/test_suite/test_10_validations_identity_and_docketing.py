"""Validation probes: user-context rejection and the docketing/reassignment gates.

User context is the first validation tier: missing headers, undeclared role
strings, and judge identities that resolve to no Judge row are all the same
400.  Docketing then stacks a referential gate (judge's home court), a strict
caseload cap, and a FILED-only state gate; backlog reassignment admits only
non-detained cases out of backlog-critical courts.
"""

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    case_version,
    create_case,
    create_court,
    create_judge,
    make_assign_judge_payload,
    make_court_payload,
    make_reassignment_payload,
    read_case,
    read_judge,
    validate_error,
    validate_success,
)


def test_create_court_without_user_context_headers_rejected(api):
    """PRD §2.1: "A request missing either header, carrying a role value outside the three declared roles, or — when the declared role is `ImmigrationJudge` — carrying an `X-User-ID` that is not the `id` of an existing `Judge` is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    # No user-context headers at all.
    resp = api.create_court(make_court_payload(), headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    # Only one of the two headers present: "missing either header" covers this too.
    resp = api.create_court(make_court_payload(), headers={"X-User-ID": "admin-01"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_undeclared_role_and_unresolvable_judge_identity_rejected(api, judge_headers):
    """PRD §2.1: "A request missing either header, carrying a role value outside the three declared roles, or — when the declared role is `ImmigrationJudge` — carrying an `X-User-ID` that is not the `id` of an existing `Judge` is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.6: "1. **User context (HTTP 400).** Both headers are present, the declared role is one of the three declared values, and an `ImmigrationJudge` caller's `X-User-ID` resolves to an existing `Judge` — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/unknown_role_and_unknown_judge_identity_returns_400
    """
    court = create_court()
    # A role value outside the three declared roles is a tier-1 rejection,
    # even on an endpoint open to all roles.
    resp = api.get_court(court["id"], headers=build_user_headers("admin-01", "SuperUser"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    # The entity-backed ImmigrationJudge role whose X-User-ID matches no Judge
    # row is the same 400 (not a 403 or 404).
    resp = api.get_court(court["id"], headers=judge_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_assign_judge_wrong_court_cap_and_state_guards(api, admin_headers):
    """PRD §3.2: "An administrator names a `judge_id`; the system requires the case to still be `FILED` (otherwise `ERR_CASE_NOT_AWAITING_DOCKET`), the judge to exist (`ERR_JUDGE_NOT_FOUND`), the judge's home `court_id` to equal the case's venue `court_id` (otherwise `ERR_JUDGE_WRONG_COURT`), and the judge's `pending_case_load` to be strictly below `max_pending_cases` — a judge whose load already equals the cap rejects the assignment with `ERR_JUDGE_CASELOAD_FULL`."
    PRD §2.9: "A judge's `pending_case_load` is the number of cases whose `assigned_judge_id` names that judge and whose `status` is anything other than `COMPLETED`."
    PRD §2.6: "A request that would fail several checks receives exactly one error: the check in the earliest tier below that fails. The eleven tiers are evaluated in this order, and the ordering is itself part of the contract."

    Design: Corner/validations/assign_judge_guard_family
    """
    court_a = create_court()
    court_b = create_court()
    judge_a = create_judge(court_a["id"], max_pending_cases=1)
    judge_b = create_judge(court_b["id"])
    case1 = create_case(court_a["id"])
    case2 = create_case(court_a["id"])

    # Referential gate: the named judge sits at a different court than the venue.
    resp = api.assign_judge(
        case1["id"], make_assign_judge_payload(judge_b["id"]), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_JUDGE_WRONG_COURT)
    assert read_case(case1["id"])["status"] == "FILED", "rejected docketing mutates nothing"

    # Happy path: docketing succeeds and the judge's load rises to exactly the cap.
    resp = api.assign_judge(
        case1["id"], make_assign_judge_payload(judge_a["id"]), headers=admin_headers
    )
    data = validate_success(resp)
    assert data["status"] == "CALENDAR"
    assert data["assigned_judge_id"] == judge_a["id"]
    assert read_judge(judge_a["id"])["pending_case_load"] == 1

    # Constraint gate: load 1 already equals cap 1 (the cap comparison is strict <).
    resp = api.assign_judge(
        case2["id"], make_assign_judge_payload(judge_a["id"]), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_JUDGE_CASELOAD_FULL)
    assert read_case(case2["id"])["status"] == "FILED"

    # State gate: the first case is CALENDAR, not FILED.  The caseload cap would
    # also fail here, but the tier-5 state gate precedes the tier-9 capacity gate.
    resp = api.assign_judge(
        case1["id"], make_assign_judge_payload(judge_a["id"]), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_AWAITING_DOCKET)


def test_reassignment_requires_critical_source_court_and_non_detained_case(
    api, admin_headers
):
    """PRD §3.7: "Reassignment is a safety valve for the non-detained docket only: a `DETAINED` case may not be reassigned — detained respondents remain with the detaining court's docket — and the attempt is rejected with `ERR_DETAINED_NOT_REASSIGNABLE`; and the case's current court must actually be backlog-critical at execution time, otherwise `ERR_COURT_NOT_BACKLOG_CRITICAL`, because the operation exists to drain courts whose pending docket has crossed the §2.9 threshold."
    PRD §2.9: "a court is backlog-critical when its `pending_case_count` reaches at least one quarter of its `annual_completion_goal`, with that quarter rounded up to a whole case before the comparison."

    Design: Corner/validations/reassignment_guard_family_rejected
    """
    # Calm court: goal 100 -> critical at ceil(0.25 * 100) = 25 pending; holds 1.
    calm = create_court(annual_completion_goal=100)
    calm_case = create_case(calm["id"])
    # Critical court: goal 4 -> critical at ceil(0.25 * 4) = 1 pending; holds 1.
    critical = create_court(annual_completion_goal=4)
    detained_case = create_case(critical["id"], custody_status="DETAINED")
    # An eligible destination exists, so an empty candidate pool is never the
    # reason either attempt fails.
    create_court()

    # The source court has not crossed the backlog-critical threshold.
    resp = api.create_case_reassignment(
        make_reassignment_payload(calm_case["id"], case_version(calm_case["id"])),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COURT_NOT_BACKLOG_CRITICAL)

    # The detained case may not be reassigned even though its court is critical.
    resp = api.create_case_reassignment(
        make_reassignment_payload(
            detained_case["id"], case_version(detained_case["id"])
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DETAINED_NOT_REASSIGNABLE)

    # Rejections write nothing: both cases stay FILED at their original venues.
    calm_after = read_case(calm_case["id"])
    assert calm_after["status"] == "FILED"
    assert calm_after["court_id"] == calm["id"]
    detained_after = read_case(detained_case["id"])
    assert detained_after["status"] == "FILED"
    assert detained_after["court_id"] == critical["id"]
