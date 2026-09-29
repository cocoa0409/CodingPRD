"""Who may hold, sign and be reinstated: the eligibility battery reporting one code per defect, the
two refusals that guard staffing, the identity and segregation axes, and the two independent gates on
lifting a suspension.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_ANALYST_ALREADY_ASSIGNED,
    ERR_ANALYST_COMPETENCY_INSUFFICIENT,
    ERR_ANALYST_DECERTIFIED,
    ERR_ANALYST_IDENTITY_MISMATCH,
    ERR_ANALYST_INVALID_QUALIFICATION_STATE,
    ERR_ANALYST_NOT_ACTIVE,
    ERR_NONCONFORMANCE_INVALID_STATE,
    ERR_NO_ELIGIBLE_ANALYST,
    ERR_OPEN_NONCONFORMANCE_BLOCKS_REINSTATEMENT,
    ERR_REINSTATEMENT_PT_REQUIRED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TRAINING_MINIMUM_NOT_MET,
)
from test_helpers.assertions import (
    assert_absent,
    assert_fields,
    assert_list_meta,
    assert_workload,
    collect_ids,
)
from test_helpers.factories import (
    administrative_review_payload,
    assignment_payload,
    closure_payload,
    complete_analysis_payload,
    reinstatement_payload,
    technical_review_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_proficiency_test,
    assign_request,
    auto_assign_request,
    close_nonconformance,
    complete_analysis,
    create_validated_method,
    decide_capa,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    score_proficiency_test,
    set_clock,
    sit_proficiency_test,
    start_analysis,
    submit_case,
    submit_proficiency_test,
    submit_root_cause,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    CASE_MANAGER_ID,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    make_analyst_headers,
    make_case_manager_headers,
)


def test_the_eligibility_battery_reports_one_code_for_each_kind_of_defect(api):
    """Three unsuitable examiners on one and the same queued request draw three different codes, the
    probationary one reporting the training shortfall rather than a priority restriction on routine
    work; raising their training hours makes the identical call succeed.

    PRD §3.4: "The incoming examiner must clear an eligibility battery, evaluated in the order §2.8
    fixes: their `employment_status` must be `ACTIVE`, else `ERR_ANALYST_NOT_ACTIVE`; their
    `qualification_state` must be `QUALIFIED`, or `PROBATION` under the remediation window described
    below, a `SUSPENDED` examiner yielding `ERR_ANALYST_NOT_QUALIFIED` and a `DECERTIFIED` one
    `ERR_ANALYST_DECERTIFIED`; a probationary examiner may hold work only on a case whose effective
    `priority_class` is `P3_ROUTINE`, else `ERR_PROBATION_PRIORITY_RESTRICTED`; a probationary examiner
    must additionally carry `training_hours_per_week` of at least 8.00, else
    `ERR_TRAINING_MINIMUM_NOT_MET`; their `disciplines` must contain the method's `discipline`, else
    `ERR_ANALYST_DISCIPLINE_MISMATCH`; their `competency_level` must be at least the method's
    `min_competency_level`, else `ERR_ANALYST_COMPETENCY_INSUFFICIENT`; and finally the capacity gate
    above must admit them."

    PRD §2.8: "**Remediation training minimum.** A probationary examiner meets the standing training
    minimum, else `ERR_TRAINING_MINIMUM_NOT_MET` (409). Checked after the priority restriction, so a
    probationary examiner offered statutory-class work reports the restriction rather than the training
    shortfall."

    PRD §3.8: "An examiner who was `QUALIFIED` and has just failed moves to `PROBATION`,
    `probation_entered_at_utc` is stamped, and the probation release of §2.10 sheds their
    priority-restricted work."

    Design: Corner/errors/analyst_state_gates_are_rejected_with_one_code_each
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    on_leave = register_analyst(
        api,
        full_name="On Leave Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    validate_success(
        api.update_analyst(
            on_leave["id"], {"employment_status": "ON_LEAVE"}, DIRECTOR_HEADERS
        )
    )
    junior = register_analyst(
        api,
        full_name="Junior Examiner",
        disciplines=["BIOLOGY"],
        competency_level=2,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    probationary = register_analyst(
        api,
        full_name="Remediation Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=4.00,
    )
    method = create_validated_method(
        api,
        name="Mixture Interpretation",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        accreditation_scope_code="BIO-MIX-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    failed = sit_proficiency_test(
        api,
        probationary["id"],
        method["id"],
        50.00,
        test_cycle="2026-C1",
        due_utc="2026-08-15T00:00:00Z",
    )
    assert_fields(failed, result="FAIL")
    assert_fields(
        validate_success(api.get_analyst(probationary["id"], QUALITY_MANAGER_HEADERS)),
        qualification_state="PROBATION",
        consecutive_pt_failures=1,
    )

    case = submit_case(
        api,
        agency_case_number="O-2026-0505",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed cutting",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        priority_class="P3_ROUTINE",
    )

    for candidate, expected_code in (
        (on_leave, ERR_ANALYST_NOT_ACTIVE),
        (junior, ERR_ANALYST_COMPETENCY_INSUFFICIENT),
        (probationary, ERR_TRAINING_MINIMUM_NOT_MET),
    ):
        validate_error(
            api.create_assignment(
                request["id"],
                assignment_payload(
                    candidate["id"], request["version"], assignment_reason="MANUAL"
                ),
                CASE_MANAGER_HEADERS,
            ),
            expected_code,
            409,
        )
    refused = read_request(api, request["id"])
    assert_fields(refused, status="QUEUED", version=request["version"])
    assert_absent(refused, "assigned_analyst_id")

    validate_success(
        api.update_analyst(
            probationary["id"], {"training_hours_per_week": 8.00}, DIRECTOR_HEADERS
        )
    )
    assignment = validate_success(
        api.create_assignment(
            request["id"],
            assignment_payload(
                probationary["id"], request["version"], assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(assignment, status="ACTIVE", estimated_hours=4.00)
    assert_fields(
        read_request(api, request["id"]),
        status="ASSIGNED",
        assigned_analyst_id=probationary["id"],
    )
    assert_workload(
        validate_success(
            api.get_analyst_workload(probationary["id"], CASE_MANAGER_HEADERS)
        ),
        available_hours=32.00,
        projected_utilization_pct=12.50,
    )


def test_the_incumbent_cannot_be_reassigned_to_themselves_and_an_empty_pool_is_refused(api):
    """Naming the holder again is refused on its own ground rather than as a stale write, leaving one
    assignment row on the request; and the balancer refuses a discipline nobody covers instead of
    reaching for an ineligible examiner, then picks the newcomer once one exists.

    PRD §3.4: "The stale-version check and the whole eligibility battery apply to the incoming examiner
    exactly as above; once those pass, the named examiner must not be the one who already holds the
    request, else `ERR_ANALYST_ALREADY_ASSIGNED`."

    PRD §3.4: "If the filter yields no candidate at all, nothing is created, the request is left
    `QUEUED`, and the call is refused with `ERR_NO_ELIGIBLE_ANALYST`."

    PRD §3.4: "The first candidate after ordering is selected, receives a new `ACTIVE` assignment with
    `assignment_reason` `AUTO_BALANCED`, and the request moves `QUEUED` → `ASSIGNED` with the same hour
    encumbrance, `assigned_analyst_id` write and case rollup as a manual assignment."

    Design: Corner/errors/reassigning_the_incumbent_and_auto_assigning_an_empty_pool_are_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    incumbent = register_analyst(
        api,
        full_name="Biology Incumbent",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    biology_method = create_validated_method(
        api,
        name="Body Fluid Identification",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        accreditation_scope_code="BIO-BFI-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    chemistry_method = create_validated_method(
        api,
        name="Controlled Substance GCMS",
        discipline="CHEMISTRY",
        standard_hours_per_item=3.00,
        min_competency_level=2,
        max_items_per_request=8,
        accreditation_scope_code="CHM-GCM-01",
        validation_study_item_count=16,
        precision_cv_pct=3.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0506",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    swab = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    powder = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed powder packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    biology_request = raise_request(
        api, case["id"], swab["id"], biology_method["id"], item_count=1
    )
    chemistry_request = raise_request(
        api, case["id"], powder["id"], chemistry_method["id"], item_count=1
    )
    first_assignment = assign_request(
        api,
        biology_request["id"],
        incumbent["id"],
        expected_version=biology_request["version"],
    )
    current_version = read_request(api, biology_request["id"])["version"]

    validate_error(
        api.create_assignment(
            biology_request["id"],
            assignment_payload(
                incumbent["id"], current_version, assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_ANALYST_ALREADY_ASSIGNED,
        409,
    )
    assert_fields(read_request(api, biology_request["id"]), version=current_version)
    held = validate_success(
        api.get_assignment(first_assignment["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(held, status="ACTIVE")
    assert_absent(held, "superseded_by_assignment_id")
    rows, meta = validate_paginated(
        api.list_assignments(
            CASE_MANAGER_HEADERS, {"examination_request_id": biology_request["id"]}
        )
    )
    assert_list_meta(meta, expected_total=1)
    assert collect_ids(rows) == [first_assignment["id"]], (
        "Only the surviving assignment row may be listed against the request"
    )

    validate_error(
        api.auto_assign(chemistry_request["id"], CASE_MANAGER_HEADERS),
        ERR_NO_ELIGIBLE_ANALYST,
        409,
    )
    assert_fields(read_request(api, chemistry_request["id"]), status="QUEUED")

    newcomer = register_analyst(
        api,
        full_name="Chemistry Examiner",
        disciplines=["CHEMISTRY"],
        competency_level=3,
        weekly_capacity_hours=20.00,
        training_hours_per_week=4.00,
    )
    balanced = auto_assign_request(api, chemistry_request["id"])
    assert_fields(
        balanced,
        analyst_id=newcomer["id"],
        assignment_reason="AUTO_BALANCED",
        estimated_hours=3.00,
    )
    assert_fields(read_request(api, chemistry_request["id"]), status="ASSIGNED")
    assert_fields(
        validate_success(api.get_analyst(newcomer["id"], DIRECTOR_HEADERS)),
        assigned_casework_hours=3.00,
    )


def test_acting_as_another_examiner_and_signing_ones_own_work_are_different_wrongs(api):
    """Bench work and proficiency submission are refused with a 403 when the caller is not the person
    the row names, while reviewing work one has already touched is a 409 on both clauses of the
    segregation rule — the holder may not technically review, and the technical reviewer's identifier
    may not sign the release.

    PRD §2.1: "Two mirror-image identity rules apply to `Analyst` callers and to nobody else. On
    starting analysis and on completing analysis, the acting `X-User-ID` must equal the request's
    `assigned_analyst_id`; on submitting a proficiency test, it must equal that test's `analyst_id`. A
    mismatch is `ERR_ANALYST_IDENTITY_MISMATCH` (HTTP 403)."

    PRD §3.6: "Segregation of duties is enforced across all three gates and is compared on both
    `reviewer_analyst_id` and `reviewer_operator_id`, so that a director or manager acting under a
    personal user identifier cannot review their own casework. The technical reviewer may be neither the
    assigned analyst nor the same acting identifier that completed the analysis. The administrative
    reviewer may be neither the assigned analyst nor the technical reviewer of the same
    `revision_round`. A disagreement resolver may be none of those three. Every violation is
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.6: "A technical record carries the reviewing examiner in `reviewer_analyst_id` and leaves
    `reviewer_operator_id` null; an administrative record and a disagreement-resolution record carry the
    acting operator's opaque identifier in `reviewer_operator_id` and leave `reviewer_analyst_id` null."

    Design: Corner/errors/caller_identity_and_reviewer_identity_violations_are_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    holder = register_analyst(
        api,
        full_name="Identity Bench Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    peer = register_analyst(
        api,
        full_name="Identity Peer Examiner",
        disciplines=["BIOLOGY"],
        competency_level=5,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Y-STR Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        accreditation_scope_code="BIO-YST-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    test = assign_proficiency_test(
        api,
        analyst_id=holder["id"],
        method_id=method["id"],
        test_cycle="2026-C1",
        due_utc="2026-08-15T00:00:00Z",
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0507",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(api, request["id"], holder["id"], expected_version=request["version"])

    validate_error(
        api.start_analysis(request["id"], make_analyst_headers(peer["id"])),
        ERR_ANALYST_IDENTITY_MISMATCH,
        403,
    )
    assert_fields(read_request(api, request["id"]), status="ASSIGNED")

    assert_fields(start_analysis(api, request["id"], holder["id"]), status="IN_ANALYSIS")
    validate_error(
        api.complete_analysis(
            request["id"],
            complete_analysis_payload(actual_hours=4.00),
            make_analyst_headers(peer["id"]),
        ),
        ERR_ANALYST_IDENTITY_MISMATCH,
        403,
    )
    assert_fields(read_request(api, request["id"]), status="IN_ANALYSIS")
    assert_fields(
        complete_analysis(api, request["id"], holder["id"], actual_hours=4.00),
        status="TECH_REVIEW",
    )

    validate_error(
        api.technical_review(
            request["id"],
            technical_review_payload("AGREE", "Self review attempt"),
            make_analyst_headers(holder["id"]),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    _rows, meta = validate_paginated(
        api.list_review_records(
            CASE_MANAGER_HEADERS, {"examination_request_id": request["id"]}
        )
    )
    assert_list_meta(meta, expected_total=0)

    technical_record = validate_success(
        api.technical_review(
            request["id"],
            technical_review_payload("AGREE", "Independent verification of the profile"),
            make_analyst_headers(peer["id"]),
        ),
        201,
    )
    assert_fields(
        technical_record, review_type="TECHNICAL", reviewer_analyst_id=peer["id"]
    )
    assert_absent(technical_record, "reviewer_operator_id")
    assert_fields(read_request(api, request["id"]), status="ADMIN_REVIEW")

    validate_error(
        api.administrative_review(
            request["id"],
            administrative_review_payload(
                "APPROVE", "Same operator as the technical reviewer"
            ),
            make_case_manager_headers(peer["id"]),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    assert_fields(read_request(api, request["id"]), status="ADMIN_REVIEW")

    administrative_record = validate_success(
        api.administrative_review(
            request["id"],
            administrative_review_payload(
                "APPROVE", "Report format, case numbers and scope statement verified"
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        administrative_record,
        review_type="ADMINISTRATIVE",
        reviewer_operator_id=CASE_MANAGER_ID,
    )
    assert_absent(administrative_record, "reviewer_analyst_id")
    assert_fields(read_request(api, request["id"]), status="RELEASED")

    validate_error(
        api.submit_proficiency_test(test["id"], make_analyst_headers(peer["id"])),
        ERR_ANALYST_IDENTITY_MISMATCH,
        403,
    )
    assert_fields(
        validate_success(api.get_proficiency_test(test["id"], QUALITY_MANAGER_HEADERS)),
        status="ASSIGNED",
    )


def test_a_suspension_lifts_only_once_the_findings_close_and_a_fresh_pass_lands(api):
    """Two failed proficiency rounds suspend an examiner and leave two live findings behind. The
    reinstatement gates then refuse in sequence — first for the open findings, then for the missing
    post-suspension pass — and once both are satisfied the lift lands on a fresh probation rather than
    on full qualification, after which a second lift has nothing left to lift.

    PRD §3.8: "An examiner already on `PROBATION` whose `consecutive_pt_failures` has reached 2 moves
    to `SUSPENDED`, `suspended_at_utc` is stamped, and the full release sheds all of their open work."

    PRD §3.8: "The examiner must carry no nonconformance whose `status` is `OPEN`,
    `ROOT_CAUSE_SUBMITTED` or `CAPA_APPROVED`, else `ERR_OPEN_NONCONFORMANCE_BLOCKS_REINSTATEMENT` —
    every finding against them must be `CLOSED` or `VOIDED`."

    PRD §3.8: "Closure is admissible only from `CAPA_APPROVED`, else `ERR_NONCONFORMANCE_INVALID_STATE`;
    the finding moves to the terminal `CLOSED`, `closed_at_utc` is stamped, and `overdue` is recomputed
    to false."

    PRD §3.8: "And they must have at least one `SCORED` proficiency test whose `result` is `PASS` and
    whose `scored_at_utc` lies strictly after their `suspended_at_utc`, else
    `ERR_REINSTATEMENT_PT_REQUIRED`; a pass earned before the suspension proves nothing about the
    competence that was suspended."

    PRD §3.8: "On success the examiner moves `SUSPENDED` → `PROBATION` rather than straight to
    `QUALIFIED`, `consecutive_pt_failures` resets to 0, `suspended_at_utc` is cleared to null, and
    `probation_entered_at_utc` is set to the current logical instant, starting a fresh probation."

    PRD §3.8: "It is admissible only from `SUSPENDED`: an examiner who is `QUALIFIED` or on `PROBATION`
    yields `ERR_ANALYST_INVALID_QUALIFICATION_STATE`, and one who is `DECERTIFIED` yields the more
    specific `ERR_ANALYST_DECERTIFIED`, decertification being irreversible."

    Design: Corner/errors/reinstatement_of_a_suspended_analyst_is_rejected_until_both_gates_clear
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Suspended Bench Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="STR Autosomal Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        accreditation_scope_code="BIO-STR-02",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    sit_proficiency_test(api, examiner["id"], method["id"], 50.00, test_cycle="2026-C1")
    sit_proficiency_test(api, examiner["id"], method["id"], 55.00, test_cycle="2026-C2")

    suspended = validate_success(
        api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(
        suspended,
        qualification_state="SUSPENDED",
        consecutive_pt_failures=2,
        suspended_at_utc="2026-08-01T00:00:00Z",
    )

    findings, meta = validate_paginated(
        api.list_nonconformances(
            QUALITY_MANAGER_HEADERS,
            {"analyst_id": examiner["id"], "source": "PT_FAILURE"},
        )
    )
    assert_list_meta(meta, expected_total=2)
    for finding in findings:
        assert_fields(
            finding,
            severity="MAJOR",
            status="OPEN",
            due_utc="2026-08-31T00:00:00Z",
            overdue=False,
        )

    validate_error(
        api.reinstate_analyst(
            examiner["id"],
            reinstatement_payload("Findings still under investigation"),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_OPEN_NONCONFORMANCE_BLOCKS_REINSTATEMENT,
        409,
    )

    validate_error(
        api.verify_close_nonconformance(
            findings[0]["id"],
            closure_payload("Closing without the corrective action steps"),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_NONCONFORMANCE_INVALID_STATE,
        409,
    )
    untouched = validate_success(
        api.get_nonconformance(findings[0]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(untouched, status="OPEN")
    assert_absent(untouched, "closed_at_utc")

    submit_root_cause(api, findings[0]["id"])
    decide_capa(api, findings[0]["id"], "APPROVE")
    first_closed = close_nonconformance(api, findings[0]["id"])
    assert_fields(
        first_closed,
        status="CLOSED",
        closed_at_utc="2026-08-01T00:00:00Z",
        overdue=False,
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        qualification_state="SUSPENDED",
    )

    submit_root_cause(api, findings[1]["id"])
    decide_capa(api, findings[1]["id"], "APPROVE")
    assert_fields(close_nonconformance(api, findings[1]["id"]), status="CLOSED")

    validate_error(
        api.reinstate_analyst(
            examiner["id"],
            reinstatement_payload("Remediation complete but no new test on file"),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_REINSTATEMENT_PT_REQUIRED,
        409,
    )

    set_clock(api, "2026-08-05T00:00:00Z")
    fresh_test = assign_proficiency_test(
        api,
        analyst_id=examiner["id"],
        method_id=method["id"],
        test_cycle="2026-C3",
        due_utc="2026-08-31T00:00:00Z",
    )
    submit_proficiency_test(api, fresh_test["id"], examiner["id"])
    scored = score_proficiency_test(api, fresh_test["id"], 95.00)
    assert_fields(
        scored, status="SCORED", result="PASS", scored_at_utc="2026-08-05T00:00:00Z"
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        qualification_state="SUSPENDED",
    )

    reinstated = validate_success(
        api.reinstate_analyst(
            examiner["id"],
            reinstatement_payload("Findings closed and a post-suspension pass on file"),
            QUALITY_MANAGER_HEADERS,
        )
    )
    assert_fields(
        reinstated,
        qualification_state="PROBATION",
        consecutive_pt_failures=0,
        probation_entered_at_utc="2026-08-05T00:00:00Z",
    )
    assert_absent(reinstated, "suspended_at_utc")

    validate_error(
        api.reinstate_analyst(
            examiner["id"],
            reinstatement_payload("Attempting to lift a suspension already lifted"),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_ANALYST_INVALID_QUALIFICATION_STATE,
        409,
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        qualification_state="PROBATION",
    )


def test_decertification_closes_the_bench_and_the_reinstatement_route_alike(api):
    """A third failure is terminal. The named-holder route reports the specific decertification code
    rather than the generic not-qualified one, the reinstatement route reports the same code because
    the state is irreversible, and the balancer — whose predicate the examiner no longer satisfies —
    finds nobody at all and leaves the request queued.

    PRD §3.8: "An examiner already `SUSPENDED` who fails again moves to the terminal `DECERTIFIED`,
    with a full release once more."

    PRD §2.8: "An `employment_status` other than `ACTIVE` yields `ERR_ANALYST_NOT_ACTIVE` (409) and a
    `DECERTIFIED` analyst yields `ERR_ANALYST_DECERTIFIED` (409); both of those are tested before the
    qualified-or-probation test, whose own failure yields `ERR_ANALYST_NOT_QUALIFIED` (409)."

    PRD §3.8: "It is admissible only from `SUSPENDED`: an examiner who is `QUALIFIED` or on `PROBATION`
    yields `ERR_ANALYST_INVALID_QUALIFICATION_STATE`, and one who is `DECERTIFIED` yields the more
    specific `ERR_ANALYST_DECERTIFIED`, decertification being irreversible."

    PRD §3.4: "If the filter yields no candidate at all, nothing is created, the request is left
    `QUEUED`, and the call is refused with `ERR_NO_ELIGIBLE_ANALYST`."

    Design: Corner/errors/a_decertified_analyst_is_rejected_for_both_assignment_and_reinstatement
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Decertified Bench Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="STR Autosomal Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        accreditation_scope_code="BIO-STR-03",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    sit_proficiency_test(api, examiner["id"], method["id"], 50.00, test_cycle="2026-C1")
    sit_proficiency_test(api, examiner["id"], method["id"], 55.00, test_cycle="2026-C2")
    sit_proficiency_test(api, examiner["id"], method["id"], 60.00, test_cycle="2026-C3")

    decertified = validate_success(
        api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(
        decertified, qualification_state="DECERTIFIED", consecutive_pt_failures=3
    )

    case = submit_case(
        api,
        agency_case_number="O-2026-0509",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="BIOLOGICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)

    validate_error(
        api.create_assignment(
            request["id"],
            assignment_payload(examiner["id"], request["version"]),
            CASE_MANAGER_HEADERS,
        ),
        ERR_ANALYST_DECERTIFIED,
        409,
    )
    unstaffed = read_request(api, request["id"])
    assert_fields(unstaffed, status="QUEUED", version=request["version"])
    assert_absent(unstaffed, "assigned_analyst_id")

    validate_error(
        api.reinstate_analyst(
            examiner["id"],
            reinstatement_payload("Requesting a second chance after decertification"),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_ANALYST_DECERTIFIED,
        409,
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        qualification_state="DECERTIFIED",
    )

    validate_error(
        api.auto_assign(request["id"], CASE_MANAGER_HEADERS),
        ERR_NO_ELIGIBLE_ANALYST,
        409,
    )
    assert_fields(read_request(api, request["id"]), status="QUEUED")
    _rows, meta = validate_paginated(
        api.list_assignments(
            CASE_MANAGER_HEADERS, {"examination_request_id": request["id"]}
        )
    )
    assert_list_meta(meta, expected_total=0)
