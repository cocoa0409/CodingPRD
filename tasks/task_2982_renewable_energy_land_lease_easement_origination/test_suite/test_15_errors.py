"""Error-code claims: the identity gate, interval shapes, temporal gates and recording replays."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_ALREADY_RECORDED,
    ERR_CONSENT_EXPIRED,
    ERR_CURATIVE_BLOCKED_PREDECESSOR,
    ERR_INVALID_STATION_RANGE,
    ERR_INVALID_WINDOW_RANGE,
    ERR_MISSING_USER_ID,
    ERR_SECURITY_NOT_POSTED,
    ERR_WINDOW_IN_PAST,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_null,
    assert_page_meta,
    assert_status,
)
from test_helpers.factories import (
    booking_payload,
    crossing_payload,
    parcel_payload,
    record_memo_payload,
)
from test_helpers.fixtures import (
    accept_option,
    client,
    draft_option,
    execute_option,
    exercise_option,
    parcels_page,
    plan_corridor,
    post_security,
    publish_setback_rule,
    raise_curative,
    read_consent,
    read_curative,
    read_landowner,
    read_lease,
    read_parcel,
    record_memo,
    register_landowner,
    register_parcel,
    request_consent,
    send_option,
    set_clock,
    submit_memo,
)
from test_helpers.test_users import (
    LAND_AGENT,
    PORTFOLIO_MANAGER,
    TITLE_COUNSEL,
    TITLE_COUNSEL_2,
    headers_without_user_id,
)

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"

CLEAN_INPUTS = {
    "county_fips": CLEAN_COUNTY,
    "gross_acres": 200.00,
    "interconnection_distance_km": 3.50,
    "resource_capacity_factor": 0.38,
    "slope_pct": 4.0,
    "title_condition_grade": "B",
    "zoning_code": "AG2",
}


def _owner_and_tract(apn: str = "R-9001-001"):
    """One owner and one clean two-hundred-acre tract in an unregulated county."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    return landowner_id, register_parcel(landowner_id, apn=apn, **CLEAN_INPUTS)


def test_a_request_without_an_acting_identifier_is_refused_before_anything_else():
    """
    The role header is valid and the body would have been accepted outright, but the
    acting principal is not named — and that is the first thing the server checks, so
    the parcel is never registered.

    PRD: "If either header is absent, or is present but empty, the request is rejected
    with `ERR_MISSING_USER_ID` and HTTP 401."

    Design: Corner/errors/missing_x_user_id_header_returns_unauthenticated
    """
    landowner_id = register_landowner(**SANDHILL)["id"]

    response = client().create_parcel(
        parcel_payload(landowner_id, apn="R-9001-001", **CLEAN_INPUTS),
        headers_without_user_id(),
    )

    validate_error(response, ERR_MISSING_USER_ID, 401)
    _rows, meta = parcels_page(LAND_AGENT)
    assert_page_meta(meta, total_count=0)


def test_a_crossing_running_past_the_end_of_the_route_is_refused():
    """
    Four thousand eight hundred to five thousand two hundred is a well-ordered
    interval of positive integers; the only thing wrong with it is that the corridor
    it is measured against is five kilometres long.

    PRD: "Two shape rules apply before anything else: `station_end_m` must be strictly
    greater than `station_start_m`, `station_start_m` must be zero or greater, and
    `station_end_m` must not exceed the corridor's `total_length_m`, with any violation
    refused as `ERR_INVALID_STATION_RANGE` (422); and `occupancy_window_end` must be
    strictly after `occupancy_window_start`, an empty or inverted window being refused
    as `ERR_INVALID_WINDOW_RANGE` (422)."

    Design: Corner/errors/crossing_beyond_the_corridor_length_returns_invalid_station_range
    """
    _landowner_id, parcel = _owner_and_tract()
    corridor = plan_corridor(
        route_name="Sandhill Collection A",
        total_length_m=5000,
        voltage_class="COLLECTION_34_5KV",
        buffer_m=50,
    )

    response = client().create_crossing_agreement(
        crossing_payload(
            corridor["id"],
            parcel["id"],
            crossing_kind="COLLECTION_LINE",
            station_start_m=4800,
            station_end_m=5200,
            occupancy_window_start="2026-08-05T00:00:00Z",
            occupancy_window_end="2026-08-20T00:00:00Z",
        ),
        LAND_AGENT,
    )

    validate_error(response, ERR_INVALID_STATION_RANGE, 422)
    _rows, meta = validate_paginated(
        client().list_crossing_agreements(LAND_AGENT, {"corridor_id": corridor["id"]})
    )
    assert_page_meta(meta, total_count=0)


def test_a_booking_whose_window_runs_backwards_is_refused():
    """
    The window is entirely in the future, so the past-dating gate cannot be the one
    answering: it is the interval shape itself, whose end must fall strictly after its
    start.

    PRD: "An empty or inverted window is refused with `ERR_INVALID_WINDOW_RANGE`
    (422), and a `window_start` strictly before the current logical clock is refused
    with `ERR_WINDOW_IN_PAST` (422) — crews cannot be booked into the past, though a
    booking starting at exactly the current instant is admissible."

    Design: Corner/errors/booking_with_an_inverted_window_returns_invalid_window_range
    """
    _landowner_id, parcel = _owner_and_tract()

    response = client().create_site_access_booking(
        booking_payload(
            parcel["id"],
            purpose="TITLE_SURVEY",
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-10T00:00:00Z",
            crew_count=2,
        ),
        LAND_AGENT,
    )

    validate_error(response, ERR_INVALID_WINDOW_RANGE, 422)
    _rows, meta = validate_paginated(
        client().list_site_access_bookings(LAND_AGENT, {"parcel_id": parcel["id"]})
    )
    assert_page_meta(meta, total_count=0)


def test_a_window_starting_before_the_logical_clock_is_refused():
    """
    The clock has been moved a month on, and a window that was perfectly bookable at
    the default instant is now in the past. Nothing was there to sweep on the way.

    PRD: "An empty or inverted window is refused with `ERR_INVALID_WINDOW_RANGE`
    (422), and a `window_start` strictly before the current logical clock is refused
    with `ERR_WINDOW_IN_PAST` (422) — crews cannot be booked into the past, though a
    booking starting at exactly the current instant is admissible."

    Design: Corner/errors/booking_before_the_logical_clock_returns_window_in_past
    """
    _landowner_id, parcel = _owner_and_tract()
    sweeps = set_clock("2026-09-01T00:00:00Z")

    response = client().create_site_access_booking(
        booking_payload(
            parcel["id"],
            purpose="GEOTECH",
            window_start="2026-08-15T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            crew_count=2,
        ),
        TITLE_COUNSEL,
    )

    validate_error(response, ERR_WINDOW_IN_PAST, 422)
    assert sweeps["completed_booking_count"] == 0, sweeps["completed_booking_count"]
    _rows, meta = validate_paginated(
        client().list_site_access_bookings(LAND_AGENT, {"parcel_id": parcel["id"]})
    )
    assert_page_meta(meta, total_count=0)


def test_the_same_crew_booked_after_the_new_clock_reading_is_accepted():
    """
    Only the comparison against the logical clock changes: the identical body, shifted
    to a window that opens after the new reading, is admitted.

    PRD: "The server does not read wall-clock time for business decisions."

    Design: Corner/errors/booking_before_the_logical_clock_returns_window_in_past
    """
    _landowner_id, parcel = _owner_and_tract()
    set_clock("2026-09-01T00:00:00Z")
    refused = client().create_site_access_booking(
        booking_payload(
            parcel["id"],
            purpose="GEOTECH",
            window_start="2026-08-15T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            crew_count=2,
        ),
        TITLE_COUNSEL,
    )
    validate_error(refused, ERR_WINDOW_IN_PAST, 422)

    response = client().create_site_access_booking(
        booking_payload(
            parcel["id"],
            purpose="GEOTECH",
            window_start="2026-09-05T00:00:00Z",
            window_end="2026-09-10T00:00:00Z",
            crew_count=2,
        ),
        TITLE_COUNSEL,
    )

    booking = validate_success(response, 201)
    assert_status(booking, "BOOKED", "booking")
    assert booking["crew_count"] == 2, booking["crew_count"]


def _consent_lapsing_at_the_end_of_august():
    """A thirty-day consent window and a clock parked exactly on its last instant."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    rule = publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=150,
        encumbrance_rate_per_acre=0.0500,
        consent_waivable=True,
    )
    parcel = register_parcel(landowner_id, apn="R-9001-001", **CLEAN_INPUTS)
    assert_acres_equals(parcel["raw_setback_acres"], 10.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 190.00, "buildable_acres")
    assert_status(parcel, "QUALIFIED", "parcel")
    consent = request_consent(
        parcel["id"], rule["id"], neighbor_name="H. Vaughn", consent_expiry_days=30
    )
    assert_instant_equals(
        consent["consent_expiry_at"], "2026-08-31T00:00:00Z", "consent_expiry_at"
    )
    sweeps = set_clock("2026-08-31T00:00:00Z")
    assert sweeps["expired_consent_count"] == 1, sweeps["expired_consent_count"]
    return landowner_id, parcel["id"], consent["id"]


def test_a_consent_grant_at_the_expiry_instant_is_refused_as_expired():
    """
    Equality lapses, so the sweep has already carried the consent to its terminal
    status — and the answer is still the expiry code rather than the generic
    from-state complaint, because the expiry gate is checked first.

    PRD: "The logical clock must be **strictly before** `consent_expiry_at` — equality
    lapses, so at exactly the expiry instant the request is treated as expired rather
    than grantable, and the rejection is `ERR_CONSENT_EXPIRED` (422)."

    Design: Corner/errors/grant_after_the_consent_expiry_sweep_returns_consent_expired
    """
    _landowner_id, _parcel_id, consent_id = _consent_lapsing_at_the_end_of_august()

    response = client().grant_neighbor_consent(consent_id, {}, LAND_AGENT)

    validate_error(response, ERR_CONSENT_EXPIRED, 422)
    consent = read_consent(consent_id)
    assert_status(consent, "EXPIRED", "consent")
    assert_acres_equals(consent["released_acres"], 0.00, "released_acres")
    assert_null(consent["granted_at"], "granted_at")


def test_the_lapsed_consent_released_no_acreage_on_its_way_out():
    """
    A consent that was never signed had nothing to give back, so neither the sweep
    that expired it nor the refused grant may move the parcel's encumbrance.

    PRD: "No acreage recompute fires, because a consent that was never granted had
    released no acres in the first place."

    Design: Corner/errors/grant_after_the_consent_expiry_sweep_returns_consent_expired
    """
    _landowner_id, parcel_id, consent_id = _consent_lapsing_at_the_end_of_august()

    response = client().grant_neighbor_consent(consent_id, {}, LAND_AGENT)
    validate_error(response, ERR_CONSENT_EXPIRED, 422)

    parcel = read_parcel(parcel_id)
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 10.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["buildable_acres"], 190.00, "buildable_acres")


def _defect_waiting_on_an_unresolved_predecessor():
    """Two blocking defects, the second one queued behind the first."""
    _landowner_id, parcel = _owner_and_tract()
    first = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=250000,
    )
    second = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="MORTGAGE_SUBORDINATION",
        severity="BLOCKING",
        curative_cost_cents=180000,
        blocks_item_id=first["id"],
    )
    assert_status(first, "OPEN", "item A")
    assert_status(second, "BLOCKED", "item B")
    return parcel["id"], first, second


def test_clearing_a_defect_still_queued_behind_another_is_refused():
    """
    A second counsel is acting, so the segregation gate passes and the only remaining
    objection is that the predecessor has not been resolved: the queued item stays
    exactly where the raise put it.

    PRD: "The item must be in `OPEN`; an item still in `BLOCKED` is refused with
    `ERR_CURATIVE_BLOCKED_PREDECESSOR` (422), and the parcel must not be
    `DISQUALIFIED`, which is `ERR_INVALID_STATE` (409)."

    Design: Corner/errors/clear_a_still_blocked_item_returns_curative_blocked_predecessor
    """
    _parcel_id, _first, second = _defect_waiting_on_an_unresolved_predecessor()

    response = client().clear_curative_item(second["id"], {}, TITLE_COUNSEL_2)

    validate_error(response, ERR_CURATIVE_BLOCKED_PREDECESSOR, 422)
    item = read_curative(second["id"])
    assert_status(item, "BLOCKED", "item B")
    assert_null(item["cleared_at"], "cleared_at")


def test_the_refused_clearing_capitalises_no_curative_cost():
    """
    Cost is capitalised by a successful clearing and by nothing else, so the parcel
    still carries nothing against two open blocking defects and is nowhere near
    qualification.

    PRD: "On success, hop one moves the item `OPEN → CLEARED`, stamps `cleared_at` from
    the logical clock and `cleared_by_user_id` from the acting identifier, and **adds
    this item's `curative_cost_cents` to the parcel's `curative_cost_cents`**."

    Design: Corner/errors/clear_a_still_blocked_item_returns_curative_blocked_predecessor
    """
    parcel_id, _first, second = _defect_waiting_on_an_unresolved_predecessor()

    response = client().clear_curative_item(second["id"], {}, TITLE_COUNSEL_2)
    validate_error(response, ERR_CURATIVE_BLOCKED_PREDECESSOR, 422)

    parcel = read_parcel(parcel_id)
    assert_cents_equals(parcel["curative_cost_cents"], 0, "curative_cost_cents")
    assert parcel["blocking_curative_open_count"] == 2, (
        parcel["blocking_curative_open_count"]
    )
    assert_status(parcel, "SCREENING", "parcel")


def _exercised_lease_with_nothing_posted():
    """A lease over two hundred as-built acres, its security requirement untouched."""
    landowner_id, parcel = _owner_and_tract()
    option = draft_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        rent_structure_type="PER_ACRE",
        base_rent_per_acre_cents=120000,
        royalty_rate_bps=0,
        escalator_pct_bps=200,
        escalator_mode="SIMPLE",
    )
    send_option(option["id"])
    accept_option(option["id"], landowner_id)
    execute_option(option["id"])
    lease = exercise_option(option["id"], "NOE-2026-0001")
    assert_cents_equals(lease["security_posted_cents"], 0, "security_posted_cents")
    assert_cents_equals(
        lease["total_security_required_cents"], 10450000, "total_security_required_cents"
    )
    return landowner_id, parcel["id"], lease


def test_submitting_the_memorandum_before_the_security_is_posted_is_refused():
    """
    The first of the three gates is the one that answers: nothing has been posted
    against a requirement of a hundred and four thousand five hundred dollars, so the
    recording dimension does not move off its initial value.

    PRD: "Three conditions gate it: `security_posted_cents` must have reached
    `total_security_required_cents`, or the submission is refused with
    `ERR_SECURITY_NOT_POSTED` (422); the parcel's `blocking_curative_open_count` must be
    zero, or it is refused with `ERR_TITLE_CURATIVE_BLOCKING` (422); and a lease whose
    `recording_status` is already `RECORDED` is refused with `ERR_ALREADY_RECORDED`
    (409), the same code that answers a second recording attempt."

    Design: Corner/errors/submit_memo_without_posted_security_returns_security_not_posted
    """
    _landowner_id, _parcel_id, lease = _exercised_lease_with_nothing_posted()

    response = client().submit_memo(lease["id"], {}, PORTFOLIO_MANAGER)

    validate_error(response, ERR_SECURITY_NOT_POSTED, 422)
    after = read_lease(lease["id"])
    assert after["recording_status"] == "UNRECORDED", after["recording_status"]
    assert_null(after["memo_submitted_at"], "memo_submitted_at")


def test_the_refused_submission_leaves_the_parcel_under_option():
    """
    Conveyance is carried by recording and by nothing earlier, so a parcel whose lease
    exists but cannot yet be submitted is still merely optioned, and its owner's posture
    with it.

    PRD: "Crucially, **the parcel does not become `LEASED` at exercise** — it stays in
    `OPTIONED` until the memorandum is actually recorded with the county."

    Design: Corner/errors/submit_memo_without_posted_security_returns_security_not_posted
    """
    landowner_id, parcel_id, lease = _exercised_lease_with_nothing_posted()

    response = client().submit_memo(lease["id"], {}, PORTFOLIO_MANAGER)
    validate_error(response, ERR_SECURITY_NOT_POSTED, 422)

    assert_status(read_parcel(parcel_id), "OPTIONED", "parcel")
    assert_status(read_landowner(landowner_id), "UNDER_OPTION", "landowner")


def _recorded_lease():
    """A lease carried all the way to the county recorder under one instrument number."""
    landowner_id, parcel_id, lease = _exercised_lease_with_nothing_posted()
    post_security(lease["id"], 10450000)
    submit_memo(lease["id"])
    recorded = record_memo(lease["id"], "2026-0091001")
    assert recorded["recording_status"] == "RECORDED", recorded["recording_status"]
    return landowner_id, parcel_id, lease["id"]


def test_a_second_recording_attempt_is_refused_as_already_recorded():
    """
    The replay quotes a different instrument number, which is exactly what must not be
    allowed to overwrite the one the county indexed: the conflict is refused and the
    stored number and instant are the ones the first recording wrote.

    PRD: "**Recording the memorandum** moves `recording_status` `MEMO_SUBMITTED →
    RECORDED` and carries the county's `recording_instrument_no`, which the server
    stores alongside `recorded_at` from the logical clock."

    Design: Corner/errors/record_memo_a_second_time_returns_already_recorded
    """
    _landowner_id, _parcel_id, lease_id = _recorded_lease()

    response = client().record_memo(
        lease_id,
        record_memo_payload(recording_instrument_no="2026-0099999"),
        PORTFOLIO_MANAGER,
    )

    validate_error(response, ERR_ALREADY_RECORDED, 409)
    after = read_lease(lease_id)
    assert after["recording_instrument_no"] == "2026-0091001", (
        after["recording_instrument_no"]
    )
    assert_instant_equals(after["recorded_at"], "2026-08-01T00:00:00Z", "recorded_at")


def test_the_same_code_answers_a_replayed_submission_on_a_recorded_lease():
    """
    One code serves both replays. The submission is refused on the recorded lease by
    the third of its three gates, and the cascade the first recording ran — the parcel
    to its terminal status and the owner to the leased posture — is left standing.

    PRD: "Recording then cascades in three hops: the recording dimension reaches the
    terminal `RECORDED`, the parcel finally moves `OPTIONED → LEASED` — its own terminal
    status — and the owner's posture advances `UNDER_OPTION → UNDER_LEASE`."

    Design: Corner/errors/record_memo_a_second_time_returns_already_recorded
    """
    landowner_id, parcel_id, lease_id = _recorded_lease()

    response = client().submit_memo(lease_id, {}, PORTFOLIO_MANAGER)

    validate_error(response, ERR_ALREADY_RECORDED, 409)
    assert read_lease(lease_id)["recording_status"] == "RECORDED"
    assert_status(read_parcel(parcel_id), "LEASED", "parcel")
    assert_status(read_landowner(landowner_id), "UNDER_LEASE", "landowner")
