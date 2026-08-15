"""Reissue campaigns: nested total-level rounding (difficulty) and the
empty-selection boundary (difficulty)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_card,
    create_open_account,
    create_program_with_bin_and_publish,
    create_reissue_campaign,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OA = TEST_USERS["operations_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]


class TestReissueFeeNestedRounding:
    def _setup_three_card_program(self, code: str, bin_prefix: str):
        """Program with three OPEN accounts, each holding one ACTIVE card
        expiring 10/2026 (matches an expiry_before=2026-11-01 filter)."""
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish(code, bin_prefix=bin_prefix)
        cards = []
        for i in range(1, 4):
            acct = create_open_account(prog["id"], f"{code}-A{i}", daily_spend_cap_cents=100000)
            card = create_active_card(
                acct["id"], pin=f"111{i}", expiry_month=10, expiry_year=2026,
            )
            cards.append(card)
        return prog, cards

    def test_reissue_fee_total_level_rounding_books_960(self, api):
        """PRD §3.8: "for an `EXPIRY_SWEEP`, a four-percent volume discount is
        taken on the total — the gross fee is the integer sum of the per-card
        `blanket_unit_fee_cents`, the discount is that gross multiplied by four
        and divided by one hundred, rounded down, and the booked fee is the
        gross minus the discount. The order matters and is pinned at the total
        level: with a 333-cent blanket fee and three cards, discounting each
        card first would book 957 cents, while the prescribed total-level
        computation books a gross of 999, a discount of 39, and a net of 960 —
        the platform books 960."

        Design: Difficulty/combinatorial_formula/reissue_fee_nested_rounding_total_level
        """
        prog, _cards = self._setup_three_card_program("P-VISA-4", "433333")
        campaign = create_reissue_campaign(
            prog["id"],
            campaign_kind="EXPIRY_SWEEP",
            scheduled_for="2026-08-05T00:00:00Z",
            selection_filter={"expiry_before": "2026-11-01"},
            blanket_unit_fee_cents=333,
        )
        get_success_data(api.schedule_campaign(campaign["id"], OA))
        set_clock("2026-08-05T00:00:00Z")
        campaign_after = get_success_data(api.get_reissue_campaign(campaign["id"], OA))
        assert campaign_after["status"] == "COMPLETED", (
            f"Campaign must run to COMPLETED once the clock reaches "
            f"scheduled_for; got {campaign_after['status']}"
        )
        resp = api.get_program_economics(prog["id"], "2026-08", FC, variant="FINAL")
        econ = validate_success(resp)
        assert econ["reissue_fee_cents"] == 960, (
            f"Total-level rounding: gross=999, floor(999*4/100)=39, net=960; got "
            f"{econ['reissue_fee_cents']}"
        )

    def test_reissue_mints_one_successor_per_selected_card(self, api):
        """PRD §3.8: "When the clock reaches `scheduled_for`, the campaign
        starts `EXECUTING` and converts each selected card whose lifecycle is
        still `ISSUED`, `ACTIVE`, or `SUSPENDED`: a successor card is minted
        with the same `form_factor`, an expiry 36 months out, lifecycle
        `ISSUED`, `pin_status` `UNSET`, the source card's id in
        `replaced_from_card_id`, and the campaign's id in `reissue_campaign_id`;
        the source card flips to `REPLACED` with `replaced_by_card_id` pointing
        at the successor."

        Design: Difficulty/combinatorial_formula/reissue_fee_nested_rounding_total_level
        """
        prog, cards = self._setup_three_card_program("P-VISA-4B", "433334")
        campaign = create_reissue_campaign(
            prog["id"],
            campaign_kind="EXPIRY_SWEEP",
            scheduled_for="2026-08-05T00:00:00Z",
            selection_filter={"expiry_before": "2026-11-01"},
            blanket_unit_fee_cents=333,
        )
        get_success_data(api.schedule_campaign(campaign["id"], OA))
        set_clock("2026-08-05T00:00:00Z")
        campaign_after = get_success_data(api.get_reissue_campaign(campaign["id"], OA))
        assert campaign_after["status"] == "COMPLETED"
        # Exactly 3 successor cards minted.
        successors, meta = validate_paginated(api.list_campaign_cards(campaign["id"], OA))
        assert meta["total_count"] == 3, (
            f"Three selected cards must mint exactly three successors; got "
            f"{meta['total_count']}"
        )
        # Each source card is REPLACED and points at its successor.
        for source in cards:
            src = get_success_data(api.get_card(source["id"], TEST_USERS["program_manager_headers"]))
            assert src["lifecycle_status"] == "REPLACED", (
                f"Source card must flip to REPLACED; got {src['lifecycle_status']}"
            )
            assert src.get("replaced_by_card_id"), (
                "Source card must record replaced_by_card_id"
            )


class TestCampaignEmptySelection:
    def test_campaign_empty_selection_zero_count(self, api):
        """PRD §3.8: "a selection that comes up empty rejects the scheduling
        with `ERR_CAMPAIGN_EMPTY_SELECTION`".

        Design: Difficulty/boundary_precision_check/campaign_empty_selection_zero_count
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-12", bin_prefix="422200")
        campaign = create_reissue_campaign(
            prog["id"],
            campaign_kind="EXPIRY_SWEEP",
            scheduled_for="2026-08-05T00:00:00Z",
            selection_filter={"expiry_before": "2027-01-01"},
            blanket_unit_fee_cents=100,
        )
        resp = api.schedule_campaign(campaign["id"], OA)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_EMPTY_SELECTION.value)

    def test_campaign_with_one_matching_card_schedules(self, api):
        """PRD §3.8: "Scheduling a campaign (`DRAFT` → `SCHEDULED`) recomputes
        the selection" and "The recomputed size lands in
        `estimated_card_count`, and a selection that comes up empty rejects the
        scheduling with `ERR_CAMPAIGN_EMPTY_SELECTION`".

        A one-card pool is the boundary just above empty: scheduling succeeds
        and estimated_card_count is 1.

        Design: Difficulty/boundary_precision_check/campaign_empty_selection_zero_count
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-12B", bin_prefix="422201")
        acct = create_open_account(prog["id"], "A-12B", daily_spend_cap_cents=100000)
        create_active_card(acct["id"], pin="9999", expiry_month=10, expiry_year=2026)
        campaign = create_reissue_campaign(
            prog["id"],
            campaign_kind="EXPIRY_SWEEP",
            scheduled_for="2026-08-05T00:00:00Z",
            selection_filter={"expiry_before": "2027-01-01"},
            blanket_unit_fee_cents=100,
        )
        resp = api.schedule_campaign(campaign["id"], OA)
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
        assert data["estimated_card_count"] == 1, (
            f"One matching card must yield estimated_card_count == 1, got "
            f"{data['estimated_card_count']}"
        )
