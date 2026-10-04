"""The weekly color-tag markdown cycle: per-week idempotence, step
progression, same-week exemption, and the inclusive four-week rotation pull."""
from test_helpers import (
    TEST_USERS,
    WEEK0_ISO,
    WEEK1_ISO,
    WEEK2_ISO,
    WEEK3_ISO,
    WEEK4_ISO,
    ApiErrorId,
    api_client,
    create_org,
    create_priced_item,
    make_member_admin_headers,
    run_markdown_event,
    set_clock,
    setup_org_with_standard,
    validate_error,
    validate_success,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]


def _get_item(item_id) -> dict:
    return validate_success(api_client.get_donated_item(item_id, ASSOCIATE))


def _setup_priced_at_week0(org_name="Org MD"):
    set_clock(WEEK0_ISO)
    org, site, _std = setup_org_with_standard(org_name)
    item = create_priced_item(org["id"], site["id"], grade="A", weight_lbs=5.0)
    return org, item


class TestMarkdownWeekIdempotence:
    def test_markdown_event_same_week_rerun_rejected(self, api):
        """PRD 3.5: "One event may run per organization per week index: if the
        org's `last_markdown_week` already equals the current week index, the
        attempt is rejected with `ERR_MARKDOWN_WEEK_ALREADY_RUN`."
        PRD 3.5: "The event finishes by recording the week in the
        organization's `last_markdown_week`, advancing the org's `version`, and
        answering with a small report whose `applied_week`,
        `marked_down_count`, and `pulled_count` summarize what happened."

        Design: Corner/calculations/markdown_event_same_week_rerun_rejected
        """
        set_clock(WEEK0_ISO)
        org = create_org("Org MW")
        first = run_markdown_event(org["id"])
        assert first["applied_week"] == 0
        assert first["marked_down_count"] == 0
        assert first["pulled_count"] == 0
        resp = api_client.create_markdown_event(
            org["id"], make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_MARKDOWN_WEEK_ALREADY_RUN)

    def test_markdown_event_leaves_same_week_items_untouched(self, api):
        """PRD 3.5: "An item priced in the very week of the event is left
        untouched."
        PRD 2.4: "Week indices drive the color-tag rotation used for markdowns:
        the cycle runs `BLUE`, `GREEN`, `YELLOW`, `RED`, repeating, and an item
        priced during week index w takes the color whose position in that cycle
        equals the remainder of dividing w by four — remainder 0 yields `BLUE`,
        remainder 1 yields `GREEN`, remainder 2 yields `YELLOW`, and remainder
        3 yields `RED`."

        Design: Corner/calculations/markdown_event_leaves_same_week_items_untouched
        """
        org, item = _setup_priced_at_week0("Org SW")
        assert item["floor_week"] == 0
        assert item["color_tag"] == "BLUE"
        event = run_markdown_event(org["id"])
        assert event["applied_week"] == 0
        assert event["marked_down_count"] == 0
        assert event["pulled_count"] == 0
        after = _get_item(item["id"])
        assert after["status"] == "ON_FLOOR"
        assert after["markdown_step"] == 0
        assert after["current_selling_price_cents"] == 1000


class TestMarkdownSelfLoopAndRotation:
    def test_weekly_events_decay_price_through_steps(self, api):
        """PRD 3.5: "An item aged one, two, or three weeks takes a single
        markdown step: its `markdown_step` advances by one, capped at 3, and
        its `current_selling_price_cents` is recomputed from the locked base
        `price_cents` reduced by the percentage attached to the new step — no
        reduction at step 0, twenty-five percent at step 1, fifty percent at
        step 2, and seventy-five percent at step 3 — rounded half-up to whole
        cents."

        Design: Difficulty/non_linear_state_machine/donated_item_markdown_self_loop_and_rotation
        """
        org, item = _setup_priced_at_week0()
        assert item["markdown_step"] == 0
        assert item["current_selling_price_cents"] == 1000

        set_clock(WEEK1_ISO)
        run_markdown_event(org["id"])
        after1 = _get_item(item["id"])
        assert after1["status"] == "ON_FLOOR"
        assert after1["markdown_step"] == 1
        assert after1["current_selling_price_cents"] == 750

        set_clock(WEEK2_ISO)
        run_markdown_event(org["id"])
        after2 = _get_item(item["id"])
        assert after2["markdown_step"] == 2
        assert after2["current_selling_price_cents"] == 500

        set_clock(WEEK3_ISO)
        run_markdown_event(org["id"])
        after3 = _get_item(item["id"])
        assert after3["status"] == "ON_FLOOR"
        assert after3["markdown_step"] == 3
        assert after3["current_selling_price_cents"] == 250

    def test_fourth_week_event_pulls_item_and_freezes_price(self, api):
        """PRD 3.5: "An item aged four weeks or more — the boundary is
        inclusive, so exactly four counts — is rotation-pulled: it leaves the
        floor for `SALVAGED` status with its `markdown_step` and
        `current_selling_price_cents` frozen, becoming eligible for salvage
        lots."
        PRD 3.5: "Otherwise the event walks every `ON_FLOOR` item whose
        donation was received at one of the organization's sites, processing
        them in `floor_week` ascending order, ties broken by `created_at`
        ascending, and applies at most one step per item per event — even when
        the logical clock has skipped several weeks since the last event."

        Design: Difficulty/non_linear_state_machine/donated_item_markdown_self_loop_and_rotation
        """
        org, item = _setup_priced_at_week0()
        for week in (WEEK1_ISO, WEEK2_ISO, WEEK3_ISO):
            set_clock(week)
            run_markdown_event(org["id"])
        set_clock(WEEK4_ISO)
        event = run_markdown_event(org["id"])
        assert event["pulled_count"] == 1
        final = _get_item(item["id"])
        assert final["status"] == "SALVAGED"
        assert final["markdown_step"] == 3
        assert final["current_selling_price_cents"] == 250, (
            "step and price freeze on the rotation pull")


class TestRotationBoundaryAtExactlyFourWeeks:
    def _setup_two_items(self):
        """Item A priced week 0; item B priced week 1; week-1 event applied."""
        set_clock(WEEK0_ISO)
        org, site, _std = setup_org_with_standard("Org Rot")
        item_a = create_priced_item(org["id"], site["id"], grade="A",
                                    weight_lbs=5.0, donor_name="D1")
        set_clock(WEEK1_ISO)
        item_b = create_priced_item(org["id"], site["id"], grade="A",
                                    weight_lbs=5.0, donor_name="D2")
        run_markdown_event(org["id"])  # A ages to 1 -> step 1; B untouched
        return org, item_a, item_b

    def test_age_exactly_four_is_pulled(self, api):
        """PRD 3.5: "An item aged four weeks or more — the boundary is
        inclusive, so exactly four counts — is rotation-pulled: it leaves the
        floor for `SALVAGED` status with its `markdown_step` and
        `current_selling_price_cents` frozen, becoming eligible for salvage
        lots."
        PRD 3.5: "The event finishes by recording the week in the
        organization's `last_markdown_week`, advancing the org's `version`, and
        answering with a small report whose `applied_week`,
        `marked_down_count`, and `pulled_count` summarize what happened."

        Design: Difficulty/boundary_precision_check/rotation_pulls_at_exactly_four_weeks
        """
        org, item_a, _item_b = self._setup_two_items()
        set_clock(WEEK4_ISO)
        event = run_markdown_event(org["id"])
        assert event["applied_week"] == 4
        assert event["pulled_count"] == 1
        assert event["marked_down_count"] == 1
        assert _get_item(item_a["id"])["status"] == "SALVAGED"

    def test_age_exactly_three_survives_with_one_step(self, api):
        """PRD 3.5: "An item aged one, two, or three weeks takes a single
        markdown step: its `markdown_step` advances by one, capped at 3, and
        its `current_selling_price_cents` is recomputed from the locked base
        `price_cents` reduced by the percentage attached to the new step — no
        reduction at step 0, twenty-five percent at step 1, fifty percent at
        step 2, and seventy-five percent at step 3 — rounded half-up to whole
        cents."
        PRD 3.5: "Each item's age is the current week index minus its
        `floor_week`."

        Design: Difficulty/boundary_precision_check/rotation_pulls_at_exactly_four_weeks
        """
        org, item_a, item_b = self._setup_two_items()
        set_clock(WEEK4_ISO)
        run_markdown_event(org["id"])
        b = _get_item(item_b["id"])
        assert b["status"] == "ON_FLOOR", "age exactly 3 stays on the floor"
        assert b["markdown_step"] == 1
        assert b["current_selling_price_cents"] == 750
        assert _get_item(item_a["id"])["status"] == "SALVAGED"
