"""Training pipeline: exact-capacity seat boundary, seat compensation on drop,
ops-run waitlist promotion order, and completion granting a pending cert."""
from test_helpers import (
    drop_enrollment,
    get_course,
    get_enrollment,
    parse_iso,
    run_ops_epoch,
    set_clock,
    setup_course_with_volunteers,
    validate_paginated,
    validate_success,
)


def test_enrollment_admitted_up_to_exact_capacity(api):
    """PRD §3.7: "The seat check happens at creation: when `seats_taken` is still below `capacity` the enrollment lands in `ENROLLED` and `seats_taken` increases by 1; when the course is full the enrollment lands in `WAITLISTED` instead"

    Design: Difficulty/boundary_precision_check/course_seat_exact_capacity_boundary
    """
    bundle = setup_course_with_volunteers(capacity=2, num_students=2)
    e1, e2 = bundle["enrollments"]
    assert e1["status"] == "ENROLLED"
    # The second enrollment makes seats_taken hit capacity exactly; the
    # admission predicate is "still below", so it is still ENROLLED.
    assert e2["status"] == "ENROLLED"
    course = get_course(bundle["course"]["id"])
    assert course["seats_taken"] == 2


def test_enrollment_beyond_capacity_waitlists_with_position(api):
    """PRD §3.7: "when the course is full the enrollment lands in `WAITLISTED` instead, and its `waitlist_position` is its 1-based position among the course's waitlisted enrollments ordered by `created_at` ascending — a field that is null for any enrollment not currently waitlisted."

    Design: Difficulty/boundary_precision_check/course_seat_exact_capacity_boundary
    """
    bundle = setup_course_with_volunteers(capacity=2, num_students=3)
    e1, e2, e3 = bundle["enrollments"]
    assert e1["status"] == "ENROLLED"
    assert e2["status"] == "ENROLLED"
    assert e3["status"] == "WAITLISTED"
    assert e3["waitlist_position"] == 1
    course = get_course(bundle["course"]["id"])
    assert course["seats_taken"] == 2


def test_drop_restores_seat_count(api):
    """PRD §3.7: "Dropping an `ENROLLED` enrollment decrements the course's `seats_taken` by 1, so that enroll-then-drop restores the seat count exactly; dropping a waitlisted entry changes no seat count."
    PRD §3.7: "from `ENROLLED` or `WAITLISTED`, an enrollment moves to the terminal `DROPPED` state at the request of the `TrainingDirector` or of the enrolled `Volunteer` acting on their own record — the acting `X-User-ID` must equal the enrollment's `volunteer_id`."

    Design: Difficulty/compensating_invariant/course_seat_compensation
    """
    bundle = setup_course_with_volunteers(capacity=2, num_students=3)
    e1 = bundle["enrollments"][0]
    v1 = bundle["volunteers"][0]
    dropped = drop_enrollment(e1["id"], volunteer_id=v1["id"])
    assert dropped["status"] == "DROPPED"
    course = get_course(bundle["course"]["id"])
    assert course["seats_taken"] == 1


def test_ops_run_promotes_waitlist_into_freed_seat(api):
    """PRD §3.7: "While a course has `seats_taken` below `capacity`, its `WAITLISTED` enrollments are promoted to `ENROLLED` in `created_at` ascending order, each promotion adding 1 to `seats_taken`, until no free seats remain; `waitlist_position` values are recomputed for whoever is still waiting."

    Design: Difficulty/compensating_invariant/course_seat_compensation
    """
    bundle = setup_course_with_volunteers(capacity=2, num_students=3)
    e1, _e2, e3 = bundle["enrollments"]
    v1 = bundle["volunteers"][0]
    drop_enrollment(e1["id"], volunteer_id=v1["id"])
    run_ops_epoch()
    course = get_course(bundle["course"]["id"])
    assert course["seats_taken"] == 2
    promoted = get_enrollment(e3["id"])
    assert promoted["status"] == "ENROLLED"
    assert promoted["waitlist_position"] is None
    dropped = get_enrollment(e1["id"])
    assert dropped["status"] == "DROPPED"


def test_waitlist_promotion_follows_creation_order(api):
    """PRD §2.4: "Sixth, waitlisted training enrollments are promoted into free seats in `created_at` ascending order."
    PRD §3.7: "its `waitlist_position` is its 1-based position among the course's waitlisted enrollments ordered by `created_at` ascending" and "`waitlist_position` values are recomputed for whoever is still waiting."

    Design: Corner/cross_cutting_layers/waitlist_promotion_follows_created_at_order
    """
    # Clock is staggered one second between enrollments so created_at is
    # strictly increasing and the promotion order is fully determined.
    bundle = setup_course_with_volunteers(capacity=2, num_students=4, stagger_clock=True)
    e1, _e2, e3, e4 = bundle["enrollments"]
    v1 = bundle["volunteers"][0]
    assert e3["status"] == "WAITLISTED" and e3["waitlist_position"] == 1
    assert e4["status"] == "WAITLISTED" and e4["waitlist_position"] == 2
    drop_enrollment(e1["id"], volunteer_id=v1["id"])
    run_ops_epoch()
    promoted = get_enrollment(e3["id"])
    assert promoted["status"] == "ENROLLED"
    assert promoted["waitlist_position"] is None
    survivor = get_enrollment(e4["id"])
    assert survivor["status"] == "WAITLISTED"
    assert survivor["waitlist_position"] == 1
    course = get_course(bundle["course"]["id"])
    assert course["seats_taken"] == 2


def test_completion_grants_pending_certification(api, training_director_headers):
    """PRD §3.7: "The director may move an `ENROLLED` enrollment to the terminal `COMPLETED` state only once `current_utc` has reached the course's `starts_at`; completion mints a `Certification` for the volunteer with `kind` copied from `grants_cert_kind`, status `PENDING_VERIFICATION`, `issued_at` stamped at `current_utc`, and `expires_at` set 730 days out (`CERT_GRANT_VALIDITY_DAYS`) — two years of validity that still requires a `SafetyOfficer`'s verification before it counts toward readiness."

    Design: Corner/state_machines/enrollment_completion_grants_pending_cert
    """
    bundle = setup_course_with_volunteers(
        capacity=5, num_students=1, starts_at="2026-09-10T09:00:00Z",
    )
    enrollment = bundle["enrollments"][0]
    student = bundle["volunteers"][0]
    assert enrollment["status"] == "ENROLLED"
    set_clock("2026-09-10T10:00:00Z")  # course has begun
    resp = api.patch_enrollment(
        enrollment["id"], {"status": "COMPLETED"}, training_director_headers
    )
    data = validate_success(resp, 200)
    assert data["status"] == "COMPLETED"
    certs, _meta = validate_paginated(
        api.list_certifications(
            training_director_headers, params={"volunteer_id": student["id"]},
        )
    )
    assert len(certs) == 1
    cert = certs[0]
    assert cert["kind"] == "CHAINSAW"
    assert cert["status"] == "PENDING_VERIFICATION"
    assert parse_iso(cert["issued_at"]) == parse_iso("2026-09-10T10:00:00Z")
    # current_utc 2026-09-10T10:00:00Z + 730 days (spans the 2028 leap day).
    assert parse_iso(cert["expires_at"]) == parse_iso("2028-09-09T10:00:00Z")
