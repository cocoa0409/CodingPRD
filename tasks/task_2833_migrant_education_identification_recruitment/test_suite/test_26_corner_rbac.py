"""Role segregation on writes, shared read access, and the two genuinely shared writes."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_assessment_components,
    assert_int_equals,
    assert_is_null,
    assert_pfs_triple,
    assert_row_count,
    assert_version,
    assert_version_advanced_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    COE_SUBMITTED,
    CREDENTIAL_QC_CERTIFIED,
    INFORMANT_EMPLOYER,
    PFS_VARIANT_INTERRUPTION_WEIGHTED,
    PURPOSE_ACCOMPANY_WORKER,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_qc_reviewer_headers,
    make_recruiter_headers,
)


def test_each_role_cannot_perform_another_roles_exclusive_write(client):
    """Seven well-formed writes are each turned away purely because of the acting role.

    "2. **Role authorization** - the acting role appears in the target endpoint's
    authorized-role list: `ERR_UNAUTHORIZED` (403)." "The `ExchangeLiaison` opens and drives
    national-exchange transfer requests and touches no certificate, plan or delivery."

    Design: Corner/rbac/corner_each_role_cannot_perform_another_roles_exclusive_write
    """
    bundle = fixtures.submitted_certificate(
        client,
        coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True},
        grade_level=factories.DROP,
    )
    recruiter_id = bundle.recruiter["id"]
    student_id = bundle.student["id"]
    area_id = bundle.area["id"]
    baseline = fixtures.read_student(client, student_id)
    baseline_version = baseline["version"]
    assert_is_null(baseline["grade_level"], "student.grade_level")
    assert_int_equals(bundle.coe["status"], COE_SUBMITTED, "certificate.status")

    validate_error(
        client.approve_coe(bundle.coe["id"], make_recruiter_headers(recruiter_id)),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    assert_int_equals(
        fixtures.read_coe(client, bundle.coe["id"])["status"],
        COE_SUBMITTED,
        "certificate.status",
    )

    validate_error(
        client.create_student(
            factories.student_payload(
                area_id, full_name="Blocked Student", birth_date="2011-01-05"
            ),
            make_coordinator_headers(),
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    students, _meta = fixtures.list_rows(client.list_students(make_admin_headers()))
    assert_row_count(students, 1, "children on file")

    validate_error(
        client.create_plan(
            factories.plan_payload(student_id, baseline_version), make_liaison_headers()
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    plans, _meta = fixtures.list_rows(
        client.list_plans(make_coordinator_headers(), {"student_id": student_id})
    )
    assert_row_count(plans, 0, "service plans for the child")

    validate_error(
        client.create_transfer_request(
            factories.transfer_request_payload(
                student_id, exchange_reference="MSIX-2026-000501"
            ),
            make_admin_headers(),
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    requests, _meta = fixtures.list_rows(
        client.list_transfer_requests(make_liaison_headers())
    )
    assert_row_count(requests, 0, "transfer requests on file")

    validate_error(
        client.create_move(
            factories.move_payload(
                student_id,
                from_state_code="ID",
                move_date="2026-06-25",
                purpose=PURPOSE_ACCOMPANY_WORKER,
                distance_miles=430.00,
            ),
            make_qc_reviewer_headers(recruiter_id),
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    moves, _meta = fixtures.list_rows(
        client.list_moves(make_admin_headers(), {"student_id": student_id})
    )
    assert_row_count(moves, 1, "qualifying moves for the child")

    validate_error(
        client.create_area(
            factories.area_payload(
                name="Blocked Area",
                primary_activity="FISHING",
                peak_season_end_date="2026-08-31",
            ),
            make_recruiter_headers(recruiter_id),
        ),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    surviving_area = fixtures.read_area(client, area_id)
    assert_int_equals(surviving_area["name"], bundle.area["name"], "area.name")
    assert_version(surviving_area, 1, "area")

    validate_error(
        client.patch_student(student_id, {"grade_level": 10}, make_liaison_headers()),
        api_errors.ERR_UNAUTHORIZED,
        403,
    )
    final = fixtures.read_student(client, student_id)
    assert_is_null(final["grade_level"], "student.grade_level")
    assert_version_unchanged(final, baseline_version, "student")


def test_all_five_roles_can_read_the_shared_get_surface(client):
    """The same three reads answer identically for every role and mutate nothing.

    "Every read endpoint in 4 is open to all five roles." "This read never writes and never
    touches `version`."

    Design: Corner/rbac/corner_all_five_roles_can_read_the_shared_get_surface
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(
        client,
        recruiter_id,
        base.area["id"],
        school_days_interrupted=0,
        credit_deficit=0,
        math_below_grade=False,
        reading_below_grade=False,
    )
    move = fixtures.verified_move(client, recruiter_id, student["id"])
    coe = fixtures.draft_coe(client, recruiter_id, student["id"], move["id"])
    first_version = fixtures.read_student(client, student["id"])["version"]

    as_admin = validate_success(
        client.get_student(student["id"], make_admin_headers()), 200
    )
    as_recruiter = validate_success(
        client.get_student(student["id"], make_recruiter_headers(recruiter_id)), 200
    )
    as_reviewer = validate_success(
        client.get_student(student["id"], make_qc_reviewer_headers(recruiter_id)), 200
    )
    assert_int_equals(as_admin["id"], student["id"], "student.id read by the state office")
    assert as_admin == as_recruiter, "the recruiter read must match the state-office read"
    assert as_admin == as_reviewer, "the reviewer read must match the state-office read"

    listed, _meta = fixtures.list_rows(
        client.list_coes(make_coordinator_headers(), {"student_id": student["id"]})
    )
    assert_row_count(listed, 1, "certificates visible to the coordinator")
    assert_int_equals(listed[0]["id"], coe["id"], "listed certificate.id")

    assessment = validate_success(
        client.get_pfs_assessment(student["id"], make_liaison_headers()), 200
    )
    assert_assessment_components(
        assessment,
        move_band_points=18,
        interruption_points=0,
        academic_points=0,
        credit_points=0,
        raw_score=18,
    )
    assert_pfs_triple(
        assessment, PFS_VARIANT_INTERRUPTION_WEIGHTED, 18, False, "assessment"
    )

    after = fixtures.read_student(client, student["id"])
    assert_version_unchanged(after, first_version, "student")


def test_shared_writes_accept_both_of_their_declared_roles(client):
    """Both callers of each shared write succeed, and each row is stamped to its own caller.

    "The `QualityControlReviewer` decides quality-control reviews and, alongside the
    `Recruiter`, may file interview documentation." "Amending a child's profile is shared
    between the `Recruiter` and the `ServiceCoordinator`, and the writable set is
    `current_state_code`, `area_id`, `schooling_status`, `grade_level`,
    `school_days_interrupted`, `math_below_grade`, `reading_below_grade`, `credit_deficit`,
    `has_hs_credential` and `primary_language_not_english`."

    Design: Corner/rbac/corner_shared_writes_accept_both_of_their_declared_roles
    """
    area = fixtures.create_area(client)
    field_recruiter = fixtures.create_recruiter(client, full_name="Rosa Aguilar")
    reviewer = fixtures.create_recruiter(
        client, full_name="Paula Vega", credential_level=CREDENTIAL_QC_CERTIFIED
    )
    student = fixtures.create_student(
        client,
        field_recruiter["id"],
        area["id"],
        school_days_interrupted=0,
        credit_deficit=0,
        math_below_grade=False,
        reading_below_grade=False,
    )
    move = fixtures.verified_move(client, field_recruiter["id"], student["id"])
    first_version = fixtures.read_student(client, student["id"])["version"]

    by_recruiter = validate_success(
        client.create_interview(
            factories.interview_payload(
                student["id"],
                move["id"],
                documentation_notes="Recruiter-recorded initial interview.",
            ),
            make_recruiter_headers(field_recruiter["id"]),
        ),
        201,
    )
    assert_int_equals(
        by_recruiter["recruiter_id"], field_recruiter["id"], "first interview.recruiter_id"
    )

    by_reviewer = validate_success(
        client.create_interview(
            factories.interview_payload(
                student["id"],
                move["id"],
                conducted_on="2026-06-21",
                informant_relationship=INFORMANT_EMPLOYER,
                documentation_notes="Reviewer-recorded corroborating interview with the employer.",
                corroboration_count=2,
            ),
            make_qc_reviewer_headers(reviewer["id"]),
        ),
        201,
    )
    assert_int_equals(
        by_reviewer["recruiter_id"], reviewer["id"], "second interview.recruiter_id"
    )

    filed, _meta = fixtures.list_rows(
        client.list_interviews(make_admin_headers(), {"move_id": move["id"]})
    )
    assert_row_count(filed, 2, "interview records documenting the move")

    amended_by_recruiter = validate_success(
        client.patch_student(
            student["id"],
            {"school_days_interrupted": 10},
            make_recruiter_headers(field_recruiter["id"]),
        ),
        200,
    )
    assert_int_equals(
        amended_by_recruiter["school_days_interrupted"],
        10,
        "student.school_days_interrupted",
    )
    assert_version_advanced_by(amended_by_recruiter, first_version, 1, "student")
    second_version = amended_by_recruiter["version"]

    amended_by_coordinator = validate_success(
        client.patch_student(
            student["id"], {"credit_deficit": 2}, make_coordinator_headers()
        ),
        200,
    )
    assert_int_equals(
        amended_by_coordinator["credit_deficit"], 2, "student.credit_deficit"
    )
    assert_version_advanced_by(amended_by_coordinator, second_version, 1, "student")

    settled = fixtures.read_student(client, student["id"])
    assert_pfs_triple(settled, PFS_VARIANT_INTERRUPTION_WEIGHTED, 32, False, "student")
