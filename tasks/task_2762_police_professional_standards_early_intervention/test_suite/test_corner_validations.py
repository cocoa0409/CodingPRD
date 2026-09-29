"""Whole-table uniqueness, cross-entity eligibility, temporal edges and conditional identity."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    SYSTEM_ADMIN_HEADERS,
    assert_instant,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"


def test_a_reused_badge_number_is_refused_and_leaves_the_roster_unchanged(api):
    """The second PN-501 is refused as a duplicate and writes nothing; PN-502 lands at once.

    PRD: `badge_number` must be unique across every officer record; a duplicate is refused with `ERR_BADGE_NUMBER_DUPLICATE`.
    PRD: A newly created officer starts with every derived field at its zero point: `employment_status` is `ACTIVE`, `eis_score` is 0.00, `eis_alert_level` is `NONE`, `open_case_load` is 0, `open_alert_count` is 0, `imposed_suspension_days_total` is 0, `intervention_escalation_count` is 0, `credibility_disclosure_active` is false, and `suspension_end_date` is null.
    Design: Corner/validations/a_reused_badge_number_is_refused_and_leaves_the_roster_unchanged
    """
    fixtures.set_clock(api, BASE_CLOCK)
    unit = fixtures.create_unit(api, intake_enabled=True)
    vance = fixtures.create_officer(api, unit["id"])
    assert vance["badge_number"] == "PN-501"

    refused = api.create_officer(
        factories.officer_payload(
            unit["id"],
            badge_number="PN-501",
            full_name="Officer Winters",
            annual_salary_cents=9000000,
        ),
        SYSTEM_ADMIN_HEADERS,
    )

    validate_error(refused, "ERR_BADGE_NUMBER_DUPLICATE", 409)
    roster, meta = fixtures.rows(
        api.list_officers(SYSTEM_ADMIN_HEADERS, {"unit_id": unit["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in roster] == [vance["id"]]
    assert fixtures.read_officer(api, vance["id"], SYSTEM_ADMIN_HEADERS)["full_name"] == "Officer Vance"

    winters = fixtures.create_officer(
        api,
        unit["id"],
        badge_number="PN-502",
        full_name="Officer Winters",
        annual_salary_cents=9000000,
    )

    assert winters["badge_number"] == "PN-502"
    assert winters["employment_status"] == "ACTIVE"
    assert_officer_ledgers(winters, open_case_load=0, open_alert_count=0)
    assert_officer_risk(winters, eis_score=0.00, eis_alert_level="NONE")
    _, after = fixtures.rows(
        api.list_officers(SYSTEM_ADMIN_HEADERS, {"unit_id": unit["id"], "limit": 10, "offset": 0})
    )
    assert after["total_count"] == 2


def test_an_investigator_certified_exactly_at_the_bar_is_accepted(api):
    """A certification of 2 against a Class II bar of 2 is not below it, so the write stands.

    PRD: `required_certification_level` — the internal-affairs certification an assignee must hold — is 3 for `CLASS_I`, 2 for `CLASS_II` and 1 for `CLASS_III`.
    PRD: A nominated officer whose `is_investigator` is false, whose `employment_status` is not `ACTIVE`, or whose `certification_level` falls below the investigation's `required_certification_level` is refused with `ERR_CERTIFICATION_INSUFFICIENT`.
    PRD: An accepted assignment writes `assigned_investigator_officer_id`, raises `assignment_count` by 1 — the counter includes reassignments, so it is a count of accepted assignment writes rather than of distinct people — credits the new assignee's `open_case_load` by 1, and advances the investigation's `version` by 1.
    Design: Corner/validations/an_investigator_certified_exactly_at_the_bar_is_accepted
    """
    world = fixtures.world_with_investigation(api, investigator_certification_level=2)
    assert world["complaint"]["classification"] == "CLASS_II"
    assert world["investigation"]["required_certification_level"] == 2
    at_the_bar = fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"])
    assert at_the_bar["certification_level"] == 2
    assert at_the_bar["is_investigator"] is True
    assert_officer_ledgers(at_the_bar, open_case_load=0)

    assigned = fixtures.assign_investigation(
        api, world, world["i1_id"], world["i1_v0"], world["inv_a_id"]
    )

    assert assigned["status"] == "ASSIGNED"
    assert assigned["assigned_investigator_officer_id"] == world["inv_a_id"]
    assert assigned["assignment_count"] == 1
    assert assigned["version"] == world["i1_v0"] + 1
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=1
    )


def two_files_and_a_bench_of_mixed_eligibility(api):
    """Ahn is full at one case, Calder is under-certified, Quinn is no investigator, Briggs is fit."""
    world = fixtures.seed_reference_data(
        api, investigator_max_case_load=1, investigator_certification_level=3
    )
    calder = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-050",
        full_name="Investigator Calder",
        certification_level=1,
        max_case_load=3,
    )
    briggs = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-102",
        full_name="Investigator Briggs",
        certification_level=2,
        max_case_load=3,
    )
    quinn = fixtures.create_officer(
        api,
        world["ia_unit_id"],
        badge_number="IA-900",
        full_name="Analyst Quinn",
        rank="SERGEANT",
        assignment_type="ADMIN",
        annual_salary_cents=9800000,
    )
    first = fixtures.file_supervisor_complaint(
        api, world, narrative="First file: reports not filed."
    )
    fixtures.attach_allegation(
        api, world, first["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    one = fixtures.open_investigation(api, world, first["id"])
    fixtures.assign_investigation(api, world, one["id"], one["version"], world["inv_a_id"])

    second = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Second file: reports not filed on a later shift.",
        incident_datetime="2026-07-20T18:00:00Z",
    )
    fixtures.attach_allegation(
        api, world, second["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    two = fixtures.open_investigation(api, world, second["id"])
    world.update(
        {
            "calder_id": calder["id"],
            "briggs_id": briggs["id"],
            "quinn_id": quinn["id"],
            "i1_id": one["id"],
            "i2_id": two["id"],
            "i2_v": two["version"],
            "i2_required": two["required_certification_level"],
        }
    )
    return world


def test_assignment_eligibility_reads_the_officer_row_not_the_request_body(api):
    """Certification and caseload are read off the roster, so three nominations fail and one wins.

    PRD: A nominated officer whose `is_investigator` is false, whose `employment_status` is not `ACTIVE`, or whose `certification_level` falls below the investigation's `required_certification_level` is refused with `ERR_CERTIFICATION_INSUFFICIENT`.
    PRD: A nominated officer whose `open_case_load` already equals `max_case_load` is refused with `ERR_CASE_LOAD_EXCEEDED`.
    PRD: When `investigator_officer_id` **is** supplied, the selector is skipped but all eight conditions are still enforced individually, and each failure now reports its own specific reason rather than the generic empty-pool error.
    Design: Corner/validations/assignment_eligibility_reads_the_officer_row_not_the_request_body
    """
    world = two_files_and_a_bench_of_mixed_eligibility(api)
    assert world["i2_required"] == 2

    def nominate(officer_id):
        return api.assign_investigation(
            world["i2_id"],
            factories.assignment_payload(world["i2_v"], officer_id),
            world["cmdr_headers"],
        )

    validate_error(nominate(world["calder_id"]), "ERR_CERTIFICATION_INSUFFICIENT", 422)
    validate_error(nominate(world["quinn_id"]), "ERR_CERTIFICATION_INSUFFICIENT", 422)
    validate_error(nominate(world["inv_a_id"]), "ERR_CASE_LOAD_EXCEEDED", 422)

    stalled = fixtures.read_investigation(api, world["i2_id"], world["cmdr_headers"])
    assert stalled["status"] == "UNASSIGNED"
    assert stalled["assigned_investigator_officer_id"] is None
    assert stalled["assignment_count"] == 0
    assert stalled["version"] == world["i2_v"]

    accepted = get_success_data(nominate(world["briggs_id"]))

    assert accepted["status"] == "ASSIGNED"
    assert accepted["assigned_investigator_officer_id"] == world["briggs_id"]
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=1
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["briggs_id"], world["cmdr_headers"]), open_case_load=1
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["calder_id"], world["cmdr_headers"]), open_case_load=0
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["quinn_id"], world["cmdr_headers"]), open_case_load=0
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["cmdr_id"], world["cmdr_headers"]), open_case_load=0
    )


def test_the_statute_and_the_event_clock_are_compared_non_strictly(api, world):
    """An incident exactly a year old files, and an event exactly on the clock is recorded.

    PRD: An incident may be complained of for one year: the supplied `incident_datetime` must be at or after the logical clock less 365 whole days, and an older incident is refused with `ERR_STATUTE_EXPIRED`.
    PRD: The same 365-day figure is stored forward as `statute_expires_at`, which is `incident_datetime` plus 365 whole days — the deadline for filing about this incident, entirely separate from the investigation's own due date.
    PRD: The `occurred_at` instant must be at or before the logical clock — the system does not accept events that have not happened yet — and a future instant is refused with `ERR_EVENT_IN_FUTURE`.
    PRD: On acceptance the system derives `base_weight` from the event type's base weight in the scoring table below, and derives `weekday_index` from `occurred_at`: an integer from 0 to 6 where 0 is Monday, computed in UTC.
    Design: Corner/validations/the_statute_and_the_event_clock_are_compared_non_strictly
    """
    stale = api.create_complaint(
        factories.supervisor_complaint_payload(
            world["patrol_unit_id"],
            world["sup_id"],
            narrative="Stale incident reported far too late.",
            incident_datetime="2025-07-31T00:00:00Z",
        ),
        world["sup_headers"],
    )

    validate_error(stale, "ERR_STATUTE_EXPIRED", 422)

    at_the_edge = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Incident exactly one year old.",
        incident_datetime="2025-08-01T00:00:00Z",
    )

    assert at_the_edge["status"] == "CLASSIFIED"
    assert at_the_edge["screening_required"] is False
    assert_instant(at_the_edge["received_at"], BASE_CLOCK)
    assert_instant(at_the_edge["statute_expires_at"], BASE_CLOCK)

    future = api.create_activity_event(
        world["subj_id"],
        factories.activity_event_payload(
            event_type="SICK_LEAVE_DAY",
            occurred_at="2026-08-01T00:00:01Z",
            severity_code="NA",
            source_reference="SL-FUTURE",
        ),
        world["sup_headers"],
    )

    validate_error(future, "ERR_EVENT_IN_FUTURE", 422)

    on_the_clock = fixtures.record_activity_event(
        api,
        world["subj_id"],
        "SICK_LEAVE_DAY",
        BASE_CLOCK,
        severity_code="NA",
        source_reference="SL-NOW",
        headers=world["sup_headers"],
    )

    assert_instant(on_the_clock["occurred_at"], BASE_CLOCK)
    assert_two_dp(on_the_clock["base_weight"], 1.0, label="base_weight")
    assert on_the_clock["weekday_index"] == 5
    assert on_the_clock["system_generated"] is False

    assert_officer_risk(
        fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"]),
        eis_score=2.50,
        eis_alert_level="NONE",
    )
    events, event_meta = fixtures.rows(
        api.list_activity_events(world["subj_id"], world["cmdr_headers"])
    )
    assert event_meta["total_count"] == 1
    assert [row["source_reference"] for row in events] == ["SL-NOW"]
    filed, complaint_meta = fixtures.rows(
        api.list_complaints(world["cmdr_headers"], {"subject_unit_id": world["patrol_unit_id"]})
    )
    assert complaint_meta["total_count"] == 1
    assert [row["id"] for row in filed] == [at_the_edge["id"]]


def test_a_plan_cannot_close_while_any_child_check_in_is_still_pending(api):
    """The close scans the children: refused with one still pending, accepted with none.

    PRD: The plan must be `ACTIVE`, otherwise `ERR_PLAN_STATE_INVALID`, and no check-in of the plan may still be `PENDING`, otherwise `ERR_PENDING_CHECKINS`.
    PRD: Acceptance moves the check-in `PENDING → COMPLETED`, stamps `completed_at` from the logical clock, and sets `on_time` true when `completed_at` is at or before `due_at` — the boundary is inclusive, so a completion at exactly the due instant is on time.
    PRD: `compliance_score` is one hundred multiplied by `on_time_checkin_count` divided by `required_checkin_count`, less 15 for each concern recorded, floored at 0 and rounded half up to two decimal places.
    Design: Corner/validations/a_plan_cannot_close_while_any_child_check_in_is_still_pending
    """
    world = fixtures.world_with_active_plan(api, required_checkin_count=2, duration_days=30)
    first_id, second_id = world["check_in_ids"]
    assert world["plan"]["status"] == "ACTIVE"
    assert_instant(world["check_ins"][0]["due_at"], "2026-08-11T00:00:00Z")
    assert_instant(world["check_ins"][1]["due_at"], "2026-08-21T00:00:00Z")

    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    first = fixtures.complete_check_in(api, world, first_id)

    assert first["status"] == "COMPLETED"
    assert_instant(first["completed_at"], "2026-08-11T00:00:00Z")
    assert first["on_time"] is True

    refused = api.close_intervention_plan(
        world["p1_id"], {"closing_note": "Premature closure attempt."}, world["sup_headers"]
    )

    validate_error(refused, "ERR_PENDING_CHECKINS", 409)
    stalled = get_success_data(api.get_intervention_plan(world["p1_id"], world["sup_headers"]))
    assert stalled["status"] == "ACTIVE"
    # PRD: completing a check-in recomputes the plan's compliance_score, so one
    # on-time completion of the two required already reads 100 * 1 / 2 = 50.00.
    # The refused close leaves it exactly there and stamps no closed_at.
    assert_two_dp(stalled["compliance_score"], 50.00, label="compliance_score")
    assert stalled["closed_at"] is None
    assert stalled["completed_checkin_count"] == 1

    fixtures.set_clock(api, "2026-08-21T00:00:00Z")
    second = fixtures.complete_check_in(api, world, second_id)

    assert second["status"] == "COMPLETED"
    assert second["on_time"] is True

    closed = get_success_data(
        api.close_intervention_plan(
            world["p1_id"], {"closing_note": "Both check-ins complete."}, world["sup_headers"]
        )
    )

    assert closed["status"] == "CLOSED_SUCCESS"
    assert closed["completed_checkin_count"] == 2
    assert closed["on_time_checkin_count"] == 2
    assert closed["concern_count"] == 0
    assert_two_dp(closed["compliance_score"], 100.00, label="compliance_score")
    assert_instant(closed["closed_at"], "2026-08-21T00:00:00Z")

    alert = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert alert["status"] == "CLOSED_SUCCESS"
    assert_officer_ledgers(
        fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"]),
        open_alert_count=0,
        intervention_escalation_count=0,
    )


def test_the_identity_requirement_switches_on_the_intake_channel(api, world):
    """A public file without contact details and an anonymous file with a name both fail.

    PRD: When `intake_channel` is `PUBLIC` or `SUPERVISOR`, both `complainant_name` and `complainant_contact` must be present and non-empty; when it is `ANONYMOUS`, both must be absent.
    PRD: Either violation is `ERR_COMPLAINANT_IDENTITY_REQUIRED`.
    PRD: `intake_sequence` is a monotonic counter: each accepted intake takes the previous maximum plus 1, and the very first accepted intake takes 1.
    PRD: Anonymous intake is the exception: the sequence is still assigned, but `intake_reference_code` stays null, and an anonymous complainant consequently holds no credential with which to withdraw.
    Design: Corner/validations/the_identity_requirement_switches_on_the_intake_channel
    """
    nameless = factories.public_complaint_payload(
        world["patrol_unit_id"],
        narrative="Public complaint filed without any contact details.",
        incident_datetime="2026-07-20T18:00:00Z",
    )
    nameless.pop("complainant_name")
    nameless.pop("complainant_contact")

    validate_error(
        api.create_complaint(nameless, world["complainant_headers"]),
        "ERR_COMPLAINANT_IDENTITY_REQUIRED",
        422,
    )

    named_anonymous = factories.anonymous_complaint_payload(
        world["patrol_unit_id"],
        narrative="Anonymous complaint that names its author anyway.",
        incident_datetime="2026-07-20T18:00:00Z",
        complainant_name="Ira Fox",
        complainant_contact="ira@example.org",
    )

    validate_error(
        api.create_complaint(named_anonymous, world["complainant_headers"]),
        "ERR_COMPLAINANT_IDENTITY_REQUIRED",
        422,
    )

    anonymous = fixtures.file_anonymous_complaint(
        api,
        world,
        narrative="Anonymous complaint with no identifying details.",
        incident_datetime="2026-07-20T18:00:00Z",
    )

    assert anonymous["intake_channel"] == "ANONYMOUS"
    assert anonymous["complainant_name"] is None
    assert anonymous["complainant_contact"] is None
    assert anonymous["intake_reference_code"] is None
    assert anonymous["intake_sequence"] == 1
    assert anonymous["status"] == "SCREENING"

    identified = fixtures.file_public_complaint(
        api,
        world,
        narrative="Public complaint with full contact details.",
        incident_datetime="2026-07-20T18:00:00Z",
        complainant_demographic_code="DG_C",
    )

    assert identified["intake_channel"] == "PUBLIC"
    assert identified["complainant_name"] == "Ira Fox"
    assert identified["intake_sequence"] == anonymous["intake_sequence"] + 1
    assert identified["intake_reference_code"] == "CMP-000002"
    assert identified["status"] == "CLASSIFIED"
