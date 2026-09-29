"""Validation corners: conditional rules, aggregate guards and priority order."""

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


def _basic_course(client, code="TV-101", seats=12, **overrides):
    """A BASIC course whose session runs on the evening of 2026-08-05."""
    return fx.publish_course(
        client,
        course_code=code,
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=seats,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
        **overrides
    )


def test_a_second_enrollment_is_refused_until_the_first_is_withdrawn(client):
    """The duplicate guard reads status, so a withdrawal reopens the same seat.

    PRD 3.1: ""Already holds a live enrollment" means an existing enrollment on
    that same course whose status is `ENROLLED`, `ATTENDED` or `PASSED` — a `FAILED`
    or `WITHDRAWN` enrollment does not block re-enrolment."

    PRD 3.1: "the producer must not already hold a live enrollment on the same
    course, otherwise `ERR_DUPLICATE_ENROLLMENT` (409)."

    PRD 3.1: "the `ENROLLED → WITHDRAWN` transition is permitted only while the
    logical clock is strictly before the course's `session_start_at`."

    PRD 2.9: "A course's `enrolled_count` is the count of its enrollments whose
    status is `ENROLLED`, `ATTENDED`, `PASSED` or `FAILED` — a withdrawal releases
    the seat, a failure does not — and its `passed_count` counts only `PASSED`
    enrollments."

    Design: Corner/validations/corner_duplicate_enrollment_rejected_until_withdrawal_frees_it
    """
    producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    course = _basic_course(client)
    headers = make_producer_headers(producer["id"])
    first = fx.enroll(client, producer["id"], course["id"])
    assert first["status"] == "ENROLLED"

    duplicate = client.create_course_enrollment(
        f.enrollment_payload(producer["id"], course["id"]), headers
    )

    a.error_of(duplicate, e.ERR_DUPLICATE_ENROLLMENT, 409)
    assert a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))[
        "enrolled_count"
    ] == 1

    withdrawn = a.data_of(client.withdraw_enrollment(first["id"], {}, headers))
    assert withdrawn["status"] == "WITHDRAWN"
    assert a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))[
        "enrolled_count"
    ] == 0

    second = a.created_of(
        client.create_course_enrollment(
            f.enrollment_payload(producer["id"], course["id"]), headers
        )
    )

    assert second["id"] != first["id"]
    assert second["status"] == "ENROLLED"
    reread = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert reread["enrolled_count"] == 1
    assert reread["passed_count"] == 0


def test_a_failed_seat_stays_occupied_while_a_withdrawn_one_is_released(client):
    """Capacity is an aggregate over statuses: the no-show keeps the course full.

    PRD 2.9: "A course's `enrolled_count` is the count of its enrollments whose
    status is `ENROLLED`, `ATTENDED`, `PASSED` or `FAILED` — a withdrawal releases
    the seat, a failure does not — and its `passed_count` counts only `PASSED`
    enrollments."

    PRD 3.1: "a seat must remain, otherwise `ERR_COURSE_FULL` (409)"

    PRD 3.1: "When `attended` is false the enrollment moves `ENROLLED → FAILED`, no
    competency is granted, and — this is the deliberate asymmetry with withdrawal —
    the course's `enrolled_count` is **not** decremented, because a no-show consumed
    the seat."

    PRD 3.1: "A withdrawal releases the seat, lowering `enrolled_count` by 1."

    Design: Corner/validations/corner_course_capacity_counts_failed_seats_but_not_withdrawn
    """
    first_producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    second_producer = fx.setup_active_producer(client, legal_name="Grace Hopper")
    crowded = _basic_course(client, code="TV-101", seats=1)
    spare = fx.publish_course(
        client,
        course_code="TV-102",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=1,
        session_start_at="2026-08-10T17:00:00Z",
        session_end_at="2026-08-10T21:00:00Z",
    )
    incumbent = fx.enroll(client, first_producer["id"], crowded["id"])
    spare_seat = fx.enroll(client, first_producer["id"], spare["id"])
    challenger_headers = make_producer_headers(second_producer["id"])

    a.error_of(
        client.create_course_enrollment(
            f.enrollment_payload(second_producer["id"], crowded["id"]), challenger_headers
        ),
        e.ERR_COURSE_FULL,
        409,
    )

    released = a.data_of(
        client.withdraw_enrollment(
            spare_seat["id"], {}, make_producer_headers(first_producer["id"])
        )
    )
    assert released["status"] == "WITHDRAWN"
    freed = a.created_of(
        client.create_course_enrollment(
            f.enrollment_payload(second_producer["id"], spare["id"]), challenger_headers
        )
    )
    assert freed["status"] == "ENROLLED"
    assert a.data_of(client.get_training_course(spare["id"], TRAINER_HEADERS))[
        "enrolled_count"
    ] == 1

    fx.set_clock(client, "2026-08-06T00:00:00Z")
    no_show = fx.mark_attended(client, incumbent["id"], False)
    assert no_show["status"] == "FAILED"

    a.error_of(
        client.create_course_enrollment(
            f.enrollment_payload(second_producer["id"], crowded["id"]), challenger_headers
        ),
        e.ERR_COURSE_FULL,
        409,
    )
    final = a.data_of(client.get_training_course(crowded["id"], TRAINER_HEADERS))
    assert final["enrolled_count"] == 1
    assert final["passed_count"] == 0


def test_the_licence_citation_is_demanded_only_of_the_copyright_attestation(client):
    """Two conditions must coincide, so the same declaration is harmless elsewhere.

    PRD 3.3: "A `COPYRIGHT_CLEARANCE` attestation that declares
    `third_party_material` true while leaving `license_reference` absent or empty is
    refused with `ERR_LICENSE_REFERENCE_REQUIRED` (422)."

    PRD 3.3: "Three kinds are required for clearance: `INDEMNIFICATION`,
    `COPYRIGHT_CLEARANCE` and `CONTENT_POLICY`."

    PRD 3.3: "When all three of those latest attestations carry a
    `statement_version` equal to the current statement version, which is `2026.1`,
    the program moves `INCOMPLETE → CLEARED` and its `version` increments by 1;
    `review_status` is untouched by that move."

    PRD 3.3: "An `INDEMNIFICATION` attestation additionally refreshes the signing
    producer's `indemnification_expires_at` to 365 days after the current logical
    instant"

    Design: Corner/validations/corner_license_reference_conditional_on_third_party_copyright
    """
    producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    headers = make_producer_headers(producer["id"])
    program = fx.create_program(client, producer["id"], title="Neighborhood Notes")
    assert program["clearance_status"] == "INCOMPLETE"

    indemnification = a.created_of(
        client.append_attestation(
            program["id"],
            f.attestation_payload(producer["id"], "INDEMNIFICATION", third_party_material=True),
            headers,
        )
    )
    assert indemnification["sequence_number"] == 1
    a.assert_field_absent_or_null(indemnification, "license_reference")

    a.error_of(
        client.append_attestation(
            program["id"],
            f.attestation_payload(
                producer["id"], "COPYRIGHT_CLEARANCE", third_party_material=True
            ),
            headers,
        ),
        e.ERR_LICENSE_REFERENCE_REQUIRED,
        422,
    )

    copyright_row = a.created_of(
        client.append_attestation(
            program["id"],
            f.attestation_payload(
                producer["id"],
                "COPYRIGHT_CLEARANCE",
                third_party_material=True,
                license_reference="ASCAP-2026-11824",
            ),
            headers,
        )
    )
    assert copyright_row["sequence_number"] == 2
    assert copyright_row["license_reference"] == "ASCAP-2026-11824"

    policy = a.created_of(
        client.append_attestation(
            program["id"],
            f.attestation_payload(producer["id"], "CONTENT_POLICY", third_party_material=False),
            headers,
        )
    )
    assert policy["sequence_number"] == 3

    on_file, _meta = a.assert_pagination_meta(
        client.list_attestations(
            headers,
            {"program_id": program["id"], "attestation_kind": "COPYRIGHT_CLEARANCE"},
        ),
        1,
    )
    a.assert_ids_equal(on_file, [copyright_row["id"]])

    cleared = fx.read_program(client, program["id"])
    assert cleared["clearance_status"] == "CLEARED"
    assert cleared["review_status"] == "DRAFT"
    assert cleared["attestation_sequence_high"] == 3
    a.assert_instant_equals(
        fx.read_producer(client, producer["id"])["indemnification_expires_at"],
        "2027-08-01T00:00:00Z",
        "indemnification_expires_at",
    )


def test_the_competency_gate_reads_the_producers_own_course_history(client):
    """The reservation never changes; the producer's training does.

    PRD 3.6: "the asset's `required_competency_code` must appear in the producer's
    `competency_codes`, otherwise `ERR_COMPETENCY_NOT_HELD` (422)"

    PRD 3.1: "the producer's `competency_codes` gains every code in that course's
    `grants_competency_codes`, the producer's `certification_level` is re-derived,
    and both the enrollment's `version` and the producer's `version` increment by 1."

    PRD 3.6: "Requesting a reservation holds no money whatsoever."

    PRD 3.6: "A clean comparison case, with no suspension points, a two-hour window
    and no live link, gives the base 12345 plus a duration line of 617, for a hold of
    12962 cents."

    Design: Corner/validations/corner_competency_gate_depends_on_producer_course_history
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    assert sorted(producer["competency_codes"]) == ["EDIT_SUITE", "STUDIO_FLOOR"]
    resource = fx.create_resource(
        client,
        resource_code="MC-SUITE",
        resource_class="EDIT_SUITE",
        required_competency_code="AUDIO_BOARD",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    reservation = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-20T10:00:00Z", end_at="2026-08-20T12:00:00Z",
    )
    advanced = fx.publish_course(
        client,
        course_code="TV-201",
        tier="ADVANCED",
        grants_competency_codes=["AUDIO_BOARD"],
        seat_capacity=12,
        session_start_at="2026-08-12T17:00:00Z",
        session_end_at="2026-08-12T21:00:00Z",
    )
    enrollment = fx.enroll(client, producer["id"], advanced["id"])

    blocked = client.confirm_reservation(reservation["id"], {}, FACILITIES_HEADERS)

    a.error_of(blocked, e.ERR_COMPETENCY_NOT_HELD, 422)
    refused = fx.read_reservation(client, reservation["id"])
    assert refused["status"] == "REQUESTED"
    a.assert_cents(refused["deposit_hold_cents"], 0, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=0)

    fx.set_clock(client, "2026-08-13T00:00:00Z")
    fx.mark_attended(client, enrollment["id"], True)
    assert fx.grade(client, enrollment["id"], 91)["status"] == "PASSED"
    trained = fx.read_producer(client, producer["id"])
    assert trained["certification_level"] == "ADVANCED"
    assert sorted(trained["competency_codes"]) == ["AUDIO_BOARD", "EDIT_SUITE", "STUDIO_FLOOR"]

    confirmed = fx.confirm_reservation(client, reservation["id"])

    assert confirmed["status"] == "CONFIRMED"
    a.assert_cents(confirmed["deposit_hold_cents"], 12962, "deposit_hold_cents")
    assert confirmed["risk_bp"] == 0
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12962)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


def test_submission_fails_at_the_expiry_instant_and_a_re_signature_renews_the_term(client):
    """The indemnification test is inclusive of the expiry instant itself.

    PRD 3.3: "The producer's `indemnification_expires_at` must be non-null and
    strictly later than the current logical instant, otherwise
    `ERR_INDEMNIFICATION_EXPIRED` (422)."

    PRD 3.3: "An `INDEMNIFICATION` attestation additionally refreshes the signing
    producer's `indemnification_expires_at` to 365 days after the current logical
    instant — the producer-level expiry is what later gates submission, and it is a
    producer-wide term, not a per-program one."

    PRD 3.3: "A successful submission clears `reviewed_by_user_id` back to null, so
    that any reviewer may claim the next round, and increments the program's
    `version` by 1."

    Design: Corner/validations/corner_indemnification_expiry_boundary_blocks_submit
    """
    producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    headers = make_producer_headers(producer["id"])
    program = fx.setup_cleared_program(client, producer["id"], title="Neighborhood Notes")
    assert program["clearance_status"] == "CLEARED"
    assert program["review_status"] == "DRAFT"
    a.assert_instant_equals(
        fx.read_producer(client, producer["id"])["indemnification_expires_at"],
        "2027-08-01T00:00:00Z",
        "indemnification_expires_at",
    )

    fx.set_clock(client, "2027-08-01T00:00:00Z")
    expired = client.submit_program(program["id"], {}, headers)

    a.error_of(expired, e.ERR_INDEMNIFICATION_EXPIRED, 422)
    assert fx.read_program(client, program["id"])["review_status"] == "DRAFT"

    renewal = fx.append_attestation(client, program["id"], producer["id"], "INDEMNIFICATION")
    assert renewal["sequence_number"] == 4
    a.assert_instant_equals(
        fx.read_producer(client, producer["id"])["indemnification_expires_at"],
        "2028-07-31T00:00:00Z",
        "indemnification_expires_at",
    )

    submitted = fx.submit_program(client, program["id"], producer["id"])

    assert submitted["review_status"] == "SUBMITTED"
    assert submitted["clearance_status"] == "CLEARED"
    a.assert_field_absent_or_null(submitted, "reviewed_by_user_id")


def test_a_producer_calling_an_admin_only_path_sees_the_role_refusal_not_a_404(client):
    """Role admission is settled before the service looks the identifier up.

    PRD 2.8: "**Role authorisation (priority 2)** — `ERR_FORBIDDEN_ROLE`, 403.
    Applies to every operation."

    PRD 2.8: "**Path existence (priority 4)** — the addressed entity's own not-found
    error, 404. Applies to every operation with a path parameter."

    PRD 2.8: "The service evaluates rules in a strict ascending priority order and
    reports **only the first violation it finds**; later violations on the same
    request are invisible."

    Design: Corner/validations/corner_forbidden_role_outranks_path_not_found
    """
    producer = fx.register_producer(client, legal_name="Ada Lovelace")
    document = f.residency_payload(document_reference="UTIL-2026-9999")

    a.error_of(
        client.verify_residency(UNKNOWN_UUID, document, make_producer_headers(producer["id"])),
        e.ERR_FORBIDDEN_ROLE,
        403,
    )
    a.error_of(
        client.verify_residency(UNKNOWN_UUID, document, ADMIN_HEADERS),
        e.ERR_PRODUCER_NOT_FOUND,
        404,
    )

    untouched = fx.read_producer(client, producer["id"])
    assert untouched["residency_verified"] is False
    assert untouched["status"] == "APPLICANT"
    a.assert_common_fields(untouched, expected_version=1)


def test_a_malformed_body_is_refused_before_its_foreign_keys_are_resolved(client):
    """Schema checking at priority 3 masks the unresolvable producer at priority 5.

    PRD 2.8: "**Request schema (priority 3)** — `ERR_INVALID_REQUEST`, 400. Applies
    to every operation with a request body or query parameters. A required input
    field is missing or null"

    PRD 2.8: "**Body foreign-key existence (priority 5)** — the referenced entity's
    own not-found error, 404. Applies to enrollment creation, series creation,
    program creation, playback-slot creation, reservation creation and
    crew-assignment creation."

    PRD 3.1: "Either the producer themselves or a `TrainingCoordinator` may create
    an enrollment by supplying `producer_id` and `course_id`"

    Design: Corner/validations/corner_invalid_request_outranks_body_fk_not_found
    """
    course = _basic_course(client)

    a.error_of(
        client.create_course_enrollment({"producer_id": UNKNOWN_UUID}, TRAINER_HEADERS),
        e.ERR_INVALID_REQUEST,
        400,
    )
    a.error_of(
        client.create_course_enrollment(
            {"producer_id": UNKNOWN_UUID, "course_id": course["id"]}, TRAINER_HEADERS
        ),
        e.ERR_PRODUCER_NOT_FOUND,
        404,
    )

    listed, _meta = a.assert_pagination_meta(client.list_course_enrollments(TRAINER_HEADERS), 0)
    assert listed == []
    assert a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))[
        "enrolled_count"
    ] == 0


def test_an_educational_channel_opens_to_the_same_program_once_its_owner_advances(client):
    """The tier gate reads the producer's level, not anything on the booking.

    PRD 3.4: "channel tier is rationed by certification: a producer whose
    `certification_level` is `BASIC` may occupy only a `PUBLIC` channel, and booking
    an `EDUCATIONAL` or `GOVERNMENT` channel for that producer's program is refused
    with `ERR_CHANNEL_TIER_NOT_ELIGIBLE` (422); only `ADVANCED` and `LIVE` producers
    reach those tiers."

    PRD 3.1: "otherwise, if it contains both `BASIC` and `ADVANCED`, the level is
    `ADVANCED`"

    PRD 3.4: "A slot's footprint is not merely the program's runtime:
    `occupied_seconds` is the program's `runtime_seconds` plus the channel's
    `inter_program_buffer_seconds`, and it is frozen on the slot at creation so that
    a later change to either input cannot retroactively move the schedule."

    PRD 2.9: "A channel's `scheduled_seconds` is the sum of `occupied_seconds` over
    its `SCHEDULED` slots and its `aired_seconds` is the same sum over its `AIRED`
    slots."

    Design: Corner/validations/corner_channel_tier_eligibility_satisfied_by_advanced_certification
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    assert producer["certification_level"] == "BASIC"
    channel = fx.create_channel(
        client,
        call_sign="PATV-EDU",
        tier="EDUCATIONAL",
        daily_window_start_minute=1080,
        daily_window_end_minute=1380,
        inter_program_buffer_seconds=120,
    )
    program = fx.setup_approved_program(
        client, producer["id"], title="Neighborhood Notes", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    advanced = fx.publish_course(
        client,
        course_code="TV-201",
        tier="ADVANCED",
        grants_competency_codes=["AUDIO_BOARD"],
        seat_capacity=12,
        session_start_at="2026-08-12T17:00:00Z",
        session_end_at="2026-08-12T21:00:00Z",
    )
    enrollment = fx.enroll(client, producer["id"], advanced["id"])

    refused = client.create_playback_slot(
        f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T18:00:00Z"),
        SCHEDULER_HEADERS,
    )

    a.error_of(refused, e.ERR_CHANNEL_TIER_NOT_ELIGIBLE, 422)
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 0, 0)

    fx.set_clock(client, "2026-08-13T00:00:00Z")
    fx.mark_attended(client, enrollment["id"], True)
    assert fx.grade(client, enrollment["id"], 91)["status"] == "PASSED"
    assert fx.read_producer(client, producer["id"])["certification_level"] == "ADVANCED"

    slot = a.created_of(
        client.create_playback_slot(
            f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T18:00:00Z"),
            SCHEDULER_HEADERS,
        )
    )

    assert slot["status"] == "SCHEDULED"
    assert slot["occupied_seconds"] == 1920
    a.assert_instant_equals(slot["end_at"], "2026-08-20T18:32:00Z", "end_at")
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 1920, 0)


def test_a_program_may_only_join_a_strand_its_own_producer_owns(client):
    """The series exists, so the refusal is a business 422 rather than a 404.

    PRD 3.3: "Where a `series_id` is supplied, that series must belong to the same
    producer as the program; a cross-owner reference is refused with
    `ERR_SERIES_NOT_OWNED_BY_PRODUCER` (422)."

    PRD 3.3: "A program is born with `review_status` `DRAFT`, `clearance_status`
    `INCOMPLETE`, `revision_round` at 0, `attestation_sequence_high` at 0, a null
    `reviewed_by_user_id`, a null `finding_category`, a null `finding_notes` and a
    null `withdrawn_reason`."

    Design: Corner/validations/corner_series_not_owned_by_producer_rejected_on_program_creation
    """
    owner = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    stranger = fx.setup_active_producer(client, legal_name="Grace Hopper")
    own_series = fx.propose_series(client, owner["id"], title="Riverside Weekly")
    other_series = fx.propose_series(client, stranger["id"], title="Harbor Nightly")
    assert own_series["status"] == "PROPOSED"
    assert other_series["status"] == "PROPOSED"
    headers = make_producer_headers(owner["id"])

    borrowed = client.create_program(
        f.program_payload(
            owner["id"],
            title="Borrowed Strand Episode",
            runtime_seconds=1800,
            series_id=other_series["id"],
            episode_number=1,
        ),
        headers,
    )

    a.error_of(borrowed, e.ERR_SERIES_NOT_OWNED_BY_PRODUCER, 422)

    accepted = a.created_of(
        client.create_program(
            f.program_payload(
                owner["id"],
                title="Own Strand Episode",
                runtime_seconds=1800,
                series_id=own_series["id"],
                episode_number=1,
            ),
            headers,
        )
    )

    assert accepted["series_id"] == own_series["id"]
    assert accepted["episode_number"] == 1
    assert accepted["review_status"] == "DRAFT"
    assert accepted["clearance_status"] == "INCOMPLETE"
    assert accepted["revision_round"] == 0
    assert accepted["attestation_sequence_high"] == 0
    listed, _meta = a.assert_pagination_meta(client.list_programs(ADMIN_HEADERS), 1)
    a.assert_ids_equal(listed, [accepted["id"]])


def test_the_maintenance_objection_answers_before_the_capacity_objection(client):
    """Both rules are violated; clearing the higher one reveals the lower one.

    PRD 3.6: "the asset's status must be `AVAILABLE`, otherwise
    `ERR_RESOURCE_NOT_AVAILABLE` (409)"

    PRD 3.6: "The asset is full when the count of such overlapping reservations has
    already reached `capacity_slots`."

    PRD 3.6: "`AVAILABLE → MAINTENANCE` and `MAINTENANCE → AVAILABLE` are both
    freely available and both simply record the reason and increment the asset's
    `version` by 1; existing reservations keep their own status across a maintenance
    move, but no `REQUESTED` reservation on the asset can be confirmed while it sits
    in `MAINTENANCE`."

    PRD 2.9: "A studio resource's `open_reservation_count` is the count of its
    reservations whose status is `CONFIRMED`, `CHECKED_OUT` or `DAMAGE_REVIEW`."

    Design: Corner/validations/corner_resource_availability_check_runs_before_overbooking_check
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    incumbent = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-20T10:00:00Z", end_at="2026-08-20T12:00:00Z",
    )
    incumbent = fx.confirm_reservation(client, incumbent["id"])
    a.assert_cents(incumbent["deposit_hold_cents"], 12962, "deposit_hold_cents")
    challenger = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-20T10:30:00Z", end_at="2026-08-20T11:30:00Z",
    )

    in_maintenance = fx.set_resource_status(
        client, resource["id"], "MAINTENANCE", status_reason="Lamp replacement"
    )
    assert in_maintenance["status"] == "MAINTENANCE"
    assert in_maintenance["open_reservation_count"] == 1
    masked = client.confirm_reservation(challenger["id"], {}, FACILITIES_HEADERS)

    a.error_of(masked, e.ERR_RESOURCE_NOT_AVAILABLE, 409)

    back_in_service = fx.set_resource_status(
        client, resource["id"], "AVAILABLE", status_reason="Service complete"
    )
    assert back_in_service["status"] == "AVAILABLE"
    assert back_in_service["open_reservation_count"] == 1
    overbooked = client.confirm_reservation(challenger["id"], {}, FACILITIES_HEADERS)

    a.error_of(overbooked, e.ERR_RESOURCE_OVERBOOKED, 409)
    still = fx.read_reservation(client, challenger["id"])
    assert still["status"] == "REQUESTED"
    a.assert_cents(still["deposit_hold_cents"], 0, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12962)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1
