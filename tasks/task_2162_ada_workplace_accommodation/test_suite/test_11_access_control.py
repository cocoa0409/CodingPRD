"""Authentication, role permissions, ownership, department scope and the
segregation of duties on appeals."""

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    UNKNOWN_IDS,
    ApiErrorId,
    build_user_headers,
    case_version,
    create_accommodation_request_payload,
    create_employee,
    create_function_analysis_payload,
    create_job_profile_payload,
    essential_function_ids,
    file_appeal,
    make_employee_headers,
    make_manager_headers,
    open_case,
    read_appeal,
    read_case,
    read_denial,
    read_employee,
    set_clock,
    setup_case_at_function_analysis,
    setup_case_denied_out_of_doc_pending,
    setup_workforce,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_a_request_without_auth_headers_is_rejected_before_anything_else(api):
    """PRD §2.1: "Every request to this API — including reads, including the
    operational endpoints — must carry two headers. `X-User-ID` identifies the
    actor and `X-User-Role` names the capacity in which that actor is acting. If
    either header is absent, or if `X-User-Role` is not exactly one of the seven
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). This check runs before anything else, ahead of body parsing and ahead
    of any lookup."

    Design: Corner/rbac/corner_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_job_profile(
        create_job_profile_payload(job_code="C-JP-41", department_code="CO7"),
        NO_AUTH_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    # Nothing was written: the same job_code is still free to an authenticated caller.
    created = validate_success(
        api.create_job_profile(
            create_job_profile_payload(job_code="C-JP-41", department_code="CO7"), COORD
        ),
        201,
    )
    assert created["job_code"] == "C-JP-41"


def test_an_employee_actor_id_that_names_no_row_is_an_unknown_actor(api):
    """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of
    the acting `Employee` row; ownership checks on any case-scoped resource
    compare that resource's owning case's `employee_id` against `X-User-ID`."
    PRD §2.1: "For both of these roles, if `X-User-ID` does not resolve to an
    existing `Employee`, the request is rejected with `ERR_UNKNOWN_ACTOR` (HTTP
    401)."

    Design: Corner/rbac/corner_unknown_actor_id_rejected_for_entity_backed_role
    """
    set_clock()
    ctx = setup_workforce(department_code="CO8", with_manager=False)

    response = api.create_accommodation_request(
        create_accommodation_request_payload(
            ctx["employee"]["id"],
            requested_accommodation_text="Filed by a ghost actor",
        ),
        build_user_headers(UNKNOWN_IDS["actor"], "Employee"),
    )
    validate_error(response, ApiErrorId.ERR_UNKNOWN_ACTOR)

    assert read_employee(ctx["employee"]["id"])["open_case_count"] == 0


def test_a_finance_officer_may_not_issue_a_documentation_round(api):
    """PRD §2.1: "Each endpoint declares the set of roles permitted to invoke it
    (see §4). An authenticated actor whose role is not in that set is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.3: "Only an `AccommodationCoordinator` may issue medical
    documentation, and the issue is guarded by the case-version concurrency token
    described in §2.7."

    Design: Corner/rbac/corner_finance_officer_cannot_issue_documentation_request
    """
    set_clock()
    ctx = setup_workforce(department_code="CO9", with_manager=False)
    case = open_case(ctx, disability_obvious=False)

    response = api.create_medical_doc_request(
        case["id"],
        {
            "scope_fields_requested": ["functional_limitations"],
            "due_date": "2026-08-17T00:00:00Z",
            "is_second_opinion": False,
            "expected_request_version": case_version(case["id"]),
        },
        FINANCE,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    stored = read_case(case["id"])
    assert stored["stage"] == "INTAKE"
    assert stored["medical_doc_request_count"] == 0


def test_an_employee_without_the_people_manager_flag_cannot_sign_an_analysis(api):
    """PRD §2.1: "Acting as `Manager` additionally requires that the resolved
    `Employee` row carries `is_people_manager` set to true; a resolved employee
    without that flag is rejected with `ERR_NOT_A_PEOPLE_MANAGER` (HTTP 403)."
    PRD §3.4: "Recording that analysis is the `Manager` role's exclusive act — no
    coordinator, officer or auditor may sign one."

    Design: Corner/rbac/corner_non_people_manager_cannot_record_function_analysis
    """
    set_clock()
    ctx = setup_case_at_function_analysis(department_code="CP1")
    assert ctx["employee"]["is_people_manager"] is False

    response = api.create_function_analysis(
        ctx["case"]["id"],
        create_function_analysis_payload(essential_function_ids(ctx)[0]),
        make_manager_headers(ctx["employee"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_A_PEOPLE_MANAGER)

    _rows, meta = validate_paginated(
        api.list_function_analyses(COORD, {"request_id": ctx["case"]["id"]})
    )
    assert meta["total_count"] == 0


def test_an_employee_cannot_drive_another_employees_case(api):
    """PRD §2.6: "**Case ownership for employees** — when acting as `Employee` on
    a case-scoped resource, `X-User-ID` must equal the case's `employee_id`;
    otherwise `ERR_NOT_CASE_OWNER`. This guard covers exactly eight operations:
    opening an accommodation case, driving a case's stage, proposing an option on
    a case, responding to a documentation round, filing an appeal against a
    denial, performing a non-terminal appeal action, recording an effectiveness
    check-in on a trial, and amending a function analysis."
    PRD §3.3: "At any point from `INTAKE`, `DOC_PENDING`, `FUNCTION_ANALYSIS`,
    `OPTION_EXPLORATION`, `HARDSHIP_REVIEW`, `DECISION_PENDING`, `TRIAL_SETUP` or
    `TRIAL_ACTIVE`, the case's own `Employee` may abandon the process by naming
    `WITHDRAWN` as the `target_stage`; the guard is simply that `X-User-ID`
    equals the case's `employee_id`."

    Design: Corner/rbac/corner_employee_cannot_act_on_another_employees_case
    """
    set_clock()
    ctx = setup_workforce(department_code="CP2", with_manager=False)
    case = open_case(ctx)
    bystander = create_employee(
        ctx["profile"]["id"],
        department_code="CP2",
        full_name="Corner Bystander",
    )

    response = api.advance_accommodation_request(
        case["id"], {"target_stage": "WITHDRAWN"}, make_employee_headers(bystander["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_CASE_OWNER)

    assert read_case(case["id"])["stage"] == "INTAKE"
    assert read_employee(ctx["employee"]["id"])["open_case_count"] == 1


def test_a_manager_outside_the_case_department_is_out_of_scope(api):
    """PRD §2.1: "When `X-User-Role` is `Manager`, `X-User-ID` is likewise the
    `id` of an acting `Employee` row, and scope checks compare that row's
    `department_code` against the case employee's `department_code`."
    PRD §2.6: "**Manager department scope** — when acting as `Manager` on a
    case-scoped resource, the acting employee's `department_code` must equal the
    case employee's `department_code`; otherwise `ERR_MANAGER_SCOPE_VIOLATION`.
    This guard covers exactly five operations: recording a function analysis on a
    case, amending a function analysis, recording an effectiveness check-in on a
    trial, authoring an essential function on a job profile, and revising an
    essential function."

    Design: Corner/rbac/corner_manager_from_other_department_cannot_record_analysis
    """
    set_clock()
    ctx = setup_case_at_function_analysis(
        department_code="CP3", manager_department_code="CP4"
    )
    assert ctx["manager"]["is_people_manager"] is True, (
        "this is a scope failure, not a people-manager failure"
    )

    response = api.create_function_analysis(
        ctx["case"]["id"],
        create_function_analysis_payload(essential_function_ids(ctx)[0]),
        ctx["manager_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MANAGER_SCOPE_VIOLATION)

    _rows, meta = validate_paginated(
        api.list_function_analyses(COORD, {"request_id": ctx["case"]["id"]})
    )
    assert meta["total_count"] == 0


def test_the_officer_who_issued_the_denial_may_not_review_the_appeal(api):
    """PRD §3.8: "On every appeal action and every appeal decision, the acting
    officer's `X-User-ID` must differ from the `issued_by_user_id` recorded on
    the denial under appeal, **and** must differ from every `manager_id` that
    signed an analysis in `status` `RECORDED` on the underlying case. A violation
    of either comparison is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "The denial creates a denial record in `status` `ISSUED`, carrying
    `issued_by_user_id` from the acting `X-User-ID` (which is the comparand the
    segregation-of-duties rule later uses), `issued_at` from the logical clock,
    `appeal_count` at zero, and `rejected_option_ids` listing the ids of every
    option on the case whose status was `CLEARED` or `HARDSHIP_BLOCKED` at that
    moment."

    Design: Corner/rbac/corner_appeal_officer_who_issued_denial_cannot_start_review
    """
    ctx = setup_case_denied_out_of_doc_pending(department_code="CP5")
    assert read_denial(ctx["denial"]["id"])["issued_by_user_id"] == "COORD-1"
    file_appeal(ctx, "The documentation was submitted through the portal.")

    conflicted = api.transition_appeal(
        ctx["appeal"]["id"],
        {"action": "START_REVIEW"},
        build_user_headers("COORD-1", "AppealOfficer"),
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert read_appeal(ctx["appeal"]["id"])["status"] == "FILED"

    allowed = validate_success(
        api.transition_appeal(
            ctx["appeal"]["id"],
            {"action": "START_REVIEW"},
            build_user_headers("APPEAL-7", "AppealOfficer"),
        ),
        200,
    )
    assert allowed["status"] == "UNDER_REVIEW"
    assert allowed["appeal_officer_user_id"] == "APPEAL-7"
