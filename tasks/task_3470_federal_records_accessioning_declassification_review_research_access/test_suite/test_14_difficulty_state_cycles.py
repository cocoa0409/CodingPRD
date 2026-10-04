"""Difficulty coverage (queue A): the cyclic state machines — the FOIA
appeal-remand loop and the schedule return-resubmit revision cycle."""

import test_helpers as th

E = th.ApiErrorId


def test_foia_appeal_remand_cycle_full_loop(api):
    """PRD §3.9: "A `REMAND` sends the request back to `IN_REVIEW` and
    increments `remand_count` — opening the remand loop, in which the request
    is adjudicated afresh (restamping `adjudicator_id` and `decided_at`), may
    be appealed again, and may cycle any number of times. `GRANTED`,
    `APPEAL_GRANTED`, `APPEAL_UPHELD`, and `CLOSED` are the terminal states."
    PRD §3.9: "The owning `Researcher` appeals a request in `PARTIAL_GRANT` or
    `DENIED` (`ERR_OWNERSHIP_MISMATCH` for anyone else;
    `ERR_APPEAL_NOT_ALLOWED_STATE`, 409, from any other status), supplying an
    `appeal_reason`."

    Design: Difficulty/non_linear_state_machine/foia_appeal_remand_cycle
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    foia = th.create_foia(bob, bundle["collection"],
                          "all memos re Operation Cedar")
    researcher = th.make_researcher_headers(bob["id"])
    officer = th.TEST_USERS["foia_officer_headers"]
    appeals = th.TEST_USERS["foia_appeals_officer_headers"]

    denied = th.validate_success(
        api.adjudicate_foia_request(
            foia["id"], th.adjudicate_payload("DENY", ["B1"]), headers=officer
        ),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["claimed_exemptions"] == ["B1"]
    assert denied["adjudicator_id"] == "foia-1"

    appealed = th.validate_success(
        api.appeal_foia_request(
            foia["id"], th.appeal_payload("public interest outweighs"),
            headers=researcher,
        ),
        200,
    )
    assert appealed["status"] == "APPEALED"

    remanded = th.validate_success(
        api.decide_foia_appeal(
            foia["id"], th.decide_appeal_payload("REMAND"), headers=appeals
        ),
        200,
    )
    assert remanded["status"] == "IN_REVIEW"
    assert remanded["remand_count"] == 1

    denied2 = th.validate_success(
        api.adjudicate_foia_request(
            foia["id"], th.adjudicate_payload("DENY", ["B1", "B3"]), headers=officer
        ),
        200,
    )
    assert denied2["status"] == "DENIED"
    assert denied2["claimed_exemptions"] == ["B1", "B3"]
    assert denied2["adjudicator_id"] == "foia-1"

    th.validate_success(
        api.appeal_foia_request(
            foia["id"], th.appeal_payload("second appeal"), headers=researcher
        ),
        200,
    )
    upheld = th.validate_success(
        api.decide_foia_appeal(
            foia["id"], th.decide_appeal_payload("UPHOLD"), headers=appeals
        ),
        200,
    )
    assert upheld["status"] == "APPEAL_UPHELD"
    assert upheld["remand_count"] == 1

    # A terminal request cannot be appealed again.
    th.validate_error(
        api.appeal_foia_request(
            foia["id"], th.appeal_payload("third appeal on terminal request"),
            headers=researcher,
        ),
        E.ERR_APPEAL_NOT_ALLOWED_STATE,
    )


def test_foia_appeal_remand_then_grant_on_readjudication(api):
    """PRD §3.9: "Initial adjudication belongs to a `FoiaOfficer`, who
    supplies a `decision` of `GRANT`, `PARTIAL`, or `DENY` against a request in
    `RECEIVED` — or, after a remand, in `IN_REVIEW`."
    PRD §3.9: "A grant also feeds the collection's demand profile:
    `foia_release_count` increments by one, the collection's `version`
    advances, and a `QUEUED` collection's `digitization_priority` recomputes on
    the spot."

    Design: Difficulty/non_linear_state_machine/foia_appeal_remand_cycle
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    foia = th.create_appealed_foia(ada, collection)

    remanded = th.decide_appeal(foia, "REMAND")
    assert remanded["status"] == "IN_REVIEW"
    assert remanded["remand_count"] == 1

    granted = th.validate_success(
        api.adjudicate_foia_request(
            foia["id"], th.adjudicate_payload("GRANT"),
            headers=th.TEST_USERS["foia_officer_headers"],
        ),
        200,
    )
    assert granted["status"] == "GRANTED"
    assert granted["remand_count"] == 1

    collection_after = th.read_collection(collection["id"])
    assert collection_after["foia_release_count"] == 1


def test_schedule_return_resubmit_cycle(api):
    """PRD §3.1: "`RETURNED` is not the end. The owning `RecordsOfficer` may
    resubmit a returned schedule, moving it back to `SUBMITTED`, and may do so
    any number of times — this revision cycle is how schedules are repaired
    after an unfavorable decision. Resubmission clears the prior round's
    markings: `appraiser_id`, `appraisal_recommendation`, `decided_by`, and
    `decision_note` all reset to null, and the schedule re-enters appraisal
    with a clean slate. Every submit, appraise, decide, and resubmit advances
    the schedule's `version` by one."

    Design: Difficulty/non_linear_state_machine/schedule_return_resubmit_cycle
    """
    th.set_clock()
    agency = th.create_agency()
    officer = th.make_records_officer_headers(agency["id"])
    chief = th.TEST_USERS["chief_archivist_headers"]
    schedule = th.create_draft_schedule(
        agency, schedule_number="SCH-DOJ-020", title="Field Office General Files",
        classification_default="CONFIDENTIAL",
    )
    assert schedule["version"] == 1

    schedule = th.validate_success(
        api.submit_schedule(schedule["id"], headers=officer), 200
    )
    assert schedule["version"] == 2 and schedule["status"] == "SUBMITTED"
    schedule = th.validate_success(
        api.appraise_schedule(
            schedule["id"], th.appraise_payload("RETURN"),
            headers=th.TEST_USERS["appraiser_headers"],
        ),
        200,
    )
    assert schedule["version"] == 3 and schedule["status"] == "APPRAISED"
    schedule = th.validate_success(
        api.decide_schedule(
            schedule["id"],
            th.decide_schedule_payload("RETURN", "insufficient appraisal rationale"),
            headers=chief,
        ),
        200,
    )
    assert schedule["version"] == 4 and schedule["status"] == "RETURNED"

    resubmitted = th.validate_success(
        api.submit_schedule(schedule["id"], headers=officer), 200
    )
    assert resubmitted["version"] == 5 and resubmitted["status"] == "SUBMITTED"
    # The prior round's markings are cleared by the resubmission.
    assert resubmitted["appraiser_id"] is None
    assert resubmitted["appraisal_recommendation"] is None
    assert resubmitted["decided_by"] is None
    assert resubmitted["decision_note"] is None

    schedule = th.validate_success(
        api.appraise_schedule(
            schedule["id"], th.appraise_payload("APPROVE"),
            headers=th.TEST_USERS["appraiser_2_headers"],
        ),
        200,
    )
    assert schedule["version"] == 6
    schedule = th.validate_success(
        api.decide_schedule(
            schedule["id"], th.decide_schedule_payload("APPROVE"), headers=chief
        ),
        200,
    )
    assert schedule["version"] == 7
    assert schedule["status"] == "APPROVED"
    assert schedule["appraiser_id"] == "arch-ap-2"
    assert schedule["decided_by"] == "arch-chief-1"


def test_schedule_return_resubmit_cycle_repeats_any_number_of_times(api):
    """PRD §3.1: "The owning `RecordsOfficer` may resubmit a returned schedule,
    moving it back to `SUBMITTED`, and may do so any number of times — this
    revision cycle is how schedules are repaired after an unfavorable
    decision."
    PRD §3.1: "Resubmission clears the prior round's markings: `appraiser_id`,
    `appraisal_recommendation`, `decided_by`, and `decision_note` all reset to
    null, and the schedule re-enters appraisal with a clean slate."

    Design: Difficulty/non_linear_state_machine/schedule_return_resubmit_cycle
    """
    th.set_clock()
    agency = th.create_agency()
    officer = th.make_records_officer_headers(agency["id"])
    chief = th.TEST_USERS["chief_archivist_headers"]
    schedule = th.create_draft_schedule(
        agency, schedule_number="SCH-DOJ-023", title="Twice returned"
    )
    schedule = th.submit_schedule(schedule)

    # First RETURN round.
    schedule = th.appraise_schedule(schedule, "RETURN")
    schedule = th.decide_schedule(schedule, "RETURN",
                                  decision_note="round one rejected",
                                  chief_headers=chief)
    assert schedule["status"] == "RETURNED"
    schedule = th.submit_schedule(schedule)

    # Second RETURN round — the cycle repeats.
    schedule = th.appraise_schedule(schedule, "RETURN",
                                    appraiser_headers=th.TEST_USERS["appraiser_2_headers"])
    schedule = th.decide_schedule(schedule, "RETURN",
                                  decision_note="round two rejected",
                                  chief_headers=chief)
    assert schedule["status"] == "RETURNED"
    resubmitted = th.validate_success(
        api.submit_schedule(schedule["id"], headers=officer), 200
    )
    assert resubmitted["appraiser_id"] is None
    assert resubmitted["decision_note"] is None

    schedule = th.appraise_schedule(resubmitted, "APPROVE")
    schedule = th.decide_schedule(schedule, "APPROVE", chief_headers=chief)
    assert schedule["status"] == "APPROVED"
    assert schedule["version"] == 10  # create + nine transitions
