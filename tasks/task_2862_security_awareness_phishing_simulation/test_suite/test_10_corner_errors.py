"""Error-surface claims: the fixed priority order and the shape of each refusal.

Every test in this module translates exactly one non-stub instance of the
`errors` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CAMPAIGN_SCHEDULED,
    CORRELATION_INSUFFICIENT_PAIRS,
    DELIVERY_QUEUED,
    INTERVENTION_COACHING_ASSIGNED,
    INTERVENTION_OPEN,
    REPORT_VARIANT_CONCURRENT,
    TEMPLATE_APPROVED_FOR_USE,
    TEMPLATE_BLOCKED,
    TIER_1,
    UNKNOWN_ASSIGNMENT_UUID,
    UNKNOWN_CAMPAIGN_UUID,
    UNKNOWN_CONSEQUENCE_UUID,
    UNKNOWN_DELIVERY_UUID,
    UNKNOWN_EMPLOYEE_UUID,
    UNKNOWN_INCIDENT_UUID,
    UNKNOWN_INTERVENTION_UUID,
    UNKNOWN_MODULE_UUID,
    UNKNOWN_NOTICE_UUID,
    UNKNOWN_TEMPLATE_UUID,
)
from test_helpers.assertions import assert_delivery, assert_instant_equals, ids_of
from test_helpers.factories import (
    effectiveness_params,
    incident_payload,
    schedule_payload,
)
from test_helpers.fixtures import (
    approved_campaign,
    create_published_module,
    create_template,
    read_employee,
    register_employee,
    repeat_clicker_at_tier_two,
    reset_clock,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    APPROVER,
    AUTHOR,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_learner_headers,
)


def test_authentication_is_settled_before_anything_else_is_looked_at(api):
    """Missing or empty headers are 401 even when the target does not exist.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, declaring the capacity in which that
    principal is acting. ... If either header is missing or empty, or if
    `X-User-Role` is not one of those six strings, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.8: "1. Header authentication — both headers present and the role
    recognised (`ERR_UNAUTHENTICATED`)."

    Design: Corner/errors/sweep_missing_x_user_role_header_returns_401
    """
    reset_clock(api)
    employee = register_employee(
        api, email="auth.probe@corp.example", full_name="Anna Auth",
        department="HR", role_code="IC", hire_date="2019-06-06",
    )

    validate_error(
        api.run_compliance_sweep(headers_without_role()),
        ApiErrorId.UNAUTHENTICATED.value,
        expected_status=401,
    )
    validate_error(
        api.run_compliance_sweep(headers_with_empty_user_id()),
        ApiErrorId.UNAUTHENTICATED.value,
        expected_status=401,
    )
    validate_error(
        api.run_compliance_sweep(headers_without_user_id()),
        ApiErrorId.UNAUTHENTICATED.value,
        expected_status=401,
    )

    # Authentication precedes path resolution, so this is 401 and not 404.
    validate_error(
        api.get_employee(UNKNOWN_EMPLOYEE_UUID, headers_without_role()),
        ApiErrorId.UNAUTHENTICATED.value,
        expected_status=401,
    )

    assert read_employee(api, employee["id"])["version"] == employee["version"]
    assert validate_success(api.list_notices({}, ADMIN)) == []


def test_an_undeclared_role_string_is_an_authentication_failure(api):
    """Role matching is exact over a closed set of six spellings.

    PRD §2.1: "Six roles exist, and their spelling is exact: `ProgramAdmin`,
    `CampaignAuthor`, `CampaignApprover`, `Manager`, `Learner`, and
    `SecurityAnalyst`. If either header is missing or empty, or if `X-User-Role` is
    not one of those six strings, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/clock_set_with_invalid_role_header_returns_401
    """
    reset_clock(api)

    validate_error(
        api.set_clock("2027-01-01T00:00:00Z", make_headers("SuperAdmin", "root")),
        ApiErrorId.UNAUTHENTICATED.value,
        expected_status=401,
    )
    validate_error(
        api.set_clock("2027-01-01T00:00:00Z",
                      make_headers("programadmin", "program-admin-1")),
        ApiErrorId.UNAUTHENTICATED.value,
        expected_status=401,
    )

    # The refused calls never moved the clock, which the sweep instant proves.
    sweep = run_sweep(api)
    assert_instant_equals(sweep["swept_at"], "2026-08-01T00:00:00Z", "swept_at")


def test_an_authenticated_learner_is_still_refused_the_admin_only_endpoints(api):
    """403 is the second gate and is distinct from the 401 of an unknown role.

    PRD §2.1: "When both headers are well formed but the declared role does not
    appear in the authorized-role list of the addressed endpoint (see the table in
    §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.8: "2. Role authorization against the endpoint's authorized-role list
    (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/errors/learner_cannot_run_compliance_sweeps_returns_403
    """
    reset_clock(api)
    employee = register_employee(
        api, email="lee.learner@corp.example", full_name="Lee Learner",
        department="SALES", role_code="IC", hire_date="2021-07-07",
    )
    learner = make_learner_headers(employee["id"])

    validate_error(
        api.run_compliance_sweep(learner),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api.create_incident(
            incident_payload(
                incident_type="BEC", severity="LOW", department="SALES",
                occurred_at="2026-07-31T10:00:00Z",
                summary="Learner attempting an analyst-only write.",
            ),
            learner,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    assert validate_success(api.list_incidents({}, ANALYST)) == []

    # The same Learner is on the authorized-role list of the single-employee read.
    own = validate_success(api.get_employee(employee["id"], learner))
    assert own["id"] == employee["id"]


def test_each_primary_family_owns_its_own_not_found_identifier(api):
    """The same well-formed unknown UUID yields five different 404 codes.

    PRD §2.8: "Each resource family has its own not-found identifier:
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND` and `ERR_DELIVERY_NOT_FOUND`
    cover employees, training modules, curriculum assignments, campaigns, phishing
    templates and simulation deliveries respectively, all at HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found_codes
    """
    reset_clock(api)

    expectations = [
        (api.get_assignment(UNKNOWN_ASSIGNMENT_UUID, ADMIN),
         ApiErrorId.ASSIGNMENT_NOT_FOUND.value),
        (api.get_template(UNKNOWN_TEMPLATE_UUID, ADMIN),
         ApiErrorId.TEMPLATE_NOT_FOUND.value),
        (api.get_campaign(UNKNOWN_CAMPAIGN_UUID, ADMIN),
         ApiErrorId.CAMPAIGN_NOT_FOUND.value),
        (api.get_delivery(UNKNOWN_DELIVERY_UUID, ADMIN),
         ApiErrorId.DELIVERY_NOT_FOUND.value),
        (api.get_module(UNKNOWN_MODULE_UUID, ADMIN),
         ApiErrorId.MODULE_NOT_FOUND.value),
    ]
    for response, expected_id in expectations:
        error = validate_error(response, expected_id, expected_status=404)
        assert error["message"], "every error envelope carries a message"

    # Path existence outranks state legality, so an action endpoint agrees.
    validate_error(
        api.launch_campaign(UNKNOWN_CAMPAIGN_UUID, ADMIN),
        ApiErrorId.CAMPAIGN_NOT_FOUND.value,
        expected_status=404,
    )


def test_the_secondary_families_share_the_generic_not_found_identifier(api):
    """Notices, consequences, interventions and incidents collapse onto one code.

    PRD §2.8: "Path identifiers for the remaining families — escalation notices,
    access consequences, repeat-clicker interventions, incident records and
    communication windows — resolve to the generic `ERR_RESOURCE_NOT_FOUND` (HTTP
    404)."

    Design: Corner/errors/unknown_secondary_resource_ids_return_404_resource_not_found
    """
    reset_clock(api)

    for response in (
        api.get_notice(UNKNOWN_NOTICE_UUID, ADMIN),
        api.get_access_consequence(UNKNOWN_CONSEQUENCE_UUID, ADMIN),
        api.get_intervention(UNKNOWN_INTERVENTION_UUID, ADMIN),
        api.get_incident(UNKNOWN_INCIDENT_UUID, ANALYST),
    ):
        validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND.value,
                       expected_status=404)

    # An empty collection is a 200 with no rows, never a 404.
    assert validate_success(api.list_notices({}, ADMIN)) == []
    assert validate_success(api.list_access_consequences({}, ADMIN)) == []
    assert validate_success(api.list_interventions({}, ADMIN)) == []
    assert validate_success(api.list_incidents({}, ANALYST)) == []


def test_the_send_instant_must_be_strictly_later_than_the_clock(api):
    """One second past the clock is legal; the clock instant itself is not.

    PRD §3.8: "First, `scheduled_send_at` must be strictly later than the current
    logical clock; an instant equal to or earlier than the clock is refused with
    `ERR_SCHEDULE_IN_PAST` (HTTP 422)."

    Design: Corner/errors/schedule_in_the_past_returns_422_schedule_in_past
    """
    reset_clock(api)
    set_clock(api, "2026-08-10T12:00:00Z")
    employee = register_employee(
        api, email="pat.past@corp.example", full_name="Pat Past",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2018-03-03",
    )
    ctx = approved_campaign(
        api, name="Past Schedule Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
        template_overrides={
            "name": "Past Probe Template",
            "pretext_category": "PACKAGE_DELIVERY",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    campaign_id = ctx["campaign"]["id"]
    version = ctx["campaign"]["version"]

    validate_error(
        api.schedule_campaign(
            campaign_id, schedule_payload("2026-08-09T12:00:00Z", version), AUTHOR),
        ApiErrorId.SCHEDULE_IN_PAST.value,
        expected_status=422,
    )
    validate_error(
        api.schedule_campaign(
            campaign_id, schedule_payload("2026-08-10T12:00:00Z", version), AUTHOR),
        ApiErrorId.SCHEDULE_IN_PAST.value,
        expected_status=422,
    )

    # Neither refusal bumped the version, so the same expectation still matches.
    scheduled = validate_success(
        api.schedule_campaign(
            campaign_id, schedule_payload("2026-08-10T12:00:01Z", version), AUTHOR))
    assert scheduled["state"] == CAMPAIGN_SCHEDULED
    assert_instant_equals(scheduled["scheduled_send_at"], "2026-08-10T12:00:01Z",
                          "scheduled_send_at")

    rows = validate_success(api.list_deliveries({"campaign_id": campaign_id}, ADMIN))
    assert len(rows) == 1
    assert rows[0]["employee_id"] == employee["id"]
    assert_delivery(rows[0], state=DELIVERY_QUEUED)


def test_the_two_report_period_defects_land_on_different_identifiers(api):
    """A 29-month span is a domain refusal; a zero-length span is malformed.

    PRD §3.10: "The requested span may cover at most 24 calendar months; a longer
    span is refused with `ERR_REPORT_PERIOD_INVALID` (HTTP 422), whereas a
    `period_end` that is not after `period_start` is caught by the earlier
    well-formedness check and returns `ERR_INVALID_REQUEST` (HTTP 400)."

    PRD §3.10: "If fewer than 2 pairs survive, or if either of the two paired series
    has zero variance, the `correlation` is `null` and a `correlation_reason_code` of
    `INSUFFICIENT_PAIRS` or `ZERO_VARIANCE` respectively explains why."

    Design: Corner/errors/report_period_span_over_24_months_returns_422
    """
    reset_clock(api)

    validate_error(
        api.get_effectiveness_report(
            effectiveness_params("2024-01-01T00:00:00Z", "2026-06-01T00:00:00Z"),
            ANALYST,
        ),
        ApiErrorId.REPORT_PERIOD_INVALID.value,
        expected_status=422,
    )
    validate_error(
        api.get_effectiveness_report(
            effectiveness_params("2026-03-01T00:00:00Z", "2026-03-01T00:00:00Z"),
            ANALYST,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        expected_status=400,
    )

    report = validate_success(
        api.get_effectiveness_report(
            effectiveness_params("2024-07-01T00:00:00Z", "2026-06-01T00:00:00Z"),
            ANALYST,
        )
    )
    assert report["variant"] == REPORT_VARIANT_CONCURRENT
    assert report["pair_count"] == 0
    assert report["correlation"] is None
    assert report["correlation_reason_code"] == CORRELATION_INSUFFICIENT_PAIRS
    assert report["total_incidents"] == 0


def test_two_non_draft_origins_collapse_onto_one_template_state_error(api):
    """A second approve and a second block both report the same identifier.

    PRD §3.7: "It requires the `review_state` to be `DRAFT` and requires
    `harmful_flag_hits` to be empty; on success the template moves `DRAFT →
    APPROVED_FOR_USE` and its `version` is bumped. ... while a template that is not
    in `DRAFT` produces `ERR_TEMPLATE_STATE_INVALID`."

    PRD §3.7: "both variants record the supplied `blocked_reason` and bump
    `version`, and both check only that the template is not already `BLOCKED`, since
    `BLOCKED` is terminal."

    Design: Corner/errors/template_approved_twice_returns_409_template_state_invalid
    """
    reset_clock(api)
    approved = create_template(
        api, AUTHOR, name="Approved Once Template",
        pretext_category="SHARED_DOCUMENT", difficulty_tier=TIER_1,
        theme_tags=["CURIOSITY"], credential_capture_enabled=False,
    )
    approved = validate_success(api.approve_template_for_use(approved["id"], APPROVER))
    assert approved["review_state"] == TEMPLATE_APPROVED_FOR_USE

    blocked_source = create_template(
        api, ADMIN, name="Blocked Once Template",
        pretext_category="IT_PASSWORD_RESET", difficulty_tier=TIER_1,
        theme_tags=["URGENCY"], credential_capture_enabled=False,
    )
    first_reason = "Lure overlaps an active real-world campaign."
    blocked = validate_success(
        api.block_template(blocked_source["id"], {"blocked_reason": first_reason},
                           ADMIN))
    assert blocked["review_state"] == TEMPLATE_BLOCKED

    validate_error(
        api.approve_template_for_use(approved["id"], APPROVER),
        ApiErrorId.TEMPLATE_STATE_INVALID.value,
        expected_status=409,
    )
    unchanged = validate_success(api.get_template(approved["id"], APPROVER))
    assert unchanged["review_state"] == TEMPLATE_APPROVED_FOR_USE
    assert unchanged["version"] == approved["version"]

    validate_error(
        api.block_template(blocked_source["id"],
                           {"blocked_reason": "Second block attempt."}, ADMIN),
        ApiErrorId.TEMPLATE_STATE_INVALID.value,
        expected_status=409,
    )
    # BLOCKED is terminal, so it is not a route back to usable either.
    validate_error(
        api.approve_template_for_use(blocked_source["id"], APPROVER),
        ApiErrorId.TEMPLATE_STATE_INVALID.value,
        expected_status=409,
    )
    still_blocked = validate_success(api.get_template(blocked_source["id"], ADMIN))
    assert still_blocked["review_state"] == TEMPLATE_BLOCKED
    assert still_blocked["blocked_reason"] == first_reason


def test_an_intervention_can_be_closed_only_once_coaching_is_complete(api):
    """Closing an OPEN intervention and double-assigning coaching share one code.

    PRD §3.10: "Attempting to assign coaching to an intervention that already has
    coaching is refused with `ERR_INTERVENTION_STATE_INVALID`, as is closing an
    intervention whose state is anything other than `COACHING_COMPLETED`."

    Design: Corner/errors/intervention_closed_before_coaching_completed_returns_409
    """
    reset_clock(api)
    coaching_module = create_published_module(
        api, code="IV-REM", title="Intervention Coaching", module_type="REMEDIAL")
    ctx = repeat_clicker_at_tier_two(api, department="SALES",
                                     hire_date="2016-08-08")
    intervention = ctx["intervention"]
    assert intervention["state"] == INTERVENTION_OPEN

    validate_error(
        api.close_intervention(
            intervention["id"], {"resolution_code": "COACHING_DELIVERED"}, ADMIN),
        ApiErrorId.INTERVENTION_STATE_INVALID.value,
        expected_status=409,
    )

    assigned = validate_success(
        api.assign_coaching(intervention["id"],
                            {"module_id": coaching_module["id"]}, ADMIN))
    assert assigned["state"] == INTERVENTION_COACHING_ASSIGNED
    assert assigned["coaching_assignment_id"] is not None

    validate_error(
        api.assign_coaching(intervention["id"],
                            {"module_id": coaching_module["id"]}, ADMIN),
        ApiErrorId.INTERVENTION_STATE_INVALID.value,
        expected_status=409,
    )
    final = validate_success(api.get_intervention(intervention["id"], ADMIN))
    assert final["coaching_assignment_id"] == assigned["coaching_assignment_id"]

    remedial_rows = validate_success(
        api.list_assignments(
            {"employee_id": ctx["employee"]["id"], "assignment_reason": "REMEDIAL"},
            ADMIN,
        )
    )
    assert ids_of(remedial_rows) == [assigned["coaching_assignment_id"]]
