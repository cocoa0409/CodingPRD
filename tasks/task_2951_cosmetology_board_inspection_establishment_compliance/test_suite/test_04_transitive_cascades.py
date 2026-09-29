"""Depth-five dependent cascades (SCAFFOLD_DIFFICULTY_DESIGN rule ``transitive_cascade``).

Each test drives ONE originating transition and then walks every hop the PRD says
that transition causes, hop by hop, so a partial implementation that stops after
the first or second consequence is visible.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    CLOCK_START,
    assert_instants_equal,
    assert_points,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    notify_incident,
    open_incident,
    refresh_booth_rental,
    refresh_establishment,
    refresh_practitioner,
    refresh_workstation,
    resolve_incident,
    setup_compliant_station,
    setup_finalized_inspection,
    setup_substantiated_incident,
    validate_paginated,
)


def _demerit_rows(api, establishment_id):
    """The establishment's DEMERIT_POINTS ledger slice with its ``total_count``."""
    return validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {
                "establishment_id": establishment_id,
                "ledger_type": "DEMERIT_POINTS",
                "limit": 100,
            },
        )
    )


def _sanction_rows(api, practitioner_id):
    return validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {
                "practitioner_id": practitioner_id,
                "ledger_type": "SANCTION_POINTS",
                "limit": 100,
            },
        )
    )


def test_finalize_cascades_score_into_ledger_balance_and_posture(api):
    """One finalize call, four dependent hops observed at once.

    PRD 3.7 hop one writes ``final_adjusted_score``; hop two snapshots
    ``demerit_balance_before_finalize`` "before anything in this cascade posts to
    the ledger" and appends an ``INSPECTION_DEMERIT_ASSESSMENT`` row with
    ``delta_points`` equal to the positive score; hop three recomputes
    ``demerit_balance`` from that ledger; hop four leaves a ``PENDING_INSPECTION``
    facility exactly where it is because "a FAIL or an IMMEDIATE_CLOSURE leaves it
    at PENDING_INSPECTION"; and PRD 2.6 then derives ``FROZEN`` because
    ``demerit_balance`` "has reached 100.00 points or more".

    PRD 3.5 pins the arithmetic: 4.00 * 5.0 (CRITICAL) * 5 = 100.00 plus
    6.00 * 2.5 (MAJOR) * 1 = 15.00, each rounded then summed, gives 115.00.

    Design: Difficulty/transitive_cascade/finalize_score_to_ledger_to_balance_to_license_status_to_posture
    """
    critical = create_violation_code(
        api, severity="CRITICAL", base_points=4.00, fine_cents_base=30000,
        category="FOOT_SPA", code="FSP-300",
    )
    major = create_violation_code(
        api, severity="MAJOR", base_points=6.00, fine_cents_base=12000,
        category="IMPLEMENT_HANDLING", code="IMP-200",
    )
    est = create_establishment(
        api, station_capacity=8, establishment_type="SALON",
        county_code="NCE", legal_name="Chair & Comb",
    )
    assert est["license_status"] == "PENDING_INSPECTION"
    assert_points(est["demerit_balance"], 0.00, "opening demerit_balance")
    assert est["compliance_posture"] == "CLEAR"

    finalized = setup_finalized_inspection(
        api,
        est["id"],
        findings=[
            {"violation_code_id": critical["id"], "observed_count": 5,
             "corrected_on_site": False},
            {"violation_code_id": major["id"], "observed_count": 1,
             "corrected_on_site": False},
        ],
        window_index=0,
    )["inspection"]

    # Hop one.
    assert finalized["status"] == "FINALIZED"
    assert_points(finalized["final_adjusted_score"], 115.00, "final_adjusted_score")
    assert finalized["final_outcome"] == "FAIL"
    # Hop two: the snapshot predates this cascade's own ledger row.
    assert_points(
        finalized["demerit_balance_before_finalize"], 0.00,
        "demerit_balance_before_finalize",
    )
    rows, meta = _demerit_rows(api, est["id"])
    assert meta["total_count"] == 1, rows
    assert rows[0]["entry_reason"] == "INSPECTION_DEMERIT_ASSESSMENT"
    assert_points(rows[0]["delta_points"], 115.00, "delta_points")
    assert rows[0]["inspection_id"] == finalized["id"]
    assert rows[0]["establishment_id"] == est["id"]
    assert rows[0]["delta_cents"] is None

    after = refresh_establishment(api, est["id"])
    # Hop three.
    assert_points(after["demerit_balance"], 115.00, "demerit_balance")
    # Hop four: a FAIL never promotes, so PENDING_INSPECTION survives.
    assert after["license_status"] == "PENDING_INSPECTION"
    # Hop five's posture recomputation.
    assert after["compliance_posture"] == "FROZEN"
    assert_instants_equal(
        after["last_finalized_inspection_at"], finalized["finalized_at"],
        "last_finalized_inspection_at",
    )
    assert_instants_equal(finalized["finalized_at"], CLOCK_START, "finalized_at")


def test_finalize_cascade_demotes_an_active_facility_to_probation(api):
    """The same cascade, observed on the licence hop the PRD actually reaches.

    PRD 3.7 hop four: "An establishment sitting at PENDING_INSPECTION moves
    PENDING_INSPECTION -> ACTIVE when final_outcome is PASS or CONDITIONAL_PASS",
    and then "if the recomputed balance has reached 100.00 points or more while
    remaining below 200.00, an establishment in ACTIVE moves ACTIVE -> PROBATION".
    So the promotion has to be earned by a clean visit before the demotion hop is
    reachable at all, and PRD 2.6 freezes the posture off the same balance.

    Design: Difficulty/transitive_cascade/finalize_score_to_ledger_to_balance_to_license_status_to_posture
    """
    critical = create_violation_code(
        api, severity="CRITICAL", base_points=4.00, fine_cents_base=30000,
        category="FOOT_SPA",
    )
    major = create_violation_code(
        api, severity="MAJOR", base_points=6.00, fine_cents_base=12000,
        category="IMPLEMENT_HANDLING",
    )
    est = create_establishment(api, station_capacity=8, county_code="NCE")

    clean = setup_finalized_inspection(api, est["id"], findings=[], window_index=0)
    assert_points(
        clean["inspection"]["final_adjusted_score"], 0.00, "final_adjusted_score"
    )
    assert clean["inspection"]["final_outcome"] == "PASS"
    promoted = refresh_establishment(api, est["id"])
    assert promoted["license_status"] == "ACTIVE"
    assert_points(promoted["demerit_balance"], 0.00, "demerit_balance")
    assert promoted["compliance_posture"] == "CLEAR"

    # A later, well-spaced window so the closed-interval overlap check of PRD 3.5
    # and its symmetric 24-hour cooldown are both clear.
    heavy = setup_finalized_inspection(
        api,
        est["id"],
        findings=[
            {"violation_code_id": critical["id"], "observed_count": 5,
             "corrected_on_site": False},
            {"violation_code_id": major["id"], "observed_count": 1,
             "corrected_on_site": False},
        ],
        window_index=1,
    )["inspection"]
    assert_points(heavy["final_adjusted_score"], 115.00, "final_adjusted_score")
    assert heavy["final_outcome"] == "FAIL"
    assert_points(
        heavy["demerit_balance_before_finalize"], 0.00,
        "demerit_balance_before_finalize",
    )

    rows, _meta = _demerit_rows(api, est["id"])
    assessment = [
        row for row in rows
        if row["inspection_id"] == heavy["id"]
        and row["entry_reason"] == "INSPECTION_DEMERIT_ASSESSMENT"
    ]
    assert len(assessment) == 1, rows
    assert_points(assessment[0]["delta_points"], 115.00, "delta_points")

    demoted = refresh_establishment(api, est["id"])
    assert_points(demoted["demerit_balance"], 115.00, "demerit_balance")
    assert demoted["license_status"] == "PROBATION"
    assert demoted["compliance_posture"] == "FROZEN"
    assert_instants_equal(
        demoted["last_finalized_inspection_at"], heavy["finalized_at"],
        "last_finalized_inspection_at",
    )


def _aqua_nails_with_one_substantiated_incident(api):
    """Northside Academy, Dana Kim on a COMPLIANT nail table, one incident closed.

    PRD 3.9 puts the auto-suspension threshold at 15.00 points and PRD 3.9 credits
    10.00 per substantiated incident, so exactly one prior incident leaves the
    licence ACTIVE and the second one is what crosses the boundary.
    """
    school = create_school(
        api, required_clock_hours=16.00, accreditation_status="ACCREDITED",
        apprenticeship_program_approved=True, county_code="NCA",
    )
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], license_type="NAIL_TECHNICIAN",
        effective_at=CLOCK_START, full_name="Dana Kim",
    )
    est = create_establishment(
        api, station_capacity=6, establishment_type="NAIL_SALON",
        county_code="NCC", legal_name="Aqua Nails",
    )
    built = setup_compliant_station(
        api, est["id"], practitioner["id"], station_number=1,
        station_type="NAIL_TABLE", term_start_at=CLOCK_START,
    )
    assert built["workstation"]["posting_status"] == "COMPLIANT"
    assert built["booth_rental"]["status"] == "ACTIVE"

    setup_substantiated_incident(api, est["id"], practitioner["id"], case_count=3)
    interim = refresh_practitioner(api, practitioner["id"])
    assert_points(interim["sanction_points"], 10.00, "sanction_points")
    assert interim["license_status"] == "ACTIVE"

    second = open_incident(
        api, est["id"], case_count=2, suspected_practitioner_id=practitioner["id"],
        onset_date="2026-07-30",
    )
    return {
        "practitioner": practitioner,
        "establishment": est,
        "workstation": built["workstation"],
        "booth_rental": built["booth_rental"],
        "incident": second,
    }


def test_substantiated_resolution_cascades_into_suspension_rental_and_posting(api):
    """Resolving the second incident walks five dependent hops.

    PRD 3.9: a SUBSTANTIATED resolution "appends a sanction-ledger entry with
    entry_reason of INFECTION_SANCTION_ASSESSMENT and delta_points of positive
    10.00 ... then recomputes their sanction_points. If the recomputed
    sanction_points has reached 15.00 points or more ... license_status moves to
    SUSPENDED, suspension_cause_points is snapshotted from the current
    sanction_points, and ... every ACTIVE booth rental of that practitioner moves
    to TERMINATED ... each affected workstation whose posted_practitioner_id was
    that practitioner has the posting cleared to null so posting_status becomes
    MISSING_POSTING".

    Design: Difficulty/transitive_cascade/infection_resolution_to_sanction_ledger_to_suspension_to_void_rental_to_stale_posting
    """
    world = _aqua_nails_with_one_substantiated_incident(api)
    practitioner_id = world["practitioner"]["id"]

    notify_incident(api, world["incident"]["id"])
    resolved = resolve_incident(
        api, world["incident"]["id"], resolution="SUBSTANTIATED"
    )
    assert resolved["status"] == "RESOLVED_SUBSTANTIATED"

    rows, meta = _sanction_rows(api, practitioner_id)
    assert meta["total_count"] == 2, rows
    for row in rows:
        assert row["entry_reason"] == "INFECTION_SANCTION_ASSESSMENT"
        assert_points(row["delta_points"], 10.00, "delta_points")
        assert row["practitioner_id"] == practitioner_id
        assert row["delta_cents"] is None

    suspended = refresh_practitioner(api, practitioner_id)
    assert_points(suspended["sanction_points"], 20.00, "sanction_points")
    assert suspended["license_status"] == "SUSPENDED"
    assert_points(
        suspended["suspension_cause_points"], 20.00, "suspension_cause_points"
    )

    rental = refresh_booth_rental(api, world["booth_rental"]["id"])
    assert rental["status"] == "TERMINATED"
    assert_instants_equal(rental["terminated_at"], CLOCK_START, "terminated_at")

    station = refresh_workstation(api, world["workstation"]["id"])
    # PRD 3.9 clears the posting outright, so the verdict is MISSING_POSTING;
    # STALE_POSTING is what the gentler licence-expiry sweep produces.
    assert station["posted_practitioner_id"] is None
    assert station["posting_status"] == "MISSING_POSTING"


def test_substantiated_resolution_never_touches_the_establishment(api):
    """The cascade stops at the practitioner: no demerit hop exists.

    PRD 3.9: "One thing an infection resolution never does is touch the
    establishment: it posts sanction points only, never demerit points, so the
    establishment's demerit_balance and compliance_posture are entirely
    unaffected by this workflow."

    Design: Difficulty/transitive_cascade/infection_resolution_to_sanction_ledger_to_suspension_to_void_rental_to_stale_posting
    """
    world = _aqua_nails_with_one_substantiated_incident(api)
    est_id = world["establishment"]["id"]

    notify_incident(api, world["incident"]["id"])
    resolve_incident(api, world["incident"]["id"], resolution="SUBSTANTIATED")

    rows, meta = _demerit_rows(api, est_id)
    assert meta["total_count"] == 0, rows
    assert rows == []

    est = refresh_establishment(api, est_id)
    assert_points(est["demerit_balance"], 0.00, "demerit_balance")
    assert est["compliance_posture"] == "CLEAR"
    assert est["license_status"] == "PENDING_INSPECTION"
