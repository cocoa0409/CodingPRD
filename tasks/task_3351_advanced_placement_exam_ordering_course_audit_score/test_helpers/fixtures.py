"""Composite setup helpers.

Most interesting rules in this program only become reachable after a long
preamble: a school must be registered, its syllabus audited and approved before
its label authority exists, an order may only open once that authority exists,
exam material only reaches a registration after a full custody round trip, and a
score only exists once a calibrated reader has been recruited. Every helper
below builds such a state from scratch, because the server is restarted with an
empty database before every single test.

All helpers read setup responses through the lenient success reader so that a
broken preamble surfaces as a setup failure rather than as a confusing
assertion further down.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    MID_REGULAR_CLOCK_UTC,
    RELEASE_READY_CLOCK_UTC,
)
from .factories import (
    DEFAULTS,
    create_accommodation_request_payload,
    create_alternate_exam_request_payload,
    create_course_audit_payload,
    create_exam_order_payload,
    create_exam_registration_payload,
    create_exam_score_payload,
    create_irregularity_case_payload,
    create_material_shipment_payload,
    create_reader_payload,
    create_school_payload,
    create_score_send_payload,
    create_student_payload,
)
from .test_users import (
    ACCOMMODATION_REVIEWER,
    ACCOMMODATION_REVIEWER_2,
    COURSE_AUDIT_REVIEWER,
    COURSE_AUDIT_REVIEWER_2,
    INTEGRITY_INVESTIGATOR,
    INTEGRITY_INVESTIGATOR_2,
    PLATFORM_ADMIN,
    SCORING_SPECIALIST,
    TEST_USERS,
    make_accommodation_reviewer_headers,
    make_course_audit_reviewer_headers,
    make_integrity_investigator_headers,
    make_school_coordinator_headers,
    make_scoring_specialist_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["course_audit_reviewer_headers"]
ACCOM_REVIEWER = TEST_USERS["accommodation_reviewer_headers"]
SPECIALIST = TEST_USERS["scoring_specialist_headers"]
INVESTIGATOR = TEST_USERS["integrity_investigator_headers"]


# --------------------------------------------------------------------------
# Identity threading
# --------------------------------------------------------------------------

def host_headers(school: dict) -> dict:
    """The acting SchoolCoordinator identity for an ownership-gated call."""
    return make_school_coordinator_headers(school["id"])


# --------------------------------------------------------------------------
# Tier 0: the logical clock
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock to an instant at or after its startup."""
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Tier 1: state progression
# --------------------------------------------------------------------------

def create_school(**overrides) -> dict:
    return get_success_data(api_client.create_school(create_school_payload(**overrides), ADMIN))


def get_school(school_id: str) -> dict:
    return get_success_data(api_client.get_school(school_id, ADMIN))


def create_audit(school: dict, **overrides) -> dict:
    payload = create_course_audit_payload(school["id"], **overrides)
    return get_success_data(api_client.create_course_audit(payload, host_headers(school)))


def take_audit_into_review(audit: dict, reviewer_headers: dict = None) -> dict:
    headers = reviewer_headers or REVIEWER
    return get_success_data(
        api_client.transition_course_audit(
            audit["id"],
            {"to_status": "IN_REVIEW", "expected_course_audit_version": audit["version"]},
            headers,
        )
    )


def approve_audit(audit: dict, reviewer_headers: dict = None, notes: str = None) -> dict:
    headers = reviewer_headers or REVIEWER
    return get_success_data(
        api_client.transition_course_audit(
            audit["id"],
            {
                "to_status": "APPROVED",
                "expected_course_audit_version": audit["version"],
                "decision_notes": notes or DEFAULTS["DECISION_NOTES"],
            },
            headers,
        )
    )


def request_audit_revision(audit: dict, reviewer_headers: dict = None, notes: str = None) -> dict:
    headers = reviewer_headers or REVIEWER
    return get_success_data(
        api_client.transition_course_audit(
            audit["id"],
            {
                "to_status": "REVISION_REQUESTED",
                "expected_course_audit_version": audit["version"],
                "decision_notes": notes or "resubmit with the lab component",
            },
            headers,
        )
    )


def resubmit_audit(audit: dict, school: dict, new_hash: str) -> dict:
    return get_success_data(
        api_client.transition_course_audit(
            audit["id"],
            {
                "to_status": "SUBMITTED",
                "expected_course_audit_version": audit["version"],
                "syllabus_hash": new_hash,
            },
            host_headers(school),
        )
    )


def setup_approved_school(school_overrides: dict = None) -> dict:
    """Register a school, audit one syllabus through to APPROVED, return both rows.

    The approval flips program_label_authorized true and is the precondition for
    every order, shipment and designation operation downstream.
    """
    school = create_school(**(school_overrides or {}))
    audit = create_audit(school)
    audit = take_audit_into_review(audit)
    audit = approve_audit(audit)
    return {"school": get_school(school["id"]), "audit": audit}


def create_student(school: dict, **overrides) -> dict:
    payload = create_student_payload(school["id"], **overrides)
    return get_success_data(api_client.create_student(payload, host_headers(school)))


def create_order(school: dict, audit: dict, **overrides) -> dict:
    payload = create_exam_order_payload(school["id"], audit["id"], **overrides)
    return get_success_data(api_client.create_exam_order(payload, host_headers(school)))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_exam_order(order_id, ADMIN))


def transition_order(order: dict, to_status: str, extra: dict = None, headers: dict = None):
    """Drive one order transition against the row's current server-side version.

    An order's version advances on every registration write, so a caller's
    in-memory copy routinely predates the row it names; the version presented to
    the OCC gate is therefore re-read rather than taken from the local dict.
    """
    current = get_order(order["id"])
    payload = {"to_status": to_status, "expected_exam_order_version": current["version"]}
    if extra:
        payload.update(extra)
    return get_success_data(
        api_client.transition_exam_order(current["id"], payload, headers or ADMIN)
    )


def open_order(order: dict, school: dict = None) -> dict:
    headers = host_headers(school) if school else None
    return transition_order(order, "OPEN", headers=headers)


def create_registration(order: dict, student: dict, school: dict = None, **overrides) -> dict:
    payload = create_exam_registration_payload(order["id"], student["id"], **overrides)
    headers = host_headers(school) if school else None
    return get_success_data(api_client.create_exam_registration(payload, headers or ADMIN))


def get_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_exam_registration(registration_id, ADMIN))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, ADMIN))


def get_accommodation(request_id: str) -> dict:
    return get_success_data(api_client.get_accommodation_request(request_id, ADMIN))


def transition_registration(registration: dict, to_status: str, extra: dict = None, school: dict = None):
    payload = {"to_status": to_status}
    if extra:
        payload.update(extra)
    headers = host_headers(school) if school else None
    return get_success_data(
        api_client.transition_exam_registration(registration["id"], payload, headers or ADMIN)
    )


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy — approved school + student + open order
# --------------------------------------------------------------------------

def setup_open_order(
    clock: str = MID_REGULAR_CLOCK_UTC,
    school_overrides: dict = None,
    student_overrides: dict = None,
    order_overrides: dict = None,
) -> dict:
    """Approved school, one enrolled student and an OPEN exam order."""
    school = create_school(**(school_overrides or {}))
    if clock:
        set_clock(clock)
    audit = create_audit(school)
    audit = take_audit_into_review(audit)
    audit = approve_audit(audit)
    school = get_school(school["id"])
    student = create_student(school, **(student_overrides or {}))
    order = create_order(school, audit, **(order_overrides or {}))
    order = open_order(order, school)
    return {"school": school, "audit": audit, "student": student, "order": order}


def setup_confirmed_registration(
    subject: str = "AP-CALC-AB",
    tier: str = "REGULAR",
    clock: str = MID_REGULAR_CLOCK_UTC,
    **kwargs,
) -> dict:
    """Approved school + OPEN order + one CONFIRMED registration."""
    bundle = setup_open_order(clock=clock, **kwargs)
    registration = create_registration(
        bundle["order"],
        bundle["student"],
        bundle["school"],
        exam_subject=subject,
        registration_tier=tier,
    )
    registration = transition_registration(registration, "CONFIRMED", school=bundle["school"])
    bundle["registration"] = registration
    return bundle


def setup_fee_pending_registration(
    subject: str = "AP-STAT",
    clock: str = MID_REGULAR_CLOCK_UTC,
    **kwargs,
) -> dict:
    """Approved school + OPEN order + a LATE-tier registration in FEE_PENDING."""
    bundle = setup_open_order(clock=clock, **kwargs)
    registration = create_registration(
        bundle["order"],
        bundle["student"],
        bundle["school"],
        exam_subject=subject,
        registration_tier="LATE",
    )
    registration = transition_registration(registration, "FEE_PENDING", school=bundle["school"])
    bundle["registration"] = registration
    return bundle


# --------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — custody round trip to MATERIAL_ASSIGNED
# --------------------------------------------------------------------------

def create_shipment(school: dict, order: dict, **overrides) -> dict:
    payload = create_material_shipment_payload(school["id"], order["id"], **overrides)
    return get_success_data(api_client.create_material_shipment(payload, ADMIN))


def transition_shipment(
    shipment: dict, to_status: str, extra: dict = None, headers: dict = None
) -> dict:
    payload = {"to_status": to_status}
    if extra:
        payload.update(extra)
    return get_success_data(
        api_client.transition_material_shipment(shipment["id"], payload, headers or ADMIN)
    )


def ship_and_receive_materials(bundle: dict, seal_intact: bool = True) -> dict:
    """Walk SUBMITTED -> MATERIALS_SHIPPED -> MATERIALS_RECEIVED for one shipment.

    The custody chain is dispatched, scanned in transit and received with an
    intact seal, so the sequence 1..n is gap-free at the receipt. An order that
    has already been submitted is left on its `SUBMITTED` row rather than
    re-submitted, since `SUBMITTED -> SUBMITTED` is not an edge of the machine.
    """
    school, order = bundle["school"], get_order(bundle["order"]["id"])
    shipment = create_shipment(school, order)
    if order["status"] == "OPEN":
        order = transition_order(order, "SUBMITTED", headers=host_headers(school))
    order = transition_order(order, "MATERIALS_SHIPPED")
    shipment = transition_shipment(shipment, "DISPATCHED")
    shipment = transition_shipment(shipment, "IN_TRANSIT")
    shipment = transition_shipment(
        shipment, "RECEIVED", {"seal_intact": seal_intact}, headers=host_headers(school)
    )
    order = transition_order(order, "MATERIALS_RECEIVED")
    bundle["order"] = order
    bundle["shipment"] = shipment
    if bundle.get("registration"):
        bundle["registration"] = get_registration(bundle["registration"]["id"])
    if bundle.get("registrations"):
        bundle["registrations"] = [get_registration(reg["id"]) for reg in bundle["registrations"]]
    return bundle


def receive_materials(bundle: dict, seal_intact: bool = True) -> dict:
    return ship_and_receive_materials(bundle, seal_intact=seal_intact)


def deliver_order(bundle: dict) -> dict:
    """MATERIALS_RECEIVED -> DELIVERED, which settles the fee and unused charge."""
    bundle["order"] = transition_order(bundle["order"], "DELIVERED")
    return bundle["order"]


def setup_order_with_registrations(
    tiers,
    subject_prefix: str = "AP-SUBJ",
    clock: str = MID_REGULAR_CLOCK_UTC,
    confirm: bool = True,
    **kwargs,
) -> dict:
    """Approved school + OPEN order + one registration per entry in `tiers`.

    A student may hold at most nine registrations per administration year, so
    the list is spread over as many students as it needs.
    """
    bundle = setup_open_order(clock=clock, **kwargs)
    school, order = bundle["school"], bundle["order"]
    students = [bundle["student"]]
    registrations = []
    for index, tier in enumerate(tiers):
        if index and index % 9 == 0:
            students.append(create_student(school))
        student = students[index // 9]
        registration = create_registration(
            order,
            student,
            school,
            exam_subject=f"{subject_prefix}-{index + 1:02d}",
            registration_tier=tier,
        )
        if confirm:
            registration = transition_registration(registration, "CONFIRMED", school=school)
        registrations.append(registration)
    bundle["registrations"] = registrations
    bundle["order"] = get_order(order["id"])
    return bundle


def list_sends_for_score(score_id: str, school: dict = None, **params) -> dict:
    query = {"exam_score_id": score_id}
    query.update(params)
    headers = host_headers(school) if school else None
    return get_success_data(api_client.list_score_sends(headers or SPECIALIST, params=query))


def find_case_for_registration(registration_id: str, headers: dict = None) -> dict:
    """Read the cases opened against one registration through the nested read."""
    from prd_bench_local_runner.testing import validate_paginated

    data, _meta = validate_paginated(
        api_client.list_registration_irregularity_cases(
            registration_id, headers or INVESTIGATOR, params={"limit": 100}
        )
    )
    return data[0] if data else {}


def get_alternate(registration_id: str, school: dict = None, **params) -> dict:
    headers = host_headers(school) if school else None
    return get_success_data(
        api_client.list_registration_alternate_requests(
            registration_id, headers or ADMIN, params=params or None
        )
    )


def setup_material_assigned_registration(
    subject: str = "AP-CALC-AB",
    tier: str = "REGULAR",
    clock: str = MID_REGULAR_CLOCK_UTC,
    **kwargs,
) -> dict:
    """Approved school + order + registration walked through to MATERIAL_ASSIGNED."""
    bundle = setup_confirmed_registration(subject=subject, tier=tier, clock=clock, **kwargs)
    return receive_materials(bundle)


# --------------------------------------------------------------------------
# Tier 3b: reader recruitment, calibration and the score row
# --------------------------------------------------------------------------

def recruit_reader(subject: str = "AP-CALC-AB", **overrides) -> dict:
    payload = create_reader_payload(subject_expertise=subject, **overrides)
    return get_success_data(api_client.create_reader(payload, SPECIALIST))


def calibrate_reader(reader: dict, samples: int = 20, agreement: float = 0.9000) -> dict:
    get_success_data(
        api_client.transition_reader(reader["id"], {"to_status": "CALIBRATING"}, SPECIALIST)
    )
    return get_success_data(
        api_client.transition_reader(
            reader["id"],
            {
                "to_status": "CALIBRATED",
                "calibration_sample_count": samples,
                "calibration_agreement_rate": agreement,
            },
            SPECIALIST,
        )
    )


def setup_calibrated_reader(
    subject: str = "AP-CALC-AB",
    samples: int = 20,
    agreement: float = 0.9000,
    **reader_overrides,
) -> dict:
    return calibrate_reader(
        recruit_reader(subject, **reader_overrides), samples=samples, agreement=agreement
    )


def create_score(registration: dict, reader: dict = None, raw_composite: float = 96.0, **overrides) -> dict:
    payload = create_exam_score_payload(registration["id"], raw_composite=raw_composite, **overrides)
    if reader is not None:
        payload["reader_id"] = reader["id"]
    return get_success_data(api_client.create_exam_score(payload, SPECIALIST))


def transition_score(score: dict, to_status: str, extra: dict = None) -> dict:
    payload = {"to_status": to_status, "expected_exam_score_version": score["version"]}
    if extra:
        payload.update(extra)
    return get_success_data(api_client.transition_exam_score(score["id"], payload, SPECIALIST))


def get_score(score_id: str) -> dict:
    return get_success_data(api_client.get_exam_score(score_id, SPECIALIST))


def advance_score_to(score: dict, target: str) -> dict:
    """Walk a score row forward through the ordered part of its machine."""
    order = ["RUBRIC_PENDING", "AGGREGATED", "RELEASED"]
    current = score["status"]
    if current == target:
        return score
    start = order.index(current) if current in order else -1
    for step in order[start + 1 : order.index(target) + 1]:
        score = transition_score(score, step)
    return score


def setup_aggregated_score(
    subject: str = "AP-CALC-AB",
    raw_composite: float = 96.0,
    clock: str = MID_REGULAR_CLOCK_UTC,
    reader_samples: int = 20,
    reader_agreement: float = 0.9000,
    **kwargs,
) -> dict:
    """Everything up to an AGGREGATED score whose registration is SCORED."""
    bundle = setup_material_assigned_registration(subject=subject, clock=clock, **kwargs)
    reader = calibrate_reader(
        recruit_reader(subject), samples=reader_samples, agreement=reader_agreement
    )
    score = create_score(bundle["registration"], reader, raw_composite=raw_composite)
    score = transition_score(score, "RUBRIC_PENDING")
    score = transition_score(score, "AGGREGATED")
    bundle.update({"reader": reader, "score": score})
    bundle["registration"] = get_registration(bundle["registration"]["id"])
    return bundle


def setup_released_score(
    subject: str = "AP-CALC-AB",
    raw_composite: float = 96.0,
    clock: str = MID_REGULAR_CLOCK_UTC,
    release_clock: str = RELEASE_READY_CLOCK_UTC,
    reader_samples: int = 20,
    reader_agreement: float = 0.9000,
    **kwargs,
) -> dict:
    """Everything up to a RELEASED score on a SCORE_RELEASED registration."""
    bundle = setup_aggregated_score(
        subject=subject,
        raw_composite=raw_composite,
        clock=clock,
        reader_samples=reader_samples,
        reader_agreement=reader_agreement,
        **kwargs,
    )
    if release_clock:
        set_clock(release_clock)
    score = transition_score(bundle["score"], "RELEASED")
    bundle["score"] = score
    bundle["registration"] = get_registration(bundle["registration"]["id"])
    return bundle


# --------------------------------------------------------------------------
# Tier 3c: score sends, irregularity cases, alternates, accommodations
# --------------------------------------------------------------------------

def create_send(score: dict, school: dict = None, **overrides) -> dict:
    payload = create_score_send_payload(score["id"], **overrides)
    headers = host_headers(school) if school else None
    return get_success_data(api_client.create_score_send(payload, headers or SPECIALIST))


def transition_send(send: dict, to_status: str, extra: dict = None, school: dict = None) -> dict:
    payload = {"to_status": to_status}
    if extra:
        payload.update(extra)
    headers = host_headers(school) if school else None
    return get_success_data(
        api_client.transition_score_send(send["id"], payload, headers or SPECIALIST)
    )


def get_send(send_id: str, school: dict = None) -> dict:
    headers = host_headers(school) if school else None
    return get_success_data(api_client.get_score_send(send_id, headers or SPECIALIST))


def open_case(
    registration: dict,
    school: dict,
    irregularity_type: str = "UNAUTHORIZED_DEVICE",
    headers: dict = None,
    **overrides,
) -> dict:
    payload = create_irregularity_case_payload(
        registration["id"], school["id"], irregularity_type=irregularity_type, **overrides
    )
    return get_success_data(api_client.create_irregularity_case(payload, headers or INVESTIGATOR))


def transition_case(case: dict, to_status: str, extra: dict = None, headers: dict = None) -> dict:
    payload = {"to_status": to_status}
    if extra:
        payload.update(extra)
    return get_success_data(
        api_client.transition_irregularity_case(case["id"], payload, headers or INVESTIGATOR)
    )


def drive_case_to_decision_pending(
    case: dict, finding_code: str = "NO_FINDING", headers: dict = None, decide_headers: dict = None
) -> dict:
    """OPEN -> INVESTIGATING -> DECISION_PENDING, recording a finding code."""
    case = transition_case(case, "INVESTIGATING", headers=headers)
    case = transition_case(case, "DECISION_PENDING", {"finding_code": finding_code}, headers=headers)
    return case


def create_alternate(registration: dict, school: dict = None, **overrides) -> dict:
    payload = create_alternate_exam_request_payload(registration["id"], **overrides)
    headers = host_headers(school) if school else None
    return get_success_data(api_client.create_alternate_exam_request(payload, headers or ADMIN))


def transition_alternate(
    alternate: dict, to_status: str, extra: dict = None, school: dict = None
) -> dict:
    payload = {
        "to_status": to_status,
        "expected_alternate_exam_request_version": alternate["version"],
    }
    if extra:
        payload.update(extra)
    headers = host_headers(school) if school else None
    return get_success_data(
        api_client.transition_alternate_exam_request(alternate["id"], payload, headers or ADMIN)
    )


def create_accommodation(student: dict, school: dict, **overrides) -> dict:
    payload = create_accommodation_request_payload(student["id"], **overrides)
    return get_success_data(
        api_client.create_accommodation_request(payload, host_headers(school))
    )


def transition_accommodation(
    request: dict, to_status: str, extra: dict = None, headers: dict = None
) -> dict:
    payload = {"to_status": to_status}
    if extra:
        payload.update(extra)
    return get_success_data(
        api_client.transition_accommodation_request(
            request["id"], payload, headers or ACCOM_REVIEWER
        )
    )
