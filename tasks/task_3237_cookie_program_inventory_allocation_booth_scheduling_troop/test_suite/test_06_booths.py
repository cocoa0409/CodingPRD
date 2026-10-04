"""Booth locations, slots, half-open overlap, lottery draw, and capacity."""
from test_helpers import (
    ApiErrorId,
    assert_booth_request,
    create_booth_location_payload,
    create_booth_request_payload,
    create_booth_slot_payload,
    create_troop_with_account,
    get_booth_request,
    make_council_admin_headers,
    setup_booth_arena,
    setup_selling_season,
    validate_error,
    validate_success,
)


class TestSlotCreationGates:
    def test_booth_approve_gated_by_location_permission(self, api):
        """PRD §3.5: "Slot creation is refused with `ERR_BOOTH_CONFLICT` when
        host permission is missing, when the slot's date appears in the
        location's blackout dates, or when the new interval overlaps an
        existing slot at the same location — touching boundaries, where one
        slot's `end_at` equals another's `start_at`, are explicitly allowed."

        Design: Difficulty/cross_entity_state_dependency/booth_approve_gated_by_location_permission
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season = ctx["season"]
        location = validate_success(
            api.create_booth_location(
                season["id"],
                create_booth_location_payload(host_permission_granted=False),
                admin,
            ),
            expected_status=201,
        )
        resp = api.create_booth_slot(
            create_booth_slot_payload(location["id"]), admin
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_CONFLICT, 409)
        resp2 = api.create_booth_slot(
            create_booth_slot_payload(location["id"]), admin
        )
        validate_error(resp2, ApiErrorId.ERR_BOOTH_CONFLICT, 409)

    def test_blackout_date_blocks_slot_creation(self, api):
        """PRD §3.5: "Slot creation is refused with `ERR_BOOTH_CONFLICT` when
        host permission is missing, when the slot's date appears in the
        location's blackout dates, or when the new interval overlaps an
        existing slot at the same location — touching boundaries, where one
        slot's `end_at` equals another's `start_at`, are explicitly allowed."

        Design: Corner/validations/blackout_date_blocks_slot_creation
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season = ctx["season"]
        location = validate_success(
            api.create_booth_location(
                season["id"],
                create_booth_location_payload(blackout_dates=["2027-02-14"]),
                admin,
            ),
            expected_status=201,
        )
        resp = api.create_booth_slot(
            create_booth_slot_payload(
                location["id"],
                start_at="2027-02-14T14:00:00Z",
                end_at="2027-02-14T16:00:00Z",
            ),
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_CONFLICT, 409)

    def test_booth_slot_half_open_interval_overlap(self, api):
        """PRD §3.5: "Slot creation is refused with `ERR_BOOTH_CONFLICT` when
        host permission is missing, when the slot's date appears in the
        location's blackout dates, or when the new interval overlaps an
        existing slot at the same location — touching boundaries, where one
        slot's `end_at` equals another's `start_at`, are explicitly allowed."

        Design: Difficulty/resource_temporal_overlap/booth_slot_half_open_interval_overlap
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        arena = setup_booth_arena(ctx["season"]["id"], admin=admin)
        # Touching boundary: 16:00 == 16:00 -> allowed under half-open semantics.
        touching = validate_success(
            api.create_booth_slot(
                create_booth_slot_payload(
                    arena["location"]["id"],
                    start_at="2027-02-10T16:00:00Z",
                    end_at="2027-02-10T18:00:00Z",
                ),
                admin,
            ),
            expected_status=201,
        )
        assert touching["location_id"] == arena["location"]["id"]
        # Interior overlap 15:00-17:00 vs 14:00-16:00 -> conflict.
        resp = api.create_booth_slot(
            create_booth_slot_payload(
                arena["location"]["id"],
                start_at="2027-02-10T15:00:00Z",
                end_at="2027-02-10T17:00:00Z",
            ),
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_CONFLICT, 409)


class TestLotteryDraw:
    def test_lottery_draw_rank_order_and_rank_gt2_denied(self, api):
        """PRD §3.5: "Candidates are the slot's `PENDING` requests in `LOTTERY`
        mode whose `lottery_rank` is at most 2, ordered by rank ascending and
        then by `created_at` ascending — earliest submission breaks ties, and
        the request `id` is never used as an ordering key. The draw approves
        the first candidates up to the slot's remaining capacity (its
        `capacity_troops` minus the current approved count) and denies the rest
        with `decision_reason` set to `LOTTERY_LOST`; pending lottery requests
        whose rank exceeds 2 are denied at the same draw with `decision_reason`
        set to `RANK_GT_2`."

        Design: Corner/calculations/lottery_draw_rank_order_and_rank_gt2_denied
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season = ctx["season"]
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        troop3, account3, leader3 = create_troop_with_account(season["id"], admin=admin)
        arena = setup_booth_arena(season["id"], admin=admin)
        slot = arena["slot"]
        br1 = validate_success(
            api.create_booth_request(
                slot["id"],
                create_booth_request_payload(ctx["troop"]["id"], "LOTTERY", lottery_rank=2),
                ctx["leader"],
            ),
            expected_status=201,
        )
        br2 = validate_success(
            api.create_booth_request(
                slot["id"],
                create_booth_request_payload(troop2["id"], "LOTTERY", lottery_rank=1),
                leader2,
            ),
            expected_status=201,
        )
        br3 = validate_success(
            api.create_booth_request(
                slot["id"],
                create_booth_request_payload(troop3["id"], "LOTTERY", lottery_rank=3),
                leader3,
            ),
            expected_status=201,
        )
        draw = validate_success(api.draw_lottery(slot["id"], admin))
        assert draw["approved_request_ids"] == [br2["id"]]
        br1_after = get_booth_request(br1["id"], admin=admin)
        assert br1_after["status"] == "DENIED"
        assert br1_after["decision_reason"] == "LOTTERY_LOST"
        br3_after = get_booth_request(br3["id"], admin=admin)
        assert br3_after["status"] == "DENIED"
        assert br3_after["decision_reason"] == "RANK_GT_2"


class TestBoothRequestCancel:
    def test_booth_request_approved_cancel_frees_capacity(self, api):
        """PRD §3.5: "A requesting troop may cancel its own request while
        `PENDING`, and may also cancel after approval — which frees one unit of
        slot occupancy — but a leader cancelling another troop's request is
        refused with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/state_machines/booth_request_approved_cancel_frees_capacity
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season = ctx["season"]
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        arena = setup_booth_arena(season["id"], admin=admin)
        slot = arena["slot"]
        br1 = validate_success(
            api.create_booth_request(
                slot["id"],
                create_booth_request_payload(ctx["troop"]["id"], "FIRST_COME"),
                ctx["leader"],
            ),
            expected_status=201,
        )
        assert_booth_request(br1)
        assert br1["status"] == "APPROVED"
        validate_success(api.cancel_booth_request(br1["id"], ctx["leader"]))
        br2 = validate_success(
            api.create_booth_request(
                slot["id"],
                create_booth_request_payload(troop2["id"], "FIRST_COME"),
                leader2,
            ),
            expected_status=201,
        )
        assert br2["status"] == "APPROVED"
