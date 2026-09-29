"""Compensating invariants: reversals restore a conserved sum to exactly zero.

Every test in this module translates exactly one non-stub instance of the
``compensating_invariant`` rule of ``SCAFFOLD_DIFFICULTY_DESIGN.yaml``.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    CLOCK_START,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    INSPECTOR_USER_ID,
    assert_cents,
    assert_instants_equal,
    assert_ledger_entry_shape,
    assert_ledger_sum,
    assert_points,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    decision_payload,
    issue_citation,
    ledger_entries,
    license_action_payload,
    refresh_booth_rental,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_practitioner,
    refresh_workstation,
    setup_compliant_station,
    setup_contested_citation_with_hearing,
    setup_finalized_inspection,
    setup_substantiated_incident,
    validate_paginated,
    validate_success,
)


# --- compensating_invariant / money and demerits reversed by a dismissal -------
def _dismissed_citation_world(api):
    """Drive one CRITICAL visit through finalize, citation, hearing and dismissal.

    4.00 base * 5.0 CRITICAL weight * 4 observed * 1.0 repeat = 80.00 demerits and
    an outcome of FAIL (PRD 3.5); the citation is then base 30000 plus a
    (80.00 - 30.00) * 400 = 20000-cent surcharge at tier 1.00, so 50000 assessed,
    an 8 percent fee of 4000 and 54000 total (PRD 3.7).
    """
    code = create_violation_code(
        api,
        severity="CRITICAL",
        base_points=4.00,
        fine_cents_base=30000,
        category="FOOT_SPA",
        code="FSP-300",
    )
    establishment = create_establishment(
        api,
        station_capacity=4,
        establishment_type="ESTHETICS_SPA",
        legal_name="Marina Spa",
    )
    inspection = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[
            {
                "violation_code_id": code["id"],
                "observed_count": 4,
                "corrected_on_site": False,
            }
        ],
        inspector_user_id=INSPECTOR_USER_ID,
    )["inspection"]
    assert_points(inspection["final_adjusted_score"], 80.00, "final_adjusted_score")
    assert inspection["final_outcome"] == "FAIL"
    citation = issue_citation(api, inspection["id"], subject_type="ESTABLISHMENT")
    assert_cents(citation["outstanding_fine_cents"], 54000, "outstanding_fine_cents")
    staged = setup_contested_citation_with_hearing(
        api,
        citation["id"],
        HEARING_OFFICER_USER_ID,
        scheduled_at="2026-08-25T14:00:00.000Z",
    )
    decided = validate_success(
        api.record_hearing_decision(
            staged["hearing"]["id"],
            decision_payload(
                decision="DISMISSED",
                rationale="replacement invoices predate the window; the finding cannot stand",
            ),
            HEARING_OFFICER_HEADERS,
        )
    )
    return {
        "establishment": establishment,
        "inspection": inspection,
        "citation": citation,
        "hearing": decided,
    }


def test_dismissal_posts_an_equal_and_opposite_fine_reversal_summing_to_zero(api):
    """PRD 3.8: a dismissal appends a `CITATION_DISMISSAL_REVERSAL` fine-ledger entry
    "whose `delta_cents` is the negative of the citation's `outstanding_fine_cents`
    immediately before the dismissal, so the citation's fine-ledger rows sum to
    exactly 0 and `outstanding_fine_cents` returns to 0" -- both original rows staying
    readable rather than being edited away.

    Design: Difficulty/compensating_invariant/dismissed_citation_conserves_fine_cents_and_demerit_points_to_zero
    """
    world = _dismissed_citation_world(api)
    citation_id = world["citation"]["id"]

    hearing = world["hearing"]
    assert hearing["status"] == "DECIDED"
    assert_instants_equal(hearing["decided_at"], CLOCK_START, "decided_at")

    citation = refresh_citation(api, citation_id)
    assert citation["status"] == "DISMISSED"
    # The assessment itself is never rewritten by the reversal.
    assert_cents(citation["assessed_fine_cents"], 50000, "assessed_fine_cents")
    assert_cents(citation["administrative_fee_cents"], 4000, "administrative_fee_cents")
    assert_cents(citation["total_due_cents"], 54000, "total_due_cents")
    assert_cents(citation["outstanding_fine_cents"], 0, "outstanding_fine_cents")

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"citation_id": citation_id, "ledger_type": "FINE_CENTS", "limit": 100},
        )
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert_ledger_entry_shape(row)
        assert row["citation_id"] == citation_id
    # PRD 2.3 pages ledger entries by occurred_at then created_at ascending.
    assert [row["entry_reason"] for row in rows] == [
        "CITATION_ASSESSMENT",
        "CITATION_DISMISSAL_REVERSAL",
    ]
    assert_cents(rows[0]["delta_cents"], 54000, "assessment delta_cents")
    assert_cents(rows[1]["delta_cents"], -54000, "reversal delta_cents")
    assert_ledger_sum(rows, "delta_cents", 0)

    establishment = refresh_establishment(api, world["establishment"]["id"])
    assert_cents(
        establishment["outstanding_fine_total_cents"], 0, "outstanding_fine_total_cents"
    )
    assert_cents(
        establishment["delinquent_fine_total_cents"], 0, "delinquent_fine_total_cents"
    )
    assert establishment["open_critical_citation_count"] == 0


def test_dismissal_reverses_the_inspection_demerits_to_exactly_zero_without_clamping(api):
    """PRD 3.8: the dismissal appends an `INSPECTION_DEMERIT_REVERSAL` "carrying the
    establishment's, the inspection's and the citation's identifiers, with
    `delta_points` equal to the negative of the inspection's `final_adjusted_score`",
    and PRD 2.5 forbids clamping the signed sum, so the demerit rows sum to 0.00.

    Design: Difficulty/compensating_invariant/dismissed_citation_conserves_fine_cents_and_demerit_points_to_zero
    """
    world = _dismissed_citation_world(api)
    establishment_id = world["establishment"]["id"]
    inspection_id = world["inspection"]["id"]
    citation_id = world["citation"]["id"]

    entries = ledger_entries(
        api, {"establishment_id": establishment_id, "ledger_type": "DEMERIT_POINTS"}
    )
    _rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {
                "establishment_id": establishment_id,
                "ledger_type": "DEMERIT_POINTS",
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 2
    assert len(entries) == 2
    assessment, reversal = entries
    for entry in entries:
        assert_ledger_entry_shape(entry)
        assert entry["establishment_id"] == establishment_id
        assert entry["inspection_id"] == inspection_id

    assert assessment["entry_reason"] == "INSPECTION_DEMERIT_ASSESSMENT"
    assert_points(assessment["delta_points"], 80.00, "assessment delta_points")
    # PRD 2.5: citation_id is set on a dismissal's demerit reversal and null on the
    # assessment that the finalize cascade posted.
    assert assessment["citation_id"] is None
    assert reversal["entry_reason"] == "INSPECTION_DEMERIT_REVERSAL"
    assert_points(reversal["delta_points"], -80.00, "reversal delta_points")
    assert reversal["citation_id"] == citation_id
    assert_ledger_sum(entries, "delta_points", 0.00)

    establishment = refresh_establishment(api, establishment_id)
    assert_points(establishment["demerit_balance"], 0.00, "demerit_balance")
    assert establishment["compliance_posture"] == "CLEAR"

    # The visit that produced the points is untouched history.
    inspection = refresh_inspection(api, inspection_id)
    assert inspection["status"] == "FINALIZED"
    assert_points(inspection["final_adjusted_score"], 80.00, "final_adjusted_score")


# --- compensating_invariant / sanction points reversed by a reinstatement -------
def _suspended_by_two_substantiated_incidents(api):
    """PRD 3.9: two substantiated incidents post +10.00 each, and the second lands on
    the inclusive 15.00 threshold, so the licence auto-suspends with
    `suspension_cause_points` snapshotted at 20.00 and the personnel cascade run."""
    school = create_school(api, required_clock_hours=16.00)
    practitioner = create_licensed_practitioner(
        api,
        school_id=school["id"],
        license_type="NAIL_TECHNICIAN",
        full_name="Vera Iles",
    )
    establishment = create_establishment(
        api, station_capacity=6, establishment_type="NAIL_SALON", legal_name="Aqua Nails"
    )
    built = setup_compliant_station(
        api,
        establishment["id"],
        practitioner["id"],
        station_number=1,
        station_type="NAIL_TABLE",
    )
    assert built["workstation"]["posting_status"] == "COMPLIANT"
    first = setup_substantiated_incident(
        api, establishment["id"], practitioner["id"], case_count=1
    )
    second = setup_substantiated_incident(
        api, establishment["id"], practitioner["id"], case_count=1
    )
    suspended = refresh_practitioner(api, practitioner["id"])
    assert suspended["license_status"] == "SUSPENDED"
    assert_points(suspended["sanction_points"], 20.00, "sanction_points")
    assert_points(
        suspended["suspension_cause_points"], 20.00, "suspension_cause_points"
    )
    return {
        "practitioner": practitioner,
        "establishment": establishment,
        "workstation": built["workstation"],
        "booth_rental": built["booth_rental"],
        "incidents": [first, second],
    }


def _reinstate(api, practitioner_id):
    return validate_success(
        api.apply_license_action(
            practitioner_id,
            license_action_payload(
                "REINSTATE",
                reason="remedial infection-control course completed and audited",
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def test_reinstatement_reverses_the_snapshot_so_sanction_points_return_to_zero(api):
    """PRD 3.2: reinstatement appends one `REINSTATEMENT_SANCTION_REVERSAL` with
    `delta_points` equal to the negative of the `suspension_cause_points` snapshot,
    "so the practitioner's `SANCTION_POINTS` rows sum to exactly 0.00 afterwards and
    `sanction_points` becomes 0.00", then sets the snapshot back to null.

    Design: Difficulty/compensating_invariant/reinstatement_conserves_sanction_points_without_restoring_terminated_rental
    """
    world = _suspended_by_two_substantiated_incidents(api)
    practitioner_id = world["practitioner"]["id"]

    reinstated = _reinstate(api, practitioner_id)
    assert reinstated["license_status"] == "ACTIVE"
    assert_points(reinstated["sanction_points"], 0.00, "sanction_points")
    assert reinstated["suspension_cause_points"] is None

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {
                "practitioner_id": practitioner_id,
                "ledger_type": "SANCTION_POINTS",
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 3
    for row in rows:
        assert_ledger_entry_shape(row)
        assert row["practitioner_id"] == practitioner_id
    assert [row["entry_reason"] for row in rows] == [
        "INFECTION_SANCTION_ASSESSMENT",
        "INFECTION_SANCTION_ASSESSMENT",
        "REINSTATEMENT_SANCTION_REVERSAL",
    ]
    assert_points(rows[0]["delta_points"], 10.00, "first assessment delta_points")
    assert_points(rows[1]["delta_points"], 10.00, "second assessment delta_points")
    # Sized to the 20.00 snapshot, not to the last 10.00 assessment.
    assert_points(rows[2]["delta_points"], -20.00, "reversal delta_points")
    assert (
        sum(
            1
            for row in rows
            if row["entry_reason"] == "REINSTATEMENT_SANCTION_REVERSAL"
        )
        == 1
    )
    assert_ledger_sum(rows, "delta_points", 0.00)


def test_reinstatement_compensation_is_scoped_and_resurrects_no_rental_or_posting(api):
    """PRD 3.2/3.9: the suspension cascade terminated the `ACTIVE` rental and cleared
    the workstation's `posted_practitioner_id` so `posting_status` became
    `MISSING_POSTING`, and reinstatement compensates the sanction ledger only -- "the
    whole sanction history that caused the suspension is wiped", not the personnel
    cascade, and PRD 3.9 keeps an infection resolution off the establishment's books.

    Design: Difficulty/compensating_invariant/reinstatement_conserves_sanction_points_without_restoring_terminated_rental
    """
    world = _suspended_by_two_substantiated_incidents(api)
    practitioner_id = world["practitioner"]["id"]
    rental_id = world["booth_rental"]["id"]
    workstation_id = world["workstation"]["id"]

    terminated = refresh_booth_rental(api, rental_id)
    assert terminated["status"] == "TERMINATED"
    cleared = refresh_workstation(api, workstation_id)
    assert cleared["posted_practitioner_id"] is None
    assert cleared["posting_status"] == "MISSING_POSTING"

    _reinstate(api, practitioner_id)

    # Nothing the suspension ended is resurrected by the compensating entry.
    still_terminated = refresh_booth_rental(api, rental_id)
    assert still_terminated["status"] == "TERMINATED"
    assert_instants_equal(still_terminated["terminated_at"], CLOCK_START, "terminated_at")
    still_cleared = refresh_workstation(api, workstation_id)
    assert still_cleared["posted_practitioner_id"] is None
    assert still_cleared["posting_status"] == "MISSING_POSTING"

    for incident in world["incidents"]:
        current = validate_success(
            api.get_infection_incident(incident["id"], BOARD_ADMIN_HEADERS)
        )
        assert current["status"] == "RESOLVED_SUBSTANTIATED"

    establishment = refresh_establishment(api, world["establishment"]["id"])
    assert_points(establishment["demerit_balance"], 0.00, "demerit_balance")
    assert establishment["compliance_posture"] == "CLEAR"
