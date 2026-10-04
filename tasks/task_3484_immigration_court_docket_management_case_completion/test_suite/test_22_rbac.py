"""RBAC probes: endpoint-level role denials, judge ownership denials, and the
read access shared by all three roles.

A BoardMember cannot file a case and an ImmigrationJudge cannot run a docket
review (endpoint permission, tier 2); the administrator who filed an appeal
cannot rule on it (the filer and the board are disjoint roles); a continuance
ruling binds to the case's assigned judge and a hearing completion to the
hearing's own judge (role-entity ownership, tier 4); and the single-case GET
answers all three roles identically.
"""

from test_helpers import (
    ApiErrorId,
    create_court,
    create_judge,
    file_continuance,
    make_case_payload,
    make_judge_headers,
    make_ruling_payload,
    read_case,
    read_hearing,
    schedule_hearing,
    set_clock,
    setup_appealed_case,
    setup_docketed_case,
    validate_error,
    validate_paginated,
    validate_success,
    CONTINUANCE_HEARING_START_ISO,
    MASTER_HEARING_CLOCK_ISO,
    MASTER_HEARING_START_ISO,
)

def test_board_member_cannot_file_case(api, admin_headers, board_headers):
    """PRD §2.1: "A request whose declared role is not permitted on the target endpoint per the §4 authorization column is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: `POST /eoir/cases` ("Initiate a case upon filing of a charging document") authorizes CourtAdministrator only.

    Design: Corner/rbac/board_member_cannot_file_case
    """
    court = create_court()
    resp = api.create_case(
        make_case_payload(court["id"], case_number="RB-1"),
        headers=board_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows, _meta = validate_paginated(
        api.list_cases(headers=admin_headers, params={"court_id": court["id"]})
    )
    assert rows == [], "the role-denied filing persisted nothing"


def test_judge_cannot_run_docket_review(api, admin_headers):
    """PRD §2.1: "A request whose declared role is not permitted on the target endpoint per the §4 authorization column is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: `POST /eoir/courts/{courtId}/docket-reviews` ("Run the docket checkpoint for a court: snapshot metrics and process lapses") authorizes CourtAdministrator only.

    Design: Corner/rbac/judge_cannot_run_docket_review
    """
    court = create_court()
    judge = create_judge(court["id"])
    # A real Judge identity, so the denial is the endpoint-permission tier and
    # not the user-context tier.
    resp = api.create_docket_review(
        court["id"], headers=make_judge_headers(judge["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows, _meta = validate_paginated(
        api.list_docket_reviews(
            headers=admin_headers, params={"court_id": court["id"]}
        )
    )
    assert rows == [], "the role-denied checkpoint froze no snapshot"


def test_administrator_cannot_decide_appeal(api, admin_headers):
    """PRD §2.1: "A request whose declared role is not permitted on the target endpoint per the §4 authorization column is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: `POST /eoir/appeals/{appealId}/decide` ("Board member affirms, remands, or dismisses an appeal") authorizes BoardMember only.

    Design: Corner/rbac/administrator_cannot_decide_appeal
    """
    # Case driven to APPEALED with the appeal FILED by the administrator.
    ctx = setup_appealed_case()
    appeal = ctx["appeal"]
    assert appeal["status"] == "FILED"

    resp = api.decide_appeal(
        appeal["id"], {"ruling": "AFFIRMED"}, headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    after = validate_success(api.get_appeal(appeal["id"], headers=admin_headers))
    assert after["status"] == "FILED", "the role-denied ruling changed nothing"
    assert read_case(ctx["case"]["id"])["status"] == "APPEALED"


def test_unassigned_judge_cannot_rule_on_continuance(api, admin_headers):
    """PRD §2.6: "4. **Role-entity ownership (HTTP 403).** Judge-scoped actions bind the caller to the record: `ERR_NOT_ASSIGNED_JUDGE` when the case's `assigned_judge_id` differs from `X-User-ID`, and `ERR_NOT_HEARING_JUDGE` when the hearing's `judge_id` differs from it."
    PRD §3.4: "Ruling rests with the assigned judge, who supplies a `decision` of `GRANTED` or `DENIED`. The request must still be `PENDING` (otherwise `ERR_CONTINUANCE_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`); either ruling stamps `decided_by_judge_id` with the acting judge and `decided_at` with the clock."

    Design: Corner/rbac/unassigned_judge_cannot_rule_on_continuance
    """
    ctx = setup_docketed_case()
    court, judge, case = ctx["court"], ctx["judge"], ctx["case"]
    other = create_judge(court["id"], full_name="Judge Other")
    hearing = schedule_hearing(case, "MASTER_CALENDAR", CONTINUANCE_HEARING_START_ISO)
    request = file_continuance(case["id"], hearing["id"], "EVIDENCE_GATHERING")
    assert request["status"] == "PENDING"

    # A different judge of the same court: identity resolves (tier 1) and the
    # role is permitted (tier 2), so the ownership tier alone denies.
    resp = api.decide_continuance_request(
        request["id"],
        make_ruling_payload("GRANTED"),
        headers=make_judge_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_JUDGE)

    after = validate_success(
        api.get_continuance_request(request["id"], headers=admin_headers)
    )
    assert after["status"] == "PENDING"
    assert after["decided_by_judge_id"] is None
    assert after["decided_at"] is None


def test_non_hearing_judge_cannot_complete_hearing(api, admin_headers):
    """PRD §3.4: "Completing a hearing requires it to be `SCHEDULED` (otherwise `ERR_HEARING_NOT_SCHEDULED`), requires the clock to have reached its `scheduled_start` (earlier attempts fail with `ERR_HEARING_NOT_YET_DUE`), and requires the caller to be the hearing's own judge — `X-User-ID` equal to the hearing's `judge_id`, otherwise `ERR_NOT_HEARING_JUDGE`."
    PRD §2.6: "4. **Role-entity ownership (HTTP 403).** Judge-scoped actions bind the caller to the record: `ERR_NOT_ASSIGNED_JUDGE` when the case's `assigned_judge_id` differs from `X-User-ID`, and `ERR_NOT_HEARING_JUDGE` when the hearing's `judge_id` differs from it."

    Design: Corner/rbac/non_hearing_judge_cannot_complete_hearing
    """
    ctx = setup_docketed_case()
    court, judge, case = ctx["court"], ctx["judge"], ctx["case"]
    other = create_judge(court["id"], full_name="Judge Other")
    hearing = schedule_hearing(case, "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    assert hearing["judge_id"] == judge["id"]
    set_clock(MASTER_HEARING_CLOCK_ISO)  # at the start, so only ownership can fail

    resp = api.complete_hearing(
        hearing["id"], headers=make_judge_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_HEARING_JUDGE)

    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"
    assert read_case(case["id"])["status"] == "CALENDAR"


def test_get_endpoints_readable_by_all_three_roles(
    api, admin_headers, board_headers
):
    """PRD §4: "The authorization column names the roles permitted to call each endpoint; "All roles" means any of the three declared roles (`CourtAdministrator`, `ImmigrationJudge`, `BoardMember`)."
    PRD §4: `GET /eoir/cases/{caseId}` ("Get a case including computed age, priority, and target fields") authorizes all roles.

    Design: Corner/rbac/get_endpoints_readable_by_all_three_roles
    """
    ctx = setup_docketed_case()
    case, judge = ctx["case"], ctx["judge"]

    as_admin = validate_success(api.get_case(case["id"], headers=admin_headers))
    as_judge = validate_success(
        api.get_case(case["id"], headers=make_judge_headers(judge["id"]))
    )
    as_board = validate_success(api.get_case(case["id"], headers=board_headers))
    assert as_admin == as_judge == as_board, (
        "the same read returns an identical data payload to all three roles"
    )
    assert as_admin["id"] == case["id"]
