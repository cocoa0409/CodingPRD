"""Validation layers, auth, OCC, and cross-entity integrity (PRD §2.5, §2.6)."""
from test_helpers import (
    ApiErrorId,
    create_edition,
    create_plan,
    create_scope,
    create_application,
    get_app,
    get_success_data,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    make_platform_admin_headers,
    make_surveyor_headers,
    set_clock,
    setup_base,
    setup_planned_full_survey,
    submit_application,
    validate_error,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import api_client


def _officer():
    return make_accreditation_officer_headers()


def _admin():
    return make_platform_admin_headers()


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside the five declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    r_no_role = api_client.list_health_plans({"X-User-ID": "someone"})
    validate_error(r_no_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert r_no_role.status_code == 400

    r_bad_role = api_client.list_health_plans(
        {"X-User-ID": "someone", "X-User-Role": "NoSuchRole"})
    validate_error(r_bad_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert r_bad_role.status_code == 400


def test_ownership_mismatch_plan_coordinator(api):
    """PRD §2.1: "Where ownership scope applies, a `PlanCoordinator` whose `X-User-ID` does not equal the owning health plan's `id` of the targeted resource, or a `Surveyor` whose `X-User-ID` does not equal the target session's `surveyor_id` on session complete or question log, is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/ownership_mismatch_plan_coordinator
    """
    plan_a = create_plan(code_suffix="A")
    plan_b = create_plan(name="Rio Verde Plan", code_suffix="B")
    r = api_client.create_product_line_scope(
        plan_a["id"],
        {"product_line": "MEDICAID", "state_codes": ["WA"], "member_count": 500},
        make_plan_coordinator_headers(plan_b["id"]),
    )
    validate_error(r, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert r.status_code == 403


def test_evidence_create_stale_version_returns_412(api):
    """PRD §2.6: "If the supplied value does not match the application's current
    `version` — because some other writer has advanced it since the client last
    read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)." and
    "adding an evidence item increments the application's `version` by 1 as a
    side effect, and the OCC check is what prevents a client with a superseded
    view of the application from layering evidence on top of a state it has not
    observed."

    Design: Corner/validations/evidence_create_stale_version_returns_412
    """
    ctx = setup_base()
    plan_id = ctx["plan"]["id"]
    submit_application(ctx["app"]["id"], plan_id)
    app_now = get_app(ctx["app"]["id"])
    observed_version = app_now["version"]

    first = api_client.create_evidence_item(
        ctx["app"]["id"],
        {"standard_element_id": ctx["elements"]["UM-1"], "title": "first",
         "expected_application_version": observed_version},
        make_plan_coordinator_headers(plan_id))
    get_success_data(first)

    # The first create bumped the version; replaying the observed value is stale.
    r = api_client.create_evidence_item(
        ctx["app"]["id"],
        {"standard_element_id": ctx["elements"]["UM-1"], "title": "stale",
         "expected_application_version": observed_version},
        make_plan_coordinator_headers(plan_id))
    validate_error(r, ApiErrorId.ERR_STALE_VERSION)
    assert r.status_code == 412

    from test_helpers import validate_paginated
    items, meta = validate_paginated(
        api_client.list_evidence_items_of_application(ctx["app"]["id"], _officer()))
    assert meta["total_count"] == 1, "only the first evidence item was stored"


def test_survey_create_stale_version_returns_412(api):
    """PRD §2.6: "creating a survey leaves the application's status untouched
    (the application only moves at confirm time) but still advances the
    application's `version`, and a stale `expected_application_version` is
    rejected."

    Design: Corner/validations/survey_create_stale_version_returns_412
    """
    ctx = setup_planned_full_survey()
    app_now = get_app(ctx["app"]["id"])
    # app_now's version already reflects the first survey create.
    stale_version = app_now["version"] - 1
    r = api_client.create_survey(
        ctx["app"]["id"],
        {"survey_type": "FULL", "mode": "ONSITE", "start_date": "2026-10-12",
         "end_date": "2026-10-16", "budgeted_surveyor_hours": 4,
         "expected_application_version": stale_version},
        _officer())
    validate_error(r, ApiErrorId.ERR_STALE_VERSION)
    assert r.status_code == 412


def test_existence_checked_before_state(api):
    """PRD §2.8: "the server validates each identifier's existence in
    left-to-right order along the path, returning the entity-specific 404 error
    for the first segment that does not resolve." PRD §2.5 lists path existence
    (item 4) before state-machine preconditions (item 7).

    Design: Corner/validations/existence_checked_before_state
    """
    r = api_client.complete_survey_session(
        NON_EXISTENT_UUID, make_surveyor_headers("00000000-0000-4000-8000-000000000001"))
    validate_error(r, ApiErrorId.ERR_SURVEY_SESSION_NOT_FOUND)
    assert r.status_code == 404


def test_case_create_zero_turnaround_rejected(api):
    """PRD §3.4: "a `required_turnaround_days` integer of at least 1 (a value
    below 1 is rejected with `ERR_INVALID_TURNAROUND_DAYS`, HTTP 422)."

    Design: Corner/validations/case_create_zero_turnaround_rejected
    """
    from test_helpers import add_case, create_sample, setup_evidence_review
    ctx = setup_evidence_review()
    sample = create_sample(ctx["app"]["id"])
    r = api_client.create_file_review_case(
        sample["id"],
        {"case_reference": "T0", "service_date": "2025-03-01T00:00:00Z",
         "decision_date": "2025-03-10T00:00:00Z",
         "resolution_date": "2025-03-10T00:00:00Z", "required_turnaround_days": 0},
        make_plan_coordinator_headers(ctx["plan"]["id"]))
    validate_error(r, ApiErrorId.ERR_INVALID_TURNAROUND_DAYS)
    assert r.status_code == 422


def test_sample_size_below_edition_minimum(api):
    """PRD §3.4: "The `required_size` must be at least the owning edition's
    `min_file_sample_per_category`; a smaller value is rejected with
    `ERR_SAMPLE_SIZE_BELOW_MINIMUM` (HTTP 422)."

    Design: Corner/validations/sample_size_below_edition_minimum
    """
    from test_helpers import setup_evidence_review
    ctx = setup_evidence_review()
    r = api_client.create_file_review_sample(
        ctx["app"]["id"],
        {"sample_type": "DENIAL", "required_size": 4, "timeliness_basis": "DECISION_DATE"},
        _officer())
    validate_error(r, ApiErrorId.ERR_SAMPLE_SIZE_BELOW_MINIMUM)
    assert r.status_code == 422


def test_duplicate_active_application_rejected(api):
    """PRD §3.3: "no other application may already exist for the same
    (`product_line_scope_id`, `standards_edition_id`) pair in a non-terminal
    status, meaning a status other than `WITHDRAWN` or `CLOSED` (otherwise
    `ERR_DUPLICATE_ACTIVE_APPLICATION`)."

    Design: Corner/validations/duplicate_active_application_rejected
    """
    ctx = setup_base()
    plan_id = ctx["plan"]["id"]
    submit_application(ctx["app"]["id"], plan_id)

    app2 = create_application(plan_id, ctx["scope"]["id"], ctx["edition"]["id"])
    r = api_client.submit_application(
        app2["id"], {"expected_application_version": app2["version"]},
        make_plan_coordinator_headers(plan_id))
    validate_error(r, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION)
    assert r.status_code == 409

    # Once the first application is withdrawn (terminal), the second submits.
    get_success_data(api_client.withdraw_application(
        ctx["app"]["id"], make_plan_coordinator_headers(plan_id)))
    app2_now = get_app(app2["id"])
    resubmitted = get_success_data(api_client.submit_application(
        app2["id"], {"expected_application_version": app2_now["version"]},
        make_plan_coordinator_headers(plan_id)))
    assert resubmitted["status"] == "SUBMITTED"


def test_element_edition_mismatch_on_score_create(api):
    """PRD §3.7: "The element named must belong to the application's edition
    (otherwise `ERR_ELEMENT_EDITION_MISMATCH`)."

    Design: Corner/errors_coverage_sweep/element_edition_mismatch_on_score_create
    """
    from test_helpers import setup_evidence_review
    ctx = setup_evidence_review()
    _els_2027_unused, els_2027 = create_edition(
        publish=False,
        elements=[{"element_code": "UM-1", "category": "UM", "max_points": 4,
                   "is_must_pass": True, "evidence_required_count": 1}],
        edition_year=2027,
        effective_from="2027-01-01T00:00:00Z",
        effective_until="2028-12-31T23:59:59Z",
    )
    r = api_client.create_element_score(
        ctx["app"]["id"], {"standard_element_id": els_2027["UM-1"]}, _officer())
    validate_error(r, ApiErrorId.ERR_ELEMENT_EDITION_MISMATCH)
    assert r.status_code == 422
