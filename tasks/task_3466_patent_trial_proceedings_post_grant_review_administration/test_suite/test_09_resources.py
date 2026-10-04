"""Resource contention: the hearing-room buffered-interval conflict and the
panel-lead aggregate capacity (PRD §3.4, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    add_petitioned_patent,
    api_client,
    create_hearing_room,
    decide_institution,
    file_brief,
    file_po_response,
    get_petition,
    get_success_data,
    issue_final_decision,
    new_world,
    outcomes_payload,
    request_hearing,
    schedule_hearing,
    schedule_payload,
    setup_decision_phase,
    setup_instituted_proceeding,
    validate_error,
    validate_success,
    PANEL,
)


class TestHearingRoomBufferedIntervalConflict:
    def _two_proceedings_one_booking(self):
        world = setup_instituted_proceeding(
            total_claims=2, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 70},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 60}],
            lead_judge="judge-mia", petitioner_name="P16 Corp",
            owner_name="O16 Corp", patent_number="US10000016A",
        )
        b = add_petitioned_patent(
            world, patent_number="US10000016B", challenged_claims=(1, 2),
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
            do_accord=True,
            do_decide=True,
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 70},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 60}],
            lead_judge="judge-nick",
        )
        # Both proceedings to REPLY_WINDOW (scheduling is phase-gated).
        file_po_response(world, 50)
        file_brief(b["proceeding"]["id"], "PO_RESPONSE", 50,
                   world["owner_headers"])
        room = create_hearing_room(name="Room R16", capacity=50)
        hearing_a = request_hearing(
            world["proceeding"]["id"], world["owner_headers"]
        )
        schedule_hearing(hearing_a["id"], room["id"],
                         "2027-03-01T14:00:00Z", "2027-03-01T15:00:00Z")
        hearing_b = request_hearing(
            b["proceeding"]["id"], world["petitioner_headers"]
        )
        return hearing_b, room

    def test_start_inside_turnover_buffer_conflicts(self):
        """PRD §3.7: "every other `SCHEDULED` hearing in the same room
        occupies its own interval extended by a trailing 30-minute buffer. A
        conflict exists precisely when the new start falls before another
        booking's buffered end and the new end falls after that booking's
        start, and is rejected with `ERR_HEARING_ROOM_CONFLICT`; starting
        exactly at another booking's buffered end is accepted, starting one
        minute earlier conflicts".

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_interval_conflict_boundary
        """
        hearing_b, room = self._two_proceedings_one_booking()
        # Booking A occupies [14:00, 15:30) with the buffer; 15:29 conflicts.
        resp = api_client.schedule_oral_hearing(
            hearing_b["id"],
            schedule_payload(room["id"], "2027-03-01T15:29:00Z",
                             "2027-03-01T16:29:00Z"),
            PANEL,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_ROOM_CONFLICT, 409)

    def test_start_exactly_at_buffered_end_is_accepted(self):
        """PRD §3.7: "starting exactly at another booking's buffered end is
        accepted, starting one minute earlier conflicts, and ending exactly
        when another booking begins is accepted."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_interval_conflict_boundary
        """
        hearing_b, room = self._two_proceedings_one_booking()
        # First the conflicting attempt leaves the hearing REQUESTED...
        resp = api_client.schedule_oral_hearing(
            hearing_b["id"],
            schedule_payload(room["id"], "2027-03-01T15:29:00Z",
                             "2027-03-01T16:29:00Z"),
            PANEL,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_ROOM_CONFLICT, 409)
        still = get_success_data(api_client.get_oral_hearing(hearing_b["id"], PANEL))
        assert still["status"] == "REQUESTED"
        assert still["hearing_room_id"] is None
        # ...then exactly 15:30 (booking end 15:00 + 30-minute buffer) books.
        ok = schedule_hearing(hearing_b["id"], room["id"],
                              "2027-03-01T15:30:00Z", "2027-03-01T16:30:00Z")
        assert ok["status"] == "SCHEDULED"


class TestPanelLeadAggregateCapacity:
    def _three_petitions(self):
        world = new_world(petitioner_name="P17 Corp", owner_name="O17 Corp")
        a = add_petitioned_patent(
            world, patent_number="US10000017A", challenged_claims=(1, 2),
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
            do_accord=True,
        )
        b = add_petitioned_patent(
            world, patent_number="US10000017B", challenged_claims=(1, 2),
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
            do_accord=True,
        )
        c = add_petitioned_patent(
            world, patent_number="US10000017C", challenged_claims=(1, 2),
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
            do_accord=True,
        )
        scores = [{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 70},
                  {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 60}]
        # A and B institute under judge-olga: active load 2.
        a["decision"] = decide_institution(a["petition"]["id"], scores, "judge-olga")
        a["proceeding"] = {"id": a["decision"]["proceeding_id"]}
        b["decision"] = decide_institution(b["petition"]["id"], scores, "judge-olga")
        return world, a, b, c, scores

    def test_third_institution_at_capacity_is_rejected(self):
        """PRD §3.4: "a panel lead may front at most two active proceedings.
        Counting proceedings whose `lead_judge_user_id` equals the payload
        designee and whose `phase` is any of `INSTITUTED`, `REPLY_WINDOW`,
        `SUR_REPLY_WINDOW`, `HEARING_PHASE`, `DECISION_PHASE`, or `REMANDED`
        — `DECIDED` and `CLOSED` proceedings release the slot — a count of
        exactly one still admits the assignment, while a count of two rejects
        the institution with `ERR_PANEL_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/panel_lead_aggregate_capacity_releases_on_decision
        """
        _, _, _, c, scores = self._three_petitions()
        resp = api_client.decide_institution(
            c["petition"]["id"],
            {"per_ground_scores": scores, "lead_judge_user_id": "judge-olga"},
            PANEL,
        )
        validate_error(resp, ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED, 409)
        # No partial mutation: petition C stays NOTICE_ACCORDED.
        assert get_petition(c["petition"]["id"])["status"] == "NOTICE_ACCORDED"

    def test_capacity_frees_the_moment_one_proceeding_is_decided(self):
        """PRD §3.4: "`DECIDED` and `CLOSED` proceedings release the slot" —
        after proceeding A reaches DECIDED, the identical institution call
        for petition C succeeds.

        Design: Difficulty/resource_temporal_overlap/panel_lead_aggregate_capacity_releases_on_decision
        """
        world, a, _, c, scores = self._three_petitions()
        resp = api_client.decide_institution(
            c["petition"]["id"],
            {"per_ground_scores": scores, "lead_judge_user_id": "judge-olga"},
            PANEL,
        )
        validate_error(resp, ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED, 409)
        # Drive proceeding A to DECIDED (outside the active set).
        world_a = {
            "proceeding": a["proceeding"],
            "owner_headers": world["owner_headers"],
            "petitioner_headers": world["petitioner_headers"],
        }
        world_a = setup_decision_phase(world_a, hearing_outcome="WAIVED")
        issue_final_decision(
            world_a["proceeding"]["id"],
            outcomes_payload((1, "NOT_UNPATENTABLE"), (2, "NOT_UNPATENTABLE")),
        )
        # The identical decision for petition C now succeeds.
        data = validate_success(
            api_client.decide_institution(
                c["petition"]["id"],
                {"per_ground_scores": scores, "lead_judge_user_id": "judge-olga"},
                PANEL,
            ),
            201,
        )
        assert data["outcome"] == "INSTITUTED"
        assert data["proceeding_id"]
