"""Cyclic state machines: the Proceeding remand loop and the OralHearing
continuance loop (PRD §3.7, §3.9).
"""
from test_helpers import (
    PANEL,
    api_client,
    create_hearing_room,
    decide_appeal,
    file_brief,
    file_po_response,
    get_proceeding,
    outcomes_payload,
    request_hearing,
    resolve_hearing,
    schedule_hearing,
    set_clock,
    setup_decided_proceeding,
    setup_decided_with_appeal,
    setup_instituted_proceeding,
    validate_success,
)


class TestProceedingRemandCycleReopensTrial:
    def _remanded_world(self):
        # Cycle 0: full trial, claim 1 UNPATENTABLE, claim 2
        # NOT_UNPATENTABLE -> DECIDED; petitioner appeals; clock at remand.
        world = setup_decided_with_appeal(
            institute_kw=dict(
                total_claims=3, challenged_claims=(1, 2),
                scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 88},
                        {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 77}],
                lead_judge="judge-frank",
            ),
            outcomes=outcomes_payload((1, "UNPATENTABLE"), (2, "NOT_UNPATENTABLE")),
            hearing_start="2027-03-01T14:00:00Z", hearing_end="2027-03-01T15:00:00Z",
        )
        set_clock("2027-10-01T00:00:00Z")
        decide_appeal(world["appeal"]["id"], "VACATED_AND_REMANDED",
                      remand_instructions="REOPEN_RECORD")
        return world

    def test_remand_increments_cycle_and_restores_amendment_budget(self):
        """PRD §3.9: "The proceeding moves `DECIDED → REMANDED`:
        `briefing_cycle` increments by one; `cycle_anchor_date` re-anchors to
        the remand timestamp, so all three briefing windows of §3.5 reopen
        from it; `amendment_slots_available` gains one, a fresh motion of
        right for the new cycle; and `estoppel_applied` flips back to false,
        the vacated decision voiding the estoppel."

        Design: Difficulty/non_linear_state_machine/proceeding_remand_cycle_reopens_trial_and_reanchors_windows
        """
        world = self._remanded_world()
        proceeding = get_proceeding(world["proceeding"]["id"])
        assert proceeding["phase"] == "REMANDED"
        assert proceeding["briefing_cycle"] == 1
        # The unconsumed cycle-0 slot plus the fresh remand slot.
        assert proceeding["amendment_slots_available"] == 2
        assert proceeding["estoppel_applied"] is False

    def test_remanded_proceeding_reenters_briefing_under_reanchored_window(self):
        """PRD §3.9: "the patent owner's `PO_RESPONSE` filed from `REMANDED`
        re-enters `REPLY_WINDOW` under the same 90-day window, sequence, and
        page rules as the original cycle".

        Design: Difficulty/non_linear_state_machine/proceeding_remand_cycle_reopens_trial_and_reanchors_windows
        """
        world = self._remanded_world()
        # Filed 2027-10-01, within the re-anchored window (anchor 2027-10-01
        # + 90 days = 2027-12-30).
        brief = file_po_response(world, 60)
        assert brief["cycle"] == 1
        assert get_proceeding(world["proceeding"]["id"])["phase"] == "REPLY_WINDOW"


class TestOralHearingContinuanceLoop:
    def _scheduled_world(self):
        world = setup_instituted_proceeding(
            total_claims=3, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 70},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 65}],
            lead_judge="judge-gail",
        )
        file_po_response(world, 85)  # phase REPLY_WINDOW
        world["room"] = create_hearing_room(name="Room R7", capacity=30)
        world["hearing"] = request_hearing(
            world["proceeding"]["id"], world["owner_headers"], argument_minutes=60
        )
        world["hearing"] = schedule_hearing(
            world["hearing"]["id"], world["room"]["id"],
            "2027-03-01T14:00:00Z", "2027-03-01T15:00:00Z",
        )
        return world

    def test_continuance_releases_the_room_booking(self):
        """PRD §3.7: "A continuance releases the booking: `hearing_room_id`,
        `start_at`, and `end_at` return to null, the hearing drops back to
        `REQUESTED`, and the proceeding's phase is left unchanged".

        Design: Difficulty/non_linear_state_machine/oral_hearing_continuance_loop_releases_and_rebooks_room
        """
        world = self._scheduled_world()
        resp = api_client.resolve_oral_hearing(
            world["hearing"]["id"], {"outcome": "CONTINUED"}, PANEL
        )
        hearing = validate_success(resp, 200)
        assert hearing["status"] == "REQUESTED"
        assert hearing["hearing_room_id"] is None
        assert hearing["start_at"] is None
        assert hearing["end_at"] is None

    def test_released_slot_rebooks_then_held_advances_to_decision_phase(self):
        """PRD §3.7: "A hearing held or waived moves the proceeding from
        `HEARING_PHASE` to `DECISION_PHASE`."

        Design: Difficulty/non_linear_state_machine/oral_hearing_continuance_loop_releases_and_rebooks_room
        """
        world = self._scheduled_world()
        resolve_hearing(world["hearing"]["id"], "CONTINUED", PANEL)
        # Rebook the SAME room: the released booking must not self-conflict.
        rebooked = schedule_hearing(
            world["hearing"]["id"], world["room"]["id"],
            "2027-04-05T14:00:00Z", "2027-04-05T15:00:00Z",
        )
        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["start_at"].startswith("2027-04-05T14:00:00")
        final = resolve_hearing(world["hearing"]["id"], "HELD", PANEL)
        assert final["status"] == "HELD"
        assert get_proceeding(world["proceeding"]["id"])["phase"] == "DECISION_PHASE"
