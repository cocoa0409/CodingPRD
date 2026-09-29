"""Endpoint behaviour: partial updates, a pure computed read, a batch pass and links."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_decimal_equals,
    assert_instant_equals,
    assert_int_equals,
    assert_is_null,
    assert_pfs_triple,
    assert_row_count,
    assert_student_ledgers,
    assert_version,
    assert_version_unchanged,
    ids_of,
)
from test_helpers.constants import (
    AREA_STATUS_OPEN,
    CLOCK_START_INSTANT,
    CREDENTIAL_QC_CERTIFIED,
    ELIGIBILITY_CONTINUATION,
    ELIGIBILITY_TERM_EXPIRED,
    INTERVIEW_KIND_INITIAL,
    INTERVIEW_KIND_QC_REINTERVIEW,
    OUTCOME_SUPPORTS,
    PFS_VARIANT_OSY_PATHWAY,
    PLAN_TYPE_SUPPLEMENTAL,
    SCHOOLING_OUT_OF_SCHOOL,
    TERM_ACTIVE,
    TERM_EXPIRED,
    TERM_EXPIRING,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_qc_reviewer_headers,
)


def test_area_patch_updates_only_the_supplied_fields_and_bumps_version(client):
    """Three supplied keys are rewritten, four unsupplied ones stand, and the read is inert.

    "Only the state office may open or amend an area, and amendment is narrow: `status`,
    `recruiter_capacity`, `peak_season_start_date` and `peak_season_end_date` are the only
    writable keys, and any other key in the body - including `name`, `state_code`,
    `primary_activity` or `assigned_primary_slots_used` - is silently ignored rather than
    rejected. Every accepted amendment increments the area's `version` by 1 and refreshes
    `updated_at`."

    Design: Corner/endpoints/corner_area_patch_updates_only_the_supplied_fields_and_bumps_version
    """
    area = fixtures.create_area(client, recruiter_capacity=3)
    assert_version(area, 1, "area")
    assert_instant_equals(area["created_at"], CLOCK_START_INSTANT, "area.created_at")

    fixtures.set_clock(client, "2026-08-10T09:30:00Z")
    patched = validate_success(
        client.patch_area(
            area["id"],
            {
                "recruiter_capacity": 5,
                "peak_season_start_date": "2026-05-15",
                "peak_season_end_date": "2026-10-15",
            },
            make_admin_headers(),
        ),
        200,
    )

    assert_int_equals(patched["recruiter_capacity"], 5, "area.recruiter_capacity")
    assert_date_equals(
        patched["peak_season_start_date"], "2026-05-15", "area.peak_season_start_date"
    )
    assert_date_equals(
        patched["peak_season_end_date"], "2026-10-15", "area.peak_season_end_date"
    )
    assert_int_equals(patched["name"], area["name"], "area.name")
    assert_int_equals(patched["state_code"], area["state_code"], "area.state_code")
    assert_int_equals(
        patched["primary_activity"], area["primary_activity"], "area.primary_activity"
    )
    assert_int_equals(patched["status"], AREA_STATUS_OPEN, "area.status")
    assert_int_equals(
        patched["assigned_primary_slots_used"], 0, "area.assigned_primary_slots_used"
    )
    assert_version(patched, 2, "area")
    assert_instant_equals(patched["created_at"], CLOCK_START_INSTANT, "area.created_at")
    assert_instant_equals(
        patched["updated_at"], "2026-08-10T09:30:00Z", "area.updated_at"
    )

    reread = fixtures.read_area(client, area["id"])
    assert_version(reread, 2, "area")
    assert_int_equals(reread["recruiter_capacity"], 5, "area.recruiter_capacity")
    assert_instant_equals(
        reread["updated_at"], "2026-08-10T09:30:00Z", "area.updated_at"
    )


def test_pfs_assessment_read_matches_the_formula_and_writes_nothing(client):
    """Every out-of-school component reconciles to 36, which the floor lifts to 55.

    "In their place, `credential_points` contribute 20 when `has_hs_credential` is false and
    0 when the child already holds a diploma or equivalency, and `language_points` contribute
    10 when `primary_language_not_english` is true and 0 otherwise. The `raw_score` is the sum
    of `move_band_points`, `interruption_points`, `credential_points` and `language_points`.
    This pathway then applies a floor before the ceiling: take whichever is larger, the raw
    sum or 55, then take whichever is smaller, that result or 100."

    Design: Corner/endpoints/corner_pfs_assessment_read_matches_the_formula_and_writes_nothing
    """
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_osy_student(
        client,
        base.recruiter["id"],
        base.area["id"],
        full_name="Ana Lopez",
        birth_date="2008-11-02",
    )
    assert_int_equals(
        student["schooling_status"], SCHOOLING_OUT_OF_SCHOOL, "student.schooling_status"
    )
    assert_pfs_triple(student, PFS_VARIANT_OSY_PATHWAY, 55, False, "student")

    assessment = fixtures.read_assessment(client, student["id"])

    assert_int_equals(assessment["student_id"], student["id"], "assessment.student_id")
    assert_int_equals(
        assessment["pfs_variant"], PFS_VARIANT_OSY_PATHWAY, "assessment.pfs_variant"
    )
    assert_int_equals(assessment["move_band_points"], 0, "assessment.move_band_points")
    assert_int_equals(
        assessment["interruption_points"], 6, "assessment.interruption_points"
    )
    assert_int_equals(assessment["academic_points"], 0, "assessment.academic_points")
    assert_int_equals(assessment["credential_points"], 20, "assessment.credential_points")
    assert_int_equals(assessment["language_points"], 10, "assessment.language_points")
    assert_int_equals(assessment["credit_points"], 0, "assessment.credit_points")
    assert_int_equals(assessment["raw_score"], 36, "assessment.raw_score")
    assert_int_equals(assessment["pfs_score"], 55, "assessment.pfs_score")
    assert_int_equals(assessment["floor_applied"], True, "assessment.floor_applied")
    assert_int_equals(assessment["pfs_flag"], False, "assessment.pfs_flag")

    after = fixtures.read_student(client, student["id"])
    assert_pfs_triple(after, PFS_VARIANT_OSY_PATHWAY, 55, False, "student")
    assert_version_unchanged(after, student["version"], "student")
    assert_instant_equals(
        after["updated_at"], student["updated_at"], "student.updated_at"
    )


def test_one_sweep_call_advances_two_terms_to_different_states(client):
    """One batch, two per-row decisions: one term expires while the other only warns.

    "Its batch is every term whose `status` is `ACTIVE`, `EXPIRING` or `EXPIRED`, processed in
    `term_end_on` ascending order with ties broken by `created_at` ascending; terms in
    `REIDENTIFIED`, `LAPSED` or `TERMINATED` are excluded from the batch entirely." "The
    second branch handles the continuation warning, `ACTIVE -> EXPIRING`: when a term is still
    `ACTIVE`, the clock date is on or after `term_end_on` minus sixty days, and the clock date
    is on or before `term_end_on`, the term becomes `EXPIRING` and the child's eligibility
    dimension advances `ELIGIBLE -> CONTINUATION`."

    Design: Corner/endpoints/corner_one_sweep_call_advances_two_terms_to_different_states
    """
    earlier = fixtures.certified_child(
        client,
        coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True},
        full_name="Student X",
    )
    later = fixtures.certified_child(
        client,
        coe_overrides={"residency_date": "2026-07-31", "qc_hold_exempt": True},
        full_name="Student Y",
    )
    assert_date_equals(earlier.term["term_end_on"], "2029-06-30", "term X.term_end_on")
    assert_date_equals(later.term["term_end_on"], "2029-07-30", "term Y.term_end_on")
    assert_int_equals(earlier.term["status"], TERM_ACTIVE, "term X.status")
    assert_int_equals(later.term["status"], TERM_ACTIVE, "term Y.status")

    fixtures.set_clock(client, "2029-07-15T00:00:00Z")
    run = fixtures.sweep(client)

    assert_int_equals(run["swept_count"], 2, "sweep.swept_count")
    assert_int_equals(run["expiring_count"], 1, "sweep.expiring_count")
    assert_int_equals(run["expired_count"], 1, "sweep.expired_count")
    assert_int_equals(run["lapsed_count"], 0, "sweep.lapsed_count")
    assert_int_equals(
        run["expired_term_ids"], [earlier.term["id"]], "sweep.expired_term_ids"
    )

    expired = fixtures.read_term(client, earlier.term["id"])
    assert_int_equals(expired["status"], TERM_EXPIRED, "term X.status")
    assert_date_equals(
        expired["reidentification_due_on"], "2029-08-14", "term X.reidentification_due_on"
    )
    expiring = fixtures.read_term(client, later.term["id"])
    assert_int_equals(expiring["status"], TERM_EXPIRING, "term Y.status")
    assert_is_null(
        expiring["reidentification_due_on"], "term Y.reidentification_due_on"
    )

    child_x = fixtures.read_student(client, earlier.student["id"])
    assert_int_equals(
        child_x["eligibility_status"],
        ELIGIBILITY_TERM_EXPIRED,
        "student X.eligibility_status",
    )
    assert_is_null(child_x["eligibility_expires_on"], "student X.eligibility_expires_on")
    child_y = fixtures.read_student(client, later.student["id"])
    assert_int_equals(
        child_y["eligibility_status"],
        ELIGIBILITY_CONTINUATION,
        "student Y.eligibility_status",
    )
    assert_date_equals(
        child_y["eligibility_expires_on"], "2029-07-30", "student Y.eligibility_expires_on"
    )


def test_qc_reinterview_links_student_move_and_certificate(client):
    """The certificate link is required for a re-interview and forbidden for an initial one.

    "The `coe_id` linking the record to a certificate is required exactly when
    `interview_kind` is `QC_REINTERVIEW` and must be absent when it is `INITIAL`; getting that
    pairing wrong is an `ERR_INVALID_REQUEST` shape failure, and a `coe_id` that does not
    resolve reports `ERR_COE_NOT_FOUND`."

    Design: Corner/endpoints/corner_qc_reinterview_links_student_move_and_certificate
    """
    bundle = fixtures.identified_child(client)
    reviewer = fixtures.create_recruiter(
        client, full_name="Paula Vega", credential_level=CREDENTIAL_QC_CERTIFIED
    )
    coe = fixtures.draft_coe(
        client,
        bundle.recruiter["id"],
        bundle.student["id"],
        bundle.move["id"],
        qc_hold_exempt=False,
    )
    headers = make_qc_reviewer_headers(reviewer["id"])

    unlinked = factories.reinterview_payload(
        bundle.student["id"], bundle.move["id"], coe["id"], conducted_on="2026-07-10"
    )
    unlinked.pop("coe_id")
    validate_error(
        client.create_interview(unlinked, headers), api_errors.ERR_INVALID_REQUEST, 422
    )

    overlinked = factories.interview_payload(
        bundle.student["id"], bundle.move["id"], conducted_on="2026-07-11"
    )
    overlinked["coe_id"] = coe["id"]
    validate_error(
        client.create_interview(overlinked, headers), api_errors.ERR_INVALID_REQUEST, 422
    )

    filed = validate_success(
        client.create_interview(
            factories.reinterview_payload(
                bundle.student["id"],
                bundle.move["id"],
                coe["id"],
                conducted_on="2026-07-12",
                corroboration_count=2,
            ),
            headers,
        ),
        201,
    )

    assert_int_equals(filed["student_id"], bundle.student["id"], "interview.student_id")
    assert_int_equals(filed["move_id"], bundle.move["id"], "interview.move_id")
    assert_int_equals(filed["coe_id"], coe["id"], "interview.coe_id")
    assert_int_equals(filed["recruiter_id"], reviewer["id"], "interview.recruiter_id")
    assert_int_equals(
        filed["interview_kind"], INTERVIEW_KIND_QC_REINTERVIEW, "interview.interview_kind"
    )
    assert_int_equals(filed["corroboration_count"], 2, "interview.corroboration_count")
    assert_int_equals(filed["outcome"], OUTCOME_SUPPORTS, "interview.outcome")

    by_coe, _meta = fixtures.list_rows(
        client.list_interviews(make_admin_headers(), {"coe_id": coe["id"]})
    )
    assert_row_count(by_coe, 1, "interviews linked to the certificate")
    assert_int_equals(by_coe[0]["id"], filed["id"], "linked interview.id")

    by_move, _meta = fixtures.list_rows(
        client.list_interviews(make_admin_headers(), {"move_id": bundle.move["id"]})
    )
    assert_row_count(by_move, 2, "interviews documenting the move")
    assert sorted(ids_of(by_move)) == sorted(
        [bundle.interview["id"], filed["id"]]
    ), "the two refused calls must not have created rows"
    kinds = sorted(row["interview_kind"] for row in by_move)
    assert_int_equals(
        kinds,
        sorted([INTERVIEW_KIND_INITIAL, INTERVIEW_KIND_QC_REINTERVIEW]),
        "interview kinds on the move",
    )


def test_reversing_a_reversal_row_is_refused(client):
    """Neither the compensating row nor the row it settled can be reversed again.

    "A record that is itself a reversal, or a forward record already flagged `is_reversed`,
    cannot be reversed and the attempt is refused with `ERR_DELIVERY_NOT_REVERSIBLE`."

    Design: Corner/endpoints/corner_reversing_a_reversal_row_is_refused
    """
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    plan = fixtures.active_plan(
        client, bundle.student["id"], plan_type=PLAN_TYPE_SUPPLEMENTAL
    )
    original = fixtures.post_delivery(
        client, plan["id"], delivered_on="2026-08-01", hours=2.50
    )
    reversal = fixtures.reverse_delivery(client, original["id"])

    assert_int_equals(
        fixtures.read_delivery(client, original["id"])["is_reversed"],
        True,
        "original.is_reversed",
    )
    assert_int_equals(
        reversal["reverses_delivery_id"], original["id"], "reversal.reverses_delivery_id"
    )
    assert_decimal_equals(
        fixtures.read_plan(client, plan["id"])["delivered_hours"],
        "0.00",
        "plan.delivered_hours",
    )
    assert_student_ledgers(
        fixtures.read_student(client, bundle.student["id"]), hours="0.00"
    )

    validate_error(
        client.reverse_delivery(reversal["id"], make_coordinator_headers()),
        api_errors.ERR_DELIVERY_NOT_REVERSIBLE,
        409,
    )
    validate_error(
        client.reverse_delivery(original["id"], make_coordinator_headers()),
        api_errors.ERR_DELIVERY_NOT_REVERSIBLE,
        409,
    )

    rows, _meta = fixtures.list_rows(
        client.list_deliveries(make_coordinator_headers(), {"plan_id": plan["id"]})
    )
    assert_row_count(rows, 2, "delivery records on the plan")
    assert_decimal_equals(
        fixtures.read_plan(client, plan["id"])["delivered_hours"],
        "0.00",
        "plan.delivered_hours",
    )
    assert_student_ledgers(
        fixtures.read_student(client, bundle.student["id"]), hours="0.00"
    )
    assert_int_equals(
        fixtures.read_delivery(client, reversal["id"])["is_reversed"],
        False,
        "reversal.is_reversed",
    )
