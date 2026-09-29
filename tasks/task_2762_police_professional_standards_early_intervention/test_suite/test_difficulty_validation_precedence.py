"""Guard ordering: which of two simultaneously violated rules reports itself."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_discipline_days,
    assert_instant,
    assert_two_dp,
    make_ia_commander_headers,
)
from test_helpers import factories, fixtures


def two_files_against_one_officer(api, world):
    """File A holds a future session; file B is tolled after an interview of its own."""
    file_a = fixtures.file_supervisor_complaint(
        api, world, narrative="Neglect of duty on the late shift."
    )
    allegation_a = fixtures.attach_allegation(
        api, world, file_a["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    investigation_a = fixtures.open_investigation(api, world, file_a["id"])
    fixtures.assign_investigation(
        api, world, investigation_a["id"], investigation_a["version"], world["inv_a_id"]
    )
    session_a = fixtures.schedule_session(
        api,
        world,
        investigation_a["id"],
        scheduled_start="2026-08-10T09:00:00Z",
        scheduled_end="2026-08-10T10:00:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        representation_status="REP_PRESENT",
    )

    file_b = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Pursuit policy violation.",
        incident_datetime="2026-07-18T22:00:00Z",
        reported_allegation_types=["PURSUIT_VIOLATION"],
    )
    allegation_b = fixtures.attach_allegation(
        api, world, file_b["id"], allegation_type="PURSUIT_VIOLATION", offense_class="B"
    )
    investigation_b = fixtures.open_investigation(api, world, file_b["id"])
    fixtures.assign_investigation(
        api, world, investigation_b["id"], investigation_b["version"], world["inv_a_id"]
    )
    early_session = fixtures.schedule_session(
        api,
        world,
        investigation_b["id"],
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T10:00:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        representation_status="WAIVED",
    )
    fixtures.set_clock(api, "2026-08-03T09:00:00Z")
    fixtures.hold_session(api, world, early_session["id"])
    fixtures.set_clock(api, "2026-08-04T00:00:00Z")
    tolled = get_success_data(
        api.toll_investigation(
            investigation_b["id"],
            factories.tolling_payload("SUSPEND", tolling_reason="Awaiting the pursuit data download."),
            world["inv_a_headers"],
        )
    )
    return {
        "ia_id": investigation_a["id"],
        "aa_id": allegation_a["id"],
        "sa_id": session_a["id"],
        "ib_id": investigation_b["id"],
        "ab_id": allegation_b["id"],
        "sb0_id": early_session["id"],
        "tolled": tolled,
    }


def clashing_session_payload(world, start="2026-08-10T11:00:00Z", end="2026-08-10T12:00:00Z"):
    """A booking that touches the existing session's rest buffer exactly."""
    return factories.interview_session_payload(
        world["subj_id"],
        world["room1_id"],
        scheduled_start=start,
        scheduled_end=end,
        notice_served_at="2026-08-04T00:00:00Z",
        representation_status="REP_PRESENT",
    )


def test_the_interviewable_state_check_outranks_the_rest_buffer(api, world):
    """A tolled investigation reports its own state, not the collision it also has.

    PRD: And on interview-session creation, the interviewability state check at tier 8 is evaluated **before** the officer rest-buffer conflict at tier 11: a session requested against an investigation that is not open reports `ERR_INVESTIGATION_NOT_INTERVIEWABLE` even when the requested times would also have collided with an existing session.
    Design: Difficulty/priority_pair_validation_conflict/investigation_state_check_outranks_officer_rest_buffer_conflict
    """
    files = two_files_against_one_officer(api, world)
    assert files["tolled"]["status"] == "TOLLED"

    refused = api.schedule_interview_session(
        files["ib_id"], clashing_session_payload(world), world["inv_a_headers"]
    )

    validate_error(refused, "ERR_INVESTIGATION_NOT_INTERVIEWABLE", 409)
    assert fixtures.read_session(api, files["sa_id"], world["inv_a_headers"])["status"] == "SCHEDULED"
    sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"investigation_id": files["ib_id"]})
    )
    assert len(sessions) == 1
    assert sessions[0]["status"] == "HELD"


def test_the_rest_buffer_is_reachable_once_the_investigation_is_open(api, world):
    """Resuming the case exposes the sixty-minute collision the state check had hidden.

    PRD: Because both ends are inclusive, a gap of exactly sixty minutes between the end of one session and the start of the next **is** a conflict — the widened window's left endpoint lands precisely on the earlier session's end instant, and touching counts.
    PRD: A gap of sixty-one minutes is accepted.
    Design: Difficulty/priority_pair_validation_conflict/investigation_state_check_outranks_officer_rest_buffer_conflict
    """
    files = two_files_against_one_officer(api, world)
    resumed = get_success_data(
        api.toll_investigation(
            files["ib_id"], factories.tolling_payload("RESUME"), world["inv_a_headers"]
        )
    )
    assert resumed["status"] == "IN_PROGRESS"

    refused = api.schedule_interview_session(
        files["ib_id"], clashing_session_payload(world), world["inv_a_headers"]
    )
    validate_error(refused, "ERR_OFFICER_REST_BUFFER_CONFLICT", 409)

    accepted = get_success_data(
        api.schedule_interview_session(
            files["ib_id"],
            clashing_session_payload(
                world, start="2026-08-10T11:01:00Z", end="2026-08-10T12:01:00Z"
            ),
            world["inv_a_headers"],
        )
    )

    assert accepted["status"] == "SCHEDULED"
    assert_two_dp(accepted["notice_hours"], 155, label="notice_hours")
    assert fixtures.read_session(api, files["sa_id"], world["inv_a_headers"])["status"] == "SCHEDULED"
    sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"investigation_id": files["ib_id"]})
    )
    assert [row["status"] for row in sessions] == ["HELD", "SCHEDULED"]


def tied_findings_case(api):
    """One allegation whose findings are an exact 50 against 50 tie."""
    world_ = fixtures.world_assigned_investigation(api, offense_class="C")
    session = fixtures.schedule_session(
        api,
        world_,
        world_["i1_id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        representation_status="REP_PRESENT",
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(api, world_, session["id"])
    filed = fixtures.submit_findings(
        api, world_, world_["i1_id"], [factories.finding_entry(world_["a1_id"], 50, 50)]
    )
    world_.update({"s1_id": session["id"], "filed": filed})
    return world_


def test_segregation_of_duties_outranks_the_preponderance_shortfall(api):
    """The investigator wearing the commander's hat is told about the conflict.

    PRD: On the disposition write, segregation of duties at tier 9 is evaluated **before** the preponderance test at tier 12: a commander who investigated the case and also lacks a preponderance receives `ERR_SEGREGATION_OF_DUTIES`.
    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_preponderance_shortfall
    """
    world = tied_findings_case(api)
    assert world["filed"]["status"] == "PENDING_REVIEW"
    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert_two_dp(allegation["support_pct"], 50.00, label="support_pct")
    assert allegation["preponderance_met"] is False

    refused = api.dispose_allegation(
        world["a1_id"],
        factories.disposition_payload("SUSTAINED", rationale="Investigator adjudicating his own case."),
        make_ia_commander_headers(world["inv_a_id"]),
    )

    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])["disposition"] == "PENDING"


def test_the_preponderance_test_is_reachable_for_an_untainted_commander(api):
    """The clean commander hits the evidence rule, and 51 against 49 finally carries it.

    PRD: `preponderance_met` is then true only when `support_pct` is **strictly greater than** 50.00.
    PRD: Weights of 51 and 49 give `support_pct` 51.00 and `preponderance_met` true.
    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_preponderance_shortfall
    """
    world = tied_findings_case(api)

    refused = api.dispose_allegation(
        world["a1_id"],
        factories.disposition_payload(
            "SUSTAINED", rationale="Commander adjudicating on tied evidence."
        ),
        world["cmdr_headers"],
    )
    validate_error(refused, "ERR_PREPONDERANCE_NOT_MET", 422)
    assert fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])["disposition"] == "PENDING"

    get_success_data(
        api.toll_investigation(
            world["i1_id"],
            factories.tolling_payload("RESUME", tolling_reason="Returned for a further evidence review."),
            world["cmdr_headers"],
        )
    )
    fixtures.submit_findings(
        api, world, world["i1_id"], [factories.finding_entry(world["a1_id"], 51, 49)]
    )
    revised = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert_two_dp(revised["support_pct"], 51.00, label="support_pct")
    assert revised["preponderance_met"] is True

    disposed = fixtures.dispose_allegation(api, world, world["a1_id"], "SUSTAINED")

    assert disposed["disposition"] == "SUSTAINED"
    discipline = fixtures.discipline_for_allegation(api, world, world["a1_id"])
    assert_discipline_days(discipline, presumptive_prior_tier=0, presumptive_days=3)
    complaint = fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])
    assert complaint["sustained_allegation_count"] == 1


def one_encumbered_file_and_one_clean_file(api, world):
    """A closed untruthfulness file under a permanent hold, beside a withdrawn file."""
    encumbered = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Officer gave a false account in a report.",
        reported_allegation_types=["UNTRUTHFULNESS"],
    )
    allegation = fixtures.attach_allegation(
        api, world, encumbered["id"], allegation_type="UNTRUTHFULNESS", offense_class="A"
    )
    clean = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Complaint later withdrawn by the reporting supervisor.",
        incident_datetime="2026-07-20T10:00:00Z",
        reported_allegation_types=["DISCOURTESY"],
    )
    investigation = fixtures.open_investigation(api, world, encumbered["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        representation_status="REP_PRESENT",
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    withdrawn = fixtures.withdraw_complaint(
        api,
        world,
        clean["id"],
        intake_reference_code=clean["intake_reference_code"],
        withdrawal_reason="Matter resolved informally.",
    )
    fixtures.hold_session(api, world, session["id"])
    fixtures.submit_findings(
        api, world, investigation["id"], [factories.finding_entry(allegation["id"], 60, 40)]
    )
    fixtures.dispose_allegation(api, world, allegation["id"], "SUSTAINED")
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    closed = fixtures.close_investigation(api, world, investigation["id"])
    disclosures, _ = fixtures.rows(
        api.list_credibility_disclosures(world["custodian_headers"], {"officer_id": world["subj_id"]})
    )
    return {
        "c1_id": encumbered["id"],
        "a1_id": allegation["id"],
        "i1_id": investigation["id"],
        "closed_investigation": closed,
        "c2_id": clean["id"],
        "withdrawn": withdrawn,
        "disc_id": disclosures[0]["id"],
    }


def test_the_credibility_hold_outranks_the_retention_window(api, world):
    """A file inside its retention window and under a hold reports the hold.

    PRD: On purge, the credibility hold at tier 9 is evaluated **before** the retention-expiry check at tier 11: a file that is both still inside its retention window and encumbered by an active disclosure reports `ERR_CREDIBILITY_HOLD`, not `ERR_RETENTION_NOT_EXPIRED`.
    Design: Difficulty/priority_pair_validation_conflict/credibility_hold_outranks_retention_window
    """
    files = one_encumbered_file_and_one_clean_file(api, world)
    encumbered = fixtures.read_complaint(api, files["c1_id"], world["custodian_headers"])
    assert encumbered["status"] == "CLOSED"
    assert_instant(encumbered["retention_until"], "2033-08-18T00:00:00Z")

    refused = api.purge_complaint(
        files["c1_id"], {"purge_reason": "Routine retention sweep."}, world["custodian_headers"]
    )
    validate_error(refused, "ERR_CREDIBILITY_HOLD", 409)

    fixtures.set_clock(api, "2033-08-18T00:00:00Z")
    still_refused = api.purge_complaint(
        files["c1_id"], {"purge_reason": "Retention period elapsed."}, world["custodian_headers"]
    )
    validate_error(still_refused, "ERR_CREDIBILITY_HOLD", 409)

    unpurged = fixtures.read_complaint(api, files["c1_id"], world["custodian_headers"])
    assert unpurged["status"] == "CLOSED"
    assert unpurged["purged_at"] is None
    disclosure = fixtures.read_disclosure(api, files["disc_id"], world["custodian_headers"])
    assert disclosure["status"] == "ACTIVE"
    assert disclosure["permanent_retention"] is True


def test_the_retention_window_is_reachable_on_a_file_with_no_disclosure(api, world):
    """The withdrawn file reports its own clock, then purges once that clock runs out.

    PRD: And the logical clock must have reached `retention_until`, a non-strict comparison so that a purge at exactly the retention instant is allowed, otherwise `ERR_RETENTION_NOT_EXPIRED`.
    PRD: The complaint's `narrative`, `complainant_name` and `complainant_contact` are nulled and `complainant_demographic_code` is set to `UNKNOWN`; every allegation's `narrative` is nulled and each allegation's `redacted` flag is set to true; `purged_at` is stamped and the complaint's `status` becomes `PURGED`.
    Design: Difficulty/priority_pair_validation_conflict/credibility_hold_outranks_retention_window
    """
    files = one_encumbered_file_and_one_clean_file(api, world)
    assert files["withdrawn"]["status"] == "WITHDRAWN"
    assert_instant(files["withdrawn"]["retention_until"], "2028-08-04T09:00:00Z")

    too_early = api.purge_complaint(
        files["c2_id"], {"purge_reason": "Routine retention sweep."}, world["custodian_headers"]
    )
    validate_error(too_early, "ERR_RETENTION_NOT_EXPIRED", 409)

    fixtures.set_clock(api, "2033-08-18T00:00:00Z")
    purged = get_success_data(
        api.purge_complaint(
            files["c2_id"], {"purge_reason": "Retention period elapsed."}, world["custodian_headers"]
        )
    )

    assert purged["status"] == "PURGED"
    assert purged["narrative"] is None
    assert purged["complainant_name"] is None
    assert purged["complainant_contact"] is None
    assert purged["complainant_demographic_code"] == "UNKNOWN"
    assert purged["purged_at"] is not None
    disclosure = fixtures.read_disclosure(api, files["disc_id"], world["custodian_headers"])
    assert disclosure["status"] == "ACTIVE"
