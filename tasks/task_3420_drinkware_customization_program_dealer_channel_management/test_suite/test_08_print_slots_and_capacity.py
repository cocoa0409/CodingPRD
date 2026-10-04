"""Print slots: overlap geometry, capacity ledger, reservations, and the
waitlist (PRD sections 3.7, 2.10)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_order_art,
    boot_clock,
    create_colorway_drop,
    create_order,
    create_print_slot,
    create_product_line,
    create_submitted_order,
    get_order,
    get_slot,
    make_buyer_headers,
    release_slot,
    reserve_slot,
    set_clock,
    setup_catalog,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    assert_slot_capacity_invariant,
    TEST_USERS,
)

_PRODUCTION = TEST_USERS["production_lead_headers"]


def _slot_payload(station, tech, start, end, cap):
    return {"station_code": station, "technology": tech,
            "window_start": start, "window_end": end, "capacity_minutes": cap}


def test_print_slot_half_open_touching_and_changeover_buffer(api):
    """Same-technology windows may touch but not intersect; cross-technology
    windows need a 20-minute changeover on both sides (10 conflicts, exactly
    20 is allowed).

    PRD section 3.7: "Slot windows are half-open intervals — the start is
    occupied, the end is not — scoped per `station_code`. Two windows on the
    same station running the same technology are rejected only when their
    intervals genuinely intersect, so touching endpoints are allowed; windows
    of different technologies additionally require a changeover gap of at
    least 20 minutes on both sides, and a smaller gap is a conflict. Any
    overlap violation is rejected with `ERR_SLOT_OVERLAP_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/print_slot_half_open_touching_and_changeover_buffer
    """
    boot_clock()
    day = "2026-09-12"
    s1 = validate_success(api.create_print_slot(
        _slot_payload("L-7", "LASER", f"{day}T09:00:00Z", f"{day}T10:00:00Z", 60),
        _PRODUCTION), 201)
    s2 = validate_success(api.create_print_slot(
        _slot_payload("L-7", "LASER", f"{day}T10:00:00Z", f"{day}T11:00:00Z", 60),
        _PRODUCTION), 201)
    assert s1["id"] != s2["id"], "touching endpoints coexist under half-open semantics"

    resp_intersect = api.create_print_slot(
        _slot_payload("L-7", "LASER", f"{day}T09:30:00Z", f"{day}T10:30:00Z", 60),
        _PRODUCTION)
    validate_error(resp_intersect, ApiErrorId.ERR_SLOT_OVERLAP_CONFLICT)

    # PAD at 10:10 leaves only a 10-minute changeover after the 10:00 LASER end.
    resp_gap10 = api.create_print_slot(
        _slot_payload("L-7", "PAD", f"{day}T10:10:00Z", f"{day}T11:00:00Z", 50),
        _PRODUCTION)
    validate_error(resp_gap10, ApiErrorId.ERR_SLOT_OVERLAP_CONFLICT)

    # PAD at 11:20 leaves exactly the 20-minute changeover: allowed.
    validate_success(api.create_print_slot(
        _slot_payload("L-7", "PAD", f"{day}T11:20:00Z", f"{day}T12:20:00Z", 60),
        _PRODUCTION), 201)

    rows, meta = validate_paginated(
        api.list_print_slots(_PRODUCTION, params={"station_code": "L-7"}))
    assert len(rows) == 3 and meta["total_count"] == 3


def test_slot_capacity_exceeds_window_rejected(api):
    """capacity_minutes is bounded by the window's duration in minutes.

    PRD section 3.7: "and `capacity_minutes` must be positive and no greater
    than the window's duration in minutes, failing with
    `ERR_CAPACITY_EXCEEDS_WINDOW`."

    Design: Corner/validations/slot_capacity_exceeds_window_rejected
    """
    boot_clock()
    resp = api.create_print_slot(
        _slot_payload("L-SOLO", "LASER", "2026-09-12T09:00:00Z",
                      "2026-09-12T10:00:00Z", 200),
        _PRODUCTION)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDS_WINDOW)

    rows, meta = validate_paginated(
        api.list_print_slots(_PRODUCTION, params={"station_code": "L-SOLO"}))
    assert len(rows) == 0 and meta["total_count"] == 0


def test_temporal_beats_constraint_on_overlapping_slot_creation(api):
    """A new slot that both overlaps an existing window (priority 10) and
    over-declares capacity (priority 11) reports the temporal error.

    PRD section 2.7: "When several checks could reject the same request, they
    are evaluated in a fixed priority order and the first failure wins."
    PRD section 3.7: "Any overlap violation is rejected with
    `ERR_SLOT_OVERLAP_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_overlapping_slot_creation
    """
    boot_clock()
    validate_success(api.create_print_slot(
        _slot_payload("L-5", "LASER", "2026-09-12T09:00:00Z",
                      "2026-09-12T10:00:00Z", 60),
        _PRODUCTION), 201)

    resp = api.create_print_slot(
        _slot_payload("L-5", "LASER", "2026-09-12T09:30:00Z",
                      "2026-09-12T10:30:00Z", 120),
        _PRODUCTION)
    # 120 > the 60-minute window also violates the capacity constraint, but
    # the overlap rule is reached first.
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP_CONFLICT)

    rows, meta = validate_paginated(
        api.list_print_slots(_PRODUCTION, params={"station_code": "L-5"}))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_slot_capacity_exact_fit_then_zero_available_waitlists(api):
    """A booking needing exactly the remaining capacity lands HELD at zero
    available; the next booking waitlists rather than failing.

    PRD section 3.7: "If the slot's `available_minutes` covers that footprint —
    an exact fit counts — the reservation lands `HELD` and the schedule moves
    to `RESERVED`, booking the minutes against the slot; otherwise the
    reservation lands `WAITLISTED` and the schedule stays `UNSCHEDULED`."
    PRD section 2.10: "Reservations consume 4 machine-minutes per unit on
    `LASER` technology and 2 per unit on `PAD`."

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fit_then_zero_available_waitlists
    """
    boot_clock()
    line = create_product_line(name="Cup 10 oz", base_sku="CUP10",
                               base_custom_price_cents=2200, map_price_cents=2799,
                               min_custom_quantity=1)
    drop = create_colorway_drop(line["id"], color_name="White",
                                pantone_code="PMS White")
    slot = create_print_slot(**_slot_payload(
        "P-2", "PAD", "2026-09-11T09:00:00Z", "2026-09-11T09:40:00Z", 40))

    def submitted_order(buyer_ref, qty):
        order = create_order(line["id"], drop["id"], buyer_ref=buyer_ref,
                             quantity=qty, print_technology="PAD",
                             requested_ship_date="2026-09-12T00:00:00Z")
        submit_order(order["id"], buyer_ref)
        return order

    fit20 = submitted_order("buyer-fit20", 20)  # 20 x 2 = exactly 40 minutes
    fit1 = submitted_order("buyer-fit1", 1)     # 2 minutes

    held = reserve_slot(fit20["id"], slot["id"], "buyer-fit20")
    assert held["reservation_status"] == "HELD"
    assert held["schedule_status"] == "RESERVED"
    mid = get_slot(slot["id"])
    assert mid["booked_minutes"] == 40 and mid["available_minutes"] == 0
    assert_slot_capacity_invariant(mid)

    waitlisted = reserve_slot(fit1["id"], slot["id"], "buyer-fit1")
    assert waitlisted["reservation_status"] == "WAITLISTED"
    assert waitlisted["schedule_status"] == "UNSCHEDULED", "no partial booking"
    end = get_slot(slot["id"])
    assert end["booked_minutes"] == 40 and end["available_minutes"] == 0, \
        "a waitlisted attempt books nothing"


def test_reserve_then_release_restores_slot_minutes_exactly(api):
    """The slot minute ledger is conserved: a HELD booking followed by its
    release restores available_minutes to exactly the pre-reserve value.

    PRD section 2.10: "the invariant `capacity_minutes` equals `booked_minutes`
    plus `available_minutes` is preserved by every reservation, release,
    promotion, and completion, so a held or confirmed booking followed by its
    release restores `available_minutes` exactly."

    Design: Difficulty/compensating_invariant/reserve_then_release_restores_slot_minutes_exactly
    """
    boot_clock()
    line = create_product_line(name="Cup 12 oz", base_sku="CUP12",
                               base_custom_price_cents=2400, map_price_cents=2899,
                               min_custom_quantity=1)
    drop = create_colorway_drop(line["id"], color_name="Ivory",
                                pantone_code="PMS 7527")
    slot = create_print_slot(**_slot_payload(
        "L-8", "LASER", "2026-09-14T09:00:00Z", "2026-09-14T11:00:00Z", 100))
    order = create_order(line["id"], drop["id"], buyer_ref="buyer-inv",
                         quantity=10, print_technology="LASER",
                         requested_ship_date="2026-09-16T00:00:00Z")
    submit_order(order["id"], "buyer-inv")

    reserve_slot(order["id"], slot["id"], "buyer-inv")
    mid = get_slot(slot["id"])
    assert mid["booked_minutes"] == 40 and mid["available_minutes"] == 60
    assert_slot_capacity_invariant(mid)  # 100 == 40 + 60

    released = release_slot(order["id"], "buyer-inv")
    assert released["reservation_status"] == "RELEASED"
    assert released["schedule_status"] == "UNSCHEDULED"
    assert released.get("slot_id") is None
    end = get_slot(slot["id"])
    assert end["booked_minutes"] == 0 and end["available_minutes"] == 100, \
        "no drift from the pre-reserve value"
    assert_slot_capacity_invariant(end)


def test_technology_mismatch_on_reserve(api):
    """A LASER order cannot book a PAD slot; nothing is reserved.

    PRD section 3.7: "The slot's `technology` must match the order's
    `print_technology`, failing with `ERR_TECHNOLOGY_MISMATCH`"

    Design: Corner/validations/technology_mismatch_on_reserve
    """
    boot_clock()
    trio = create_submitted_order()  # LASER order, payment AUTHORIZED
    slot_pad = create_print_slot(**_slot_payload(
        "P-9", "PAD", "2026-09-14T09:00:00Z", "2026-09-14T12:00:00Z", 180))

    resp = api.reserve_slot(trio["order"]["id"], {"slot_id": slot_pad["id"]},
                            make_buyer_headers("buyer-std"))
    validate_error(resp, ApiErrorId.ERR_TECHNOLOGY_MISMATCH)
    order = get_order(trio["order"]["id"])
    assert order["reservation_status"] == "NONE"
    assert order["schedule_status"] == "UNSCHEDULED"
    assert get_slot(slot_pad["id"])["booked_minutes"] == 0


def test_slot_lazy_closed_blocks_reservation(api):
    """Once the clock passes window_end the slot reads CLOSED with no explicit
    transition, and reserving against it is rejected.

    PRD section 2.4: "a print slot moves from `OPEN` or `LOCKED` to `CLOSED`
    once the clock reaches its `window_end`"
    PRD section 3.7: "the slot must be `OPEN`, failing with `ERR_SLOT_NOT_OPEN`"

    Design: Corner/state_machines/slot_lazy_closed_blocks_reservation
    """
    boot_clock()
    trio = create_submitted_order()
    slot = create_print_slot()  # default window ends 2026-09-14T12:00:00Z

    set_clock("2026-09-15T00:00:00Z")
    assert get_slot(slot["id"])["status"] == "CLOSED", "lazy evaluation on read"

    resp = api.reserve_slot(trio["order"]["id"], {"slot_id": slot["id"]},
                            make_buyer_headers("buyer-std"))
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN)
    assert get_order(trio["order"]["id"])["reservation_status"] == "NONE"


def test_peak_slot_reserve_requires_approved_art(api):
    """Peak-overlapping slots require ART_APPROVED at reserve time; after
    approval the same reserve succeeds and confirms atomically.

    PRD section 3.7: "Peak-window slots are stricter: when the slot's
    `peak_overlap` is true the order's artwork must already be `ART_APPROVED`,
    failing with `ERR_ARTWORK_NOT_APPROVED`, while off-peak slots accept
    reservations with art still pending."
    PRD section 3.7: "When the artwork was already approved at reserve time,
    the new reservation confirms atomically in the same request: `HELD` to
    `CONFIRMED` and `RESERVED` to `CONFIRMED`."
    PRD section 2.9: "a print slot whose window intersects the peak window is
    marked `peak_overlap`, which tightens the artwork readiness required to
    reserve it."

    Design: Corner/validations/peak_slot_reserve_requires_approved_art
    """
    boot_clock()
    trio = create_submitted_order()
    slot_peak = create_print_slot(**_slot_payload(
        "L-PEAK", "LASER", "2026-11-02T09:00:00Z", "2026-11-02T12:00:00Z", 180))
    assert slot_peak["peak_overlap"] is True, \
        "2026-11-02 intersects the peak window [2026-10-15, 2026-12-21)"

    resp = api.reserve_slot(trio["order"]["id"], {"slot_id": slot_peak["id"]},
                            make_buyer_headers("buyer-std"))
    validate_error(resp, ApiErrorId.ERR_ARTWORK_NOT_APPROVED)

    approve_order_art(trio["order"]["id"], "buyer-std")
    confirmed = reserve_slot(trio["order"]["id"], slot_peak["id"], "buyer-std")
    assert confirmed["reservation_status"] == "CONFIRMED"
    assert confirmed["schedule_status"] == "CONFIRMED"


def test_release_slot_promotes_waitlist_in_ship_date_order(api):
    """Releasing a HELD reservation promotes the waitlist in
    requested_ship_date order (not creation order), and a candidate that does
    not fit the freed capacity stays WAITLISTED.

    PRD section 3.7: "candidates are the orders pointing at the freed slot with
    `reservation_status` `WAITLISTED`, still `ACTIVE`, and — when the slot is
    a peak-window slot — already `ART_APPROVED`; they are ranked by
    `requested_ship_date` ascending and then `created_at` ascending, and each
    candidate whose `reserved_minutes` fits the current `available_minutes` is
    promoted in that order, moving from `WAITLISTED` to `HELD` and from
    `UNSCHEDULED` to `RESERVED` and booking its minutes"

    Design: Difficulty/transitive_cascade/release_slot_promotes_waitlist_in_ship_date_order
    """
    boot_clock()
    line = create_product_line(name="Rambler 40 oz", base_sku="RAM40",
                               base_custom_price_cents=3600, map_price_cents=4299,
                               min_custom_quantity=5)
    drop = create_colorway_drop(line["id"], color_name="Granite",
                                pantone_code="PMS 432")
    slot = create_print_slot(**_slot_payload(
        "L-9", "LASER", "2026-09-10T09:00:00Z", "2026-09-10T10:40:00Z", 100))

    def submitted(buyer_ref, qty, ship):
        order = create_order(line["id"], drop["id"], buyer_ref=buyer_ref,
                             quantity=qty, print_technology="LASER",
                             requested_ship_date=ship)
        submit_order(order["id"], buyer_ref)
        return order

    o1 = submitted("buyer-a", 15, "2026-09-18T00:00:00Z")  # 60 min
    o4 = submitted("buyer-d", 10, "2026-09-19T00:00:00Z")  # 40 min
    o2 = submitted("buyer-b", 10, "2026-09-20T00:00:00Z")  # 40 min, waitlisted
    o3 = submitted("buyer-c", 5, "2026-09-15T00:00:00Z")   # 20 min, created last

    assert reserve_slot(o1["id"], slot["id"], "buyer-a")["reservation_status"] == "HELD"
    assert reserve_slot(o4["id"], slot["id"], "buyer-d")["reservation_status"] == "HELD"
    assert reserve_slot(o2["id"], slot["id"], "buyer-b")["reservation_status"] == "WAITLISTED"
    assert reserve_slot(o3["id"], slot["id"], "buyer-c")["reservation_status"] == "WAITLISTED"
    before = get_slot(slot["id"])
    assert before["booked_minutes"] == 100 and before["available_minutes"] == 0

    release_slot(o4["id"], "buyer-d")  # frees 40 minutes

    # o3 ships earliest (09-15) although created last: it promotes first.
    o3_after = get_order(o3["id"])
    assert o3_after["reservation_status"] == "HELD"
    assert o3_after["schedule_status"] == "RESERVED"

    # Only 20 of the 40 freed minutes remain; o2 needs 40 and stays waitlisted.
    o2_after = get_order(o2["id"])
    assert o2_after["reservation_status"] == "WAITLISTED"
    assert o2_after["schedule_status"] == "UNSCHEDULED"

    after = get_slot(slot["id"])
    assert after["booked_minutes"] == 80 and after["available_minutes"] == 20
    assert_slot_capacity_invariant(after)

    o4_after = get_order(o4["id"])
    assert o4_after["reservation_status"] == "RELEASED"
    assert o4_after.get("slot_id") is None
