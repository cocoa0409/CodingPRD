"""Channel events: share computation, posture derivation, overlap rules."""
from test_helpers import (
    CD,
    RM,
    ApiErrorId,
    api_client,
    post_channel_event,
    setup_onboarded_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


def _list_events(api, dealer_id):
    return validate_paginated(api.list_channel_events(dealer_id, CD))


class TestBigboxShare:
    def test_share_zero_with_no_events(self, api):
        """PRD section 3.7: "The `bigbox_share_pct` is one hundred times the
        numerator divided by the denominator, rounded half-up to two decimal
        places — and is 0 when the denominator is 0."

        Design: Corner/calculations/bigbox_share_rounding_and_empty_denominator
        """
        ctx = setup_onboarded_dealer()
        dealer = validate_success(api.get_dealer(ctx["dealer"]["id"], RM))
        assert dealer["bigbox_share_pct"] == 0

    def test_share_100_and_blocked_with_only_bigbox_sales(self, api):
        """PRD section 3.7: "A share greater than or equal to the threshold
        yields `BLOCKED`".
        PRD section 3.7: "the big-box numerator is the sum of `sales_cents`
        across the dealer's `CONFIRMED` events with `channel` `BIGBOX` whose
        `period_start` lies in the window; the denominator adds the same sum
        for `channel` `INDEPENDENT`."

        Design: Corner/calculations/bigbox_share_rounding_and_empty_denominator
        """
        ctx = setup_onboarded_dealer()
        post_channel_event(ctx["dealer"]["id"], channel="BIGBOX", sales_cents=1000)
        dealer = validate_success(api.get_dealer(ctx["dealer"]["id"], RM))
        assert dealer["bigbox_share_pct"] == 100.0
        assert dealer["channel_posture"] == "BLOCKED"


class TestOverlapSupersede:
    def test_partial_overlap_supersedes_confirmed_event_and_recomputes_share(self, api):
        """PRD section 3.7: "Posting a new event for the same dealer and
        channel whose period overlaps an existing `CONFIRMED` event
        supersedes the old one: the existing event moves to `SUPERSEDED` and
        the dealer's `bigbox_share_pct` and `channel_posture` are recomputed
        from the remaining confirmed events."

        Design: Difficulty/resource_temporal_overlap/channel_event_overlap_supersede_semantics
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        old_event = post_channel_event(
            dealer_id, channel="INDEPENDENT", sales_cents=10000,
        )
        post_channel_event(dealer_id, channel="BIGBOX", sales_cents=1000)
        # Partially overlapping replacement for the INDEPENDENT period.
        post_channel_event(
            dealer_id,
            period_start="2026-01-15T00:00:00Z",
            period_end="2026-02-15T00:00:00Z",
            channel="INDEPENDENT",
            sales_cents=9000,
        )
        events, _meta = _list_events(api, dealer_id)
        old = [e for e in events if e["id"] == old_event["id"]][0]
        assert old["status"] == "SUPERSEDED"
        dealer = validate_success(api.get_dealer(dealer_id, RM))
        assert dealer["bigbox_share_pct"] == 10.0

    def test_superseded_event_replacement_stays_confirmed(self, api):
        """PRD section 3.7: "Events begin `CONFIRMED`. Posting a new event
        for the same dealer and channel whose period overlaps an existing
        `CONFIRMED` event supersedes the old one: the existing event moves to
        `SUPERSEDED` and the dealer's `bigbox_share_pct` and
        `channel_posture` are recomputed from the remaining confirmed
        events."

        Design: Difficulty/resource_temporal_overlap/channel_event_overlap_supersede_semantics
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        old_event = post_channel_event(
            dealer_id, channel="INDEPENDENT", sales_cents=10000,
        )
        new_event = post_channel_event(
            dealer_id,
            period_start="2026-01-15T00:00:00Z",
            period_end="2026-02-15T00:00:00Z",
            channel="INDEPENDENT",
            sales_cents=9000,
        )
        assert new_event["status"] == "CONFIRMED"
        events, _meta = _list_events(api, dealer_id)
        old = [e for e in events if e["id"] == old_event["id"]][0]
        assert old["status"] == "SUPERSEDED"


class TestExactDuplicateAndPeriodShape:
    def test_exact_duplicate_period_rejected(self, api):
        """PRD section 3.7: "One refinement prevents double counting: an
        exact duplicate — same dealer, same channel, same `period_start`,
        same `period_end` as an existing `CONFIRMED` event — is not a
        supersession but a rejection with `ERR_CHANNEL_EVENT_OVERLAP`
        (HTTP 422)."

        Design: Corner/validations/exact_duplicate_channel_event_rejected
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        post_channel_event(dealer_id, channel="INDEPENDENT", sales_cents=10000)
        resp = api.create_channel_event(
            dealer_id,
            {
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-02-01T00:00:00Z",
                "channel": "INDEPENDENT",
                "sales_cents": 9999,
            },
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_CHANNEL_EVENT_OVERLAP)

    def test_zero_width_period_rejected(self, api):
        """PRD section 3.7: "A `period_end` at or before `period_start`, or a
        `period_start` in the future, is rejected with `ERR_INVALID_PERIOD`
        (HTTP 422)."

        Design: Corner/validations/invalid_period_end_before_start
        """
        ctx = setup_onboarded_dealer()
        resp = api.create_channel_event(
            ctx["dealer"]["id"],
            {
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-01T00:00:00Z",
                "channel": "INDEPENDENT",
                "sales_cents": 100,
            },
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)

    def test_future_period_start_rejected(self, api):
        """PRD section 3.7: "A `period_end` at or before `period_start`, or a
        `period_start` in the future, is rejected with `ERR_INVALID_PERIOD`
        (HTTP 422)."

        Design: Corner/validations/invalid_period_end_before_start
        """
        ctx = setup_onboarded_dealer()
        resp = api.create_channel_event(
            ctx["dealer"]["id"],
            {
                "period_start": "2027-01-01T00:00:00Z",
                "period_end": "2027-02-01T00:00:00Z",
                "channel": "INDEPENDENT",
                "sales_cents": 100,
            },
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)


class TestBlockedPosture:
    def test_bigbox_event_rejected_when_blocked_but_independent_posts(self, api):
        """PRD section 2.8: "The `OVERRIDE_REQUIRED` posture is advisory:
        big-box channel events remain postable while a dealer is in it —
        posting them is precisely what pushes the share over the block
        threshold — while the `BLOCKED` posture rejects new big-box events
        outright."
        PRD section 3.7: "A big-box event posted while the dealer's
        `channel_posture` is `BLOCKED` is rejected with
        `ERR_CHANNEL_EXCLUSIVITY_VIOLATION` (HTTP 422)."

        Design: Corner/validations/bigbox_event_blocked_when_posture_blocked
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        # First BIGBOX event posts while INDEPENDENT_ONLY; share becomes 100.
        post_channel_event(dealer_id, channel="BIGBOX", sales_cents=1000)
        dealer = validate_success(api.get_dealer(dealer_id, RM))
        assert dealer["channel_posture"] == "BLOCKED"
        resp = api.create_channel_event(
            dealer_id,
            {
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-04-01T00:00:00Z",
                "channel": "BIGBOX",
                "sales_cents": 500,
            },
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_CHANNEL_EXCLUSIVITY_VIOLATION)
        ok = post_channel_event(
            dealer_id,
            period_start="2026-03-01T00:00:00Z",
            period_end="2026-04-01T00:00:00Z",
            channel="INDEPENDENT",
            sales_cents=5000,
        )
        assert ok["status"] == "CONFIRMED"
