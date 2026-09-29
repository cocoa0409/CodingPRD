"""Error corners: each refusal code raised on its own documented occasion."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN2_HEADERS,
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    FINANCE2_HEADERS,
    FINANCE_HEADERS,
    ROLE_CENTER_ADMIN,
    ROLE_FACILITIES_MANAGER,
    ROLE_FINANCE_OFFICER,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    USER_ADMIN,
    USER_ADMIN_2,
    USER_FINANCE,
    USER_FINANCE_2,
    make_producer_headers,
    make_staff_headers,
)

NO_HEADERS = {}
ROLE_ONLY_HEADERS = {"X-User-Role": ROLE_CENTER_ADMIN, "Content-Type": "application/json"}
USER_ONLY_HEADERS = {"X-User-ID": USER_ADMIN, "Content-Type": "application/json"}
CLOCK_ONLY_HEADERS = {"X-User-ID": "sys-1", "Content-Type": "application/json"}


def test_neither_identity_header_may_be_left_off_an_ordinary_call(client):
    """Identity is checked first, and only the clock control is exempt from it.

    PRD 2.1: "Every request other than the logical-clock control operation must
    carry two headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, naming the role that user is acting in."

    PRD 2.1: "When either header is missing or empty on an operation that
    requires it, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401),
    and this check precedes every other check in the system — an unauthenticated
    call naming a non-existent resource still returns 401, never 404."

    PRD 2.8: "**Authentication (priority 1)** — `ERR_UNAUTHENTICATED`, 401.
    Applies to every operation except the logical-clock control operation."

    PRD 2.5: "An operator in any of the seven roles may reposition the clock by
    supplying `to_iso8601`, the new instant in ISO 8601 form; the response reports
    the instant now in force as `current_utc`."

    Design: Corner/errors/corner_error_unauthenticated_missing_auth_headers
    """
    payload = f.producer_payload(legal_name="Ada Lovelace")

    a.error_of(
        client.create_producer(payload, USER_ONLY_HEADERS), e.ERR_UNAUTHENTICATED, 401
    )
    a.error_of(
        client.create_producer(payload, ROLE_ONLY_HEADERS), e.ERR_UNAUTHENTICATED, 401
    )
    a.error_of(
        client.list_producers(NO_HEADERS, {"limit": 10, "offset": 0}),
        e.ERR_UNAUTHENTICATED,
        401,
    )
    a.error_of(client.create_producer({}, NO_HEADERS), e.ERR_UNAUTHENTICATED, 401)

    clock = a.data_of(client.set_clock("2026-08-10T00:00:00Z", CLOCK_ONLY_HEADERS))

    a.assert_instant_equals(clock["current_utc"], "2026-08-10T00:00:00Z", "current_utc")
    survivors, _meta = a.assert_pagination_meta(client.list_producers(ADMIN_HEADERS), 0)
    assert survivors == []


def test_a_producer_may_act_only_on_records_that_name_them(client):
    """Ownership is judged from the row, whether the id arrives by path or by body.

    PRD 2.1: "Concretely, a producer may only enroll themselves, withdraw their
    own enrollment, propose a series they own, create and attest and submit and
    withdraw their own program, request and cancel their own reservation, and
    confirm or release a crew assignment whose volunteer is themselves."

    PRD 2.1: "Where the acting `X-User-ID` is not the `producer_id` (or, for crew
    work, the `volunteer_producer_id`) that owns the target record, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD 2.8: "**Ownership (priority 6)** — `ERR_NOT_RESOURCE_OWNER`, 403. Applies
    to enrollment creation, enrollment withdrawal, program creation, attestation
    append, program submit, program withdraw, reservation creation, reservation
    cancellation, crew-assignment confirm and crew-assignment release."

    PRD 3.3: "A program is born with `review_status` `DRAFT`, `clearance_status`
    `INCOMPLETE`, `revision_round` at 0, `attestation_sequence_high` at 0, a null
    `reviewed_by_user_id`, a null `finding_category`, a null `finding_notes` and a
    null `withdrawn_reason`."

    Design: Corner/errors/corner_error_not_resource_owner_across_two_producers
    """
    owner = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    stranger = fx.setup_active_producer(client, legal_name="Grace Hopper")
    course = fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    program = fx.create_program(client, owner["id"], title="Riverside Weekly Recap")
    intruder = make_producer_headers(stranger["id"])

    a.error_of(
        client.append_attestation(
            program["id"], f.attestation_payload(owner["id"], "INDEMNIFICATION"), intruder
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    a.error_of(
        client.create_course_enrollment(
            f.enrollment_payload(owner["id"], course["id"]), intruder
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    a.error_of(
        client.create_program(
            f.program_payload(owner["id"], title="Impostor Show", runtime_seconds=900),
            intruder,
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    accepted = a.created_of(
        client.create_course_enrollment(
            f.enrollment_payload(owner["id"], course["id"]),
            make_producer_headers(owner["id"]),
        )
    )

    assert accepted["status"] == "ENROLLED"
    assert accepted["producer_id"] == owner["id"]
    assert fx.read_program(client, program["id"])["attestation_sequence_high"] == 0
    programs, _meta = a.assert_pagination_meta(client.list_programs(ADMIN_HEADERS), 1)
    a.assert_ids_equal(programs, [program["id"]])


def test_the_filer_may_not_forgive_and_the_submitter_may_not_decide(client):
    """Both duty rules read X-User-ID, so the correct role is no help at all.

    PRD 2.1: "Duties are segregated where money or sanction is at stake. A
    `FinanceOfficer` may not waive a damage assessment whose `filed_by_user_id`
    equals their own `X-User-ID`, and a `CenterAdmin` may not accept or return a
    funding period whose `submitted_by_user_id` equals their own `X-User-ID`;
    either attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 2.8: "**Segregation of duties (priority 7)** — `ERR_SEGREGATION_OF_DUTIES`,
    403. Applies to damage-assessment waiver and funding-period report decision."

    PRD 3.7: "A waiver leaves `assessed_repair_cents` at 0 and
    `suspension_points_assessed` at 0, records `waived_by_user_id` and
    `waiver_reason`, and increments the assessment's `version` by 1."

    PRD 3.8: "Submission recomputes `allocable_base_cents`, `admin_reserve_cents`,
    `capital_allocation_cents`, `operating_allocation_cents` and
    `total_program_funds_cents` in the pinned order above, records
    `submitted_by_user_id` as the acting `X-User-ID`, and increments the period's
    `version` by 1."

    PRD 3.8: "`SUBMITTED → ACCEPTED` records `decided_by_user_id` and freezes the
    period's figures permanently; `ACCEPTED` is terminal and no further revision is
    accepted."

    Design: Corner/errors/corner_error_segregation_of_duties_on_waiver_and_report_decision
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
    _resource, reservation = fx.setup_confirmed_reservation(
        client, producer["id"], resource,
        start_at="2026-08-20T10:00:00Z", end_at="2026-08-20T12:00:00Z",
    )
    fx.set_clock(client, "2026-08-20T10:00:00Z")
    fx.checkout_reservation(client, reservation["id"], condition_notes="Handover clean")
    fx.set_clock(client, "2026-08-20T12:00:00Z")
    a.data_of(
        client.return_reservation(
            reservation["id"],
            f.damaged_return_payload("MINOR", 40000, damage_notes="Pedestal column bent"),
            make_staff_headers(USER_FINANCE, ROLE_FACILITIES_MANAGER),
        )
    )
    assessments = fx.list_assessments_for(client, reservation["id"])
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment["filed_by_user_id"] == USER_FINANCE

    a.error_of(
        client.waive_damage_assessment(assessment["id"], f.waiver_payload(), FINANCE_HEADERS),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    waived = a.data_of(
        client.waive_damage_assessment(assessment["id"], f.waiver_payload(), FINANCE2_HEADERS)
    )

    assert waived["status"] == "WAIVED"
    assert waived["waived_by_user_id"] == USER_FINANCE_2
    assert waived["suspension_points_assessed"] == 0
    a.assert_cents(waived["assessed_repair_cents"], 0, "assessed_repair_cents")
    settled = fx.read_reservation(client, reservation["id"])
    assert settled["status"] == "SETTLED"
    a.assert_cents(settled["late_fee_cents"], 0, "late_fee_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    after = fx.read_producer(client, producer["id"])
    assert after["status"] == "ACTIVE"
    a.assert_producer_counters(after, held=0, forfeited_total=0, suspension_points=0)

    period = fx.open_funding_period(client, fiscal_year=2026, quarter=3)
    submitted = fx.submit_funding_report(
        client, period["id"], make_staff_headers(USER_ADMIN, ROLE_FINANCE_OFFICER)
    )
    assert submitted["report_status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == USER_ADMIN

    a.error_of(
        client.decide_funding_report(
            period["id"], f.report_decision_payload("ACCEPT"), ADMIN_HEADERS
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    decided = fx.decide_funding_report(client, period["id"], "ACCEPT", ADMIN2_HEADERS)

    assert decided["report_status"] == "ACCEPTED"
    assert decided["decided_by_user_id"] == USER_ADMIN_2
    assert decided["submitted_by_user_id"] == USER_ADMIN


def test_each_of_the_fourteen_reads_names_its_own_entity_when_the_id_is_unknown(client):
    """Fourteen distinct 404 codes, one per addressed entity, never a shared one.

    PRD 2.8: "**Path existence (priority 4)** — the addressed entity's own
    not-found error, 404. Applies to every operation with a path parameter. Path
    identifiers are resolved left to right and the leftmost missing segment decides
    which error is reported."

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/corner_error_not_found_catalog_is_entity_specific
    """
    expectations = [
        (client.get_producer("00000000-0000-4000-8000-000000000001", ADMIN_HEADERS),
         e.ERR_PRODUCER_NOT_FOUND),
        (client.get_training_course("00000000-0000-4000-8000-000000000002", ADMIN_HEADERS),
         e.ERR_TRAINING_COURSE_NOT_FOUND),
        (client.get_course_enrollment("00000000-0000-4000-8000-000000000003", ADMIN_HEADERS),
         e.ERR_COURSE_ENROLLMENT_NOT_FOUND),
        (client.get_series("00000000-0000-4000-8000-000000000004", ADMIN_HEADERS),
         e.ERR_SERIES_NOT_FOUND),
        (client.get_program("00000000-0000-4000-8000-000000000005", ADMIN_HEADERS),
         e.ERR_PROGRAM_NOT_FOUND),
        (client.get_attestation("00000000-0000-4000-8000-000000000006", ADMIN_HEADERS),
         e.ERR_ATTESTATION_NOT_FOUND),
        (client.get_channel("00000000-0000-4000-8000-000000000007", ADMIN_HEADERS),
         e.ERR_CHANNEL_NOT_FOUND),
        (client.get_playback_slot("00000000-0000-4000-8000-000000000008", ADMIN_HEADERS),
         e.ERR_PLAYBACK_SLOT_NOT_FOUND),
        (client.get_studio_resource("00000000-0000-4000-8000-000000000009", ADMIN_HEADERS),
         e.ERR_STUDIO_RESOURCE_NOT_FOUND),
        (client.get_reservation("00000000-0000-4000-8000-00000000000a", ADMIN_HEADERS),
         e.ERR_RESERVATION_NOT_FOUND),
        (client.get_damage_assessment("00000000-0000-4000-8000-00000000000b", ADMIN_HEADERS),
         e.ERR_DAMAGE_ASSESSMENT_NOT_FOUND),
        (client.get_crew_assignment("00000000-0000-4000-8000-00000000000c", ADMIN_HEADERS),
         e.ERR_CREW_ASSIGNMENT_NOT_FOUND),
        (client.get_funding_period("00000000-0000-4000-8000-00000000000d", ADMIN_HEADERS),
         e.ERR_FUNDING_PERIOD_NOT_FOUND),
        (client.get_archive_asset("00000000-0000-4000-8000-00000000000e", ADMIN_HEADERS),
         e.ERR_ARCHIVE_ASSET_NOT_FOUND),
    ]

    assert len(expectations) == 14
    for response, expected_error_id in expectations:
        body = a.error_of(response, expected_error_id, 404)
        assert isinstance(body["message"], str) and body["message"]


def test_one_duplicate_code_guards_four_keys_and_the_composite_needs_both_parts(client):
    """A repeat of any catalogue key is a 409, but a new quarter is a new key.

    PRD 2.8: "**Natural key uniqueness (priority 38)** — `ERR_DUPLICATE_NATURAL_KEY`,
    409. Applies to course creation, channel creation, studio-resource creation and
    funding-period creation."

    PRD 3.1: "A course carries a `course_code` — a catalog key unique across all
    courses, whose reuse is refused with `ERR_DUPLICATE_NATURAL_KEY` — plus a
    `title`, a `tier` of `BASIC`, `ADVANCED` or `LIVE`, a non-empty
    `grants_competency_codes` list drawn from the five equipment competency codes, a
    `seat_capacity` of at least 1, and a session window given by `session_start_at`
    and `session_end_at`, where the end must be strictly after the start."

    PRD 3.4: "A channel carries a `call_sign` unique across all channels — a reuse
    is `ERR_DUPLICATE_NATURAL_KEY` (409)"

    PRD 3.8: "The pair of `fiscal_year` and `quarter` is a natural key: a second
    period for the same quarter of the same year is refused with
    `ERR_DUPLICATE_NATURAL_KEY` (409)."

    Design: Corner/errors/corner_error_duplicate_natural_keys_across_four_entities
    """
    fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    fx.create_channel(client, call_sign="PATV1")
    fx.create_resource(client, resource_code="STUDIO-A")
    fx.open_funding_period(client, fiscal_year=2026, quarter=3)

    a.error_of(
        client.create_training_course(
            f.training_course_payload(
                course_code="TV-101",
                title="Studio Basics Repeat",
                tier="ADVANCED",
                grants_competency_codes=["AUDIO_BOARD"],
                seat_capacity=4,
                session_start_at="2026-09-05T17:00:00Z",
                session_end_at="2026-09-05T21:00:00Z",
            ),
            TRAINER_HEADERS,
        ),
        e.ERR_DUPLICATE_NATURAL_KEY,
        409,
    )
    a.error_of(
        client.create_channel(
            f.channel_payload(
                call_sign="PATV1",
                tier="EDUCATIONAL",
                daily_window_start_minute=600,
                daily_window_end_minute=1200,
                inter_program_buffer_seconds=60,
            ),
            ADMIN_HEADERS,
        ),
        e.ERR_DUPLICATE_NATURAL_KEY,
        409,
    )
    a.error_of(
        client.create_studio_resource(
            f.studio_resource_payload(
                resource_code="STUDIO-A",
                resource_class="EDIT_SUITE",
                required_competency_code="EDIT_SUITE",
                capacity_slots=2,
                turnaround_minutes=0,
                base_deposit_cents=1000,
                replacement_value_cents=50000,
            ),
            FACILITIES_HEADERS,
        ),
        e.ERR_DUPLICATE_NATURAL_KEY,
        409,
    )
    a.error_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=3,
                basis="CASH",
                gross_franchise_fee_cents=100,
                service_period_earned_cents=100,
                remittance_received_cents=100,
                capital_grant_cents=0,
            ),
            FINANCE_HEADERS,
        ),
        e.ERR_DUPLICATE_NATURAL_KEY,
        409,
    )

    fourth_quarter = a.created_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=4,
                basis="CASH",
                gross_franchise_fee_cents=100,
                service_period_earned_cents=100,
                remittance_received_cents=100,
                capital_grant_cents=0,
            ),
            FINANCE_HEADERS,
        )
    )

    assert fourth_quarter["report_status"] == "DRAFT"
    assert fourth_quarter["quarter"] == 4
    assert fourth_quarter["fiscal_year"] == 2026
    a.assert_pagination_meta(client.list_training_courses(TRAINER_HEADERS), 1)
    a.assert_pagination_meta(client.list_channels(SCHEDULER_HEADERS), 1)
    a.assert_pagination_meta(client.list_studio_resources(FACILITIES_HEADERS), 1)
    a.assert_pagination_meta(client.list_funding_periods(FINANCE_HEADERS), 2)


def test_the_grant_ceiling_bites_at_creation_and_the_base_rule_only_at_submission(client):
    """Both fiscal guards read the basis-selected base, not the gross fee.

    PRD 3.8: "Already at creation, and again on every restatement, the capital grant
    is sanity-checked against the money it sits on top of: a `capital_grant_cents`
    exceeding the basis-selected allocable base is refused with
    `ERR_CAPITAL_GRANT_EXCEEDS_BASE` (402)."

    PRD 3.8: "Step one selects the recognised amount: `allocable_base_cents` becomes
    `service_period_earned_cents` when the `basis` is `ACCRUAL`, and
    `remittance_received_cents` when the `basis` is `CASH`."

    PRD 3.8: "The basis-selected allocable base must be strictly positive; a period
    whose selected base is 0 or negative cannot be reported and is refused with
    `ERR_ALLOCABLE_BASE_NOT_POSITIVE` (402)."

    PRD 2.8: "**Capital grant within base (priority 42)** —
    `ERR_CAPITAL_GRANT_EXCEEDS_BASE`, 402. Applies to funding-period creation and
    funding-period restatement."

    Design: Corner/errors/corner_error_funding_guards_on_base_and_grant
    """
    a.error_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=1,
                basis="ACCRUAL",
                gross_franchise_fee_cents=9000000,
                service_period_earned_cents=5000000,
                remittance_received_cents=8000000,
                capital_grant_cents=5000001,
            ),
            FINANCE_HEADERS,
        ),
        e.ERR_CAPITAL_GRANT_EXCEEDS_BASE,
        402,
    )

    on_cash = a.created_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=1,
                basis="CASH",
                gross_franchise_fee_cents=9000000,
                service_period_earned_cents=5000000,
                remittance_received_cents=8000000,
                capital_grant_cents=5000001,
            ),
            FINANCE_HEADERS,
        )
    )

    assert on_cash["report_status"] == "DRAFT"
    a.assert_cents(on_cash["capital_grant_cents"], 5000001, "capital_grant_cents")
    a.assert_cents(on_cash["allocable_base_cents"], 0, "allocable_base_cents")

    zero_base = a.created_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=2,
                basis="ACCRUAL",
                gross_franchise_fee_cents=4000000,
                service_period_earned_cents=0,
                remittance_received_cents=4000000,
                capital_grant_cents=0,
            ),
            FINANCE_HEADERS,
        )
    )

    a.assert_cents(zero_base["allocable_base_cents"], 0, "allocable_base_cents")
    a.assert_common_fields(zero_base, expected_version=1)

    a.error_of(
        client.submit_funding_report(zero_base["id"], {}, FINANCE_HEADERS),
        e.ERR_ALLOCABLE_BASE_NOT_POSITIVE,
        402,
    )
    a.error_of(
        client.revise_funding_period(
            zero_base["id"],
            f.revise_funding_payload(zero_base["version"], capital_grant_cents=9999999),
            FINANCE_HEADERS,
        ),
        e.ERR_CAPITAL_GRANT_EXCEEDS_BASE,
        402,
    )

    untouched = fx.read_funding_period(client, zero_base["id"])
    assert untouched["report_status"] == "DRAFT"
    a.assert_cents(untouched["capital_grant_cents"], 0, "capital_grant_cents")
    assert untouched["revision_round"] == 0
    a.assert_field_absent_or_null(untouched, "submitted_by_user_id")


def test_the_two_session_guards_close_and_open_on_the_session_edges(client):
    """Withdrawal shuts as the session starts; attendance opens as it ends.

    PRD 3.1: "Withdrawal is the producer's escape hatch, available to the enrollee
    or to a `TrainingCoordinator`, and it is bounded by time: the `ENROLLED →
    WITHDRAWN` transition is permitted only while the logical clock is strictly
    before the course's `session_start_at`."

    PRD 3.1: "At or after the session's start instant the request is refused with
    `ERR_WITHDRAWAL_WINDOW_CLOSED` (409)."

    PRD 3.1: "The session must genuinely be over — the logical clock must have
    reached or passed `session_end_at`, and an earlier attempt is refused with
    `ERR_COURSE_SESSION_NOT_ENDED` (409)."

    PRD 3.1: "When `attended` is true the enrollment moves `ENROLLED → ATTENDED`
    and `attended_at` is stamped with the current logical instant."

    PRD 3.1: "A withdrawal releases the seat, lowering `enrolled_count` by 1."

    Design: Corner/errors/corner_error_course_temporal_guards_bracket_the_session
    """
    staying = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    leaving = fx.setup_active_producer(client, legal_name="Grace Hopper")
    course = fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    held = fx.enroll(client, staying["id"], course["id"])
    abandoned = fx.enroll(client, leaving["id"], course["id"])
    assert held["status"] == "ENROLLED"

    a.error_of(
        client.record_attendance(held["id"], f.attendance_payload(True), TRAINER_HEADERS),
        e.ERR_COURSE_SESSION_NOT_ENDED,
        409,
    )

    fx.set_clock(client, "2026-08-05T16:59:59Z")
    withdrawn = a.data_of(
        client.withdraw_enrollment(
            abandoned["id"], {}, make_producer_headers(leaving["id"])
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    fx.set_clock(client, "2026-08-05T17:00:00Z")
    a.error_of(
        client.withdraw_enrollment(held["id"], {}, make_producer_headers(staying["id"])),
        e.ERR_WITHDRAWAL_WINDOW_CLOSED,
        409,
    )
    a.error_of(
        client.record_attendance(held["id"], f.attendance_payload(True), TRAINER_HEADERS),
        e.ERR_COURSE_SESSION_NOT_ENDED,
        409,
    )

    fx.set_clock(client, "2026-08-05T21:00:00Z")
    attended = fx.mark_attended(client, held["id"], True)

    assert attended["status"] == "ATTENDED"
    a.assert_instant_equals(attended["attended_at"], "2026-08-05T21:00:00Z", "attended_at")
    after_course = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert after_course["enrolled_count"] == 1
    assert after_course["passed_count"] == 0


def test_the_scheduling_gates_answer_in_band_order_before_the_clock_is_consulted(client):
    """Approval, then clearance, then series state, and only then the airtime.

    PRD 3.3: "`clearance_status` must be `CLEARED`, otherwise
    `ERR_ATTESTATION_INCOMPLETE` (409) — this is the refusal a producer sees when a
    required kind is missing or when the latest attestation of a kind carries a
    superseded statement version."

    PRD 3.4: "Its `review_status` must be `APPROVED`, otherwise
    `ERR_PROGRAM_NOT_APPROVED` (409), and this state check runs ahead of every
    window and conflict check on the same request — a slot request that is both for
    an unapproved program and in a full window reports the approval failure."

    PRD 3.4: "Where a `series_id` is supplied, the named series must be `ACTIVE`,
    otherwise `ERR_SERIES_NOT_ACTIVE` (409)."

    PRD 3.2: "The request supplies `expected_series_version` and
    `hold_plan_slots_granted`; on success both `hold_plan_slots_granted` and
    `remaining_hold_slots` are set to the granted figure — a new plan replaces the
    old one outright rather than adding to it — and the series' `version` increments
    by 1."

    PRD 3.4: "Its `booking_type` becomes `SERIES_HOLD` when a `series_id` was
    supplied, in which case that series' `remaining_hold_slots` falls by 1;
    otherwise `booking_type` is `FIRST_COME`."

    PRD 3.5: "Four conditions gate the `SCHEDULED → AIRED` transition: the slot must
    be `SCHEDULED`; the logical clock must have reached or passed the slot's
    `start_at`, otherwise `ERR_AIRTIME_NOT_REACHED` (409); the program must still be
    `APPROVED`, otherwise `ERR_PROGRAM_NOT_APPROVED` (409); and the slot's
    `staffing_status` must be either `READY` or `NOT_REQUIRED` — an `UNDERSTAFFED`
    slot cannot air and the attempt is refused with `ERR_SLOT_UNDERSTAFFED` (409)."

    Design: Corner/errors/corner_error_program_and_series_gates_precede_scheduling
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(
        client,
        call_sign="PATV1",
        tier="PUBLIC",
        daily_window_start_minute=1080,
        daily_window_end_minute=1380,
        inter_program_buffer_seconds=120,
    )
    series = fx.propose_series(
        client, producer["id"], title="Riverside Council Recap",
        cadence="WEEKLY", first_air_date="2026-08-20T00:00:00Z",
    )
    assert series["status"] == "PROPOSED"
    assert series["remaining_hold_slots"] == 0
    program = fx.create_program(
        client, producer["id"], title="Riverside Weekly Recap", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    fx.append_attestation(client, program["id"], producer["id"], "INDEMNIFICATION")
    fx.append_attestation(client, program["id"], producer["id"], "COPYRIGHT_CLEARANCE")
    assert fx.read_program(client, program["id"])["clearance_status"] == "INCOMPLETE"
    producer_headers = make_producer_headers(producer["id"])

    a.error_of(
        client.submit_program(program["id"], {}, producer_headers),
        e.ERR_ATTESTATION_INCOMPLETE,
        409,
    )
    a.error_of(
        client.create_playback_slot(
            f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T18:00:00Z"),
            SCHEDULER_HEADERS,
        ),
        e.ERR_PROGRAM_NOT_APPROVED,
        409,
    )

    fx.append_attestation(client, program["id"], producer["id"], "CONTENT_POLICY")
    assert fx.read_program(client, program["id"])["clearance_status"] == "CLEARED"
    fx.submit_program(client, program["id"], producer["id"])
    fx.claim_review(client, program["id"])
    approved = fx.approve_program(client, program["id"])
    assert approved["review_status"] == "APPROVED"

    a.error_of(
        client.create_playback_slot(
            f.playback_slot_payload(
                channel["id"], program["id"], "2026-08-20T18:00:00Z", series_id=series["id"]
            ),
            SCHEDULER_HEADERS,
        ),
        e.ERR_SERIES_NOT_ACTIVE,
        409,
    )

    activated = fx.activate_series(client, series["id"])
    assert activated["status"] == "ACTIVE"
    planned = fx.grant_hold_plan(client, series["id"], 2)
    assert planned["hold_plan_slots_granted"] == 2
    assert planned["remaining_hold_slots"] == 2

    slot = a.created_of(
        client.create_playback_slot(
            f.playback_slot_payload(
                channel["id"], program["id"], "2026-08-20T18:00:00Z", series_id=series["id"]
            ),
            SCHEDULER_HEADERS,
        )
    )

    assert slot["booking_type"] == "SERIES_HOLD"
    assert slot["status"] == "SCHEDULED"
    assert fx.read_series(client, series["id"])["remaining_hold_slots"] == 1

    fx.set_clock(client, "2026-08-20T17:59:59Z")
    a.error_of(
        client.air_playback_slot(slot["id"], f.air_payload(500), SCHEDULER_HEADERS),
        e.ERR_AIRTIME_NOT_REACHED,
        409,
    )

    fx.set_clock(client, "2026-08-20T18:00:00Z")
    aired = fx.air_slot(client, slot["id"], 500)

    assert aired["status"] == "AIRED"
    a.assert_instant_equals(aired["aired_at"], "2026-08-20T18:00:00Z", "aired_at")
    assert aired["measured_households"] == 500


def test_the_tier_ladder_reads_passed_history_and_refuses_every_shortcut(client):
    """No basic pass, no advanced seat; and a failed advanced pass unlocks nothing.

    PRD 3.1: "The tier prerequisite reads: an `ADVANCED` course requires that the
    producer already holds a `PASSED` enrollment on some `BASIC` course, and a
    `LIVE` course requires a `PASSED` enrollment on some `ADVANCED` course; a
    `BASIC` course has no prerequisite."

    PRD 3.1: "A score of at least 80 drives `ATTENDED → PASSED`; a score below 80
    drives `ATTENDED → FAILED`."

    PRD 3.1: "Otherwise the level is read off the set of tiers the producer has
    passed: if that set contains all three of `BASIC`, `ADVANCED` and `LIVE`, the
    level is `LIVE`; otherwise, if it contains both `BASIC` and `ADVANCED`, the
    level is `ADVANCED`; otherwise, if it contains `BASIC`, the level is `BASIC`;
    otherwise `NONE`."

    PRD 3.1: "Only `PASSED` enrollments feed that tier set — `ENROLLED`, `ATTENDED`,
    `FAILED` and `WITHDRAWN` enrollments contribute nothing."

    Design: Corner/errors/corner_error_prerequisite_ladder_blocks_tier_skipping
    """
    producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    assert producer["certification_level"] == "NONE"
    basic = fx.publish_course(
        client, course_code="TV-101", tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"], seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z", session_end_at="2026-08-05T21:00:00Z",
    )
    advanced = fx.publish_course(
        client, course_code="TV-201", tier="ADVANCED",
        grants_competency_codes=["ENG_CAMERA", "AUDIO_BOARD"], seat_capacity=12,
        session_start_at="2026-08-12T17:00:00Z", session_end_at="2026-08-12T21:00:00Z",
    )
    live = fx.publish_course(
        client, course_code="TV-301", tier="LIVE",
        grants_competency_codes=["LIVE_SWITCHER"], seat_capacity=12,
        session_start_at="2026-08-19T17:00:00Z", session_end_at="2026-08-19T21:00:00Z",
    )
    headers = make_producer_headers(producer["id"])

    a.error_of(
        client.create_course_enrollment(
            f.enrollment_payload(producer["id"], advanced["id"]), headers
        ),
        e.ERR_PREREQUISITE_NOT_MET,
        422,
    )

    first = fx.enroll(client, producer["id"], basic["id"])
    fx.set_clock(client, "2026-08-06T00:00:00Z")
    fx.mark_attended(client, first["id"], True)
    passed = fx.grade(client, first["id"], 88)
    assert passed["status"] == "PASSED"
    assert fx.read_producer(client, producer["id"])["certification_level"] == "BASIC"

    a.error_of(
        client.create_course_enrollment(
            f.enrollment_payload(producer["id"], live["id"]), headers
        ),
        e.ERR_PREREQUISITE_NOT_MET,
        422,
    )

    second = fx.enroll(client, producer["id"], advanced["id"])
    fx.set_clock(client, "2026-08-13T00:00:00Z")
    fx.mark_attended(client, second["id"], True)
    failed = fx.grade(client, second["id"], 61)

    assert failed["status"] == "FAILED"
    assert failed["practical_score"] == 61
    assert fx.read_producer(client, producer["id"])["certification_level"] == "BASIC"

    a.error_of(
        client.create_course_enrollment(
            f.enrollment_payload(producer["id"], live["id"]), headers
        ),
        e.ERR_PREREQUISITE_NOT_MET,
        422,
    )


def test_only_retirement_is_blocked_by_an_open_booking(client):
    """Maintenance is accepted with a booking standing; retirement waits for zero.

    PRD 3.6: "Retirement is reachable from either `AVAILABLE` or `MAINTENANCE`, but
    only when the asset's `open_reservation_count` is exactly 0; a retirement
    attempt against an asset with any open reservation is refused with
    `ERR_RESOURCE_HAS_OPEN_RESERVATIONS` (409)."

    PRD 2.8: "**Resource has no open reservations (priority 20)** —
    `ERR_RESOURCE_HAS_OPEN_RESERVATIONS`, 409. Applies to a resource status change
    whose target `status` is `RETIRED`."

    PRD 2.9: "A studio resource's `open_reservation_count` is the count of its
    reservations whose status is `CONFIRMED`, `CHECKED_OUT` or `DAMAGE_REVIEW`."

    PRD 3.6: "`AVAILABLE → MAINTENANCE` and `MAINTENANCE → AVAILABLE` are both
    freely available and both simply record the reason and increment the asset's
    `version` by 1; existing reservations keep their own status across a maintenance
    move, but no `REQUESTED` reservation on the asset can be confirmed while it sits
    in `MAINTENANCE`."

    Design: Corner/errors/corner_error_retire_blocked_while_reservation_is_open
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
    _resource, reservation = fx.setup_confirmed_reservation(
        client, producer["id"], resource,
        start_at="2026-08-20T10:00:00Z", end_at="2026-08-20T12:00:00Z",
    )
    assert reservation["status"] == "CONFIRMED"
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1

    a.error_of(
        client.set_studio_resource_status(
            resource["id"],
            f.resource_status_payload("RETIRED", status_reason="End of service life"),
            FACILITIES_HEADERS,
        ),
        e.ERR_RESOURCE_HAS_OPEN_RESERVATIONS,
        409,
    )

    in_maintenance = fx.set_resource_status(
        client, resource["id"], "MAINTENANCE", status_reason="Interim lockout"
    )

    assert in_maintenance["status"] == "MAINTENANCE"
    assert in_maintenance["open_reservation_count"] == 1
    assert fx.read_reservation(client, reservation["id"])["status"] == "CONFIRMED"

    cancelled = a.data_of(
        client.cancel_reservation(
            reservation["id"],
            f.reservation_cancel_payload(cancellation_reason="Producer released the studio"),
            make_producer_headers(producer["id"]),
        )
    )

    assert cancelled["status"] == "CANCELLED"
    a.assert_cents(cancelled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=0)

    retired = fx.set_resource_status(
        client, resource["id"], "RETIRED", status_reason="End of service life"
    )

    assert retired["status"] == "RETIRED"
    assert retired["open_reservation_count"] == 0
    assert retired["status_reason"] == "End of service life"
