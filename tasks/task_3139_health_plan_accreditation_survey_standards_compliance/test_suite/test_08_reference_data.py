"""Reference data: health plans, editions, elements, scopes, surveyors
(PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assert_health_plan,
    assert_standards_edition,
    assert_surveyor,
    create_edition,
    create_plan,
    create_scope,
    get_success_data,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    make_platform_admin_headers,
    make_public_viewer_headers,
    set_clock,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import api_client


def _admin():
    return make_platform_admin_headers()


def _officer():
    return make_accreditation_officer_headers()


def _public():
    return make_public_viewer_headers()


def test_health_plan_create_returns_system_fields_and_active_status(api):
    """PRD §3.2: "New plans begin `ACTIVE`." PRD §2.4: "The `id` is a
    server-minted UUID with no type prefix. The `created_at` and `updated_at`
    fields are ISO 8601 UTC timestamps rendered with three fractional digits".

    Design: Corner/entities/health_plan_create_returns_system_fields_and_active_status
    """
    set_clock()
    r = api_client.create_health_plan(
        {"name": "Meridian Health Alliance", "plan_code": "MHA-01"}, _admin())
    data = validate_success(r, expected_status=201)
    assert_health_plan(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_health_plan_duplicate_plan_code_rejected(api):
    """PRD §3.2: "the code must be unique across all health plans, with
    duplicates rejected as `ERR_PLAN_CODE_DUPLICATE`."

    Design: Corner/entities/health_plan_duplicate_plan_code_rejected
    """
    create_plan(plan_code="MHA-DUP")
    r = api_client.create_health_plan(
        {"name": "Copycat Health", "plan_code": "MHA-DUP"}, _admin())
    validate_error(r, ApiErrorId.ERR_PLAN_CODE_DUPLICATE)
    assert r.status_code == 409


def test_health_plan_get_not_found(api):
    """PRD §2.8: "the server validates each identifier's existence in
    left-to-right order along the path, returning the entity-specific 404 error
    for the first segment that does not resolve."

    Design: Corner/entities/health_plan_get_not_found
    """
    r = api_client.get_health_plan("00000000-0000-4000-8000-000000000000", _admin())
    validate_error(r, ApiErrorId.ERR_HEALTH_PLAN_NOT_FOUND)
    assert r.status_code == 404


def test_health_plan_list_pagination_envelope(api):
    """PRD §2.3: "when omitted it defaults to 10, with a minimum accepted value
    of 1 and a maximum accepted value of 100. The `offset` parameter specifies
    the number of items to skip and defaults to 0." and "List responses carry
    the four pagination fields `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the response envelope."

    Design: Corner/entities/health_plan_list_pagination_envelope
    """
    create_plan(code_suffix="01")
    create_plan(name="Cascade Peak Health", code_suffix="02")
    create_plan(name="Rio Verde Plan", code_suffix="03")

    r = api_client.list_health_plans(_public())
    data, meta = validate_paginated(r)
    assert len(data) == 3
    assert meta["total_count"] == 3
    assert meta["limit"] == 10, "default limit"
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_standards_edition_get_round_trips_configuration(api):
    """PRD §3.1: "A `PlatformAdmin` authors a standards cycle by creating a `StandardsEdition`, supplying an `edition_year` (unique across all editions; duplicates are rejected with `ERR_EDITION_YEAR_DUPLICATE`), an `effective_from` timestamp marking the start of the edition's effective window (inclusive), an `effective_until` timestamp marking the end of the window (inclusive and strictly after `effective_from`), a `min_file_sample_per_category` integer of at least 1 (the floor that every file review sample created under applications on this edition must respect), and a `timeliness_threshold` strictly greater than 0 and at most 1 (the pass threshold a sample's `timeliness_rate` must reach)."
    PRD §3.1: "New editions begin in `DRAFT` status."

    Design: Corner/entities/standards_edition_get_round_trips_configuration
    """
    edition, _ = create_edition(publish=False)
    r = api_client.get_standards_edition(edition["id"], _officer())
    data = validate_success(r)
    assert_standards_edition(data)
    assert data["edition_year"] == 2026
    assert data["min_file_sample_per_category"] == 5
    assert data["timeliness_threshold"] == 0.9
    assert data["status"] == "DRAFT"
    assert data["version"] == 1


def test_standard_element_create_missing_required_field(api):
    """PRD §2.5 item 5: "required fields present, types correct, enum values in
    the declared set, string lengths and numeric ranges within declared
    constraints (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/standard_element_create_missing_required_field
    """
    edition, _ = create_edition(publish=False)
    r = api_client.create_standard_element(
        edition["id"],
        {"category": "UM", "max_points": 4, "is_must_pass": True,
         "evidence_required_count": 2},
        _admin())
    validate_error(r, ApiErrorId.ERR_INVALID_REQUEST)
    assert r.status_code == 400


def test_standard_element_invalid_category_enum_rejected(api):
    """PRD §2.10: "A `StandardElement` declares a `category` of `UM`
    (utilization management), `CR` (credentialing), `MRR` (member rights and
    responsibilities), or `QI` (quality improvement)." PRD §2.5 item 5:
    "enum values in the declared set (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/standard_element_invalid_category_enum_rejected
    """
    edition, _ = create_edition(publish=False)
    r = api_client.create_standard_element(
        edition["id"],
        {"element_code": "X-1", "category": "DENTAL", "max_points": 4,
         "is_must_pass": False, "evidence_required_count": 0},
        _admin())
    validate_error(r, ApiErrorId.ERR_INVALID_REQUEST)
    assert r.status_code == 400


def test_product_line_scope_duplicate_product_line_rejected(api):
    """PRD §3.2: "A plan may not register the same product line twice — a second
    scope for the same (plan, product line) pair is rejected with
    `ERR_PRODUCT_LINE_DUPLICATE`."

    Design: Corner/entities/product_line_scope_duplicate_product_line_rejected
    """
    plan_a = create_plan(code_suffix="A")
    create_scope(plan_a["id"], product_line="COMMERCIAL", state_codes=["OR"],
                 member_count=50000)
    plan_b = create_plan(name="Rio Verde Plan", code_suffix="B")

    r = api_client.create_product_line_scope(
        plan_a["id"],
        {"product_line": "COMMERCIAL", "state_codes": ["WA"], "member_count": 1000},
        make_plan_coordinator_headers(plan_a["id"]))
    validate_error(r, ApiErrorId.ERR_PRODUCT_LINE_DUPLICATE)
    assert r.status_code == 409

    # The same product_line on a DIFFERENT plan succeeds.
    ok = api_client.create_product_line_scope(
        plan_b["id"],
        {"product_line": "COMMERCIAL", "state_codes": ["TX"], "member_count": 2000},
        make_plan_coordinator_headers(plan_b["id"]))
    validate_success(ok, expected_status=201)


def test_application_create_scope_plan_mismatch(api):
    """PRD §3.3: "The scope named must belong to the path's health plan;
    otherwise `ERR_SCOPE_PLAN_MISMATCH`."

    Design: Corner/entities/application_create_scope_plan_mismatch
    """
    edition, _ = create_edition(publish=True)
    plan_a = create_plan(code_suffix="A")
    scope_a = create_scope(plan_a["id"])
    plan_b = create_plan(name="Rio Verde Plan", code_suffix="B")

    r = api_client.create_application(
        plan_b["id"],
        {"product_line_scope_id": scope_a["id"],
         "standards_edition_id": edition["id"],
         "review_period_start": TEST_DEFAULTS["REVIEW_PERIOD_START"],
         "review_period_end": TEST_DEFAULTS["REVIEW_PERIOD_END"]},
        make_plan_coordinator_headers(plan_b["id"]))
    validate_error(r, ApiErrorId.ERR_SCOPE_PLAN_MISMATCH)
    assert r.status_code == 422


def test_application_create_invalid_review_period(api):
    """PRD §3.3: "`review_period_end` must be strictly after
    `review_period_start`, otherwise `ERR_REVIEW_PERIOD_INVALID`".

    Design: Corner/entities/application_create_invalid_review_period
    """
    edition, _ = create_edition(publish=True)
    plan = create_plan()
    scope = create_scope(plan["id"])

    r = api_client.create_application(
        plan["id"],
        {"product_line_scope_id": scope["id"],
         "standards_edition_id": edition["id"],
         "review_period_start": "2025-06-01T00:00:00Z",
         "review_period_end": "2025-06-01T00:00:00Z"},
        make_plan_coordinator_headers(plan["id"]))
    validate_error(r, ApiErrorId.ERR_REVIEW_PERIOD_INVALID)
    assert r.status_code == 422


def test_file_review_sample_derives_category_from_type(api):
    """PRD §3.4: "The sample's `category` is derived from its type at creation:
    a `DENIAL` sample belongs to `UM`, an `APPEAL` sample belongs to `UM`, and a
    `CREDENTIALING` sample belongs to `CR`. New samples begin `OPEN` with
    `timely_case_count` 0, `timeliness_rate` null, and
    `must_pass_threshold_breached` false."

    Design: Corner/entities/file_review_sample_derives_category_from_type
    """
    from test_helpers import setup_evidence_review
    ctx = setup_evidence_review()
    r = api_client.create_file_review_sample(
        ctx["app"]["id"],
        {"sample_type": "CREDENTIALING", "required_size": 5,
         "timeliness_basis": "DECISION_DATE"},
        _officer())
    data = validate_success(r, expected_status=201)
    assert data["category"] == "CR"
    assert data["status"] == "OPEN"
    assert data["timeliness_rate"] is None
    assert data["timely_case_count"] == 0
    assert data["must_pass_threshold_breached"] is False


def test_survey_frozen_cap_closure_rate_defaults_null_for_full(api):
    """PRD §3.5: "starts the survey in `PLANNED` with `frozen_cap_closure_rate`
    null" and "For a `RESURVEY` survey, ... the survey freezes its
    `frozen_cap_closure_rate` at this instant" — only a RESURVEY populates the
    frozen rate; a FULL survey's stays null even after confirm.

    Design: Corner/entities/survey_frozen_cap_closure_rate_defaults_null_for_full
    """
    from test_helpers import add_session, confirm_survey, setup_planned_full_survey
    ctx = setup_planned_full_survey()
    add_session(ctx["survey"]["id"], ctx["surveyor"]["id"])
    confirmed = confirm_survey(ctx["survey"]["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["frozen_cap_closure_rate"] is None, "FULL survey"


def test_surveyor_active_field_is_system_default_true(api):
    """PRD §3.2: "The `active` flag on a surveyor is always `true` and retained
    for roster display purposes; it never transitions."

    Design: Corner/entities/surveyor_active_field_is_system_default_true
    """
    r = api_client.create_surveyor(
        {"name": "Pat Staff", "credential_level": "STAFF"}, _admin())
    data = validate_success(r, expected_status=201)
    assert_surveyor(data)
    assert data["active"] is True
    assert data["version"] == 1


def test_element_score_computed_fields_ignore_client_values(api):
    """PRD §3.7: "The new score carries a `scoring_basis` of `FILE_REVIEW` when
    the application has never completed a `RESURVEY` survey" and "when the
    category has no `SCORED` sample, the sample rate is null and
    `sample_rate_used` is null" and "the provisional variant treats the
    confirmed gap count as 0 ... so `gap_count_used` is 0 while the score is
    `PROVISIONAL`."

    Design: Corner/entities/element_score_computed_fields_ignore_client_values
    """
    from test_helpers import setup_evidence_review
    ctx = setup_evidence_review()
    r = api_client.create_element_score(
        ctx["app"]["id"], {"standard_element_id": ctx["elements"]["UM-1"]}, _officer())
    data = validate_success(r, expected_status=201)
    assert data["status"] == "PROVISIONAL"
    assert data["scoring_basis"] == "FILE_REVIEW"
    # No SCORED UM sample -> file round(4*0.6,2)=2.40; evidence 0/2 -> 0.00
    assert data["awarded_points"] == 2.40, f"awarded {data['awarded_points']}"
    assert data["forfeited_points"] == 1.60
    assert data["sample_rate_used"] is None
    assert data["evidence_count_used"] == 0
    assert data["gap_count_used"] == 0


def test_edition_starts_in_draft_and_publish_requires_element(api):
    """PRD §3.1: "Publishing moves the edition from `DRAFT` to `PUBLISHED` and
    is rejected with `ERR_EDITION_HAS_NO_ELEMENTS` when the edition still has
    zero elements; publishing from any state other than `DRAFT` is rejected with
    `ERR_EDITION_NOT_PUBLISHED`."

    Design: Corner/state_machines/edition_starts_in_draft_and_publish_requires_element
    """
    edition, _ = create_edition(publish=False, elements=[])
    r = api_client.publish_standards_edition(edition["id"], _admin())
    validate_error(r, ApiErrorId.ERR_EDITION_HAS_NO_ELEMENTS)
    assert r.status_code == 409

    get_success_data(api_client.create_standard_element(
        edition["id"],
        {"element_code": "UM-1", "category": "UM", "max_points": 4,
         "is_must_pass": True, "evidence_required_count": 2},
        _admin()))
    published = get_success_data(api_client.publish_standards_edition(edition["id"], _admin()))
    assert published["status"] == "PUBLISHED"


def test_question_adjudicate_twice_rejected(api):
    """PRD §3.6: "Adjudicating requires the question to be `LOGGED`; invoking it
    on an already-adjudicated question returns `ERR_QUESTION_ALREADY_ADJUDICATED`."

    Design: Corner/state_machines/question_adjudicate_twice_rejected
    """
    from test_helpers import (
        add_session,
        adjudicate_question,
        confirm_survey,
        log_question,
        setup_planned_full_survey,
    )
    ctx = setup_planned_full_survey()
    session = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"])
    confirm_survey(ctx["survey"]["id"])
    q = log_question(session["id"], ctx["surveyor"]["id"], ctx["elements"]["UM-1"],
                     "probe")
    first = adjudicate_question(q["id"], False)
    assert first["status"] == "ADJUDICATED"
    assert first["gap_confirmed"] is False

    r = api_client.adjudicate_surveyor_question(q["id"], {"gap_confirmed": True},
                                                _officer())
    validate_error(r, ApiErrorId.ERR_QUESTION_ALREADY_ADJUDICATED)
    assert r.status_code == 409
    after = get_success_data(api_client.get_surveyor_question(q["id"], _officer()))
    assert after["gap_confirmed"] is False, "the first adjudication stands"


def test_score_finalize_from_final_rejected(api):
    """PRD §3.7: "Finalizing requires the score to be `PROVISIONAL` (otherwise
    `ERR_SCORE_NOT_PROVISIONAL`)"."

    Design: Corner/state_machines/score_finalize_from_final_rejected
    """
    from test_helpers import create_score, finalize_score, setup_scoring
    ctx = setup_scoring()
    score = create_score(ctx["app"]["id"], ctx["elements"]["UM-1"])
    finalize_score(score["id"])

    r = api_client.finalize_element_score(score["id"], _officer())
    validate_error(r, ApiErrorId.ERR_SCORE_NOT_PROVISIONAL)
    assert r.status_code == 409


def test_plan_retire_blocked_by_active_application(api):
    """PRD §3.2: "no `AccreditationApplication` of the plan may be in a
    non-terminal status — that is, every application must be either `WITHDRAWN`
    or `CLOSED` — otherwise the retire is rejected with
    `ERR_ACTIVE_APPLICATIONS_EXIST`."

    Design: Corner/endpoints/plan_retire_blocked_by_active_application
    """
    ctx = setup_base()
    plan_id = ctx["plan"]["id"]

    r = api_client.retire_health_plan(plan_id, _admin())
    validate_error(r, ApiErrorId.ERR_ACTIVE_APPLICATIONS_EXIST)
    assert r.status_code == 409

    get_success_data(api_client.withdraw_application(
        ctx["app"]["id"], make_plan_coordinator_headers(plan_id)))
    retired = get_success_data(api_client.retire_health_plan(plan_id, _admin()))
    assert retired["status"] == "RETIRED"
