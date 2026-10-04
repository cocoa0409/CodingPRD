"""Volunteer lifecycle: certification stamping, the leave loop, lazy expiry at
the strictly-greater boundary, recertification, the decertification cascade,
and the segregation-of-duties screen."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_case_note,
    add_training_record,
    assert_instant,
    assign_case,
    create_assigned_case,
    create_case,
    create_certified_ombudsman,
    create_member,
    create_ombudsman,
    open_round,
    read_case,
    read_ombudsman,
    set_clock,
    setup_basic_world,
    transition_ombudsman,
    triage_case,
    validate_error,
    validate_success,
)


def test_certification_stamps_and_leave_cycle_while_unexpired(api: ApiClient):
    """PRD §3.8: "Certification stamps `certified_on` with the logical clock and sets `certification_expires_on` 24 months later."
    PRD §3.8: "A certified volunteer may be placed `ON_LEAVE` by a coordinator and returned to `CERTIFIED` the same way; leave retains the volunteer's existing assignments but, per §3.3, fails the certification gate on new ones."
    PRD §2.4: "An ombudsman's certification flips from `CERTIFIED` to `EXPIRED` only when the logical clock is strictly later than `certification_expires_on`; at the exact expiry instant the volunteer is still `CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/ombudsman_leave_and_recertify_cycles
    """
    set_clock(api)
    ombudsman = create_certified_ombudsman(api)
    assert ombudsman["status"] == "CERTIFIED"
    assert_instant(ombudsman["certified_on"], "2026-09-01T00:00:00Z", "certified_on")
    assert_instant(ombudsman["certification_expires_on"], "2028-09-01T00:00:00Z", "certification_expires_on")

    on_leave = transition_ombudsman(api, ombudsman["id"], "ON_LEAVE")
    assert on_leave["status"] == "ON_LEAVE"
    returned = transition_ombudsman(api, ombudsman["id"], "CERTIFIED")
    assert returned["status"] == "CERTIFIED", "return from leave succeeds while the certification is unexpired"

    set_clock(api, "2028-09-01T00:00:00Z")
    at_expiry = read_ombudsman(api, ombudsman["id"])
    assert at_expiry["status"] == "CERTIFIED", \
        "at the exact expiry instant the volunteer is still CERTIFIED (strictly-greater comparison)"


def test_lazy_expiry_then_recertification_with_recent_training(api: ApiClient, coordinator_lead_headers: dict):
    """PRD §2.4: "An ombudsman's certification flips from `CERTIFIED` to `EXPIRED` only when the logical clock is strictly later than `certification_expires_on`; at the exact expiry instant the volunteer is still `CERTIFIED`."
    PRD §3.8: "Recertification moves `EXPIRED → CERTIFIED` on a lighter standard: at least one training record whose `completed_on` falls within the trailing 24 months of the logical clock, with the hours over those recent records totaling at least 8, and the segregation screen applied again. Recertification re-stamps `certified_on` and extends `certification_expires_on` a fresh 24 months."

    Design: Difficulty/non_linear_state_machine/ombudsman_leave_and_recertify_cycles
    """
    set_clock(api)
    ombudsman = create_certified_ombudsman(api)

    set_clock(api, "2028-10-01T00:00:00Z")
    lapsed = read_ombudsman(api, ombudsman["id"])
    assert lapsed["status"] == "EXPIRED", "the read surfaces the lazy flip once the clock is past 2028-09-01"

    add_training_record(api, ombudsman["id"], module_code="ELECTIVE", hours=8, exam_score=70,
                        completed_on="2028-09-15T00:00:00Z")
    recertified = transition_ombudsman(api, ombudsman["id"], "CERTIFIED", coordinator_lead_headers)
    assert recertified["status"] == "CERTIFIED"
    assert_instant(recertified["certified_on"], "2028-10-01T00:00:00Z", "re-stamped certified_on")
    assert_instant(recertified["certification_expires_on"], "2030-10-01T00:00:00Z", "fresh 24-month expiry")


def _setup_two_assigned_cases(api: ApiClient) -> dict:
    """Certified ombudsman carrying case A (AWAITING_RESPONSE behind a
    PROPOSED round, one INTAKE note) and case B (ASSIGNED, no rounds)."""
    world = setup_basic_world(api)
    case_a = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    add_case_note(api, case_a["id"], "INTAKE", "Intake done.")
    round_a = open_round(api, case_a["id"], world["ombudsman"]["id"], proposal_text="Reinstate promptly.")

    member_b = create_member(api, full_name="Jo Silva", email="jo@example.com",
                             branch="NAVY", component="NAVY_RESERVE")
    case_b = create_case(api, member_b["id"], world["employer"]["id"],
                         issue_type="BENEFITS", description="Health coverage dropped during service")
    case_b = triage_case(api, case_b["id"])
    case_b = assign_case(api, case_b["id"], world["ombudsman"]["id"], case_b["version"])
    return {"world": world, "case_a": case_a, "round_a": round_a, "case_b": case_b}


def test_decertify_reverts_cases_and_releases_caseload(api: ApiClient, coordinator_headers: dict):
    """PRD §3.8: "Decertifying a certified volunteer unwinds their active docket in three linked steps: every case assigned to them in `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` reverts to `TRIAGE` with its `assigned_ombudsman_id` cleared, the caseload drop following derivedly; each reverted case's `PROPOSED` rounds are closed `CLOSED_MOOT`; and a system `AUDIT` note is appended to the case for every round so closed."
    PRD §3.8: "A coordinator may decertify a `CERTIFIED` volunteer — or remove a mere `TRAINEE` — into the terminal `DECERTIFIED` status, supplying a `reason`."

    Design: Difficulty/transitive_cascade/decertify_reverts_cases_rounds_notes
    """
    setup = _setup_two_assigned_cases(api)
    world, case_a, case_b = setup["world"], setup["case_a"], setup["case_b"]
    ombudsman_id = world["ombudsman"]["id"]

    decertified = transition_ombudsman(api, ombudsman_id, "DECERTIFIED", coordinator_headers,
                                       reason="Ethics violation")
    assert decertified["status"] == "DECERTIFIED"
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 0

    reverted_a = read_case(api, case_a["id"])
    assert reverted_a["status"] == "TRIAGE"
    assert reverted_a["assigned_ombudsman_id"] is None, "link 1: the case revert clears the assignment"

    reverted_b = read_case(api, case_b["id"])
    assert reverted_b["status"] == "TRIAGE"
    assert reverted_b["assigned_ombudsman_id"] is None


def test_decertify_moots_open_rounds_and_appends_audit_notes(api: ApiClient, coordinator_headers: dict):
    """PRD §3.8: "each reverted case's `PROPOSED` rounds are closed `CLOSED_MOOT`; and a system `AUDIT` note is appended to the case for every round so closed."
    PRD §3.4: "A case's notes, including the system's own audit entries, are readable by ombudsmen and coordinators, while the case's rounds are readable by all four case parties."

    Design: Difficulty/transitive_cascade/decertify_reverts_cases_rounds_notes
    """
    setup = _setup_two_assigned_cases(api)
    world, case_a, round_a = setup["world"], setup["case_a"], setup["round_a"]

    transition_ombudsman(api, world["ombudsman"]["id"], "DECERTIFIED", coordinator_headers,
                         reason="Ethics violation")

    rounds = validate_success(api.list_case_rounds(case_a["id"], coordinator_headers))
    assert len(rounds) == 1
    assert rounds[0]["id"] == round_a["id"]
    assert rounds[0]["status"] == "CLOSED_MOOT", "link 2: the reverted case's open round is mooted"

    notes = validate_success(api.list_case_notes(case_a["id"], coordinator_headers))
    assert len(notes) == 2, "the manual INTAKE note plus exactly one system AUDIT note"
    note_types = sorted(note["note_type"] for note in notes)
    assert note_types == ["AUDIT", "INTAKE"], "link 3: one system AUDIT note per mooted round"


def test_proctor_cannot_certify_same_ombudsman(
    api: ApiClient, coordinator_admin_headers: dict, coordinator_lead_headers: dict
):
    """PRD §2.8: "The coordinator who records a volunteer's training is stamped onto each `TrainingRecord` as its `proctor_id`, taken from the acting coordinator's `X-User-ID` at recording time. A coordinator who appears as `proctor_id` on any of a volunteer's training records may not then certify or recertify that same volunteer; the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "Certification stamps `certified_on` with the logical clock and sets `certification_expires_on` 24 months later."

    Design: Corner/rbac/proctor_cannot_certify_same_ombudsman
    """
    set_clock(api)
    ombudsman = create_ombudsman(api)
    for module_code, hours, exam_score, completed_on in (
        ("CORE_LAW", 8, 90, "2026-08-01T00:00:00Z"),
        ("MEDIATION_SKILLS", 8, 88, "2026-08-05T00:00:00Z"),
        ("DOCUMENTATION", 6, 95, "2026-08-10T00:00:00Z"),
    ):
        add_training_record(api, ombudsman["id"], module_code=module_code, hours=hours,
                            exam_score=exam_score, completed_on=completed_on,
                            proctor_headers=coordinator_admin_headers)

    conflicted = api.transition_ombudsman(ombudsman["id"], {"to_status": "CERTIFIED"}, coordinator_admin_headers)
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert conflicted.status_code == 403

    certified = transition_ombudsman(api, ombudsman["id"], "CERTIFIED", coordinator_lead_headers)
    assert certified["status"] == "CERTIFIED"
    assert_instant(certified["certified_on"], "2026-09-01T00:00:00Z", "certified_on")
    assert_instant(certified["certification_expires_on"], "2028-09-01T00:00:00Z", "certification_expires_on")


def test_certification_with_missing_core_module_returns_requirements_unmet(
    api: ApiClient, coordinator_lead_headers: dict
):
    """PRD §3.8: "Each core module — `CORE_LAW`, `MEDIATION_SKILLS`, and `DOCUMENTATION` — must have at least one record with an `exam_score` of 80 or better; the `total_training_hours` must reach at least 20; and the segregation-of-duties screen of §2.8 must pass, evaluated before the training checks per the precedence order of §2.7. Shortfalls in the modules or hours fail with `ERR_CERTIFICATION_REQUIREMENTS_UNMET` (HTTP 422); a conflicted proctor fails with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/certification_with_missing_core_module_returns_requirements_unmet
    """
    set_clock(api)
    ombudsman = create_ombudsman(api)
    add_training_record(api, ombudsman["id"], module_code="CORE_LAW", hours=8, exam_score=90,
                        completed_on="2026-08-01T00:00:00Z")
    add_training_record(api, ombudsman["id"], module_code="MEDIATION_SKILLS", hours=8, exam_score=88,
                        completed_on="2026-08-05T00:00:00Z")

    response = api.transition_ombudsman(ombudsman["id"], {"to_status": "CERTIFIED"}, coordinator_lead_headers)
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_REQUIREMENTS_UNMET)
    assert response.status_code == 422

    after = read_ombudsman(api, ombudsman["id"])
    assert after["status"] == "TRAINEE"
    assert after["certified_on"] is None
