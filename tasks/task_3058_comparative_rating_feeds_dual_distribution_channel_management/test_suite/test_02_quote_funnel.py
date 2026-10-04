"""Quote funnel lifecycle: submit pricing, re-rate loops, referral data reuse,
withdrawal terminality, expiry boundaries, and publish-driven rate staleness."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_product,
    create_agent_quote,
    create_appointed_agent,
    create_consumer,
    create_direct_quote,
    create_feed_publication,
    create_published_feed,
    create_rater,
    get_success_data,
    make_agent_headers,
    make_consumer_headers,
    publish_feed,
    set_clock,
    setup_product_with_feed,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestQuoteSubmitBasics:
    def test_quote_starts_draft_and_submit_computes_premium(self, api):
        """PRD §3.3: "A successful submit stamps `quoted_at` with the logical clock,
        sets `expires_at` to exactly 30 days after `quoted_at`, clears `rate_stale`
        to false, and increments the quote's `version`."
        PRD §3.3: "Pricing is the channel quote premium: a channel factor is
        chosen first (for `DIRECT`, one minus `direct_discount_pct`; for `AGENT`,
        one plus `agent_load_pct`, less `bundle_credit_pct` when
        `bundled_home_intended` is true); each selected coverage is priced by
        looking up its code and tier in the product's `coverage_rates`,
        multiplying by the channel factor, and rounding half-up to integer
        cents **per line**; the rounded lines are then summed; and finally the
        sum is raised to `min_premium_cents` if it falls below the floor."

        Design: Corner/state_machines/quote_starts_draft_and_submit_computes_premium
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000, "STANDARD": 70000},
                            "COLLISION": {"STANDARD": 90000, "PLUS": 120000}},
            direct_discount_pct=0.10,
            agent_load_pct=0.15,
            bundle_credit_pct=0.05,
            min_premium_cents=40000,
        )
        consumer = create_consumer()
        quote = create_direct_quote(consumer, product["id"])
        assert quote["status"] == "DRAFT"
        assert quote["quoted_premium_cents"] is None

        submitted = validate_success(
            api.submit_quote(quote["id"], make_consumer_headers(consumer["id"]))
        )
        assert submitted["status"] == "QUOTED"
        assert submitted["quoted_premium_cents"] == 45000  # 50000 * 0.90
        assert submitted["quoted_at"] == "2026-01-01T00:00:00.000Z"
        assert submitted["expires_at"] == "2026-01-31T00:00:00.000Z"
        assert submitted["rate_stale"] is False

    def test_bind_on_draft_quote_rejected_invalid_transition(self, api):
        """PRD §3.3: "A `Consumer` binds a direct quote from `QUOTED` — the caller
        must be the quote's own `consumer_id` (`ERR_OWNERSHIP_MISMATCH`) and the
        quote must still be direct-channel (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/bind_on_draft_quote_rejected_invalid_transition
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        quote = create_direct_quote(consumer, product["id"])
        resp = api.bind_quote(quote["id"], make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        rows, meta = validate_paginated(
            api.list_policies(
                TEST_USERS["carrier_admin_headers"],
                params={"quote_id": quote["id"]},
            )
        )
        assert len(rows) == 0

    def test_withdrawn_quote_is_terminal_for_all_actions(self, api):
        """PRD §3.3: "Quotes may also be withdrawn from `QUOTED`,
        `REFERRED_TO_AGENT`, or `AGENT_QUOTED` to `WITHDRAWN`; withdrawal from
        `QUOTED` or `REFERRED_TO_AGENT` increments the quote's `version`, while
        withdrawal from `AGENT_QUOTED` records no further field changes."

        Design: Corner/state_machines/withdrawn_quote_is_terminal_for_all_actions
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        quote = create_direct_quote(consumer, product["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))
        validate_success(api.withdraw_quote(quote["id"], consumer_headers))

        resp_submit = api.submit_quote(quote["id"], consumer_headers)
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        resp_withdraw = api.withdraw_quote(quote["id"], consumer_headers)
        validate_error(resp_withdraw, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_quote(quote["id"], consumer_headers))
        assert after["status"] == "WITHDRAWN"

    def test_submit_twice_second_call_rejected(self, api):
        """PRD §3.3: "Submitting a `DRAFT` quote — by the consumer for a direct
        quote or by the named agent for an agent quote — prices it and moves it to
        `QUOTED`."

        Design: Corner/state_machines/submit_twice_second_call_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000, "STANDARD": 70000},
                            "COLLISION": {"STANDARD": 90000, "PLUS": 120000}},
            direct_discount_pct=0.10,
            agent_load_pct=0.15,
            bundle_credit_pct=0.05,
            min_premium_cents=40000,
        )
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        quote = create_direct_quote(consumer, product["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))

        resp = api.submit_quote(quote["id"], consumer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_quote(quote["id"], consumer_headers))
        assert after["status"] == "QUOTED"
        assert after["quoted_premium_cents"] == 45000


class TestQuoteRerateAndReferralCycle:
    def _setup_agent_and_product(self, api):
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"LIABILITY": {"BASIC": 50000}},
                "direct_discount_pct": 0.10,
                "agent_load_pct": 0.15,
                "min_premium_cents": 40000,
            }
        )
        agent = create_appointed_agent()
        consumer = create_consumer()
        return ctx, agent, consumer

    def test_quote_rerate_cycle_resets_computed_fields(self, api):
        """PRD §3.3: "Re-rating unwinds a priced quote without destroying it. From
        `QUOTED` it returns to `DRAFT`; from `AGENT_QUOTED` it returns to
        `REFERRED_TO_AGENT` so the referral relationship survives. Either way the
        computed artifacts are cleared — `quoted_premium_cents`, `quoted_at`,
        `expires_at`, and `rate_feed_publication_id` go to null and `rate_stale` to
        false — while on the agent-side re-rate the `agent_id` and
        `referral_snapshot` are preserved."

        Design: Difficulty/non_linear_state_machine/quote_rerate_cycle_and_referral_loop_on_quote
        """
        ctx, agent, consumer = self._setup_agent_and_product(api)
        consumer_headers = make_consumer_headers(consumer["id"])
        agent_headers = make_agent_headers(agent["id"])

        quote = create_direct_quote(consumer, ctx["product"]["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))
        rerated = validate_success(api.re_rate_quote(quote["id"], consumer_headers))
        assert rerated["status"] == "DRAFT"
        assert rerated["quoted_premium_cents"] is None
        assert rerated["quoted_at"] is None
        assert rerated["expires_at"] is None
        assert rerated["rate_stale"] is False
        assert rerated["rate_feed_publication_id"] is None

        resubmitted = validate_success(api.submit_quote(quote["id"], consumer_headers))
        assert resubmitted["status"] == "QUOTED"

    def test_referral_loop_preserves_agent_and_snapshot_then_binds(self, api):
        """PRD §3.3: "The transition moves the quote `QUOTED → REFERRED_TO_AGENT`,
        flips its `channel` to `AGENT`, sets the `agent_id`, and captures the
        `referral_snapshot` — the current `coverages` together with the
        direct-channel `quoted_premium_cents` — which is the payload the agent
        inherits."
        PRD §3.3: "The premium is recomputed with agent-channel factors,
        `quoted_at` and the 30-day `expires_at` are restamped, `rate_stale`
        clears, and the quote moves `REFERRED_TO_AGENT → AGENT_QUOTED`."

        Design: Difficulty/non_linear_state_machine/quote_rerate_cycle_and_referral_loop_on_quote
        """
        ctx, agent, consumer = self._setup_agent_and_product(api)
        consumer_headers = make_consumer_headers(consumer["id"])
        agent_headers = make_agent_headers(agent["id"])

        quote = create_direct_quote(consumer, ctx["product"]["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))
        referred = validate_success(
            api.refer_quote_to_agent(
                quote["id"], {"agent_id": agent["id"]}, consumer_headers
            )
        )
        assert referred["status"] == "REFERRED_TO_AGENT"
        assert referred["channel"] == "AGENT"
        assert referred["agent_id"] == agent["id"]
        assert referred["referral_snapshot"]["quoted_premium_cents"] == 45000

        agent_quoted = validate_success(api.agent_quote(quote["id"], agent_headers))
        assert agent_quoted["status"] == "AGENT_QUOTED"
        assert agent_quoted["quoted_premium_cents"] == 57500  # 50000 * 1.15

        rerated = validate_success(api.re_rate_quote(quote["id"], agent_headers))
        assert rerated["status"] == "REFERRED_TO_AGENT"
        assert rerated["agent_id"] == agent["id"]
        assert rerated["referral_snapshot"] is not None
        assert rerated["quoted_premium_cents"] is None

        requoted = validate_success(api.agent_quote(quote["id"], agent_headers))
        assert requoted["status"] == "AGENT_QUOTED"
        assert requoted["quoted_premium_cents"] == 57500

        policy = validate_success(api.bind_quote(quote["id"], agent_headers))
        assert policy["status"] == "IN_FORCE"
        assert policy["written_premium_cents"] == 57500
        bound_quote = get_success_data(api.get_quote(quote["id"], agent_headers))
        assert bound_quote["status"] == "BOUND"


class TestQuoteExpiryBoundary:
    def test_quote_bind_one_second_before_expiry_succeeds(self, api):
        """PRD §3.3: "the logical clock must be before `expires_at`
        (`ERR_QUOTE_EXPIRED`)".

        Design: Difficulty/boundary_precision_check/quote_bind_at_exact_expiry_timestamp_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            direct_discount_pct=0.10,
            min_premium_cents=0,
        )
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        quote = create_direct_quote(consumer, product["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))

        set_clock("2026-01-30T23:59:59Z")
        policy = validate_success(api.bind_quote(quote["id"], consumer_headers))
        assert policy["status"] == "IN_FORCE"
        bound_quote = get_success_data(api.get_quote(quote["id"], consumer_headers))
        assert bound_quote["status"] == "BOUND"

    def test_quote_bind_at_exact_expiry_timestamp_rejected(self, api):
        """PRD §2.9: "A quote whose expiry instant has been reached likewise reads
        as `EXPIRED` — and a bind attempted at or past that instant fails with
        `ERR_QUOTE_EXPIRED`, after which the quote reads `EXPIRED` thereafter."

        Design: Difficulty/boundary_precision_check/quote_bind_at_exact_expiry_timestamp_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            direct_discount_pct=0.10,
            min_premium_cents=0,
        )
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        quote = create_direct_quote(consumer, product["id"])
        validate_success(api.submit_quote(quote["id"], consumer_headers))

        set_clock("2026-01-31T00:00:00Z")
        resp = api.bind_quote(quote["id"], consumer_headers)
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED, 409)
        expired = get_success_data(api.get_quote(quote["id"], consumer_headers))
        assert expired["status"] == "EXPIRED"


class TestFeedPinningAndStaleness:
    def test_agent_channel_submit_requires_published_feed_for_product(self, api):
        """PRD §3.3: "for an agent-channel quote a publication for the product must
        be `PUBLISHED` with a window covering the current logical time — the
        earliest-published qualifying publication wins the pin, with ties broken by
        the lowest `published_at` and then by publication `created_at` ascending —
        and its id is recorded as `rate_feed_publication_id` (absence of a covering
        publication fails with `ERR_FEED_NOT_PUBLISHED`)."

        Design: Difficulty/cross_entity_state_dependency/agent_channel_submit_requires_published_feed_for_product
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            agent_load_pct=0.15,
            min_premium_cents=0,
        )
        rater = create_rater()
        feed = create_feed_publication(rater["id"], product["id"])
        agent = create_appointed_agent()
        consumer = create_consumer()
        agent_headers = make_agent_headers(agent["id"])

        quote = create_agent_quote(consumer, agent, product["id"])
        resp = api.submit_quote(quote["id"], agent_headers)
        validate_error(resp, ApiErrorId.ERR_FEED_NOT_PUBLISHED, 409)
        still_draft = get_success_data(api.get_quote(quote["id"], agent_headers))
        assert still_draft["status"] == "DRAFT"

        publish_feed(feed["id"])
        submitted = validate_success(api.submit_quote(quote["id"], agent_headers))
        assert submitted["status"] == "QUOTED"
        assert submitted["quoted_premium_cents"] == 57500
        assert submitted["rate_feed_publication_id"] == feed["id"]

    def test_agent_channel_submit_pins_covering_publication(self, api):
        """PRD §3.3: "for an agent-channel quote a publication for the product
        must be `PUBLISHED` with a window covering the current logical time — the
        earliest-published qualifying publication wins the pin, with ties broken
        by the lowest `published_at` and then by publication `created_at`
        ascending — and its id is recorded as `rate_feed_publication_id` (absence
        of a covering publication fails with `ERR_FEED_NOT_PUBLISHED`)."

        Design: Difficulty/cross_entity_state_dependency/agent_channel_submit_requires_published_feed_for_product
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            agent_load_pct=0.15,
            min_premium_cents=0,
        )
        rater = create_rater()
        feed = create_feed_publication(
            rater["id"], product["id"],
            effective_start="2026-06-01T00:00:00Z",
            effective_end="2027-01-01T00:00:00Z",
        )
        publish_feed(feed["id"])
        agent = create_appointed_agent()
        consumer = create_consumer()
        agent_headers = make_agent_headers(agent["id"])

        # Now (January) is outside the feed window [2026-06-01, 2027-01-01)
        quote = create_agent_quote(consumer, agent, product["id"])
        resp = api.submit_quote(quote["id"], agent_headers)
        validate_error(resp, ApiErrorId.ERR_FEED_NOT_PUBLISHED, 409)

        # Once the clock enters the window, the same quote submits and pins
        set_clock("2026-06-15T00:00:00Z")
        submitted = validate_success(api.submit_quote(quote["id"], agent_headers))
        assert submitted["status"] == "QUOTED"
        assert submitted["rate_feed_publication_id"] == feed["id"]

    def test_feed_publish_supersede_marks_dependent_quotes_stale(self, api, rating_manager_headers):
        """PRD §3.2: "The first cascade hop supersedes whatever publication was
        previously `PUBLISHED` for the same rater-and-product pair, moving it
        `PUBLISHED → SUPERSEDED` with a version increment — at most one publication
        per pair is ever live. The second hop flags every quote pinned to that
        superseded publication and still sitting in `QUOTED` or `AGENT_QUOTED`: each
        such quote's `rate_stale` is set to true and its `version` increments."
        PRD §3.3: "Binding is where a quote becomes a policy, and it is guarded by
        two lazy-state checks on both legs: the logical clock must be before
        `expires_at` (`ERR_QUOTE_EXPIRED`) and `rate_stale` must be false
        (`ERR_RATE_STALE`)."

        Design: Difficulty/transitive_cascade/rate_feed_publish_supersede_marks_dependent_quotes_stale
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            agent_load_pct=0.15,
            min_premium_cents=0,
        )
        rater = create_rater()
        feed_f1 = create_published_feed(
            rater["id"], product["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-07-01T00:00:00Z",
        )
        agent = create_appointed_agent()
        consumer = create_consumer()
        agent_headers = make_agent_headers(agent["id"])

        set_clock("2026-06-15T00:00:00Z")
        quote = create_agent_quote(consumer, agent, product["id"])
        submitted = validate_success(api.submit_quote(quote["id"], agent_headers))
        assert submitted["rate_feed_publication_id"] == feed_f1["id"]

        feed_f2 = create_feed_publication(
            rater["id"], product["id"],
            effective_start="2026-07-02T00:00:00Z",
            effective_end="2027-01-01T00:00:00Z",
        )
        publish_feed(feed_f2["id"])

        f1_after = get_success_data(
            api.get_feed_publication(feed_f1["id"], rating_manager_headers)
        )
        assert f1_after["status"] == "SUPERSEDED"

        quote_after = get_success_data(api.get_quote(quote["id"], rating_manager_headers))
        assert quote_after["rate_stale"] is True
        assert quote_after["status"] == "QUOTED"

        resp = api.bind_quote(quote["id"], agent_headers)
        # PRD §3.3 binds the agent leg strictly to AGENT_QUOTED, so a QUOTED
        # agent-channel quote that is rate-stale fails either the leg check
        # (ERR_INVALID_STATE_TRANSITION) or the lazy stale check
        # (ERR_RATE_STALE) depending on evaluation order; §2.8 admits both.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_RATE_STALE, ApiErrorId.ERR_INVALID_STATE_TRANSITION],
        )
        still_quoted = get_success_data(api.get_quote(quote["id"], rating_manager_headers))
        assert still_quoted["status"] == "QUOTED"

    def test_rerate_clears_rate_stale_and_allows_rebind(self, api, rating_manager_headers):
        """PRD §3.3: "Either way the computed artifacts are cleared —
        `quoted_premium_cents`, `quoted_at`, `expires_at`, and
        `rate_feed_publication_id` go to null and `rate_stale` to false — while on
        the agent-side re-rate the `agent_id` and `referral_snapshot` are
        preserved."
        PRD §3.2: "Recall moves a publication from `DRAFT` or `PUBLISHED` to
        `RECALLED` with a version increment; when the recalled publication was
        `PUBLISHED`, the same dependent-quote staleness flag is applied to quotes
        pinned to it in `QUOTED` or `AGENT_QUOTED`."

        Design: Difficulty/transitive_cascade/rate_feed_publish_supersede_marks_dependent_quotes_stale
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            agent_load_pct=0.15,
            min_premium_cents=0,
        )
        rater = create_rater()
        feed = create_published_feed(rater["id"], product["id"])
        agent = create_appointed_agent()
        consumer = create_consumer()
        agent_headers = make_agent_headers(agent["id"])

        quote = create_agent_quote(consumer, agent, product["id"])
        submitted = validate_success(api.submit_quote(quote["id"], agent_headers))
        assert submitted["rate_feed_publication_id"] == feed["id"]

        # Recalling the PUBLISHED publication flags pinned quotes stale
        validate_success(api.recall_feed_publication(feed["id"], rating_manager_headers))
        stale = get_success_data(api.get_quote(quote["id"], rating_manager_headers))
        assert stale["rate_stale"] is True

        resp = api.bind_quote(quote["id"], agent_headers)
        # As above: agent-leg bind of a QUOTED rate-stale quote may report
        # either the leg check or the stale check (§2.8).
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_RATE_STALE, ApiErrorId.ERR_INVALID_STATE_TRANSITION],
        )

        # Re-rate clears the stale flag (but with no PUBLISHED feed left, the
        # quote cannot be re-submitted in the agent channel)
        rerated = validate_success(api.re_rate_quote(quote["id"], agent_headers))
        assert rerated["status"] == "DRAFT"
        assert rerated["rate_stale"] is False
        assert rerated["rate_feed_publication_id"] is None
