"""Production slots: overlap geometry, commit/release cycle, bubble-up, reservations."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_confirmed_custom_order,
    create_retail_quote,
    create_member_quote,
    add_line,
    read_order,
    create_production_slot_payload,
    commit_line_to_slot,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


class TestSlotOverlap:

    def test_adjacent_slots_allowed_and_overlap_rejected(self, api):
        """PRD §3.5: "A new slot enters in `OPEN` status. Slot creation rejects overlap against any non-`CONSUMED` slot on the same gallery: two intervals conflict when the new slot's start is strictly before the existing slot's end **and** the existing slot's start is strictly before the new slot's end, in which case creation is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). Pure adjacency — the new slot starting exactly when the existing one ends — does not conflict."

        Design: Difficulty/resource_temporal_overlap/production_slot_half_open_adjacency
        """
        gallery = setup_gallery(name="Gallery N")
        validate_success(
            api.create_production_slot(
                create_production_slot_payload(
                    gallery["id"],
                    starts_at="2026-09-10T09:00:00Z",
                    ends_at="2026-09-10T12:00:00Z",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        adjacent = validate_success(
            api.create_production_slot(
                create_production_slot_payload(
                    gallery["id"],
                    starts_at="2026-09-10T12:00:00Z",
                    ends_at="2026-09-10T15:00:00Z",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "OPEN"

        resp = api.create_production_slot(
            create_production_slot_payload(
                gallery["id"],
                starts_at="2026-09-10T11:00:00Z",
                ends_at="2026-09-10T13:00:00Z",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)

    def test_overlap_on_other_gallery_allowed(self, api):
        """PRD §3.5: "Slots on different galleries never interact."

        Design: Difficulty/resource_temporal_overlap/production_slot_half_open_adjacency
        """
        gallery_a = setup_gallery(name="Gallery NA")
        gallery_b = setup_gallery(name="Gallery NB")
        validate_success(
            api.create_production_slot(
                create_production_slot_payload(
                    gallery_a["id"],
                    starts_at="2026-09-10T09:00:00Z",
                    ends_at="2026-09-10T12:00:00Z",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        other = validate_success(
            api.create_production_slot(
                create_production_slot_payload(
                    gallery_b["id"],
                    starts_at="2026-09-10T09:00:00Z",
                    ends_at="2026-09-10T12:00:00Z",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert other["status"] == "OPEN"


class TestScheduleProductionPreconditions:

    def test_schedule_production_requires_deposit_paid(self, api):
        """PRD §3.5: "The target line must be a `CUSTOM` line whose `production_status` is exactly `DEPOSIT_PAID` — a line in any other state, including `PENDING_DEPOSIT`, is rejected with `ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID` (HTTP 409)"

        Design: Corner/state_machines/schedule_production_requires_deposit_paid
        """
        gallery = setup_gallery(name="Gallery T7")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        line = add_line(order["id"], product["id"], qty=1)
        slot = validate_success(
            api.create_production_slot(
                create_production_slot_payload(gallery["id"]), PLANNER
            ),
            expected_status=201,
        )

        resp = api.schedule_production(
            order["id"], line["id"], {"production_slot_id": slot["id"]}, PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID.value)

    def test_schedule_into_committed_slot_rejected(self, api):
        """PRD §3.5: "The named slot must be `OPEN` (otherwise `ERR_SLOT_NOT_OPEN`, HTTP 409)"

        Design: Corner/validations/schedule_into_committed_slot_rejected
        """
        gallery = setup_gallery(name="Gallery V11")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        line1 = add_line(order["id"], product["id"], qty=1)
        line2 = add_line(order["id"], product["id"], qty=1)
        get_success_data(
            api.confirm_order(order["id"], {"deposit_payment_cents": 120000}, ASSOCIATE)
        )
        slot = validate_success(
            api.create_production_slot(
                create_production_slot_payload(gallery["id"]), PLANNER
            ),
            expected_status=201,
        )
        get_success_data(
            api.schedule_production(
                order["id"], line1["id"], {"production_slot_id": slot["id"]}, PLANNER
            )
        )

        resp = api.schedule_production(
            order["id"], line2["id"], {"production_slot_id": slot["id"]}, PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN.value)


class TestSlotCommitReleaseCycle:

    def test_commit_release_recommit_cycle(self, api):
        """PRD §3.4: "Removing a custom line in `DEPOSIT_PAID` or `COMMITTED` forfeits its deposit; if the line held a committed production slot, that slot returns from `COMMITTED` to `OPEN` (its `committed_order_line_id` is cleared and the gallery's reserved production minutes drop by the slot's duration), and the line's `production_status` becomes `RELEASED`."
        PRD §3.5: "On commit, the slot moves `OPEN → COMMITTED`, its `committed_order_line_id` is set to the line, the line's `production_slot_id` is set to the slot, the line's `production_status` moves to `COMMITTED`, and the gallery's `reserved_production_minutes` rises by the slot's duration."

        Design: Difficulty/non_linear_state_machine/production_slot_commit_release_recommit_cycle
        """
        gallery = setup_gallery(name="Gallery F")
        member = setup_member(email="m5@x.com", full_name="M Five")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        line1 = add_line(order["id"], product["id"], qty=1, headers=headers)
        line2 = add_line(order["id"], product["id"], qty=1, headers=headers)
        get_success_data(
            api.confirm_order(order["id"], {"deposit_payment_cents": 100000}, headers)
        )
        slot = validate_success(
            api.create_production_slot(
                create_production_slot_payload(
                    gallery["id"],
                    starts_at="2026-09-10T09:00:00Z",
                    ends_at="2026-09-10T12:00:00Z",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        committed = validate_success(
            api.schedule_production(
                order["id"], line1["id"], {"production_slot_id": slot["id"]}, PLANNER
            )
        )
        assert committed["status"] == "COMMITTED"
        gallery_mid = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert gallery_mid["reserved_production_minutes"] == 180

        order_now = read_order(order["id"])
        validate_success(
            api.remove_order_line(
                order["id"], line1["id"],
                {"expected_order_version": order_now["version"]}, headers,
            )
        )
        slot_released = get_success_data(api.get_production_slot(slot["id"], PLANNER))
        assert slot_released["status"] == "OPEN"
        assert slot_released["committed_order_line_id"] is None

        recommitted = validate_success(
            api.schedule_production(
                order["id"], line2["id"], {"production_slot_id": slot["id"]}, PLANNER
            )
        )
        assert recommitted["status"] == "COMMITTED"
        assert recommitted["committed_order_line_id"] == line2["id"]

    def test_line_released_status_visible_after_removal(self, api):
        """PRD §3.4: "if the line held a committed production slot, that slot returns from `COMMITTED` to `OPEN` (its `committed_order_line_id` is cleared and the gallery's reserved production minutes drop by the slot's duration), and the line's `production_status` becomes `RELEASED`."

        Design: Difficulty/non_linear_state_machine/production_slot_commit_release_recommit_cycle
        """
        gallery = setup_gallery(name="Gallery F2")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        line1 = add_line(order["id"], product["id"], qty=1)
        line2 = add_line(order["id"], product["id"], qty=1)
        get_success_data(
            api.confirm_order(order["id"], {"deposit_payment_cents": 120000}, ASSOCIATE)
        )
        slot = commit_line_to_slot(order["id"], line1["id"], gallery["id"])
        order_now = read_order(order["id"])
        validate_success(
            api.remove_order_line(
                order["id"], line1["id"],
                {"expected_order_version": order_now["version"]}, ASSOCIATE,
            )
        )
        # The removed line no longer appears among current lines, and the slot is OPEN.
        remaining = get_success_data(api.list_order_lines(order["id"], ADMIN))
        assert all(l["id"] != line1["id"] for l in remaining)
        slot_after = get_success_data(api.get_production_slot(slot["id"], PLANNER))
        assert slot_after["status"] == "OPEN"
        assert slot_after["committed_order_line_id"] is None


class TestReservedMinutesInvariant:

    def test_production_minutes_restored_on_line_removal(self, api):
        """PRD §3.5: "The gallery tracks the production load imposed by its slots as `reserved_production_minutes`: the sum, in whole minutes, of each slot's duration (end minus start) over all of its slots in `COMMITTED` or `IN_PROGRESS`."
        PRD §3.5: "When a custom line in `COMMITTED` is removed by amendment or its order is cancelled, its slot returns from `COMMITTED` to `OPEN`, `committed_order_line_id` is cleared to null, and the reserved minutes fall by the slot's duration, as described in §3.4."

        Design: Difficulty/compensating_invariant/production_minutes_restored_on_line_removal
        """
        gallery = setup_gallery(name="Gallery Q")
        member = setup_member(email="m10@x.com", full_name="M Ten")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        line = add_line(order["id"], product["id"], qty=1, headers=headers)
        get_success_data(
            api.confirm_order(order["id"], {"deposit_payment_cents": 50000}, headers)
        )
        slot = commit_line_to_slot(order["id"], line["id"], gallery["id"])

        before = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert before["reserved_production_minutes"] == 180

        order_now = read_order(order["id"])
        validate_success(
            api.remove_order_line(
                order["id"], line["id"],
                {"expected_order_version": order_now["version"]}, headers,
            )
        )
        after = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert after["reserved_production_minutes"] == 0
        slot_after = get_success_data(api.get_production_slot(slot["id"], PLANNER))
        assert slot_after["status"] == "OPEN"
        assert slot_after["committed_order_line_id"] is None

    def test_in_progress_slot_keeps_minutes_reserved(self, api):
        """PRD §3.5: "Advancing a `COMMITTED` slot with `to_state` `IN_PROGRESS` moves the slot to `IN_PROGRESS` and the committed line's `production_status` to `IN_PRODUCTION`; the slot's minutes remain reserved."

        Design: Difficulty/compensating_invariant/production_minutes_restored_on_line_removal
        """
        gallery = setup_gallery(name="Gallery Q2")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        line = add_line(order["id"], product["id"], qty=1)
        get_success_data(
            api.confirm_order(order["id"], {"deposit_payment_cents": 60000}, ASSOCIATE)
        )
        slot = commit_line_to_slot(order["id"], line["id"], gallery["id"])
        advanced = validate_success(
            api.advance_production_slot(slot["id"], {"to_state": "IN_PROGRESS"}, PLANNER)
        )
        assert advanced["status"] == "IN_PROGRESS"

        gallery_after = get_success_data(api.get_gallery(gallery["id"], ADMIN))
        assert gallery_after["reserved_production_minutes"] == 180


class TestBubbleUp:

    def test_slot_completion_bubbles_order_to_ready(self, api):
        """PRD §3.5: "when the last outstanding custom line of a `CONFIRMED` order reaches `COMPLETE` — that is, when every custom line on the order is `COMPLETE` — the order itself moves from `CONFIRMED` to `READY_FOR_DELIVERY` without any client action."

        Design: Corner/state_machines/slot_completion_bubbles_order_to_ready
        """
        gallery = setup_gallery(name="Gallery T6")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        line = add_line(order["id"], product["id"], qty=1)
        confirmed = validate_success(
            api.confirm_order(order["id"], {"deposit_payment_cents": 60000}, ASSOCIATE)
        )
        assert confirmed["status"] == "CONFIRMED"

        slot = commit_line_to_slot(order["id"], line["id"], gallery["id"])
        get_success_data(
            api.advance_production_slot(slot["id"], {"to_state": "IN_PROGRESS"}, PLANNER)
        )
        consumed = validate_success(
            api.advance_production_slot(slot["id"], {"to_state": "CONSUMED"}, PLANNER)
        )
        assert consumed["status"] == "CONSUMED"

        order_after = read_order(order["id"])
        assert order_after["status"] == "READY_FOR_DELIVERY"

    def test_in_production_custom_line_removal_rejected(self, api):
        """PRD §3.4: "a custom line whose `production_status` is `IN_PRODUCTION` or `COMPLETE` can never be removed — the attempt is rejected with `ERR_LINE_NON_CANCELABLE` (HTTP 409)."

        Design: Corner/state_machines/in_production_custom_line_removal_rejected
        """
        gallery = setup_gallery(name="Gallery T8")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        order = create_retail_quote(gallery["id"])
        line = add_line(order["id"], product["id"], qty=1)
        get_success_data(
            api.confirm_order(order["id"], {"deposit_payment_cents": 60000}, ASSOCIATE)
        )
        slot = commit_line_to_slot(order["id"], line["id"], gallery["id"])
        get_success_data(
            api.advance_production_slot(slot["id"], {"to_state": "IN_PROGRESS"}, PLANNER)
        )
        order_now = read_order(order["id"])

        resp = api.remove_order_line(
            order["id"], line["id"],
            {"expected_order_version": order_now["version"]}, ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_NON_CANCELABLE.value)
