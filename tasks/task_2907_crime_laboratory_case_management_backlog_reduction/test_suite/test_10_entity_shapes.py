"""The shape of the persisted rows themselves: derived fields computed at creation, declared
defaults applied when optional inputs are omitted, schema refusals that mint nothing, and the
collection filters that read the rows back.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_ANALYST_NOT_FOUND,
    ERR_CASE_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (
    assert_absent,
    assert_fields,
    assert_immutable_entity,
    assert_instant_equals,
    assert_list_meta,
    collect_ids,
)
from test_helpers.assertions import assert_workload
from test_helpers.factories import (
    analyst_payload,
    case_payload,
    evidence_item_payload,
    technical_review_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_proficiency_test,
    assign_request,
    carry_to_tech_review,
    create_validated_method,
    log_evidence,
    raise_request,
    register_analyst,
    set_clock,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
    make_analyst_headers,
)

UNPERSISTED_ANALYST_ID = "00000000-0000-0000-0000-0000000000ff"
UNPERSISTED_CASE_ID = "00000000-0000-0000-0000-0000000000aa"


def test_a_minimal_other_category_submission_carries_both_state_axes(api):
    """An OTHER submission with no custody flag and no dates earns the bare category weight of
    4.00 with no temporal points, so it derives the routine queue class while reporting the
    casework axis and the discovery axis independently from the very first response.

    PRD §3.1: "On acceptance of the submission the server stamps `received_at_utc` from the
    logical clock — this instant is the baseline for priority tiers, backlog aging and turnaround
    alike — and sets `workflow_status` to `SUBMITTED` and `discovery_status` to `NONE`."

    Design: Corner/entities/case_creation_returns_derived_priority_and_both_state_axes
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    created = validate_success(
        api.create_case(
            case_payload(
                agency_case_number="O-2026-0001",
                submitting_agency="METRO PD",
                offense_category="OTHER",
            ),
            TECHNICIAN_HEADERS,
        ),
        201,
    )

    assert_fields(
        created,
        priority_score=4.00,
        priority_class="P3_ROUTINE",
        violent_crime_flag=False,
        suspect_in_custody=False,
        workflow_status="SUBMITTED",
        discovery_status="NONE",
        open_examination_request_count=0,
        released_examination_request_count=0,
        version=1,
    )
    assert_instant_equals(created["received_at_utc"], "2026-08-01T00:00:00Z", "received_at_utc")
    assert_absent(created, "gross_turnaround_days", "net_turnaround_days")


def test_omitted_optional_examiner_inputs_take_their_declared_defaults(api):
    """Omitting employment status, competency level and training hours leaves the examiner ACTIVE
    at level 1 with 0.00 training hours, so the whole thirty-hour week is available for casework
    and the casework-to-training ratio is pinned at 0.00 rather than divided by zero.

    PRD §3.4: "A third figure, `casework_training_ratio`, is 0.00 when `training_hours_per_week`
    is 0.00 and otherwise `projected_load_hours` divided by `training_hours_per_week`, rounded
    half up to 2 decimal places."

    Design: Corner/entities/analyst_creation_applies_declared_defaults_when_optional_fields_omitted
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    created = validate_success(
        api.create_analyst(
            analyst_payload(
                full_name="Nia Sorensen",
                disciplines=["TRACE"],
                weekly_capacity_hours=30.00,
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )

    assert_fields(
        created,
        employment_status="ACTIVE",
        competency_level=1,
        training_hours_per_week=0.00,
        qualification_state="QUALIFIED",
        consecutive_pt_failures=0,
        assigned_casework_hours=0.00,
    )
    assert_absent(created, "probation_entered_at_utc", "suspended_at_utc")

    workload = validate_success(api.get_analyst_workload(created["id"], DIRECTOR_HEADERS))
    assert_workload(
        workload,
        available_hours=30.00,
        projected_load_hours=0.00,
        projected_utilization_pct=0.00,
        casework_training_ratio=0.00,
        active_assignment_count=0,
        assigned_casework_hours=0.00,
    )


def test_a_client_supplied_custody_status_is_refused_and_logs_no_exhibit(api):
    """Custody position is the server's to assign, so a body that tries to seed custody_status is
    refused as an unknown field and the vault stays empty behind the refusal.

    PRD §2.8: "The body parses, carries every required field, carries no unknown field, and every
    value matches its declared type, enum domain and numeric range, else `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/evidence_item_creation_rejects_client_supplied_custody_status
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0002",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )

    validate_error(
        api.create_evidence_item(
            evidence_item_payload(
                case["id"],
                item_number="1",
                item_description="Sealed envelope",
                item_type="TRACE_MEDIA",
                seal_intact=True,
                custody_status="IN_ANALYSIS",
            ),
            TECHNICIAN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_evidence_items(TECHNICIAN_HEADERS, {"case_id": case["id"]})
    )
    assert rows == [], f"No exhibit may survive the refusal, found {rows!r}"
    assert_list_meta(meta, expected_total=0)
    assert_fields(
        validate_success(api.get_case(case["id"], TECHNICIAN_HEADERS)),
        workflow_status="SUBMITTED",
    )


def test_the_request_copies_its_discipline_and_prices_its_estimate_from_the_method(api):
    """Neither the queue nor the hour estimate is a client input: the discipline is copied from the
    method and 2.50 accredited hours across three items prices the request at 7.50 hours, which it
    carries into a queued life with no holder and no reported hours.

    PRD §3.3: "On success the request copies its `discipline` from the method — that copy is the
    queue it will sit in for the rest of its life, unaffected by any later method edit — and
    computes its `estimated_hours` as the method's `standard_hours_per_item` multiplied by the
    `item_count`, rounded half up to 2 decimal places."

    Design: Corner/entities/examination_request_discipline_and_estimated_hours_are_computed_from_the_method
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = create_validated_method(
        api,
        name="Presumptive Colour Test Battery",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.50,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-COL-01",
        validation_study_item_count=20,
        precision_cv_pct=4.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0003",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed powder packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])

    request = raise_request(api, case["id"], item["id"], method["id"], item_count=3)

    assert_fields(
        request,
        discipline="CHEMISTRY",
        estimated_hours=7.50,
        status="QUEUED",
        revision_round=0,
        vendor_custody_days=0.00,
    )
    assert_absent(request, "assigned_analyst_id", "actual_hours_logged")
    assert_instant_equals(request["requested_at_utc"], "2026-08-01T00:00:00Z", "requested_at_utc")
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=1,
    )


def test_the_case_read_echoes_the_submission_and_its_derived_priority(api):
    """A burglary with a trial date nineteen days out reads back every stored input alongside a
    weighted base of 16.00 and blended temporal points of 10.00, and it stays in the routine queue
    because a court date is not a statutory deadline and burglary is not a violent category.

    PRD §3.1: "**Fourth**, the two temporal signals blend non-linearly: the larger of the deadline
    points and the court points counts in full, the smaller counts at half its value, and the sum
    is rounded half up to 2 decimal places."

    PRD §3.1: "Absent an override, the class is `P1_STATUTORY` when the days-to-deadline figure is
    not null and is at most 30 days; otherwise `P2_VIOLENT` when the `violent_crime_flag` is true;
    otherwise `P3_ROUTINE`."

    Design: Corner/entities/case_read_returns_the_stored_submission_and_priority_fields
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="B-2026-0004",
        submitting_agency="COUNTY SO",
        offense_category="BURGLARY",
        suspect_in_custody=False,
        court_date_utc="2026-08-20T00:00:00Z",
    )

    read = validate_success(api.get_case(case["id"], TECHNICIAN_HEADERS))

    assert read["id"] == case["id"], "The read must answer with the case that was submitted"
    assert_fields(
        read,
        agency_case_number="B-2026-0004",
        submitting_agency="COUNTY SO",
        offense_category="BURGLARY",
        priority_score=26.00,
        priority_class="P3_ROUTINE",
        violent_crime_flag=False,
    )
    assert_instant_equals(read["court_date_utc"], "2026-08-20T00:00:00Z", "court_date_utc")
    assert_absent(read, "statutory_deadline_utc")


def test_the_queue_view_filters_by_case_and_counts_before_paginating(api):
    """Two of three requests belong to the filtered case, so the narrowed read counts exactly two
    matches, and a one-row window walks those two rows in turn: the first page still has more to
    come while the second page does not.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside
    the `meta` object of the envelope, where `total_count` is the number of rows matching the
    filters before pagination is applied."

    Design: Corner/entities/examination_request_listing_filters_by_case_and_reports_total_count
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = create_validated_method(
        api,
        name="Presumptive Colour Test Battery",
        discipline="CHEMISTRY",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-COL-01",
        validation_study_item_count=20,
        precision_cv_pct=4.00,
    )
    first_case = submit_case(
        api,
        agency_case_number="O-2026-0005",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api, first_case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    second_item = log_evidence(
        api, first_case["id"], item_number="2", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, first_case["id"])
    second_case = submit_case(
        api,
        agency_case_number="O-2026-0006",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    third_item = log_evidence(
        api, second_case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, second_case["id"])
    first_request = raise_request(
        api, first_case["id"], first_item["id"], method["id"], item_count=1
    )
    second_request = raise_request(
        api, first_case["id"], second_item["id"], method["id"], item_count=1
    )
    other_case_request = raise_request(
        api, second_case["id"], third_item["id"], method["id"], item_count=1
    )

    rows, meta = validate_paginated(
        api.list_examination_requests(CASE_MANAGER_HEADERS, {"case_id": first_case["id"]})
    )
    assert set(collect_ids(rows)) == {first_request["id"], second_request["id"]}
    assert other_case_request["id"] not in collect_ids(rows)
    assert_list_meta(meta, expected_total=2)

    first_page, first_meta = validate_paginated(
        api.list_examination_requests(
            CASE_MANAGER_HEADERS,
            {"case_id": first_case["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(first_page) == 1, f"A one-row window returns one row, got {first_page!r}"
    assert_list_meta(
        first_meta,
        expected_total=2,
        expected_limit=1,
        expected_offset=0,
        expected_has_more=True,
    )

    second_page, second_meta = validate_paginated(
        api.list_examination_requests(
            CASE_MANAGER_HEADERS,
            {"case_id": first_case["id"], "limit": 1, "offset": 1},
        )
    )
    assert len(second_page) == 1, f"A one-row window returns one row, got {second_page!r}"
    assert_list_meta(
        second_meta,
        expected_total=2,
        expected_offset=1,
        expected_has_more=False,
    )
    assert first_page[0]["id"] != second_page[0]["id"]
    assert {first_page[0]["id"], second_page[0]["id"]} == {
        first_request["id"],
        second_request["id"],
    }


def test_an_unpersisted_examiner_identifier_reports_the_examiner_not_found_code(api):
    """A well-formed identifier that names no examiner resolves to the examiner's own not-found
    code rather than to the generic schema refusal, even with the roster empty.

    PRD §2.8: "**Path identifiers.** Every identifier segment in the URL resolves to an existing
    row of its declared entity, checked left to right, else the entity's own not-found code (404)."

    Design: Corner/entities/analyst_read_with_unknown_id_returns_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_analyst(UNPERSISTED_ANALYST_ID, DIRECTOR_HEADERS),
        ERR_ANALYST_NOT_FOUND,
        404,
    )


def test_a_request_raised_without_an_item_count_is_refused_by_the_schema(api):
    """The examined item count has no default, so a body that omits it never reaches the coherence
    rules: the queue stays empty and the accepted case keeps its intake status.

    PRD §3.3: "A `CaseManager` raises one by naming the `case_id`, the `evidence_item_id` to be
    examined, the `method_id` to apply, and the `item_count` — the number of items examined under
    this request, an integer of at least 1 at the schema layer."

    Design: Corner/entities/examination_request_creation_without_item_count_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = create_validated_method(
        api,
        name="Presumptive Colour Test Battery",
        discipline="CHEMISTRY",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-COL-01",
        validation_study_item_count=20,
        precision_cv_pct=4.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0007",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])

    validate_error(
        api.create_examination_request(
            {
                "case_id": case["id"],
                "evidence_item_id": item["id"],
                "method_id": method["id"],
            },
            CASE_MANAGER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_examination_requests(CASE_MANAGER_HEADERS, {"case_id": case["id"]})
    )
    assert rows == [], f"The refused body may not raise a request, found {rows!r}"
    assert_list_meta(meta, expected_total=0)
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=0,
        workflow_status="ACCEPTED",
    )


def test_a_competency_level_above_five_is_refused_and_mints_no_examiner(api):
    """Competency is an integer on the closed range one through five, so a sixth level is a schema
    violation and the roster is left with nothing at the identifier that was never created.

    PRD §3.4: "The `competency_level` is an integer on the closed range 1 through 5, where 1 is a
    trainee and 5 a technical lead, and defaults to 1; any integer outside that range is a schema
    violation."

    Design: Corner/entities/analyst_creation_with_out_of_range_competency_level_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_analyst(
            analyst_payload(
                full_name="Out Of Range",
                disciplines=["TRACE"],
                competency_level=6,
                weekly_capacity_hours=40.00,
                training_hours_per_week=8.00,
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api.get_analyst(UNPERSISTED_ANALYST_ID, DIRECTOR_HEADERS),
        ERR_ANALYST_NOT_FOUND,
        404,
    )


def test_the_signed_technical_record_carries_no_version_and_no_operator_identifier(api):
    """The review record is written once and never revised: it exposes an identifier and a birth
    stamp but no version, it names the reviewing examiner rather than an opaque operator, and it
    freezes the revision round the request stood at when the signature was given.

    PRD §2.4: "A `ReviewRecord` is immutable once written: it carries only `id` and `created_at`."

    PRD §3.6: "A technical record carries the reviewing examiner in `reviewer_analyst_id` and
    leaves `reviewer_operator_id` null; an administrative record and a disagreement-resolution
    record carry the acting operator's opaque identifier in `reviewer_operator_id` and leave
    `reviewer_analyst_id` null."

    Design: Corner/entities/review_record_is_immutable_and_exposes_no_version_field
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    author = register_analyst(
        api,
        full_name="Author Analyst",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Reviewer Analyst",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0008",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(api, request["id"], author["id"], expected_version=request["version"])
    carry_to_tech_review(
        api, request["id"], author["id"], actual_hours=3.00, evidence_consumed=False
    )

    record = validate_success(
        api.technical_review(
            request["id"],
            technical_review_payload("AGREE", "Peer verification concurs."),
            make_analyst_headers(reviewer["id"]),
        ),
        201,
    )

    assert_immutable_entity(record)
    assert_fields(
        record,
        review_type="TECHNICAL",
        decision="AGREE",
        reviewer_analyst_id=reviewer["id"],
        revision_round_snapshot=0,
    )
    assert_absent(record, "reviewer_operator_id")
    assert_instant_equals(record["recorded_at_utc"], "2026-08-01T00:00:00Z", "recorded_at_utc")

    read = validate_success(api.get_review_record(record["id"], QUALITY_MANAGER_HEADERS))
    assert_immutable_entity(read)

    rows, meta = validate_paginated(
        api.list_review_records(
            QUALITY_MANAGER_HEADERS, {"examination_request_id": request["id"]}
        )
    )
    assert collect_ids(rows) == [record["id"]]
    assert_list_meta(meta, expected_total=1)


def test_an_exhibit_logged_against_an_unpersisted_case_reports_the_case_not_found(api):
    """A case identifier carried in the body is resolved against the case table, so an exhibit
    logged under a case that was never submitted reports the case's own not-found code rather than
    a coherence mismatch between rows that both exist.

    PRD §2.8: "**Body foreign keys.** Every identifier carried in the body resolves to an existing
    row of its declared entity, else that entity's not-found code (404). Body foreign keys are
    resolved after the schema check so that a syntactically invalid identifier yields 400 rather
    than 404."

    Design: Corner/entities/evidence_item_creation_with_unknown_case_id_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_evidence_item(
            evidence_item_payload(
                UNPERSISTED_CASE_ID,
                item_number="1",
                item_description="Sealed envelope",
                item_type="TRACE_MEDIA",
                seal_intact=True,
            ),
            TECHNICIAN_HEADERS,
        ),
        ERR_CASE_NOT_FOUND,
        404,
    )


def test_a_proficiency_test_is_reachable_from_the_examiner_and_from_the_method(api):
    """The proficiency test joins one examiner to one method, so the same row answers a filter on
    the examiner and a filter on the method, and two examiners booked onto one method produce two
    rows that each narrow cleanly by examiner and cycle.

    PRD §3.8: "Proficiency tests are readable individually and as a list narrowable by
    `analyst_id`, `method_id`, `test_cycle`, `status` and `result`."

    PRD §3.8: "A new test has `status` `ASSIGNED`, `late_submission` false and no
    `submitted_at_utc`, `score_pct`, `result` or `scored_at_utc`."

    Design: Corner/entities/proficiency_test_junction_is_reachable_from_both_analyst_and_method
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    first_examiner = register_analyst(
        api,
        full_name="Junction One",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    second_examiner = register_analyst(
        api,
        full_name="Junction Two",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    first_test = assign_proficiency_test(
        api,
        analyst_id=first_examiner["id"],
        method_id=method["id"],
        test_cycle="2026-Q3",
        due_utc="2026-09-01T00:00:00Z",
    )
    second_test = assign_proficiency_test(
        api,
        analyst_id=second_examiner["id"],
        method_id=method["id"],
        test_cycle="2026-Q3",
        due_utc="2026-09-01T00:00:00Z",
    )

    by_examiner, by_examiner_meta = validate_paginated(
        api.list_proficiency_tests(
            QUALITY_MANAGER_HEADERS, {"analyst_id": first_examiner["id"]}
        )
    )
    assert collect_ids(by_examiner) == [first_test["id"]]
    assert_list_meta(by_examiner_meta, expected_total=1)

    by_method, by_method_meta = validate_paginated(
        api.list_proficiency_tests(QUALITY_MANAGER_HEADERS, {"method_id": method["id"]})
    )
    assert set(collect_ids(by_method)) == {first_test["id"], second_test["id"]}
    assert_list_meta(by_method_meta, expected_total=2)

    by_cycle, by_cycle_meta = validate_paginated(
        api.list_proficiency_tests(
            QUALITY_MANAGER_HEADERS,
            {"analyst_id": second_examiner["id"], "test_cycle": "2026-Q3"},
        )
    )
    assert collect_ids(by_cycle) == [second_test["id"]]
    assert_list_meta(by_cycle_meta, expected_total=1)

    assert_fields(first_test, status="ASSIGNED", late_submission=False)
    assert_absent(first_test, "result", "submitted_at_utc", "score_pct", "scored_at_utc")
