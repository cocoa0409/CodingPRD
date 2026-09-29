"""Tolling cycles, reclassification cascades, sibling dispositions and the case-load ledger."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_instant,
    assert_investigation_window,
    assert_officer_ledgers,
)
from test_helpers import factories, fixtures


def world_with_held_interview(api, offense_class="C", **kwargs):
    """One assigned investigation with a held interview, so it sits in IN_PROGRESS."""
    world = fixtures.world_assigned_investigation(api, offense_class=offense_class, **kwargs)
    session = fixtures.schedule_session(api, world, world["i1_id"])
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(api, world, session["id"])
    world.update({"s1_id": session["id"], "clock": "2026-08-05T09:00:00Z"})
    return world


def toll(api, world, action, at):
    """Move the clock and then suspend or resume the statutory clock."""
    fixtures.set_clock(api, at)
    world["clock"] = at
    return get_success_data(
        api.toll_investigation(world["i1_id"], factories.tolling_payload(action), world["inv_a_headers"])
    )


def world_after_two_tolling_cycles(api):
    """Two full suspend-and-resume cycles over the same investigation."""
    world = world_with_held_interview(api)
    toll(api, world, "SUSPEND", "2026-08-06T00:00:00Z")
    first_resume = toll(api, world, "RESUME", "2026-08-13T12:00:00Z")
    toll(api, world, "SUSPEND", "2026-08-20T00:00:00Z")
    second_resume = toll(api, world, "RESUME", "2026-08-25T06:00:00Z")
    world.update({"first_resume": first_resume, "second_resume": second_resume})
    return world


def test_two_tolling_cycles_recompute_due_at_from_received_at(api):
    """Seven then five more whole days give tolled_days 12 and a due date of 12 December.

    PRD: The recomputation always runs from the complaint's `received_at` plus `statutory_days` plus the new `tolled_days` — never from the previous `due_at` — so a case that is tolled and resumed many times cannot drift.
    Design: Difficulty/non_linear_state_machine/investigation_double_tolling_cycle_then_pending_review_revision_loop
    """
    world = world_with_held_interview(api)
    opened = world["investigation"]
    assert opened["statutory_days"] == 121
    assert_instant(opened["due_at"], "2026-11-30T00:00:00Z")

    toll(api, world, "SUSPEND", "2026-08-06T00:00:00Z")
    first_resume = toll(api, world, "RESUME", "2026-08-13T12:00:00Z")
    assert first_resume["tolled_days"] == 7
    assert_instant(first_resume["due_at"], "2026-12-07T00:00:00Z")

    toll(api, world, "SUSPEND", "2026-08-20T00:00:00Z")
    second_resume = toll(api, world, "RESUME", "2026-08-25T06:00:00Z")
    assert second_resume["tolled_days"] == 12
    assert_instant(second_resume["due_at"], "2026-12-12T00:00:00Z")
    assert second_resume["status"] == "IN_PROGRESS"
    assert second_resume["suspended_at"] is None


def test_a_pending_review_return_accrues_no_tolled_days(api):
    """Resuming a case that is awaiting review reopens it and clears the findings stamp.

    PRD: The return clears `findings_submitted_at` and moves the owning complaint back from `ADJUDICATION` to `UNDER_INVESTIGATION`, so findings must be resubmitted in full before the complaint can be adjudicated again.
    PRD: No tolled time accrues on this path, because the clock was never suspended.
    Design: Difficulty/non_linear_state_machine/investigation_double_tolling_cycle_then_pending_review_revision_loop
    """
    world = world_after_two_tolling_cycles(api)
    fixtures.submit_findings(
        api, world, world["i1_id"], [factories.finding_entry(world["a1_id"], 60, 40)]
    )

    returned = get_success_data(
        api.toll_investigation(
            world["i1_id"], factories.tolling_payload("RESUME"), world["cmdr_headers"]
        )
    )

    assert returned["status"] == "IN_PROGRESS"
    assert returned["tolled_days"] == 12
    assert_instant(returned["due_at"], "2026-12-12T00:00:00Z")
    assert returned["findings_submitted_at"] is None
    reopened_complaint = fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])
    assert reopened_complaint["status"] == "UNDER_INVESTIGATION"

    revised = fixtures.submit_findings(
        api, world, world["i1_id"], [factories.finding_entry(world["a1_id"], 70, 30)]
    )
    assert revised["status"] == "PENDING_REVIEW"
    assert revised["interview_held_count"] == 1
    assert revised["assignment_count"] == 1
    assert revised["overdue"] is False
    assert fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])["status"] == "ADJUDICATION"
    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert allegation["evidence_weight_for"] == 70
    assert allegation["preponderance_met"] is True


def public_class_three_case(api, world):
    """A minor public complaint under investigation by a level-1 certified investigator."""
    bell = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-201",
        full_name="Investigator Bell",
        certification_level=1,
        max_case_load=2,
    )
    complaint = fixtures.file_public_complaint(api, world)
    allegation = fixtures.attach_allegation(
        api, world, complaint["id"], allegation_type="DISCOURTESY", offense_class="D"
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    assigned = fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], bell["id"]
    )
    return {
        "bell_id": bell["id"],
        "c_id": complaint["id"],
        "complaint": complaint,
        "a1_id": allegation["id"],
        "i1_id": investigation["id"],
        "investigation": assigned,
    }


def reclassify(api, world, complaint_id, classification_override):
    """Accept a complaint again with an override, which is the reclassification self-loop."""
    return get_success_data(
        api.classify_complaint(
            complaint_id,
            factories.screening_payload("ACCEPT", classification_override=classification_override),
            world["cmdr_headers"],
        )
    )


def test_reclassification_recomputes_the_statutory_window_and_reroutes_the_file(api, world):
    """A Class III file lifted to Class I gains 180 days, a level-3 bar and an IA owner.

    PRD: When the complaint already has an investigation, that investigation's `statutory_days` and `required_certification_level` are recomputed from the new classification while the accumulated `tolled_days` is preserved untouched, and `due_at` is then recomputed from the complaint's `received_at`.
    Design: Difficulty/transitive_cascade/reclassification_forces_investigation_back_to_unassigned
    """
    case = public_class_three_case(api, world)
    opened = case["investigation"]
    assert opened["status"] == "ASSIGNED"
    assert_investigation_window(
        opened, statutory_days=90, required_certification_level=1, due_at="2026-10-30T00:00:00Z"
    )
    assert case["complaint"]["classification"] == "CLASS_III"
    assert case["complaint"]["priority"] == 3
    assert case["complaint"]["assigned_unit_id"] == world["patrol_unit_id"]

    reclassified = reclassify(api, world, case["c_id"], "CLASS_I")

    assert reclassified["classification"] == "CLASS_I"
    assert reclassified["priority"] == 1
    assert reclassified["reclassification_count"] == 1
    assert reclassified["assigned_unit_id"] == world["ia_unit_id"]
    assert reclassified["status"] == "UNDER_INVESTIGATION"

    investigation = fixtures.read_investigation(api, case["i1_id"], world["cmdr_headers"])
    assert_investigation_window(
        investigation,
        statutory_days=180,
        required_certification_level=3,
        due_at="2027-01-28T00:00:00Z",
    )
    assert investigation["tolled_days"] == 0
    assert investigation["overdue"] is False


def test_reclassification_forces_the_investigation_back_to_unassigned(api, world):
    """The level-1 investigator loses the case and the caseload credit with it.

    PRD: And when the recomputed `required_certification_level` now exceeds the current assignee's `certification_level`, the investigation is forced back to `UNASSIGNED`: `assigned_investigator_officer_id` is cleared, and the displaced assignee's `open_case_load` is decremented by 1.
    Design: Difficulty/transitive_cascade/reclassification_forces_investigation_back_to_unassigned
    """
    case = public_class_three_case(api, world)
    before = fixtures.read_officer(api, case["bell_id"], world["cmdr_headers"])
    assert_officer_ledgers(before, open_case_load=1)

    reclassify(api, world, case["c_id"], "CLASS_I")

    investigation = fixtures.read_investigation(api, case["i1_id"], world["cmdr_headers"])
    assert investigation["status"] == "UNASSIGNED"
    assert investigation["assigned_investigator_officer_id"] is None
    assert investigation["assignment_count"] == 1
    assert investigation["closed_at"] is None

    after = fixtures.read_officer(api, case["bell_id"], world["cmdr_headers"])
    assert_officer_ledgers(after, open_case_load=0)


def two_allegation_case(api, world):
    """One file carrying two allegations, both found on, one of them sustained."""
    complaint = fixtures.file_supervisor_complaint(
        api, world, reported_allegation_types=["NEGLECT_OF_DUTY", "DISCOURTESY"]
    )
    neglect = fixtures.attach_allegation(
        api, world, complaint["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    discourtesy = fixtures.attach_allegation(
        api, world, complaint["id"], allegation_type="DISCOURTESY", offense_class="D"
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session = fixtures.schedule_session(api, world, investigation["id"])
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(api, world, session["id"])
    pending_review = fixtures.submit_findings(
        api,
        world,
        investigation["id"],
        [
            factories.finding_entry(neglect["id"], 60, 40, policy_compliant=False),
            factories.finding_entry(discourtesy["id"], 40, 60, policy_compliant=True),
        ],
    )
    fixtures.dispose_allegation(api, world, neglect["id"], "SUSTAINED")
    return {
        "c_id": complaint["id"],
        "a1_id": neglect["id"],
        "a2_id": discourtesy["id"],
        "i1_id": investigation["id"],
        "investigation": pending_review,
    }


def test_close_is_refused_while_a_sibling_allegation_is_still_pending(api, world):
    """A valid from-state is not enough: the undisposed sibling blocks the close.

    PRD: The investigation must be in `PENDING_REVIEW`, and if any allegation is still `PENDING` the close is refused with `ERR_PENDING_DISPOSITIONS`.
    Design: Difficulty/cross_entity_state_dependency/investigation_close_depends_on_every_sibling_allegation_being_disposed
    """
    case = two_allegation_case(api, world)
    assert case["investigation"]["status"] == "PENDING_REVIEW"

    refused = api.close_investigation(case["i1_id"], {}, world["cmdr_headers"])

    validate_error(refused, "ERR_PENDING_DISPOSITIONS", 409)
    investigation = fixtures.read_investigation(api, case["i1_id"], world["cmdr_headers"])
    assert investigation["status"] == "PENDING_REVIEW"
    assert investigation["closed_at"] is None
    complaint = fixtures.read_complaint(api, case["c_id"], world["cmdr_headers"])
    assert complaint["status"] == "ADJUDICATION"
    assert complaint["retention_until"] is None
    investigator = fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"])
    assert_officer_ledgers(investigator, open_case_load=1)
    assert fixtures.read_allegation(api, case["a2_id"], world["cmdr_headers"])["disposition"] == "PENDING"


def test_the_close_takes_the_retention_class_of_the_strongest_disposition(api, world):
    """Disposing the sibling admits the close, and the sustained finding governs retention.

    PRD: The governing disposition is the strongest disposition present across the complaint's allegations, chosen by this precedence with the first match winning: `SUSTAINED`, then `POLICY_FAILURE`, then `NOT_SUSTAINED`, then `EXONERATED`, then `UNFOUNDED`, then `WITHDRAWN`.
    Design: Difficulty/cross_entity_state_dependency/investigation_close_depends_on_every_sibling_allegation_being_disposed
    """
    case = two_allegation_case(api, world)
    fixtures.dispose_allegation(api, world, case["a2_id"], "NOT_SUSTAINED")
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")

    closed = fixtures.close_investigation(api, world, case["i1_id"])

    assert closed["status"] == "CLOSED"
    assert_instant(closed["closed_at"], "2026-08-20T00:00:00Z")
    complaint = fixtures.read_complaint(api, case["c_id"], world["cmdr_headers"])
    assert complaint["status"] == "CLOSED"
    assert_instant(complaint["closed_at"], "2026-08-20T00:00:00Z")
    assert complaint["allegation_count"] == 2
    assert complaint["sustained_allegation_count"] == 1
    assert_instant(complaint["retention_until"], "2033-08-18T00:00:00Z")
    investigator = fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"])
    assert_officer_ledgers(investigator, open_case_load=0)


def two_open_cases(api, world):
    """Two files against the same officer, both carried by the standing investigator."""
    bly = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-102",
        full_name="Investigator Bly",
        certification_level=3,
        max_case_load=3,
    )
    first = fixtures.file_supervisor_complaint(api, world)
    first_allegation = fixtures.attach_allegation(
        api, world, first["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    i1 = fixtures.open_investigation(api, world, first["id"])
    i1_assigned = fixtures.assign_investigation(api, world, i1["id"], i1["version"], world["inv_a_id"])

    second = fixtures.file_supervisor_complaint(api, world, incident_datetime="2026-07-20T18:00:00Z")
    second_allegation = fixtures.attach_allegation(
        api, world, second["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    i2 = fixtures.open_investigation(api, world, second["id"])
    fixtures.assign_investigation(api, world, i2["id"], i2["version"], world["inv_a_id"])
    session = fixtures.schedule_session(
        api,
        world,
        i2["id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:00:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
    )
    return {
        "bly_id": bly["id"],
        "c1_id": first["id"],
        "c1_code": first["intake_reference_code"],
        "a1_id": first_allegation["id"],
        "i1_id": i1["id"],
        "i1_v1": i1_assigned["version"],
        "c2_id": second["id"],
        "a2_id": second_allegation["id"],
        "i2_id": i2["id"],
        "s2_id": session["id"],
    }


def test_reassignment_moves_exactly_one_unit_of_case_load(api, world):
    """The outgoing and incoming investigators trade a single case between them.

    PRD: On the reassignment self-loop the outgoing assignee's `open_case_load` is debited by 1 in the same request, so the department-wide caseload total is conserved.
    Design: Difficulty/compensating_invariant/open_case_load_is_conserved_across_assignment_reassignment_void_and_close
    """
    cases = two_open_cases(api, world)
    before = fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"])
    assert_officer_ledgers(before, open_case_load=2)

    reassigned = fixtures.assign_investigation(
        api, world, cases["i1_id"], cases["i1_v1"], cases["bly_id"]
    )

    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_investigator_officer_id"] == cases["bly_id"]
    assert reassigned["assignment_count"] == 2
    outgoing = fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"])
    incoming = fixtures.read_officer(api, cases["bly_id"], world["cmdr_headers"])
    assert_officer_ledgers(outgoing, open_case_load=1)
    assert_officer_ledgers(incoming, open_case_load=1)


def test_a_void_and_a_close_return_the_case_load_ledgers_to_zero(api, world):
    """One withdrawal and one close empty both investigators' caseloads.

    PRD: Withdrawing from `UNDER_INVESTIGATION` also drives the investigation to `VOIDED` and stamps its `closed_at`; because the investigation became `VOIDED`, every interview session on it in `SCHEDULED` or `POSTPONED` moves to `CANCELLED` and releases the room and officer time it was holding; and because the investigation left the open set, the assignee's `open_case_load` is decremented by 1.
    Design: Difficulty/compensating_invariant/open_case_load_is_conserved_across_assignment_reassignment_void_and_close
    """
    cases = two_open_cases(api, world)
    fixtures.assign_investigation(api, world, cases["i1_id"], cases["i1_v1"], cases["bly_id"])

    withdrawn = fixtures.withdraw_complaint(
        api, world, cases["c1_id"], intake_reference_code=cases["c1_code"]
    )

    assert withdrawn["status"] == "WITHDRAWN"
    voided = fixtures.read_investigation(api, cases["i1_id"], world["cmdr_headers"])
    assert voided["status"] == "VOIDED"
    assert voided["closed_at"] is not None
    assert_officer_ledgers(
        fixtures.read_officer(api, cases["bly_id"], world["cmdr_headers"]), open_case_load=0
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=1
    )

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(api, world, cases["s2_id"])
    fixtures.submit_findings(
        api,
        world,
        cases["i2_id"],
        [factories.finding_entry(cases["a2_id"], 40, 60, policy_compliant=True)],
    )
    fixtures.dispose_allegation(api, world, cases["a2_id"], "NOT_SUSTAINED")
    closed = fixtures.close_investigation(api, world, cases["i2_id"])

    assert closed["status"] == "CLOSED"
    complaint = fixtures.read_complaint(api, cases["c2_id"], world["cmdr_headers"])
    assert complaint["status"] == "CLOSED"
    assert complaint["sustained_allegation_count"] == 0
    assert_instant(complaint["retention_until"], "2031-08-04T09:00:00Z")
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=0
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, cases["bly_id"], world["cmdr_headers"]), open_case_load=0
    )
    disciplines, _ = fixtures.rows(
        api.list_disciplines(world["cmdr_headers"], {"allegation_id": cases["a2_id"]})
    )
    assert disciplines == []
