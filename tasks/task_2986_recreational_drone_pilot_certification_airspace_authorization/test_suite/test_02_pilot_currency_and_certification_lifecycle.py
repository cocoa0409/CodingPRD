"""Currency arithmetic, the projection read, and the lapse-and-recertify cycle.

Every test builds its own pilot from an empty datastore: the harness restarts the
service before each test, so the logical clock always opens at its startup value
and each timeline is driven strictly forward from there.
"""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    CertificationStatus,
    CurrencyBasis,
    FlightStatus,
    KnowledgeTestStatus,
    OperatorCategory,
    PilotStatus,
    TestCode,
    add_calendar_months,
    assert_certification,
    assert_currency_projection,
    assert_flight,
    assert_flight_summary,
    assert_instant_equals,
    assert_knowledge_test,
    assert_pilot,
    constants,
    factories,
    fixtures,
    parse_instant,
    set_clock,
    shift_days,
    validate_paginated,
    validate_success,
)

CERTIFICATION_INSTANT = CLOCK_STARTUP_UTC
BASE_EXPIRY = add_calendar_months(CERTIFICATION_INSTANT, constants.CERTIFICATE_VALIDITY_MONTHS)
ISSUANCE_RECENCY_EXPIRY = shift_days(CERTIFICATION_INSTANT, constants.RECENCY_WINDOW_DAYS)

FLIGHT_START = "2026-09-15T11:00:00Z"
FLIGHT_END = "2026-09-15T12:00:00Z"
FLIGHT_RECENCY_EXPIRY = shift_days(FLIGHT_END, constants.RECENCY_WINDOW_DAYS)
PROJECTION_INSTANT = "2026-10-01T00:00:00Z"


def _commercial_pilot_with_one_completed_flight(api, headers):
    """Certify a commercial pilot, fly one clean recreational-category sortie, then park the clock."""
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=1200
    )
    zone = fixtures.create_zone(api, class_ceiling_ft=400, max_concurrent_authorizations=2)
    set_clock(api, FLIGHT_START, headers=headers)
    flight = fixtures.create_completed_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        FLIGHT_START,
        FLIGHT_END,
        max_altitude_reached_ft=320,
        actual_end=FLIGHT_END,
        planned_max_altitude_ft=350,
    )
    set_clock(api, PROJECTION_INSTANT, headers=headers)
    return pilot, flight


def test_the_two_currency_bases_diverge_on_byte_identical_stored_data(api, compliance_officer):
    """PRD §3.2: "The **base expiry** is the pilot's single `ACTIVE` certificate's `issued_at` advanced by 24 calendar months, using the same calendar-month arithmetic and day clamping described in §3.1 — it is exactly the `expires_at` stored on that certificate."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."
    PRD §3.2: "Under `RECREATIONAL_BASIS`, which applies whenever the pilot's `operator_category` is `RECREATIONAL`, certificate validity alone governs: the projected expiry is the base expiry, and `last_completed_flight_end` is ignored entirely."
    PRD §3.2: "Under `COMMERCIAL_BASIS`, which applies whenever the `operator_category` is `COMMERCIAL`, both constraints bite and the earlier of the two wins: the projected expiry is the base expiry when the base expiry is the earlier instant, and the recency expiry otherwise."
    PRD §3.2: "The response reports `projected_expires_at` (the instant the chosen variant yields), `basis_applied` (the basis actually used, as a string), `base_expiry` and `recency_expiry` (both anchors, reported regardless of which one the chosen basis consults), `days_remaining` (the whole number of days from the current instant to `projected_expires_at`, discarding any part-day remainder, and negative when the projection already lies in the past), and `lapse_due` (true exactly when `projected_expires_at` is at or before the current instant)."

    Design: Difficulty/dual_variant_calc/currency_expiry_recreational_basis_versus_commercial_basis
    """
    pilot, _ = _commercial_pilot_with_one_completed_flight(api, compliance_officer)

    recreational = validate_success(
        api.get_currency_projection(
            pilot["id"],
            params={"basis": CurrencyBasis.RECREATIONAL_BASIS.value},
            headers=compliance_officer,
        )
    )
    commercial = validate_success(
        api.get_currency_projection(
            pilot["id"],
            params={"basis": CurrencyBasis.COMMERCIAL_BASIS.value},
            headers=compliance_officer,
        )
    )

    assert_currency_projection(
        recreational,
        basis_applied=CurrencyBasis.RECREATIONAL_BASIS.value,
        base_expiry=BASE_EXPIRY,
        recency_expiry=FLIGHT_RECENCY_EXPIRY,
        projected_expires_at=BASE_EXPIRY,
        lapse_due=False,
    )
    assert_currency_projection(
        commercial,
        basis_applied=CurrencyBasis.COMMERCIAL_BASIS.value,
        base_expiry=BASE_EXPIRY,
        recency_expiry=FLIGHT_RECENCY_EXPIRY,
        projected_expires_at=FLIGHT_RECENCY_EXPIRY,
        lapse_due=False,
    )
    assert_instant_equals(
        recreational["base_expiry"],
        commercial["base_expiry"],
        label="base expiry reported under both bases",
    )
    assert_instant_equals(
        recreational["recency_expiry"],
        commercial["recency_expiry"],
        label="recency expiry reported under both bases",
    )
    assert parse_instant(recreational["projected_expires_at"]) != parse_instant(
        commercial["projected_expires_at"]
    ), (
        "the same stored data must project two different instants, got "
        f"{recreational['projected_expires_at']} under both bases"
    )


def test_the_stored_currency_ledger_follows_the_operator_category(api, compliance_officer):
    """PRD §3.2: "`last_completed_flight_end` itself is the greatest `actual_end` over that pilot's flights whose `status` is `COMPLETED`, breaking any tie on `created_at` ascending, and it is null while the pilot has completed no flight."
    PRD §3.2: "The projection accepts an optional `basis` selector naming either `RECREATIONAL_BASIS` or `COMMERCIAL_BASIS`, and when it is omitted the basis implied by the pilot's `operator_category` is used."
    PRD §3.2: "This read never mutates the pilot: it is the diagnostic that lets an operator see both variants over the same stored data."
    PRD §3.7: "The pilot's `last_completed_flight_end` is set to the new `actual_end`, `currency_expires_at` is recomputed (§3.2), `risk_score` is recomputed (§3.9) and the pilot's `version` is incremented; when the recomputed `risk_score` reaches 70 the pilot is suspended on the spot and the depth-four suspension cascade of §2.8 fires from inside the completion."

    Design: Difficulty/dual_variant_calc/currency_expiry_recreational_basis_versus_commercial_basis
    """
    pilot, _ = _commercial_pilot_with_one_completed_flight(api, compliance_officer)
    before = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))

    defaulted = validate_success(
        api.get_currency_projection(pilot["id"], headers=compliance_officer)
    )
    validate_success(
        api.get_currency_projection(
            pilot["id"],
            params={"basis": CurrencyBasis.RECREATIONAL_BASIS.value},
            headers=compliance_officer,
        )
    )
    after = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))

    assert_currency_projection(
        defaulted,
        basis_applied=CurrencyBasis.COMMERCIAL_BASIS.value,
        projected_expires_at=FLIGHT_RECENCY_EXPIRY,
    )
    assert_pilot(
        after,
        status=PilotStatus.CERTIFIED.value,
        currency_basis=CurrencyBasis.COMMERCIAL_BASIS.value,
        currency_expires_at=FLIGHT_RECENCY_EXPIRY,
        last_completed_flight_end=FLIGHT_END,
        version=before["version"],
    )


LAPSE_INSTANT = shift_days(ISSUANCE_RECENCY_EXPIRY, 1)
SECOND_BASE_EXPIRY = add_calendar_months(LAPSE_INSTANT, constants.CERTIFICATE_VALIDITY_MONTHS)
SECOND_RECENCY_EXPIRY = shift_days(LAPSE_INSTANT, constants.RECENCY_WINDOW_DAYS)


def _walk_the_lapse_and_recertify_cycle(api, headers):
    """Certify, let currency run out, review into LAPSED, then pass a second exam."""
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    first_certificates, _ = validate_paginated(
        api.list_certifications(params={"pilot_id": pilot["id"]}, headers=headers)
    )
    walk = {
        "pilot_id": pilot["id"],
        "first_certificate_id": first_certificates[0]["id"],
        "first_expiry": pilot["currency_expires_at"],
        "first_status": pilot["status"],
        "first_version": pilot["version"],
    }
    set_clock(api, LAPSE_INSTANT, headers=headers)
    walk["reviewed"] = validate_success(
        api.currency_review(pilot["id"], headers=headers)
    )
    walk["second_sitting"] = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, LAPSE_INSTANT
            ),
            headers=headers,
        ),
        201,
    )
    walk["status_while_booked"] = validate_success(
        api.get_pilot(pilot["id"], headers=headers)
    )["status"]
    walk["graded"] = validate_success(
        api.grade_knowledge_test(
            walk["second_sitting"]["id"], factories.grade_payload(75), headers=headers
        )
    )
    walk["final"] = validate_success(api.get_pilot(pilot["id"], headers=headers))
    return walk


def test_a_lapse_and_a_fresh_pass_re_enter_certified_with_a_later_expiry(
    api, compliance_officer
):
    """PRD §3.2: "A `ComplianceOfficer` runs a **currency review** on a pilot to re-settle these values against the clock. The review rewrites `currency_expires_at` and `currency_basis`; moves the pilot from `CERTIFIED` to `LAPSED` when the recomputed expiry is at or before the current instant; moves the pilot from `LAPSED` back to `CERTIFIED` when the recomputed expiry is strictly after the current instant, which happens once a fresh certificate or a fresh completed flight has pushed the anchor forward; transitions any of that pilot's certificates in `ACTIVE` whose `expires_at` is at or before the current instant to `EXPIRED`; and recomputes `risk_score`."
    PRD §3.1: "Booking is admissible only from `UNCERTIFIED` or from `LAPSED` — a pilot who is already `KNOWLEDGE_PENDING`, already `CERTIFIED`, or `REVOKED` is refused with `ERR_PILOT_INVALID_STATE` — and it moves the pilot to `KNOWLEDGE_PENDING`."
    PRD §3.1: "A score at or above the mark writes `passed` true and moves the sitting from `SCHEDULED` to `PASSED`; a score below the mark writes `passed` false and moves it to `FAILED`."
    PRD §3.1: "The pilot then moves from `KNOWLEDGE_PENDING` to `CERTIFIED`, `certified_at` is set to the new certificate's `issued_at`, and `currency_expires_at` together with `currency_basis` are recomputed as described in §3.2."

    Design: Difficulty/non_linear_state_machine/pilot_certified_lapsed_recertified_cycle_revisits_certified
    """
    walk = _walk_the_lapse_and_recertify_cycle(api, compliance_officer)

    assert walk["first_status"] == PilotStatus.CERTIFIED.value, (
        f"the first occupancy of CERTIFIED, got {walk['first_status']}"
    )
    assert_instant_equals(
        walk["first_expiry"],
        ISSUANCE_RECENCY_EXPIRY,
        label="currency expiry at the first certification",
    )
    assert_pilot(walk["reviewed"], status=PilotStatus.LAPSED.value)
    assert walk["status_while_booked"] == PilotStatus.KNOWLEDGE_PENDING.value, (
        "booking from LAPSED must move the pilot to KNOWLEDGE_PENDING, got "
        f"{walk['status_while_booked']}"
    )
    assert_knowledge_test(
        walk["graded"],
        status=KnowledgeTestStatus.PASSED.value,
        passed=True,
        attempt_number=2,
    )
    assert_pilot(
        walk["final"],
        status=PilotStatus.CERTIFIED.value,
        certified_at=LAPSE_INSTANT,
        currency_basis=CurrencyBasis.COMMERCIAL_BASIS.value,
        currency_expires_at=min(SECOND_BASE_EXPIRY, SECOND_RECENCY_EXPIRY),
    )
    assert parse_instant(walk["final"]["currency_expires_at"]) > parse_instant(
        walk["first_expiry"]
    ), (
        "the second occupancy of CERTIFIED must carry a later expiry, got "
        f"{walk['final']['currency_expires_at']} against {walk['first_expiry']}"
    )


def test_the_older_certificate_is_superseded_rather_than_expired_by_the_second_pass(
    api, compliance_officer
):
    """PRD §3.1: "If the pilot already held a certificate in `ACTIVE`, that older certificate moves to `SUPERSEDED` and its `id` is written into the new certificate's `supersedes_certification_id`; a first issuance leaves `supersedes_certification_id` null."
    PRD §3.1: "A certificate's own `status` moves through `ACTIVE`, `SUPERSEDED`, `EXPIRED` and `REVOKED`, with `REVOKED` terminal."
    PRD §3.1: "Note that the pilot's `knowledge_attempt_count` counts something narrower — the number of that pilot's knowledge tests whose `status` is `PASSED` or `FAILED` — so booking a sitting leaves it unchanged and grading is what moves it."
    PRD §3.2: "A `ComplianceOfficer` runs a **currency review** on a pilot to re-settle these values against the clock. The review rewrites `currency_expires_at` and `currency_basis`; moves the pilot from `CERTIFIED` to `LAPSED` when the recomputed expiry is at or before the current instant; moves the pilot from `LAPSED` back to `CERTIFIED` when the recomputed expiry is strictly after the current instant, which happens once a fresh certificate or a fresh completed flight has pushed the anchor forward; transitions any of that pilot's certificates in `ACTIVE` whose `expires_at` is at or before the current instant to `EXPIRED`; and recomputes `risk_score`."

    Design: Difficulty/non_linear_state_machine/pilot_certified_lapsed_recertified_cycle_revisits_certified
    """
    walk = _walk_the_lapse_and_recertify_cycle(api, compliance_officer)
    older = validate_success(
        api.get_certification(walk["first_certificate_id"], headers=compliance_officer)
    )

    assert_certification(
        older,
        status=CertificationStatus.SUPERSEDED.value,
        issued_at=CERTIFICATION_INSTANT,
        expires_at=BASE_EXPIRY,
        supersedes_certification_id=None,
    )
    assert parse_instant(older["expires_at"]) > parse_instant(LAPSE_INSTANT), (
        "the demoted certificate's own validity has not run out, so nothing may expire "
        f"it: expires_at {older['expires_at']} against the clock at {LAPSE_INSTANT}"
    )

    records, meta = validate_paginated(
        api.list_certifications(
            params={"pilot_id": walk["pilot_id"]}, headers=compliance_officer
        )
    )
    assert meta["total_count"] == 2, (
        f"two passes leave two certificate rows, got {meta['total_count']}"
    )
    newer = [c for c in records if c["id"] != walk["first_certificate_id"]]
    assert len(newer) == 1, (
        f"exactly one certificate other than the demoted one, got {len(newer)}"
    )
    assert_certification(
        newer[0],
        status=CertificationStatus.ACTIVE.value,
        issued_at=LAPSE_INSTANT,
        expires_at=SECOND_BASE_EXPIRY,
        supersedes_certification_id=walk["first_certificate_id"],
        originating_test_id=walk["second_sitting"]["id"],
    )
    assert_pilot(
        walk["final"],
        knowledge_attempt_count=2,
        status=PilotStatus.CERTIFIED.value,
        suspension_reason=None,
    )
    observed = [
        walk["first_status"],
        walk["reviewed"]["status"],
        walk["status_while_booked"],
        walk["final"]["status"],
    ]
    assert PilotStatus.SUSPENDED.value not in observed, (
        f"the recertification path never suspends the pilot, saw {observed}"
    )
    assert PilotStatus.REVOKED.value not in observed, (
        f"the recertification path never revokes the pilot, saw {observed}"
    )


FIRST_READ_INSTANT = shift_days(ISSUANCE_RECENCY_EXPIRY, -10)
SECOND_READ_INSTANT = shift_days(ISSUANCE_RECENCY_EXPIRY, 9)


def _whole_days_between(earlier, later):
    """The whole-day gap the projection reports, part-day remainders discarded."""
    return (parse_instant(later) - parse_instant(earlier)).days


def test_the_projection_pins_days_remaining_and_flips_lapse_due_at_the_expiry(
    api, compliance_officer, pilot_headers
):
    """PRD §3.2: "Pilots and officers can also ask the service to project currency **without writing anything**."
    PRD §3.2: "The response reports `projected_expires_at` (the instant the chosen variant yields), `basis_applied` (the basis actually used, as a string), `base_expiry` and `recency_expiry` (both anchors, reported regardless of which one the chosen basis consults), `days_remaining` (the whole number of days from the current instant to `projected_expires_at`, discarding any part-day remainder, and negative when the projection already lies in the past), and `lapse_due` (true exactly when `projected_expires_at` is at or before the current instant)."
    PRD §3.2: "Under `RECREATIONAL_BASIS`, which applies whenever the pilot's `operator_category` is `RECREATIONAL`, certificate validity alone governs: the projected expiry is the base expiry, and `last_completed_flight_end` is ignored entirely."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."

    Design: Corner/endpoints/currency_projection_reports_without_writing_anything
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    owner = pilot_headers(pilot["id"])
    assert_pilot(
        pilot,
        currency_basis=CurrencyBasis.COMMERCIAL_BASIS.value,
        currency_expires_at=ISSUANCE_RECENCY_EXPIRY,
        last_completed_flight_end=None,
    )

    set_clock(api, FIRST_READ_INSTANT, headers=compliance_officer)
    early = validate_success(api.get_currency_projection(pilot["id"], headers=owner))
    set_clock(api, SECOND_READ_INSTANT, headers=compliance_officer)
    late = validate_success(api.get_currency_projection(pilot["id"], headers=owner))
    override = validate_success(
        api.get_currency_projection(
            pilot["id"],
            params={"basis": CurrencyBasis.RECREATIONAL_BASIS.value},
            headers=compliance_officer,
        )
    )

    assert_currency_projection(
        early,
        basis_applied=CurrencyBasis.COMMERCIAL_BASIS.value,
        base_expiry=BASE_EXPIRY,
        recency_expiry=ISSUANCE_RECENCY_EXPIRY,
        projected_expires_at=ISSUANCE_RECENCY_EXPIRY,
        days_remaining=_whole_days_between(FIRST_READ_INSTANT, ISSUANCE_RECENCY_EXPIRY),
        lapse_due=False,
    )
    assert_currency_projection(
        late,
        basis_applied=CurrencyBasis.COMMERCIAL_BASIS.value,
        projected_expires_at=ISSUANCE_RECENCY_EXPIRY,
        days_remaining=_whole_days_between(SECOND_READ_INSTANT, ISSUANCE_RECENCY_EXPIRY),
        lapse_due=True,
    )
    assert late["days_remaining"] < 0, (
        f"a projection already in the past reports a negative gap, got {late['days_remaining']}"
    )
    assert_currency_projection(
        override,
        basis_applied=CurrencyBasis.RECREATIONAL_BASIS.value,
        base_expiry=BASE_EXPIRY,
        recency_expiry=ISSUANCE_RECENCY_EXPIRY,
        projected_expires_at=BASE_EXPIRY,
        days_remaining=_whole_days_between(SECOND_READ_INSTANT, BASE_EXPIRY),
        lapse_due=False,
    )


def test_three_projections_write_nothing_and_only_the_review_lapses_the_pilot(
    api, compliance_officer
):
    """PRD §3.2: "This read never mutates the pilot: it is the diagnostic that lets an operator see both variants over the same stored data."
    PRD §3.2: "Currency is recomputed and written at four moments: when a passing grade issues a certificate, when a currency review is run, when a flight is completed (a fresh `actual_end` moves the recency anchor forward), and, read-only, when a client asks for a projection."
    PRD §3.2: "A `ComplianceOfficer` runs a **currency review** on a pilot to re-settle these values against the clock. The review rewrites `currency_expires_at` and `currency_basis`; moves the pilot from `CERTIFIED` to `LAPSED` when the recomputed expiry is at or before the current instant; moves the pilot from `LAPSED` back to `CERTIFIED` when the recomputed expiry is strictly after the current instant, which happens once a fresh certificate or a fresh completed flight has pushed the anchor forward; transitions any of that pilot's certificates in `ACTIVE` whose `expires_at` is at or before the current instant to `EXPIRED`; and recomputes `risk_score`."
    PRD §2.5: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/currency_projection_reports_without_writing_anything
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    before = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))

    set_clock(api, FIRST_READ_INSTANT, headers=compliance_officer)
    validate_success(api.get_currency_projection(pilot["id"], headers=compliance_officer))
    set_clock(api, SECOND_READ_INSTANT, headers=compliance_officer)
    validate_success(api.get_currency_projection(pilot["id"], headers=compliance_officer))
    validate_success(
        api.get_currency_projection(
            pilot["id"],
            params={"basis": CurrencyBasis.RECREATIONAL_BASIS.value},
            headers=compliance_officer,
        )
    )
    after = validate_success(api.get_pilot(pilot["id"], headers=compliance_officer))

    assert_pilot(
        after,
        status=PilotStatus.CERTIFIED.value,
        currency_expires_at=ISSUANCE_RECENCY_EXPIRY,
        currency_basis=CurrencyBasis.COMMERCIAL_BASIS.value,
        version=before["version"],
    )
    assert_instant_equals(
        after["updated_at"],
        before["updated_at"],
        label="pilot updated_at across three projection reads",
    )

    reviewed = validate_success(api.currency_review(pilot["id"], headers=compliance_officer))

    assert_pilot(reviewed, status=PilotStatus.LAPSED.value)
    assert reviewed["version"] > before["version"], (
        "only the explicit review mutates the pilot, got version "
        f"{reviewed['version']} against {before['version']}"
    )


LEDGER_LAUNCH_INSTANT = "2026-08-02T09:00:00Z"
LEDGER_PLANNED_END = "2026-08-02T10:00:00Z"
LEDGER_COMPLETION_INSTANT = "2026-08-02T10:07:00Z"
LEDGER_SUMMARY_INSTANT = "2026-08-02T10:30:00Z"
LEDGER_LOGGED_MINUTES = 67
LEDGER_RECENCY_EXPIRY = shift_days(LEDGER_COMPLETION_INSTANT, constants.RECENCY_WINDOW_DAYS)


def _fly_one_clean_sortie_for_a_commercial_pilot(api, headers, owner_builder):
    """Certify, clear, launch and complete a single clean flight, reporting the before state."""
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    owner = owner_builder(pilot["id"])
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(api, class_ceiling_ft=400, max_concurrent_authorizations=2)
    flight = fixtures.create_cleared_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        LEDGER_LAUNCH_INSTANT,
        LEDGER_PLANNED_END,
        planned_max_altitude_ft=380,
    )
    set_clock(api, LEDGER_LAUNCH_INSTANT, headers=headers)
    launched = validate_success(api.launch_flight(flight["id"], headers=owner))
    before = validate_success(api.get_pilot(pilot["id"], headers=headers))
    set_clock(api, LEDGER_COMPLETION_INSTANT, headers=headers)
    completed = validate_success(
        api.complete_flight(
            flight["id"],
            factories.completion_payload(LEDGER_COMPLETION_INSTANT, 300, False),
            headers=owner,
        )
    )
    after = validate_success(api.get_pilot(pilot["id"], headers=headers))
    return pilot, launched, before, completed, after


def test_completion_moves_the_recency_anchor_and_recomputes_the_currency_expiry(
    api, compliance_officer, pilot_headers
):
    """PRD §3.7: "On success the flight moves from `PREFLIGHT_CLEARED` to `IN_PROGRESS`, `actual_start` is set to the current instant, and the cited authorization moves from `APPROVED` to `ACTIVE`, keeping its zone slot."
    PRD §3.7: "The service writes all four fields, then computes `logged_minutes` as the whole minutes between `actual_start` and `actual_end`, discarding any part-minute remainder, and computes `altitude_exceedance` as true exactly when `max_altitude_reached_ft` is strictly greater than the flight's effective ceiling — the cited authorization's `granted_ceiling_ft` when the flight names one, and 400 feet otherwise."
    PRD §3.7: "The pilot's `last_completed_flight_end` is set to the new `actual_end`, `currency_expires_at` is recomputed (§3.2), `risk_score` is recomputed (§3.9) and the pilot's `version` is incremented; when the recomputed `risk_score` reaches 70 the pilot is suspended on the spot and the depth-four suspension cascade of §2.8 fires from inside the completion."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."

    Design: Corner/state_machines/flight_completion_syncs_the_pilots_derived_recency_ledger
    """
    _, launched, before, completed, after = _fly_one_clean_sortie_for_a_commercial_pilot(
        api, compliance_officer, pilot_headers
    )

    assert_flight(
        launched,
        status=FlightStatus.IN_PROGRESS.value,
        actual_start=LEDGER_LAUNCH_INSTANT,
    )
    assert_pilot(
        before,
        last_completed_flight_end=None,
        currency_expires_at=ISSUANCE_RECENCY_EXPIRY,
    )
    assert_flight(
        completed,
        status=FlightStatus.COMPLETED.value,
        actual_end=LEDGER_COMPLETION_INSTANT,
        logged_minutes=LEDGER_LOGGED_MINUTES,
        altitude_exceedance=False,
        max_altitude_reached_ft=300,
        incident_occurred=False,
    )
    assert_pilot(
        after,
        last_completed_flight_end=LEDGER_COMPLETION_INSTANT,
        currency_expires_at=min(BASE_EXPIRY, LEDGER_RECENCY_EXPIRY),
        currency_basis=CurrencyBasis.COMMERCIAL_BASIS.value,
        status=PilotStatus.CERTIFIED.value,
    )
    assert parse_instant(after["currency_expires_at"]) > parse_instant(
        before["currency_expires_at"]
    ), (
        "a fresh actual_end pushes the recency window later, got "
        f"{after['currency_expires_at']} against {before['currency_expires_at']}"
    )


def test_one_clean_flight_clamps_the_risk_score_and_lands_in_the_summary_window(
    api, compliance_officer, pilot_headers
):
    """PRD §3.9: "Then take the raw score as 25 times the incident count, plus 15 times the exceedance count, plus 30 times the open-accident count, plus a lapsed-currency term of 10 when the pilot's `status` is `LAPSED` and 0 otherwise, minus 5 times the clean-flight count."
    PRD §3.9: "Clamp that raw value into the range 0 to 100 — negative raws become 0 and raws above 100 become 100 — and the clamped integer is the `risk_score`."
    PRD §3.7: "The source set is that pilot's flights whose `status` is `COMPLETED` and whose `actual_end` falls in the half-open window — at or after `window_start` and strictly before `window_end`."
    PRD §3.7: "From that set the response reports `completed_flight_count` (the number of flights), `total_logged_minutes` (the sum of their `logged_minutes`), `max_altitude_reached_ft` (the greatest `max_altitude_reached_ft` among them), `incident_flight_count` (how many have `incident_occurred` true), `exceedance_flight_count` (how many have `altitude_exceedance` true), `average_duration_minutes` (the `total_logged_minutes` divided by the `completed_flight_count`, rounded half-up to one decimal place), and the `window_start` and `window_end` actually applied."

    Design: Corner/state_machines/flight_completion_syncs_the_pilots_derived_recency_ledger
    """
    pilot, _, before, _, after = _fly_one_clean_sortie_for_a_commercial_pilot(
        api, compliance_officer, pilot_headers
    )

    assert_pilot(after, risk_score=0)
    assert after["version"] > before["version"], (
        "completion mutates the pilot row, got version "
        f"{after['version']} against {before['version']}"
    )

    set_clock(api, LEDGER_SUMMARY_INSTANT, headers=compliance_officer)
    summary = validate_success(
        api.get_flight_summary(pilot["id"], headers=compliance_officer)
    )

    assert_flight_summary(
        summary,
        completed_flight_count=1,
        total_logged_minutes=LEDGER_LOGGED_MINUTES,
        max_altitude_reached_ft=300,
        incident_flight_count=0,
        exceedance_flight_count=0,
        average_duration_minutes=float(LEDGER_LOGGED_MINUTES),
        window_end=LEDGER_SUMMARY_INSTANT,
    )
