"""
Row shapes, declared defaults and registry reads of the licensing contract.

This file pins what a freshly written row looks like on the wire: the venue
survey a `LicensingAdmin` registers and reads back unchanged, the rate schedule
whose four pricing levers fall to their published defaults, the resting values
of every derived field a venue carries before it is ever licensed, the
server-minted identity triplet, the thin immutable shape of a setlist entry, the
pagination envelope of the society registry, and the four rejections that guard
the registry: an unknown row id, a missing required survey field, an undeclared
enum value and a body foreign key that names nothing at all.
"""

from typing import Any, Dict

from test_helpers import (
    DEFAULT_ADJUSTMENT_BP,
    DEFAULT_LIMIT,
    DEFAULT_MAX_ANNUAL_FEE_CENTS,
    DEFAULT_MIN_ANNUAL_FEE_CENTS,
    ERR_AUDIT_CASE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LICENSE_NOT_FOUND,
    ERR_SOCIETY_NOT_FOUND,
    ERR_VENUE_NOT_FOUND,
    EXEMPTION_NOT_ANALYZED,
    POSTURE_UNCOVERED,
    REPORT_STATUS_DRAFT,
    SCHEDULE_STATUS_DRAFT,
    UNUSED_UUID,
    UNUSED_UUID_ALT,
    UNUSED_UUID_THIRD,
    USE_TYPE_LIVE,
    VENUE_STATUS_OPERATING,
    admin_headers,
    ascap_payload,
    assert_bp,
    assert_count,
    assert_coverage,
    assert_empty_list,
    assert_immutable_row,
    assert_instant_equals,
    assert_money,
    assert_pct,
    assert_venue_ledger,
    assert_version,
    bar_grill_venue_payload,
    bmi_payload,
    concert_hall_venue_payload,
    given_draft_report,
    given_licensed_venue,
    given_society,
    given_venue,
    is_valid_uuid,
    performance_report_payload,
    rate_schedule_payload,
    read_page,
    repertoire_work_payload,
    sesac_payload,
    setlist_entry_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_payload,
)

Row = Dict[str, Any]

# The survey the licensing administrator files for the Blue Note Grill, spelled
# out field by field so a test can drop or corrupt exactly one entry of it.
_BLUE_NOTE_SURVEY: Row = venue_payload(
    "Blue Note Grill",
    "BAR_GRILL",
    120,
    180,
    200,
    "MIXED",
    4,
    4200000,
)


def _without(payload: Row, *fields: str) -> Row:
    """A copy of a request body with the named fields removed entirely."""
    body = dict(payload)
    for field in fields:
        body.pop(field, None)
    return body


def _replacing(payload: Row, **changes: Any) -> Row:
    """A copy of a request body with the named fields overwritten."""
    body = dict(payload)
    body.update(changes)
    return body


def _envelope(response) -> Row:
    """The whole response envelope, for the two `meta` fields §2.2 requires."""
    return response.json()


def test_row_venue_create_returns_the_whole_survey_row(api):
    """Registering a venue answers 201 with every surveyed input echoed back,
    and a later read of the same venue returns the identical figures.

    PRD §4: "Endpoints that bring a brand-new row into existence — a society, a
    rate schedule, a venue, an application, a successor licence, a coverage
    window, a registered work, a performance report, a setlist entry or an audit
    case — answer with HTTP 201 and the created row in `data`."

    PRD §3.3: "Registering a venue requires a `legal_name` of 1 to 160
    characters, the licensing `venue_category`, a `seating_capacity` of at least
    0 fixed seats in the music room, a `standing_capacity` of at least 0, an
    `occupancy_limit` of at least 1 recording the fire-code occupancy of the
    music room, a `music_use_profile` that is one of `LIVE_ONLY`,
    `RECORDED_ONLY`, `MIXED` or `BACKGROUND_ONLY`, a
    `weekly_live_performance_nights` count between 0 and 7 inclusive, and an
    `annual_cover_revenue_cents` figure of at least 0 covering verified annual
    cover-charge and admission revenue."

    Design: Corner/entities/corner_venue_create_returns_full_row
    """
    response = api.create_venue(bar_grill_venue_payload(), admin_headers())
    created = validate_success(response, 201)

    body = _envelope(response)
    assert body["response_type"] == "object", (
        f"a single-resource create must declare response_type 'object', "
        f"got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', "
        f"got {body['meta']['api_request_id']!r}"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str) and body["meta"][
        "api_request_timestamp"
    ], "meta.api_request_timestamp must be a non-empty server-generated string"

    assert created["legal_name"] == "Blue Note Grill"
    assert created["venue_category"] == "BAR_GRILL"
    assert_count(created["seating_capacity"], 120, "seating_capacity")
    assert_count(created["standing_capacity"], 180, "standing_capacity")
    assert_count(created["occupancy_limit"], 200, "occupancy_limit")
    assert created["music_use_profile"] == "MIXED"
    assert_count(
        created["weekly_live_performance_nights"], 4, "weekly_live_performance_nights"
    )
    assert_money(
        created["annual_cover_revenue_cents"], 4200000, "annual_cover_revenue_cents"
    )

    reread = validate_success(api.get_venue(created["id"], admin_headers()))
    for field in (
        "legal_name",
        "venue_category",
        "seating_capacity",
        "standing_capacity",
        "occupancy_limit",
        "music_use_profile",
        "weekly_live_performance_nights",
        "annual_cover_revenue_cents",
    ):
        assert reread[field] == created[field], (
            f"reading the venue back changed {field}: "
            f"{created[field]!r} became {reread[field]!r}"
        )


def test_row_rate_schedule_defaults_applied_on_create(api):
    """A rate schedule filed without pricing levers takes the four published
    defaults and opens in DRAFT as version 1 with nothing pinned to it yet.

    PRD §3.2: "`adjustment_bp` is a basis-point multiplier that must lie between
    5000 and 20000 inclusive and defaults to 10000, meaning unadjusted; §3.5
    explains precisely which two components of the fee it scales and which one
    it deliberately leaves alone."

    PRD §3.2: "`min_annual_fee_cents` is a floor of at least 0 cents applied
    before the society's share is taken and defaults to 30000."

    PRD §3.2: "A new schedule is born in `DRAFT` `status` and carries
    `pinned_license_count` at 0."

    Design: Corner/entities/corner_rate_schedule_defaults_applied_on_create
    """
    society = given_society(api, bmi_payload())

    schedule = validate_success(
        api.create_rate_schedule(
            rate_schedule_payload(society["id"], "BAR_GRILL", "2026-01-01T00:00:00Z"),
            admin_headers(),
        ),
        201,
    )

    assert_bp(schedule["adjustment_bp"], DEFAULT_ADJUSTMENT_BP, "adjustment_bp")
    assert_money(
        schedule["min_annual_fee_cents"],
        DEFAULT_MIN_ANNUAL_FEE_CENTS,
        "min_annual_fee_cents",
    )
    assert_money(
        schedule["max_annual_fee_cents"],
        DEFAULT_MAX_ANNUAL_FEE_CENTS,
        "max_annual_fee_cents",
    )
    assert schedule["status"] == SCHEDULE_STATUS_DRAFT, (
        f"a new schedule must open in DRAFT, got {schedule['status']!r}"
    )
    assert_count(schedule["schedule_version"], 1, "schedule_version")
    assert_count(schedule["pinned_license_count"], 0, "pinned_license_count")
    assert schedule["rate_court_order_ref"] is None, (
        "a voluntary filing carries no rate-court docket reference, got "
        f"{schedule['rate_court_order_ref']!r}"
    )


def test_row_societies_list_pagination_envelope(api):
    """The society registry pages: two of three rows with more beyond, then the
    last row with nothing beyond, then the whole registry on the default page.

    PRD §2.3: "`limit` caps the number of rows returned; when it is omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100."

    PRD §2.3: "`total_count` is the number of rows matching the request's
    filters before `limit` and `offset` are applied, and `has_more` is true
    exactly when rows matching the filters remain beyond the returned page."

    Design: Corner/entities/corner_societies_list_pagination_envelope
    """
    given_society(api, bmi_payload())
    given_society(api, ascap_payload())
    given_society(api, sesac_payload())

    first_rows, first_meta = read_page(
        api.list_societies(admin_headers(), {"limit": 2, "offset": 0}),
        expected_total=3,
    )
    assert len(first_rows) == 2, f"expected 2 rows on the first page, got {len(first_rows)}"
    assert_count(first_meta["limit"], 2, "meta.limit")
    assert_count(first_meta["offset"], 0, "meta.offset")
    assert first_meta["has_more"] is True, (
        "a third society remains beyond a two-row page, so has_more must be true"
    )

    last_rows, last_meta = read_page(
        api.list_societies(admin_headers(), {"limit": 2, "offset": 2}),
        expected_total=3,
    )
    assert len(last_rows) == 1, f"expected 1 row on the last page, got {len(last_rows)}"
    assert_count(last_meta["offset"], 2, "meta.offset")
    assert last_meta["has_more"] is False, (
        "nothing remains beyond the third society, so has_more must be false"
    )

    default_rows, default_meta = read_page(
        api.list_societies(admin_headers()), expected_total=3
    )
    assert len(default_rows) == 3, (
        f"the default page must carry all three societies, got {len(default_rows)}"
    )
    assert_count(default_meta["limit"], DEFAULT_LIMIT, "default meta.limit")
    assert_count(default_meta["offset"], 0, "default meta.offset")
    assert default_meta["has_more"] is False, (
        "three rows fit inside the default page, so has_more must be false"
    )


def test_row_unknown_row_id_reads_back_as_a_typed_not_found(api):
    """Reading a well-formed but unused id is a typed 404 naming the addressed
    resource, never an empty success.

    PRD §2.8: "The request fails on the *first* identifier in the path that
    matches no row, with the 404 error naming that identifier's resource type:
    `ERR_SOCIETY_NOT_FOUND` for `society_id`, `ERR_RATE_SCHEDULE_NOT_FOUND` for
    `rate_schedule_id`, `ERR_VENUE_NOT_FOUND` for `venue_id`,
    `ERR_APPLICATION_NOT_FOUND` for `application_id`, `ERR_LICENSE_NOT_FOUND`
    for `license_id`, `ERR_COVERAGE_WINDOW_NOT_FOUND` for `coverage_window_id`,
    `ERR_WORK_NOT_FOUND` for `repertoire_work_id`, `ERR_REPORT_NOT_FOUND` for
    `report_id`, `ERR_SETLIST_ENTRY_NOT_FOUND` for `setlist_entry_id`,
    `ERR_AUDIT_CASE_NOT_FOUND` for `audit_case_id`, and
    `ERR_ASSESSMENT_NOT_FOUND` for `assessment_id`."

    Design: Corner/entities/corner_venue_get_unknown_id_not_found
    """
    venue_read = api.get_venue(UNUSED_UUID, admin_headers())
    validate_error(venue_read, ERR_VENUE_NOT_FOUND)
    assert _envelope(venue_read)["response_type"] == "error", (
        "a rejection must declare response_type 'error'"
    )

    validate_error(
        api.get_license(UNUSED_UUID, admin_headers()), ERR_LICENSE_NOT_FOUND
    )
    validate_error(
        api.get_audit_case(UNUSED_UUID, admin_headers()), ERR_AUDIT_CASE_NOT_FOUND
    )


def test_row_venue_create_missing_required_field_rejected(api):
    """A survey filed without a required field is refused on shape alone and
    leaves the venue registry empty.

    PRD §2.12: "The body parses; every required field is present and non-null;
    every enum-typed field carries a declared value; every field whose name ends
    in `_cents` or `_bp` and every count field is a JSON integer of at least 0;
    every instant-valued field is an RFC 3339 UTC instant ending in `Z`; a
    disposition arrives with its mandatory companion reason; and a supplied
    `limit` lies within 1 to 100 — otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/corner_venue_create_missing_required_field_rejected
    """
    validate_error(
        api.create_venue(
            _without(_BLUE_NOTE_SURVEY, "music_use_profile"), admin_headers()
        ),
        ERR_INVALID_REQUEST,
    )
    assert_empty_list(api.list_venues(admin_headers()))

    for omitted in ("occupancy_limit", "seating_capacity", "legal_name"):
        validate_error(
            api.create_venue(_without(_BLUE_NOTE_SURVEY, omitted), admin_headers()),
            ERR_INVALID_REQUEST,
        )

    assert_empty_list(api.list_venues(admin_headers()))


def test_row_venue_computed_fields_start_at_their_declared_defaults(api):
    """Every field the licensing system derives for itself reads back at its
    resting value on a venue that has just been surveyed.

    PRD §3.3: "Every derived field on a fresh venue starts at its resting value:
    `bgm_exemption_status` at `NOT_ANALYZED` with `bgm_exemption_reason` at null,
    `covered_share_bp` at 0 with `coverage_posture` at `UNCOVERED`,
    `gap_risk_score` at 0, `audit_hold` at false, and all four ledger totals —
    `lifetime_assessed_cents`, `outstanding_balance_cents`,
    `settled_amount_cents` and `voided_amount_cents` — at 0."

    PRD §3.3: "Finally, `status` records whether the establishment is
    `OPERATING` or `CLOSED`, defaulting to `OPERATING`."

    Design: Corner/entities/corner_venue_computed_fields_start_at_their_declared_defaults
    """
    venue = validate_success(
        api.create_venue(bar_grill_venue_payload(), admin_headers()), 201
    )

    assert_coverage(venue, 0, POSTURE_UNCOVERED)
    assert_pct(venue["gap_risk_score"], 0.00, "gap_risk_score")
    assert venue["audit_hold"] is False, (
        "a venue with no audit case cannot be on hold, got "
        f"{venue['audit_hold']!r}"
    )
    assert venue["bgm_exemption_status"] == EXEMPTION_NOT_ANALYZED, (
        f"a fresh survey is unanalysed, got {venue['bgm_exemption_status']!r}"
    )
    assert venue["bgm_exemption_reason"] is None, (
        f"an unanalysed venue carries no reason, got {venue['bgm_exemption_reason']!r}"
    )
    assert_venue_ledger(venue, outstanding=0, settled=0, voided=0, lifetime=0)

    assert venue["status"] == VENUE_STATUS_OPERATING, (
        f"a venue defaults to OPERATING, got {venue['status']!r}"
    )
    assert venue["has_cover_charge"] is False, "has_cover_charge defaults to false"
    assert venue["retransmission_only"] is False, "retransmission_only defaults to false"
    assert venue["uses_licensed_bgm_service"] is False, (
        "uses_licensed_bgm_service defaults to false"
    )


def test_row_venue_system_fields_generated_by_server(api, clock_start):
    """Identity, both timestamps and the revision counter are minted by the
    server: the created row opens at version 1 stamped with the logical clock,
    and a survey revision moves the counter to 2.

    PRD §2.5: "Every resource in the system is addressed by an `id`, a
    server-minted UUID carrying no type prefix and no embedded meaning."

    PRD §2.5: "`version` is an integer that starts at 1 on creation and increases
    by exactly 1 on every mutation of that row — including mutations the row's
    owner never requested, such as a recomputed derived field written by a
    cascade."

    PRD §2.4: "At server start-up the logical clock reads exactly
    `2026-08-01T00:00:00Z`; until it is explicitly moved it stays at that value
    and never falls back to wall-clock time."

    Design: Corner/entities/corner_venue_system_fields_generated_by_server
    """
    venue = validate_success(
        api.create_venue(concert_hall_venue_payload(), admin_headers()), 201
    )

    assert is_valid_uuid(venue["id"]), (
        f"id must be a server-minted UUID with no type prefix, got {venue['id']!r}"
    )
    assert_version(venue, 1, "venue")
    assert_instant_equals(venue["created_at"], clock_start, "venue.created_at")
    assert_instant_equals(venue["updated_at"], clock_start, "venue.updated_at")

    revised = validate_success(
        api.update_venue(venue["id"], {"seating_capacity": 1100}, admin_headers())
    )
    assert_version(revised, 2, "revised venue")
    assert_count(revised["seating_capacity"], 1100, "seating_capacity")


def test_row_venue_create_invalid_enum_rejected(api):
    """An undeclared enum value and a negative money figure are both refused as
    request-shape failures.

    PRD §3.3: "Registering a venue requires a `legal_name` of 1 to 160
    characters, the licensing `venue_category`, a `seating_capacity` of at least
    0 fixed seats in the music room, a `standing_capacity` of at least 0, an
    `occupancy_limit` of at least 1 recording the fire-code occupancy of the
    music room, a `music_use_profile` that is one of `LIVE_ONLY`,
    `RECORDED_ONLY`, `MIXED` or `BACKGROUND_ONLY`, a
    `weekly_live_performance_nights` count between 0 and 7 inclusive, and an
    `annual_cover_revenue_cents` figure of at least 0 covering verified annual
    cover-charge and admission revenue."

    PRD §3.2: "A `LicensingAdmin` creates one by naming the owning `society_id`
    and the `venue_category` it prices — one of `CONCERT_HALL`, `BAR_GRILL`,
    `NIGHTCLUB`, `RESTAURANT`, `HOTEL` or `FITNESS_STUDIO` — together with
    `effective_from`, the instant from which the schedule may begin to be
    selected for fee calculation."

    PRD §2.12: "The body parses; every required field is present and non-null;
    every enum-typed field carries a declared value; every field whose name ends
    in `_cents` or `_bp` and every count field is a JSON integer of at least 0;
    every instant-valued field is an RFC 3339 UTC instant ending in `Z`; a
    disposition arrives with its mandatory companion reason; and a supplied
    `limit` lies within 1 to 100 — otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/corner_venue_create_invalid_enum_rejected
    """
    validate_error(
        api.create_venue(
            _replacing(
                _BLUE_NOTE_SURVEY,
                legal_name="Odd Venue",
                venue_category="AMPHITHEATRE",
            ),
            admin_headers(),
        ),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_venue(
            _replacing(_BLUE_NOTE_SURVEY, annual_cover_revenue_cents=-1),
            admin_headers(),
        ),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_venue(
            _replacing(_BLUE_NOTE_SURVEY, music_use_profile="AMBIENT"),
            admin_headers(),
        ),
        ERR_INVALID_REQUEST,
    )

    assert_empty_list(api.list_venues(admin_headers()))


def test_row_setlist_entry_is_immutable_and_has_no_version(api):
    """A performance appended to a draft report is a thin registry row: id and
    creation stamp only, with all three verdict flags still at their defaults,
    and it reads back unchanged.

    PRD §2.5: "Two resources are immutable registry rows and are deliberately
    thinner: a `RepertoireWork` and a `SetlistEntry` each carry only `id` and
    `created_at`."

    PRD §3.8: "The three derived flags on the entry — `is_matched` at false,
    `matched_work_id` at null and `is_covered` at false — stay at their defaults
    until submission recomputes them."

    Design: Corner/entities/corner_setlist_entry_is_immutable_and_has_no_version
    """
    world = given_licensed_venue(api)
    venue_id = world["venue"]["id"]
    report = given_draft_report(api, world["license"]["id"], venue_id)
    assert report["status"] == REPORT_STATUS_DRAFT, (
        f"a new report opens in DRAFT, got {report['status']!r}"
    )

    entry = validate_success(
        api.create_setlist_entry(
            report["id"],
            setlist_entry_payload(
                "Blue Horizon",
                "A. Reed",
                "BMI",
                "2026-09-05T20:00:00Z",
                300,
                USE_TYPE_LIVE,
            ),
            venue_operator_headers(venue_id),
        ),
        201,
    )

    assert_immutable_row(entry, "setlist entry")
    assert entry["is_matched"] is False, (
        f"a freshly appended performance is unmatched, got {entry['is_matched']!r}"
    )
    assert entry["matched_work_id"] is None, (
        f"no work is bound before submission, got {entry['matched_work_id']!r}"
    )
    assert entry["is_covered"] is False, (
        f"coverage is only tested at submission, got {entry['is_covered']!r}"
    )

    reread = validate_success(api.get_setlist_entry(entry["id"], admin_headers()))
    assert_immutable_row(reread, "re-read setlist entry")
    assert reread["id"] == entry["id"]
    assert_instant_equals(
        reread["created_at"], entry["created_at"], "setlist entry.created_at"
    )
    assert reread["work_title"] == "Blue Horizon"
    assert reread["writer_name"] == "A. Reed"
    assert reread["society_affiliation"] == "BMI"
    assert reread["use_type"] == USE_TYPE_LIVE
    assert_count(reread["duration_seconds"], 300, "duration_seconds")
    assert reread["is_matched"] is False
    assert reread["matched_work_id"] is None
    assert reread["is_covered"] is False


def test_row_repertoire_work_unknown_society_not_found(api):
    """Registering a work against a society that does not exist is a typed 404
    and stores nothing in the repertoire.

    PRD §2.8: "The same existence discipline extends to foreign keys supplied in
    a request **body**, which are checked before any business rule that would
    consult the referenced row: `venue_id`, `society_id`, `license_id`,
    `audit_case_id`, and every element of the `society_ids` array."

    Design: Corner/entities/corner_repertoire_work_unknown_society_not_found
    """
    validate_error(
        api.create_repertoire_work(
            repertoire_work_payload(UNUSED_UUID_ALT, "Ghost Registration", "Nobody"),
            admin_headers(),
        ),
        ERR_SOCIETY_NOT_FOUND,
    )

    assert_empty_list(api.list_repertoire_works(admin_headers()))


def test_row_report_create_unknown_license_not_found(api):
    """A performance report names its licence by foreign key rather than by URL
    nesting, so an unknown licence is a typed 404 and opens no report.

    PRD §2.12: "Every foreign key in the request body exists — `venue_id`,
    `society_id`, `license_id`, `audit_case_id`, and each element of
    `society_ids` — otherwise `ERR_VENUE_NOT_FOUND`, `ERR_SOCIETY_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND` or `ERR_AUDIT_CASE_NOT_FOUND` (404)."

    Design: Corner/entities/corner_flat_topology_report_create_unknown_license_not_found
    """
    given_society(api, bmi_payload())
    given_venue(api, bar_grill_venue_payload())

    validate_error(
        api.create_performance_report(
            performance_report_payload(
                UNUSED_UUID_THIRD, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
            ),
            admin_headers(),
        ),
        ERR_LICENSE_NOT_FOUND,
    )

    assert_empty_list(api.list_performance_reports(admin_headers()))
