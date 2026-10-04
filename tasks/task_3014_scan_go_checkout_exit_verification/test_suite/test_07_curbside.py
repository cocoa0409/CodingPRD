"""Curbside pickup: staging slots, half-open windows, OCC, and pickup."""
from test_helpers import (
    ASSOCIATE,
    ApiErrorId,
    create_club,
    create_curbside_order,
    create_member,
    get_curbside_order,
    member_headers,
    patch_club,
    stage_order,
    validate_error,
    validate_success,
)

S1 = "2026-09-01T10:00:00Z"
E1 = "2026-09-01T11:00:00Z"
S2 = "2026-09-01T11:00:00Z"
E2 = "2026-09-01T12:00:00Z"


class TestStagingWindowsAndCapacity:
    def test_invalid_window_temporal_beats_slot_capacity_constraint(self, api):
        """PRD §2.8: "Across a single request, validation proceeds in a fixed
        priority order so that overlapping failures surface deterministically.
        ... then temporal gates (windows and shopping-hours), then aggregate
        and referential constraints (capacities, conflicts,
        one-active-session)"; PRD §3.9: "A window whose end is not strictly
        after its start is rejected with `ERR_SLOT_WINDOW_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_window_temporal_beats_slot_capacity_constraint
        """
        club = create_club()
        club = patch_club(club["id"], club["version"], staging_slot_capacity=1)
        member = create_member(club["id"], tier="CLUB", birth_year=1982)
        order_a = create_curbside_order(club, member, item_count=2)
        stage_order(order_a["id"], "S1", "2026-09-01T09:00:00Z", "2026-09-01T13:00:00Z")
        order_b = create_curbside_order(club, member, item_count=1)

        # Inverted window AND slot at capacity: the temporal gate wins.
        resp = api.stage_curbside_order(
            order_b["id"],
            {
                "staging_slot_label": "S1",
                "window_start_iso": "2026-09-01T12:00:00Z",
                "window_end_iso": "2026-09-01T11:00:00Z",
            },
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_INVALID)
        assert get_curbside_order(order_b["id"])["status"] == "PLACED"

    def test_invalid_window_rejected_even_with_free_slot(self, api):
        """PRD §3.9: "A window whose end is not strictly after its start is
        rejected with `ERR_SLOT_WINDOW_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_window_temporal_beats_slot_capacity_constraint
        """
        club = create_club()  # default capacity 2, no occupancy
        member = create_member(club["id"], tier="CLUB", birth_year=1982)
        order = create_curbside_order(club, member, item_count=1)

        resp = api.stage_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S1",
                "window_start_iso": "2026-09-01T12:00:00Z",
                "window_end_iso": "2026-09-01T11:00:00Z",
            },
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_INVALID)
        assert get_curbside_order(order["id"])["status"] == "PLACED"

    def test_invalid_window_rejected_even_with_free_slot(self, api):
        """PRD §3.9: "A window whose end is not strictly after its start is
        rejected with `ERR_SLOT_WINDOW_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_window_temporal_beats_slot_capacity_constraint
        """
        club = create_club()  # default capacity 2, no occupancy
        member = create_member(club["id"], tier="CLUB", birth_year=1982)
        order = create_curbside_order(club, member, item_count=1)

        resp = api.stage_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S1",
                "window_start_iso": "2026-09-01T12:00:00Z",
                "window_end_iso": "2026-09-01T11:00:00Z",
            },
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_INVALID)
        assert get_curbside_order(order["id"])["status"] == "PLACED"

    def test_staging_slot_half_open_adjacency_and_capacity(self, api):
        """PRD §3.9: "The window is half-open: it includes its start instant
        and excludes its end instant, so back-to-back windows — one ending at
        11:00 and another beginning at 11:00 — do not overlap."; "Staging is
        rejected with `ERR_SLOT_CAPACITY_EXCEEDED` when that occupancy already
        equals the club's `staging_slot_capacity`."

        Design: Difficulty/resource_temporal_overlap/staging_slot_half_open_adjacency_and_capacity
        """
        club = create_club()
        club = patch_club(club["id"], club["version"], staging_slot_capacity=1)
        member = create_member(club["id"], tier="CLUB", birth_year=1984)
        order_a = create_curbside_order(club, member, item_count=1)
        stage_order(order_a["id"], "S1", S1, E1)
        order_b = create_curbside_order(club, member, item_count=1)
        order_c = create_curbside_order(club, member, item_count=1)

        # Adjacent half-open window [11:00,12:00) coexists with [10:00,11:00).
        resp = api.stage_curbside_order(
            order_b["id"],
            {"staging_slot_label": "S1", "window_start_iso": S2, "window_end_iso": E2},
            ASSOCIATE,
        )
        staged_b = validate_success(resp)
        assert staged_b["status"] == "STAGING"

        # Genuinely overlapping third window hits the capacity gate.
        resp = api.stage_curbside_order(
            order_c["id"],
            {
                "staging_slot_label": "S1",
                "window_start_iso": "2026-09-01T10:30:00Z",
                "window_end_iso": "2026-09-01T11:30:00Z",
            },
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)
        assert get_curbside_order(order_c["id"])["status"] == "PLACED"

    def test_adjacent_windows_do_not_count_toward_occupancy(self, api):
        """PRD §3.9: "The occupancy of a slot label over a candidate window is
        the number of orders at the same club, in `STAGING` or `STAGED`,
        sharing that label, whose windows overlap the candidate — overlap
        meaning each existing window starts strictly before the candidate ends
        and the candidate starts strictly before the existing window ends."

        Design: Difficulty/resource_temporal_overlap/staging_slot_half_open_adjacency_and_capacity
        """
        club = create_club()
        club = patch_club(club["id"], club["version"], staging_slot_capacity=1)
        member = create_member(club["id"], tier="CLUB", birth_year=1984)
        order_a = create_curbside_order(club, member, item_count=1)
        stage_order(order_a["id"], "S1", S1, E1)
        order_b = create_curbside_order(club, member, item_count=1)

        resp = api.stage_curbside_order(
            order_b["id"],
            {"staging_slot_label": "S1", "window_start_iso": S2, "window_end_iso": E2},
            ASSOCIATE,
        )
        staged_b = validate_success(resp)
        assert staged_b["status"] == "STAGING"
        assert staged_b["staging_slot_label"] == "S1"

    def test_stage_then_cancel_restores_slot_occupancy(self, api):
        """PRD §3.9: "The member may cancel their own order from `PLACED`,
        `STAGING`, or `STAGED`; cancelling a staged or staging order likewise
        releases the slot"."

        Design: Difficulty/compensating_invariant/stage_then_cancel_restores_slot_occupancy
        """
        club = create_club()
        club = patch_club(club["id"], club["version"], staging_slot_capacity=1)
        member = create_member(club["id"], tier="CLUB", birth_year=1981)
        order_a = create_curbside_order(club, member, item_count=2)
        order_b = create_curbside_order(club, member, item_count=3)
        stage_order(order_a["id"], "S1", S1, E1)

        overlap = {
            "staging_slot_label": "S1",
            "window_start_iso": "2026-09-01T10:30:00Z",
            "window_end_iso": "2026-09-01T11:30:00Z",
        }
        resp = api.stage_curbside_order(order_b["id"], overlap, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)

        resp = api.cancel_curbside_order(order_a["id"], member_headers(member))
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

        resp = api.stage_curbside_order(order_b["id"], overlap, ASSOCIATE)
        staged_b = validate_success(resp)
        assert staged_b["status"] == "STAGING"

    def test_cancel_releases_occupancy_observable_by_third_stage(self, api):
        """PRD §3.9: "Staging is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`
        when that occupancy already equals the club's
        `staging_slot_capacity`."; "cancelling a staged or staging order
        likewise releases the slot".

        Design: Difficulty/compensating_invariant/stage_then_cancel_restores_slot_occupancy
        """
        club = create_club()
        club = patch_club(club["id"], club["version"], staging_slot_capacity=1)
        member = create_member(club["id"], tier="CLUB", birth_year=1981)
        order_a = create_curbside_order(club, member, item_count=1)
        order_b = create_curbside_order(club, member, item_count=1)
        order_c = create_curbside_order(club, member, item_count=1)
        stage_order(order_a["id"], "S1", S1, E1)
        stage_order(order_b["id"], "S1", S2, E2)  # adjacent: no overlap

        overlap_window = {
            "staging_slot_label": "S1",
            "window_start_iso": "2026-09-01T10:30:00Z",
            "window_end_iso": "2026-09-01T11:30:00Z",
        }
        resp = api.stage_curbside_order(order_c["id"], overlap_window, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)

        api.cancel_curbside_order(order_a["id"], member_headers(member))
        # Only B overlaps the candidate window now; capacity 1 blocks again.
        resp = api.stage_curbside_order(order_c["id"], overlap_window, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)

        api.cancel_curbside_order(order_b["id"], member_headers(member))
        resp = api.stage_curbside_order(order_c["id"], overlap_window, ASSOCIATE)
        assert validate_success(resp)["status"] == "STAGING"


class TestCurbsideLifecycle:
    def test_curbside_staged_demotes_to_staging_on_reschedule(self, api):
        """PRD §3.9: "A member may also reschedule their own order from
        `STAGING` or `STAGED`, replacing the `staging_slot_label`,
        `window_start_iso`, and `window_end_iso` wholesale; the new window must
        satisfy the same validity and capacity rules, except that the order's
        own current occupancy does not count against it, and a `STAGED` order
        is demoted back to `STAGING` by the move."

        Design: Difficulty/non_linear_state_machine/curbside_staged_demotes_to_staging_on_reschedule
        """
        club = create_club()
        member = create_member(club["id"], tier="CLUB", birth_year=1975)
        order = create_curbside_order(club, member, item_count=4)
        staged = stage_order(
            order["id"], "S1", "2026-09-01T14:00:00Z", "2026-09-01T15:00:00Z",
        )
        resp = api.mark_staged(order["id"], ASSOCIATE)
        marked = validate_success(resp)
        assert marked["status"] == "STAGED"

        resp = api.reschedule_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S2",
                "window_start_iso": "2026-09-01T16:00:00Z",
                "window_end_iso": "2026-09-01T17:00:00Z",
                "expected_curbside_order_version": marked["version"],
            },
            member_headers(member),
        )
        demoted = validate_success(resp)
        assert demoted["status"] == "STAGING"
        assert demoted["staging_slot_label"] == "S2"

    def test_demoted_order_can_be_restaged_and_picked_up(self, api):
        """PRD §3.9: "Once physically loaded, the order is marked staged
        (`STAGING → STAGED`) and the acting associate's identity is recorded as
        `staged_by_associate_id`."; "The member picks up a `STAGED` order ...
        which moves the order to its terminal `PICKED_UP` state and releases
        the slot occupancy."

        Design: Difficulty/non_linear_state_machine/curbside_staged_demotes_to_staging_on_reschedule
        """
        club = create_club()
        member = create_member(club["id"], tier="CLUB", birth_year=1975)
        order = create_curbside_order(club, member, item_count=4)
        staged = stage_order(
            order["id"], "S1", "2026-09-01T14:00:00Z", "2026-09-01T15:00:00Z",
        )
        resp = api.mark_staged(order["id"], ASSOCIATE)
        marked = validate_success(resp)
        resp = api.reschedule_curbside_order(
            order["id"],
            {
                "staging_slot_label": "S2",
                "window_start_iso": "2026-09-01T16:00:00Z",
                "window_end_iso": "2026-09-01T17:00:00Z",
                "expected_curbside_order_version": marked["version"],
            },
            member_headers(member),
        )
        validate_success(resp)

        resp = api.mark_staged(order["id"], ASSOCIATE)
        assert validate_success(resp)["status"] == "STAGED"
        resp = api.pickup_curbside_order(order["id"], member_headers(member))
        assert validate_success(resp)["status"] == "PICKED_UP"

    def test_pickup_before_staged_rejected(self, api):
        """PRD §3.9: "The member picks up a `STAGED` order — pickup from any
        other state is rejected with `ERR_CURBSIDE_NOT_CANCELLABLE`'s sibling
        `ERR_CURBSIDE_NOT_STAGED`".

        Design: Corner/state_machines/pickup_before_staged_rejected
        """
        club = create_club()
        member = create_member(club["id"], tier="CLUB", birth_year=1990)
        order = create_curbside_order(club, member, item_count=2)
        stage_order(order["id"], "S1", "2026-09-01T14:00:00Z", "2026-09-01T15:00:00Z")

        resp = api.pickup_curbside_order(order["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_CURBSIDE_NOT_STAGED)
        assert get_curbside_order(order["id"])["status"] == "STAGING"

    def test_cancel_picked_up_order_rejected(self, api):
        """PRD §3.9: "cancelling a terminal order (`PICKED_UP`, `CANCELLED`,
        or `EXPIRED`) is rejected with `ERR_CURBSIDE_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_picked_up_order_rejected
        """
        club = create_club()
        member = create_member(club["id"], tier="CLUB", birth_year=1990)
        order = create_curbside_order(club, member, item_count=1)
        stage_order(order["id"], "S1", "2026-09-01T14:00:00Z", "2026-09-01T15:00:00Z")
        api.mark_staged(order["id"], ASSOCIATE)
        resp = api.pickup_curbside_order(order["id"], member_headers(member))
        assert validate_success(resp)["status"] == "PICKED_UP"

        resp = api.cancel_curbside_order(order["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_CURBSIDE_NOT_CANCELLABLE)
