"""Composite setup helpers. All use lenient get_success_data so a setup failure
surfaces as a clear error instead of a confusing assertion failure."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_curriculum_level_payload, create_term_payload, create_instructor_payload,
    create_section_payload, create_student_payload, create_placement_evaluation_payload,
    create_enrollment_payload, create_venue_slot_payload, create_showcase_payload,
    create_cohort_program_payload, create_audition_payload, create_ensemble_cast_payload,
    create_touring_assignment_payload, create_scholarship_payload,
)
from .test_users import TEST_USERS, make_student_headers
from .constants import BOOT_CLOCK

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]
CD = TEST_USERS["casting_director_headers"]
FO = TEST_USERS["finance_officer_headers"]


def reset_clock():
    """Re-pin the logical clock to its boot value."""
    get_success_data(api_client.set_clock(BOOT_CLOCK, PD))


def set_clock(current_utc):
    get_success_data(api_client.set_clock(current_utc, PD))


def create_level(**overrides):
    data = get_success_data(api_client.create_curriculum_level(
        create_curriculum_level_payload(**overrides), PD))
    return data


def create_level_chain(codes_with_overrides):
    """Create levels where each entry maps code -> overrides (requires_level_code
    handled by caller). Returns dict code -> level data."""
    out = {}
    for code, ov in codes_with_overrides.items():
        ov = dict(ov)
        ov["code"] = code
        out[code] = create_level(**ov)
    return out


def create_student(**overrides):
    return get_success_data(api_client.create_student(create_student_payload(**overrides), REG))


def create_students(n):
    return [create_student() for _ in range(n)]


def create_term_draft(**overrides):
    return get_success_data(api_client.create_term(create_term_payload(**overrides), PD))


def create_instructor(**overrides):
    return get_success_data(api_client.create_instructor(create_instructor_payload(**overrides), PD))


def get_section(section_id):
    return get_success_data(api_client.get_section(section_id, REG))


def get_term(term_id):
    return get_success_data(api_client.get_term(term_id, PD))


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, REG))


def get_student(student_id):
    return get_success_data(api_client.get_student(student_id, REG))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_tuition_invoice(invoice_id, FO))


def get_cast(cast_id):
    return get_success_data(api_client.get_ensemble_cast(cast_id, CD))


def get_venue_slot(slot_id):
    return get_success_data(api_client.get_venue_slot(slot_id, PD))


def get_placement(pe_id):
    return get_success_data(api_client.get_placement_evaluation(pe_id, PO))


def get_scholarship(sch_id):
    return get_success_data(api_client.get_scholarship(sch_id, FO))


def get_tour(tour_id):
    return get_success_data(api_client.get_touring_assignment(tour_id, CD))


def setup_open_term_with_section(capacity=4, tuition_cents=10000, level_overrides=None,
                                 weekly_hours=3):
    """Term brought DRAFT -> SCHEDULING -> ENROLLMENT_OPEN with one section created
    during SCHEDULING (cascades to OPEN). Returns dict with term, level, instructor,
    section (post-cascade re-fetched)."""
    reset_clock()
    level = create_level(**(level_overrides or {}))
    term = create_term_draft()
    instructor = create_instructor()
    get_success_data(api_client.open_scheduling(term["id"], PD))
    section = get_success_data(api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"],
                               capacity=capacity, tuition_cents=tuition_cents,
                               weekly_hours=weekly_hours), PD))
    get_success_data(api_client.open_enrollment(term["id"], PD))
    section = get_section(section["id"])
    return {"term": term, "level": level, "instructor": instructor, "section": section}


def enroll_with_fresh_version(student_id, section_id, priority_tier=None, headers=None):
    """GET the section to read its current version, then POST the enrollment with
    expected_section_version matching. Returns the created enrollment data."""
    section = get_section(section_id)
    payload = create_enrollment_payload(student_id, section_id, section["version"])
    if priority_tier is not None:
        payload["priority_tier"] = priority_tier
    return get_success_data(api_client.create_enrollment(payload, headers or REG))


def confirm_enrollment(enrollment_id):
    return get_success_data(api_client.confirm_enrollment(enrollment_id, REG))


def drop_enrollment(enrollment_id):
    return get_success_data(api_client.drop_enrollment(enrollment_id, REG))


def invoice_id_for_enrollment(enrollment_id):
    resp = api_client.list_tuition_invoices(FO, params={"enrollment_id": enrollment_id})
    body = resp.json()
    data = body.get("data", [])
    assert isinstance(data, list) and len(data) >= 1, \
        f"expected an invoice for enrollment {enrollment_id}"
    return data[0]["id"]


def pay_invoice(invoice_id, amount_cents):
    return get_success_data(api_client.pay_tuition_invoice(invoice_id, amount_cents, FO))


def grant_placement(student_id, target_level_id, prior_institution="UCB",
                    portfolio_score=0, track="IMPROV"):
    """Create -> begin-review -> grant a placement evaluation. Returns the granted
    evaluation data."""
    pe = get_success_data(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(
            student_id, target_level_id, track=track,
            prior_institution=prior_institution, portfolio_score=portfolio_score), PO))
    get_success_data(api_client.begin_review_placement(pe["id"], PO))
    return get_success_data(api_client.grant_placement(pe["id"], PO))


def run_term_to_close(section_id):
    """Given a section in OPEN with enrollments confirmed as needed by the caller,
    move the parent term to CLOSED. Returns the closed term data."""
    section = get_section(section_id)
    term_id = section["term_id"]
    get_success_data(api_client.start_session(term_id, PD))
    return get_success_data(api_client.close_term(term_id, PD))


def create_venue_slot(**overrides):
    return get_success_data(api_client.create_venue_slot(
        create_venue_slot_payload(**overrides), PD))


def create_evaluated_audition(student_id, target_kind="ENSEMBLE",
                              ensemble_cast_id=None, cohort_program_id=None,
                              rubric_scores=None):
    """Create an audition and evaluate it. Returns the EVALUATED audition data."""
    overrides = {}
    if ensemble_cast_id is not None:
        overrides["ensemble_cast_id"] = ensemble_cast_id
    if cohort_program_id is not None:
        overrides["cohort_program_id"] = cohort_program_id
    aud = get_success_data(api_client.create_audition(
        create_audition_payload(student_id, target_kind,
                                rubric_scores=rubric_scores, **overrides), CD))
    return get_success_data(api_client.evaluate_audition(aud["id"], CD))


def create_cast_and_fill(cast_size=1, understudy_slots=0, rubric_scores_list=None,
                         source_policy="OPEN_CALL"):
    """Create a venue slot + cast + open casting, evaluate one audition per
    principal+understudy slot, then run the selector. Returns (cast, slot, auditions)."""
    reset_clock()
    slot = create_venue_slot()
    cast = get_success_data(api_client.create_ensemble_cast(
        create_ensemble_cast_payload(slot["id"], cast_size=cast_size,
                                     understudy_slots=understudy_slots,
                                     source_policy=source_policy), CD))
    get_success_data(api_client.open_casting(cast["id"], CD))
    n = cast_size + understudy_slots
    auditions = []
    for i in range(n):
        student = create_student()
        scores = (rubric_scores_list[i] if rubric_scores_list else None)
        auditions.append(create_evaluated_audition(
            student["id"], "ENSEMBLE", ensemble_cast_id=cast["id"],
            rubric_scores=scores))
    cast = get_success_data(api_client.cast_ensemble(cast["id"], CD))
    return cast, slot, auditions


def setup_completed_student_no_showcase():
    """Drive one student through a full no-showcase level: returns dict with
    term, level, section, student, enrollment (now CREDITED)."""
    ctx = setup_open_term_with_section(capacity=1)
    student = create_student()
    enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
    confirm_enrollment(enr["id"])
    run_term_to_close(ctx["section"]["id"])
    ctx["student"] = get_student(student["id"])
    ctx["enrollment"] = get_enrollment(enr["id"])
    return ctx


def setup_staged_showcase(level_code="L1S"):
    """Full path: showcase-required level, enrollment completed at term close,
    manual showcase created + scheduled + staged PASS. Returns context dict."""
    reset_clock()
    level = create_level(code=level_code, showcase_required=True)
    term = create_term_draft()
    instructor = create_instructor()
    get_success_data(api_client.open_scheduling(term["id"], PD))
    section = get_success_data(api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"],
                               capacity=1), PD))
    get_success_data(api_client.open_enrollment(term["id"], PD))
    student = create_student()
    enr = enroll_with_fresh_version(student["id"], section["id"])
    confirm_enrollment(enr["id"])
    run_term_to_close(section["id"])
    slot = create_venue_slot()
    showcase = get_success_data(api_client.create_showcase(
        create_showcase_payload(level["id"], term["id"], slot["id"], [enr["id"]]), PD))
    get_success_data(api_client.schedule_showcase(showcase["id"], PD))
    return {
        "level": level, "term": term, "section": get_section(section["id"]),
        "student": student, "enrollment": get_enrollment(enr["id"]),
        "slot": slot, "showcase": get_success_data(
            api_client.get_showcase(showcase["id"], PD)),
    }
