"""Guest eligibility (lazy expiry and reverification), check-in gates
(posture, duplicate, occupancy), and the occupancy round-trip invariant."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    assert_check_in,
    check_in_guest,
    create_center,
    create_center_with_active_agreement,
    create_guest,
    get_center,
    reverify_guest,
    run_ops,
    set_clock,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]


def test_checkin_duplicate_rejected(api: ApiClient):
    """PRD §3.4: "The guest must not already hold a `CHECKED_IN` visit at that center, else `ERR_ALREADY_CHECKED_IN`."
    PRD §3.4: "A successful check-in records `checked_in_at` from the logical clock, leaves `checked_out_at` null, holds the visit in `CHECKED_IN`, increments the center's `current_occupancy` by one, and increments the center's `version` by one."

    Design: Corner/validations/checkin_duplicate_rejected
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Kaph Center",
            "airport_code": "GEG",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        }
    )
    guest = create_guest(full_name="G Dup")
    first = check_in_guest(center["id"], guest["id"])
    assert_check_in(first)
    assert first["status"] == "CHECKED_IN"

    resp = api.create_check_in(center["id"], {"guest_id": guest["id"]}, MGR)
    validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_IN)

    assert get_center(center["id"])["current_occupancy"] == 1, (
        "the rejected duplicate must not double-count occupancy"
    )


def test_guest_verification_lazy_expiry_and_reverify(api: ApiClient):
    """PRD §3.4: "Thereafter, whenever a check-in or a service booking is attempted and the guest's `verification_expires_on` is earlier than the current clock date, the guest's `eligibility_status` flips to `EXPIRED` on the spot and the attempted operation is rejected with `ERR_GUEST_INELIGIBLE`."
    PRD §3.4: "A `CenterManager` restores standing through reverification: supplying a new `verification_expires_on` on or after the current clock date (anything earlier is `ERR_VALIDATION`) sets the date and returns the guest to `ELIGIBLE`, so `ELIGIBLE` and `EXPIRED` form a cycle."

    Design: Corner/validations/guest_verification_lazy_expiry_and_reverify
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Lamed Center",
            "airport_code": "PSC",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        }
    )
    # An already-past verification date is accepted at registration.
    guest = create_guest(
        full_name="G Lapsed",
        category="VETERAN",
        verification_expires_on="2026-08-15",
    )
    assert guest["eligibility_status"] == "ELIGIBLE"

    denied = api.create_check_in(center["id"], {"guest_id": guest["id"]}, MGR)
    validate_error(denied, ApiErrorId.ERR_GUEST_INELIGIBLE)

    mid = validate_success(api.get_guest(guest["id"], MGR), 200)
    assert mid["eligibility_status"] == "EXPIRED", (
        "the failed check-in lazily flips the guest to EXPIRED, got "
        f"{mid['eligibility_status']!r}"
    )

    reverified = reverify_guest(guest["id"], "2027-06-01")
    assert reverified["eligibility_status"] == "ELIGIBLE"
    assert reverified["verification_expires_on"] == "2027-06-01"

    ok = api.create_check_in(center["id"], {"guest_id": guest["id"]}, MGR)
    visit = validate_success(ok, 201)
    assert_check_in(visit)
    assert visit["status"] == "CHECKED_IN"


def test_occupancy_capacity_gate(api: ApiClient):
    """PRD §3.4: "Finally, occupancy: when the center's `current_occupancy` has reached `occupancy_cap`, the check-in is rejected with `ERR_CENTER_AT_CAPACITY`."

    Design: Corner/calculations/occupancy_capacity_gate
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Zayin Center",
            "airport_code": "FAT",
            "occupancy_cap": 1,
            "required_daily_confirmed_assignments": 1,
        }
    )
    g1 = create_guest(full_name="G Cap1")
    g2 = create_guest(full_name="G Cap2", category="RETIREE")
    check_in_guest(center["id"], g1["id"])

    resp = api.create_check_in(center["id"], {"guest_id": g2["id"]}, MGR)
    validate_error(resp, ApiErrorId.ERR_CENTER_AT_CAPACITY)

    assert get_center(center["id"])["current_occupancy"] == 1, (
        "occupancy stays at the cap after the rejected check-in"
    )


def test_checkin_occupancy_roundtrip_invariant(api: ApiClient):
    """PRD §3.4: "A successful check-in records `checked_in_at` from the logical clock, leaves `checked_out_at` null, holds the visit in `CHECKED_IN`, increments the center's `current_occupancy` by one, and increments the center's `version` by one."
    PRD §3.4: "There is no manual check-out. The operations checkpoint performs a day-end sweep: any visit still `CHECKED_IN` whose `checked_in_at` date is earlier than the current clock date is moved to `CHECKED_OUT`, with `checked_out_at` stamped at the checkpoint's clock time and `current_occupancy` decremented by one."

    Design: Difficulty/compensating_invariant/checkin_occupancy_roundtrip_invariant
    """
    set_clock("2026-09-01T20:00:00Z")
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Sigma Center",
            "airport_code": "SAN",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 2,
        }
    )
    assert center["current_occupancy"] == 0

    guest = create_guest(full_name="G Occ")
    resp = api.create_check_in(center["id"], {"guest_id": guest["id"]}, MGR)
    visit = validate_success(resp, 201)
    assert_check_in(visit)
    assert visit["checked_out_at"] is None

    assert get_center(center["id"])["current_occupancy"] == 1

    # Roll past midnight: the day-end sweep checks the visit out and
    # returns occupancy to 0 (net drift zero).
    set_clock("2026-09-02T00:30:00Z")
    swept = run_ops(center["id"])
    assert swept["current_occupancy"] == 0, (
        f"day-end sweep must return occupancy to 0, got "
        f"{swept['current_occupancy']}"
    )

    visit_after = validate_success(api.get_check_in(visit["id"], MGR), 200)
    assert visit_after["status"] == "CHECKED_OUT"
    assert visit_after["checked_out_at"] is not None


def test_center_closed_beats_guest_ineligible(api: ApiClient):
    """PRD §2.7: "Incoming requests pass through a fixed pipeline of checks, and an earlier failure always masks every later one."
    PRD §2.7: "Only then do business rules run, in this relative order: state admissibility — the target entity must be in a from-state its transition allows, covering `ERR_INVALID_STATE`, `ERR_CENTER_CLOSED`, `ERR_ALREADY_CHECKED_IN`, `ERR_SCREENING_ALREADY_OPEN`, and `ERR_RENEWAL_WINDOW_NOT_OPEN`; then safety and compliance — `ERR_GUEST_INELIGIBLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_SECURITY_LEVEL_INSUFFICIENT`, `ERR_TALENT_AGREEMENT_UNSIGNED`, and `ERR_SEGREGATION_OF_DUTIES`"
    PRD §3.4: "The center must not be `CLOSED` — no active agreement, no visits — or the check-in fails with `ERR_CENTER_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/center_closed_beats_guest_ineligible
    """
    set_clock()
    # No site agreement is ever activated: posture stays CLOSED.
    center = create_center(
        name="Iota Center",
        airport_code="MIA",
        occupancy_cap=20,
        required_daily_confirmed_assignments=1,
    )
    guest = create_guest(
        full_name="Expired Guest",
        category="VETERAN",
        verification_expires_on="2026-08-15",
    )

    # The request violates both the posture gate (CLOSED) and guest
    # eligibility; the earlier state check masks the later safety check.
    resp = api.create_check_in(center["id"], {"guest_id": guest["id"]}, MGR)
    validate_error(resp, ApiErrorId.ERR_CENTER_CLOSED)

    guest_after = validate_success(api.get_guest(guest["id"], MGR), 200)
    assert guest_after["eligibility_status"] == "ELIGIBLE", (
        "the masked eligibility check never runs, so the lazy flip to "
        f"EXPIRED must not happen, got {guest_after['eligibility_status']!r}"
    )
