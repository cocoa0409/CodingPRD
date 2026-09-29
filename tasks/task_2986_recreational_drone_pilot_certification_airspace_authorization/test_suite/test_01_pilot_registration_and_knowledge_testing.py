"""Pilot enrolment, knowledge testing and the certificate a passing grade mints.

Every test builds its own pilot from an empty datastore: the harness restarts the
service before each test, so the logical clock always opens at its startup value.
"""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    NON_EXISTENT_UUID,
    OMIT,
    ApiErrorId,
    CertificationStatus,
    CurrencyBasis,
    KnowledgeTestStatus,
    OperatorCategory,
    PilotStatus,
    TestCode,
    add_calendar_months,
    assert_certification,
    assert_currency_projection,
    assert_instant_equals,
    assert_knowledge_test,
    assert_pilot,
    constants,
    factories,
    normalize_instant,
    set_clock,
    shift_days,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_pilot_registration_returns_the_declared_defaults(api, compliance_officer):
    """PRD §4: "Creation endpoints that bring a new resource into existence respond with HTTP 201; every other successful call responds with HTTP 200."
    PRD §3.1: "The new pilot lands in `UNCERTIFIED` with no certificate and no currency: `certified_at` is null, `currency_expires_at` is null, `suspension_reason` is null, and the three derived counters `risk_score`, `knowledge_attempt_count` and `open_waiver_count` all start at 0."
    PRD §3.1: "`currency_basis` is derived immediately from the declared category — `RECREATIONAL_BASIS` for a recreational operator and `COMMERCIAL_BASIS` for a commercial one — even though there is nothing yet for it to govern."
    PRD §3.2: "`last_completed_flight_end` itself is the greatest `actual_end` over that pilot's flights whose `status` is `COMPLETED`, breaking any tie on `created_at` ascending, and it is null while the pilot has completed no flight."
    PRD §2.5: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."
    PRD §2.4: "The server maintains a single logical UTC clock whose value at startup is exactly `2026-08-01T00:00:00Z`, and it must never fall back on real wall-clock time for any decision."

    Design: Corner/entities/pilot_creation_returns_declared_defaults_and_server_stamped_fields
    """
    payload = factories.pilot_payload(
        OperatorCategory.RECREATIONAL.value,
        full_name="Ada Ferrer",
        email="ada.ferrer@example.com",
    )

    pilot = validate_success(api.create_pilot(payload, headers=compliance_officer), 201)

    assert_pilot(
        pilot,
        full_name="Ada Ferrer",
        email="ada.ferrer@example.com",
        operator_category=OperatorCategory.RECREATIONAL.value,
        status=PilotStatus.UNCERTIFIED.value,
        currency_basis=CurrencyBasis.RECREATIONAL_BASIS.value,
        risk_score=0,
        knowledge_attempt_count=0,
        open_waiver_count=0,
        certified_at=None,
        currency_expires_at=None,
        last_completed_flight_end=None,
        suspension_reason=None,
        version=1,
    )
    assert_instant_equals(pilot["created_at"], CLOCK_STARTUP_UTC, "pilot.created_at")
    assert_instant_equals(pilot["updated_at"], CLOCK_STARTUP_UTC, "pilot.updated_at")


def test_pilot_read_back_matches_the_registration_response(api, compliance_officer):
    """PRD §3.1: "A pilot's `status` moves only through the states `UNCERTIFIED`, `KNOWLEDGE_PENDING`, `CERTIFIED`, `LAPSED`, `SUSPENDED` and `REVOKED`, and `REVOKED` is terminal."
    PRD §2.5: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/pilot_creation_returns_declared_defaults_and_server_stamped_fields
    """
    created = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value),
            headers=compliance_officer,
        ),
        201,
    )

    fetched = validate_success(api.get_pilot(created["id"], headers=compliance_officer))

    assert fetched["id"] == created["id"], (
        f"expected the same pilot row back, got {fetched['id']} for {created['id']}"
    )
    assert_pilot(
        fetched,
        status=PilotStatus.UNCERTIFIED.value,
        operator_category=OperatorCategory.RECREATIONAL.value,
        currency_basis=CurrencyBasis.RECREATIONAL_BASIS.value,
        risk_score=0,
        knowledge_attempt_count=0,
        open_waiver_count=0,
        version=1,
    )
    assert fetched["status"] == created["status"], (
        f"the read-back status must equal the created status, got {fetched['status']}"
    )


def test_reading_an_unknown_pilot_id_returns_the_pilot_not_found_code(api, compliance_officer):
    """PRD §2.6: "Identifiers embedded in a request path are resolved strictly left to right, and the first segment that fails to resolve determines the error."
    PRD §2.6: "Each entity has its own dedicated code, all of them HTTP 404: `ERR_PILOT_NOT_FOUND`, `ERR_KNOWLEDGE_TEST_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_SAFETY_CASE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` and `ERR_TFR_NOT_FOUND`."

    Design: Corner/entities/get_pilot_with_an_unknown_id_returns_pilot_not_found
    """
    validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value),
            headers=compliance_officer,
        ),
        201,
    )

    response = api.get_pilot(NON_EXISTENT_UUID, headers=compliance_officer)

    error = validate_error(response, ApiErrorId.PILOT_NOT_FOUND.value, 404)
    assert error["message"].strip(), "the error envelope must carry a human-readable message"


def test_an_unknown_pilot_lookup_leaves_the_existing_roster_readable(api, compliance_officer):
    """PRD §2.6: "Identifiers embedded in a request path are resolved strictly left to right, and the first segment that fails to resolve determines the error."
    PRD §2.11: "6. **Path existence**, on every endpoint carrying a path id: each id resolves, left to right, with the code naming the entity of the failing segment as catalogued in §2.6 — for example `ERR_PILOT_NOT_FOUND` (404)."

    Design: Corner/entities/get_pilot_with_an_unknown_id_returns_pilot_not_found
    """
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value),
            headers=compliance_officer,
        ),
        201,
    )

    validate_error(
        api.get_pilot(NON_EXISTENT_UUID, headers=compliance_officer),
        ApiErrorId.PILOT_NOT_FOUND.value,
        404,
    )

    survivor = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))
    assert_pilot(survivor, status=PilotStatus.UNCERTIFIED.value, version=1)
    records, meta = validate_paginated(api.list_pilots(headers=compliance_officer))
    assert meta["total_count"] == 1, (
        f"the failed lookup must not disturb the roster, got total_count {meta['total_count']}"
    )
    assert records[0]["id"] == pilot["id"], "the surviving row is the pilot that was registered"


def test_a_failing_grade_returns_the_pilot_to_uncertified_and_the_next_sitting_is_attempt_two(
    api, compliance_officer
):
    """PRD §3.1: "Each new sitting is stamped with an `attempt_number` equal to one plus the number of knowledge tests that already exist for that pilot in any state, so a pilot's first booking is attempt 1 and the numbering never reuses a value."
    PRD §3.1: "The sitting is created in `SCHEDULED` with `raw_score`, `passed` and `graded_at` all null."
    PRD §3.1: "A score at or above the mark writes `passed` true and moves the sitting from `SCHEDULED` to `PASSED`; a score below the mark writes `passed` false and moves it to `FAILED`."
    PRD §3.1: "A failure returns the pilot from `KNOWLEDGE_PENDING` to `UNCERTIFIED`, issues no certificate, and leaves `currency_expires_at` exactly as it was, which is what allows the `UNCERTIFIED → KNOWLEDGE_PENDING → UNCERTIFIED` cycle to repeat up to the three-attempt ceiling."
    PRD §3.1: "Either way `graded_at` is set to the current instant and both destinations are terminal, so a second grading attempt on the same sitting is refused with `ERR_TEST_ALREADY_GRADED`."

    Design: Corner/entities/knowledge_test_attempt_number_and_passed_are_computed_not_supplied
    """
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.COMMERCIAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    first = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, CLOCK_STARTUP_UTC
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert_knowledge_test(
        first,
        attempt_number=1,
        status=KnowledgeTestStatus.SCHEDULED.value,
        raw_score=None,
        passed=None,
        graded_at=None,
    )

    graded = validate_success(
        api.grade_knowledge_test(
            first["id"],
            factories.grade_payload(constants.COMMERCIAL_PASS_MARK - 1),
            headers=compliance_officer,
        )
    )

    assert_knowledge_test(
        graded,
        status=KnowledgeTestStatus.FAILED.value,
        passed=False,
        raw_score=constants.COMMERCIAL_PASS_MARK - 1,
        graded_at=CLOCK_STARTUP_UTC,
    )
    assert_pilot(
        validate_success(api.get_pilot(pilot["id"], headers=compliance_officer)),
        status=PilotStatus.UNCERTIFIED.value,
        knowledge_attempt_count=1,
        currency_expires_at=None,
        certified_at=None,
    )
    second = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, shift_days(CLOCK_STARTUP_UTC, 1)
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert_knowledge_test(
        second,
        attempt_number=2,
        status=KnowledgeTestStatus.SCHEDULED.value,
    )
    _, cert_meta = validate_paginated(
        api.list_certifications(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert cert_meta["total_count"] == 0, (
        f"a failing grade issues no certificate, got {cert_meta['total_count']}"
    )


def test_a_commercial_score_equal_to_the_pass_mark_passes_on_the_inclusive_comparison(
    api, compliance_officer
):
    """PRD §3.1: "The pass mark depends entirely on which exam was sat: the recreational knowledge test is graded against a mark of 100, and the commercial exam against a mark of 70."
    PRD §3.1: "The comparison is inclusive — a score equal to the mark passes."
    PRD §3.1: "Note that the pilot's `knowledge_attempt_count` counts something narrower — the number of that pilot's knowledge tests whose `status` is `PASSED` or `FAILED` — so booking a sitting leaves it unchanged and grading is what moves it."

    Design: Corner/entities/knowledge_test_attempt_number_and_passed_are_computed_not_supplied
    """
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.COMMERCIAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    first = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, CLOCK_STARTUP_UTC
            ),
            headers=compliance_officer,
        ),
        201,
    )
    validate_success(
        api.grade_knowledge_test(
            first["id"],
            factories.grade_payload(constants.COMMERCIAL_PASS_MARK - 1),
            headers=compliance_officer,
        )
    )
    second = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, shift_days(CLOCK_STARTUP_UTC, 1)
            ),
            headers=compliance_officer,
        ),
        201,
    )

    graded = validate_success(
        api.grade_knowledge_test(
            second["id"],
            factories.grade_payload(constants.COMMERCIAL_PASS_MARK),
            headers=compliance_officer,
        )
    )

    assert_knowledge_test(
        graded,
        status=KnowledgeTestStatus.PASSED.value,
        passed=True,
        raw_score=constants.COMMERCIAL_PASS_MARK,
        attempt_number=2,
    )
    assert_pilot(
        validate_success(api.get_pilot(pilot["id"], headers=compliance_officer)),
        status=PilotStatus.CERTIFIED.value,
        knowledge_attempt_count=2,
    )


def test_a_passing_grade_mints_a_certificate_with_a_server_generated_number(
    api, compliance_officer
):
    """PRD §3.1: "A certificate is minted in `ACTIVE` for the pilot, with `originating_test_id` pointing at the sitting that produced it, `category` mirroring the pilot's `operator_category` at the moment of issuance, `issued_at` set to the current instant, and a `certificate_number` formatted as the literal prefix `CERT-` followed by a six-digit zero-padded issuance sequence — `CERT-000001` for the first certificate the service ever issues, `CERT-000002` for the second, and so on in `created_at` ascending order across the whole service."
    PRD §3.1: "If the pilot already held a certificate in `ACTIVE`, that older certificate moves to `SUPERSEDED` and its `id` is written into the new certificate's `supersedes_certification_id`; a first issuance leaves `supersedes_certification_id` null."
    PRD §3.1: "The pass mark depends entirely on which exam was sat: the recreational knowledge test is graded against a mark of 100, and the commercial exam against a mark of 70."

    Design: Corner/entities/certification_number_and_issue_stamp_are_system_generated_on_pass
    """
    grading_instant = "2026-08-04T08:30:00Z"
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    sitting = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.TRUST_RECREATIONAL.value, shift_days(CLOCK_STARTUP_UTC, 1)
            ),
            headers=compliance_officer,
        ),
        201,
    )
    set_clock(api, grading_instant, headers=compliance_officer)

    graded = validate_success(
        api.grade_knowledge_test(
            sitting["id"],
            factories.grade_payload(constants.RECREATIONAL_PASS_MARK),
            headers=compliance_officer,
        )
    )

    assert_knowledge_test(graded, status=KnowledgeTestStatus.PASSED.value, passed=True)
    records, meta = validate_paginated(
        api.list_certifications(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"one passing grade mints exactly one certificate, got {meta['total_count']}"
    )
    assert_certification(
        records[0],
        pilot_id=pilot["id"],
        originating_test_id=sitting["id"],
        supersedes_certification_id=None,
        category=OperatorCategory.RECREATIONAL.value,
        status=CertificationStatus.ACTIVE.value,
        issued_at=grading_instant,
    )
    assert records[0]["certificate_number"] == "CERT-000001", (
        f"the first certificate the service issues is CERT-000001, got "
        f"{records[0]['certificate_number']!r}"
    )


def test_certificate_issue_stamp_is_the_grading_instant_not_the_sitting_date(
    api, compliance_officer
):
    """PRD §3.1: "Its `expires_at` is the issuance instant advanced by 24 calendar months, that is by two calendar years: the arithmetic is calendar-month arithmetic on the UTC instant, so the day-of-month is clamped down to the last day of the target month when the target month is shorter, and the time-of-day is preserved unchanged."
    PRD §3.1: "Nothing creates a certificate directly — issuance is always a consequence of a passing grade — so reading certificates individually or listing them, optionally narrowed by `pilot_id`, `originating_test_id`, `supersedes_certification_id` or `status`, is the only channel through which a client discovers a certificate's `id` and `certificate_number`."
    PRD §2.4: "The clock is monotonic and forward-only: a target instant that is at or before the present clock value is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409), so the supplied instant must be strictly later than the current one."

    Design: Corner/entities/certification_number_and_issue_stamp_are_system_generated_on_pass
    """
    scheduled_at = shift_days(CLOCK_STARTUP_UTC, 1)
    grading_instant = "2026-08-04T08:30:00Z"
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    sitting = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.TRUST_RECREATIONAL.value, scheduled_at
            ),
            headers=compliance_officer,
        ),
        201,
    )
    set_clock(api, grading_instant, headers=compliance_officer)
    validate_success(
        api.grade_knowledge_test(
            sitting["id"],
            factories.grade_payload(constants.RECREATIONAL_PASS_MARK),
            headers=compliance_officer,
        )
    )

    listed, _ = validate_paginated(
        api.list_certifications(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    certification = validate_success(
        api.get_certification(listed[0]["id"], headers=compliance_officer)
    )

    assert_certification(
        certification,
        issued_at=grading_instant,
        expires_at=add_calendar_months(grading_instant, constants.CERTIFICATE_VALIDITY_MONTHS),
        status=CertificationStatus.ACTIVE.value,
    )
    assert normalize_instant(certification["issued_at"]) != normalize_instant(scheduled_at), (
        "issued_at is the grading instant, never the sitting's scheduled_at"
    )
    assert_pilot(
        validate_success(api.get_pilot(pilot["id"], headers=compliance_officer)),
        status=PilotStatus.CERTIFIED.value,
        certified_at=grading_instant,
    )


def test_scheduling_a_sitting_under_an_unknown_pilot_returns_pilot_not_found(
    api, compliance_officer
):
    """PRD §2.6: "Identifiers embedded in a request path are resolved strictly left to right, and the first segment that fails to resolve determines the error."
    PRD §2.6: "A request that names a pilot and then a nested resource under that pilot fails with the pilot's not-found code before the nested identifier is examined at all."

    Design: Corner/entities/knowledge_test_creation_requires_an_existing_parent_pilot
    """
    survivor = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.COMMERCIAL.value),
            headers=compliance_officer,
        ),
        201,
    )

    response = api.schedule_knowledge_test(
        NON_EXISTENT_UUID,
        factories.knowledge_test_payload(TestCode.PART107_COMMERCIAL.value, CLOCK_STARTUP_UTC),
        headers=compliance_officer,
    )

    validate_error(response, ApiErrorId.PILOT_NOT_FOUND.value, 404)
    _, meta = validate_paginated(
        api.list_knowledge_tests(params={"pilot_id": survivor["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        f"the refused booking must persist no sitting, got total_count {meta['total_count']}"
    )
    assert_pilot(
        validate_success(api.get_pilot(survivor["id"], headers=compliance_officer)),
        status=PilotStatus.UNCERTIFIED.value,
    )


def test_an_unknown_parent_pilot_pre_empts_the_body_shape_check(api, compliance_officer):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "6. **Path existence**, on every endpoint carrying a path id: each id resolves, left to right, with the code naming the entity of the failing segment as catalogued in §2.6 — for example `ERR_PILOT_NOT_FOUND` (404)."
    PRD §2.11: "7. **Body shape**, on every endpoint: all required fields present, every enum value inside its declared member set, every integer inside its declared range, every string non-blank, arrays well-formed, and `limit` within 1 to 100 with `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/knowledge_test_creation_requires_an_existing_parent_pilot
    """
    response = api.schedule_knowledge_test(
        NON_EXISTENT_UUID,
        factories.knowledge_test_payload(test_code=OMIT, scheduled_at=CLOCK_STARTUP_UTC),
        headers=compliance_officer,
    )

    validate_error(response, ApiErrorId.PILOT_NOT_FOUND.value, 404)


def test_a_passing_grade_certifies_the_pilot_and_writes_the_commercial_currency_basis(
    api, compliance_officer
):
    """PRD §3.1: "Booking is admissible only from `UNCERTIFIED` or from `LAPSED` — a pilot who is already `KNOWLEDGE_PENDING`, already `CERTIFIED`, or `REVOKED` is refused with `ERR_PILOT_INVALID_STATE` — and it moves the pilot to `KNOWLEDGE_PENDING`."
    PRD §3.1: "The pilot then moves from `KNOWLEDGE_PENDING` to `CERTIFIED`, `certified_at` is set to the new certificate's `issued_at`, and `currency_expires_at` together with `currency_basis` are recomputed as described in §3.2."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."
    PRD §3.2: "Under `COMMERCIAL_BASIS`, which applies whenever the `operator_category` is `COMMERCIAL`, both constraints bite and the earlier of the two wins: the projected expiry is the base expiry when the base expiry is the earlier instant, and the recency expiry otherwise."

    Design: Corner/state_machines/a_passing_grade_executes_every_declared_side_effect_on_the_pilot
    """
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.COMMERCIAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    sitting = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, CLOCK_STARTUP_UTC
            ),
            headers=compliance_officer,
        ),
        201,
    )
    booked = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))
    assert_pilot(booked, status=PilotStatus.KNOWLEDGE_PENDING.value)

    graded = validate_success(
        api.grade_knowledge_test(
            sitting["id"], factories.grade_payload(91), headers=compliance_officer
        )
    )

    assert_knowledge_test(
        graded,
        status=KnowledgeTestStatus.PASSED.value,
        passed=True,
        graded_at=CLOCK_STARTUP_UTC,
    )
    base_expiry = add_calendar_months(CLOCK_STARTUP_UTC, constants.CERTIFICATE_VALIDITY_MONTHS)
    recency_expiry = shift_days(CLOCK_STARTUP_UTC, constants.RECENCY_WINDOW_DAYS)
    assert_pilot(
        validate_success(api.get_pilot(pilot["id"], headers=compliance_officer)),
        status=PilotStatus.CERTIFIED.value,
        certified_at=CLOCK_STARTUP_UTC,
        currency_basis=CurrencyBasis.COMMERCIAL_BASIS.value,
        currency_expires_at=min(base_expiry, recency_expiry),
        last_completed_flight_end=None,
    )


def test_a_passing_grade_mints_one_active_certificate_and_bumps_the_pilot_version(
    api, compliance_officer
):
    """PRD §3.2: "The **base expiry** is the pilot's single `ACTIVE` certificate's `issued_at` advanced by 24 calendar months, using the same calendar-month arithmetic and day clamping described in §3.1 — it is exactly the `expires_at` stored on that certificate."
    PRD §3.1: "`knowledge_attempt_count` is recomputed at this point too."
    PRD §2.5: "A mutation includes writing a derived field: when a completed flight pushes a pilot's `currency_expires_at` forward, or an approval bumps a zone's `reserved_slot_count`, that is a mutation of the pilot and of the zone respectively, and each one increments the version of the row it touched."

    Design: Corner/state_machines/a_passing_grade_executes_every_declared_side_effect_on_the_pilot
    """
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.COMMERCIAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    version_at_registration = pilot["version"]
    sitting = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, CLOCK_STARTUP_UTC
            ),
            headers=compliance_officer,
        ),
        201,
    )
    version_after_booking = validate_success(
        api.get_pilot(pilot["id"], headers=compliance_officer)
    )["version"]

    validate_success(
        api.grade_knowledge_test(
            sitting["id"], factories.grade_payload(91), headers=compliance_officer
        )
    )

    records, meta = validate_paginated(
        api.list_certifications(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"the passing grade mints exactly one certificate, got {meta['total_count']}"
    )
    assert_certification(
        records[0],
        status=CertificationStatus.ACTIVE.value,
        category=OperatorCategory.COMMERCIAL.value,
        issued_at=CLOCK_STARTUP_UTC,
        expires_at=add_calendar_months(
            CLOCK_STARTUP_UTC, constants.CERTIFICATE_VALIDITY_MONTHS
        ),
    )
    certified = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))
    assert version_after_booking > version_at_registration, (
        f"booking a sitting mutates the pilot, got {version_after_booking} after "
        f"{version_at_registration}"
    )
    assert certified["version"] > version_after_booking, (
        f"grading mutates the pilot again, got {certified['version']} after "
        f"{version_after_booking}"
    )
    assert_pilot(certified, knowledge_attempt_count=1)


def _sit_and_fail_three_recreational_exams(api, headers):
    """Book and fail three recreational sittings, one per day, keeping the clock at each sitting."""
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value), headers=headers
        ),
        201,
    )
    attempt_numbers = []
    for day, score in ((0, 50), (1, 80), (2, 99)):
        sitting_instant = shift_days(CLOCK_STARTUP_UTC, day)
        if day:
            set_clock(api, sitting_instant, headers=headers)
        sitting = validate_success(
            api.schedule_knowledge_test(
                pilot["id"],
                factories.knowledge_test_payload(
                    TestCode.TRUST_RECREATIONAL.value, sitting_instant
                ),
                headers=headers,
            ),
            201,
        )
        attempt_numbers.append(sitting["attempt_number"])
        graded = validate_success(
            api.grade_knowledge_test(
                sitting["id"], factories.grade_payload(score), headers=headers
            )
        )
        assert_knowledge_test(
            graded, status=KnowledgeTestStatus.FAILED.value, passed=False
        )
    return pilot, attempt_numbers


def test_a_fourth_sitting_inside_the_trailing_year_is_refused_by_the_attempt_cap(
    api, compliance_officer
):
    """PRD §3.1: "At most three sittings may be booked for one pilot inside any trailing 365 days, counted over the pilot's knowledge tests whose `scheduled_at` falls at or after the instant exactly 365 days before the current clock value and at or before the current clock value itself, in any state."
    PRD §3.1: "A fourth booking inside that window is refused with `ERR_TEST_ATTEMPT_LIMIT`."
    PRD §2.11: "34. **Attempt cap**, on `POST /drone-ops/pilots/{id}/knowledge-tests` only: the pilot has fewer than three knowledge tests whose `scheduled_at` falls in the trailing 365 days of the current instant — otherwise `ERR_TEST_ATTEMPT_LIMIT` (409)."

    Design: Corner/errors/knowledge_test_attempt_cap_is_triggerable_and_the_trailing_window_releases_it
    """
    pilot, attempt_numbers = _sit_and_fail_three_recreational_exams(api, compliance_officer)
    assert attempt_numbers == [1, 2, 3], (
        f"three consecutive sittings number 1, 2, 3, got {attempt_numbers}"
    )

    refused = api.schedule_knowledge_test(
        pilot["id"],
        factories.knowledge_test_payload(
            TestCode.TRUST_RECREATIONAL.value, shift_days(CLOCK_STARTUP_UTC, 2)
        ),
        headers=compliance_officer,
    )

    validate_error(refused, ApiErrorId.TEST_ATTEMPT_LIMIT.value, 409)
    sittings, meta = validate_paginated(
        api.list_knowledge_tests(
            params={"pilot_id": pilot["id"]}, headers=compliance_officer
        )
    )
    assert meta["total_count"] == 3, (
        f"the refused booking creates no sitting, got {meta['total_count']} rows"
    )
    assert all(s["status"] == KnowledgeTestStatus.FAILED.value for s in sittings), (
        f"all three rationed sittings stay failed, got {[s['status'] for s in sittings]}"
    )
    assert_pilot(
        validate_success(api.get_pilot(pilot["id"], headers=compliance_officer)),
        status=PilotStatus.UNCERTIFIED.value,
        knowledge_attempt_count=3,
    )


def test_the_trailing_window_releases_the_cap_once_the_oldest_sitting_falls_out(
    api, compliance_officer
):
    """PRD §3.1: "At most three sittings may be booked for one pilot inside any trailing 365 days, counted over the pilot's knowledge tests whose `scheduled_at` falls at or after the instant exactly 365 days before the current clock value and at or before the current clock value itself, in any state."
    PRD §3.1: "Each new sitting is stamped with an `attempt_number` equal to one plus the number of knowledge tests that already exist for that pilot in any state, so a pilot's first booking is attempt 1 and the numbering never reuses a value."
    PRD §3.1: "The sitting is created in `SCHEDULED` with `raw_score`, `passed` and `graded_at` all null."

    Design: Corner/errors/knowledge_test_attempt_cap_is_triggerable_and_the_trailing_window_releases_it
    """
    pilot, _ = _sit_and_fail_three_recreational_exams(api, compliance_officer)
    oldest_scheduled_at = CLOCK_STARTUP_UTC
    released_at = shift_days(shift_days(oldest_scheduled_at, 1), constants.TEST_ATTEMPT_WINDOW_DAYS)
    set_clock(api, released_at, headers=compliance_officer)

    fourth = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(TestCode.TRUST_RECREATIONAL.value, released_at),
            headers=compliance_officer,
        ),
        201,
    )

    assert_knowledge_test(
        fourth,
        pilot_id=pilot["id"],
        attempt_number=4,
        status=KnowledgeTestStatus.SCHEDULED.value,
        scheduled_at=released_at,
        raw_score=None,
        passed=None,
        graded_at=None,
    )
    _, meta = validate_paginated(
        api.list_knowledge_tests(
            params={"pilot_id": pilot["id"]}, headers=compliance_officer
        )
    )
    assert meta["total_count"] == 4, (
        f"the released booking is persisted, got {meta['total_count']} rows"
    )


LEAP_DAY_ISSUANCE = "2028-02-29T23:59:59Z"


def _certify_a_commercial_pilot_on_the_leap_day(api, headers):
    """Move the clock to the final second of a leap day and certify a commercial pilot there."""
    pilot = validate_success(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.COMMERCIAL.value), headers=headers
        ),
        201,
    )
    set_clock(api, LEAP_DAY_ISSUANCE, headers=headers)
    sitting = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, LEAP_DAY_ISSUANCE
            ),
            headers=headers,
        ),
        201,
    )
    validate_success(
        api.grade_knowledge_test(
            sitting["id"],
            factories.grade_payload(constants.COMMERCIAL_PASS_MARK),
            headers=headers,
        )
    )
    return pilot


def test_a_leap_day_issuance_clamps_the_expiry_to_the_last_day_of_the_target_month(
    api, compliance_officer
):
    """PRD §3.1: "Its `expires_at` is the issuance instant advanced by 24 calendar months, that is by two calendar years: the arithmetic is calendar-month arithmetic on the UTC instant, so the day-of-month is clamped down to the last day of the target month when the target month is shorter, and the time-of-day is preserved unchanged."
    PRD §2.4: "All datetimes the service accepts and emits are ISO 8601 UTC instants at whole-second precision with a literal `Z` suffix and no fractional part — for example `2026-06-13T12:00:00Z`."

    Design: Corner/calculations/certification_dates_clamp_the_calendar_month_and_stay_whole_second_utc
    """
    pilot = _certify_a_commercial_pilot_on_the_leap_day(api, compliance_officer)

    records, meta = validate_paginated(
        api.list_certifications(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"the leap-day pass mints one certificate, got {meta['total_count']}"
    )
    certificate = validate_success(
        api.get_certification(records[0]["id"], headers=compliance_officer)
    )
    expected_expiry = add_calendar_months(
        LEAP_DAY_ISSUANCE, constants.CERTIFICATE_VALIDITY_MONTHS
    )
    assert_certification(
        certificate,
        status=CertificationStatus.ACTIVE.value,
        issued_at=LEAP_DAY_ISSUANCE,
        expires_at=expected_expiry,
    )
    assert certificate["expires_at"].startswith("2030-02-28T"), (
        f"the 29th clamps down to the 28th of the shorter target month, got "
        f"{certificate['expires_at']}"
    )
    assert certificate["expires_at"].endswith("T23:59:59Z"), (
        f"the time-of-day survives the clamp unchanged, got {certificate['expires_at']}"
    )
    for field in ("issued_at", "expires_at", "created_at", "updated_at"):
        value = certificate[field]
        assert normalize_instant(value) == value, (
            f"{field} is a whole-second UTC instant with a literal Z, got {value}"
        )


def test_the_leap_day_projection_reports_both_anchors_and_honours_the_recreational_override(
    api, compliance_officer
):
    """PRD §3.2: "The **base expiry** is the pilot's single `ACTIVE` certificate's `issued_at` advanced by 24 calendar months, using the same calendar-month arithmetic and day clamping described in §3.1 — it is exactly the `expires_at` stored on that certificate."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."
    PRD §3.2: "Under `COMMERCIAL_BASIS`, which applies whenever the `operator_category` is `COMMERCIAL`, both constraints bite and the earlier of the two wins: the projected expiry is the base expiry when the base expiry is the earlier instant, and the recency expiry otherwise."
    PRD §3.2: "Under `RECREATIONAL_BASIS`, which applies whenever the pilot's `operator_category` is `RECREATIONAL`, certificate validity alone governs: the projected expiry is the base expiry, and `last_completed_flight_end` is ignored entirely."
    PRD §3.2: "The projection accepts an optional `basis` selector naming either `RECREATIONAL_BASIS` or `COMMERCIAL_BASIS`, and when it is omitted the basis implied by the pilot's `operator_category` is used."

    Design: Corner/calculations/certification_dates_clamp_the_calendar_month_and_stay_whole_second_utc
    """
    pilot = _certify_a_commercial_pilot_on_the_leap_day(api, compliance_officer)
    base_expiry = add_calendar_months(
        LEAP_DAY_ISSUANCE, constants.CERTIFICATE_VALIDITY_MONTHS
    )
    recency_expiry = shift_days(LEAP_DAY_ISSUANCE, constants.RECENCY_WINDOW_DAYS)

    default_projection = validate_success(
        api.get_currency_projection(pilot["id"], headers=compliance_officer)
    )
    assert_currency_projection(
        default_projection,
        basis_applied=CurrencyBasis.COMMERCIAL_BASIS.value,
        base_expiry=base_expiry,
        recency_expiry=recency_expiry,
        projected_expires_at=recency_expiry,
        lapse_due=False,
    )
    for field in ("projected_expires_at", "base_expiry", "recency_expiry"):
        value = default_projection[field]
        assert normalize_instant(value) == value, (
            f"{field} is a whole-second UTC instant with a literal Z, got {value}"
        )

    override = validate_success(
        api.get_currency_projection(
            pilot["id"],
            params={"basis": CurrencyBasis.RECREATIONAL_BASIS.value},
            headers=compliance_officer,
        )
    )

    assert_currency_projection(
        override,
        basis_applied=CurrencyBasis.RECREATIONAL_BASIS.value,
        base_expiry=base_expiry,
        recency_expiry=recency_expiry,
        projected_expires_at=base_expiry,
        lapse_due=False,
    )
    assert_instant_equals(
        validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))[
            "currency_expires_at"
        ],
        recency_expiry,
        label="stored currency expiry after a leap-day commercial certification",
    )
