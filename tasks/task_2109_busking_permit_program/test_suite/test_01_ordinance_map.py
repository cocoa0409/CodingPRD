"""The ordinance map: registering districts and their designated pitches."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_zone, assert_pitch,
    create_zone_payload, create_pitch_payload,
    create_zone, create_pitch,
    make_officer_headers,
)
from test_helpers.api_client import api_client


def test_district_registration_returns_every_declared_field(api):
    """PRD §4: "Creating a brand-new resource answers **201 Created**; every
    other successful call — reads, state transitions, payments, cancellations,
    the epoch advance and the clock move — answers **200 OK**."
    PRD §3.1: "Finally, `max_concurrent_closures`, which defaults to 1 and may
    not exceed 5, caps how many street closures may cover any single instant in
    the district, and `active_closure_count` is a computed counter that starts
    at 0 when the district is registered and tracks the closures currently in
    force there."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row, whether the
    mutation was requested directly by a client or produced as a side effect of
    an operation on another resource."

    Design: Corner/entities/corner_zone_creation_returns_every_declared_field
    """
    resp = api.create_zone(
        create_zone_payload(name="Riverside Plaza", code="RP",
                            base_noise_cap_db=78, evening_start_minute=1080,
                            quiet_hours_start_minute=1380,
                            quiet_hours_end_minute=360,
                            weekend_noise_bonus_db=3, evening_penalty_db=5,
                            max_concurrent_closures=1),
        make_officer_headers())
    zone = validate_success(resp, 201)
    assert_zone(zone)
    assert zone["name"] == "Riverside Plaza"
    assert zone["code"] == "RP"
    assert zone["base_noise_cap_db"] == 78
    assert zone["quiet_hours_start_minute"] == 1380
    assert zone["active_closure_count"] == 0, \
        "active_closure_count starts at 0 when the district is registered"
    assert zone["version"] == 1, "version starts at 1 when the row is created"

    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_pitch_and_district_optional_inputs_take_their_declared_defaults(api):
    """PRD §3.1: "Four optional knobs shape how the pitch is used:
    `amplification_allowed` defaults to false and decides whether any amplified
    act may occupy the pitch at all; `max_session_minutes` defaults to 120 and
    must lie between 15 and 240, capping the length of a single session;
    `daily_session_cap` defaults to 3 and must lie between 1 and 12, capping how
    many live sessions the pitch may hold on one UTC calendar date; and
    `premium_slots_per_draw` defaults to 1 and may not exceed 5, fixing how many
    winners a rotation draw on this pitch awards."
    PRD §3.1: "A pitch may also nominate a `fallback_pitch_id`, defaulting to
    null, naming the sibling pitch that displaced sessions are moved to when the
    street closes."
    PRD §3.1: "Newly registered pitches start with `availability_status` of
    `OPEN`; it becomes `CLOSED` while a closure covers them and returns to
    `OPEN` only when the last covering closure is lifted."

    Design: Corner/entities/corner_pitch_defaults_applied_when_optional_inputs_omitted
    """
    zone = validate_success(api.create_zone(
        {"name": "Riverside Plaza", "code": "RP", "base_noise_cap_db": 78,
         "evening_start_minute": 1080, "quiet_hours_start_minute": 1380,
         "quiet_hours_end_minute": 360},
        make_officer_headers()), 201)

    pitch = validate_success(api.create_pitch(
        {"zone_id": zone["id"], "code": "RP-09", "tier": "STANDARD",
         "noise_cap_db": 80},
        make_officer_headers()), 201)
    assert_pitch(pitch)
    assert pitch["amplification_allowed"] is False
    assert pitch["max_session_minutes"] == 120
    assert pitch["daily_session_cap"] == 3
    assert pitch["premium_slots_per_draw"] == 1
    assert pitch["fallback_pitch_id"] is None
    assert pitch["availability_status"] == "OPEN"

    assert zone["weekend_noise_bonus_db"] == 0
    assert zone["evening_penalty_db"] == 0
    assert zone["max_concurrent_closures"] == 1


def test_pitch_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted,
    may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "`total_count` is the number of rows matching the request's
    filters before pagination is applied, and `has_more` is true when rows
    remain beyond the current page."

    Design: Corner/entities/corner_pitch_listing_paginates_with_total_count_and_has_more
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    create_pitch(zone["id"], code="RP-01", tier="STANDARD", noise_cap_db=82)
    create_pitch(zone["id"], code="RP-02", tier="STANDARD", noise_cap_db=80)
    create_pitch(zone["id"], code="RP-P1", tier="PREMIUM", noise_cap_db=84)

    first_resp = api.list_pitches(make_officer_headers(),
                                  params={"zone_id": zone["id"], "limit": 2,
                                          "offset": 0})
    rows, meta = validate_paginated(first_resp)
    assert len(rows) == 2, f"limit=2 must return 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert first_resp.json()["response_type"] == "array"

    second_resp = api.list_pitches(make_officer_headers(),
                                   params={"zone_id": zone["id"], "limit": 2,
                                           "offset": 2})
    rows2, meta2 = validate_paginated(second_resp)
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert second_resp.json()["response_type"] == "array"


def test_reading_an_unknown_pitch_returns_pitch_not_found(api):
    """PRD §2.11: "The not-found errors are `ERR_ZONE_NOT_FOUND`,
    `ERR_PITCH_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`,
    `ERR_ENTRY_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`
    and `ERR_CLOSURE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/corner_pitch_not_found_returns_404
    """
    resp = api.get_pitch(NON_EXISTENT_UUID, make_officer_headers())
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_NOT_FOUND)


def test_pitch_tier_outside_its_declared_set_is_rejected(api):
    """PRD §3.1: "The `tier` is either `PREMIUM` or `STANDARD`: standard pitches
    are booked directly, first come first served, while premium pitches are
    allocated only through rotation draws."
    PRD §2.6: "Well-formedness at step 6 means: every required field is present;
    every enumerated value is a member of its declared set; every integer sits
    inside its declared range; `end_at` is strictly after `start_at`; `ends_at`
    is strictly after `starts_at`; `entry_deadline_at` is strictly before
    `slot_start_at`; `decision_note` is present and non-empty when the decision
    outcome is `CHANGES_REQUESTED`; and the `season_year` supplied on a renewal
    equals the permit's current `season_year` plus one."

    Design: Corner/entities/corner_pitch_invalid_tier_enum_rejected
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    resp = api.create_pitch(
        {"zone_id": zone["id"], "code": "RP-BAD", "tier": "GOLD",
         "noise_cap_db": 80},
        make_officer_headers())
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_pitches(
        make_officer_headers(), params={"zone_id": zone["id"]}))
    assert meta["total_count"] == 0, "the rejected pitch must not have been created"


def test_pitch_registration_with_unknown_district_returns_zone_not_found(api):
    """PRD §2.6: "Every foreign key supplied in the request body resolves to a
    live row, validated in the order the fields appear in that endpoint's input
    list, otherwise the matching not-found error. This applies to pitch
    registration, application creation, audition scheduling, draw creation,
    lottery entry filing, session booking, noise-reading filing, complaint
    intake and closure-order drafting."

    Design: Corner/entities/corner_pitch_creation_with_unknown_zone_returns_zone_not_found
    """
    resp = api.create_pitch(
        {"zone_id": NON_EXISTENT_UUID, "code": "RP-01", "tier": "STANDARD",
         "noise_cap_db": 82},
        make_officer_headers())
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND)


def test_fallback_pitch_in_another_district_is_rejected(api):
    """PRD §3.1: "That sibling must belong to the same `zone_id` and must not be
    the pitch being registered itself; either mistake is refused with
    `ERR_PITCH_ZONE_MISMATCH`."

    Design: Corner/entities/corner_pitch_fallback_must_sit_in_the_same_zone
    """
    riverside = create_zone(name="Riverside Plaza", code="RP",
                            weekend_noise_bonus_db=0, evening_penalty_db=0)
    old_town = create_zone(name="Old Town", code="OT", base_noise_cap_db=72,
                           evening_start_minute=1020,
                           quiet_hours_start_minute=1260,
                           quiet_hours_end_minute=480,
                           weekend_noise_bonus_db=0, evening_penalty_db=0,
                           max_concurrent_closures=2)
    foreign_pitch = create_pitch(old_town["id"], code="OT-01", tier="STANDARD",
                                 noise_cap_db=70, amplification_allowed=False)

    resp = api.create_pitch(
        create_pitch_payload(riverside["id"], code="RP-01", tier="STANDARD",
                             noise_cap_db=82,
                             fallback_pitch_id=foreign_pitch["id"]),
        make_officer_headers())
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_ZONE_MISMATCH)

    _, meta = validate_paginated(api.list_pitches(
        make_officer_headers(), params={"zone_id": riverside["id"]}))
    assert meta["total_count"] == 0


def test_duplicate_district_code_is_refused(api):
    """PRD §3.1: "Registering a district whose `code` is already in use is
    refused with `ERR_ZONE_CODE_TAKEN`."

    Design: Corner/entities/corner_zone_code_uniqueness_enforced
    """
    first = create_zone(name="Riverside Plaza", code="RP",
                        weekend_noise_bonus_db=0, evening_penalty_db=0)
    resp = api.create_zone(
        create_zone_payload(name="Riverside Plaza Annex", code="RP",
                            base_noise_cap_db=74, weekend_noise_bonus_db=0,
                            evening_penalty_db=0),
        make_officer_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_ZONE_CODE_TAKEN)

    reread = validate_success(api.get_zone(first["id"], make_officer_headers()))
    assert reread["name"] == "Riverside Plaza", \
        "the incumbent district must be untouched by the refused registration"


def test_pitch_code_is_unique_across_every_district(api):
    """PRD §3.1: "A pitch is registered with the payload naming its district
    through `zone_id`, its placard `code` (again one to sixteen characters and
    unique across all pitches, case-sensitive, refused with
    `ERR_PITCH_CODE_TAKEN` when taken), its `tier`, and its own `noise_cap_db`
    between 55 and 100."

    Design: Corner/entities/corner_pitch_code_uniqueness_enforced
    """
    riverside = create_zone(name="Riverside Plaza", code="RP",
                            weekend_noise_bonus_db=0, evening_penalty_db=0)
    old_town = create_zone(name="Old Town", code="OT", base_noise_cap_db=72,
                           evening_start_minute=1020,
                           quiet_hours_start_minute=1260,
                           quiet_hours_end_minute=480,
                           weekend_noise_bonus_db=0, evening_penalty_db=0,
                           max_concurrent_closures=2)
    create_pitch(riverside["id"], code="RP-01", tier="STANDARD", noise_cap_db=82)

    resp = api.create_pitch(
        create_pitch_payload(old_town["id"], code="RP-01", tier="STANDARD",
                             noise_cap_db=70),
        make_officer_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_CODE_TAKEN)

    _, meta = validate_paginated(api.list_pitches(
        make_officer_headers(), params={"zone_id": old_town["id"]}))
    assert meta["total_count"] == 0
