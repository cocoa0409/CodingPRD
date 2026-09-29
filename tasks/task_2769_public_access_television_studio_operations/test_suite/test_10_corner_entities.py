"""Entity-shape corners: defaults, computed fields, envelopes and referents."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    make_producer_headers,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_SERIES_UUID = "00000000-0000-4000-8000-0000000000aa"


def test_registering_a_producer_returns_every_declared_applicant_default(client):
    """A creation returns 201 and every system field at its stated opening value.

    PRD 3.1: "A freshly registered producer sits in `APPLICANT` status with
    `residency_verified` false, `certification_level` `NONE`, an empty
    `competency_codes` list, `suspension_points` at 0, `reinstated_count` at 0, a
    null `indemnification_expires_at`, a null `revocation_reason`, and every
    derived money and volunteer counter — `deposit_held_cents`,
    `deposit_forfeited_total_cents`, `volunteer_hours_tenths` and
    `confirmed_crew_commitments` — at 0."

    PRD 2.4: "Every resource carries a server-minted `id` that is a UUID string
    with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with
    three fractional digits. Clients never supply either."

    PRD 4: "Creating a new resource returns HTTP 201 with the created resource in
    `data`; every other successful operation, including every state transition and
    every read, returns HTTP 200."

    Design: Corner/entities/corner_producer_creation_returns_applicant_defaults
    """
    payload = f.producer_payload(legal_name="Ada Lovelace")

    producer = a.created_of(client.create_producer(payload, ADMIN_HEADERS))

    assert producer["status"] == "APPLICANT"
    assert producer["certification_level"] == "NONE"
    assert producer["legal_name"] == "Ada Lovelace"
    assert producer["email"] == payload["email"]
    assert producer["residency_verified"] is False
    assert producer["competency_codes"] == []
    a.assert_producer_counters(
        producer,
        held=0,
        forfeited_total=0,
        suspension_points=0,
        volunteer_tenths=0,
        commitments=0,
    )
    assert producer["reinstated_count"] == 0
    a.assert_field_absent_or_null(producer, "indemnification_expires_at")
    a.assert_field_absent_or_null(producer, "revocation_reason")
    a.assert_common_fields(producer, expected_version=1)


def test_reading_a_channel_back_returns_exactly_what_creation_stored(client):
    """The read is a faithful echo of the stored row, counters included.

    PRD 3.4: "A channel carries a `call_sign` unique across all channels — a
    reuse is `ERR_DUPLICATE_NATURAL_KEY` (409) — a `tier` of `PUBLIC`,
    `EDUCATIONAL` or `GOVERNMENT` marking its PEG designation, and a daily
    broadcast window given as `daily_window_start_minute` and
    `daily_window_end_minute`, both counted in minutes after 00:00 UTC."

    PRD 3.4: "A new channel opens with `scheduled_seconds` at 0, `aired_seconds`
    at 0 and `slot_sequence_high` at 0."

    Design: Corner/entities/corner_channel_retrieval_returns_stored_data
    """
    created = fx.create_channel(
        client,
        call_sign="PATV1",
        tier="PUBLIC",
        daily_window_start_minute=1080,
        daily_window_end_minute=1380,
        inter_program_buffer_seconds=120,
    )

    read = a.data_of(client.get_channel(created["id"], SCHEDULER_HEADERS))

    assert read["id"] == created["id"]
    assert read["call_sign"] == "PATV1"
    assert read["tier"] == "PUBLIC"
    assert read["daily_window_start_minute"] == 1080
    assert read["daily_window_end_minute"] == 1380
    assert read["inter_program_buffer_seconds"] == 120
    a.assert_channel_ledger(read, 0, 0)
    assert read["slot_sequence_high"] == 0
    a.assert_common_fields(read, expected_version=1)


def test_listing_producers_pages_by_creation_order_with_a_total_count(client):
    """Two pages of three rows, with total_count counted before pagination.

    PRD 2.3: "Every list response reports `limit` and `offset` as they were
    applied, `total_count` as the number of rows matching the filters before
    pagination, and `has_more` as true exactly when rows remain beyond the current
    page."

    PRD 2.3: "Collection reads are ordered by `created_at` ascending."

    PRD 2.3: "`limit` controls page size: its default is 10, its minimum accepted
    value is 1, and its maximum accepted value is 100. `offset` controls the
    starting position: its default is 0 and its minimum accepted value is 0."

    Design: Corner/entities/corner_producers_listing_paginates_with_total_count
    """
    first = fx.register_producer(client, legal_name="Ada Lovelace")
    fx.register_producer(client, legal_name="Grace Hopper")
    third = fx.register_producer(client, legal_name="Vera Rubin")

    page_one, meta_one = a.assert_pagination_meta(
        client.list_producers(ADMIN_HEADERS, {"limit": 2, "offset": 0}), 3
    )
    page_two, meta_two = a.assert_pagination_meta(
        client.list_producers(ADMIN_HEADERS, {"limit": 2, "offset": 2}), 3
    )

    assert len(page_one) == 2
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0
    assert meta_one["has_more"] is True
    assert page_one[0]["id"] == first["id"]

    assert len(page_two) == 1
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False
    assert page_two[0]["id"] == third["id"]

    filtered, meta_filtered = a.assert_pagination_meta(
        client.list_producers(ADMIN_HEADERS, {"status": "APPLICANT"}), 3
    )
    assert len(filtered) == 3
    assert filtered[0]["id"] == first["id"]

    defaulted, meta_default = a.assert_pagination_meta(client.list_producers(ADMIN_HEADERS), 3)
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0
    assert meta_default["has_more"] is False
    assert len(defaulted) == 3
    assert meta_filtered["has_more"] is False


def test_an_unknown_identifier_reports_the_addressed_entitys_own_not_found(client):
    """Each read reports its own 404 error id, never a generic one.

    PRD 2.8: "**Path existence (priority 4)** — the addressed entity's own
    not-found error, 404. Applies to every operation with a path parameter. Path
    identifiers are resolved left to right and the leftmost missing segment decides
    which error is reported."

    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/corner_producer_not_found_returns_producer_not_found
    """
    producer_error = a.error_of(
        client.get_producer(UNKNOWN_UUID, ADMIN_HEADERS), e.ERR_PRODUCER_NOT_FOUND, 404
    )
    assert isinstance(producer_error["message"], str) and producer_error["message"]

    a.error_of(
        client.get_channel(UNKNOWN_UUID, SCHEDULER_HEADERS), e.ERR_CHANNEL_NOT_FOUND, 404
    )
    a.error_of(
        client.get_reservation(UNKNOWN_UUID, FACILITIES_HEADERS),
        e.ERR_RESERVATION_NOT_FOUND,
        404,
    )


def test_publishing_a_course_without_a_seat_capacity_is_a_schema_refusal(client):
    """A missing required input is a 400 and nothing is persisted.

    PRD 2.8: "**Request schema (priority 3)** — `ERR_INVALID_REQUEST`, 400.
    Applies to every operation with a request body or query parameters. A required
    input field is missing or null; a field carries the wrong JSON type; an enum
    field carries a value outside its declared set"

    PRD 3.1: "A course carries a `course_code` — a catalog key unique across all
    courses, whose reuse is refused with `ERR_DUPLICATE_NATURAL_KEY` — plus a
    `title`, a `tier` of `BASIC`, `ADVANCED` or `LIVE`, a non-empty
    `grants_competency_codes` list drawn from the five equipment competency codes,
    a `seat_capacity` of at least 1, and a session window given by
    `session_start_at` and `session_end_at`, where the end must be strictly after
    the start."

    Design: Corner/entities/corner_training_course_missing_seat_capacity_returns_invalid_request
    """
    for omitted in ("seat_capacity", "title", "tier", "grants_competency_codes",
                    "session_start_at", "session_end_at"):
        payload = f.training_course_payload(course_code="TV-101")
        payload.pop(omitted)
        a.error_of(
            client.create_training_course(payload, TRAINER_HEADERS),
            e.ERR_INVALID_REQUEST,
            400,
        )

    listed, meta = a.assert_pagination_meta(client.list_training_courses(TRAINER_HEADERS), 0)
    assert listed == []
    assert meta["has_more"] is False


def test_a_channel_created_without_the_flag_enables_preemption_by_default(client):
    """The optional flag defaults to true and an explicit false overrides it.

    PRD 3.4: "`preemption_enabled` defaults to true; when it is set false, a
    series-priority challenger can never displace an incumbent on that channel."

    PRD 3.4: "`inter_program_buffer_seconds` gives the interstitial seconds
    appended to every slot on the channel and must not be negative."

    Design: Corner/entities/corner_channel_preemption_enabled_defaults_to_true
    """
    defaulted = fx.create_channel(client, call_sign="PATV1")
    explicit = fx.create_channel(
        client, call_sign="PATV2", inter_program_buffer_seconds=0, preemption_enabled=False
    )

    assert defaulted["preemption_enabled"] is True
    assert explicit["preemption_enabled"] is False
    assert explicit["inter_program_buffer_seconds"] == 0
    a.assert_channel_ledger(defaulted, 0, 0)
    a.assert_channel_ledger(explicit, 0, 0)


def test_a_slots_footprint_is_computed_from_the_channels_own_buffer(client):
    """The buffer belongs to the channel, so the client never states the footprint.

    PRD 3.4: "A slot's footprint is not merely the program's runtime:
    `occupied_seconds` is the program's `runtime_seconds` plus the channel's
    `inter_program_buffer_seconds`, and it is frozen on the slot at creation so
    that a later change to either input cannot retroactively move the schedule."

    PRD 3.4: "its `sequence_number` is set to the channel's `slot_sequence_high`
    plus 1, with `slot_sequence_high` advancing to match."

    PRD 3.4: "`measured_households` stays null until the slot airs, `aired_at` and
    `cancellation_reason` stay null, and `preempted_by_slot_id` stays null unless
    and until this slot is itself displaced."

    Design: Corner/entities/corner_playback_slot_occupied_seconds_is_computed
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(
        client, call_sign="PATV3", inter_program_buffer_seconds=90
    )
    program = fx.setup_approved_program(
        client, producer["id"], title="Short Feature", runtime_seconds=1500,
        is_live=False, required_crew_roles=[],
    )

    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")

    assert slot["occupied_seconds"] == 1590
    a.assert_instant_equals(slot["end_at"], "2026-08-20T18:26:30Z", "end_at")
    assert slot["sequence_number"] == 1
    a.assert_field_absent_or_null(slot, "measured_households")
    a.assert_field_absent_or_null(slot, "aired_at")
    a.assert_field_absent_or_null(slot, "cancellation_reason")
    a.assert_field_absent_or_null(slot, "preempted_by_slot_id")

    after = fx.read_channel(client, channel["id"])
    assert after["slot_sequence_high"] == 1
    a.assert_channel_ledger(after, 1590, 0)


def test_system_sourced_producer_fields_cannot_be_seeded_by_the_client(client):
    """Membership state and sanction counters are the server's to set.

    PRD 3.1: "Membership begins with a registration performed by a `CenterAdmin`,
    who records the applicant's `legal_name` and their `email`."

    PRD 3.1: "A freshly registered producer sits in `APPLICANT` status with
    `residency_verified` false, `certification_level` `NONE`, an empty
    `competency_codes` list, `suspension_points` at 0, `reinstated_count` at 0"

    PRD 2.4: "Every resource carries a server-minted `id` that is a UUID string
    with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with
    three fractional digits. Clients never supply either."

    Design: Corner/entities/corner_producer_creation_extra_field_ignored
    """
    payload = f.producer_payload(
        legal_name="Ada Lovelace",
        status="ACTIVE",
        suspension_points=9,
        certification_level="LIVE",
        id=UNKNOWN_UUID,
    )

    producer = a.created_of(client.create_producer(payload, ADMIN_HEADERS))

    assert producer["status"] == "APPLICANT"
    assert producer["certification_level"] == "NONE"
    a.assert_producer_counters(producer, suspension_points=0)
    assert producer["residency_verified"] is False
    assert producer["id"] != UNKNOWN_UUID
    a.assert_common_fields(producer, expected_version=1)
    assert fx.read_producer(client, producer["id"])["status"] == "APPLICANT"


def test_an_out_of_enum_tier_and_an_inverted_window_are_both_schema_refusals(client):
    """Both are 400s from the schema band, never 422 business refusals.

    PRD 2.1: "Channel tier is `PUBLIC`, `EDUCATIONAL` or `GOVERNMENT`."

    PRD 2.8: "an enum field carries a value outside its declared set; an integer
    field is negative where non-negative is required; a reservation's `end_at` is
    at or before its `start_at`; a course's `session_end_at` is at or before its
    `session_start_at`; a channel's `daily_window_end_minute` is at or below its
    `daily_window_start_minute`"

    Design: Corner/entities/corner_channel_invalid_tier_enum_rejected
    """
    a.error_of(
        client.create_channel(
            f.channel_payload(call_sign="PATV9", tier="MUNICIPAL"), ADMIN_HEADERS
        ),
        e.ERR_INVALID_REQUEST,
        400,
    )
    a.error_of(
        client.create_channel(
            f.channel_payload(
                call_sign="PATV9",
                daily_window_start_minute=1380,
                daily_window_end_minute=1080,
            ),
            ADMIN_HEADERS,
        ),
        e.ERR_INVALID_REQUEST,
        400,
    )

    listed, _meta = a.assert_pagination_meta(client.list_channels(SCHEDULER_HEADERS), 0)
    assert listed == []


def test_an_attestation_is_append_only_and_carries_no_version(client):
    """A correction is a new row with the next sequence number, never an edit.

    PRD 2.4: "The `Attestation` resource is the exception: attestations are an
    append-only legal log, never edited after they are written, so an attestation
    carries only `id` and `created_at`. It has no `updated_at` field and no
    `version` field at all, and neither is ever emitted for it."

    PRD 3.3: "Each new one is stamped with a `sequence_number` equal to the
    program's `attestation_sequence_high` plus 1 — so the counter is per-program,
    starting at 1 — and that high-water mark advances with it. Its
    `effective_from` is the current logical instant. Its `effective_until` is set
    only for the `INDEMNIFICATION` kind, at 365 days after its own
    `effective_from`; for `COPYRIGHT_CLEARANCE` and `CONTENT_POLICY` attestations
    `effective_until` is null."

    Design: Corner/entities/corner_attestation_is_immutable_with_no_version_field
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    program = fx.create_program(client, producer["id"], title="Neighborhood Notes")

    first = a.created_of(
        client.append_attestation(
            program["id"],
            f.attestation_payload(producer["id"], "INDEMNIFICATION"),
            make_producer_headers(producer["id"]),
        )
    )
    second = a.created_of(
        client.append_attestation(
            program["id"],
            f.attestation_payload(producer["id"], "INDEMNIFICATION"),
            make_producer_headers(producer["id"]),
        )
    )

    assert first["sequence_number"] == 1
    assert second["sequence_number"] == 2
    a.assert_attestation_shape(first)
    a.assert_attestation_shape(second)
    a.assert_instant_equals(first["effective_from"], "2026-08-06T00:00:00Z", "effective_from")
    a.assert_instant_equals(first["effective_until"], "2027-08-06T00:00:00Z", "effective_until")
    assert second["signed_by_producer_id"] == producer["id"]
    assert second["program_id"] == program["id"]

    reread = a.data_of(
        client.get_attestation(first["id"], make_producer_headers(producer["id"]))
    )
    assert reread["id"] == first["id"]
    assert reread["sequence_number"] == 1
    a.assert_attestation_shape(reread)
    assert fx.read_program(client, program["id"])["attestation_sequence_high"] == 2


def test_an_unknown_series_reference_on_a_program_is_reported_as_not_found(client):
    """Body foreign keys are resolved before any referential business rule.

    PRD 2.8: "**Body foreign-key existence (priority 5)** — the referenced
    entity's own not-found error, 404. Applies to enrollment creation, series
    creation, program creation, playback-slot creation, reservation creation and
    crew-assignment creation."

    PRD 3.3: "Where a `series_id` is supplied, that series must belong to the same
    producer as the program; a cross-owner reference is refused with
    `ERR_SERIES_NOT_OWNED_BY_PRODUCER` (422)."

    Design: Corner/entities/corner_program_series_fk_must_exist
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")

    response = client.create_program(
        f.program_payload(
            producer["id"],
            series_id=UNKNOWN_SERIES_UUID,
            episode_number=1,
            title="Orphan Episode",
        ),
        make_producer_headers(producer["id"]),
    )

    a.error_of(response, e.ERR_SERIES_NOT_FOUND, 404)
    listed, _meta = a.assert_pagination_meta(
        client.list_programs(make_producer_headers(producer["id"])), 0
    )
    assert listed == []

    accepted = a.created_of(
        client.create_program(
            f.program_payload(producer["id"], title="Orphan Episode"),
            make_producer_headers(producer["id"]),
        )
    )
    assert accepted["review_status"] == "DRAFT"
    a.assert_field_absent_or_null(accepted, "series_id")
