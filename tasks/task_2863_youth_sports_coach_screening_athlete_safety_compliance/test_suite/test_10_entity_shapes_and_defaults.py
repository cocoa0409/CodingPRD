"""The shape of a freshly created resource: defaults, derived fields and envelopes.

These tests read the resources the platform mints for itself.  A charter, a
registration and an order each carry fields no client supplied — computed
defaults, snapshots of the parent, and the four common properties every row in
the platform has — and each of those values is stated literally by the PRD.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_counters,
    assert_instant_equals,
    assert_money_equals,
    assert_pagination_meta,
    assert_state,
    assert_version_is,
    ids_of,
)
from test_helpers.constants import CLOCK_EPOCH, CLOCK_EPOCH_MS, UNKNOWN_UUID, UNKNOWN_UUID_ALT
from test_helpers.test_users import NGB_ADMIN_HEADERS, make_club_admin_headers

ALPHA_SEEDED = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 250000,
}
ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
BARE_CHARTER = {
    "name": "Default Aquatics",
    "state_code": "OR",
    "roster_size_attested": 2,
}
SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
}


def _epoch(api: ApiClient) -> None:
    """Park the logical clock on the instant the server starts at (PRD 2.5)."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))


def _club(api: ApiClient, payload: Dict[str, Any] = ALPHA_AQUATICS) -> Dict[str, Any]:
    _epoch(api)
    return get_success_data(api.charter_club(payload, NGB_ADMIN_HEADERS), 201)


def _member_payload(
    club_id: str,
    name: str,
    email: str,
    dob: str,
    role_type: str = "VOLUNTEER",
    contact: bool = False,
    codes: Iterable[str] = ("CA",),
) -> Dict[str, Any]:
    return {
        "club_id": club_id,
        "full_name": name,
        "email": email,
        "role_type": role_type,
        "has_minor_athlete_contact": contact,
        "date_of_birth": dob,
        "jurisdiction_codes": list(codes),
    }


def _live_club_version(api: ApiClient, club_id: str) -> int:
    """Read the club so an order can pin the version it actually holds (PRD 2.6)."""
    club = get_success_data(api.get_club(club_id, make_club_admin_headers(club_id)))
    return club["version"]


def test_a_chartered_club_reports_every_computed_default_at_version_one(
    api: ApiClient,
) -> None:
    """The charter response carries the whole derived ledger, not just the input.

    PRD 3.1 says:
    "A freshly chartered club has `escrow_balance_cents` and `total_funded_cents` both equal to the seeded amount, `sanction_status` of `NONE`, and `compliance_posture` of `OPEN`, with `compliance_score` null and all four of its finding and placement counters at zero."

    PRD 4 says:
    "Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation — reads, state transitions, and the operations that modify an existing resource in place — returns HTTP 200 with the affected resource in `data`."

    PRD 2.4 says:
    "`version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, whether the mutation came from a direct client request or from a cascade triggered elsewhere."

    Design: Corner/entities/club_creation_returns_computed_defaults_and_version_one
    """
    _epoch(api)

    response = api.charter_club(ALPHA_SEEDED, NGB_ADMIN_HEADERS)
    club = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", body
    assert str(body["meta"]["api_request_id"]).startswith("req_"), body["meta"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), body["meta"]

    assert is_valid_uuid(club["id"]), club["id"]
    assert club["roster_size_attested"] == 3, club
    assert_money_equals(club, "escrow_balance_cents", 250000)
    assert_money_equals(club, "total_funded_cents", 250000)
    assert_state(club, "sanction_status", "NONE")
    assert_state(club, "compliance_posture", "OPEN")
    assert club["compliance_score"] is None, club["compliance_score"]
    assert_counters(
        club,
        open_finding_count=0,
        critical_open_finding_count=0,
        restricted_member_count=0,
        active_assignment_count=0,
    )
    assert_version_is(club, 1)


def test_reading_a_fresh_member_returns_the_input_and_the_derived_dimensions(
    api: ApiClient,
) -> None:
    """An assistant coach with no athlete contact and one state scores 30 and starts restricted.

    PRD 3.1 says:
    "A newly registered member starts at `screening_status` of `UNSCREENED` on the screening dimension and `membership_status` of `PENDING` on the membership dimension, with `training_status` of `NEVER` and `contact_eligibility` of `RESTRICTED`."
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    "The contact component contributes 25 points when `has_minor_athlete_contact` is true and nothing when it is false."
    "The score selects a screening tier and writes it to `required_tier`: a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`."

    PRD 3.4 says:
    "When the bubble-up fires it sets `membership_status` to `ACTIVE` and stamps `eligible_through` from the audit-snapshot projection."

    Design: Corner/entities/member_retrieval_returns_stored_fields_and_derived_dimensions
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    created = validate_success(
        api.register_member(
            _member_payload(
                club["id"],
                "Ada Pruitt",
                "ada.pruitt@alpha.test",
                "1990-01-15",
                role_type="ASSISTANT_COACH",
            ),
            headers,
        ),
        201,
    )

    member = validate_success(api.get_member(created["id"], headers))

    assert member["full_name"] == "Ada Pruitt", member
    assert member["email"] == "ada.pruitt@alpha.test", member
    assert member["club_id"] == club["id"], member
    assert_state(member, "role_type", "ASSISTANT_COACH")
    assert_counters(member, risk_points=30)
    assert_state(member, "required_tier", "TIER_1")
    assert_state(member, "screening_status", "UNSCREENED")
    assert_state(member, "membership_status", "PENDING")
    assert_state(member, "training_status", "NEVER")
    assert_state(member, "contact_eligibility", "RESTRICTED")
    assert member["eligible_through"] is None, member["eligible_through"]
    assert_version_is(member, 1)


def test_the_club_member_listing_pages_by_two_and_defaults_to_a_limit_of_ten(
    api: ApiClient,
) -> None:
    """Three members, a window of two, and then a call that names no window at all.

    PRD 2.3 says:
    "`limit` defaults to 10, must be at least 1, and must not exceed 100."
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true exactly when rows remain beyond the current window."
    "Unless a specific list endpoint states otherwise, results are ordered by `created_at` ascending."

    Design: Corner/entities/club_member_listing_paginates_with_total_count_and_has_more
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    first = get_success_data(
        api.register_member(
            _member_payload(club["id"], "Page One", "page.one@alpha.test", "1990-02-01"),
            headers,
        ),
        201,
    )
    second = get_success_data(
        api.register_member(
            _member_payload(club["id"], "Page Two", "page.two@alpha.test", "1990-03-01"),
            headers,
        ),
        201,
    )
    third = get_success_data(
        api.register_member(
            _member_payload(
                club["id"], "Page Three", "page.three@alpha.test", "1990-04-01"
            ),
            headers,
        ),
        201,
    )

    page_one_response = api.list_club_members(club["id"], headers, limit=2, offset=0)
    page_one, meta_one = validate_paginated(page_one_response)
    assert page_one_response.json()["response_type"] == "array", page_one_response.json()
    assert_pagination_meta(meta_one, total=3, limit=2, offset=0)
    assert meta_one["has_more"] is True, meta_one
    assert len(page_one) == 2, ids_of(page_one)

    page_two, meta_two = validate_paginated(
        api.list_club_members(club["id"], headers, limit=2, offset=2)
    )
    assert_pagination_meta(meta_two, total=3, limit=2, offset=2)
    assert meta_two["has_more"] is False, meta_two
    assert len(page_two) == 1, ids_of(page_two)

    paged_ids = ids_of(page_one) + ids_of(page_two)
    assert len(set(paged_ids)) == 3, paged_ids
    assert set(paged_ids) == {first["id"], second["id"], third["id"]}, paged_ids

    unwindowed, meta_default = validate_paginated(api.list_club_members(club["id"], headers))
    assert_pagination_meta(meta_default, total=3, limit=10, offset=0)
    assert meta_default["has_more"] is False, meta_default
    assert len(unwindowed) == 3, ids_of(unwindowed)


def test_reading_an_unknown_member_uuid_is_a_not_found(api: ApiClient) -> None:
    """A well-formed UUID that names no row is a 404, never an empty success.

    PRD 2.8 says:
    "Every path-templated resource id resolves to an existing row, validated left to right, so an outer segment's 404 is reported before an inner one's — `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_SCREENING_ORDER_NOT_FOUND`, `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`, `ERR_COACH_ASSIGNMENT_NOT_FOUND`, `ERR_INVESTIGATING_BODY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_INTERIM_MEASURE_NOT_FOUND`, `ERR_CLUB_AUDIT_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, or `ERR_ROOM_STAY_NOT_FOUND` as appropriate."

    PRD 2.2 says:
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/unknown_member_uuid_read_is_not_found
    """
    _club(api)

    error = validate_error(
        api.get_member(UNKNOWN_UUID, NGB_ADMIN_HEADERS),
        ApiErrorId.MEMBER_NOT_FOUND.value,
        404,
    )

    assert isinstance(error["message"], str) and error["message"].strip(), error


def test_registering_a_member_without_a_role_type_is_rejected_and_writes_nothing(
    api: ApiClient,
) -> None:
    """role_type is an input with no default, so its absence is a shape failure.

    PRD 3.1 says:
    "The registration payload names the chartering `club_id`, the individual's `full_name` (1 to 120 characters), an `email` that must contain an at-sign and must be unique across the entire governing body when compared case-insensitively, the `role_type` held at the club — one of `HEAD_COACH`, `ASSISTANT_COACH`, `OFFICIAL`, `CHAPERONE`, or `VOLUNTEER` — the boolean `has_minor_athlete_contact` declaring whether the role involves direct contact with minor athletes, a `date_of_birth` as an ISO 8601 calendar date in year-month-day form (registrants are adults, and the date of birth is what later lets the lodging policy classify an occupant as an adult member), and `jurisdiction_codes`, a list of 1 to 6 two-uppercase-letter state codes, free of duplicates, that the background screen must cover."

    PRD 2.8 says:
    "The request body conforms to the endpoint's input schema: required fields present, JSON types correct, enum values members of their declared set, string lengths within bounds, `limit` between 1 and 100, `offset` at least 0, `season_end` strictly after `season_start`, `check_out` strictly after `check_in`, `audit_period_end` strictly after `audit_period_start`, `effective_to` at or after `effective_from`, `jurisdiction_codes` non-empty and free of duplicates, and a room stay's `member_id` and `minor_athlete_age` pairing consistent with its `occupant_kind` — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/member_creation_without_role_type_is_rejected
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    payload = _member_payload(
        club["id"], "No Role", "no.role@alpha.test", "1990-05-01"
    )
    payload.pop("role_type")

    validate_error(
        api.register_member(payload, headers), ApiErrorId.VALIDATION.value, 422
    )

    _rows, meta = validate_paginated(api.list_club_members(club["id"], headers))
    assert meta["total_count"] == 0, meta


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(
    api: ApiClient,
) -> None:
    """A bare charter, a bare course and a bare order each pick up their default.

    PRD 3.1 says:
    "`minor_athlete_program` declares whether the organization runs programs serving minor athletes; it defaults to true, and when it is true the electronic-communication policy and the travel-and-lodging policy are enforced against that club's activity."
    "Optionally the charter may seed the club's screening escrow with `initial_escrow_cents`; when omitted the seed is zero."
    "Adding money to the escrow is the only action in the platform that raises `total_funded_cents`, a lifetime total that never decreases: a caller supplies `amount_cents`, a positive whole number of cents, and both `escrow_balance_cents` and `total_funded_cents` rise by that amount while the club's `version` advances by one."

    PRD 3.4 says:
    "A course carries a `code` that is its natural key — 3 to 20 characters of uppercase letters, digits, and hyphens, globally unique, with a collision refused as `ERR_DUPLICATE_COURSE_CODE` — a human-readable `title`, a `validity_days` figure between 1 and 3,650 stating how long a completion of that course stays current, a `delivery_mode` of either `ONLINE` or `IN_PERSON`, a `required_for_tiers` list naming which screening tiers must hold this course before athlete contact (a non-empty duplicate-free subset of `TIER_1`, `TIER_2`, and `TIER_3`), and a `pass_score` between 0 and 100 that defaults to 80."

    PRD 3.2 says:
    "The request body is deliberately small: an optional `expedited` flag defaulting to false, and the mandatory `expected_club_version` described in §2.6."
    "Step seven, only when `expedited` is true, takes 35 percent **of that post-discount net subtotal**, rounds half up to a whole cent, and records it as `expedite_cents`; when `expedited` is false, `expedite_cents` is zero."
    "Step one takes the tier base fee: 2,500 cents for `TIER_1`, 4,800 cents for `TIER_2`, and 9,200 cents for `TIER_3`."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    _epoch(api)

    club = validate_success(api.charter_club(BARE_CHARTER, NGB_ADMIN_HEADERS), 201)
    assert club["minor_athlete_program"] is True, club
    assert_money_equals(club, "escrow_balance_cents", 0)
    assert_money_equals(club, "total_funded_cents", 0)

    headers = make_club_admin_headers(club["id"])
    funded = validate_success(
        api.fund_escrow(club["id"], {"amount_cents": 500000}, headers)
    )
    assert_money_equals(funded, "escrow_balance_cents", 500000)
    assert_money_equals(funded, "total_funded_cents", 500000)
    assert_version_is(funded, 2)

    course = validate_success(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    assert course["pass_score"] == 80, course

    member = validate_success(
        api.register_member(
            _member_payload(
                club["id"],
                "Deft Owens",
                "deft.owens@default.test",
                "1992-06-01",
                codes=("OR",),
            ),
            headers,
        ),
        201,
    )
    assert_state(member, "required_tier", "TIER_1")

    order = validate_success(
        api.order_screening(
            member["id"],
            {"expected_club_version": _live_club_version(api, club["id"])},
            headers,
        ),
        201,
    )
    assert order["expedited"] is False, order
    assert_money_equals(order, "expedite_cents", 0)
    assert_money_equals(order, "gross_subtotal_cents", 2500)
    assert_money_equals(order, "discount_cents", 0)
    assert_money_equals(order, "charged_cents", 2500)

    after = validate_success(api.get_club(club["id"], headers))
    assert_money_equals(after, "escrow_balance_cents", 497500)
    assert_money_equals(after, "total_funded_cents", 500000)


def test_the_order_snapshots_the_members_tier_and_jurisdiction_count(
    api: ApiClient,
) -> None:
    """A chaperone with athlete contact across two states is priced from the member row.

    PRD 3.1 says:
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    "The contact component contributes 25 points when `has_minor_athlete_contact` is true and nothing when it is false."
    "The jurisdiction component contributes 5 points for each jurisdiction beyond the first — that is, five points multiplied by the number of entries in `jurisdiction_codes` less one, never taken below zero — and is capped at 15 points, so a screen covering four or more states contributes the same 15 as one covering six."

    PRD 3.2 says:
    "`tier` is a snapshot of the member's `required_tier` at order time, and `jurisdiction_count` is a snapshot of how many entries the member's `jurisdiction_codes` held at order time."
    "Step two computes the multi-jurisdiction surcharge as 1,100 cents for each jurisdiction beyond the first — that is, 1,100 multiplied by the order's `jurisdiction_count` less one, never taken below zero."
    "Step four selects the volume-discount rate **from that pre-discount gross subtotal**: 10 percent when the gross subtotal reaches or exceeds 12,000 cents, otherwise 5 percent when it reaches or exceeds 8,000 cents, otherwise no discount at all."
    "A successful order is written in status `ORDERED` with all four money fields stamped, the club's `escrow_balance_cents` is debited by `charged_cents`, the club's `version` advances by one, and the member's screening dimension moves `UNSCREENED → SCREENING_ORDERED` (or `CLEARED → SCREENING_ORDERED`, or `EXPIRED → SCREENING_ORDERED`, all three governed by the identical preconditions and side effects)."

    Design: Corner/entities/screening_order_computed_fields_snapshot_member_state_at_order_time
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    member = validate_success(
        api.register_member(
            _member_payload(
                club["id"],
                "Cara Fenn",
                "cara.fenn@alpha.test",
                "1985-07-02",
                role_type="CHAPERONE",
                contact=True,
                codes=("CA", "NV"),
            ),
            headers,
        ),
        201,
    )
    assert_counters(member, risk_points=55)
    assert_state(member, "required_tier", "TIER_2")

    order = validate_success(
        api.order_screening(
            member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )

    assert order["member_id"] == member["id"], order
    assert_state(order, "tier", "TIER_2")
    assert_counters(order, jurisdiction_count=2)
    assert_money_equals(order, "gross_subtotal_cents", 5900)
    assert_money_equals(order, "discount_cents", 0)
    assert_money_equals(order, "charged_cents", 5900)
    assert_state(order, "status", "ORDERED")

    after = validate_success(api.get_club(club["id"], headers))
    assert_money_equals(after, "escrow_balance_cents", 494100)


def test_system_fields_are_server_minted_and_the_version_advances_on_every_write(
    api: ApiClient,
) -> None:
    """A funding that changes nothing but the balance still advances the club's version.

    PRD 2.4 says:
    "`id` is a server-minted UUID with no type prefix and is never accepted from a client."
    "`created_at` is the ISO 8601 UTC instant of creation with three fractional digits."
    "`updated_at` is the ISO 8601 UTC instant of the most recent mutation of that row, likewise with three fractional digits, and equals `created_at` on a freshly created row."
    "`version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, whether the mutation came from a direct client request or from a cascade triggered elsewhere."

    PRD 2.5 says:
    "On server start the clock stands at exactly `2026-08-01T00:00:00Z`, and until it is repositioned every rule that consults the clock sees that instant."

    Design: Corner/entities/system_fields_are_server_minted_and_version_increments_per_write
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    assert is_valid_uuid(club["id"]), club["id"]
    assert len(club["id"]) == 36, club["id"]
    assert_instant_equals(club["created_at"], CLOCK_EPOCH_MS)
    assert_instant_equals(club["updated_at"], CLOCK_EPOCH_MS)
    assert_version_is(club, 1)

    funded = validate_success(api.fund_escrow(club["id"], {"amount_cents": 1000}, headers))
    assert_version_is(funded, 2)
    assert_instant_equals(funded["updated_at"], CLOCK_EPOCH_MS)
    assert_money_equals(funded, "escrow_balance_cents", 501000)

    member = get_success_data(
        api.register_member(
            _member_payload(club["id"], "Sam Frei", "sam.frei@alpha.test", "1994-08-03"),
            headers,
        ),
        201,
    )

    order = validate_success(
        api.order_screening(
            member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )

    assert order["member_id"] == member["id"], order
    assert_version_is(order, 1)
    assert_instant_equals(order["created_at"], CLOCK_EPOCH_MS)
    assert_instant_equals(order["updated_at"], order["created_at"])


def test_a_bad_enum_an_oversized_limit_and_a_backwards_season_are_all_shape_failures(
    api: ApiClient,
) -> None:
    """Three unrelated malformed requests all land on the same request-shape refusal.

    PRD 2.8 says:
    "The request body conforms to the endpoint's input schema: required fields present, JSON types correct, enum values members of their declared set, string lengths within bounds, `limit` between 1 and 100, `offset` at least 0, `season_end` strictly after `season_start`, `check_out` strictly after `check_in`, `audit_period_end` strictly after `audit_period_start`, `effective_to` at or after `effective_from`, `jurisdiction_codes` non-empty and free of duplicates, and a room stay's `member_id` and `minor_athlete_age` pairing consistent with its `occupant_kind` — otherwise `ERR_VALIDATION`."

    PRD 2.3 says:
    "A `limit` outside 1 through 100, or a negative `offset`, is a request-shape failure and is refused with `ERR_VALIDATION` (HTTP 422)."

    PRD 3.6 says:
    "The club administrator creating the placement supplies the `member_id`, the `club_id`, the `team_name`, and the season interval as `season_start` and `season_end`, where `season_end` must be strictly after `season_start`."

    Design: Corner/entities/invalid_enum_and_out_of_range_inputs_are_rejected
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    member = get_success_data(
        api.register_member(
            _member_payload(club["id"], "Tyra Cobb", "tyra.cobb@alpha.test", "1993-09-04"),
            headers,
        ),
        201,
    )

    bad_enum = api.register_member(
        _member_payload(
            club["id"],
            "Bad Enum",
            "bad.enum@alpha.test",
            "1993-10-05",
            role_type="SUPER_COACH",
        ),
        headers,
    )
    validate_error(bad_enum, ApiErrorId.VALIDATION.value, 422)
    assert bad_enum.json()["response_type"] == "error", bad_enum.json()

    oversized = api.list_club_members(club["id"], headers, limit=101, offset=0)
    validate_error(oversized, ApiErrorId.VALIDATION.value, 422)
    assert oversized.json()["response_type"] == "error", oversized.json()

    backwards = api.create_coach_assignment(
        {
            "member_id": member["id"],
            "club_id": club["id"],
            "team_name": "Backwards Season",
            "season_start": "2027-05-31T00:00:00Z",
            "season_end": "2026-09-01T00:00:00Z",
        },
        headers,
    )
    validate_error(backwards, ApiErrorId.VALIDATION.value, 422)
    assert backwards.json()["response_type"] == "error", backwards.json()

    _rows, meta = validate_paginated(api.list_club_members(club["id"], headers))
    assert meta["total_count"] == 1, meta


def test_ordering_a_screen_under_an_unknown_member_is_a_not_found(
    api: ApiClient,
) -> None:
    """The path parent is resolved before the order is ever priced or paid for.

    PRD 2.8 says:
    "Every path-templated resource id resolves to an existing row, validated left to right, so an outer segment's 404 is reported before an inner one's — `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_SCREENING_ORDER_NOT_FOUND`, `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`, `ERR_COACH_ASSIGNMENT_NOT_FOUND`, `ERR_INVESTIGATING_BODY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_INTERIM_MEASURE_NOT_FOUND`, `ERR_CLUB_AUDIT_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, or `ERR_ROOM_STAY_NOT_FOUND` as appropriate."

    PRD 3.2 says:
    "The escrow check is the very last gate in the entire order of refusal, so a request that is both unfunded and unsafe always reports the safety problem."

    Design: Corner/entities/screening_order_under_unknown_member_is_not_found
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    validate_error(
        api.order_screening(
            UNKNOWN_UUID_ALT,
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        ApiErrorId.MEMBER_NOT_FOUND.value,
        404,
    )

    after = validate_success(api.get_club(club["id"], headers))
    assert_money_equals(after, "escrow_balance_cents", 500000)
    assert_money_equals(after, "total_funded_cents", 500000)
