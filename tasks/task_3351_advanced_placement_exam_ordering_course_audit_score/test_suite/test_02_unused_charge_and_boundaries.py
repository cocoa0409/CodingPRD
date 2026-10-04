"""The unused-exam charge and the two numeric boundaries that pin it."""
from test_helpers import (
    ApiErrorId,
    LATE_WINDOW_CLOSES_UTC,
    MAX_EXAMS_PER_STUDENT,
    NOT_OPEN_LAST_INSTANT_UTC,
    REGULAR_WINDOW_OPENS_UTC,
    api_client,
    create_exam_registration_payload,
    create_registration,
    deliver_order,
    get_registration,
    host_headers,
    setup_confirmed_registration,
    setup_open_order,
    ship_and_receive_materials,
    transition_registration,
    validate_error,
    validate_paginated,
)


def _add_confirmed_registrations(bundle, count, prefix="AP-EXTRA"):
    """Register `count` further exams on an already-received order and confirm them.

    A REGULAR-tier registration carries no assessed late fee, so the explicit
    confirmation is permitted without a fee settlement.
    """
    order, student, school = bundle["order"], bundle["student"], bundle["school"]
    created = []
    for index in range(count):
        registration = create_registration(
            order,
            student,
            school,
            exam_subject=f"{prefix}-{index + 1:02d}",
            registration_tier="REGULAR",
        )
        registration = transition_registration(registration, "CONFIRMED", school=school)
        created.append(registration)
    return created


# --------------------------------------------------------------------------
# The unused-exam charge
# --------------------------------------------------------------------------

def test_unused_exam_charge_charges_every_confirmed_exam_beyond_the_grace_count():
    """PRD §3.3: "A count of one or zero is free; beyond that the chargeable count is the confirmed count minus the grace count of one, multiplied by 27000 cents, so two unused exams cost 27000 cents and three cost 54000."
    PRD §3.3: "It is computed at the moment an order reaches `DELIVERED`, after `order_fee_cents` has been finalized, and it counts the order's registrations still in `CONFIRMED` at that instant."

    Design: Difficulty/combinatorial_formula/unused_charge_evaluation_order_after_fee
    """
    bundle = setup_confirmed_registration(subject="AP-CHEM")
    ship_and_receive_materials(bundle)
    _add_confirmed_registrations(bundle, 3)

    delivered = deliver_order(bundle)

    # Three exams still CONFIRMED at delivery: (3 - 1) * 27000.
    assert delivered["unused_exam_charge_cents"] == 54000, (
        f"three unused exams should cost 54000, got {delivered['unused_exam_charge_cents']}"
    )
    # One delivered exam selects the 1.00 slice, so the charge never enters the fee.
    assert delivered["order_fee_cents"] == 18000


def test_unused_exam_charge_is_27000_for_two_confirmed_exams_and_leaves_the_fee_alone():
    """PRD §3.3: "A count of one or zero is free; beyond that the chargeable count is the confirmed count minus the grace count of one, multiplied by 27000 cents, so two unused exams cost 27000 cents and three cost 54000."
    PRD §3.3: "The charge is never an input to the rebate tier selection, and the count is taken from the registration statuses as they stand at the transition, not from any earlier snapshot."

    Design: Difficulty/combinatorial_formula/unused_charge_evaluation_order_after_fee
    """
    bundle = setup_confirmed_registration(subject="AP-CHEM")
    ship_and_receive_materials(bundle)
    _add_confirmed_registrations(bundle, 2)

    delivered = deliver_order(bundle)

    assert delivered["unused_exam_charge_cents"] == 27000, (
        f"two unused exams should cost 27000, got {delivered['unused_exam_charge_cents']}"
    )
    assert delivered["order_fee_cents"] == 18000, (
        "the unused charge must not feed the rebate tier: one delivered exam is 18000"
    )


# --------------------------------------------------------------------------
# The ordering-window opening edge
# --------------------------------------------------------------------------

def test_registration_is_accepted_at_the_regular_window_opening_instant():
    """PRD §2.4: "Boundary precision is pinned: the opening edge is compared with a strict less-than, so `2026-11-01T00:00:00Z` is already `REGULAR`, while the closing edge of each band is inclusive"
    PRD §3.3: "Acceptance is gated three ways: the ordering-window classification at the logical clock must be `REGULAR` or `LATE`, with `CLOSED` and `NOT_OPEN` refused as `ERR_ORDER_WINDOW_CLOSED`"

    Design: Difficulty/boundary_precision_check/ordering_window_open_edge_is_strictly_less
    """
    bundle = setup_open_order(clock=REGULAR_WINDOW_OPENS_UTC)

    assert bundle["order"]["ordering_window"] == "REGULAR", (
        "the opening instant itself is already REGULAR"
    )
    registration = create_registration(
        bundle["order"], bundle["student"], bundle["school"], exam_subject="AP-CSA"
    )
    assert registration["status"] == "REGISTERED"


def test_registration_is_refused_one_second_before_the_window_opens():
    """PRD §2.4: "Before `2026-11-01T00:00:00Z` the window is `NOT_OPEN`."
    PRD §3.3: "the ordering-window classification at the logical clock must be `REGULAR` or `LATE`, with `CLOSED` and `NOT_OPEN` refused as `ERR_ORDER_WINDOW_CLOSED`"

    Design: Difficulty/boundary_precision_check/ordering_window_open_edge_is_strictly_less
    """
    bundle = setup_open_order(clock=NOT_OPEN_LAST_INSTANT_UTC)
    assert bundle["order"]["ordering_window"] == "NOT_OPEN"

    response = api_client.create_exam_registration(
        create_exam_registration_payload(
            bundle["order"]["id"], bundle["student"]["id"], exam_subject="AP-CSA"
        ),
        host_headers(bundle["school"]),
    )
    validate_error(response, ApiErrorId.ERR_ORDER_WINDOW_CLOSED)

    data, meta = validate_paginated(
        api_client.list_order_registrations(bundle["order"]["id"], host_headers(bundle["school"]))
    )
    assert meta["total_count"] == 0
    assert data == []


# --------------------------------------------------------------------------
# The per-student exam cap
# --------------------------------------------------------------------------

def test_ninth_registration_for_one_student_is_accepted():
    """PRD §2.6: "A student holds at most nine registrations per administration year"
    PRD §3.3: "the student must not already hold nine registrations for the administration year, or the request is refused as `ERR_MAX_EXAMS_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/max_exams_per_student_ninth_registration_boundary
    """
    bundle = setup_open_order()
    registrations = []
    for index in range(MAX_EXAMS_PER_STUDENT):
        registrations.append(
            create_registration(
                bundle["order"],
                bundle["student"],
                bundle["school"],
                exam_subject=f"AP-SUBJ-{index + 1:02d}",
            )
        )

    ninth = get_registration(registrations[8]["id"])
    assert ninth["status"] == "REGISTERED", "the ninth registration must be accepted"


def test_tenth_registration_for_one_student_is_refused():
    """PRD §3.3: "the student must not already hold nine registrations for the administration year, or the request is refused as `ERR_MAX_EXAMS_EXCEEDED`"
    PRD §2.6: "A student holds at most nine registrations per administration year"

    Design: Difficulty/boundary_precision_check/max_exams_per_student_ninth_registration_boundary
    """
    bundle = setup_open_order()
    for index in range(MAX_EXAMS_PER_STUDENT):
        create_registration(
            bundle["order"],
            bundle["student"],
            bundle["school"],
            exam_subject=f"AP-SUBJ-{index + 1:02d}",
        )

    response = api_client.create_exam_registration(
        create_exam_registration_payload(
            bundle["order"]["id"], bundle["student"]["id"], exam_subject="AP-SUBJ-10"
        ),
        host_headers(bundle["school"]),
    )
    validate_error(response, ApiErrorId.ERR_MAX_EXAMS_EXCEEDED)

    data, meta = validate_paginated(
        api_client.list_student_registrations(bundle["student"]["id"], host_headers(bundle["school"]))
    )
    assert meta["total_count"] == MAX_EXAMS_PER_STUDENT
