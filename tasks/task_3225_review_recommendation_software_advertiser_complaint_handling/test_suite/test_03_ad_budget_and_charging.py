"""Ad spend budget: pinned evaluation order, equality boundary, idempotency."""
from test_helpers import (
    OPS,
    ApiErrorId,
    create_campaign_payload,
    make_advertiser_headers,
    record_call,
    charge_impression,
    set_clock,
    setup_active_campaign,
    validate_error,
    validate_success,
)


class TestBudgetCapEvaluationOrder:
    def test_charges_accumulate_until_cap_would_be_exceeded(self, api):
        """PRD §3.5: "The account admits the charge only if the sum of
        `spent_today_cents` and the candidate cost does not strictly exceed
        `daily_budget_cents`; equality is allowed, so spend may land exactly on
        the cap. If the sum would exceed the cap, the charge is rejected with
        `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/ad_budget_circular_order_pinned
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=400, budget_cents=1000
        )
        r1 = charge_impression(account["id"], campaign["id"], "imp-001")
        validate_success(r1, expected_status=201)
        r2 = charge_impression(account["id"], campaign["id"], "imp-002")
        validate_success(r2, expected_status=201)
        # 800 + 400 = 1200 > 1000 -> rejected.
        r3 = charge_impression(account["id"], campaign["id"], "imp-003")
        validate_error(r3, ApiErrorId.ERR_BUDGET_EXCEEDED.value)

    def test_failed_charge_does_not_accumulate(self, api):
        """PRD §3.5: "Otherwise `spent_today_cents` is incremented by the
        candidate cost."
        PRD §3.5: "If the sum would exceed the cap, the charge is rejected with
        `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/ad_budget_circular_order_pinned
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=400, budget_cents=1000
        )
        charge_impression(account["id"], campaign["id"], "imp-001")
        charge_impression(account["id"], campaign["id"], "imp-002")
        charge_impression(account["id"], campaign["id"], "imp-003")  # rejected
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 800
        events = validate_success(
            api.list_account_impressions(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert len(events) == 2


class TestBudgetEqualityBoundary:
    def test_spend_may_land_exactly_on_the_cap(self, api):
        """PRD §3.5: "equality is allowed, so spend may land exactly on the
        cap."

        Design: Difficulty/boundary_precision_check/budget_equality_allowed_and_call_duration_30
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=500, budget_cents=500
        )
        event = validate_success(
            record_call(account["id"], campaign["id"], "2026-09-02T10:00:00Z", 30),
            expected_status=201,
        )
        assert event["qualified"] is True
        assert event["cost_cents"] == 500
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 500

    def test_one_cent_over_the_cap_is_rejected(self, api):
        """PRD §3.5: "If the sum would exceed the cap, the charge is rejected
        with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/budget_equality_allowed_and_call_duration_30
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=500, budget_cents=500
        )
        record_call(account["id"], campaign["id"], "2026-09-02T10:00:00Z", 30)
        # 500 + 500 > 500 -> rejected.
        r = record_call(account["id"], campaign["id"], "2026-09-02T11:00:00Z", 45,
                        caller_number="+15550001001")
        validate_error(r, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 500


class TestCallQualificationBoundary:
    def test_call_under_30_seconds_costs_nothing(self, api):
        """PRD §3.6: "A call whose `duration_seconds` is at least 30 seconds is
        marked `qualified` = true; shorter calls record `qualified` = false and
        `cost_cents` = 0 and never touch the budget."

        Design: Corner/calculations/attribution_unqualified_call_costs_nothing
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=700, budget_cents=10000
        )
        event = validate_success(
            record_call(account["id"], campaign["id"], "2026-09-05T12:00:00Z", 10),
            expected_status=201,
        )
        assert event["qualified"] is False
        assert event["cost_cents"] == 0
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 0
        # The unqualified call is excluded from report counts too.
        report = validate_success(
            api.create_attribution_report(
                account["id"],
                {
                    "campaign_id": campaign["id"],
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "variant": "STRICT",
                },
                make_advertiser_headers(owner["id"]),
            ),
            expected_status=201,
        )
        assert report["qualified_calls"] == 0
        assert report["spend_cents"] == 0

    def test_call_exactly_30_seconds_qualifies(self, api):
        """PRD §3.6: "A call whose `duration_seconds` is at least 30 seconds is
        marked `qualified` = true".
        PRD §3.6: "A qualified call's `cost_cents` equals the campaign's
        `bid_cents` and is charged to the budget per §3.5."

        Design: Difficulty/boundary_precision_check/budget_equality_allowed_and_call_duration_30
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=250, budget_cents=10000
        )
        event = validate_success(
            record_call(account["id"], campaign["id"], "2026-09-05T12:00:00Z", 30),
            expected_status=201,
        )
        assert event["qualified"] is True
        assert event["cost_cents"] == 250
        assert event["attribution_window_days"] == 30


class TestDailySpendRollover:
    def test_spent_today_resets_on_utc_date_rollover(self, api):
        """PRD §2.4: "an `AdAccount`'s `spent_today_cents` resets to zero when
        the UTC calendar day rolls over (the reset is applied lazily on the
        next charge or read against the account)."

        Design: Corner/calculations/budget_rollover_resets_daily_spend
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=400, budget_cents=500
        )
        charge_impression(account["id"], campaign["id"], "roll-1")  # spent 400
        blocked = charge_impression(account["id"], campaign["id"], "roll-2")
        validate_error(blocked, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
        # Midnight rollover: the next day the same charge fits again.
        set_clock("2026-09-02T00:00:01Z")
        event = validate_success(
            charge_impression(account["id"], campaign["id"], "roll-3"),
            expected_status=201,
        )
        assert event["cost_cents"] == 400
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 400


class TestAppendOnlyEventRecords:
    def test_event_records_carry_no_updated_at_or_version(self, api):
        """PRD §2.5: "The three event-like resources in the advertising stack —
        `AdImpressionEvent`, `CallTrackEvent`, and `AttributionReport` — are
        append-only records: they carry only `id` and `created_at`, and both
        `updated_at` and `version` are absent on them."

        Design: Corner/entities/event_entities_immutable_no_update
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=100, budget_cents=10000
        )
        validate_success(
            charge_impression(account["id"], campaign["id"], "ao-1"),
            expected_status=201,
        )
        events = validate_success(
            api.list_account_impressions(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert len(events) == 1
        impression = validate_success(
            api.get_impression_event(events[0]["id"], make_advertiser_headers(owner["id"]))
        )
        assert "updated_at" not in impression
        assert "version" not in impression
        page2, owner2, account2, campaign2 = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=100, budget_cents=10000
        )
        call = validate_success(
            record_call(account2["id"], campaign2["id"], "2026-09-05T12:00:00Z", 45),
            expected_status=201,
        )
        call_after = validate_success(
            api.get_call_track_event(call["id"], make_advertiser_headers(owner2["id"]))
        )
        assert "updated_at" not in call_after
        assert "version" not in call_after
        report = validate_success(
            api.create_attribution_report(
                account2["id"],
                {
                    "campaign_id": campaign2["id"],
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "variant": "STRICT",
                },
                make_advertiser_headers(owner2["id"]),
            ),
            expected_status=201,
        )
        report_after = validate_success(
            api.get_attribution_report(report["id"], make_advertiser_headers(owner2["id"]))
        )
        assert "updated_at" not in report_after
        assert "version" not in report_after


class TestImpressionIdempotency:
    def test_replay_same_key_returns_original_event_without_recharging(self, api):
        """PRD §3.6: "The `idempotency_key` is unique within the account:
        replaying the same key against the same `campaign_id` returns the
        original event without charging again".

        Design: Difficulty/compensating_invariant/budget_conserved_across_idempotent_replay
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=250, budget_cents=10000
        )
        first = validate_success(
            charge_impression(account["id"], campaign["id"], "key-aaa"),
            expected_status=201,
        )
        second = validate_success(
            charge_impression(account["id"], campaign["id"], "key-aaa"),
            expected_status=201,
        )
        assert second["id"] == first["id"]
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 250

    def test_replay_same_key_leaves_exactly_one_event(self, api):
        """PRD §3.6: "The `idempotency_key` is unique within the account:
        replaying the same key against the same `campaign_id` returns the
        original event without charging again".

        Design: Difficulty/compensating_invariant/budget_conserved_across_idempotent_replay
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=250, budget_cents=10000
        )
        charge_impression(account["id"], campaign["id"], "key-bbb")
        charge_impression(account["id"], campaign["id"], "key-bbb")
        events = validate_success(
            api.list_account_impressions(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert len(events) == 1

    def test_same_key_with_different_campaign_is_conflict(self, api):
        """PRD §3.6: "replaying the same key against a different `campaign_id`
        on the same account is rejected with `ERR_IDEMPOTENCY_CONFLICT`
        (HTTP 409)."

        Design: Corner/endpoints/idempotency_key_conflict_different_campaign
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign1 = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=100, budget_cents=100000
        )
        campaign2 = validate_success(
            api.create_campaign(
                account["id"],
                create_campaign_payload(kind="SPONSORED_PLACEMENT", bid_cents=100),
                make_advertiser_headers(owner["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api.activate_campaign(campaign2["id"], make_advertiser_headers(owner["id"]))
        )
        charge_impression(account["id"], campaign1["id"], "shared-key")
        conflict = charge_impression(account["id"], campaign2["id"], "shared-key")
        validate_error(conflict, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value)
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 100
