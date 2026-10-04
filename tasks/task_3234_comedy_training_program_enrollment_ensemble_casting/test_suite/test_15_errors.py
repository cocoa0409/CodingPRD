"""Corner queue: errors — OCC stale version, invoice overpayment, grades
incomplete, unauthorized role."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, reset_clock, setup_open_term_with_section,
    enroll_with_fresh_version, confirm_enrollment, run_term_to_close,
    create_venue_slot, create_showcase_payload, invoice_id_for_enrollment,
    create_ensemble_cast_payload, get_section, create_audition_payload,
    create_curriculum_level_payload, create_section_payload, create_term_draft,
    create_instructor,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
CD = TEST_USERS["casting_director_headers"]
FO = TEST_USERS["finance_officer_headers"]
STUDENT = TEST_USERS["student_headers"]


def test_error_stale_version_on_enrollment_create():
    """PRD §2.5: "Creating an enrollment requires `expected_section_version` in the
    request body, carrying the client's last observed `version` of the target
    section. If the section's current `version` does not match — because another
    writer has since confirmed, dropped, or transferred an enrollment, or patched
    the section, each of which legitimately bumps the section's version — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_enrollment_create
    """
    ctx = setup_open_term_with_section(capacity=4)
    s1 = create_student()
    s2 = create_student()
    stale_version = get_section(ctx["section"]["id"])["version"]
    enroll_with_fresh_version(s1["id"], ctx["section"]["id"])
    resp = api_client.create_enrollment(
        {"student_id": s2["id"], "section_id": ctx["section"]["id"],
         "expected_section_version": stale_version}, REG)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_error_stale_version_on_cast_lock():
    """PRD §3.8: "Locking the cast (`CASTING → REHEARSING`) is the OCC-guarded
    write of §2.5: the request must carry `expected_cast_version` matching the
    cast's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_cast_lock
    """
    reset_clock()
    slot = create_venue_slot(venue_name="M")
    cast = validate_success(api_client.create_ensemble_cast(
        create_ensemble_cast_payload(slot["id"], cast_size=1, understudy_slots=0,
                                     source_policy="OPEN_CALL"), CD), 201)
    student = create_student()
    aud = validate_success(api_client.create_audition(
        create_audition_payload(student["id"], "ENSEMBLE",
                                ensemble_cast_id=cast["id"],
                                rubric_scores={"scene_work": 9, "characters": 9,
                                               "musicality": 9, "game": 9}), CD), 201)
    validate_success(api_client.open_casting(cast["id"], CD))
    stale_version = validate_success(api_client.get_ensemble_cast(cast["id"], CD))["version"]
    validate_success(api_client.evaluate_audition(aud["id"], CD))
    validate_success(api_client.cast_ensemble(cast["id"], CD))  # bumps cast version
    resp = api_client.lock_cast(cast["id"], stale_version, CD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_error_invoice_overpayment():
    """PRD §3.4: "A payment of `amount_cents` against an invoice must be positive
    and must not push `paid_cents` past `amount_due_cents`: an overpayment is
    rejected with `ERR_INVOICE_OVERPAYMENT` (HTTP 422)."

    Design: Corner/errors/error_invoice_overpayment
    """
    ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
    student = create_student()
    enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
    inv = invoice_id_for_enrollment(enr["id"])
    resp = api_client.pay_tuition_invoice(inv, 10001, FO)
    validate_error(resp, ApiErrorId.ERR_INVOICE_OVERPAYMENT, 422)


def test_error_grades_incomplete_on_showcase_stage():
    """PRD §3.5: "The request carries `grade_by_enrollment`, a map from each
    performing enrollment to `PASS` or `FAIL`, and it must cover every entry of
    `performer_enrollment_ids` — a missing grade rejects the staging with
    `ERR_GRADES_INCOMPLETE` (HTTP 422)."

    Design: Corner/errors/error_grades_incomplete_on_showcase_stage
    """
    reset_clock()
    level = create_level(code="L1W", showcase_required=True)
    term = create_term_draft()
    instructor = create_instructor()
    validate_success(api_client.open_scheduling(term["id"], PD))
    section = validate_success(api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"],
                               capacity=2), PD), 201)
    validate_success(api_client.open_enrollment(term["id"], PD))
    s1 = create_student()
    s2 = create_student()
    e1 = enroll_with_fresh_version(s1["id"], section["id"])
    e2 = enroll_with_fresh_version(s2["id"], section["id"])
    confirm_enrollment(e1["id"])
    confirm_enrollment(e2["id"])
    run_term_to_close(section["id"])
    slot = create_venue_slot(venue_name="M")
    showcase = validate_success(api_client.create_showcase(
        create_showcase_payload(level["id"], term["id"], slot["id"],
                                [e1["id"], e2["id"]]), PD), 201)
    validate_success(api_client.schedule_showcase(showcase["id"], PD))
    resp = api_client.stage_showcase(showcase["id"], {e1["id"]: "PASS"}, PD)
    validate_error(resp, ApiErrorId.ERR_GRADES_INCOMPLETE, 422)


def test_error_unauthorized_role_student_cannot_create_level():
    """PRD §2.1: "A request whose role is not authorized for the target endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/errors/error_unauthorized_role_student_cannot_create_level
    """
    reset_clock()
    resp = api_client.create_curriculum_level(
        create_curriculum_level_payload(code="LX", title="Bad"), STUDENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
