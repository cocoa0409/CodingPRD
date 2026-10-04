"""Corner coverage: entity-level claims.

Program config defaults, required fields, uniqueness, weight snapshots
across frame replacement, report birth state, not-found errors on read and
action paths, pagination/filtering, and the fixed error envelope.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_program,
    assert_same_instant,
    create_cycle,
    create_enrollment_payload,
    create_establishment_payload,
    create_frame,
    create_program,
    create_program_payload,
    create_stratum,
    enroll,
    freeze_frame,
    get_enrollment,
    lifecycle,
    open_collection,
    register_establishment,
    set_clock,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COLLECTOR = TEST_USERS["collection_officer_headers"]
ANALYST = TEST_USERS["estimation_analyst_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]
METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]


def test_program_create_applies_config_defaults(api):
    """PRD §3.1: "two optional policy knobs: `embargo_window_minutes`, the number of minutes before a release's publication instant when the media embargo window opens, defaulting to 30 and accepting values from 1 to 1440; and `annual_burden_budget_minutes`, the per-establishment reporting burden cap applied per calendar year, defaulting to 120 and never configurable below 15."
    PRD §3.1: "A new program is created with `version` 1."

    Design: Corner/entities/program_create_applies_config_defaults
    """
    program = create_program(code="CES", sample_budget=3)
    assert_program(program)
    assert program["embargo_window_minutes"] == 30, "default applied"
    assert program["annual_burden_budget_minutes"] == 120, "default applied"
    assert program["version"] == 1


def test_program_create_missing_code_rejected(api):
    """PRD §2.8 (stage 5): "Required fields are present; enum values are valid; the `YYYY-Qn`, `YYYY-MM`, and ISO 8601 formats hold; ... Violations are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/program_create_missing_code_rejected
    """
    resp = api_client.create_program(
        {"name": "No Code Program", "sample_budget": 3}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)  # 400


def test_duplicate_establishment_ein_rejected(api):
    """PRD §3.2: "The `ein` is unique across establishments; re-registering one is rejected with `ERR_DUPLICATE_ESTABLISHMENT`"

    Design: Corner/entities/duplicate_establishment_ein_rejected
    """
    register_establishment(ein="11-0000001", name="Alpha")
    resp = api_client.create_establishment(
        create_establishment_payload(ein="11-0000001", name="Alpha Clone",
                                     industry_code="RETAIL",
                                     size_class="LARGE"),
        COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ESTABLISHMENT)  # 409


def test_enrollment_weight_snapshot_survives_frame_replacement(api):
    """PRD §3.1: "Replacement does not reweight anything downstream: enrollments already created keep the `base_weight` snapshot they were born with."
    PRD §3.2: "Its `base_weight` — the design weight used throughout estimation — is computed immediately from the matching stratum of the program's latest `FROZEN` frame: the stratum's `frame_unit_count` divided by its `allocated_sample_size`, rounded half up to 6 decimal places."
    PRD §3.1: "A successful replacement moves the named frame — whether `DRAFT` or `FROZEN` — to `SUPERSEDED` and records the successor in its `replaced_by_frame_id`."

    Design: Corner/entities/enrollment_weight_snapshot_survives_frame_replacement
    """
    set_clock("2026-09-01T00:00:00Z")
    program, frame = setup_program_with_frozen_frame(
        code="CES", sample_budget=3,
        strata=[create_stratum("MANUFACTURING", "SMALL", 100)])
    e1 = register_establishment()
    e2 = register_establishment()
    en1 = enroll(e1["id"], "CES")
    assert en1["base_weight"] == 33.333333, "100/3 frozen-frame snapshot"

    # Replace F1 with a smaller stratum (n=50) and freeze the replacement.
    f2 = create_frame("CES", "2026-Q3",
                      strata=[create_stratum("MANUFACTURING", "SMALL", 50)],
                      replaces_frame_id=frame["id"])
    freeze_frame(f2["id"])

    en2 = enroll(e2["id"], "CES")
    assert en2["base_weight"] == 16.666667, (
        f"50/3 round_half_up to 6 decimals — new enrollments read the "
        f"replacement frame, got {en2['base_weight']}")
    assert get_enrollment(en1["id"])["base_weight"] == 33.333333, (
        "snapshot unchanged by frame replacement")

    old = api_client.get_sample_frame(frame["id"], ADMIN)
    old = validate_success(old)
    assert old["frame_status"] == "SUPERSEDED"
    assert old["replaced_by_frame_id"] == f2["id"]


def test_report_created_in_submitted_initial_state(api):
    """PRD §3.3: "The report is created directly in `SUBMITTED` status, with `submit_count` set to 1 and `submitted_at` stamped from the logical clock."
    PRD §3.3: "Every submission event — the initial create and each resubmission after a return — adds 15 minutes to the enrollment's burden ledger under the rollover rule of §3.4."

    Design: Corner/entities/report_created_in_submitted_initial_state
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)  # clock pinned at 2026-09-01T00:00:00Z

    report = submit_report(en1, cycle["id"], 9)
    assert report["report_status"] == "SUBMITTED"
    assert report["submit_count"] == 1
    assert_same_instant(report["submitted_at"], "2026-09-01T00:00:00Z"), (
        "logical clock, not wall clock")
    assert get_enrollment(en1["id"])["burden_minutes_ytd"] == 15


def test_missing_entities_return_404_on_read_paths(api):
    """PRD §2.8 (stage 3): "Each resource identifier in the request path must resolve: a program, frame, establishment, enrollment, cycle, report, case, estimate, factor set, benchmark run, notice, release, outlet, or grant that does not exist is rejected with its dedicated not-found error"

    Design: Corner/entities/missing_entities_return_404_on_read_paths
    """
    resp = api_client.get_release(
        "11111111-1111-4111-8111-111111111111", RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_FOUND)
    resp = api_client.get_grant(
        "22222222-2222-4222-8222-222222222222", RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_FOUND)
    resp = api_client.get_cell_estimate(
        "33333333-3333-4333-8333-333333333333", ANALYST)
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_FOUND)
    resp = api_client.get_enrollment(
        "44444444-4444-4444-8444-444444444444", COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)  # all 404


def test_missing_entities_return_404_on_action_paths(api):
    """PRD §2.8 (stage 4): "Resources referenced in the request body must resolve: `program_code` must name an existing program (`ERR_PROGRAM_NOT_FOUND`), `enrollment_id` an existing enrollment (`ERR_ENROLLMENT_NOT_FOUND`), `cycle_id` an existing cycle (`ERR_CYCLE_NOT_FOUND`), and `replaces_frame_id` an existing frame (`ERR_FRAME_NOT_FOUND`) — each HTTP 404."
    PRD §3.2: "a reference to an unknown establishment id is rejected with `ERR_ESTABLISHMENT_NOT_FOUND`"

    Design: Corner/entities/missing_entities_return_404_on_action_paths
    """
    create_program(code="CES", sample_budget=3)
    cases = [
        (api_client.advance_cycle(
            "11111111-1111-4111-8111-111111111111",
            {"action": "OPEN_COLLECTION"}, COLLECTOR),
         ApiErrorId.ERR_CYCLE_NOT_FOUND),
        (api_client.advance_follow_up_case(
            "22222222-2222-4222-8222-222222222222",
            {"action": "ESCALATE"}, COLLECTOR),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        (api_client.finalize_factor_set(
            "33333333-3333-4333-8333-333333333333", METHODOLOGIST),
         ApiErrorId.ERR_FACTOR_SET_NOT_FOUND),
        (api_client.apply_benchmark_run(
            "44444444-4444-4444-8444-444444444444", METHODOLOGIST),
         ApiErrorId.ERR_BENCHMARK_NOT_FOUND),
        (api_client.advance_notice(
            "55555555-5555-4555-8555-555555555555",
            {"action": "ANNOUNCE"}, METHODOLOGIST),
         ApiErrorId.ERR_NOTICE_NOT_FOUND),
        (api_client.freeze_sample_frame(
            "66666666-6666-4666-8666-666666666666", ADMIN),
         ApiErrorId.ERR_FRAME_NOT_FOUND),
        (api_client.outlet_accreditation(
            "77777777-7777-4777-8777-777777777777",
            {"action": "ACCREDIT"}, RELEASE_MANAGER),
         ApiErrorId.ERR_OUTLET_NOT_FOUND),
        (api_client.advance_report(
            "88888888-8888-4888-8888-888888888888",
            {"action": "ACCEPT"}, COLLECTOR),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api_client.create_cycle(
            {"program_code": "NOPE", "reference_month": "2026-09"}, ADMIN),
         ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (api_client.create_enrollment(
            create_enrollment_payload(
                "99999999-9999-4999-8999-999999999999", "CES"), COLLECTOR),
         ApiErrorId.ERR_ESTABLISHMENT_NOT_FOUND),
    ]
    for resp, error_id in cases:
        validate_error(resp, error_id)  # each 404 with its dedicated id


def test_list_pagination_and_status_filtering(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0."
    PRD §2.3: "Enrollments filter by `establishment_id`, `program_code`, and `enrollment_status`"

    Design: Corner/entities/list_pagination_and_status_filtering
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    e1 = register_establishment()
    e2 = register_establishment()
    e3 = register_establishment()
    en1 = lifecycle(enroll(e1["id"], "CES"), "ACCEPT")
    enroll(e2["id"], "CES")  # stays INVITED
    enroll(e3["id"], "CES")  # stays INVITED

    page1, meta1 = validate_paginated(api_client.list_enrollments(
        COLLECTOR, params={"program_code": "CES", "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(api_client.list_enrollments(
        COLLECTOR, params={"program_code": "CES", "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    rows, meta3 = validate_paginated(api_client.list_enrollments(
        COLLECTOR, params={"program_code": "CES",
                           "enrollment_status": "ENROLLED"}))
    assert meta3["total_count"] == 1 and rows[0]["id"] == en1["id"], (
        "status filter narrows to the matching subset")


def test_error_envelope_shape_is_fixed(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/error_envelope_shape_is_fixed
    """
    resp = api_client.get_release(
        "11111111-1111-4111-8111-111111111111", RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"]
    assert isinstance(body["data"].get("message"), str)
    assert body["data"]["message"].strip(), "message is a non-empty string"
