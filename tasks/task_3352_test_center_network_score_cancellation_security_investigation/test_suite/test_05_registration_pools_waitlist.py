"""Registration pools, waitlist boundary, promotion order, immediate consistency."""
from test_helpers import (
    ApiErrorId,
    add_staff,
    api_client,
    assert_registration,
    create_authorized_center,
    create_examinee,
    create_published_session,
    get_registration,
    get_session,
    register_examinee,
    register_new_examinee,
    setup_bookable_session,
    validate_success,
)
from test_helpers import (
    make_examinee_headers,
    make_program_admin_headers,
)
from test_helpers import (
    create_accommodation_request_payload,
    decide_accommodation_payload,
)


def test_registration_initial_dimensions(api):
    """PRD §3.3: "When occupancy is below the pool size, the registration is
    created `CONFIRMED` with `attendance_status` `PENDING` and the session's
    `confirmed_count` increases by 1. A confirmed registration's
    `waitlist_position` is null — the field is only ever set while
    `booking_status` is `WAITLISTED`, and it returns to null on promotion or
    cancellation."

    Design: Corner/state_machines/registration_initial_dimensions
    """
    ctx = setup_bookable_session(name="Center IN", total_seats=5)
    examinee, registration = register_new_examinee(
        ctx["session"]["id"], full_name="Ex IN", id_document_number="PIN1"
    )
    assert_registration(registration)
    assert registration["booking_status"] == "CONFIRMED"
    assert registration["attendance_status"] == "PENDING"
    assert registration["waitlist_position"] is None
    assert registration["pool"] == "GENERAL"


def test_registration_computed_pool_for_accommodation_examinee(api):
    """PRD §3.3: "computes `requires_accommodation_seat` as true exactly when
    the examinee holds at least one `APPROVED` accommodation request at that
    moment, and derives the registration's `pool` as `ACCOMMODATION` when that
    flag is true and `GENERAL` otherwise."
    PRD §3.3: "Two types — `SCREEN_READER` and `LARGE_PRINT` — call for
    alternate-format test delivery, so the system derives
    `requires_alternate_format` as true for exactly those two types and false
    for the others."
    PRD §3.2: "Its `effective_general_cap` — the ceiling on confirmed
    general-pool bookings — is computed as `total_seats` minus
    `reserved_accommodation_seats` and tracks those fields."

    Design: Corner/entities/registration_computed_pool_for_accommodation_examinee
    """
    ctx = setup_bookable_session(name="Center AC", total_seats=3,
                                 reserved_accommodation_seats=1)
    assert ctx["session"]["effective_general_cap"] == 2, "3 - 1"
    examinee = create_examinee(full_name="Ex AC", id_document_number="PAC1")
    request = validate_success(
        api.create_accommodation_request(
            examinee["id"],
            create_accommodation_request_payload("SCREEN_READER"),
            make_examinee_headers(examinee["id"]),
        ),
        201,
    )
    assert request["requires_alternate_format"] is True, "SCREEN_READER"
    decided = validate_success(
        api.decide_accommodation_request(
            request["id"],
            decide_accommodation_payload("APPROVED"),
            make_program_admin_headers("admin-1"),
        ),
        200,
    )
    assert decided["status"] == "APPROVED"
    registration = register_examinee(ctx["session"]["id"], examinee["id"])
    assert registration["requires_accommodation_seat"] is True
    assert registration["pool"] == "ACCOMMODATION"
    assert registration["booking_status"] == "CONFIRMED", (
        "accommodation pool occupancy 0 < reserved 1"
    )


def test_capacity_at_cap_third_registrant_waitlisted(api):
    """PRD §3.3: "When occupancy equals the pool size — the boundary is
    inclusive on the full side, never an error — the registration is instead
    created `WAITLISTED`, with `waitlist_position` set to the number of
    already-`WAITLISTED` registrations in the same session and pool plus one,
    and the session's `waitlist_count` increases by 1."

    Design: Difficulty/boundary_precision_check/capacity_at_cap_waitlists_third_registrant
    """
    ctx = setup_bookable_session(name="Center CP", total_seats=2)
    session_id = ctx["session"]["id"]
    register_new_examinee(session_id, full_name="Ex C1", id_document_number="PC01")
    register_new_examinee(session_id, full_name="Ex C2", id_document_number="PC02")
    examinee3, registration3 = register_new_examinee(
        session_id, full_name="Ex C3", id_document_number="PC03"
    )
    # The full pool waitlists: a 201 create, never an error.
    assert registration3["booking_status"] == "WAITLISTED"
    assert registration3["waitlist_position"] == 1, (
        "first position of a previously empty waitlist"
    )


def test_capacity_at_cap_counts_and_confirmed_unchanged(api):
    """PRD §3.3: "When occupancy equals the pool size — the boundary is
    inclusive on the full side, never an error — the registration is instead
    created `WAITLISTED`, with `waitlist_position` set to the number of
    already-`WAITLISTED` registrations in the same session and pool plus one,
    and the session's `waitlist_count` increases by 1."
    PRD §3.2: "Its `effective_general_cap` — the ceiling on confirmed
    general-pool bookings — is computed as `total_seats` minus
    `reserved_accommodation_seats` and tracks those fields."

    Design: Difficulty/boundary_precision_check/capacity_at_cap_waitlists_third_registrant
    """
    ctx = setup_bookable_session(name="Center CP2", total_seats=2)
    session_id = ctx["session"]["id"]
    _, reg1 = register_new_examinee(session_id, full_name="Ex C1",
                                    id_document_number="PC01")
    _, reg2 = register_new_examinee(session_id, full_name="Ex C2",
                                    id_document_number="PC02")
    register_new_examinee(session_id, full_name="Ex C3", id_document_number="PC03")
    session = get_session(session_id)
    assert session["confirmed_count"] == 2, "== effective_general_cap"
    assert session["waitlist_count"] == 1
    assert get_registration(reg1["id"])["booking_status"] == "CONFIRMED"
    assert get_registration(reg2["id"])["booking_status"] == "CONFIRMED"


def test_waitlist_promotion_earliest_created_first(api):
    """PRD §3.3: "exactly one waitlisted registration in the same session and
    pool is promoted: the one with the smallest `created_at` (server-stamped
    at millisecond precision, so ties cannot occur and no further tie-break
    exists). The promoted registration's `waitlist_position` becomes null, its
    `booking_status` becomes `CONFIRMED`, and the remaining waitlisted
    registrations in that pool have their positions recomputed as 1 through n
    in `created_at` ascending order."

    Design: Corner/calculations/waitlist_promotion_earliest_created_first
    """
    ctx = setup_bookable_session(name="Center WP", total_seats=1)
    session_id = ctx["session"]["id"]
    _, reg1 = register_new_examinee(session_id, full_name="Ex W1",
                                    id_document_number="PW01")
    _, reg2 = register_new_examinee(session_id, full_name="Ex W2",
                                    id_document_number="PW02")
    _, reg3 = register_new_examinee(session_id, full_name="Ex W3",
                                    id_document_number="PW03")
    assert reg2["waitlist_position"] == 1 and reg3["waitlist_position"] == 2, (
        "creation order"
    )
    validate_success(
        api.cancel_registration(reg1["id"], make_program_admin_headers("admin-1")),
        200,
    )
    reg2 = get_registration(reg2["id"])
    assert reg2["booking_status"] == "CONFIRMED", "earliest created_at promoted"
    assert reg2["waitlist_position"] is None
    reg3 = get_registration(reg3["id"])
    assert reg3["booking_status"] == "WAITLISTED"
    assert reg3["waitlist_position"] == 1, "recomputed in created_at order"
    session = get_session(session_id)
    assert session["confirmed_count"] == 1
    assert session["waitlist_count"] == 1


def test_registration_create_immediate_visibility(api):
    """PRD §3.3: "When occupancy is below the pool size, the registration is
    created `CONFIRMED` with `attendance_status` `PENDING` and the session's
    `confirmed_count` increases by 1."

    Design: Corner/consistency_model/registration_create_immediate_visibility
    """
    ctx = setup_bookable_session(name="Center IV", total_seats=5)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex IV", id_document_number="PIV1"
    )
    assert registration["booking_status"] == "CONFIRMED", (
        "state visible in the create response itself"
    )
    assert get_session(session_id)["confirmed_count"] == 1, (
        "derived field reconciled synchronously on the next read"
    )
