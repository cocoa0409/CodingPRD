"""Corner cases: the declared state machines of the Cosmetology Board API.

Every test in this module translates exactly one non-stub `instance` of the
`state_machines` section of `SCAFFOLD_CORNER_DESIGN.yaml`, and asserts only what
`workspace/PRD.md` derives.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    CLOCK_START,
    HEALTH_LIAISON_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    INSPECTOR_HEADERS,
    INSPECTOR_USER_ID,
    ApiErrorId,
    advance_clock,
    assert_cents,
    assert_finding_shape,
    assert_fresh_inspection,
    assert_hearing_shape,
    assert_infection_incident_shape,
    assert_inspection_shape,
    assert_instants_equal,
    assert_points,
    contest_citation,
    contest_payload,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    decision_payload,
    hazard_clearance_payload,
    hazard_declaration_payload,
    hearing_payload,
    inspection_payload,
    issue_citation,
    make_establishment_owner_headers,
    notification_payload,
    open_incident,
    record_finding,
    refresh_booth_rental,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_practitioner,
    refresh_workstation,
    resolution_payload,
    schedule_hearing,
    schedule_inspection,
    setup_compliant_station,
    setup_finalized_inspection,
    termination_payload,
    validate_error,
    validate_paginated,
    validate_success,
    window_for,
)

# A MINOR code weighing 2.00 base points scores 2.00 * 1.0 * 1 * 1.0 * (1 - 0)
# = 2.00 on a single uncorrected observation (PRD 3.5), which lands in the
# `PASS` band and puts a 3000-cent base fine under the 5000-cent floor.
_MINOR_BASE_POINTS = 2.0
_MINOR_FINE_BASE = 3000
# PRD 3.7: base 3000 * tier 1.00 * subject 1.00 = 3000, clamped up to the 5000
# floor; the fee band for <= 25000 cents is 5 percent, so 250, total 5250.
_ASSESSED = 5000
_FEE = 250
_TOTAL = 5250


def _minor_code(api, code):
    return create_violation_code(
        api,
        severity="MINOR",
        base_points=_MINOR_BASE_POINTS,
        fine_cents_base=_MINOR_FINE_BASE,
        category="RECORDKEEPING",
        code=code,
    )


def _finalized_minor_inspection(api, establishment_id, code_id):
    """One ROUTINE visit carrying a single uncorrected MINOR finding, finalized."""
    return setup_finalized_inspection(
        api,
        establishment_id,
        findings=[
            {
                "violation_code_id": code_id,
                "observed_count": 1,
                "corrected_on_site": False,
            }
        ],
        window_index=1,
    )


# --- Inspection: the two independent dimensions --------------------------------
def test_new_inspection_opens_in_scheduled_with_hazard_state_none(api):
    """A freshly created inspection sits at the initial state of BOTH dimensions.

    PRD 3.5: "A new inspection opens at `status` of `SCHEDULED` and `hazard_state`
    of `NONE`, with `finding_count` and `citation_count` at 0, `started_at`,
    `submitted_at`, `finalized_at` and `demerit_balance_before_finalize` all null,
    and both score fields and both outcome fields ... null."

    Design: Corner/state_machines/state_machine_inspection_starts_in_scheduled_with_hazard_state_none
    """
    est = create_establishment(
        api, station_capacity=4, county_code="ABA", legal_name="Origin Salon"
    )
    inspection = validate_success(
        api.create_inspection(
            inspection_payload(
                establishment_id=est["id"],
                inspector_user_id=INSPECTOR_USER_ID,
                inspection_type="ROUTINE",
                **window_for(1),
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )
    assert_inspection_shape(inspection)
    assert_fresh_inspection(inspection)
    # PRD 2.4: version starts at 1 on creation.
    assert inspection["version"] == 1
    # PRD 2.9 pairing: neither optional edge belongs on a ROUTINE visit.
    assert inspection["complaint_reference"] is None
    assert inspection["reinspection_of_id"] is None


def test_start_moves_the_inspection_scheduled_to_in_progress(api):
    """The status dimension advances while the hazard dimension stays at NONE.

    PRD 3.5: "Opening the visit on site moves the inspection `SCHEDULED →
    IN_PROGRESS` and stamps `started_at` from the current logical clock".

    Design: Corner/state_machines/state_machine_inspection_start_moves_scheduled_to_in_progress
    """
    est = create_establishment(
        api,
        station_capacity=4,
        establishment_type="BARBERSHOP",
        county_code="ABB",
        legal_name="Kickoff Salon",
    )
    scheduled = schedule_inspection(
        api, est["id"], window_index=1, headers=INSPECTOR_HEADERS
    )
    started = validate_success(api.start_inspection(scheduled["id"], INSPECTOR_HEADERS))

    assert started["status"] == "IN_PROGRESS"
    assert_instants_equal(started["started_at"], CLOCK_START, "started_at")
    # PRD 2.4: exactly one version increment per mutation of the row.
    assert started["version"] == 2
    # PRD 3.6: the hazard dimension "evolves entirely separately from `status`".
    assert started["hazard_state"] == "NONE"
    # PRD 3.1: a facility "cannot reach `ACTIVE` until an inspection has been
    # finalized", so merely opening the visit leaves the licence where it was.
    assert refresh_establishment(api, est["id"])["license_status"] == "PENDING_INSPECTION"

    rows, meta = validate_paginated(
        api.list_inspections(BOARD_ADMIN_HEADERS, {"status": "IN_PROGRESS"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scheduled["id"]


def test_finalize_from_scheduled_is_rejected_as_not_pending_review(api):
    """finalize is absent from the SCHEDULED row of the transition table.

    PRD 3.7: "The inspection must be in `PENDING_REVIEW`, and an attempt from any
    other status is refused with `ERR_INSPECTION_NOT_PENDING_REVIEW` (HTTP 409)."

    Design: Corner/state_machines/state_machine_inspection_finalize_from_scheduled_rejected
    """
    est = create_establishment(
        api, station_capacity=4, county_code="ABC", legal_name="Premature Salon"
    )
    scheduled = schedule_inspection(
        api, est["id"], window_index=1, headers=INSPECTOR_HEADERS
    )

    validate_error(
        api.finalize_inspection(scheduled["id"], BOARD_ADMIN_HEADERS),
        ApiErrorId.ERR_INSPECTION_NOT_PENDING_REVIEW,
    )

    unchanged = refresh_inspection(api, scheduled["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["version"] == 1
    assert unchanged["final_adjusted_score"] is None
    assert unchanged["final_outcome"] is None
    est_after = refresh_establishment(api, est["id"])
    assert est_after["license_status"] == "PENDING_INSPECTION"
    assert_points(est_after["demerit_balance"], 0.00, "demerit_balance")


def test_start_twice_is_not_idempotent_and_the_second_call_is_rejected(api):
    """start is a one-way transition, not an idempotent setter.

    PRD 3.5: "attempting it on an inspection that is not `SCHEDULED` yields
    `ERR_INSPECTION_NOT_SCHEDULED` (HTTP 409)".

    Design: Corner/state_machines/state_machine_inspection_start_twice_is_not_idempotent_and_second_call_rejected
    """
    est = create_establishment(
        api, station_capacity=4, county_code="ABD", legal_name="Twice Salon"
    )
    scheduled = schedule_inspection(
        api, est["id"], window_index=1, headers=INSPECTOR_HEADERS
    )
    first = validate_success(api.start_inspection(scheduled["id"], INSPECTOR_HEADERS))

    validate_error(
        api.start_inspection(scheduled["id"], INSPECTOR_HEADERS),
        ApiErrorId.ERR_INSPECTION_NOT_SCHEDULED,
    )

    after = refresh_inspection(api, scheduled["id"])
    assert after["status"] == "IN_PROGRESS"
    assert after["version"] == first["version"] == 2
    assert_instants_equal(after["started_at"], CLOCK_START, "started_at")


def test_finalized_is_terminal_and_a_further_submit_is_rejected(api):
    """No trigger moves an inspection once it is FINALIZED.

    PRD 3.5: findings and submission happen "only while it is open, any attempt
    outside `IN_PROGRESS` being refused with `ERR_INSPECTION_NOT_IN_PROGRESS`
    (HTTP 409)".

    Design: Corner/state_machines/state_machine_inspection_finalized_is_terminal_and_a_further_submit_is_rejected
    """
    code = _minor_code(api, "REC-950")
    est = create_establishment(
        api, station_capacity=4, county_code="ABE", legal_name="Terminal Salon"
    )
    finalized = _finalized_minor_inspection(api, est["id"], code["id"])["inspection"]

    validate_error(
        api.submit_inspection(finalized["id"], INSPECTOR_HEADERS),
        ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS,
    )

    frozen = refresh_inspection(api, finalized["id"])
    assert frozen["status"] == "FINALIZED"
    # PRD 3.5: 2.00 base points * 1.0 MINOR weight * 1 observation * 1.0 repeat
    # factor * (1 - 0.00 credit) = 2.00, which is at or below the 10.00 band.
    assert_points(frozen["final_adjusted_score"], 2.00, "final_adjusted_score")
    assert frozen["final_outcome"] == "PASS"
    # No on-site correction was claimed, so the two variants agree.
    assert_points(
        frozen["provisional_adjusted_score"], 2.00, "provisional_adjusted_score"
    )
    assert frozen["provisional_outcome"] == "PASS"
    # PRD 3.7 hop two: the snapshot is taken before anything posts to the ledger.
    assert_points(
        frozen["demerit_balance_before_finalize"], 0.00, "demerit_balance_before_finalize"
    )

    est_after = refresh_establishment(api, est["id"])
    # PRD 3.7 hop four: PENDING_INSPECTION -> ACTIVE on a PASS.
    assert est_after["license_status"] == "ACTIVE"
    assert_points(est_after["demerit_balance"], 2.00, "demerit_balance")
    assert est_after["compliance_posture"] == "CLEAR"


# --- Citation and hearing --------------------------------------------------------
def test_contest_after_the_twenty_day_window_is_rejected(api):
    """The contest right closes while the citation is still ISSUED.

    PRD 3.8: "The current logical clock must also be at or before
    `contest_deadline_at`; the boundary is inclusive ... while anything later is
    refused with `ERR_CONTEST_WINDOW_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/state_machine_citation_contest_after_the_twenty_day_window_rejected
    """
    code = _minor_code(api, "REC-951")
    est = create_establishment(
        api, station_capacity=4, county_code="ABF", legal_name="Late Salon"
    )
    finalized = _finalized_minor_inspection(api, est["id"], code["id"])["inspection"]
    citation = issue_citation(api, finalized["id"])

    assert_instants_equal(citation["issued_at"], CLOCK_START, "issued_at")
    assert_cents(citation["assessed_fine_cents"], _ASSESSED, "assessed_fine_cents")
    assert_cents(citation["administrative_fee_cents"], _FEE, "administrative_fee_cents")
    assert_cents(citation["total_due_cents"], _TOTAL, "total_due_cents")
    assert_cents(citation["outstanding_fine_cents"], _TOTAL, "outstanding_fine_cents")
    # PRD 3.7: due_at at 30 days, contest_deadline_at at 20 days after issued_at.
    assert_instants_equal(citation["due_at"], "2026-08-31T00:00:00.000Z", "due_at")
    assert_instants_equal(
        citation["contest_deadline_at"], "2026-08-21T00:00:00.000Z", "contest_deadline_at"
    )

    # One day past the contest deadline but still nine days short of due_at, so
    # PRD 3.9's delinquency sweep leaves the citation ISSUED.
    advance_clock(api, "2026-08-22T00:00:00.000Z")

    error = validate_error(
        api.contest_citation(
            citation["id"],
            contest_payload(grounds="The recordkeeping binder was produced within the hour."),
            make_establishment_owner_headers(est["id"]),
        ),
        ApiErrorId.ERR_CONTEST_WINDOW_EXPIRED,
    )
    # PRD 3.8: ISSUED is still a contestable status, so the temporal rule fires
    # rather than the status gate.
    assert error["error_id"] != ApiErrorId.ERR_CITATION_NOT_CONTESTABLE

    after = refresh_citation(api, citation["id"])
    assert after["status"] == "ISSUED"
    assert after["hearing_round_count"] == 0
    assert_cents(after["outstanding_fine_cents"], _TOTAL, "outstanding_fine_cents")


def test_hearing_scheduling_sets_round_index_and_increments_round_count(api):
    """The round counter lives on the citation; round_index is derived from it.

    PRD 3.8: a scheduling "creates a hearing at `status` of `SCHEDULED` with
    `decision`, `amended_fine_cents`, `rationale` and `decided_at` all null and
    `round_index` set to the citation's `hearing_round_count` plus one ... then
    moves the citation `CONTESTED → HEARING_SCHEDULED`, increments
    `hearing_round_count` by one".

    Design: Corner/state_machines/state_machine_citation_hearing_scheduling_sets_round_index_and_round_count
    """
    code = _minor_code(api, "REC-952")
    est = create_establishment(
        api, station_capacity=4, county_code="ABG", legal_name="Round Salon"
    )
    finalized = _finalized_minor_inspection(api, est["id"], code["id"])["inspection"]
    citation = issue_citation(api, finalized["id"])
    contest_citation(
        api, citation["id"], make_establishment_owner_headers(est["id"])
    )
    assert refresh_citation(api, citation["id"])["status"] == "CONTESTED"

    # PRD 2.10: the presiding officer must differ from inspector_user_id.
    assert HEARING_OFFICER_USER_ID != INSPECTOR_USER_ID
    hearing = validate_success(
        api.schedule_hearing(
            citation["id"],
            hearing_payload(
                HEARING_OFFICER_USER_ID, scheduled_at="2026-08-12T14:00:00.000Z"
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    assert_hearing_shape(hearing)
    assert hearing["round_index"] == 1
    assert hearing["status"] == "SCHEDULED"
    assert hearing["decision"] is None
    assert hearing["amended_fine_cents"] is None
    assert hearing["rationale"] is None
    assert hearing["decided_at"] is None
    assert hearing["citation_id"] == citation["id"]

    after = refresh_citation(api, citation["id"])
    assert after["status"] == "HEARING_SCHEDULED"
    assert after["hearing_round_count"] == 1
    assert_cents(after["outstanding_fine_cents"], _TOTAL, "outstanding_fine_cents")

    rows, meta = validate_paginated(
        api.list_citation_hearings(citation["id"], BOARD_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == hearing["id"]


def test_affirmed_leaves_the_fine_untouched_and_posts_no_ledger_row(api):
    """AFFIRMED is the one hearing outcome with no monetary side effect.

    PRD 3.8: "An `AFFIRMED` decision moves the citation `HEARING_SCHEDULED →
    AFFIRMED` and changes nothing financial: `assessed_fine_cents`,
    `administrative_fee_cents`, `total_due_cents` and `outstanding_fine_cents` are
    all left exactly as they were and no ledger entry is posted."

    Design: Corner/state_machines/state_machine_hearing_affirmed_leaves_the_fine_untouched_and_posts_no_ledger_row
    """
    code = _minor_code(api, "REC-953")
    est = create_establishment(
        api, station_capacity=4, county_code="ABH", legal_name="Affirm Salon"
    )
    finalized = _finalized_minor_inspection(api, est["id"], code["id"])["inspection"]
    citation = issue_citation(api, finalized["id"])
    contest_citation(api, citation["id"], make_establishment_owner_headers(est["id"]))
    hearing = schedule_hearing(
        api,
        citation["id"],
        HEARING_OFFICER_USER_ID,
        scheduled_at="2026-08-12T14:00:00.000Z",
    )

    # PRD 2.10: the deciding X-User-ID must also differ from inspector_user_id.
    decided = validate_success(
        api.record_hearing_decision(
            hearing["id"],
            decision_payload(
                decision="AFFIRMED",
                rationale="The binder gap is established on the record.",
            ),
            HEARING_OFFICER_HEADERS,
        )
    )
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "AFFIRMED"
    assert_instants_equal(decided["decided_at"], CLOCK_START, "decided_at")
    assert decided["amended_fine_cents"] is None

    after = refresh_citation(api, citation["id"])
    assert after["status"] == "AFFIRMED"
    assert_cents(after["assessed_fine_cents"], _ASSESSED, "assessed_fine_cents")
    assert_cents(after["administrative_fee_cents"], _FEE, "administrative_fee_cents")
    assert_cents(after["total_due_cents"], _TOTAL, "total_due_cents")
    assert_cents(after["outstanding_fine_cents"], _TOTAL, "outstanding_fine_cents")

    # PRD 2.5: the FINE_CENTS ledger of this citation still holds only the
    # original CITATION_ASSESSMENT row.
    rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"citation_id": citation["id"], "ledger_type": "FINE_CENTS", "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["entry_reason"] == "CITATION_ASSESSMENT"
    assert_cents(rows[0]["delta_cents"], _TOTAL, "delta_cents")

    est_after = refresh_establishment(api, est["id"])
    assert_points(est_after["demerit_balance"], 2.00, "demerit_balance")
    assert_cents(
        est_after["outstanding_fine_total_cents"], _TOTAL, "outstanding_fine_total_cents"
    )


# --- Practitioner and booth rental ------------------------------------------------
def test_practitioner_lapses_when_the_clock_passes_license_expiry(api):
    """A lapse degrades the posting without clearing it.

    PRD 3.9: the licence-expiry sweep moves an expired `ACTIVE` licence to
    `LAPSED`, and "A lapse is gentler than a suspension: the practitioner's
    `ACTIVE` booth rentals keep their `ACTIVE` status, but every workstation whose
    posting names them recomputes `posting_status` to `STALE_POSTING`".

    Design: Corner/state_machines/state_machine_practitioner_lapses_when_the_clock_passes_license_expiry
    """
    school = create_school(
        api, required_clock_hours=16.00, accreditation_status="ACCREDITED", county_code="ABJ"
    )
    practitioner = create_licensed_practitioner(
        api,
        school_id=school["id"],
        license_type="COSMETOLOGIST",
        effective_at=CLOCK_START,
        full_name="Nell Vance",
    )
    # PRD 3.2: license_expires_on is effective_at plus the 730-day term.
    assert practitioner["license_expires_on"] == "2028-07-31"

    est = create_establishment(
        api, station_capacity=4, county_code="ABK", legal_name="Expiry Salon"
    )
    built = setup_compliant_station(api, est["id"], practitioner["id"], station_number=1)
    assert built["workstation"]["posting_status"] == "COMPLIANT"

    advance_clock(api, "2028-08-01T00:00:00.000Z")

    lapsed = refresh_practitioner(api, practitioner["id"])
    assert lapsed["license_status"] == "LAPSED"
    assert lapsed["license_expires_on"] == "2028-07-31"

    rental = refresh_booth_rental(api, built["booth_rental"]["id"])
    assert rental["status"] == "ACTIVE"
    assert rental["terminated_at"] is None
    assert rental["term_end_at"] is None

    station = refresh_workstation(api, built["workstation"]["id"])
    assert station["posted_practitioner_id"] == practitioner["id"]
    assert station["posting_status"] == "STALE_POSTING"

    rows, meta = validate_paginated(
        api.list_practitioners(BOARD_ADMIN_HEADERS, {"license_status": "LAPSED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == practitioner["id"]


def test_booth_rental_termination_clears_the_posting_to_missing(api):
    """A termination clears the posting outright, unlike a lapse.

    PRD 3.3: "Termination moves the rental `ACTIVE → TERMINATED`, writes
    `terminated_at`, and truncates the term by setting `term_end_at` to that same
    instant. Where the station's `posted_practitioner_id` equals the departing
    rental's `practitioner_id`, that posting is cleared to null so the station's
    `posting_status` falls to `MISSING_POSTING`".

    Design: Corner/state_machines/state_machine_booth_rental_termination_clears_the_posting_to_missing
    """
    school = create_school(api, required_clock_hours=16.00, county_code="ABL")
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], license_type="BARBER", full_name="Otto Blake"
    )
    est = create_establishment(
        api,
        station_capacity=4,
        establishment_type="BARBERSHOP",
        county_code="ABM",
        legal_name="Exit Salon",
    )
    built = setup_compliant_station(api, est["id"], practitioner["id"], station_number=1)
    assert built["workstation"]["posting_status"] == "COMPLIANT"

    terminated = validate_success(
        api.terminate_booth_rental(
            built["booth_rental"]["id"],
            make_establishment_owner_headers(est["id"]),
            termination_payload(
                terminated_at="2026-08-15T12:00:00.000Z",
                reason="Renter relocated out of county.",
            ),
        )
    )
    assert terminated["status"] == "TERMINATED"
    assert_instants_equal(
        terminated["terminated_at"], "2026-08-15T12:00:00.000Z", "terminated_at"
    )
    assert_instants_equal(
        terminated["term_end_at"], "2026-08-15T12:00:00.000Z", "term_end_at"
    )

    station = refresh_workstation(api, built["workstation"]["id"])
    assert station["posted_practitioner_id"] is None
    assert station["posting_status"] == "MISSING_POSTING"
    # PRD 3.3: ending the commercial relationship says nothing about the licence.
    assert refresh_practitioner(api, practitioner["id"])["license_status"] == "ACTIVE"

    _rows, meta = validate_paginated(
        api.list_booth_rentals(
            BOARD_ADMIN_HEADERS, {"workstation_id": station["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 0


# --- Infection incidents ----------------------------------------------------------
def test_infection_incident_escalates_only_once_the_deadline_is_strictly_passed(api):
    """The infection sweep's comparison is strict, not inclusive.

    PRD 3.9: "The **infection sweep** moves every incident whose `status` is
    `REPORTED` and whose `notification_deadline_at` is strictly earlier than the
    new clock value to `ESCALATED_OVERDUE`; an incident whose deadline equals the
    new clock value exactly is still on time."

    Design: Corner/state_machines/state_machine_infection_incident_escalates_only_once_the_deadline_is_strictly_passed
    """
    est = create_establishment(
        api,
        station_capacity=4,
        establishment_type="NAIL_SALON",
        county_code="ABN",
        legal_name="Deadline Salon",
    )
    incident = open_incident(
        api, est["id"], case_count=1, onset_date="2026-07-30", headers=INSPECTOR_HEADERS
    )
    assert_infection_incident_shape(incident)
    assert incident["status"] == "REPORTED"
    assert_instants_equal(incident["reported_at"], CLOCK_START, "reported_at")
    # PRD 3.9: a single-case cluster gets the 72-hour window.
    assert_instants_equal(
        incident["notification_deadline_at"],
        "2026-08-04T00:00:00.000Z",
        "notification_deadline_at",
    )

    advance_clock(api, "2026-08-04T00:00:00.000Z")
    on_time = validate_success(
        api.get_infection_incident(incident["id"], BOARD_ADMIN_HEADERS)
    )
    assert on_time["status"] == "REPORTED"

    advance_clock(api, "2026-08-04T00:00:00.001Z")
    escalated = validate_success(
        api.get_infection_incident(incident["id"], BOARD_ADMIN_HEADERS)
    )
    assert escalated["status"] == "ESCALATED_OVERDUE"
    assert escalated["notified_at"] is None
    assert escalated["health_authority_reference"] is None

    rows, meta = validate_paginated(
        api.list_infection_incidents(
            BOARD_ADMIN_HEADERS, {"status": "ESCALATED_OVERDUE"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incident["id"]


def test_unsubstantiated_resolution_posts_no_sanction_points(api):
    """The UNSUBSTANTIATED branch has no ledger consequence at all.

    PRD 3.9: "An `UNSUBSTANTIATED` resolution moves the incident `NOTIFIED →
    RESOLVED_UNSUBSTANTIATED` and stops there: no ledger entry is posted and the
    suspected practitioner's `sanction_points` is unchanged."

    Design: Corner/state_machines/state_machine_infection_unsubstantiated_resolution_posts_no_sanction_points
    """
    school = create_school(api, required_clock_hours=16.00, county_code="ABP")
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], license_type="NAIL_TECHNICIAN", full_name="Pia Rowe"
    )
    est = create_establishment(
        api,
        station_capacity=4,
        establishment_type="NAIL_SALON",
        county_code="ABQ",
        legal_name="Clear Nails",
    )
    incident = open_incident(
        api,
        est["id"],
        case_count=2,
        suspected_practitioner_id=practitioner["id"],
        onset_date="2026-07-29",
        headers=HEALTH_LIAISON_HEADERS,
    )
    # PRD 3.9: two or more cases compress the window to 24 hours.
    assert_instants_equal(
        incident["notification_deadline_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_deadline_at",
    )

    advance_clock(api, "2026-08-03T00:00:00.000Z")
    assert (
        validate_success(api.get_infection_incident(incident["id"], BOARD_ADMIN_HEADERS))[
            "status"
        ]
        == "ESCALATED_OVERDUE"
    )

    # PRD 3.9: "reporting late is still reporting, and it lifts the escalation."
    notified = validate_success(
        api.notify_infection_incident(
            incident["id"],
            notification_payload(health_authority_reference="HD-2026-0447"),
            HEALTH_LIAISON_HEADERS,
        )
    )
    assert notified["status"] == "NOTIFIED"
    assert_instants_equal(
        notified["notified_at"], "2026-08-03T00:00:00.000Z", "notified_at"
    )
    assert notified["health_authority_reference"] == "HD-2026-0447"

    resolved = validate_success(
        api.resolve_infection_incident(
            incident["id"],
            resolution_payload(
                resolution="UNSUBSTANTIATED",
                findings_summary=(
                    "Cultures did not match the salon's implements; no protocol breach."
                ),
            ),
            BOARD_ADMIN_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED_UNSUBSTANTIATED"

    after = refresh_practitioner(api, practitioner["id"])
    assert_points(after["sanction_points"], 0.00, "sanction_points")
    assert after["license_status"] == "ACTIVE"
    assert after["suspension_cause_points"] is None

    _rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"practitioner_id": practitioner["id"], "ledger_type": "SANCTION_POINTS"},
        )
    )
    assert meta["total_count"] == 0

    # PRD 3.9: an infection resolution "never does ... touch the establishment".
    est_after = refresh_establishment(api, est["id"])
    assert_points(est_after["demerit_balance"], 0.00, "demerit_balance")
    assert est_after["compliance_posture"] == "CLEAR"


# --- Establishment closure loop -----------------------------------------------------
def test_hazard_declaration_closes_the_establishment_and_clearance_restores_active(api):
    """The closure loop's exit condition is external to the declaring inspection.

    PRD 3.6: a declaration drives the establishment straight to
    `CLOSED_IMMINENT_HAZARD` / `FROZEN`, and clearance needs a distinct FINALIZED
    `REINSPECTION` of the same establishment whose `reinspection_of_id` is the
    declaring inspection, whose own `hazard_state` is `NONE` and whose
    `final_adjusted_score` is at most 10.00; on success "The establishment moves
    `CLOSED_IMMINENT_HAZARD → ACTIVE`".

    Design: Corner/state_machines/state_machine_hazard_declaration_closes_the_establishment_and_clearance_restores_active
    """
    code = create_violation_code(
        api,
        severity="IMMINENT_HAZARD",
        base_points=1.0,
        fine_cents_base=50000,
        category="FACILITY",
        code="FAC-960",
    )
    est = create_establishment(
        api, station_capacity=4, county_code="ABR", legal_name="Hazard Salon"
    )
    inspection = schedule_inspection(
        api, est["id"], window_index=0, headers=INSPECTOR_HEADERS
    )
    validate_success(api.start_inspection(inspection["id"], INSPECTOR_HEADERS))
    finding = record_finding(
        api,
        inspection["id"],
        code["id"],
        observed_count=1,
        corrected_on_site=False,
    )

    declared = validate_success(
        api.declare_hazard(
            inspection["id"],
            hazard_declaration_payload(
                finding["id"],
                narrative="Energised conductor over a water source; shop closed on the spot.",
            ),
            INSPECTOR_HEADERS,
        )
    )
    # PRD 3.6: declaring never moves the status dimension.
    assert declared["hazard_state"] == "HAZARD_DECLARED"
    assert declared["status"] == "IN_PROGRESS"
    closed = refresh_establishment(api, est["id"])
    assert closed["license_status"] == "CLOSED_IMMINENT_HAZARD"
    assert closed["compliance_posture"] == "FROZEN"

    validate_success(api.submit_inspection(inspection["id"], INSPECTOR_HEADERS))
    finalized = validate_success(
        api.finalize_inspection(inspection["id"], BOARD_ADMIN_HEADERS)
    )
    # PRD 3.5: 1.00 base * 8.0 IMMINENT_HAZARD weight * 1 * 1.0 * (1 - 0) = 8.00,
    # and a HAZARD_DECLARED inspection bands as IMMEDIATE_CLOSURE regardless.
    assert_points(finalized["final_adjusted_score"], 8.00, "final_adjusted_score")
    assert finalized["final_outcome"] == "IMMEDIATE_CLOSURE"
    assert finalized["status"] == "FINALIZED"
    assert finalized["hazard_state"] == "HAZARD_DECLARED"

    # PRD 3.5: a REINSPECTION is exempt from the 24-hour cooldown but still bound
    # by the closed-interval overlap check, so its window is spaced clear.
    reinspection = setup_finalized_inspection(
        api,
        est["id"],
        inspection_type="REINSPECTION",
        reinspection_of_id=inspection["id"],
        window_index=1,
    )["inspection"]
    assert reinspection["reinspection_of_id"] == inspection["id"]
    assert_points(reinspection["final_adjusted_score"], 0.00, "final_adjusted_score")
    assert reinspection["final_outcome"] == "PASS"
    assert reinspection["hazard_state"] == "NONE"

    cleared = validate_success(
        api.clear_hazard(
            inspection["id"],
            hazard_clearance_payload(reinspection["id"]),
            BOARD_ADMIN_HEADERS,
        )
    )
    assert cleared["hazard_state"] == "HAZARD_CLEARED"
    assert cleared["status"] == "FINALIZED"

    hazard_finding = validate_success(
        api.get_violation_finding(finding["id"], BOARD_ADMIN_HEADERS)
    )
    assert_finding_shape(hazard_finding)
    assert hazard_finding["declared_hazard"] is True
    assert hazard_finding["severity"] == "IMMINENT_HAZARD"

    reopened = refresh_establishment(api, est["id"])
    assert reopened["license_status"] == "ACTIVE"
    # PRD 3.6: "the demerits the hazard inspection assessed are not reversed."
    assert_points(reopened["demerit_balance"], 8.00, "demerit_balance")
    assert reopened["compliance_posture"] == "CLEAR"
