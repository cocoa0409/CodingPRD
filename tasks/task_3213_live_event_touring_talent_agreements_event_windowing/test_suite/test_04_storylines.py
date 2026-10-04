"""Storyline lifecycle: activation precondition, chapter indexing, gap
accounting, shelving sweeps, conclude rules, and revive."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_arena, create_event, create_storyline, create_chapter,
    activate_storyline, lock_event, complete_event, cancel_event,
    create_shelved_storyline,
    get_storyline,
)

SE = TEST_USERS["storyline_editor_headers"]
TP = TEST_USERS["tour_planner_headers"]


class TestStorylineActivation:
    def test_activation_requires_a_planned_chapter(self, api):
        """PRD §3.4: "A storyline can only be activated — `PLANNED → ACTIVE` — while it has at least one chapter still `PLANNED`; activation with none is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/storyline_activation_requires_planned_chapter
        """
        storyline = create_storyline(title="Empty Feud")
        resp = api.activate_storyline(storyline["id"], SE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_activation_with_planned_chapter_succeeds(self, api):
        """PRD §3.4: "A storyline can only be activated — `PLANNED → ACTIVE` — while it has at least one chapter still `PLANNED`; activation with none is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/storyline_activation_requires_planned_chapter
        """
        arena = create_arena(name="Act Arena")
        event = create_event(arena["id"], name="AE", event_date="2026-09-05")
        storyline = create_storyline(title="Real Feud")
        create_chapter(storyline["id"], event["id"])
        resp = api.activate_storyline(storyline["id"], SE)
        assert validate_success(resp)["status"] == "ACTIVE"


class TestChapterIndexing:
    def test_chapter_index_follows_event_date_not_creation_order(self, api):
        """PRD §3.4: "the system assigns a `chapter_index` — the chapter's 1-based position within its storyline, ordered by the event's `event_date` ascending, with ties broken by the event's `created_at` ascending."

        Design: Corner/calculations/chapter_index_chronological_assignment
        """
        storyline = create_storyline(title="Index Feud")
        arena = create_arena(name="Idx Arena")
        later = create_event(arena["id"], name="EL", event_date="2026-09-20")
        earlier = create_event(arena["id"], name="EE", event_date="2026-09-10")
        ch_later = validate_success(
            api.create_chapter({"storyline_id": storyline["id"], "event_id": later["id"]}, SE),
            expected_status=201)
        ch_earlier = validate_success(
            api.create_chapter({"storyline_id": storyline["id"], "event_id": earlier["id"]}, SE),
            expected_status=201)
        # chapter_index is the 1-based position ordered by event_date, so it is
        # only fully determined once both chapters exist; re-read the storyline's
        # chapters rather than trusting the first creation response.
        chapters, _meta = validate_paginated(
            api.list_storyline_chapters(storyline["id"], SE))
        by_id = {c["id"]: c for c in chapters}
        assert by_id[ch_later["id"]]["chapter_index"] == 2
        assert by_id[ch_earlier["id"]]["chapter_index"] == 1


class TestShelveReviveCycle:
    def test_shelve_at_three_gaps_then_revive_resets(self, api):
        """PRD §3.4: "a storyline whose `gap_count` reaches 3 flips `ACTIVE → SHELVED`, and the shelving sweep then flips all of its remaining `PLANNED` chapters to `MISSED` **without** further incrementing `gap_count`."
        PRD §3.4: "A `SHELVED` storyline may be revived by the `StorylineEditor`, returning to `ACTIVE` with `gap_count` reset to 0."

        Design: Difficulty/non_linear_state_machine/storyline_shelve_revive_cycle_resets_gaps
        """
        arena = create_arena(name="Cyc Arena")
        storyline, chapters, events = create_shelved_storyline(arena["id"])
        assert storyline["status"] == "SHELVED"
        assert storyline["gap_count"] == 3
        revived = validate_success(api.revive_storyline(storyline["id"], SE))
        assert revived["status"] == "ACTIVE"
        assert revived["gap_count"] == 0

    def test_revived_storyline_can_shelve_again(self, api):
        """PRD §3.4: "A `SHELVED` storyline may be revived by the `StorylineEditor`, returning to `ACTIVE` with `gap_count` reset to 0."
        PRD §3.4: "a storyline whose `gap_count` reaches 3 flips `ACTIVE → SHELVED`, and the shelving sweep then flips all of its remaining `PLANNED` chapters to `MISSED` **without** further incrementing `gap_count`."

        Design: Difficulty/non_linear_state_machine/storyline_shelve_revive_cycle_resets_gaps
        """
        arena = create_arena(name="Cyc Arena B")
        storyline, _, _ = create_shelved_storyline(arena["id"])
        validate_success(api.revive_storyline(storyline["id"], SE))
        # After revival the storyline holds a fresh 3-gap budget: three more
        # chapters on three more cancelled events shelve it a second time.
        dates = ["2026-09-10", "2026-09-11", "2026-09-12"]
        events = [create_event(arena["id"], name=f"CYC2-{d}", event_date=d) for d in dates]
        for e in events:
            create_chapter(storyline["id"], e["id"])
        for e in events:
            cancel_event(e["id"])
        final = get_storyline(storyline["id"])
        assert final["status"] == "SHELVED"
        assert final["gap_count"] == 3


class TestShelvingSweep:
    def test_shelving_misses_remaining_planned_chapters_without_extra_gaps(self, api):
        """PRD §3.4: "a storyline whose `gap_count` reaches 3 flips `ACTIVE → SHELVED`, and the shelving sweep then flips all of its remaining `PLANNED` chapters to `MISSED` **without** further incrementing `gap_count`."

        Design: Corner/state_machines/shelving_misses_remaining_planned_chapters_without_extra_gaps
        """
        storyline = create_storyline(title="Shelf Feud")
        arena = create_arena(name="Shelf Arena")
        events = [create_event(arena["id"], name=f"S{i}", event_date=f"2026-09-0{5 + i - 1}")
                  for i in range(1, 5)]
        for e in events:
            create_chapter(storyline["id"], e["id"])
        activate_storyline(storyline["id"])
        cancel_event(events[0]["id"])
        cancel_event(events[1]["id"])
        cancel_event(events[2]["id"])
        storyline_after = get_storyline(storyline["id"])
        assert storyline_after["status"] == "SHELVED"
        assert storyline_after["gap_count"] == 3
        chapters = api.list_event_chapters(events[3]["id"], SE)
        data, _meta = validate_paginated(chapters)
        assert len(data) == 1
        assert data[0]["status"] == "MISSED"


class TestGapResetByCompletion:
    def test_completed_chapter_resets_gap_count(self, api):
        """PRD §3.4: "When an event completes, each of its `PLANNED` chapters flips to `COMPLETED` and the owning storyline's `gap_count` resets to 0 — consecutive-gap semantics mean a completed chapter wipes the slate."

        Design: Corner/state_machines/event_completion_chapter_sweep_resets_gap
        """
        storyline = create_storyline(title="Reset Feud")
        arena = create_arena(name="Reset Arena")
        e1 = create_event(arena["id"], name="R1", event_date="2026-09-05")
        e2 = create_event(arena["id"], name="R2", event_date="2026-09-06")
        create_chapter(storyline["id"], e1["id"])
        ch2 = create_chapter(storyline["id"], e2["id"])
        activate_storyline(storyline["id"])
        cancel_event(e1["id"])
        assert get_storyline(storyline["id"])["gap_count"] == 1
        lock_event(e2)
        complete_event(e2["id"])
        chapters = api.list_event_chapters(e2["id"], SE)
        data, _ = validate_paginated(chapters)
        assert data[0]["id"] == ch2["id"]
        assert data[0]["status"] == "COMPLETED"
        assert get_storyline(storyline["id"])["gap_count"] == 0

    def test_miss_complete_miss_miss_stays_active_at_two_gaps(self, api):
        """PRD §3.4: "When an event completes, each of its `PLANNED` chapters flips to `COMPLETED` and the owning storyline's `gap_count` resets to 0 — consecutive-gap semantics mean a completed chapter wipes the slate."
        PRD §3.4: "When an event is cancelled, each of its `PLANNED` chapters flips to `MISSED` and the owning storyline's `gap_count` increases by 1; a storyline whose `gap_count` reaches 3 flips `ACTIVE → SHELVED`, and the shelving sweep then flips all of its remaining `PLANNED` chapters to `MISSED` **without** further incrementing `gap_count`."

        Design: Difficulty/compensating_invariant/storyline_gap_count_conservation_miss_then_complete
        """
        storyline = create_storyline(title="Gap Feud")
        arena = create_arena(name="Gap Arena")
        e1 = create_event(arena["id"], name="G1", event_date="2026-09-05")
        e2 = create_event(arena["id"], name="G2", event_date="2026-09-06")
        e3 = create_event(arena["id"], name="G3", event_date="2026-09-07")
        e4 = create_event(arena["id"], name="G4", event_date="2026-09-08")
        for e in (e1, e2, e3, e4):
            create_chapter(storyline["id"], e["id"])
        activate_storyline(storyline["id"])
        cancel_event(e1["id"])            # gap 1
        lock_event(e2)
        complete_event(e2["id"])          # reset to 0
        cancel_event(e3["id"])            # gap 1
        cancel_event(e4["id"])            # gap 2
        final = get_storyline(storyline["id"])
        assert final["gap_count"] == 2
        assert final["status"] == "ACTIVE"

    def test_completion_between_misses_wipes_the_slate(self, api):
        """PRD §3.4: "When an event completes, each of its `PLANNED` chapters flips to `COMPLETED` and the owning storyline's `gap_count` resets to 0 — consecutive-gap semantics mean a completed chapter wipes the slate."
        PRD §3.4: "When an event is cancelled, each of its `PLANNED` chapters flips to `MISSED` and the owning storyline's `gap_count` increases by 1; a storyline whose `gap_count` reaches 3 flips `ACTIVE → SHELVED`, and the shelving sweep then flips all of its remaining `PLANNED` chapters to `MISSED` **without** further incrementing `gap_count`."

        Design: Difficulty/compensating_invariant/storyline_gap_count_conservation_miss_then_complete
        """
        storyline = create_storyline(title="Wipe Feud")
        arena = create_arena(name="Wipe Arena")
        e1 = create_event(arena["id"], name="W1", event_date="2026-09-05")
        e2 = create_event(arena["id"], name="W2", event_date="2026-09-06")
        e3 = create_event(arena["id"], name="W3", event_date="2026-09-07")
        e4 = create_event(arena["id"], name="W4", event_date="2026-09-08")
        for e in (e1, e2, e3, e4):
            create_chapter(storyline["id"], e["id"])
        activate_storyline(storyline["id"])
        cancel_event(e1["id"])            # gap 1
        cancel_event(e2["id"])            # gap 2
        lock_event(e3)
        complete_event(e3["id"])          # reset to 0
        assert get_storyline(storyline["id"])["gap_count"] == 0
        cancel_event(e4["id"])            # gap 1
        final = get_storyline(storyline["id"])
        assert final["gap_count"] == 1
        assert final["status"] == "ACTIVE"


class TestStorylineConclude:
    def test_conclude_requires_all_chapters_terminal(self, api):
        """PRD §3.4: "A storyline may be concluded manually once every one of its chapters sits in a terminal state (`COMPLETED` or `MISSED`)"

        Design: Corner/state_machines/storyline_conclude_requires_all_chapters_terminal
        """
        storyline = create_storyline(title="Conclude Feud")
        arena = create_arena(name="Con Arena")
        event = create_event(arena["id"], name="EC", event_date="2026-09-05")
        create_chapter(storyline["id"], event["id"])
        activate_storyline(storyline["id"])
        early = api.conclude_storyline(storyline["id"], SE)
        validate_error(early, ApiErrorId.ERR_INVALID_STATE)
        cancel_event(event["id"])
        late = api.conclude_storyline(storyline["id"], SE)
        assert validate_success(late)["status"] == "CONCLUDED"

    def test_concluded_storyline_rejects_revive(self, api):
        """PRD §3.4: "A storyline may be concluded manually once every one of its chapters sits in a terminal state (`COMPLETED` or `MISSED`)"
        PRD §3.4: "A `SHELVED` storyline may be revived by the `StorylineEditor`, returning to `ACTIVE` with `gap_count` reset to 0."

        Design: Corner/state_machines/storyline_conclude_terminal_rejects_revive
        """
        storyline = create_storyline(title="Done Feud")
        arena = create_arena(name="Done Arena")
        event = create_event(arena["id"], name="DE", event_date="2026-09-05")
        create_chapter(storyline["id"], event["id"])
        activate_storyline(storyline["id"])
        lock_event(event)
        complete_event(event["id"])
        validate_success(api.conclude_storyline(storyline["id"], SE))
        resp = api.revive_storyline(storyline["id"], SE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
