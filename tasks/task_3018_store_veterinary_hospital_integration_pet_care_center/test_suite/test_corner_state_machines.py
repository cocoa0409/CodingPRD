"""Lifecycle guards: what a state forbids, and what a terminal state ends."""

from test_helpers import (
    ApiErrorId,
    cancel_booking,
    check_in,
    create_encounter,
    create_prescription,
    disable_bay,
    get_success_data,
    pause_package,
    read_store,
    read_visit,
    resume_package,
    restrict_store,
    saturate_to_capacity,
    start_exam,
    setup_bay_with_two_grooming_bookings,
    setup_completed_grooming_booking,
    setup_confirmed_booking,
    setup_member_with_package,
    setup_visit_with_certificate,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_disable_is_refused_while_a_booking_of_the_bay_is_still_live(api):
    """The bay may not leave the schedule while it holds a live commitment.

    PRD §3.1: "Disabling a bay is an irreversible act available only while the bay
    holds no live commitment: if any booking of that bay is still `REQUESTED`,
    `SCREENED`, `BAY_CONFIRMED` or `IN_SERVICE`, the request is refused with
    `ERR_BAY_HAS_ACTIVE_BOOKINGS`."
    PRD §3.1: "Bays are the units of shared-space contention"

    Design: Corner/state_machines/bay_disable_rejected_while_a_booking_is_still_open
    """
    world = setup_confirmed_booking(api, pet=("Clove", "FELINE", "Siamese", 3.6))
    store_id = world["store"]["id"]
    bay = get_success_data(api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN))

    response = api.disable_service_bay(
        store_id, bay["id"], {"expected_bay_version": bay["version"]}, MANAGER
    )
    validate_error(response, ApiErrorId.BAY_HAS_ACTIVE_BOOKINGS.value)

    unchanged = get_success_data(api.get_store_service_bay(store_id, bay["id"], ADMIN))
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == bay["version"]


def test_disable_succeeds_once_the_bays_last_live_booking_clears(api):
    """With the booking completed the identical request is admitted.

    PRD §3.1: "When the last live booking clears, the bay moves to `DISABLED`,
    which is terminal, and it never returns to the schedule."
    PRD §3.1: "Attempting to disable a bay that is not `ACTIVE` is refused with
    `ERR_BAY_NOT_ACTIVE`."

    Design: Corner/state_machines/bay_disable_rejected_while_a_booking_is_still_open
    """
    world = setup_completed_grooming_booking(api, pet=("Clove", "FELINE", "Siamese", 3.6))
    store_id = world["store"]["id"]
    bay = get_success_data(api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN))

    disabled = disable_bay(api, store_id, bay)
    assert disabled["status"] == "DISABLED"
    assert disabled["version"] > bay["version"]

    again = api.disable_service_bay(
        store_id, bay["id"], {"expected_bay_version": disabled["version"]}, MANAGER
    )
    validate_error(again, ApiErrorId.BAY_NOT_ACTIVE.value)


def test_a_cancelled_booking_cannot_be_confirmed_again(api):
    """CANCELLED has no outbound transition, so the confirmation is refused.

    PRD §3.2: "A confirmed booking may also be cancelled, which requires the
    booking to still be in `BAY_CONFIRMED` and is refused with
    `ERR_BOOKING_NOT_CANCELLABLE` otherwise"
    PRD §3.2: "A grooming booking must be in `SCREENED` to be confirmed and a
    non-grooming booking must not be, refused with `ERR_BOOKING_NOT_SCREENED` in
    either case where the check fails."
    PRD §3.2: "Confirmation is a `StoreManager` act"

    Design: Corner/state_machines/second_confirm_bay_after_cancellation_is_an_invalid_from
    """
    world = setup_confirmed_booking(api, pet=("Drift", "CANINE", "Whippet", 11.5))
    store_id = world["store"]["id"]
    confirmed = world["booking"]
    cancelled = cancel_booking(api, store_id, confirmed)
    assert cancelled["status"] == "CANCELLED"

    response = api.confirm_bay(
        store_id,
        confirmed["id"],
        {
            "expected_booking_version": cancelled["version"],
            "expected_pet_version": cancelled["pet_version"],
        },
        MANAGER,
    )
    validate_error(response, ApiErrorId.BOOKING_NOT_SCREENED.value)
    assert get_success_data(api.get_booking(confirmed["id"], ADMIN))["status"] == "CANCELLED"


def test_a_blocked_visit_cannot_be_reported_and_owes_nothing(api):
    """BLOCKED is terminal and sets the visit's reporting status to NOT_REQUIRED.

    PRD §3.7: "A visit that never becomes reportable at all — one blocked while
    it was merely `REGISTERED` — has its `state_report_status` set to
    `NOT_REQUIRED`, distinguishing a visit that owed nothing from one that owes
    something still unpaid."
    PRD §3.7: "Submitting the report is a `ComplianceOfficer` act. It requires the
    visit to be in `REPORT_REQUIRED`, refused with `ERR_VISIT_NOT_REPORTABLE`
    otherwise"
    PRD §3.7: "A deadline that passes without a submission does not move the visit
    out of `REPORT_REQUIRED`"

    Design: Corner/state_machines/vaccination_visit_terminal_state_locks_reporting
    """
    world = setup_visit_with_certificate(api, state_code="CA", hospital_capacity=1)
    store_id = world["store"]["id"]
    visit = world["visit"]
    assert visit["status"] == "REPORT_REQUIRED"

    store = saturate_to_capacity(api, store_id, hospital_capacity=1)
    restrict_store(api, store_id, store["version"])

    blocked = read_visit(api, visit["id"])
    assert blocked["status"] == "BLOCKED"
    assert blocked["state_report_status"] == "NOT_REQUIRED"

    # A refused submission is checked on the raw response rather than through the
    # success-asserting fixture.
    response = api.submit_state_report(
        store_id,
        blocked["id"],
        {"expected_visit_version": blocked["version"]},
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.VISIT_NOT_REPORTABLE.value)


def test_a_new_prescription_is_pending_its_exam_and_charges_nothing_yet(api):
    """The prescription carries no frozen price before the exam completes.

    PRD §3.5: "The new prescription starts in `PENDING_EXAM`, which is a
    statement that the examination has not yet concluded, and its `retail_facing`
    flag is set true permanently, marking it as the one hospital-originated record
    the retail side is allowed to read."
    PRD §3.5: "Its `price_at_authorization_cents` is deferred: nothing is frozen
    until the examination completes."

    Design: Corner/state_machines/prescription_authorization_initial_state_and_charge_zero_before_exam
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="NY", state_sales_tax_rate=0.0887, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    # PRD §3.5 requires the cited encounter to have reached IN_EXAM or beyond
    # before a prescription may be raised, so the row starts PENDING_EXAM only
    # once the exam is under way.
    encounter = check_in(
        api, store_id, create_encounter(
            api, store_id, world["pet"]["id"], scheduled_at="2026-06-15T09:00:00Z"
        )
    )
    encounter = start_exam(api, store_id, encounter)
    prescription = create_prescription(
        api, store_id, world["pet"]["id"], encounter["id"],
        item_type="MEDICATION", item_name="Metronidazole 250mg", sku="SKU-MET-250",
        unit_price_cents=2200, quantity=4,
    )
    assert prescription["status"] == "PENDING_EXAM"
    assert prescription["price_at_authorization_cents"] == 0
    assert prescription["authorized_at"] is None
    assert prescription["retail_facing"] is True
    assert prescription["version"] == 1


def test_a_package_cannot_be_paused_twice_and_the_resume_round_trip_closes(api):
    """PAUSED has no self-loop, so a second pause is refused.

    PRD §3.8: "A package may be paused only while `ACTIVE`, refused with
    `ERR_PACKAGE_NOT_ACTIVE` otherwise, and while paused no cycle may be billed.
    It may be resumed only while `PAUSED`, refused with `ERR_PACKAGE_NOT_PAUSED`
    otherwise."
    PRD §3.8: "Pausing, resuming and cancelling govern the package's life."

    Design: Corner/state_machines/package_billing_cycle_idempotent_pause_and_resume_round_trip
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="FL", state_sales_tax_rate=0.07, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    member_id = world["member"]["id"]
    paused = pause_package(api, store_id, member_id, world["package"])
    assert paused["status"] == "PAUSED"

    response = api.pause_package(
        store_id, member_id, world["package"]["id"],
        {"expected_package_version": paused["version"]}, MANAGER,
    )
    # PRD §3.8: "A package may be paused only while `ACTIVE`, refused with
    # `ERR_PACKAGE_NOT_ACTIVE` otherwise" — the state gate fires before any
    # not-paused reading, because a package that is not ACTIVE is already
    # outside the pause transition's declared source state.
    validate_error(response, ApiErrorId.PACKAGE_NOT_ACTIVE.value)

    resumed = resume_package(api, store_id, member_id, paused)
    assert resumed["status"] == "ACTIVE"


def test_a_bay_freeze_completes_in_service_bookings_and_cancels_merely_confirmed_ones(api):
    """One parent freeze produces two different child outcomes.

    PRD §3.3: "Every booking of that bay in `REQUESTED`, `SCREENED` or
    `BAY_CONFIRMED` moves to `CANCELLED` and increments its own version, and every
    booking of that bay in `IN_SERVICE` moves to `COMPLETED` and increments its
    own version."
    PRD §3.3: "freezing a store mid-afternoon cancels everything not yet begun
    and closes out everything already in progress"
    PRD §3.3: "Every bay of the store moves to `FROZEN` with `is_frozen` set true."

    Design: Corner/state_machines/bay_freeze_cancels_pending_bookings_and_completes_in_service_ones
    """
    from test_helpers import bump_occupancy

    world = setup_bay_with_two_grooming_bookings(api)
    store_id = world["store"]["id"]
    store = read_store(api, store_id)
    bump_occupancy(api, store_id, store["version"], 1)

    assert read_store(api, store_id)["hospital_posture"] == "FROZEN"
    confirmed_booking = get_success_data(api.get_booking(world["confirmed"]["id"], ADMIN))
    in_service_booking = get_success_data(api.get_booking(world["in_service"]["id"], ADMIN))
    bay = get_success_data(api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN))
    assert confirmed_booking["status"] == "CANCELLED"
    assert in_service_booking["status"] == "COMPLETED"
    assert bay["status"] == "FROZEN"
    assert bay["is_frozen"] is True