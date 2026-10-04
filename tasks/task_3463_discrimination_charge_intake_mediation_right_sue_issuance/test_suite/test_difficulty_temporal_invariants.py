"""Difficulty queue: resource temporal-overlap rules and compensating-action
invariants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_investigator,
    conclude_mediation,
    create_interview_payload,
    create_mediation_session_payload,
    log_interview,
    make_investigator_headers,
    make_mediator_headers,
    read_charge,
    schedule_session,
    set_clock,
    setup_in_mediation,
    setup_under_investigation,
    vacate_settlement,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_mediator_sessions_half_open_adjacency(api):
    """PRD section 3.4: "A mediator's calendar is protected by a half-open overlap rule: sessions are treated as the interval from start inclusive to end exclusive, so back-to-back sessions are allowed, but any true overlap with another `SCHEDULED` session of the same mediator — on any mediation case — is rejected with `ERR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/mediator_sessions_half_open_adjacency
    """
    base = setup_in_mediation(basis_codes=["COLOR"], incident_date="2026-06-01")
    mediation = base["mediation_case"]
    set_clock("2027-01-05T00:00:00Z")  # all session times below are future

    # Back-to-back under [start, end): end == start touches but does not overlap.
    session_1 = schedule_session(mediation, "med-001",
                                 scheduled_start="2027-01-10T10:00:00Z",
                                 scheduled_end="2027-01-10T11:00:00Z")
    session_2 = schedule_session(mediation, "med-001",
                                 scheduled_start="2027-01-10T11:00:00Z",
                                 scheduled_end="2027-01-10T12:00:00Z")
    assert session_1["status"] == session_2["status"] == "SCHEDULED"

    # A true interior intersection with the same mediator's calendar is rejected.
    overlap = api_client.create_mediation_session(
        mediation["id"],
        create_mediation_session_payload(
            scheduled_start="2027-01-10T10:30:00Z",
            scheduled_end="2027-01-10T11:30:00Z",
        ),
        make_mediator_headers("med-001"),
    )
    validate_error(overlap, ApiErrorId.ERR_SESSION_OVERLAP)

    # The check is scoped per mediator_user_id: the identical slot is legal
    # for a different mediator.
    other = schedule_session(mediation, "med-002",
                             scheduled_start="2027-01-10T10:30:00Z",
                             scheduled_end="2027-01-10T11:30:00Z")
    assert other["mediator_user_id"] == "med-002"


def test_investigator_interview_thirty_minute_buffer(api):
    """PRD section 3.5: "One investigator's interviews are kept apart by a 30-minute buffer on both sides, evaluated across all of that investigator's interviews regardless of case: if the gap between the new interview and any existing interview of the same investigator is less than 30 minutes on either side, the logging is rejected with `ERR_INTERVIEW_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/investigator_interview_thirty_minute_buffer
    """
    first = setup_under_investigation(basis_codes=["RACE"],
                                      incident_date="2026-06-01")
    assign_investigator(first["investigation_case_id"], "inv-007")
    second = setup_under_investigation(basis_codes=["SEX"],
                                       incident_date="2026-06-01")
    assign_investigator(second["investigation_case_id"], "inv-007")

    log_interview(first["investigation_case_id"], "inv-007",
                  witness_name="W1",
                  interview_start="2026-09-10T10:00:00Z",
                  interview_end="2026-09-10T11:00:00Z", summary="first")

    # 11:00 -> 11:29 leaves a 29-minute gap on a different case of the same
    # investigator: less than the 30-minute buffer, so rejected.
    too_close = api_client.create_witness_interview(
        second["investigation_case_id"],
        create_interview_payload(
            witness_name="W2", interview_start="2026-09-10T11:29:00Z",
            interview_end="2026-09-10T12:00:00Z", summary="too close",
        ),
        make_investigator_headers("inv-007"),
    )
    validate_error(too_close, ApiErrorId.ERR_INTERVIEW_BUFFER_CONFLICT)

    # Exactly 30 minutes is not "less than 30": the buffer permits it.
    exact = log_interview(second["investigation_case_id"], "inv-007",
                          witness_name="W2",
                          interview_start="2026-09-10T11:30:00Z",
                          interview_end="2026-09-10T12:00:00Z",
                          summary="exactly 30")
    assert exact["investigator_user_id"] == "inv-007"


def test_assign_transfer_conserves_active_assignments(api):
    """PRD section 3.5: "Assignment (or reassignment, which transfers the caseload slot) names the target in `investigator_user_id`, stamps `assigned_investigator_id`, and recomputes the priority score."
    PRD section 3.5: "An `InvestigationCase` is born by cascade: the system auto-creates one, in `OPEN` with a null `assigned_investigator_id`, the first time its charge enters `UNDER_INVESTIGATION`, stamping the charge's `investigation_case_id`; the pair is one-to-one, and the case can be found from the charge through the investigation list filtered by `charge_id` (the list also supports `status` and `assigned_investigator_id` filters, so a director can survey any investigator's caseload)."
    PRD section 2.5: "`version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, including mutations driven by cascades."

    Design: Difficulty/compensating_invariant/assign_transfer_conserves_active_assignments
    """
    case_a = setup_under_investigation(basis_codes=["RACE"],
                                       incident_date="2026-06-01")
    case_b = setup_under_investigation(basis_codes=["AGE"],
                                       incident_date="2026-06-01")

    def caseload(investigator_user_id):
        rows, meta = validate_paginated(
            api_client.list_investigation_cases(
                _DIRECTOR, params={"assigned_investigator_id": investigator_user_id}
            )
        )
        return rows, meta["total_count"]

    assigned_a = assign_investigator(case_a["investigation_case_id"], "inv-101")
    assign_investigator(case_b["investigation_case_id"], "inv-101")
    _rows, total_101 = caseload("inv-101")
    assert total_101 == 2

    # The compensating action: transfer case A to inv-102 — a slot moves,
    # none is created, so the global assignment total stays at 2.
    moved = assign_investigator(case_a["investigation_case_id"], "inv-102")
    assert moved["assigned_investigator_id"] == "inv-102"
    assert moved["version"] == assigned_a["version"] + 1

    rows_101, total_101 = caseload("inv-101")
    rows_102, total_102 = caseload("inv-102")
    assert total_101 == 1 and rows_101[0]["id"] == case_b["investigation_case_id"]
    assert total_102 == 1 and rows_102[0]["id"] == case_a["investigation_case_id"]
    assert total_101 + total_102 == 2  # conserved across the transfer


def test_settle_vacate_conserve_settled_total(api):
    """PRD section 3.4: "On settlement the mediation case becomes `SETTLED` with `concluded_at` stamped from the clock, the charge records `settled_amount_cents` equal to the agreed amount with `settled_via` set to `MEDIATION` and `settled_at` stamped from the clock, every `SCHEDULED` session is `CANCELLED`, and the charge moves `IN_MEDIATION` → `CLOSED_SETTLED`."
    PRD section 3.8: "On vacatur the charge reopens to `UNDER_INVESTIGATION` with `settled_amount_cents` zeroed and both `settled_via` and `settled_at` cleared to null; the `SETTLED` mediation case moves to `VACATED`, retaining its own `settlement_amount_cents` for audit; and the investigation reopens — an existing case moves `CLOSED` → `GATHERING`, or, if none exists, one is auto-created in `OPEN`."

    Design: Difficulty/compensating_invariant/settle_vacate_conserve_settled_total
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = base["mediation_case"]
    # No investigation has ever existed on this mediation-only path.
    assert charge["investigation_case_id"] is None
    assert charge["settled_amount_cents"] == 0

    # Forward action: settle for 2500000 cents at the 2026-09-01 boot clock.
    settled_mediation = conclude_mediation(
        mediation, outcome="SETTLED", settlement_amount_cents=2_500_000
    )
    assert settled_mediation["status"] == "SETTLED"
    settled = read_charge(charge["id"])
    assert settled["case_status"] == "CLOSED_SETTLED"
    assert settled["settled_amount_cents"] == 2_500_000
    assert settled["settled_via"] == "MEDIATION"
    assert settled["settled_at"][:10] == "2026-09-01"

    # Compensating action inside the 10-day window: every settlement field is
    # zeroed without residue and the global settled total returns to 0.
    reopened = vacate_settlement(charge, reason="respondent repudiated the agreement")
    assert reopened["case_status"] == "UNDER_INVESTIGATION"
    assert reopened["settled_amount_cents"] == 0
    assert reopened["settled_via"] is None
    assert reopened["settled_at"] is None

    vacated = validate_ok(api_client.get_mediation_case(mediation["id"], _DIRECTOR))
    assert vacated["status"] == "VACATED"

    refreshed = read_charge(charge["id"])
    case_id = refreshed["investigation_case_id"]
    assert case_id  # auto-created in OPEN because none existed
    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["status"] == "OPEN"
