"""Cross-entity state dependencies, temporal overlap conventions and
compensating invariants.

Three families of depth tests live here.

*Cross-entity state dependency.* An operation that is legal in every respect
readable off the entity it addresses is still refused because a second entity
moved underneath it — a cutover slot another port request booked, or a
dispatchable location a network report drove stale.

*Resource temporal overlap.* The PRD deliberately runs two opposite interval
conventions side by side: cutover windows are half-open and expanded by the
carrier's quiet-time buffer before the scan, while reservation intervals are
closed at both ends and unbuffered. Touching edges are therefore free on one
side and a conflict on the other.

*Compensating invariant.* A hop and its compensating hop must return a
conserved quantity to exactly its prior value — the block's integer census
vector, and the whole-cent fee ledgers of a jurisdiction and an account — while
the compensated row itself is retained rather than deleted.
"""
from test_helpers import (
    ApiErrorId,
    FRAUD_BLOCK_THRESHOLD,
    assert_block_census,
    assert_cents_equal,
    assert_instant,
    assert_null,
    block_version,
    book_slot,
    census_snapshot,
    ids_of,
    make_calling_restriction_payload,
    make_cutover_slot_payload,
    make_fee_assessment_payload,
    make_number_reservation_payload,
    make_schedule_payload,
    make_void_payload,
    make_billing_admin_headers,
    make_numbering_admin_headers,
    make_porting_specialist_headers,
    make_security_analyst_headers,
    post_matching_csr_snapshot,
    read_account,
    read_cutover_slot,
    read_device,
    read_jurisdiction,
    read_number_block,
    read_phone_number,
    read_port_request,
    read_registration,
    read_reservation,
    release_reservation,
    report_network_location,
    seed_account,
    seed_carrier,
    seed_cutover_slot,
    seed_number_block,
    seed_phone_number,
    seed_jurisdiction,
    seed_port_request,
    seed_reservation,
    set_clock,
    setup_compliant_device,
    validate_error,
    validate_paginated,
    validate_success,
    BILLING_USER_ID,
    BILLING_USER_ID_ALT,
)

# --- Shared literals for the scheduling contention scenario -----------------
_CONTENTION_CLOCK = "2026-08-03T09:00:00.000Z"
_CONTENTION_FOC_FLOOR = "2026-08-06T00:00:00.000Z"
_SLOT_START = "2026-08-10T14:00:00.000Z"
_SLOT_END = "2026-08-10T18:00:00.000Z"


def _two_validated_requests_and_one_slot(api):
    """Two VALIDATED requests of one account and a single OPEN slot of their
    own carrier, with the first request already holding the booking."""
    set_clock(_CONTENTION_CLOCK)
    account = seed_account("ACCT0013", billing_name="MAPLE GMBH")
    carrier = seed_carrier(
        "SL04",
        name="Sierra Legacy",
        csr_match_policy="STRICT",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    request_a = seed_port_request(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155550013"],
        claimed_account_number="CSRACC013",
        claimed_pin="1313",
        claimed_billing_name="MAPLE GMBH",
        claimed_address_line1="13 MAPLE ROW",
        claimed_zip="94578",
    )
    post_matching_csr_snapshot(request_a["id"], request_a)
    request_b = seed_port_request(
        account["id"],
        carrier["id"],
        requested_numbers=["+14155550014"],
        claimed_account_number="CSRACC014",
        claimed_pin="1414",
        claimed_billing_name="MAPLE GMBH",
        claimed_address_line1="13 MAPLE ROW",
        claimed_zip="94578",
    )
    post_matching_csr_snapshot(request_b["id"], request_b)
    slot = seed_cutover_slot(
        carrier["id"], window_start=_SLOT_START, window_end=_SLOT_END
    )
    book_slot(request_a["id"], slot["id"])
    return {
        "account": account,
        "carrier": carrier,
        "request_a": request_a,
        "request_b": request_b,
        "slot": slot,
    }


def test_second_port_request_cannot_schedule_a_slot_the_first_already_booked__refused_with_slot_not_open(api):
    """The named slot must be `OPEN`; a slot that is already `BOOKED`, or that has been `CONSUMED` or `RELEASED`, yields `ERR_SLOT_NOT_OPEN`.

    Nothing readable off the second request explains the refusal: it is
    VALIDATED, the slot belongs to its own losing carrier and the window starts
    after its own firm-order-commitment floor.

    Design: Difficulty/cross_entity_state_dependency/second_port_request_cannot_schedule_a_slot_the_first_already_booked
    """
    scenario = _two_validated_requests_and_one_slot(api)

    response = api.schedule_port_request(
        scenario["request_b"]["id"],
        make_schedule_payload(scenario["slot"]["id"]),
        make_porting_specialist_headers(),
    )
    # The slot's status outranks the carrier check and the FOC floor, so none of
    # ERR_PORT_REQUEST_NOT_SCHEDULABLE, ERR_SLOT_CARRIER_MISMATCH or
    # ERR_CUTOVER_BEFORE_FOC may surface here.
    validate_error(response, ApiErrorId.ERR_SLOT_NOT_OPEN.value, 409)

    # The precondition the refusal is NOT about: same carrier on both sides.
    assert scenario["slot"]["carrier_id"] == scenario["carrier"]["id"]
    assert (
        scenario["request_b"]["losing_carrier_id"] == scenario["carrier"]["id"]
    )


def test_second_port_request_cannot_schedule_a_slot_the_first_already_booked__loser_stays_validated(api):
    """The named slot must be `OPEN`; a slot that is already `BOOKED`, or that has been `CONSUMED` or `RELEASED`, yields `ERR_SLOT_NOT_OPEN`.

    The refused request keeps its own readiness intact — still VALIDATED, still
    carrying the firm-order-commitment floor it earned — and no slot names it.

    Design: Difficulty/cross_entity_state_dependency/second_port_request_cannot_schedule_a_slot_the_first_already_booked
    """
    scenario = _two_validated_requests_and_one_slot(api)

    validate_error(
        api.schedule_port_request(
            scenario["request_b"]["id"],
            make_schedule_payload(scenario["slot"]["id"]),
            make_porting_specialist_headers(),
        ),
        ApiErrorId.ERR_SLOT_NOT_OPEN.value,
        409,
    )

    refused = read_port_request(scenario["request_b"]["id"])
    assert refused["status"] == "VALIDATED"
    assert_instant(
        refused["earliest_cutover_at"],
        _CONTENTION_FOC_FLOOR,
        "port_request.earliest_cutover_at",
    )

    rows, _meta = validate_paginated(
        api.list_cutover_slots(
            make_porting_specialist_headers(),
            params={"booked_port_request_id": scenario["request_b"]["id"]},
        )
    )
    assert rows == [], f"no slot may name the refused request, got {ids_of(rows)}"


def test_second_port_request_cannot_schedule_a_slot_the_first_already_booked__winner_and_slot_keep_the_booking(api):
    """On the slot side it moves `OPEN → BOOKED`, sets `booked_port_request_id` to the booking request and `booked_at` to the logical clock, and increments the slot's `version` by 1.

    The losing attempt leaves the winning request and the slot exactly as the
    successful booking left them.

    Design: Difficulty/cross_entity_state_dependency/second_port_request_cannot_schedule_a_slot_the_first_already_booked
    """
    scenario = _two_validated_requests_and_one_slot(api)

    validate_error(
        api.schedule_port_request(
            scenario["request_b"]["id"],
            make_schedule_payload(scenario["slot"]["id"]),
            make_porting_specialist_headers(),
        ),
        ApiErrorId.ERR_SLOT_NOT_OPEN.value,
        409,
    )

    winner = read_port_request(scenario["request_a"]["id"])
    assert winner["status"] == "SCHEDULED"

    slot = read_cutover_slot(scenario["slot"]["id"])
    assert slot["status"] == "BOOKED"
    assert slot["booked_port_request_id"] == scenario["request_a"]["id"]
    assert_instant(slot["booked_at"], _CONTENTION_CLOCK, "cutover_slot.booked_at")


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / review_unblock_refused_while_the_devices_
# registration_is_stale
# ---------------------------------------------------------------------------
def _nomadic_device_gone_stale(api):
    """A nomadic, number-holding device whose VERIFIED location was driven STALE
    by a cross-jurisdiction network report — and which never dialled at all."""
    scenario = setup_compliant_device(
        account_number="ACCT0014",
        npa_nxx="415565",
        line_number="1101",
        mac_address="AABBCC000081",
        device_overrides={"nomadic": True, "device_type": "SOFTPHONE"},
    )
    assert scenario["device"]["registration_status"] == "REGISTERED"
    assert scenario["device"]["calling_status"] == "UNRESTRICTED"
    assert scenario["account"]["e911_compliance_posture"] == "COMPLIANT"

    report_network_location(
        scenario["device"]["id"],
        scenario["account"]["id"],
        reported_state_code="NV",
        reported_postal_code="89501",
    )
    return scenario


def test_review_unblock_refused_while_the_devices_registration_is_stale__refused_although_no_call_was_ever_placed(api):
    """The device's current registration must have `verification_status` exactly `VERIFIED` — a `STALE` address is good enough to keep dialling but not good enough to earn a release — and the DAILY_REVIEW fraud score must be strictly below 60.

    The device has never placed a call attempt, so the refusal can only come
    from the second entity the gate reads: the dispatchable location.

    Design: Difficulty/cross_entity_state_dependency/review_unblock_refused_while_the_devices_registration_is_stale
    """
    scenario = _nomadic_device_gone_stale(api)

    rows, _meta = validate_paginated(
        api.list_call_attempts(scenario["device"]["id"], make_security_analyst_headers())
    )
    assert rows == [], f"the device must have dialled nothing, got {len(rows)} rows"

    response = api.create_calling_restriction(
        scenario["device"]["id"],
        make_calling_restriction_payload(
            "REVIEW_UNBLOCK", note="customer says the relocation was temporary"
        ),
        make_security_analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_UNBLOCK_REVIEW_SCORE_TOO_HIGH.value, 409)


def test_review_unblock_refused_while_the_devices_registration_is_stale__device_dimensions_survive_the_refusal(api):
    """Moving to `AT_RISK` sends every device of the account that is `nomadic` and currently `UNRESTRICTED` to `INTL_BLOCKED`; non-nomadic devices are left alone by this sweep.

    The refused release leaves both device dimensions exactly where the posture
    sweep and the relocation left them, and the fraud counter untouched.

    Design: Difficulty/cross_entity_state_dependency/review_unblock_refused_while_the_devices_registration_is_stale
    """
    scenario = _nomadic_device_gone_stale(api)

    validate_error(
        api.create_calling_restriction(
            scenario["device"]["id"],
            make_calling_restriction_payload("REVIEW_UNBLOCK"),
            make_security_analyst_headers(),
        ),
        ApiErrorId.ERR_UNBLOCK_REVIEW_SCORE_TOO_HIGH.value,
        409,
    )

    device = read_device(scenario["device"]["id"])
    assert device["calling_status"] == "INTL_BLOCKED"
    assert device["registration_status"] == "RELOCATION_DETECTED"
    assert device["fraud_block_count"] == 0
    # The DAILY_REVIEW score cannot be what refused the release: with no rows in
    # the window it stays far below the fraud threshold.
    assert device["toll_fraud_score"] < FRAUD_BLOCK_THRESHOLD, (
        "the refusal must not be score-driven, got "
        f"toll_fraud_score={device['toll_fraud_score']}"
    )


def test_review_unblock_refused_while_the_devices_registration_is_stale__registration_is_stale_and_posture_at_risk(api):
    """A **cross-jurisdiction** report moves the device `REGISTERED → RELOCATION_DETECTED` — the device has crossed a 911 jurisdiction line and its dispatchable location is now positively wrong — and likewise drives its current registration `VERIFIED → STALE`.

    The second entity in the dependency: the registration is STALE and still
    current, and the account posture it drove is AT_RISK.

    Design: Difficulty/cross_entity_state_dependency/review_unblock_refused_while_the_devices_registration_is_stale
    """
    scenario = _nomadic_device_gone_stale(api)

    validate_error(
        api.create_calling_restriction(
            scenario["device"]["id"],
            make_calling_restriction_payload("REVIEW_UNBLOCK"),
            make_security_analyst_headers(),
        ),
        ApiErrorId.ERR_UNBLOCK_REVIEW_SCORE_TOO_HIGH.value,
        409,
    )

    registration = read_registration(scenario["registration"]["id"])
    assert registration["verification_status"] == "STALE"
    assert_null(registration["superseded_at"], "e911_registration.superseded_at")

    account = read_account(scenario["account"]["id"])
    assert account["e911_compliance_posture"] == "AT_RISK"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / cutover_slot_buffer_expands_half_open_windows_
# and_touching_edges_are_free
# ---------------------------------------------------------------------------
_BUFFERED_CLOCK = "2026-08-03T09:00:00.000Z"
# The incumbent window, 240 minutes long and therefore legal on length.
_INCUMBENT_START = "2026-08-10T14:00:00.000Z"
_INCUMBENT_END = "2026-08-10T18:00:00.000Z"
# A 60-minute buffer on both sides expands the incumbent to [13:00Z, 19:00Z).
_COLLIDING_START = "2026-08-10T18:30:00.000Z"
_COLLIDING_END = "2026-08-10T20:30:00.000Z"
# [20:00Z, 22:00Z) starts exactly one hour after the expanded end, so its own
# expanded form only touches it.
_TOUCHING_START = "2026-08-10T20:00:00.000Z"
_TOUCHING_END = "2026-08-10T22:00:00.000Z"


def _carrier_with_one_buffered_slot(api):
    """A carrier demanding 60 minutes of quiet time either side, holding one
    OPEN window from 14:00Z to 18:00Z."""
    set_clock(_BUFFERED_CLOCK)
    carrier = seed_carrier(
        "CL05",
        name="Cascade Legacy",
        csr_match_policy="RELAXED",
        porting_buffer_minutes=60,
        foc_business_days=3,
    )
    slot = seed_cutover_slot(
        carrier["id"], window_start=_INCUMBENT_START, window_end=_INCUMBENT_END
    )
    assert carrier["porting_buffer_minutes"] == 60
    return {"carrier": carrier, "slot": slot}


def test_cutover_slot_buffer_expands_half_open_windows_and_touching_edges_are_free__buffered_candidate_refused(api):
    """The candidate collides with an expanded interval when the candidate's start is strictly before the expanded interval's end and the expanded interval's start is strictly before the candidate's end.

    The raw windows 14:00-18:00 and 18:30-20:30 do not touch at all; only the
    carrier's 60-minute expansion of the incumbent makes them collide.

    Design: Difficulty/resource_temporal_overlap/cutover_slot_buffer_expands_half_open_windows_and_touching_edges_are_free
    """
    scenario = _carrier_with_one_buffered_slot(api)

    response = api.create_cutover_slot(
        make_cutover_slot_payload(
            scenario["carrier"]["id"],
            window_start=_COLLIDING_START,
            window_end=_COLLIDING_END,
        ),
        make_porting_specialist_headers(),
    )
    # 120 minutes sits inside the 60..480 legal band, so the length test cannot
    # be what refused this candidate.
    validate_error(response, ApiErrorId.ERR_CUTOVER_SLOT_OVERLAP.value, 409)

    incumbent = read_cutover_slot(scenario["slot"]["id"])
    assert incumbent["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_cutover_slots(
            make_porting_specialist_headers(),
            params={"carrier_id": scenario["carrier"]["id"]},
        )
    )
    assert len(rows) == 1, f"the refused candidate must not persist, got {len(rows)} rows"


def test_cutover_slot_buffer_expands_half_open_windows_and_touching_edges_are_free__touching_expanded_edge_admitted(api):
    """Because both intervals are half-open, adjacency is permitted: a candidate whose `window_start` falls exactly on an expanded interval's end does not collide.

    The 18:30 candidate is refused and the 20:00 candidate — starting exactly on
    the incumbent's expanded end — is admitted.

    Design: Difficulty/resource_temporal_overlap/cutover_slot_buffer_expands_half_open_windows_and_touching_edges_are_free
    """
    scenario = _carrier_with_one_buffered_slot(api)

    validate_error(
        api.create_cutover_slot(
            make_cutover_slot_payload(
                scenario["carrier"]["id"],
                window_start=_COLLIDING_START,
                window_end=_COLLIDING_END,
            ),
            make_porting_specialist_headers(),
        ),
        ApiErrorId.ERR_CUTOVER_SLOT_OVERLAP.value,
        409,
    )

    admitted = validate_success(
        api.create_cutover_slot(
            make_cutover_slot_payload(
                scenario["carrier"]["id"],
                window_start=_TOUCHING_START,
                window_end=_TOUCHING_END,
            ),
            make_porting_specialist_headers(),
        ),
        201,
    )
    assert admitted["status"] == "OPEN"
    assert_instant(admitted["window_start"], _TOUCHING_START, "cutover_slot.window_start")
    assert_instant(admitted["window_end"], _TOUCHING_END, "cutover_slot.window_end")

    incumbent = read_cutover_slot(scenario["slot"]["id"])
    assert incumbent["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_cutover_slots(
            make_porting_specialist_headers(),
            params={"carrier_id": scenario["carrier"]["id"]},
        )
    )
    assert len(rows) == 2, f"expected the incumbent and the admitted slot, got {len(rows)}"
    assert sorted(ids_of(rows)) == sorted([scenario["slot"]["id"], admitted["id"]])


# ---------------------------------------------------------------------------
# resource_temporal_overlap / number_reservations_treat_touching_closed_
# endpoints_as_a_conflict
# ---------------------------------------------------------------------------
_RESERVATION_CLOCK = "2026-08-01T00:00:00.000Z"
_HOLD_FROM = "2026-08-05T00:00:00.000Z"
_HOLD_UNTIL = "2026-08-10T00:00:00.000Z"
# A second hold starting exactly on the incumbent's closed upper endpoint.
_TOUCHING_FROM = "2026-08-10T00:00:00.000Z"
# One second later, and therefore genuinely disjoint.
_DISJOINT_FROM = "2026-08-10T00:00:01.000Z"
_SECOND_HOLD_UNTIL = "2026-08-12T00:00:00.000Z"


def _number_with_one_closed_hold(api):
    """One minted number held over the closed interval 2026-08-05 .. 2026-08-10,
    inside a block whose reservation ceiling is deliberately never binding."""
    set_clock(_RESERVATION_CLOCK)
    account = seed_account("ACCT0015", billing_name="OSPREY LTD")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415566",
        total_capacity=20,
        max_concurrent_reservations=5,
    )
    number = seed_phone_number(block["id"], "1201")
    hold = seed_reservation(
        block["id"],
        account["id"],
        number_id=number["id"],
        purpose="NEW_LINE",
        reserved_from=_HOLD_FROM,
        reserved_until=_HOLD_UNTIL,
    )
    assert hold["status"] == "HELD"
    return {
        "account": account,
        "jurisdiction": jurisdiction,
        "block": block,
        "number": number,
        "hold": hold,
    }


def _reservation_request(scenario, reserved_from, reserved_until):
    """A same-number reservation payload carrying a freshly read block token."""
    return make_number_reservation_payload(
        scenario["block"]["id"],
        scenario["account"]["id"],
        block_version(scenario["block"]["id"]),
        reserved_from=reserved_from,
        reserved_until=reserved_until,
        purpose="NEW_LINE",
        number_id=scenario["number"]["id"],
    )


def test_number_reservations_treat_touching_closed_endpoints_as_a_conflict__touching_endpoint_refused(api):
    """Fourth, and only after selection, the chosen number is tested for its own conflicts: if any other `HELD` reservation of that same number has a closed interval intersecting the candidate, the request is refused with `ERR_NUMBER_RESERVATION_OVERLAP`.

    The candidate starts exactly on the incumbent's `reserved_until`, and closed
    endpoints intersect.

    Design: Difficulty/resource_temporal_overlap/number_reservations_treat_touching_closed_endpoints_as_a_conflict
    """
    scenario = _number_with_one_closed_hold(api)

    response = api.create_number_reservation(
        _reservation_request(scenario, _TOUCHING_FROM, _SECOND_HOLD_UNTIL),
        make_numbering_admin_headers(),
    )
    # The block ceiling is 5, the named number is RESERVED (an accepted status
    # for an explicit number_id) and the interval is well formed, so none of
    # ERR_BLOCK_RESERVATION_CAPACITY_EXCEEDED, ERR_PHONE_NUMBER_STATE_INVALID or
    # ERR_RESERVATION_WINDOW_INVALID may surface here.
    validate_error(response, ApiErrorId.ERR_NUMBER_RESERVATION_OVERLAP.value, 409)

    incumbent = read_reservation(scenario["hold"]["id"])
    assert incumbent["status"] == "HELD"
    assert_instant(
        incumbent["reserved_until"], _HOLD_UNTIL, "number_reservation.reserved_until"
    )

    number = read_phone_number(scenario["number"]["id"])
    assert number["status"] == "RESERVED"

    assert_block_census(
        read_number_block(scenario["block"]["id"]),
        minted=1,
        available=0,
        reserved=1,
        assigned=0,
        parked=0,
    )

    rows, _meta = validate_paginated(
        api.list_number_reservations(
            make_numbering_admin_headers(),
            params={"block_id": scenario["block"]["id"], "status": "HELD"},
        )
    )
    assert len(rows) == 1, f"the refused hold must not persist, got {len(rows)} rows"


def test_number_reservations_treat_touching_closed_endpoints_as_a_conflict__one_second_later_admitted(api):
    """An already-`RESERVED` number may legitimately take one further hold covering a disjoint interval, and whether the intervals are actually disjoint is settled by the same-number overlap check rather than by the status check.

    Moving the candidate start one second past the incumbent's closed upper
    endpoint makes the two intervals disjoint, and the hold is admitted.

    Design: Difficulty/resource_temporal_overlap/number_reservations_treat_touching_closed_endpoints_as_a_conflict
    """
    scenario = _number_with_one_closed_hold(api)

    validate_error(
        api.create_number_reservation(
            _reservation_request(scenario, _TOUCHING_FROM, _SECOND_HOLD_UNTIL),
            make_numbering_admin_headers(),
        ),
        ApiErrorId.ERR_NUMBER_RESERVATION_OVERLAP.value,
        409,
    )

    admitted = validate_success(
        api.create_number_reservation(
            _reservation_request(scenario, _DISJOINT_FROM, _SECOND_HOLD_UNTIL),
            make_numbering_admin_headers(),
        ),
        201,
    )
    assert admitted["status"] == "HELD"
    assert admitted["number_id"] == scenario["number"]["id"]
    assert_instant(
        admitted["reserved_from"], _DISJOINT_FROM, "number_reservation.reserved_from"
    )

    # Two holds, one number: the census still counts the single RESERVED row once.
    assert_block_census(
        read_number_block(scenario["block"]["id"]),
        minted=1,
        available=0,
        reserved=1,
        assigned=0,
        parked=0,
    )
    assert read_phone_number(scenario["number"]["id"])["status"] == "RESERVED"

    rows, _meta = validate_paginated(
        api.list_number_reservations(
            make_numbering_admin_headers(),
            params={"block_id": scenario["block"]["id"], "status": "HELD"},
        )
    )
    assert len(rows) == 2, f"expected two live holds on the number, got {len(rows)}"
    assert sorted(ids_of(rows)) == sorted([scenario["hold"]["id"], admitted["id"]])


# ---------------------------------------------------------------------------
# compensating_invariant / reserve_then_release_restores_block_census_counts_
# exactly
# ---------------------------------------------------------------------------
def _block_with_two_available_numbers(api):
    """A block holding exactly two AVAILABLE numbers, 1301 and 1302, whose
    pre-reservation census vector is minted 2 / available 2 / rest 0."""
    set_clock(_RESERVATION_CLOCK)
    account = seed_account("ACCT0016", billing_name="PONDEROSA SL")
    jurisdiction = seed_jurisdiction("CA", "06001")
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx="415567",
        total_capacity=20,
        max_concurrent_reservations=5,
    )
    first = seed_phone_number(block["id"], "1301")
    second = seed_phone_number(block["id"], "1302")
    before = read_number_block(block["id"])
    assert_block_census(before, minted=2, available=2, reserved=0, assigned=0, parked=0)
    return {
        "account": account,
        "jurisdiction": jurisdiction,
        "block": block,
        "first": first,
        "second": second,
        "before": census_snapshot(before),
    }


def test_reserve_then_release_restores_block_census_counts_exactly__reserve_draws_down_the_census(api):
    """A successful creation drives the selected number `AVAILABLE → RESERVED` when it was available, leaves it `RESERVED` when it was already held for a disjoint window, recomputes the block census so that `available_count` falls and `reserved_count` rises by 1, and increments the block's `version` by 1.

    Automatic selection takes the lowest `line_number`, so the hold lands on 1301
    and the conservation identity still closes at 2.

    Design: Difficulty/compensating_invariant/reserve_then_release_restores_block_census_counts_exactly
    """
    scenario = _block_with_two_available_numbers(api)

    hold = seed_reservation(scenario["block"]["id"], scenario["account"]["id"])
    assert hold["status"] == "HELD"
    assert hold["number_id"] == scenario["first"]["id"], (
        "the lowest line_number 1301 must be selected"
    )

    assert read_phone_number(scenario["first"]["id"])["status"] == "RESERVED"
    assert read_phone_number(scenario["second"]["id"])["status"] == "AVAILABLE"

    assert_block_census(
        read_number_block(scenario["block"]["id"]),
        minted=2,
        available=1,
        reserved=1,
        assigned=0,
        parked=0,
    )


def test_reserve_then_release_restores_block_census_counts_exactly__release_restores_the_exact_vector(api):
    """A hold followed by its release restores all four counters to their pre-hold values; an orphaned bridge instead moves one number out of `reserved_count` and into `parked_count`; and a later reclamation moves it from `parked_count` back into `available_count`.

    The compensation is a return to the whole pre-hold vector, not merely a
    decrement of `reserved_count`.

    Design: Difficulty/compensating_invariant/reserve_then_release_restores_block_census_counts_exactly
    """
    scenario = _block_with_two_available_numbers(api)

    hold = seed_reservation(scenario["block"]["id"], scenario["account"]["id"])
    release_reservation(hold["id"])

    after = read_number_block(scenario["block"]["id"])
    assert_block_census(after, minted=2, available=2, reserved=0, assigned=0, parked=0)
    assert census_snapshot(after) == scenario["before"], (
        f"census must return to {scenario['before']}, got {census_snapshot(after)}"
    )

    released_number = read_phone_number(scenario["first"]["id"])
    assert released_number["status"] == "AVAILABLE"
    assert released_number["park_cycle_count"] == 0
    assert_null(released_number["parked_until"], "phone_number.parked_until")

    # The number that was never held is untouched throughout.
    assert read_phone_number(scenario["second"]["id"])["status"] == "AVAILABLE"


def test_reserve_then_release_restores_block_census_counts_exactly__released_row_is_retained(api):
    """It drives `HELD → RELEASED` and sets `released_reason` to `MANUAL`.

    Compensation is not deletion: the released row survives with its number
    reference and its reason, and simply leaves the HELD population.

    Design: Difficulty/compensating_invariant/reserve_then_release_restores_block_census_counts_exactly
    """
    scenario = _block_with_two_available_numbers(api)

    hold = seed_reservation(scenario["block"]["id"], scenario["account"]["id"])
    release_reservation(hold["id"])

    row = read_reservation(hold["id"])
    assert row["status"] == "RELEASED"
    assert row["released_reason"] == "MANUAL"
    assert row["number_id"] == scenario["first"]["id"]

    held_rows, _held_meta = validate_paginated(
        api.list_number_reservations(
            make_numbering_admin_headers(),
            params={"block_id": scenario["block"]["id"], "status": "HELD"},
        )
    )
    assert held_rows == [], f"no hold may remain, got {ids_of(held_rows)}"

    all_rows, _all_meta = validate_paginated(
        api.list_number_reservations(
            make_numbering_admin_headers(),
            params={"block_id": scenario["block"]["id"]},
        )
    )
    assert ids_of(all_rows) == [hold["id"]], (
        f"the released row must be retained, got {ids_of(all_rows)}"
    )


# ---------------------------------------------------------------------------
# compensating_invariant / assess_then_void_restores_jurisdiction_and_account_
# fee_cents
# ---------------------------------------------------------------------------
_ASSESSMENT_PERIOD = "2026-08"
_MID_PERIOD_CLOCK = "2026-08-15T12:00:00.000Z"
# One PER_LINE unit anchored on day 1 of a 31-day month: 175 * 31 / 31 = 175.
_EXPECTED_UNIT_CENTS = 175


def _one_billable_line_mid_period(api):
    """A single number-holding device with a VERIFIED location captured on day 1
    of the period, with both fee ledgers still at zero and the clock mid-month."""
    scenario = setup_compliant_device(
        account_number="ACCT0017",
        npa_nxx="415568",
        line_number="1401",
        mac_address="AABBCC000091",
    )
    jurisdiction = read_jurisdiction(scenario["jurisdiction"]["id"])
    assert jurisdiction["fee_type"] == "PER_LINE"
    assert_cents_equal(jurisdiction["monthly_fee_cents"], 175, "jurisdiction.monthly_fee_cents")
    assert_cents_equal(jurisdiction["pending_fee_cents"], 0, "jurisdiction.pending_fee_cents")
    assert_cents_equal(jurisdiction["remitted_fee_cents"], 0, "jurisdiction.remitted_fee_cents")
    assert_cents_equal(
        read_account(scenario["account"]["id"])["fee_liability_cents"],
        0,
        "account.fee_liability_cents",
    )

    set_clock(_MID_PERIOD_CLOCK)
    return scenario


def _assess_as_billing_one(api, scenario):
    return validate_success(
        api.create_fee_assessment(
            make_fee_assessment_payload(
                scenario["account"]["id"],
                scenario["jurisdiction"]["id"],
                _ASSESSMENT_PERIOD,
            ),
            make_billing_admin_headers(BILLING_USER_ID),
        ),
        201,
    )


def _void_as_billing_two(api, assessment_id):
    return validate_success(
        api.void_fee_assessment(
            assessment_id,
            make_void_payload(void_note="assessed against the wrong jurisdiction"),
            make_billing_admin_headers(BILLING_USER_ID_ALT),
        ),
        200,
    )


def test_assess_then_void_restores_jurisdiction_and_account_fee_cents__assessment_raises_both_ledgers(api):
    """Otherwise the row is created with `variant` `PROVISIONAL`, `status` `ASSESSED` and `assessed_by_user_id` set to the acting `X-User-ID`, and the fee ledger is recomputed, raising the jurisdiction's `pending_fee_cents` and the account's `fee_liability_cents` by `amount_cents`.

    Design: Difficulty/compensating_invariant/assess_then_void_restores_jurisdiction_and_account_fee_cents
    """
    scenario = _one_billable_line_mid_period(api)

    assessment = _assess_as_billing_one(api, scenario)
    assert assessment["variant"] == "PROVISIONAL"
    assert assessment["status"] == "ASSESSED"
    assert assessment["unit_basis"] == "PER_LINE"
    assert assessment["billable_units"] == 1
    assert assessment["unit_fee_breakdown"] == [_EXPECTED_UNIT_CENTS]
    assert_cents_equal(assessment["amount_cents"], _EXPECTED_UNIT_CENTS)
    assert assessment["assessed_by_user_id"] == BILLING_USER_ID
    assert_null(assessment["voided_by_user_id"], "fee_assessment.voided_by_user_id")

    jurisdiction = read_jurisdiction(scenario["jurisdiction"]["id"])
    assert_cents_equal(
        jurisdiction["pending_fee_cents"],
        _EXPECTED_UNIT_CENTS,
        "jurisdiction.pending_fee_cents",
    )
    assert_cents_equal(
        jurisdiction["remitted_fee_cents"], 0, "jurisdiction.remitted_fee_cents"
    )
    assert_cents_equal(
        read_account(scenario["account"]["id"])["fee_liability_cents"],
        _EXPECTED_UNIT_CENTS,
        "account.fee_liability_cents",
    )


def test_assess_then_void_restores_jurisdiction_and_account_fee_cents__void_returns_both_ledgers_to_zero(api):
    """A successful void moves the row `ASSESSED → VOIDED`, records `voided_by_user_id`, increments the assessment's `version` by 1, and recomputes the fee ledger so that the jurisdiction's `pending_fee_cents` and the account's `fee_liability_cents` return to the exact cent values they held before the assessment existed.

    The compensation is gated by segregation of duties, so it is performed by a
    second administrator.

    Design: Difficulty/compensating_invariant/assess_then_void_restores_jurisdiction_and_account_fee_cents
    """
    scenario = _one_billable_line_mid_period(api)

    assessment = _assess_as_billing_one(api, scenario)
    voided = _void_as_billing_two(api, assessment["id"])

    assert voided["status"] == "VOIDED"
    assert voided["assessed_by_user_id"] == BILLING_USER_ID
    assert voided["voided_by_user_id"] == BILLING_USER_ID_ALT
    assert voided["version"] == assessment["version"] + 1

    jurisdiction = read_jurisdiction(scenario["jurisdiction"]["id"])
    assert_cents_equal(
        jurisdiction["pending_fee_cents"], 0, "jurisdiction.pending_fee_cents"
    )
    assert_cents_equal(
        jurisdiction["remitted_fee_cents"], 0, "jurisdiction.remitted_fee_cents"
    )
    assert_cents_equal(
        read_account(scenario["account"]["id"])["fee_liability_cents"],
        0,
        "account.fee_liability_cents",
    )


def test_assess_then_void_restores_jurisdiction_and_account_fee_cents__voided_row_is_retained_for_audit(api):
    """The voided row itself is retained for audit and is never deleted.

    The row keeps the money it charged while contributing zero to either ledger,
    which is exactly what the jurisdiction's reconciliation identity requires.

    Design: Difficulty/compensating_invariant/assess_then_void_restores_jurisdiction_and_account_fee_cents
    """
    scenario = _one_billable_line_mid_period(api)

    assessment = _assess_as_billing_one(api, scenario)
    _void_as_billing_two(api, assessment["id"])

    retained = validate_success(
        api.get_fee_assessment(
            assessment["id"], make_billing_admin_headers(BILLING_USER_ID_ALT)
        ),
        200,
    )
    assert retained["status"] == "VOIDED"
    assert_cents_equal(retained["amount_cents"], _EXPECTED_UNIT_CENTS)
    assert retained["unit_fee_breakdown"] == [_EXPECTED_UNIT_CENTS]
    assert retained["period_month"] == _ASSESSMENT_PERIOD

    rows, _meta = validate_paginated(
        api.list_fee_assessments(
            make_billing_admin_headers(BILLING_USER_ID),
            params={"jurisdiction_id": scenario["jurisdiction"]["id"]},
        )
    )
    non_voided_total = sum(
        row["amount_cents"] for row in rows if row["status"] != "VOIDED"
    )
    jurisdiction = read_jurisdiction(scenario["jurisdiction"]["id"])
    assert (
        jurisdiction["pending_fee_cents"] + jurisdiction["remitted_fee_cents"]
        == non_voided_total
        == 0
    ), (
        "pending + remitted must equal the non-VOIDED total: "
        f"{jurisdiction['pending_fee_cents']} + {jurisdiction['remitted_fee_cents']} "
        f"vs {non_voided_total}"
    )

    voided_rows, _voided_meta = validate_paginated(
        api.list_fee_assessments(
            make_billing_admin_headers(BILLING_USER_ID),
            params={
                "jurisdiction_id": scenario["jurisdiction"]["id"],
                "status": "VOIDED",
            },
        )
    )
    assert ids_of(voided_rows) == [assessment["id"]], (
        f"expected exactly the voided row, got {ids_of(voided_rows)}"
    )
