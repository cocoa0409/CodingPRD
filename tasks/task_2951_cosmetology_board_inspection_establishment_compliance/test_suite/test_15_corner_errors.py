"""Corner coverage: the error surface of PRD sections 2.4, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8 and 3.9.

Every test in this module translates exactly one non-stub ``errors`` instance of
``SCAFFOLD_CORNER_DESIGN.yaml``.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    HEALTH_LIAISON_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    INSPECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_workstation,
    assert_cents,
    assert_instants_equal,
    assert_points,
    create_candidate,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    decision_payload,
    file_training_record,
    finding_payload,
    get_success_data,
    hazard_clearance_payload,
    hazard_declaration_payload,
    hearing_payload,
    issue_citation,
    license_action_payload,
    make_establishment_owner_headers,
    notification_payload,
    open_incident,
    payment_payload,
    propose_rental,
    record_finding,
    refresh_booth_rental,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_practitioner,
    refresh_workstation,
    resolution_payload,
    sanitation_log_payload,
    setup_compliant_station,
    setup_contested_citation_with_hearing,
    setup_finalized_inspection,
    setup_inspection_in_progress,
    termination_payload,
    validate_error,
    validate_paginated,
    validate_success,
    workstation_payload,
)


def test_every_entity_lookup_has_its_own_not_found_code(api):
    """Eleven identical GETs against unknown UUIDs yield eleven distinct 404 codes.

    PRD 2.4: "A request naming a workstation beneath an establishment, or a
    finding beneath an inspection, fails on the leftmost identifier that names no
    row, and the error names the entity that was missing: ...
    ERR_SCHOOL_NOT_FOUND ... ERR_LEDGER_ENTRY_NOT_FOUND ..., each with HTTP 404."

    Design: Corner/errors/error_every_entity_lookup_has_its_own_not_found_code
    """
    lookups = [
        (api.get_school(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_SCHOOL_NOT_FOUND),
        (api.get_workstation(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_WORKSTATION_NOT_FOUND),
        (api.get_booth_rental(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_BOOTH_RENTAL_NOT_FOUND),
        (api.get_inspection(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api.get_violation_code(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_VIOLATION_CODE_NOT_FOUND),
        (api.get_violation_finding(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_VIOLATION_FINDING_NOT_FOUND),
        (api.get_citation(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_CITATION_NOT_FOUND),
        (api.get_hearing(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_HEARING_NOT_FOUND),
        (api.get_infection_incident(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_INFECTION_INCIDENT_NOT_FOUND),
        (api.get_ledger_entry(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
        (api.get_training_record(NON_EXISTENT_UUID, BOARD_ADMIN_HEADERS),
         ApiErrorId.ERR_TRAINING_RECORD_NOT_FOUND),
    ]
    seen = []
    for response, expected in lookups:
        assert response.status_code == 404, (
            f"{expected}: expected HTTP 404, got {response.status_code}"
        )
        body = validate_error(response, expected)
        seen.append(body["error_id"])
    assert len(set(seen)) == 11, (
        f"each entity family must own its own 404 code, got {seen}"
    )


def test_hazard_declaration_family_and_the_closed_establishment_write_gate(
    api, hazard_code, minor_code
):
    """Four refusals hang off one visit, and the closure gate beats the posture gate.

    PRD 3.6: "The named finding must belong to this very inspection and its
    `severity` must be exactly `IMMINENT_HAZARD`; ... either case is rejected with
    `ERR_HAZARD_FINDING_NOT_ELIGIBLE` (422)"; "The inspection must currently be at
    `HAZARD_DECLARED`, or the request is refused with `ERR_HAZARD_NOT_DECLARED`
    (HTTP 409)"; "a second attempt on an inspection already at `HAZARD_DECLARED`
    or `HAZARD_CLEARED` is refused with `ERR_HAZARD_ALREADY_DECLARED` (HTTP 409)".
    PRD 2.6 with 2.9 step 11 before step 13: a non-operable establishment refuses a
    capacity write with `ERR_ESTABLISHMENT_NOT_OPERABLE` (409), not
    `ERR_POSTURE_FROZEN`.

    Design: Corner/errors/error_hazard_declaration_family_and_the_closed_establishment_write_gate
    """
    est = create_establishment(api, station_capacity=4)
    inspection = setup_inspection_in_progress(api, est["id"])
    hazard_finding = record_finding(api, inspection["id"], hazard_code["id"])
    minor_finding = record_finding(api, inspection["id"], minor_code["id"])

    # A MINOR finding cannot support immediate closure.
    validate_error(
        api.declare_hazard(
            inspection["id"],
            hazard_declaration_payload(
                minor_finding["id"], narrative="Attempting closure on paperwork."
            ),
            INSPECTOR_HEADERS,
        ),
        ApiErrorId.ERR_HAZARD_FINDING_NOT_ELIGIBLE,
    )
    assert refresh_inspection(api, inspection["id"])["hazard_state"] == "NONE"

    # Clearance before any declaration is refused among the state preconditions.
    # PRD 2.9 step 11 sequences `ERR_INSPECTION_NOT_FINALIZED` ahead of
    # `ERR_HAZARD_NOT_DECLARED`, so the nominated clearing inspection must already
    # be FINALIZED for the hazard-state gate to be the first rule that fires.
    elsewhere = create_establishment(api, station_capacity=4)
    finalized_elsewhere = setup_finalized_inspection(api, elsewhere["id"])["inspection"]
    assert finalized_elsewhere["status"] == "FINALIZED"
    validate_error(
        api.clear_hazard(
            inspection["id"],
            hazard_clearance_payload(finalized_elsewhere["id"]),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_HAZARD_NOT_DECLARED,
    )

    declared = validate_success(
        api.declare_hazard(
            inspection["id"],
            hazard_declaration_payload(
                hazard_finding["id"], narrative="Autoclave inoperable; doors shut."
            ),
            INSPECTOR_HEADERS,
        )
    )
    assert declared["hazard_state"] == "HAZARD_DECLARED"
    assert declared["status"] == "IN_PROGRESS"
    assert validate_success(
        api.get_violation_finding(hazard_finding["id"], BOARD_ADMIN_HEADERS)
    )["declared_hazard"] is True
    assert validate_success(
        api.get_violation_finding(minor_finding["id"], BOARD_ADMIN_HEADERS)
    )["declared_hazard"] is False
    closed = refresh_establishment(api, est["id"])
    assert closed["license_status"] == "CLOSED_IMMINENT_HAZARD"
    assert closed["compliance_posture"] == "FROZEN"

    # A hazard may be declared at most once per inspection.
    validate_error(
        api.declare_hazard(
            inspection["id"],
            hazard_declaration_payload(
                hazard_finding["id"], narrative="Duplicate closure order."
            ),
            INSPECTOR_HEADERS,
        ),
        ApiErrorId.ERR_HAZARD_ALREADY_DECLARED,
    )

    # Operability (step 11) fires ahead of the frozen posture (step 13).
    validate_error(
        api.create_workstation(
            est["id"], workstation_payload(1, "STYLING_CHAIR"), BOARD_ADMIN_HEADERS
        ),
        ApiErrorId.ERR_ESTABLISHMENT_NOT_OPERABLE,
    )
    assert refresh_establishment(api, est["id"])["station_count"] == 0


def test_citation_adjudication_and_payment_state_gates(api):
    """A hearing needs a CONTESTED citation, and a settled one takes no more money.

    PRD 3.8: "The citation must currently be `CONTESTED`, or the request is refused
    with `ERR_CITATION_NOT_CONTESTED` (HTTP 409)"; "A citation whose `status` is
    already `SETTLED` or `DISMISSED` accepts no further payment and is refused with
    `ERR_CITATION_ALREADY_SETTLED` (HTTP 409)".

    Design: Corner/errors/error_citation_adjudication_and_payment_state_gates
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=2.00, fine_cents_base=3000
    )
    est = create_establishment(api, station_capacity=4)
    finalized = setup_finalized_inspection(
        api, est["id"], findings=[{"violation_code_id": code["id"]}]
    )
    citation = issue_citation(api, finalized["inspection"]["id"])
    # base 3000 -> floor-clamped to 5000, 5 percent fee of 250 -> 5250 due (PRD 3.7).
    assert_cents(citation["total_due_cents"], 5250, "total_due_cents")
    assert_cents(citation["outstanding_fine_cents"], 5250, "outstanding_fine_cents")
    assert citation["status"] == "ISSUED"

    validate_error(
        api.schedule_hearing(
            citation["id"],
            hearing_payload(HEARING_OFFICER_USER_ID, scheduled_at="2026-08-14T10:00:00.000Z"),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_CITATION_NOT_CONTESTED,
    )
    assert refresh_citation(api, citation["id"])["hearing_round_count"] == 0
    _, meta = validate_paginated(
        api.list_citation_hearings(citation["id"], BOARD_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0

    owner_headers = make_establishment_owner_headers(est["id"])
    get_success_data(
        api.pay_citation(citation["id"], payment_payload(5250, "CHK-9001"), owner_headers)
    )
    settled = refresh_citation(api, citation["id"])
    assert settled["status"] == "SETTLED"
    assert_cents(settled["outstanding_fine_cents"], 0, "outstanding_fine_cents")

    validate_error(
        api.pay_citation(
            citation["id"], payment_payload(100, "CHK-9002"), owner_headers
        ),
        ApiErrorId.ERR_CITATION_ALREADY_SETTLED,
    )
    assert_cents(
        refresh_citation(api, citation["id"])["outstanding_fine_cents"],
        0,
        "outstanding_fine_cents",
    )
    _, ledger_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"citation_id": citation["id"], "entry_reason": "CITATION_PAYMENT"},
        )
    )
    assert ledger_meta["total_count"] == 1


def test_hearing_decision_cannot_be_recorded_twice_on_one_round(api):
    """The decision endpoint is single-shot per adjudication round.

    PRD 3.8: "The hearing must still be `SCHEDULED`, and a second decision on the
    same hearing is refused with `ERR_HEARING_ALREADY_DECIDED` (HTTP 409)".

    Design: Corner/errors/error_hearing_decision_cannot_be_recorded_twice_on_one_round
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=2.00, fine_cents_base=3000
    )
    est = create_establishment(api, station_capacity=4)
    finalized = setup_finalized_inspection(
        api, est["id"], findings=[{"violation_code_id": code["id"]}]
    )
    citation = issue_citation(api, finalized["inspection"]["id"])
    staged = setup_contested_citation_with_hearing(
        api, citation["id"], HEARING_OFFICER_USER_ID
    )
    hearing = staged["hearing"]

    decided = validate_success(
        api.record_hearing_decision(
            hearing["id"], decision_payload(decision="AFFIRMED"), HEARING_OFFICER_HEADERS
        )
    )
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "AFFIRMED"

    validate_error(
        api.record_hearing_decision(
            hearing["id"], decision_payload(decision="DISMISSED"), HEARING_OFFICER_HEADERS
        ),
        ApiErrorId.ERR_HEARING_ALREADY_DECIDED,
    )

    unchanged = validate_success(api.get_hearing(hearing["id"], BOARD_ADMIN_HEADERS))
    assert unchanged["decision"] == "AFFIRMED"
    assert unchanged["amended_fine_cents"] is None
    after = refresh_citation(api, citation["id"])
    assert after["status"] == "AFFIRMED"
    assert_cents(after["outstanding_fine_cents"], 5250, "outstanding_fine_cents")
    assert after["hearing_round_count"] == 1
    _, ledger_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"citation_id": citation["id"], "ledger_type": "FINE_CENTS"},
        )
    )
    assert ledger_meta["total_count"] == 1


def test_incident_notification_ordering_gates_in_both_directions(api):
    """Each end of the investigation workflow owns its own refusal.

    PRD 3.9: "the incident must be at `NOTIFIED`, or the request is refused with
    `ERR_INCIDENT_NOT_NOTIFIED` (HTTP 409)"; "The incident must be at `REPORTED` or
    `ESCALATED_OVERDUE` — an already-notified or resolved incident cannot be
    notified again, and the attempt is refused with `ERR_INCIDENT_NOT_NOTIFIABLE`
    (HTTP 409)".

    Design: Corner/errors/error_incident_notification_ordering_gates_in_both_directions
    """
    est = create_establishment(api, station_capacity=4)
    incident = open_incident(
        api,
        est["id"],
        case_count=1,
        onset_date="2026-07-30",
        headers=HEALTH_LIAISON_HEADERS,
    )
    assert incident["status"] == "REPORTED"
    # A single-case cluster gets 72 hours from reported_at (PRD 3.9).
    assert_instants_equal(
        incident["notification_deadline_at"], "2026-08-04T00:00:00.000Z"
    )

    validate_error(
        api.resolve_infection_incident(
            incident["id"],
            resolution_payload(
                resolution="UNSUBSTANTIATED", findings_summary="Closing before notifying."
            ),
            HEALTH_LIAISON_HEADERS,
        ),
        ApiErrorId.ERR_INCIDENT_NOT_NOTIFIED,
    )
    premature = validate_success(
        api.get_infection_incident(incident["id"], HEALTH_LIAISON_HEADERS)
    )
    assert premature["status"] == "REPORTED"
    assert premature["findings_summary"] is None

    notified = validate_success(
        api.notify_infection_incident(
            incident["id"],
            notification_payload(health_authority_reference="HD-2026-0777"),
            HEALTH_LIAISON_HEADERS,
        )
    )
    assert notified["status"] == "NOTIFIED"
    assert notified["health_authority_reference"] == "HD-2026-0777"
    assert_instants_equal(notified["notified_at"], "2026-08-01T00:00:00.000Z")

    validate_error(
        api.notify_infection_incident(
            incident["id"],
            notification_payload(health_authority_reference="HD-2026-0778"),
            HEALTH_LIAISON_HEADERS,
        ),
        ApiErrorId.ERR_INCIDENT_NOT_NOTIFIABLE,
    )
    after = validate_success(
        api.get_infection_incident(incident["id"], HEALTH_LIAISON_HEADERS)
    )
    assert after["health_authority_reference"] == "HD-2026-0777"
    assert after["status"] == "NOTIFIED"


def test_booth_rental_state_gates_and_sanitation_log_eligibility_gates(api):
    """Four refusals from one salon: two rental status gates and two log gates.

    PRD 3.3: "The rental must currently be `PROPOSED`, or the request is refused
    with `ERR_BOOTH_RENTAL_NOT_PROPOSED` (HTTP 409)"; "The rental must currently be
    `ACTIVE`, or the request is refused with `ERR_BOOTH_RENTAL_NOT_ACTIVE`
    (HTTP 409)". PRD 3.4: "the station's `posting_status` must be `COMPLIANT` at the
    moment of filing ... the attempt is refused with
    `ERR_WORKSTATION_POSTING_NONCOMPLIANT` (HTTP 409)"; "`FOOT_SPA_WEEKLY_BIOFILM`
    ... valid only on a station whose `station_type` is `FOOT_SPA` ... A mismatch is
    reported as `ERR_SANITATION_LOG_STATION_TYPE_MISMATCH` (HTTP 422)".

    Design: Corner/errors/error_booth_rental_state_gates_and_sanitation_log_eligibility_gates
    """
    school = create_school(api, required_clock_hours=16.00, accreditation_status="ACCREDITED")
    practitioner = create_licensed_practitioner(api, school_id=school["id"])
    est = create_establishment(
        api, station_capacity=4, establishment_type="NAIL_SALON"
    )
    built = setup_compliant_station(
        api, est["id"], practitioner["id"], station_number=1, station_type="STYLING_CHAIR"
    )
    station_one = built["workstation"]
    rental_one = built["booth_rental"]
    assert station_one["posting_status"] == "COMPLIANT"
    assert refresh_booth_rental(api, rental_one["id"])["status"] == "ACTIVE"

    station_two = add_workstation(
        api, est["id"], station_number=2, station_type="NAIL_TABLE"
    )
    rental_two = propose_rental(api, station_two["id"], practitioner["id"])
    assert rental_two["status"] == "PROPOSED"
    assert refresh_workstation(api, station_two["id"])["posting_status"] == "MISSING_POSTING"

    validate_error(
        api.activate_booth_rental(rental_one["id"], BOARD_ADMIN_HEADERS),
        ApiErrorId.ERR_BOOTH_RENTAL_NOT_PROPOSED,
    )
    assert refresh_booth_rental(api, rental_one["id"])["status"] == "ACTIVE"

    validate_error(
        api.terminate_booth_rental(
            rental_two["id"],
            BOARD_ADMIN_HEADERS,
            termination_payload(reason="Renter withdrew before starting."),
        ),
        ApiErrorId.ERR_BOOTH_RENTAL_NOT_ACTIVE,
    )
    still_proposed = refresh_booth_rental(api, rental_two["id"])
    assert still_proposed["status"] == "PROPOSED"
    assert still_proposed["terminated_at"] is None

    # Station two's protocol matches its NAIL_TABLE type, so the posting gate fires.
    validate_error(
        api.create_sanitation_log(
            sanitation_log_payload(
                workstation_id=station_two["id"],
                log_type="IMPLEMENT_DISINFECTION",
                performed_at="2026-08-01T09:00:00.000Z",
                contact_minutes=10.00,
                implement_batch_count=6,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_WORKSTATION_POSTING_NONCOMPLIANT,
    )

    # Station one's posting is COMPLIANT, so the station-type gate is what refuses.
    validate_error(
        api.create_sanitation_log(
            sanitation_log_payload(
                workstation_id=station_one["id"],
                log_type="FOOT_SPA_WEEKLY_BIOFILM",
                performed_at="2026-08-01T09:00:00.000Z",
                contact_minutes=360.00,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_SANITATION_LOG_STATION_TYPE_MISMATCH,
    )
    assert refresh_workstation(api, station_one["id"])["posting_status"] == "COMPLIANT"

    for station_id in (station_one["id"], station_two["id"]):
        _, meta = validate_paginated(
            api.list_workstation_sanitation_logs(station_id, BOARD_ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0
    assert refresh_workstation(api, station_one["id"])["last_biofilm_cycle_at"] is None
    assert refresh_establishment(api, est["id"])["foot_spa_biofilm_current"] is True


def test_license_action_legality_and_the_school_to_license_prerequisites(api):
    """The licensing pipeline refuses in three different ways, and the ladder decides.

    PRD 3.2: "any action attempted from a status it does not permit is rejected with
    `ERR_LICENSE_ACTION_NOT_PERMITTED` (HTTP 409): `GRANT_EXAM_ELIGIBILITY` only from
    `STUDENT`; `ISSUE_LICENSE` only from `EXAM_ELIGIBLE`; ... `REINSTATE` only from
    `PROBATION`, `SUSPENDED` or `LAPSED`"; "a shortfall is reported as
    `ERR_EXAM_ELIGIBILITY_REQUIRED` (HTTP 409)"; "the candidate must hold at least
    one training record whose `discipline` is `SANITATION` and at least one whose
    `discipline` is `DISINFECTION` ... Either composition failure is reported as
    `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422)."

    Design: Corner/errors/error_license_action_legality_and_the_school_to_license_prerequisites
    """
    school = create_school(
        api, required_clock_hours=16.00, accreditation_status="ACCREDITED"
    )
    dov = create_candidate(api, school_id=school["id"], full_name="Dov Halevi")
    file_training_record(
        api,
        dov["id"],
        hours=8.00,
        performed_on="2026-07-06",
        discipline="SANITATION",
        school_id=school["id"],
    )
    esme = create_candidate(api, school_id=school["id"], full_name="Esme Waverly")
    for performed_on in ("2026-07-06", "2026-07-07"):
        file_training_record(
            api,
            esme["id"],
            hours=8.00,
            performed_on=performed_on,
            discipline="SANITATION",
            school_id=school["id"],
        )

    # Step 11 of PRD 2.9 refuses the illegal action before the eligibility quota.
    validate_error(
        api.apply_license_action(
            dov["id"],
            license_action_payload("ISSUE_LICENSE", effective_at="2026-08-01T00:00:00.000Z"),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_LICENSE_ACTION_NOT_PERMITTED,
    )
    validate_error(
        api.apply_license_action(
            dov["id"], license_action_payload("GRANT_EXAM_ELIGIBILITY"), BOARD_ADMIN_HEADERS
        ),
        ApiErrorId.ERR_EXAM_ELIGIBILITY_REQUIRED,
    )
    dov_after = refresh_practitioner(api, dov["id"])
    assert_points(dov_after["credited_hours_total"], 8.00, "credited_hours_total")
    assert_points(
        dov_after["required_clock_hours_effective"], 16.00, "required_clock_hours_effective"
    )
    assert dov_after["exam_eligible"] is False
    assert dov_after["license_status"] == "STUDENT"

    validate_error(
        api.apply_license_action(
            esme["id"], license_action_payload("GRANT_EXAM_ELIGIBILITY"), BOARD_ADMIN_HEADERS
        ),
        ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT,
    )
    esme_after = refresh_practitioner(api, esme["id"])
    assert_points(esme_after["credited_hours_total"], 16.00, "credited_hours_total")
    # PRD 3.2: the hour comparison is inclusive, so the flag is true even though the
    # composition gate blocked the grant and the status is still STUDENT.
    assert esme_after["exam_eligible"] is True
    assert esme_after["license_status"] == "STUDENT"

    validate_error(
        api.apply_license_action(
            esme["id"],
            license_action_payload("REINSTATE", reason="Reinstating a student."),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_LICENSE_ACTION_NOT_PERMITTED,
    )
    assert refresh_practitioner(api, esme["id"])["license_status"] == "STUDENT"


def test_finding_workstation_must_belong_to_the_inspected_establishment(api, minor_code):
    """A station of another salon is a 422 scope failure, never a 404.

    PRD 3.5: "a supplied `workstation_id` must name a workstation belonging to the
    inspection's own establishment, failing which the refusal is
    `ERR_WORKSTATION_NOT_IN_ESTABLISHMENT` (HTTP 422)."

    Design: Corner/errors/error_finding_workstation_must_belong_to_the_inspected_establishment
    """
    est_a = create_establishment(api, station_capacity=4, county_code="AAK")
    est_b = create_establishment(api, station_capacity=4, county_code="AAL")
    station_b = add_workstation(api, est_b["id"], station_number=1)
    inspection = setup_inspection_in_progress(api, est_a["id"])

    validate_error(
        api.create_finding(
            inspection["id"],
            finding_payload(minor_code["id"], workstation_id=station_b["id"]),
            INSPECTOR_HEADERS,
        ),
        ApiErrorId.ERR_WORKSTATION_NOT_IN_ESTABLISHMENT,
    )

    created = validate_success(
        api.create_finding(
            inspection["id"], finding_payload(minor_code["id"]), INSPECTOR_HEADERS
        ),
        201,
    )
    assert created["workstation_id"] is None
    assert created["severity"] == "MINOR"
    assert refresh_inspection(api, inspection["id"])["finding_count"] == 1
    _, meta = validate_paginated(
        api.list_violation_findings(
            BOARD_ADMIN_HEADERS, {"workstation_id": station_b["id"]}
        )
    )
    assert meta["total_count"] == 0
