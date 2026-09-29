"""Declared initial states, legal transitions, terminal lockdowns and bounded loops."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    assert_eis_run_counters,
    assert_instant,
    assert_investigation_window,
    assert_list_page,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"


def test_complaint_and_investigation_rows_start_in_their_declared_initial_states(api, world):
    """No client ever sees an intake before it has been screened or classified.

    PRD: A complaint's lifecycle formally begins at `INTAKE_RECEIVED`, but no client ever observes that value: inside the same intake request the complaint moves to `SCREENING` when `screening_required` is true, and to `CLASSIFIED` otherwise.
    PRD: On both paths `allegation_count`, `sustained_allegation_count` and `reclassification_count` start at 0, and `closed_at`, `retention_until` and `purged_at` are null.
    PRD: The new investigation records the `complaint_id` of the file it belongs to and is created in `UNASSIGNED` with `assigned_investigator_officer_id` null, `tolled_days` 0, `assignment_count` 0, `interview_held_count` 0, and `findings_submitted_at`, `suspended_at` and `closed_at` all null.
    Design: Corner/state_machines/complaint_and_investigation_rows_start_in_their_declared_initial_states
    """
    anonymous = fixtures.file_anonymous_complaint(
        api,
        world,
        narrative="Rude tone at a traffic stop.",
        incident_datetime="2026-07-20T18:00:00Z",
        reported_allegation_types=["DISCOURTESY"],
    )

    assert anonymous["status"] == "SCREENING"
    assert anonymous["screening_required"] is True
    assert anonymous["intake_reference_code"] is None

    supervisor_filed = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Reports not filed for four shifts.",
        reported_allegation_types=["NEGLECT_OF_DUTY"],
    )

    assert supervisor_filed["status"] == "CLASSIFIED"
    assert supervisor_filed["reclassification_count"] == 0
    assert supervisor_filed["sustained_allegation_count"] == 0
    assert supervisor_filed["closed_at"] is None
    assert supervisor_filed["retention_until"] is None
    assert supervisor_filed["purged_at"] is None
    assert supervisor_filed["version"] == 1

    unscreened, meta = fixtures.rows(
        api.list_complaints(world["cmdr_headers"], {"status": "INTAKE_RECEIVED"})
    )
    assert unscreened == []
    assert meta["total_count"] == 0

    allegation = fixtures.attach_allegation(
        api,
        world,
        supervisor_filed["id"],
        allegation_type="NEGLECT_OF_DUTY",
        offense_class="C",
        narrative="Reports for four shifts were never filed.",
    )
    assert allegation["disposition"] == "PENDING"

    investigation = fixtures.open_investigation(api, world, supervisor_filed["id"])

    assert investigation["status"] == "UNASSIGNED"
    assert investigation["complaint_id"] == supervisor_filed["id"]
    assert investigation["assigned_investigator_officer_id"] is None
    assert investigation["tolled_days"] == 0
    assert investigation["assignment_count"] == 0
    assert investigation["interview_held_count"] == 0
    assert investigation["overdue"] is False
    assert investigation["findings_submitted_at"] is None
    assert investigation["suspended_at"] is None
    assert investigation["closed_at"] is None


def test_screening_rejection_walks_the_declared_transition_and_starts_the_retention_clock(
    api, world
):
    """A rejected screen closes a file that never became a case, on the 730-day class.

    PRD: Rejecting a complaint that sits in `SCREENING` moves it `SCREENING → REJECTED_INTAKE`, and requires a `rejection_reason`.
    PRD: Three things happen together: `closed_at` is stamped from the logical clock, every allegation on the complaint is set to `disposition` `WITHDRAWN`, and `retention_until` is set to `closed_at` plus the withdrawal retention class of 730 whole days — two years for a file that never became a case.
    Design: Corner/state_machines/screening_rejection_walks_the_declared_transition_and_starts_the_retention_clock
    """
    anonymous = fixtures.file_anonymous_complaint(
        api,
        world,
        narrative="Rude tone at a traffic stop.",
        incident_datetime="2026-07-20T18:00:00Z",
        reported_allegation_types=["DISCOURTESY"],
    )
    assert anonymous["status"] == "SCREENING"
    assert anonymous["allegation_count"] == 0

    rejected = get_success_data(
        api.classify_complaint(
            anonymous["id"],
            factories.screening_payload(
                "REJECT",
                rejection_reason="No corroborating witness or recording could be identified.",
            ),
            world["cmdr_headers"],
        ),
        200,
    )

    assert rejected["status"] == "REJECTED_INTAKE"
    assert_instant(rejected["closed_at"], BASE_CLOCK, label="closed_at")
    assert_instant(rejected["retention_until"], "2028-07-31T00:00:00Z", label="retention_until")
    assert rejected["screening_required"] is True
    assert rejected["classification"] == "CLASS_III"
    assert rejected["priority"] == 3
    assert rejected["allegation_count"] == 0
    assert rejected["assigned_unit_id"] == world["ia_unit_id"]
    assert rejected["version"] == 2


def test_opening_an_investigation_enforces_each_declared_precondition(api, world):
    """An empty file cannot be opened, and an opened file cannot be opened twice.

    PRD: Two substantive preconditions follow: the complaint must carry at least one allegation, because an investigation with nothing to investigate is refused with `ERR_NO_ALLEGATIONS`, and no investigation may already exist for that complaint, because a second one would fork the case file and is refused with `ERR_INVESTIGATION_ALREADY_EXISTS`.
    PRD: `statutory_days` — the investigation window the state grants — is 180 days for `CLASS_I`, 121 days for `CLASS_II` and 90 days for `CLASS_III`.
    PRD: From those, `due_at` is the complaint's `received_at` advanced by `statutory_days` plus `tolled_days` whole days; at opening `tolled_days` is 0, so a Class I complaint received at the start of September 2026 is due at the end of February 2027.
    Design: Corner/state_machines/opening_an_investigation_enforces_each_declared_precondition
    """
    complaint = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Reports not filed for four shifts.",
        reported_allegation_types=["NEGLECT_OF_DUTY"],
    )
    assert complaint["status"] == "CLASSIFIED"
    assert complaint["classification"] == "CLASS_II"
    assert complaint["allegation_count"] == 0

    empty = api.open_investigation(
        complaint["id"],
        {"opening_note": "Opened with no allegation recorded yet."},
        world["cmdr_headers"],
    )

    validate_error(empty, "ERR_NO_ALLEGATIONS", 422)
    assert fixtures.read_complaint(api, complaint["id"], world["cmdr_headers"])["status"] == "CLASSIFIED"
    none_yet, meta = fixtures.rows(
        api.list_investigations(world["cmdr_headers"], {"complaint_id": complaint["id"]})
    )
    assert none_yet == []
    assert meta["total_count"] == 0

    fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        allegation_type="NEGLECT_OF_DUTY",
        offense_class="C",
        narrative="Reports for four shifts were never filed.",
    )
    investigation = validate_success(
        api.open_investigation(
            complaint["id"], {"opening_note": "Opened for assignment."}, world["cmdr_headers"]
        ),
        201,
    )

    assert fixtures.read_complaint(api, complaint["id"], world["cmdr_headers"])["status"] == "UNDER_INVESTIGATION"
    assert_investigation_window(
        investigation,
        statutory_days=121,
        required_certification_level=2,
        due_at="2026-11-30T00:00:00Z",
    )
    assert investigation["status"] == "UNASSIGNED"
    assert investigation["overdue"] is False

    duplicate = api.open_investigation(
        complaint["id"], {"opening_note": "Second opening attempt."}, world["cmdr_headers"]
    )

    # The first opening drove the complaint to UNDER_INVESTIGATION, so the second
    # attempt violates both the tier-8 complaint-state check and the tier-10
    # already-exists rule. PRD: "Validation proceeds strictly in ascending
    # priority tier; the first violated rule determines the response, and no
    # later rule is evaluated." Tier 8 therefore answers with
    # ERR_COMPLAINT_STATE_INVALID before tier 10 is reached.
    validate_error(duplicate, "ERR_COMPLAINT_STATE_INVALID", 409)
    still_one, meta = fixtures.rows(
        api.list_investigations(world["cmdr_headers"], {"complaint_id": complaint["id"]})
    )
    assert [row["id"] for row in still_one] == [investigation["id"]]
    assert meta["total_count"] == 1


def test_investigation_calls_out_of_order_are_refused_by_the_state_ladder(api):
    """Tolling, closing and findings all aim at states that declare no such trigger.

    PRD: Suspension is legal only from `IN_PROGRESS` and produces `IN_PROGRESS → TOLLED`, stamping `suspended_at` from the logical clock.
    PRD: Resumption is legal from `TOLLED` and from `PENDING_REVIEW`; from anything else, and likewise for a suspension attempted from a status other than `IN_PROGRESS`, the answer is `ERR_INVESTIGATION_STATE_INVALID`.
    PRD: The investigation must be `IN_PROGRESS`, otherwise `ERR_INVESTIGATION_STATE_INVALID`, and the owning complaint must correspondingly be `UNDER_INVESTIGATION`.
    PRD: The investigation must be in `PENDING_REVIEW`, and if any allegation is still `PENDING` the close is refused with `ERR_PENDING_DISPOSITIONS`.
    Design: Corner/state_machines/investigation_calls_out_of_order_are_refused_by_the_state_ladder
    """
    world = fixtures.world_with_investigation(api, offense_class="C")
    assert world["investigation"]["status"] == "UNASSIGNED"

    early_suspend = api.toll_investigation(
        world["i1_id"],
        factories.tolling_payload("SUSPEND", tolling_reason="Suspend before anyone is assigned."),
        world["cmdr_headers"],
    )
    validate_error(early_suspend, "ERR_INVESTIGATION_STATE_INVALID", 409)

    early_close = api.close_investigation(
        world["i1_id"], {"closing_note": "Close before anyone is assigned."}, world["cmdr_headers"]
    )
    validate_error(early_close, "ERR_INVESTIGATION_STATE_INVALID", 409)

    assigned = fixtures.assign_investigation(
        api, world, world["i1_id"], world["i1_v0"], world["inv_a_id"]
    )
    assert assigned["status"] == "ASSIGNED"
    assert assigned["assignment_count"] == 1
    assert assigned["version"] == 2

    early_findings = api.submit_findings(
        world["i1_id"],
        factories.findings_payload(
            [factories.finding_entry(world["a1_id"], 60, 40)],
            summary="Findings before any interview or IN_PROGRESS status.",
        ),
        world["inv_a_headers"],
    )
    validate_error(early_findings, "ERR_INVESTIGATION_STATE_INVALID", 409)

    early_resume = api.toll_investigation(
        world["i1_id"],
        factories.tolling_payload("RESUME", tolling_reason="Resume from ASSIGNED."),
        world["cmdr_headers"],
    )
    validate_error(early_resume, "ERR_INVESTIGATION_STATE_INVALID", 409)

    unmoved = fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])
    assert unmoved["status"] == "ASSIGNED"
    assert unmoved["tolled_days"] == 0
    assert unmoved["suspended_at"] is None
    assert unmoved["findings_submitted_at"] is None
    assert unmoved["version"] == 2
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=1
    )
    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert_two_dp(allegation["evidence_weight_for"], 0, label="evidence_weight_for")
    assert allegation["preponderance_met"] is False


def test_a_withdrawn_complaint_refuses_every_further_lifecycle_call(api, world):
    """Four lifecycle calls report the state; the purge gets past it and reports the clock.

    PRD: A `Complainant` or a `Supervisor` supplies the `intake_reference_code` issued at intake plus an optional `withdrawal_reason`, and the complaint may be withdrawn from `CLASSIFIED`, from `UNDER_INVESTIGATION` or from `ADJUDICATION` — any other status is `ERR_COMPLAINT_STATE_INVALID`.
    PRD: Attempting to attach an allegation to a complaint in any other state is `ERR_COMPLAINT_STATE_INVALID`.
    PRD: The complaint must be `CLOSED` or `WITHDRAWN` with `purged_at` still null, otherwise `ERR_COMPLAINT_NOT_PURGEABLE`.
    PRD: And the logical clock must have reached `retention_until`, a non-strict comparison so that a purge at exactly the retention instant is allowed, otherwise `ERR_RETENTION_NOT_EXPIRED`.
    Design: Corner/state_machines/a_withdrawn_complaint_refuses_every_further_lifecycle_call
    """
    narrative = "Officer ignored a report request."
    complaint = fixtures.file_public_complaint(
        api,
        world,
        narrative=narrative,
        reported_allegation_types=["NEGLECT_OF_DUTY"],
        complainant_demographic_code="DG_B",
    )
    code = complaint["intake_reference_code"]

    withdrawn = fixtures.withdraw_complaint(
        api,
        world,
        complaint["id"],
        intake_reference_code=code,
        headers=world["complainant_headers"],
        withdrawal_reason="Matter resolved directly with the district commander.",
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert_instant(withdrawn["closed_at"], BASE_CLOCK, label="closed_at")
    assert_instant(withdrawn["retention_until"], "2028-07-31T00:00:00Z", label="retention_until")

    again = api.withdraw_complaint(
        complaint["id"],
        factories.withdrawal_payload(code, withdrawal_reason="Second withdrawal attempt."),
        world["complainant_headers"],
    )
    validate_error(again, "ERR_COMPLAINT_STATE_INVALID", 409)

    reclassify = api.classify_complaint(
        complaint["id"],
        factories.screening_payload("ACCEPT", classification_override="CLASS_I"),
        world["cmdr_headers"],
    )
    validate_error(reclassify, "ERR_COMPLAINT_STATE_INVALID", 409)

    reopen = api.open_investigation(
        complaint["id"], {"opening_note": "Open a withdrawn file."}, world["cmdr_headers"]
    )
    validate_error(reopen, "ERR_COMPLAINT_STATE_INVALID", 409)

    late_allegation = api.create_allegation(
        complaint["id"],
        factories.allegation_payload(
            world["subj_id"],
            allegation_type="NEGLECT_OF_DUTY",
            narrative="Late allegation on a withdrawn file.",
            offense_class="C",
        ),
        world["cmdr_headers"],
    )
    validate_error(late_allegation, "ERR_COMPLAINT_STATE_INVALID", 409)

    early_purge = api.purge_complaint(
        complaint["id"],
        {"purge_reason": "Purge before the retention clock expires."},
        world["custodian_headers"],
    )
    validate_error(early_purge, "ERR_RETENTION_NOT_EXPIRED", 409)

    final = fixtures.read_complaint(api, complaint["id"], world["custodian_headers"])
    assert final["status"] == "WITHDRAWN"
    assert final["classification"] == "CLASS_II"
    assert final["allegation_count"] == 0
    assert final["purged_at"] is None
    assert final["narrative"] == narrative


def test_a_replayed_sweep_neither_creates_nor_promotes_a_second_alert(api):
    """Both sweep guards hold on unchanged event data, so only the run sequence moves.

    PRD: For each officer whose band is not `NONE` and who has no alert already open, it creates an alert with `trigger_source` `EIS_RUN` and raises `open_alert_count` by 1.
    PRD: It promotes an alert `OPEN → PLAN_REQUIRED` when the recomputed band reaches `ALERT` or `CRITICAL`, setting `review_due_at` to the promotion instant plus 30 whole days — the same 30-day rule that sets `review_due_at` at creation.
    PRD: The run reports six counters: the `run_sequence` of this run, the `evaluated_officer_count`, the number of `alerts_created`, the number of `alerts_promoted`, the number of `checkins_missed`, and the number of `disclosures_expired`.
    Design: Corner/state_machines/a_replayed_sweep_neither_creates_nor_promotes_a_second_alert
    """
    world = fixtures.world_with_scored_officer(api, pattern=fixtures.THREE_FORCE_EVENT_PATTERN)

    scored = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_risk(scored, eis_score=55.00, eis_alert_level="ALERT")
    assert_officer_ledgers(scored, open_alert_count=1)

    first = fixtures.run_sweep(api, world, officer_id=world["subj_id"])
    assert_eis_run_counters(
        first,
        run_sequence=1,
        evaluated_officer_count=1,
        alerts_created=0,
        alerts_promoted=1,
        checkins_missed=0,
        disclosures_expired=0,
    )

    replay = fixtures.run_sweep(api, world, officer_id=world["subj_id"])
    assert_eis_run_counters(replay, run_sequence=2, alerts_created=0, alerts_promoted=0)

    alerts, meta = fixtures.rows(
        api.list_eis_alerts(world["cmdr_headers"], {"officer_id": world["subj_id"]})
    )
    assert_list_page(meta, 10, 0, 1, False)
    alert = alerts[0]
    assert alert["status"] == "PLAN_REQUIRED"
    assert_two_dp(alert["composite_score"], 55.00, label="composite_score")
    assert alert["alert_level"] == "ALERT"
    assert alert["score_variant"] == "ROLLING_12M"
    assert alert["breached_indicators"] == ["FORCE_COUNT"]
    assert alert["plan_count"] == 0
    assert_instant(alert["review_due_at"], "2026-08-31T00:00:00Z", label="review_due_at")
    assert_officer_ledgers(
        fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"]), open_alert_count=1
    )


def test_reclassification_self_loop_stops_at_the_declared_maximum(api, world):
    """The loop turns exactly twice, re-routing each turn, and the third turn is refused.

    PRD: A reclassification is accepted only when `reclassification_count` is strictly less than 2 and the supplied `classification_override` differs from the currently stored `classification`; either failure is `ERR_MAX_RECLASSIFICATIONS_REACHED`.
    PRD: On acceptance `reclassification_count` rises by 1, and `priority` and `assigned_unit_id` are recomputed from the new classification by the same five-step rule — so a complaint reclassified upward to `CLASS_I` is pulled away from its subject unit and re-routed to internal affairs.
    PRD: The same 365-day figure is stored forward as `statute_expires_at`, which is `incident_datetime` plus 365 whole days — the deadline for filing about this incident, entirely separate from the investigation's own due date.
    Design: Corner/state_machines/reclassification_self_loop_stops_at_the_declared_maximum
    """
    complaint = fixtures.file_public_complaint(
        api,
        world,
        narrative="Officer ignored a report request.",
        reported_allegation_types=["NEGLECT_OF_DUTY"],
        complainant_demographic_code="DG_B",
    )
    assert complaint["classification"] == "CLASS_II"
    assert complaint["reclassification_count"] == 0
    assert complaint["assigned_unit_id"] == world["patrol_unit_id"]
    assert_instant(
        complaint["statute_expires_at"], "2027-07-15T20:00:00Z", label="statute_expires_at"
    )

    def reclassify(override):
        return api.classify_complaint(
            complaint["id"],
            factories.screening_payload("ACCEPT", classification_override=override),
            world["cmdr_headers"],
        )

    repeat = reclassify("CLASS_II")
    validate_error(repeat, "ERR_MAX_RECLASSIFICATIONS_REACHED", 409)
    assert fixtures.read_complaint(api, complaint["id"], world["cmdr_headers"])["reclassification_count"] == 0

    first = get_success_data(reclassify("CLASS_I"), 200)
    assert first["classification"] == "CLASS_I"
    assert first["priority"] == 1
    assert first["reclassification_count"] == 1
    assert first["assigned_unit_id"] == world["ia_unit_id"]

    second = get_success_data(reclassify("CLASS_III"), 200)
    assert second["classification"] == "CLASS_III"
    assert second["priority"] == 3
    assert second["reclassification_count"] == 2
    assert second["assigned_unit_id"] == world["patrol_unit_id"]
    assert second["screening_required"] is False
    assert second["status"] == "CLASSIFIED"

    exhausted = reclassify("CLASS_I")
    validate_error(exhausted, "ERR_MAX_RECLASSIFICATIONS_REACHED", 409)

    frozen = fixtures.read_complaint(api, complaint["id"], world["cmdr_headers"])
    assert frozen["classification"] == "CLASS_III"
    assert frozen["reclassification_count"] == 2
    assert_instant(frozen["statute_expires_at"], "2027-07-15T20:00:00Z", label="statute_expires_at")
    investigations, meta = fixtures.rows(
        api.list_investigations(world["cmdr_headers"], {"complaint_id": complaint["id"]})
    )
    assert investigations == []
    assert meta["total_count"] == 0


def a_case_with_one_held_and_one_scheduled_session(api):
    """A public file under investigation, one interview already held and one still booked."""
    world = fixtures.seed_reference_data(api, room_capacity=2)
    complaint = fixtures.file_public_complaint(
        api,
        world,
        narrative="Officer ignored a report request.",
        reported_allegation_types=["NEGLECT_OF_DUTY"],
        complainant_demographic_code="DG_B",
    )
    allegation = fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        allegation_type="NEGLECT_OF_DUTY",
        offense_class="C",
        narrative="Reports for four shifts were never filed.",
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session_a = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:00:00Z",
        notice_served_at=BASE_CLOCK,
        representation_status="WAIVED",
    )
    session_b = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        scheduled_start="2026-08-05T11:01:00Z",
        scheduled_end="2026-08-05T12:01:00Z",
        notice_served_at=BASE_CLOCK,
        representation_status="REP_PRESENT",
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(
        api,
        world,
        session_a["id"],
        interview_summary="Officer answered on the record.",
        representation_status="WAIVED",
    )
    world.update(
        {
            "c_id": complaint["id"],
            "c_code": complaint["intake_reference_code"],
            "narrative": complaint["narrative"],
            "a1_id": allegation["id"],
            "i1_id": investigation["id"],
            "sa_id": session_a["id"],
            "sb_id": session_b["id"],
        }
    )
    return world


def test_withdrawing_a_complaint_cancels_only_the_non_terminal_children(api):
    """The cascade voids the case and cancels the booking, but never rewrites the held one.

    PRD: Withdrawing from `UNDER_INVESTIGATION` also drives the investigation to `VOIDED` and stamps its `closed_at`; because the investigation became `VOIDED`, every interview session on it in `SCHEDULED` or `POSTPONED` moves to `CANCELLED` and releases the room and officer time it was holding; and because the investigation left the open set, the assignee's `open_case_load` is decremented by 1.
    PRD: `WITHDRAWN` is written by the system when the owning complaint moves to `WITHDRAWN` or `REJECTED_INTAKE`, and the allegation's `disposed_at` in that case is set to the complaint's `closed_at` rather than to the clock.
    Design: Corner/state_machines/withdrawing_a_complaint_cancels_only_the_non_terminal_children
    """
    world = a_case_with_one_held_and_one_scheduled_session(api)
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["status"] == "IN_PROGRESS"

    withdrawn = fixtures.withdraw_complaint(
        api,
        world,
        world["c_id"],
        intake_reference_code=world["c_code"],
        headers=world["complainant_headers"],
        withdrawal_reason="Complainant withdrew after a direct resolution.",
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert_instant(withdrawn["closed_at"], "2026-08-05T09:00:00Z", label="closed_at")
    assert_instant(withdrawn["retention_until"], "2028-08-04T09:00:00Z", label="retention_until")
    assert withdrawn["narrative"] == world["narrative"]

    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert allegation["disposition"] == "WITHDRAWN"
    assert_instant(allegation["disposed_at"], "2026-08-05T09:00:00Z", label="disposed_at")

    voided = fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])
    assert voided["status"] == "VOIDED"
    assert_instant(voided["closed_at"], "2026-08-05T09:00:00Z", label="investigation.closed_at")
    assert voided["interview_held_count"] == 1

    cancelled = fixtures.read_session(api, world["sb_id"], world["inv_a_headers"])
    assert cancelled["status"] == "CANCELLED"
    held = fixtures.read_session(api, world["sa_id"], world["inv_a_headers"])
    assert held["status"] == "HELD"
    assert_instant(held["held_at"], "2026-08-05T09:00:00Z", label="held_at")

    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=0
    )
    rows_cancelled, meta = fixtures.rows(
        api.list_interview_sessions(
            world["inv_a_headers"], {"investigation_id": world["i1_id"], "status": "CANCELLED"}
        )
    )
    assert [row["id"] for row in rows_cancelled] == [world["sb_id"]]
    assert meta["total_count"] == 1


def test_a_successful_plan_closure_bubbles_up_and_closes_its_alert(api):
    """The alert has no closing endpoint of its own; the plan's close carries it over.

    PRD: Activation accepts an optional `activation_note`, moves the plan `DRAFT → ACTIVE`, stamps `activated_at` from the logical clock, sets `end_date` to `activated_at` plus `duration_days` whole days, materialises the check-in schedule, and moves the owning alert `PLAN_REQUIRED → PLAN_ACTIVE`.
    PRD: One check-in row is then created for each `sequence_index` from 1 up to and including `required_checkin_count`, with `due_at` equal to `activated_at` plus the interval multiplied by that index, in whole days, carrying the time of day of `activated_at`.
    PRD: Acceptance moves the check-in `PENDING → COMPLETED`, stamps `completed_at` from the logical clock, and sets `on_time` true when `completed_at` is at or before `due_at` — the boundary is inclusive, so a completion at exactly the due instant is on time.
    PRD: The plan moves `ACTIVE → CLOSED_SUCCESS` when `compliance_score` is at least 80 — the comparison is non-strict, so a score of exactly 80.00 succeeds — **and** no early-intervention alert other than the plan's own was created for the officer with `created_at` inside the closed interval running from `activated_at` to the logical clock.
    PRD: The owning alert moves `PLAN_ACTIVE → CLOSED_SUCCESS` and the officer's `open_alert_count` falls by 1.
    Design: Corner/state_machines/a_successful_plan_closure_bubbles_up_and_closes_its_alert
    """
    world = fixtures.world_with_scored_officer(api, pattern=fixtures.THREE_FORCE_EVENT_PATTERN)
    fixtures.run_sweep(api, world, officer_id=world["subj_id"])
    alert = fixtures.alert_for_officer(api, world, world["subj_id"])
    assert alert["status"] == "PLAN_REQUIRED"

    plan = validate_success(
        api.create_intervention_plan(
            alert["id"],
            factories.intervention_plan_payload(
                alert["version"],
                world["sup_id"],
                required_checkin_count=2,
                duration_days=30,
                interventions=["COUNSELING", "PEER_REVIEW"],
            ),
            world["sup_headers"],
        ),
        201,
    )

    assert plan["status"] == "DRAFT"
    assert fixtures.read_alert(api, alert["id"], world["cmdr_headers"])["plan_count"] == 1

    activated = get_success_data(
        api.activate_intervention_plan(
            plan["id"], {"activation_note": "Monitoring starts today."}, world["sup_headers"]
        ),
        200,
    )

    assert activated["status"] == "ACTIVE"
    assert_instant(activated["activated_at"], BASE_CLOCK, label="activated_at")
    assert_instant(activated["end_date"], "2026-08-31T00:00:00Z", label="end_date")
    assert fixtures.read_alert(api, alert["id"], world["cmdr_headers"])["status"] == "PLAN_ACTIVE"

    check_ins, meta = fixtures.rows(api.list_plan_check_ins(plan["id"], world["sup_headers"]))
    assert meta["total_count"] == 2
    assert check_ins[0]["sequence_index"] == 1
    assert_instant(check_ins[0]["due_at"], "2026-08-11T00:00:00Z", label="check-in 1 due_at")
    assert check_ins[1]["sequence_index"] == 2
    assert_instant(check_ins[1]["due_at"], "2026-08-21T00:00:00Z", label="check-in 2 due_at")

    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    first = fixtures.complete_check_in(api, world, check_ins[0]["id"])
    assert first["status"] == "COMPLETED"
    assert first["outcome"] == "SATISFACTORY"
    assert first["on_time"] is True

    fixtures.set_clock(api, "2026-08-21T00:00:00Z")
    second = fixtures.complete_check_in(api, world, check_ins[1]["id"])
    assert second["status"] == "COMPLETED"
    assert second["on_time"] is True

    monitored = fixtures.read_plan(api, plan["id"], world["sup_headers"])
    assert monitored["completed_checkin_count"] == 2
    assert monitored["on_time_checkin_count"] == 2
    assert monitored["concern_count"] == 0

    closed = get_success_data(
        api.close_intervention_plan(
            plan["id"], {"closing_note": "Both check-ins met on time."}, world["sup_headers"]
        ),
        200,
    )

    assert closed["status"] == "CLOSED_SUCCESS"
    assert_two_dp(closed["compliance_score"], 100.00, label="compliance_score")
    assert_instant(closed["closed_at"], "2026-08-21T00:00:00Z", label="plan.closed_at")
    assert fixtures.read_alert(api, alert["id"], world["cmdr_headers"])["status"] == "CLOSED_SUCCESS"

    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(officer, open_alert_count=0, intervention_escalation_count=0)
    assert_officer_risk(officer, eis_alert_level="ALERT")
