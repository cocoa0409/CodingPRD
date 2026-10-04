"""Statutory deadline and per-cycle uniqueness corners (PRD §3.4, §3.5,
§3.7–§3.9).
"""
from test_helpers import (
    ApiErrorId,
    PANEL,
    accord,
    add_petitioned_patent,
    api_client,
    assert_same_instant,
    create_brief_payload,
    create_hearing_room,
    decide_institution,
    file_po_response,
    get_proceeding,
    get_success_data,
    issue_final_decision,
    new_world,
    outcomes_payload,
    per_ground_scores,
    request_extension,
    request_hearing,
    schedule_payload,
    set_clock,
    setup_decided_proceeding,
    setup_decided_with_appeal,
    setup_decision_phase,
    setup_instituted_proceeding,
    validate_error,
)


class TestInstitutionWindowBoundary:
    def _two_accorded(self):
        world = new_world(petitioner_name="PAB Corp", owner_name="OAB Corp")
        a = add_petitioned_patent(world, patent_number="US10001035A",
                                  challenged_claims=(1,), do_accord=True)
        b = add_petitioned_patent(world, patent_number="US10001035B",
                                  challenged_claims=(1,), do_accord=True)
        return a, b

    def test_decision_exactly_93_days_after_accordance_is_timely(self):
        """PRD §3.4: "a decision on or before `accorded_date` plus 93 days is
        timely, while one attempted 94 or more days after accordance is
        rejected with `ERR_INSTITUTION_WINDOW_LAPSED`."

        Design: Corner/validations/institution_decision_at_day_93_timely_day_94_lapsed
        """
        a, _ = self._two_accorded()
        # Accorded 2026-09-01; 2026-12-03 is exactly day 93.
        set_clock("2026-12-03T00:00:00Z")
        data = decide_institution(
            a["petition"]["id"], per_ground_scores((1, 60)), "judge-faye"
        )
        assert data["outcome"] == "INSTITUTED"

    def test_decision_94_days_after_accordance_lapses(self):
        """PRD §3.4: "one attempted 94 or more days after accordance is
        rejected with `ERR_INSTITUTION_WINDOW_LAPSED`."

        Design: Corner/validations/institution_decision_at_day_93_timely_day_94_lapsed
        """
        _, b = self._two_accorded()
        set_clock("2026-12-04T00:00:00Z")  # day 94
        resp = api_client.decide_institution(
            b["petition"]["id"],
            {"per_ground_scores": per_ground_scores((1, 60)),
             "lead_judge_user_id": "judge-faye"},
            PANEL,
        )
        validate_error(resp, ApiErrorId.ERR_INSTITUTION_WINDOW_LAPSED, 422)


def test_final_decision_after_unextended_deadline_rejected():
    """PRD §3.8: "the logical clock has not passed `fwd_due_date` — issuance
    after the deadline is `ERR_FWD_DEADLINE_PASSED`, and an extension must be
    obtained first."

    Design: Corner/validations/final_decision_after_unextended_deadline_rejected
    """
    world = setup_decision_phase(
        setup_instituted_proceeding(
            total_claims=2, challenged_claims=(1,),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 74}],
            lead_judge="judge-gwen",
        ),
        hearing_start="2027-03-01T09:00:00Z", hearing_end="2027-03-01T10:00:00Z",
    )
    # One day past the unextended 2027-09-01 deadline.
    set_clock("2027-09-02T00:00:00Z")
    resp = api_client.create_final_decision(
        world["proceeding"]["id"],
        {"outcomes": [{"claim_number": 1, "outcome": "UNPATENTABLE"}]},
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_FWD_DEADLINE_PASSED, 422)
    assert get_proceeding(world["proceeding"]["id"])["phase"] == "DECISION_PHASE"


def test_hearing_scheduled_beyond_fwd_deadline_rejected():
    """PRD §3.7: "the hearing must start on or before the proceeding's
    `fwd_due_date` — a start beyond the final-decision deadline is
    `ERR_HEARING_PAST_FWD_DATE`."

    Design: Corner/validations/hearing_scheduled_beyond_fwd_deadline_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 74}],
        lead_judge="judge-hugh",
    )
    file_po_response(world, 50)
    room = create_hearing_room(name="Room RAD")
    hearing = request_hearing(world["proceeding"]["id"],
                              world["petitioner_headers"])
    # fwd_due_date is 2027-09-01; the start falls one day beyond it.
    resp = api_client.schedule_oral_hearing(
        hearing["id"],
        schedule_payload(room["id"], "2027-09-02T09:00:00Z",
                         "2027-09-02T10:00:00Z"),
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_PAST_FWD_DATE, 422)
    assert get_success_data(
        api_client.get_oral_hearing(hearing["id"], PANEL)
    )["status"] == "REQUESTED"


def test_reply_brief_after_window_close_rejected():
    """PRD §3.5: "the petitioner answers with a `PETITIONER_REPLY`, due
    within 132 days" of the cycle anchor, and "A brief tendered after its
    window has closed is rejected with `ERR_BRIEF_WINDOW_CLOSED`."

    Design: Corner/validations/reply_brief_after_window_close_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 74}],
        lead_judge="judge-ivan",
    )
    file_po_response(world, 50)  # phase REPLY_WINDOW, anchor 2026-09-01
    # Window closed 2027-01-11 (anchor + 132 days); filing on 2027-01-12.
    set_clock("2027-01-12T00:00:00Z")
    resp = api_client.create_brief(
        world["proceeding"]["id"],
        create_brief_payload("PETITIONER_REPLY", 25),
        world["petitioner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_BRIEF_WINDOW_CLOSED, 422)
    assert get_proceeding(world["proceeding"]["id"])["phase"] == "REPLY_WINDOW"


def test_second_extension_request_rejected():
    """PRD §3.8: "Good cause may be shown once per proceeding." and "If
    `extension_used` is already true, the request is rejected with
    `ERR_EXTENSION_ALREADY_USED`".

    Design: Corner/validations/second_extension_request_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 74}],
        lead_judge="judge-jane",
    )
    first = request_extension(
        world["proceeding"]["id"], world["petitioner_headers"],
        justification="Good cause: parallel reissue proceeding requires "
                      "coordination.",
    )
    assert first["extension_used"] is True
    resp = api_client.create_extension_request(
        world["proceeding"]["id"],
        {"justification": "Second request: expert witness medical emergency "
                          "delays hearing."},
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_ALREADY_USED, 409)
    # The single 183-day bump stands (institution 2026-09-01 -> 2028-03-02).
    assert_same_instant(
        get_proceeding(world["proceeding"]["id"])["fwd_due_date"],
        "2028-03-02T00:00:00Z", "fwd_due_date",
    )


def test_second_decision_in_same_cycle_reports_decision_issued_before_phase_gate():
    """PRD §3.8: "Issuing the final written decision is a panel action whose
    guards are checked in a fixed order: first, that no decision already
    exists for the current `briefing_cycle` — exactly one decision may issue
    per cycle, and a second attempt is `ERR_DECISION_ALREADY_ISSUED`; then
    that the proceeding stands in `DECISION_PHASE` (`ERR_INVALID_PHASE`)".

    Design: Corner/validations/second_decision_in_same_cycle_reports_decision_issued_before_phase_gate
    """
    world = setup_decided_proceeding(
        institute_kw=dict(
            total_claims=2, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 60}],
            lead_judge="judge-kent",
        ),
        outcomes=outcomes_payload((1, "UNPATENTABLE"), (2, "NOT_UNPATENTABLE")),
    )
    # Phase is DECIDED: both the uniqueness rule and the phase gate are
    # tripped; uniqueness is checked first.
    resp = api_client.create_final_decision(
        world["proceeding"]["id"],
        {"outcomes": [{"claim_number": 1, "outcome": "NOT_UNPATENTABLE"},
                      {"claim_number": 2, "outcome": "NOT_UNPATENTABLE"}]},
        PANEL,
    )
    err = validate_error(resp, ApiErrorId.ERR_DECISION_ALREADY_ISSUED, 409)
    assert err["error_id"] != ApiErrorId.ERR_INVALID_PHASE


def test_second_appeal_while_one_pending_rejected():
    """PRD §3.9: "admits only one pending appeal at a time: a second appeal
    while one already stands `FILED` is rejected with
    `ERR_APPEAL_ALREADY_PENDING`."

    Design: Corner/validations/second_appeal_while_one_pending_rejected
    """
    world = setup_decided_with_appeal(
        institute_kw=dict(
            total_claims=2, challenged_claims=(1,),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102",
                     "score": 80}],
            lead_judge="judge-lars",
        ),
        outcomes=[{"claim_number": 1, "outcome": "UNPATENTABLE"}],
    )
    # The petitioner's appeal stands FILED; the owner's appeal is second.
    resp = api_client.create_appeal(
        world["proceeding"]["id"], world["owner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_PENDING, 409)


def test_second_hearing_request_while_one_pending_rejected():
    """PRD §3.7: "at most one hearing may be in flight per proceeding, so a
    request while another stands `REQUESTED` or `SCHEDULED` is rejected with
    `ERR_HEARING_ALREADY_PENDING`."

    Design: Corner/validations/second_hearing_request_while_one_pending_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-monk",
    )
    request_hearing(world["proceeding"]["id"], world["petitioner_headers"])
    resp = api_client.create_oral_hearing(
        world["proceeding"]["id"], {}, world["owner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_ALREADY_PENDING, 409)
