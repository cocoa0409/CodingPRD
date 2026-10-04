"""Complaint weighting, deletion review cycles, discontinuation cascades, and
treasure-hunt markdown decisions."""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_many,
    assert_club_invariants,
    create_active_item,
    create_club,
    create_draft_item,
    create_member,
    create_open_run,
    create_region,
    create_vendor,
    file_complaint,
    receive_pallet,
    record_purchase,
    setup_received_pallets,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CM, DM, DP, MD, RO


def _item_with_complaint_score(score_target=None):
    """Region + vendor + club + ACTIVE REGULAR item; members and complaints per call."""
    region = create_region()
    vendor = create_vendor()
    club = create_club(region["id"])
    item = create_active_item(vendor["id"])
    return region, vendor, club, item


class TestItemActivation:
    def test_activate_from_draft_moves_to_active_and_bumps_version(self, api):
        """PRD §3.1: "Activation, performed by a `CategoryManager`, moves an item from `DRAFT` to `ACTIVE`."
        PRD §2.4: "a `version` integer that starts at 1 and increments by exactly 1 on every mutation of
        that entity."

        Design: Corner/state_machines/item_activate_from_draft_recomputes_fields
        """
        region = create_region()
        vendor = create_vendor()
        item = create_draft_item(vendor["id"])
        assert item["version"] == 1
        activated = validate_success(api.activate_item(item["id"], CM))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2, "the transition increments the version by exactly 1"


class TestDeletionReviewCycle:
    def test_reject_cycles_back_to_active_and_second_review_recomputes(self, api):
        """PRD §3.7: "Calling it on a `DELETION_REVIEW` item with `decision` equal to `REJECT` cycles the item
        back to `ACTIVE` with no field mutations beyond the usual `updated_at` and
        `version` bump."
        PRD §3.7: "Calling it without a decision on an `ACTIVE` item moves the item to `DELETION_REVIEW`
        and recomputes `complaint_weighted_score` and `complaint_count` from the
        trailing-30-day window so the manager reviews fresh numbers."

        Design: Difficulty/non_linear_state_machine/item_deletion_review_cycle_back_to_active
        """
        _, _, club, item = _item_with_complaint_score()
        m1 = create_member(club["id"], household_size=2)
        m2 = create_member(club["id"])
        file_complaint(m1["id"], item["id"], "QUALITY")  # 2.0 * 2 = 4.0
        first = validate_success(api.request_item_deletion(item["id"], CM))
        assert first["status"] == "DELETION_REVIEW"
        assert first["complaint_weighted_score"] == pytest.approx(4.0, abs=1e-2)
        rejected = validate_success(
            api.request_item_deletion(item["id"], CM, payload={"decision": "REJECT"})
        )
        assert rejected["status"] == "ACTIVE"
        file_complaint(m2["id"], item["id"], "QUALITY")  # 2.0 * 1 = 2.0
        second = validate_success(api.request_item_deletion(item["id"], CM))
        assert second["status"] == "DELETION_REVIEW"
        assert second["complaint_weighted_score"] == pytest.approx(6.0, abs=1e-2), (
            "recomputed from current OPEN complaints after the cycle, not the stale 4.0"
        )

    def test_second_review_opens_after_reject(self, api):
        """PRD §3.7: "Calling it without a decision on an `ACTIVE` item moves the item to `DELETION_REVIEW`
        and recomputes `complaint_weighted_score` and `complaint_count` from the
        trailing-30-day window so the manager reviews fresh numbers."

        Design: Difficulty/non_linear_state_machine/item_deletion_review_cycle_back_to_active
        """
        _, _, club, item = _item_with_complaint_score()
        validate_success(api.request_item_deletion(item["id"], CM))
        validate_success(api.request_item_deletion(item["id"], CM, payload={"decision": "REJECT"}))
        second = validate_success(api.request_item_deletion(item["id"], CM))
        assert second["status"] == "DELETION_REVIEW"
        assert second["complaint_count"] == 0

    def test_open_review_on_item_already_in_review_rejected(self, api):
        """PRD §3.7: "Calling it without a decision on an `ACTIVE` item moves the item to `DELETION_REVIEW`
        and recomputes `complaint_weighted_score` and `complaint_count` from the
        trailing-30-day window so the manager reviews fresh numbers. Calling it on a
        `DELETION_REVIEW` item with `decision` equal to `REJECT` cycles the item back to
        `ACTIVE` with no field mutations beyond the usual `updated_at` and `version`
        bump."
        PRD §2.9: "then state-machine admissibility (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/double_request_deletion_second_open_returns_invalid_state
        """
        _, _, _, item = _item_with_complaint_score()
        validate_success(api.request_item_deletion(item["id"], CM))
        validate_error(api.request_item_deletion(item["id"], CM), ApiErrorId.ERR_INVALID_STATE)


class TestApproveThreshold:
    def test_approve_below_threshold_guarded(self, api):
        """PRD §3.7: "Calling it with `decision` equal to `APPROVE` discontinues the item — but only when
        `complaint_weighted_score` is at least 25.0; below that threshold the approval
        is rejected with `ERR_REFERENTIAL_GUARD`, because an item may not be deleted
        over lukewarm member sentiment."

        Design: Corner/validations/item_deletion_approve_below_threshold_guarded
        """
        _, _, club, item = _item_with_complaint_score()
        member = create_member(club["id"], household_size=3)
        file_complaint(member["id"], item["id"], "QUALITY")  # 2.0 * 3 = 6.0 < 25.0
        validate_success(api.request_item_deletion(item["id"], CM))
        validate_error(
            api.request_item_deletion(item["id"], CM, payload={"decision": "APPROVE"}),
            ApiErrorId.ERR_REFERENTIAL_GUARD,
        )
        item_after = validate_success(api.get_item(item["id"], CM))
        assert item_after["status"] == "DELETION_REVIEW"


class TestDiscontinueCascade:
    def _setup_frozen_club_with_review_item(self, api):
        """Capacity-2 club filled by 2 PROPOSED allocations of one item; the item sits in
        DELETION_REVIEW with complaint_weighted_score 28.0 (>= 25.0 threshold)."""
        region = create_region()
        vendor = create_vendor()
        club = create_club(region["id"], floor_slot_capacity=2)
        ctx = setup_received_pallets(
            delivery_date="2026-09-02", num_pallets=2, club_capacity=2,
            item_overrides={"case_pack_qty": 6, "pallet_length_in": 40, "pallet_width_in": 40,
                            "cases_per_layer": 5, "max_layers": 4},
        )
        # Rebind the receiving context to the capacity-2 club by using its own club.
        club = ctx["club"]
        m1 = create_member(club["id"], household_size=3)
        m2 = create_member(club["id"], household_size=4)
        file_complaint(m1["id"], ctx["item"]["id"], "SAFETY")  # 4.0 * 3 = 12.0
        file_complaint(m2["id"], ctx["item"]["id"], "SAFETY")  # 4.0 * 4 = 16.0
        run = create_open_run(ctx["depot"]["id"], run_date="2026-09-02")
        allocs, _ = allocate_many(run["id"], run["version"], ctx["pallets"], club["id"])
        validate_success(api.request_item_deletion(ctx["item"]["id"], CM))
        return ctx, run, allocs

    def test_approve_discontinue_strands_pallets_and_voids_allocations(self, api):
        """PRD §3.7: "Discontinuation, by whatever path, is a heavy cascade. Every pallet of the item in
        `RECEIVED` or `ALLOCATED` becomes `STRANDED`. For each stranded pallet that was
        `ALLOCATED`, its `PROPOSED` allocation becomes `VOIDED` first with `void_reason`
        set to the string `ITEM_DISCONTINUED`, and each such void decrements the
        destination club's `allocated_slot_count` by the allocation's
        `floor_slots_reserved` and recomputes the club's posture."

        Design: Difficulty/transitive_cascade/item_discontinue_cascades_pallet_allocation_club_posture
        """
        ctx, run, allocs = self._setup_frozen_club_with_review_item(api)
        final = validate_success(
            api.request_item_deletion(ctx["item"]["id"], CM, payload={"decision": "APPROVE"})
        )
        assert final["status"] == "DISCONTINUED"
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "STRANDED", "cascaded from the item discontinue"
        alloc = validate_success(api.get_allocation(allocs[0]["id"], DP))
        assert alloc["status"] == "VOIDED"
        assert alloc["void_reason"] == "ITEM_DISCONTINUED"
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 0
        assert club["posture"] == "NORMAL", "third-order cascade: voids recompute posture"
        assert_club_invariants(club)

    def test_discontinue_cascade_returns_pallet_to_stranded_not_received(self, api):
        """PRD §3.7: "Unlike a planner-initiated void, the cascade never returns the pallet to `RECEIVED` — it
        is stranded for good, awaiting reconciliation. The item ends in the terminal
        `DISCONTINUED` state."

        Design: Difficulty/transitive_cascade/item_discontinue_cascades_pallet_allocation_club_posture
        """
        ctx, run, allocs = self._setup_frozen_club_with_review_item(api)
        validate_success(
            api.request_item_deletion(ctx["item"]["id"], CM, payload={"decision": "APPROVE"})
        )
        for pallet in ctx["pallets"]:
            after = validate_success(api.get_pallet(pallet["id"], DP))
            assert after["status"] == "STRANDED", "cascade strands; it never returns to RECEIVED"
        for alloc in allocs:
            after = validate_success(api.get_allocation(alloc["id"], DP))
            assert after["status"] == "VOIDED"
            assert after["void_reason"] == "ITEM_DISCONTINUED"


class TestMarkdownDecisions:
    def _setup_treasure_hunt_below_target(self, api, regional_ops_headers,
                                          sold=10, received=40, clock_after="2026-09-30T23:00:00Z"):
        """ACTIVE TREASURE_HUNT item (pallet_qty 40, target 80, exit 2026-09-30) with one
        received pallet and `sold` units purchased; clock advanced to the exit window.

        The pallet is received on 2026-09-30 itself so it remains in RECEIVED at the
        exit-window evaluation (PRD §3.3 strands a pallet only when the clock advances
        past its received_date)."""
        region = create_region()
        vendor = create_vendor()
        club = create_club(region["id"])
        depot_ctx = setup_received_pallets(
            delivery_date="2026-09-30", num_pallets=1,
            item_overrides={"case_pack_qty": 10, "pallet_length_in": 40, "pallet_width_in": 40,
                            "cases_per_layer": 2, "max_layers": 2, "item_type": "TREASURE_HUNT",
                            "exit_window_date": "2026-09-30", "sell_through_target_pct": 80},
        )
        member = create_member(depot_ctx["club"]["id"])
        if sold:
            record_purchase(member["id"], depot_ctx["club"]["id"], depot_ctx["item"]["id"], sold)
        api.set_clock(clock_after, regional_ops_headers)
        item = validate_success(api.get_item(depot_ctx["item"]["id"], CM))
        return depot_ctx, member, item

    def test_markdown_missing_pct_and_premature_sell_through_rejected(self, api, regional_ops_headers):
        """PRD §3.8: "the percentage is required exactly when `decision` is `MARKDOWN`, must then be greater
        than 0 and less than 100, and its absence or presence in the wrong combination
        is rejected with `ERR_MARKDOWN_RULE_VIOLATION`."
        PRD §3.8: "When the current logical date is on or after the item's `exit_window_date` and the
        recomputed `sell_through_pct` is below the item's `sell_through_target_pct`, the
        only lawful decision is `MARKDOWN`; a `SELL_THROUGH` decision in that situation
        is rejected with `ERR_MARKDOWN_RULE_VIOLATION`."

        Design: Corner/validations/markdown_missing_pct_and_premature_sell_through_rejected
        """
        ctx, member, item = self._setup_treasure_hunt_below_target(api, regional_ops_headers)
        # sell-through 10/40 = 25 < target 80 at the exit window.
        no_pct = api.create_markdown_decision(
            item["id"], {"decision": "MARKDOWN", "expected_item_version": item["version"]}, CM,
        )
        validate_error(no_pct, ApiErrorId.ERR_MARKDOWN_RULE_VIOLATION)
        premature = api.create_markdown_decision(
            item["id"], {"decision": "SELL_THROUGH", "expected_item_version": item["version"]}, CM,
        )
        validate_error(premature, ApiErrorId.ERR_MARKDOWN_RULE_VIOLATION)

    def test_markdown_decision_requires_pct_but_sell_through_at_exit_blocked(self, api, regional_ops_headers):
        """PRD §3.8: "the percentage is required exactly when `decision` is `MARKDOWN`, must then be greater
        than 0 and less than 100, and its absence or presence in the wrong combination
        is rejected with `ERR_MARKDOWN_RULE_VIOLATION`."
        PRD §3.8: "When the current logical date is on or after the item's `exit_window_date` and the
        recomputed `sell_through_pct` is below the item's `sell_through_target_pct`, the
        only lawful decision is `MARKDOWN`; a `SELL_THROUGH` decision in that situation
        is rejected with `ERR_MARKDOWN_RULE_VIOLATION`."

        Design: Corner/validations/markdown_missing_pct_and_premature_sell_through_rejected
        """
        ctx, member, item = self._setup_treasure_hunt_below_target(api, regional_ops_headers)
        # The lawful path at the exit window: MARKDOWN with a valid percentage.
        decision = validate_success(
            api.create_markdown_decision(
                item["id"],
                {"decision": "MARKDOWN", "expected_item_version": item["version"],
                 "markdown_pct": 30},
                CM,
            ), 201,
        )
        assert decision["decision"] == "MARKDOWN"
        assert decision["markdown_pct"] == 30


class TestNoReorder:
    def test_no_reorder_after_markdown_then_direct_discontinue(self, api, regional_ops_headers):
        """PRD §3.8: "The same error enforces the no-reorder rule on the receiving dock: once any `MARKDOWN`
        decision exists for an item, receiving further pallets of it is refused (§3.3)."
        PRD §3.8: "A treasure-hunt item with a recorded `MARKDOWN` decision may also be discontinued
        directly by a `CategoryManager`, skipping deletion review entirely: the direct
        path requires the item to be `ACTIVE`, requires `item_type` to be
        `TREASURE_HUNT`, and requires an existing `MARKDOWN` decision for the item —
        without one the request is rejected with `ERR_REFERENTIAL_GUARD`."

        Design: Corner/validations/treasure_hunt_no_reorder_after_markdown
        """
        region = create_region()
        vendor = create_vendor()
        club = create_club(region["id"])
        from test_helpers import create_depot, book_appointment, check_in_appointment
        depot = create_depot(region["id"])
        item = create_active_item(
            vendor["id"], case_pack_qty=10, cases_per_layer=2, max_layers=2,
            item_type="TREASURE_HUNT", exit_window_date="2026-09-30",
        )
        item_now = validate_success(api.get_item(item["id"], CM))
        decision = validate_success(
            api.create_markdown_decision(
                item["id"],
                {"decision": "MARKDOWN", "expected_item_version": item_now["version"],
                 "markdown_pct": 30},
                CM,
            ), 201,
        )
        # Second delivery on the exit-window date: receiving a further pallet is refused.
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-30", pallet_count=1)
        api.set_clock("2026-09-30T09:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        resp = api.create_pallet(
            {"appointment_id": appt["id"], "item_id": item["id"], "unit_qty": 40}, DM,
        )
        validate_error(resp, ApiErrorId.ERR_MARKDOWN_RULE_VIOLATION)
        # Direct discontinue is now enabled by the existing MARKDOWN decision.
        final = validate_success(api.discontinue_item(item["id"], CM))
        assert final["status"] == "DISCONTINUED"


class TestMarkdownOcc:
    def test_stale_item_version_rejected(self, api):
        """PRD §2.7: "When recording a markdown decision on an item, the request must carry
        `expected_item_version` holding the client-observed `version` of the item. If
        the item's `version` has advanced since that read, the request is rejected with
        `ERR_STALE_ITEM_VERSION` (HTTP 412), forcing the deciding manager to re-read the
        item before deciding."

        Design: Corner/endpoints/stale_item_version_occ_on_markdown_decision
        """
        region = create_region()
        vendor = create_vendor()
        item = create_draft_item(
            vendor["id"], item_type="TREASURE_HUNT", exit_window_date="2026-09-30",
            case_pack_qty=10, cases_per_layer=2, max_layers=2,
        )
        observed_version = item["version"]
        validate_success(api.activate_item(item["id"], CM))  # advances the version
        resp = api.create_markdown_decision(
            item["id"],
            {"decision": "SELL_THROUGH", "expected_item_version": observed_version},
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ITEM_VERSION)

    def test_current_item_version_accepted(self, api):
        """PRD §2.7: "When recording a markdown decision on an item, the request must carry
        `expected_item_version` holding the client-observed `version` of the item. If
        the item's `version` has advanced since that read, the request is rejected with
        `ERR_STALE_ITEM_VERSION` (HTTP 412), forcing the deciding manager to re-read the
        item before deciding."

        Design: Corner/endpoints/stale_item_version_occ_on_markdown_decision
        """
        region = create_region()
        vendor = create_vendor()
        item = create_active_item(
            vendor["id"], item_type="TREASURE_HUNT", exit_window_date="2026-09-30",
            case_pack_qty=10, cases_per_layer=2, max_layers=2,
        )
        # Current date 2026-09-01 is before the exit window: SELL_THROUGH is lawful.
        decision = validate_success(
            api.create_markdown_decision(
                item["id"],
                {"decision": "SELL_THROUGH", "expected_item_version": item["version"]},
                CM,
            ), 201,
        )
        assert decision["decision"] == "SELL_THROUGH"
