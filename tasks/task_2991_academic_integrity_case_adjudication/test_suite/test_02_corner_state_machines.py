"""Corner-design tests for the `state_machines` section (queue B).

Every test in this file translates exactly one non-stub instance of
`SCAFFOLD_CORNER_DESIGN.yaml`'s `state_machines` section, and the last line of
each docstring names that instance.

The harness restarts the API server before every individual test, so each test
rebuilds its whole precondition chain through public endpoints and the logical
clock starts at `2026-08-01T00:00:00Z` (PRD §2.4).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId


def test_fresh_case_starts_at_the_origin_of_both_state_dimensions(api):
    """PRD §3.3: "A newly created report has `status` `DRAFT`, `submitted_at` null,
    `returned_at` null, `triaged_at` null, `triage_note` null, `resubmission_count` 0,
    `evidence_strength_score` 0.00 and `evidence_complete` false."
    PRD §3.4: "The new case copies `student_id` and `offering_id` from the report, sets
    `origin` to `OFFICE_INTAKE`, `pathway` to `UNASSIGNED`, `adjudication_status` to
    `INTAKE_REVIEW`, `notation_status` to `NOT_APPLICABLE`, `responsibility_finding` to
    `UNDETERMINED`, `finding_basis` to `NONE`, `hearing_round` to 0, `overturned` to
    false, `decided_at` to null, `panel_severity_recommendation` to null,
    `pre_appeal_adjudication_status` to null, `dismiss_reason` to null,
    `expungement_eligible_at` to null and `version` to 1."
    PRD §3.4: "Finally the offering's department has `open_case_count` increased by one."
    PRD §3.5: "The new engagement has `status` `REQUESTED`, `speaking_rights` false,
    `reconfirmation_required` false and `decision_reason` null."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    world = fixtures.seed_actors()

    report = fixtures.create_report(
        world["offering"]["id"], world["student"]["id"], world["reporter_h"]
    )
    assert report["status"] == "DRAFT", "a report starts in DRAFT (PRD §3.3)"
    assert report["submitted_at"] is None
    assert report["triaged_at"] is None
    assert report["returned_at"] is None
    assert report["triage_note"] is None
    assert report["resubmission_count"] == 0

    fixtures.attach_similarity_evidence(report["id"], world["reporter_h"])
    fixtures.submit_report(report["id"], world["reporter_h"])
    fixtures.triage_report(report["id"], "ACCEPT", headers=world["officer"])
    case = fixtures.open_case(report["id"], world["officer"])
    assertions.assert_case(case)

    # Both dimensions sit at their own declared origin at the same moment.
    assert case["adjudication_status"] == "INTAKE_REVIEW"
    assert case["notation_status"] == "NOT_APPLICABLE"
    assert case["pathway"] == "UNASSIGNED"
    assert case["responsibility_finding"] == "UNDETERMINED"
    assert case["finding_basis"] == "NONE"
    assert case["origin"] == "OFFICE_INTAKE"
    assert case["hearing_round"] == 0
    assert case["overturned"] is False
    assert case["decided_at"] is None
    assert case["panel_severity_recommendation"] is None
    assert case["pre_appeal_adjudication_status"] is None
    assert case["dismiss_reason"] is None
    assert case["expungement_eligible_at"] is None
    assert case["version"] == 1

    # The same origin is what a re-read reports.
    stored = validate_success(api.get_case(case["id"], world["officer"]))
    assert stored["adjudication_status"] == "INTAKE_REVIEW"
    assert stored["notation_status"] == "NOT_APPLICABLE"
    assert stored["version"] == 1

    engagement = validate_success(
        api.create_advisor_engagement(
            factories.advisor_engagement_payload(case["id"]), world["student_h"]
        ),
        201,
    )
    assertions.assert_advisor_engagement(engagement)
    assert engagement["status"] == "REQUESTED"
    assert engagement["speaking_rights"] is False
    assert engagement["reconfirmation_required"] is False
    assert engagement["decision_reason"] is None

    department = validate_success(
        api.get_department(world["dept"]["id"], world["officer"])
    )
    assert department["open_case_count"] == 1, (
        "opening the case is the only ledger move the create performs (PRD §3.4)"
    )


def test_allegation_notice_advances_the_case_and_writes_every_side_effect(api):
    """PRD §3.5: "Every notice records `sent_at` from the current logical clock,
    computes `response_deadline_at` as `sent_at` plus `response_window_days` days, and
    starts with `acknowledged_at` null."
    PRD §3.5: "On success the notice is created, the case's notified instant is set to
    the notice's `sent_at`, `adjudication_status` becomes `NOTIFIED`, and the case's
    `version` advances."
    PRD §3.4: "The office sets `pathway` to `INFORMAL` or `FORMAL` on a case in
    `INTAKE_REVIEW` or `NOTIFIED`."

    Design: Corner/state_machines/sending_the_allegation_notice_advances_the_case_and_writes_every_declared_side_effect
    """
    world = fixtures.seed_case()
    case_id = world["case"]["id"]
    assert world["case"]["version"] == 1

    # Effect one: the pathway write moves `pathway` and nothing else.
    after_pathway = validate_success(
        api.set_case_pathway(case_id, factories.pathway_payload("FORMAL"), world["officer"])
    )
    assert after_pathway["pathway"] == "FORMAL"
    assert after_pathway["adjudication_status"] == "INTAKE_REVIEW", (
        "setting the pathway is not a notification"
    )
    assert after_pathway["version"] == 2

    # Effect two: the notice row itself.
    notice = validate_success(
        api.create_case_notification(
            case_id,
            factories.notification_payload("ALLEGATION_NOTICE", 5),
            world["officer"],
        ),
        201,
    )
    assertions.assert_notification(notice)
    assert notice["kind"] == "ALLEGATION_NOTICE"
    assert notice["case_id"] == case_id
    assertions.assert_instant_equals(notice["sent_at"], "2026-08-01T00:00:00Z", "sent_at")
    assert notice["acknowledged_at"] is None
    assert notice["response_window_days"] == 5
    assertions.assert_instant_equals(
        notice["response_deadline_at"], "2026-08-06T00:00:00Z", "response_deadline_at"
    )

    # Effect three: the case advanced exactly one step and bumped once.
    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["adjudication_status"] == "NOTIFIED"
    assert stored["pathway"] == "FORMAL"
    assert stored["version"] == 3, "one bump for the pathway write, one for the notice"

    rows, meta = assertions.validate_list(
        api.list_case_notifications(case_id, world["student_h"])
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [notice["id"]]


def test_report_state_machine_refuses_the_four_triggers_its_state_forbids(api):
    """PRD §2.9 rank 11: "report status does not admit the operation, on
    `POST /integrity/reports/{id}/submit`, `POST /integrity/reports/{id}/triage`,
    `POST /integrity/evidence-items`, `POST /integrity/cases` and
    `POST /integrity/cases/legacy-import` → `ERR_REPORT_STATE_INVALID`."
    PRD §3.3: "Office triage acts on a `SUBMITTED` report with a `decision` of
    `ACCEPT`, `RETURN_FOR_INFO` or `REJECT_INSUFFICIENT` and a `triage_note`."
    PRD §3.3: "Evidence items are attached to a report that is in `DRAFT` or
    `RETURNED_FOR_INFO`, and only by the report's own reporter."
    PRD §3.4: "The report must exist and its `status` must be `ACCEPTED`, otherwise
    `ERR_REPORT_STATE_INVALID`"

    Design: Corner/state_machines/each_state_machine_rejects_the_triggers_its_current_state_does_not_admit
    """
    world = fixtures.seed_actors()

    # R2 stays in DRAFT with one exhibit; R3 is SUBMITTED and untriaged.
    student_b = fixtures.create_student(world["officer"])
    report_2 = fixtures.create_report(
        world["offering"]["id"], student_b["id"], world["reporter_h"]
    )
    fixtures.attach_similarity_evidence(report_2["id"], world["reporter_h"])

    student_c = fixtures.create_student(world["officer"])
    report_3 = fixtures.create_report(
        world["offering"]["id"], student_c["id"], world["reporter_h"]
    )
    fixtures.attach_similarity_evidence(report_3["id"], world["reporter_h"])
    submitted = fixtures.submit_report(report_3["id"], world["reporter_h"])
    assert submitted["status"] == "SUBMITTED"

    # Re-submitting a SUBMITTED report: submit admits DRAFT or RETURNED_FOR_INFO.
    validate_error(
        api.submit_report(report_3["id"], world["reporter_h"]),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
    )
    # Triaging a DRAFT report: triage requires SUBMITTED.
    validate_error(
        api.triage_report(
            report_2["id"], factories.triage_payload("ACCEPT", "Too early."), world["officer"]
        ),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
    )
    # Attaching evidence after submission: attachment requires DRAFT/RETURNED_FOR_INFO.
    validate_error(
        api.create_evidence_item(
            factories.document_evidence_payload(report_3["id"]), world["reporter_h"]
        ),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
    )
    # Opening a case from a SUBMITTED report: case creation requires ACCEPTED.
    validate_error(
        api.create_case(factories.case_payload(report_3["id"]), world["officer"]),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
    )

    still_submitted = validate_success(api.get_report(report_3["id"], world["officer"]))
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["resubmission_count"] == 0
    assert still_submitted["triaged_at"] is None
    still_draft = validate_success(api.get_report(report_2["id"], world["officer"]))
    assert still_draft["status"] == "DRAFT"
    _, meta = assertions.validate_list(api.list_cases(world["officer"]))
    assert meta["total_count"] == 0, "no refusal created a case"


def test_second_case_and_second_pathway_write_each_name_their_own_error(api):
    """PRD §3.4: "if a case already exists for that report the request is rejected with
    `ERR_CASE_ALREADY_OPENED`"
    PRD §3.4: "The field can be set exactly once by this operation; a second attempt is
    rejected with `ERR_CASE_PATHWAY_ALREADY_SET`."
    PRD §3.7: "The case's `adjudication_status` must be `NOTIFIED` or `FORMAL_REFERRED`,
    and its `pathway` must be `FORMAL`, otherwise `ERR_CASE_PATHWAY_NOT_SET`."

    Design: Corner/state_machines/each_state_machine_rejects_the_triggers_its_current_state_does_not_admit
    """
    world = fixtures.seed_notified_case(response_window_days=5)
    case_id = world["case"]["id"]

    validate_error(
        api.create_case(factories.case_payload(world["report"]["id"]), world["officer"]),
        ApiErrorId.ERR_CASE_ALREADY_OPENED,
    )

    # NOTIFIED still admits the first pathway write.
    first = validate_success(
        api.set_case_pathway(case_id, factories.pathway_payload("FORMAL"), world["officer"])
    )
    assert first["pathway"] == "FORMAL"
    version_after_first = first["version"]

    validate_error(
        api.set_case_pathway(
            case_id, factories.pathway_payload("INFORMAL"), world["officer"]
        ),
        ApiErrorId.ERR_CASE_PATHWAY_ALREADY_SET,
    )
    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["pathway"] == "FORMAL", "the refused write left the pathway alone"
    assert stored["version"] == version_after_first

    # The scheduling call the same case refused before now succeeds, which proves
    # the earlier refusals were about state and not about the payload.
    fixtures.seed_panel(world)
    fixtures.schedule_hearing(world)
    assert world["session"]["status"] == "SCHEDULED"
    _, meta = assertions.validate_list(api.list_cases(world["officer"]))
    assert meta["total_count"] == 1


def test_hearing_scheduling_on_an_unassigned_pathway_reports_pathway_not_set(api):
    """PRD §3.7: "The case's `adjudication_status` must be `NOTIFIED` or
    `FORMAL_REFERRED`, and its `pathway` must be `FORMAL`, otherwise
    `ERR_CASE_PATHWAY_NOT_SET`."
    PRD §2.9 rank 15: "the case's `pathway` is `UNASSIGNED` or is set to the pathway the
    operation does not belong to, on `POST /integrity/cases/{id}/informal-resolution`,
    `POST /integrity/hearing-sessions` and `POST /integrity/appeals/{id}/decide` with a
    remand outcome → `ERR_CASE_PATHWAY_NOT_SET`."

    Design: Corner/state_machines/each_state_machine_rejects_the_triggers_its_current_state_does_not_admit
    """
    world = fixtures.seed_notified_case(response_window_days=5)
    fixtures.seed_panel(world)
    case_before = fixtures.read_case(world["case"]["id"], world["officer"])
    assert case_before["adjudication_status"] == "NOTIFIED"
    assert case_before["pathway"] == "UNASSIGNED"

    validate_error(
        api.create_hearing_session(
            factories.hearing_session_payload(
                world["case"]["id"],
                world["room"]["id"],
                world["chair"]["id"],
                [p["id"] for p in world["panelists"]],
                fixtures.SESSION_START,
                fixtures.SESSION_END,
            ),
            world["officer"],
        ),
        ApiErrorId.ERR_CASE_PATHWAY_NOT_SET,
    )

    case_after = fixtures.read_case(world["case"]["id"], world["officer"])
    assert case_after["adjudication_status"] == "NOTIFIED"
    assert case_after["hearing_round"] == 0
    assert case_after["version"] == case_before["version"]
    room = validate_success(api.get_hearing_room(world["room"]["id"], world["officer"]))
    assert room["booked_minutes_total"] == 0, "a rejected schedule reserves no minutes"


def test_replayed_acknowledgement_keeps_the_first_acknowledged_at(api):
    """PRD §3.5: "The student named by the case's `student_id` may acknowledge a notice,
    which sets `acknowledged_at` to the current logical clock; a second acknowledgement
    is rejected with `ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED`."
    PRD §2.9: "Every rule is evaluated before any side effect is applied, and no partial
    write is ever observable: a rejected request leaves the store byte-identical to its
    pre-request state, including every derived counter and ledger."

    Design: Corner/state_machines/replaying_any_one_shot_trigger_returns_that_machines_own_already_done_error
    """
    world = fixtures.seed_notified_case(response_window_days=5)
    fixtures.acknowledge_notice(world)
    notice = world["notice"]
    assertions.assert_instant_equals(
        notice["acknowledged_at"], "2026-08-01T00:00:00Z", "acknowledged_at"
    )
    version_after_first = notice["version"]

    # The clock moves on, so a second stamp would be plainly visible.
    fixtures.set_clock("2026-08-20T10:05:00Z", world["officer"])
    validate_error(
        api.acknowledge_notification(notice["id"], world["student_h"]),
        ApiErrorId.ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED,
    )

    stored = validate_success(api.get_notification(notice["id"], world["officer"]))
    assertions.assert_instant_equals(
        stored["acknowledged_at"], "2026-08-01T00:00:00Z", "acknowledged_at"
    )
    assert stored["version"] == version_after_first


def test_replayed_advisor_review_leaves_the_engagement_approved(api):
    """PRD §3.5: "Reviewing an engagement that is not `REQUESTED` is rejected with
    `ERR_ADVISOR_ENGAGEMENT_STATE_INVALID`."
    PRD §3.5: "`speaking_rights` as a derived field is true exactly when `status` is
    `APPROVED`, `advisor_kind` is `ATTORNEY`, and the case's `pathway` is `FORMAL`; in
    every other combination it is false."

    Design: Corner/state_machines/replaying_any_one_shot_trigger_returns_that_machines_own_already_done_error
    """
    world = fixtures.seed_notified_case(response_window_days=5)
    fixtures.request_advisor(world, advisor_kind="FACULTY_ADVISOR")
    fixtures.review_advisor(world, "APPROVE")
    engagement = world["engagement"]
    assert engagement["status"] == "APPROVED"
    assert engagement["speaking_rights"] is False, "a faculty advisor never speaks"
    assert engagement["reconfirmation_required"] is False
    version_after_first = engagement["version"]

    fixtures.set_clock("2026-08-20T10:05:00Z", world["officer"])
    validate_error(
        api.review_advisor_engagement(
            engagement["id"],
            factories.review_payload("DENY", "Second look."),
            world["officer"],
        ),
        ApiErrorId.ERR_ADVISOR_ENGAGEMENT_STATE_INVALID,
    )

    stored = validate_success(
        api.get_advisor_engagement(engagement["id"], world["officer"])
    )
    assert stored["status"] == "APPROVED", "the refused DENY did not overwrite APPROVED"
    assert stored["decision_reason"] is None
    assert stored["speaking_rights"] is False
    assert stored["version"] == version_after_first


def test_replayed_meeting_outcome_and_convene_each_keep_their_own_state(api):
    """PRD §3.5: "The outcome is recorded once, with an `outcome` of `HELD`, `NO_SHOW`
    or `CANCELLED`, and only from `SCHEDULED`; anything else is
    `ERR_MEETING_STATE_INVALID`."
    PRD §3.7: "The session's own chair convenes a `SCHEDULED` session."
    PRD §3.7: "On success `status` becomes `CONVENED`, the case moves to
    `HEARING_IN_PROGRESS`, and `version` advances."

    Design: Corner/state_machines/replaying_any_one_shot_trigger_returns_that_machines_own_already_done_error
    """
    world = fixtures.seed_formal_case(response_window_days=5)
    fixtures.schedule_meeting(world)
    fixtures.record_meeting_outcome(world, "CANCELLED")
    meeting = world["meeting"]
    assert meeting["status"] == "CANCELLED"
    meeting_version = meeting["version"]

    fixtures.acknowledge_notice(world)
    fixtures.seed_panel(world)
    fixtures.schedule_hearing(world)
    fixtures.convene_hearing(world)
    session = world["session"]
    assert session["status"] == "CONVENED"
    assert world["case"]["adjudication_status"] == "HEARING_IN_PROGRESS"
    session_version = session["version"]
    case_version = world["case"]["version"]

    fixtures.set_clock("2026-08-20T10:05:00Z", world["officer"])
    validate_error(
        api.record_meeting_outcome(
            meeting["id"], factories.meeting_outcome_payload("CANCELLED"), world["officer"]
        ),
        ApiErrorId.ERR_MEETING_STATE_INVALID,
    )
    validate_error(
        api.convene_hearing_session(session["id"], world["chair_h"]),
        ApiErrorId.ERR_SESSION_STATE_INVALID,
    )

    stored_meeting = validate_success(api.get_case_meeting(meeting["id"], world["officer"]))
    assert stored_meeting["status"] == "CANCELLED"
    assert stored_meeting["version"] == meeting_version
    stored_session = validate_success(
        api.get_hearing_session(session["id"], world["officer"])
    )
    assert stored_session["status"] == "CONVENED"
    assert stored_session["version"] == session_version
    stored_case = fixtures.read_case(world["case"]["id"], world["officer"])
    assert stored_case["adjudication_status"] == "HEARING_IN_PROGRESS", (
        "no replay advanced the case"
    )
    assert stored_case["version"] == case_version


def test_dismissed_case_refuses_dismiss_pathway_and_notice_alike(api):
    """PRD §3.4: "Dismissal records the reason, moves every sanction of the case in
    `PROPOSED` or `ACCEPTED` to `VACATED` with `vacated_reason` `CASE_DISMISSED`,
    decreases the department's `open_case_count` by one, sets `adjudication_status` to
    `DISMISSED`, and advances `version`. `DISMISSED` is terminal."
    PRD §2.9 rank 13: "the case's `adjudication_status` does not admit the operation, on
    `POST /integrity/cases/{id}/pathway`, `POST /integrity/cases/{id}/notifications`,
    `POST /integrity/cases/{id}/dismiss`, ... → `ERR_CASE_STATE_INVALID`."

    Design: Corner/state_machines/a_dismissed_case_is_locked_down_against_every_downstream_operation
    """
    world = fixtures.seed_case()
    case_id = world["case"]["id"]

    dismissed = validate_success(
        api.dismiss_case(case_id, factories.dismiss_payload(), world["officer"])
    )
    assert dismissed["adjudication_status"] == "DISMISSED"
    assert dismissed["pathway"] == "UNASSIGNED"
    assert dismissed["notation_status"] == "NOT_APPLICABLE"
    terminal_version = dismissed["version"]

    validate_error(
        api.dismiss_case(
            case_id,
            factories.dismiss_payload(dismiss_reason="Second dismissal."),
            world["officer"],
        ),
        ApiErrorId.ERR_CASE_STATE_INVALID,
    )
    # Rank 13 outranks rank 14: the pathway is still UNASSIGNED, so the refusal can
    # only be the terminal-state one.
    validate_error(
        api.set_case_pathway(case_id, factories.pathway_payload("FORMAL"), world["officer"]),
        ApiErrorId.ERR_CASE_STATE_INVALID,
    )
    validate_error(
        api.create_case_notification(
            case_id, factories.notification_payload("ALLEGATION_NOTICE"), world["officer"]
        ),
        ApiErrorId.ERR_CASE_STATE_INVALID,
    )

    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["adjudication_status"] == "DISMISSED"
    assert stored["pathway"] == "UNASSIGNED"
    assert stored["notation_status"] == "NOT_APPLICABLE"
    assert stored["version"] == terminal_version, "no refusal mutated the case"


def test_dismissed_case_beats_the_pathway_guards_on_meeting_and_hearing_writes(api):
    """PRD §2.9: "When a single request violates more than one rule, the response must
    carry the error of the **earliest-ranked** rule that matches."
    PRD §2.9 rank 13: "the case's `adjudication_status` does not admit the operation, on
    ... `POST /integrity/case-meetings`, `POST /integrity/hearing-sessions`, ... →
    `ERR_CASE_STATE_INVALID`."
    PRD §3.5: "The case's `adjudication_status` must be exactly `NOTIFIED`,
    `INFORMAL_PROPOSED` or `FORMAL_REFERRED` — a meeting cannot be booked before the
    student has been notified, nor after the case has been decided — and any other status
    is `ERR_CASE_STATE_INVALID`."

    Design: Corner/state_machines/a_dismissed_case_is_locked_down_against_every_downstream_operation
    """
    world = fixtures.seed_case()
    fixtures.seed_panel(world)
    case_id = world["case"]["id"]
    dismissed = validate_success(
        api.dismiss_case(case_id, factories.dismiss_payload(), world["officer"])
    )
    terminal_version = dismissed["version"]

    validate_error(
        api.create_case_meeting(
            factories.case_meeting_payload(
                case_id,
                world["reporter"]["id"],
                fixtures.MEETING_START,
                fixtures.MEETING_END,
            ),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_CASE_STATE_INVALID,
    )
    # Rank 13 outranks rank 15: an undismissed NOTIFIED case with pathway UNASSIGNED
    # answers ERR_CASE_PATHWAY_NOT_SET here, but the terminal state wins.
    validate_error(
        api.create_hearing_session(
            factories.hearing_session_payload(
                case_id,
                world["room"]["id"],
                world["chair"]["id"],
                [p["id"] for p in world["panelists"]],
                fixtures.SESSION_START,
                fixtures.SESSION_END,
            ),
            world["officer"],
        ),
        ApiErrorId.ERR_CASE_STATE_INVALID,
    )

    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["adjudication_status"] == "DISMISSED"
    assert stored["hearing_round"] == 0
    assert stored["version"] == terminal_version
    room = validate_success(api.get_hearing_room(world["room"]["id"], world["officer"]))
    assert room["booked_minutes_total"] == 0


def test_dismissed_case_refuses_an_appeal_and_leaves_its_ledgers_alone(api):
    """PRD §3.9: "The case must have reached a finding — `adjudication_status` `DECIDED`,
    `INFORMAL_ACCEPTED` or `SANCTION_IMPOSED` — otherwise `ERR_CASE_STATE_INVALID`."
    PRD §2.11: "`Department.open_case_count` always equals the number of cases whose
    offering belongs to that department and whose `adjudication_status` is neither
    `CLOSED` nor `DISMISSED`."

    Design: Corner/state_machines/a_dismissed_case_is_locked_down_against_every_downstream_operation
    """
    world = fixtures.seed_case()
    case_id = world["case"]["id"]
    dismissed = validate_success(
        api.dismiss_case(case_id, factories.dismiss_payload(), world["officer"])
    )
    terminal_version = dismissed["version"]

    validate_error(
        api.create_appeal(factories.appeal_payload(case_id), world["student_h"]),
        ApiErrorId.ERR_CASE_STATE_INVALID,
    )

    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["adjudication_status"] == "DISMISSED"
    assert stored["version"] == terminal_version
    department = validate_success(
        api.get_department(world["dept"]["id"], world["officer"])
    )
    assert department["open_case_count"] == 0, (
        "the dismissal released the ledger and no refusal touched it again"
    )
    _, meeting_meta = assertions.validate_list(
        api.list_case_meetings(world["officer"], params={"case_id": case_id})
    )
    assert meeting_meta["total_count"] == 0
    _, appeal_meta = assertions.validate_list(
        api.list_case_appeals(case_id, world["officer"])
    )
    assert appeal_meta["total_count"] == 0


def test_notation_walks_pending_posting_to_expunged_through_one_denial(api):
    """PRD §3.10: "A case's `notation_status` starts at `NOT_APPLICABLE` and is moved to
    `PENDING_POSTING` only as a side effect of imposing a sanction whose `ladder_rank` is
    4 or greater; a rank-1 through rank-3 sanction never produces a notation at all.
    `expungement_eligible_at` stays null while the notation is pending."
    PRD §3.10: "The registrar posts a notation for a case whose `notation_status` is
    exactly `PENDING_POSTING`; any other value is `ERR_NOTATION_STATE_INVALID`.
    `notation_status` becomes `POSTED`, the student's `transcript_notation` becomes
    `POSTED`, `expungement_eligible_at` is computed — or left null when the governing
    sanction is not yet `COMPLETED` — and `version` advances."
    PRD §3.10: "Denying sets `notation_status` to `EXPUNGEMENT_DENIED`, records the
    reason, and leaves `transcript_notation` unchanged; the student may request again, and
    the request-and-deny cycle may repeat without bound. `EXPUNGED` is terminal."
    PRD §3.10: "Granting sets `notation_status` to `EXPUNGED` and re-derives the student's
    `transcript_notation`: it is `POSTED` when any other case of that student still has a
    posted notation, and otherwise `EXPUNGED` — never `NONE`, because this case is now
    expunged."

    Design: Corner/state_machines/notation_dimension_walks_pending_posting_to_expunged_through_one_denied_request
    """
    world = fixtures.seed_decided_case(panel_recommendation=4)
    case_id = world["case"]["id"]
    session = world["session"]
    assert session["quorum_required"] == 2
    assert session["effective_vote_count"] == 3
    assert session["panel_finding"] == "RESPONSIBLE"
    assert session["panel_severity_recommendation"] == 4
    assert world["case"]["recommended_ladder_rank"] == 4, (
        "MAX(severity tier 3, panel recommendation 4) (PRD §3.4)"
    )

    fixtures.propose_sanction(world, ladder_rank=4)
    assert world["sanction"]["ladder_rank"] == 4
    assert world["sanction"]["kind"] == "TRANSCRIPT_NOTATION_ONLY"

    fixtures.impose_sanction(world)
    assert world["case"]["adjudication_status"] == "SANCTION_IMPOSED"
    assert world["case"]["notation_status"] == "PENDING_POSTING"
    assert world["case"]["expungement_eligible_at"] is None

    posted = validate_success(api.post_notation(case_id, world["registrar"]))
    assert posted["notation_status"] == "POSTED"
    assert posted["expungement_eligible_at"] is None, (
        "the governing sanction is only IMPOSED (PRD §3.10)"
    )
    student = validate_success(api.get_student(world["student"]["id"], world["officer"]))
    assert student["transcript_notation"] == "POSTED"

    # POSTED admits a request, but the eligibility instant is still unknown.
    validate_error(
        api.request_expungement(
            case_id, factories.expungement_request_payload(), world["student_h"]
        ),
        ApiErrorId.ERR_EXPUNGEMENT_TOO_EARLY,
    )

    fixtures.set_clock("2026-08-21T00:00:00Z", world["officer"])
    fixtures.complete_sanction(world)
    assert world["sanction"]["status"] == "COMPLETED"
    assertions.assert_instant_equals(
        world["sanction"]["completed_at"], "2026-08-21T00:00:00Z", "completed_at"
    )
    assert world["case"]["adjudication_status"] == "CLOSED"
    assert world["case"]["notation_status"] == "POSTED", (
        "the adjudication dimension closed without touching the notation dimension"
    )
    assertions.assert_instant_equals(
        world["case"]["expungement_eligible_at"],
        "2027-08-21T00:00:00Z",
        "expungement_eligible_at",
    )

    fixtures.set_clock("2027-08-21T00:00:00Z", world["officer"])
    requested = validate_success(
        api.request_expungement(
            case_id, factories.expungement_request_payload(), world["student_h"]
        )
    )
    assert requested["notation_status"] == "EXPUNGEMENT_REQUESTED"
    # PRD §3.2 derives `transcript_notation` from the notation dimension alone:
    # "`POSTED` when any of the student's cases has `notation_status` `POSTED`,
    # otherwise `EXPUNGED` when any case has `notation_status` `EXPUNGED`,
    # otherwise `NONE`".  The only case has left `POSTED` for
    # `EXPUNGEMENT_REQUESTED`, so neither branch matches.
    before_decision = validate_success(
        api.get_student(world["student"]["id"], world["officer"])
    )
    assert before_decision["transcript_notation"] == "NONE"

    denied = validate_success(
        api.decide_expungement(
            case_id,
            factories.expungement_decision_payload("DENY", "Record still too recent."),
            world["registrar"],
        )
    )
    assert denied["notation_status"] == "EXPUNGEMENT_DENIED"
    student = validate_success(api.get_student(world["student"]["id"], world["officer"]))
    # PRD §3.10: denial "leaves `transcript_notation` unchanged".
    assert student["transcript_notation"] == before_decision["transcript_notation"], (
        "a denial changes nothing"
    )

    requested_again = validate_success(
        api.request_expungement(
            case_id, factories.expungement_request_payload(), world["student_h"]
        )
    )
    assert requested_again["notation_status"] == "EXPUNGEMENT_REQUESTED", (
        "the deny/request cycle repeats"
    )

    granted = validate_success(
        api.decide_expungement(
            case_id,
            factories.expungement_decision_payload("GRANT"),
            world["registrar"],
        )
    )
    assert granted["notation_status"] == "EXPUNGED"
    student = validate_success(api.get_student(world["student"]["id"], world["officer"]))
    assert student["transcript_notation"] == "EXPUNGED"

    # EXPUNGED is terminal on the notation dimension.
    validate_error(
        api.post_notation(case_id, world["registrar"]),
        ApiErrorId.ERR_NOTATION_STATE_INVALID,
    )
    validate_error(
        api.decide_expungement(
            case_id, factories.expungement_decision_payload("GRANT"), world["registrar"]
        ),
        ApiErrorId.ERR_NOTATION_STATE_INVALID,
    )


def test_expungement_eligibility_gate_admits_the_boundary_instant_exactly(api):
    """PRD §3.10: "Otherwise it is the **later** of two instants: the governing
    sanction's `completed_at` plus the ladder waiting period, and the case's `decided_at`
    plus 365 days. The ladder waiting periods are 365 days at rank 4, 365 days at rank 5,
    730 days at rank 6 and 1095 days at rank 7."
    PRD §3.10: "the request is rejected with `ERR_EXPUNGEMENT_TOO_EARLY` when
    `expungement_eligible_at` is null because the governing sanction is not yet completed,
    or when the current logical clock has not reached `expungement_eligible_at`"

    Design: Corner/state_machines/notation_dimension_walks_pending_posting_to_expunged_through_one_denied_request
    """
    world = fixtures.seed_case_with_posted_notation(ladder_rank=4, panel_recommendation=4)
    case_id = world["case"]["id"]
    assert world["case"]["notation_status"] == "POSTED"
    assertions.assert_instant_equals(
        world["case"]["decided_at"], "2026-08-20T10:00:00Z", "decided_at"
    )

    fixtures.set_clock("2026-08-21T00:00:00Z", world["officer"])
    fixtures.complete_sanction(world)
    # MAX(2026-08-21T00:00:00Z + 365 d, 2026-08-20T10:00:00Z + 365 d).
    assertions.assert_instant_equals(
        world["case"]["expungement_eligible_at"],
        "2027-08-21T00:00:00Z",
        "expungement_eligible_at",
    )
    version_before = world["case"]["version"]

    fixtures.set_clock("2027-08-20T23:59:59Z", world["officer"])
    validate_error(
        api.request_expungement(
            case_id, factories.expungement_request_payload(), world["student_h"]
        ),
        ApiErrorId.ERR_EXPUNGEMENT_TOO_EARLY,
    )
    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["notation_status"] == "POSTED"
    assert stored["version"] == version_before

    fixtures.set_clock("2027-08-21T00:00:00Z", world["officer"])
    admitted = validate_success(
        api.request_expungement(
            case_id, factories.expungement_request_payload(), world["student_h"]
        )
    )
    assert admitted["notation_status"] == "EXPUNGEMENT_REQUESTED", (
        "the gate opens at the eligibility instant itself, not one second later"
    )


def test_hearing_preconditions_each_refuse_with_their_own_error(api):
    """PRD §3.5: "A case whose notice is still unacknowledged and whose
    `response_deadline_at` has not passed is inside its response window, and convening a
    hearing in that condition is rejected with `ERR_RESPONSE_WINDOW_OPEN`."
    PRD §3.7: "**Deciding.** The chair closes a `CONVENED` session."
    PRD §3.10: "The registrar posts a notation for a case whose `notation_status` is
    exactly `PENDING_POSTING`; any other value is `ERR_NOTATION_STATE_INVALID`."
    PRD §3.10: "The `notation_status` must be `POSTED` or `EXPUNGEMENT_DENIED`, otherwise
    `ERR_NOTATION_STATE_INVALID`."
    PRD §2.9: "Every rule is evaluated before any side effect is applied, and no partial
    write is ever observable: a rejected request leaves the store byte-identical to its
    pre-request state, including every derived counter and ledger."

    Design: Corner/state_machines/hearing_lifecycle_preconditions_each_refuse_with_their_own_error_before_the_gate_opens
    """
    world = fixtures.seed_hearing_scheduled(response_window_days=30)
    case_id = world["case"]["id"]
    session_id = world["session"]["id"]
    assertions.assert_instant_equals(
        world["notice"]["response_deadline_at"],
        "2026-08-31T00:00:00Z",
        "response_deadline_at",
    )
    assert world["notice"]["acknowledged_at"] is None
    assert world["case"]["adjudication_status"] == "HEARING_SCHEDULED"
    assert world["case"]["notation_status"] == "NOT_APPLICABLE"
    assert world["session"]["status"] == "SCHEDULED"
    version_before = world["case"]["version"]

    room = validate_success(api.get_hearing_room(world["room"]["id"], world["officer"]))
    assert room["booked_minutes_total"] == fixtures.SESSION_LEDGER_MINUTES

    fixtures.set_clock(fixtures.CLOCK_AT_SESSION, world["officer"])

    # The window is still open: the chair may not convene his own scheduled session.
    validate_error(
        api.convene_hearing_session(session_id, world["chair_h"]),
        ApiErrorId.ERR_RESPONSE_WINDOW_OPEN,
    )
    # A SCHEDULED session can be neither decided nor adjourned.
    validate_error(
        api.decide_hearing_session(session_id, world["chair_h"]),
        ApiErrorId.ERR_SESSION_STATE_INVALID,
    )
    validate_error(
        api.adjourn_hearing_session(
            session_id, factories.adjourn_payload(), world["chair_h"]
        ),
        ApiErrorId.ERR_SESSION_STATE_INVALID,
    )
    # The notation dimension is untouched, so both of its triggers refuse too.
    validate_error(
        api.post_notation(case_id, world["registrar"]),
        ApiErrorId.ERR_NOTATION_STATE_INVALID,
    )
    validate_error(
        api.request_expungement(
            case_id, factories.expungement_request_payload(), world["student_h"]
        ),
        ApiErrorId.ERR_NOTATION_STATE_INVALID,
    )

    session = validate_success(api.get_hearing_session(session_id, world["officer"]))
    assert session["status"] == "SCHEDULED"
    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["adjudication_status"] == "HEARING_SCHEDULED"
    assert stored["notation_status"] == "NOT_APPLICABLE"
    assert stored["version"] == version_before, "five refusals wrote nothing"
    room = validate_success(api.get_hearing_room(world["room"]["id"], world["officer"]))
    assert room["booked_minutes_total"] == fixtures.SESSION_LEDGER_MINUTES


def test_acknowledged_notice_opens_the_convene_gate_and_cancel_then_refuses(api):
    """PRD §3.5: "The student acknowledges an unacknowledged notice addressed to them,
    which stamps `acknowledged_at` from the current logical clock"
    PRD §3.7: "The session's own chair convenes a `SCHEDULED` session." and "On success
    `status` becomes `CONVENED`, the case moves to `HEARING_IN_PROGRESS`, and `version`
    advances."
    PRD §3.7: "**Cancelling.** The office may cancel a session that is still
    `SCHEDULED`; any other status is `ERR_SESSION_STATE_INVALID`."

    Design: Corner/state_machines/hearing_lifecycle_preconditions_each_refuse_with_their_own_error_before_the_gate_opens
    """
    world = fixtures.seed_hearing_scheduled(response_window_days=30)
    case_id = world["case"]["id"]
    session_id = world["session"]["id"]
    fixtures.set_clock(fixtures.CLOCK_AT_SESSION, world["officer"])
    validate_error(
        api.convene_hearing_session(session_id, world["chair_h"]),
        ApiErrorId.ERR_RESPONSE_WINDOW_OPEN,
    )

    fixtures.acknowledge_notice(world)
    assertions.assert_instant_equals(
        world["notice"]["acknowledged_at"],
        fixtures.CLOCK_AT_SESSION,
        "acknowledged_at",
    )
    version_before_convene = fixtures.case_version(case_id, world["officer"])

    convened = validate_success(api.convene_hearing_session(session_id, world["chair_h"]))
    assert convened["status"] == "CONVENED", (
        "the very same request now succeeds — only the gate had changed"
    )
    stored = fixtures.read_case(case_id, world["officer"])
    assert stored["adjudication_status"] == "HEARING_IN_PROGRESS"
    assert stored["version"] == version_before_convene + 1

    # Cancellation is reserved to SCHEDULED sessions.
    validate_error(
        api.cancel_hearing_session(
            session_id, factories.cancel_payload(), world["officer"]
        ),
        ApiErrorId.ERR_SESSION_STATE_INVALID,
    )
    session = validate_success(api.get_hearing_session(session_id, world["officer"]))
    assert session["status"] == "CONVENED"
    room = validate_success(api.get_hearing_room(world["room"]["id"], world["officer"]))
    assert room["booked_minutes_total"] == fixtures.SESSION_LEDGER_MINUTES, (
        "the refused cancellation released no booked minutes (PRD §2.11)"
    )
