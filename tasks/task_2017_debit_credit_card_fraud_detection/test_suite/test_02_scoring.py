"""Real-time authorization scoring: multi-factor formula, boundaries, blocked
cards, travel suppression, missing-ruleset rejection."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    STD_RULESET,
    create_account,
    create_card,
    create_active_ruleset,
    create_rule_set_payload,
    post_txn,
    set_clock,
    get_success_data,
    make_analyst_headers,
    make_manager_headers,
    create_travel_notice_payload,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _std_account_card_ruleset(account_number, pan_token, product_type="CREDIT", network="VISA"):
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account(account_number)
    card = create_card(acct["id"], pan_token, product_type=product_type, network=network)
    rs = create_active_ruleset()
    return acct, card, rs


class TestScoringMultifactorNonlinear:
    """Five hand-computed scores pin the scoring formula exactly."""

    def test_score_components_amount_tiers_and_channel(self, api):
        """PRD §3.3: "Otherwise the score is the sum of five integer components: the
        `base_score`; the `points` of the amount tier with the greatest
        `min_amount_cents` that is less than or equal to `amount_cents`; the
        channel's points from `channel_weights`".

        Design: Difficulty/combinatorial_formula/scoring_multifactor_nonlinear
        """
        _acct, card, _rs = _std_account_card_ruleset("ACCT-CF1", "PT-CF1")
        t1 = post_txn(card["id"], 99999, "M-CF", channel="CNP", origin_country="MX")
        assert t1["auth_score"] == 75, f"10+20+25+20 expected 75, got {t1['auth_score']}"
        assert t1["decision"] == "REVIEW"
        t5 = post_txn(card["id"], 1000, "M-CF", channel="CNP", origin_country="US")
        assert t5["auth_score"] == 40, f"10+5+25+0 expected 40, got {t5['auth_score']}"
        assert t5["decision"] == "APPROVE"

    def test_amount_tier_step_and_high_risk_multiplier(self, api):
        """PRD §3.3: "the cross-border component, which is zero when `origin_country`
        equals the account's `home_country`, otherwise `cross_border_weight`, and
        that weight multiplied by `high_risk_multiplier` when the origin appears in
        `high_risk_countries`".

        Design: Difficulty/combinatorial_formula/scoring_multifactor_nonlinear
        """
        _acct, card, _rs = _std_account_card_ruleset("ACCT-CF1", "PT-CF1")
        t2 = post_txn(card["id"], 100000, "M-CF", channel="CNP", origin_country="MX")
        assert t2["auth_score"] == 100, f"10+45+25+20 expected 100, got {t2['auth_score']}"
        assert t2["decision"] == "DECLINE"
        t3 = post_txn(card["id"], 100000, "M-CF", channel="CNP", origin_country="RU")
        assert t3["auth_score"] == 120, f"10+45+25+40 expected 120, got {t3['auth_score']}"
        assert t3["decision"] == "DECLINE"
        t4 = post_txn(card["id"], 1000, "M-CF", channel="CNP", origin_country="MX")
        assert t4["auth_score"] == 60, f"10+5+25+20 expected 60, got {t4['auth_score']}"
        assert t4["decision"] == "REVIEW"


class TestDeclineThresholdEquality:
    def test_score_equal_to_decline_threshold_declines(self, api):
        """PRD §3.3: "The decision is `DECLINE` when the score is at least
        `decline_threshold` (an inclusive boundary)".

        Design: Difficulty/boundary_precision_check/decline_threshold_equality
        """
        _acct, card, _rs = _std_account_card_ruleset("ACCT-BP1", "PT-BP1")
        t_eq = post_txn(card["id"], 100000, "M-BP1", channel="CNP", origin_country="MX")
        assert t_eq["auth_score"] == 100
        assert t_eq["decision"] == "DECLINE", (
            f"score == decline_threshold must DECLINE (inclusive), got {t_eq['decision']}"
        )
        # DECLINE creates no alert
        alerts, meta = validate_paginated(
            api.list_fraud_alerts(MANAGER, params={"auth_transaction_id": t_eq["id"]})
        )
        assert meta["total_count"] == 0, "DECLINE must not create an alert"

    def test_score_below_decline_threshold_reviews_with_exactly_one_alert(self, api):
        """PRD §3.3: "`REVIEW` when it is at least `review_threshold` but below the
        decline threshold"; "A `REVIEW` decision creates exactly one `FraudAlert`
        with `source` equal to `SCORING_REVIEW`."

        Design: Difficulty/boundary_precision_check/decline_threshold_equality
        """
        _acct, card, _rs = _std_account_card_ruleset("ACCT-BP1", "PT-BP1")
        t_below = post_txn(card["id"], 99999, "M-BP1", channel="CNP", origin_country="MX")
        assert t_below["auth_score"] == 75
        assert t_below["decision"] == "REVIEW"
        alerts, meta = validate_paginated(
            api.list_fraud_alerts(MANAGER, params={"auth_transaction_id": t_below["id"]})
        )
        assert meta["total_count"] == 1
        assert alerts[0]["source"] == "SCORING_REVIEW"


def test_blocked_card_auth_declined_without_score(api):
    """PRD §3.3: "When the presented card is not in `card_status` `ACTIVE`, scoring
    is bypassed entirely: the decision is `DECLINE` with `decision_reason` equal to
    `CARD_BLOCKED`, `auth_score` and `ruleset_id` are null, no alert is created —
    but the transaction is still recorded and the intake still returns success
    (HTTP 201)."

    Design: Corner/calculations/blocked_card_auth_declined_without_score
    """
    _acct, card, _rs = _std_account_card_ruleset("ACCT-CA1", "PT-CA1")
    get_success_data(
        api.block_card(card["id"], {"block_type": "SOFT", "reason": "ANALYST_REVIEW"}, ANALYST)
    )
    resp = api.create_auth_transaction(
        {
            "card_id": card["id"],
            "amount_cents": 1000,
            "merchant_id": "M-CA1",
            "merchant_category_code": "5411",
            "channel": "CNP",
            "origin_country": "US",
        },
        TEST_USERS["gateway_headers"],
    )
    txn = validate_success(resp, expected_status=201)
    assert txn["decision"] == "DECLINE"
    assert txn["decision_reason"] == "CARD_BLOCKED"
    assert txn["auth_score"] is None
    assert txn["ruleset_id"] is None
    alerts, meta = validate_paginated(
        api.list_fraud_alerts(MANAGER, params={"auth_transaction_id": txn["id"]})
    )
    assert meta["total_count"] == 0, "blocked-card decline must create no alert"


def test_review_decision_creates_single_alert(api):
    """PRD §3.4: "second, `band_points` is frozen — 25 for a `MANUAL` alert, or for
    a `SCORING_REVIEW` alert the transaction's `auth_score` minus the ruleset's
    `review_threshold`, clamped below at 0 and capped above at 49; third,
    `priority` is the tier points (0 for `LOW`, 100 for `MEDIUM`, 200 for `HIGH`)
    plus the frozen `band_points`".

    Design: Corner/calculations/review_decision_creates_single_alert
    """
    _acct, card, _rs = _std_account_card_ruleset("ACCT-CA2", "PT-CA2", product_type="DEBIT", network="MASTERCARD")
    txn = post_txn(card["id"], 99999, "M-CA2", channel="CNP", origin_country="MX")
    assert txn["decision"] == "REVIEW"
    alerts, meta = validate_paginated(
        api.list_fraud_alerts(MANAGER, params={"auth_transaction_id": txn["id"]})
    )
    assert meta["total_count"] == 1
    alert = alerts[0]
    assert alert["source"] == "SCORING_REVIEW"
    assert alert["alert_status"] == "OPEN"
    assert alert["band_points"] == 15, f"75-60 expected 15, got {alert['band_points']}"
    assert alert["priority"] == 15, f"LOW tier 0 + band 15 expected 15, got {alert['priority']}"


class TestTravelNoticeSuppressionWindowBoundaries:
    def _setup_with_notice(self, api):
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CA3")
        card = create_card(acct["id"], "PT-CA3")
        create_active_ruleset()
        notice = get_success_data(
            api.create_travel_notice(
                {
                    "card_id": card["id"],
                    "region_country": "MX",
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-20",
                },
                ANALYST,
            ),
            expected_status=201,
        )
        return acct, card, notice

    def test_score_before_window_charges_cross_border(self, api):
        """PRD §3.3: "Travel suppression overrides the cross-border component to zero
        when an `ACTIVE` travel notice exists for the card whose `region_country`
        equals `origin_country` and whose half-open date range contains the date of
        `scored_at` (start inclusive, end exclusive)."

        Design: Corner/calculations/travel_notice_suppression_window_boundaries
        """
        _acct, card, _notice = self._setup_with_notice(api)
        set_clock("2026-08-09T12:00:00Z")
        t1 = post_txn(card["id"], 1000, "M-CA3", channel="CNP", origin_country="MX")
        assert t1["auth_score"] == 60, f"before window: 10+5+25+20 expected 60, got {t1['auth_score']}"
        assert t1["decision"] == "REVIEW"

    def test_score_inside_window_suppressed_and_end_date_exclusive(self, api):
        """PRD §3.3: "whose half-open date range contains the date of `scored_at`
        (start inclusive, end exclusive)"."

        Design: Corner/calculations/travel_notice_suppression_window_boundaries
        """
        _acct, card, _notice = self._setup_with_notice(api)
        set_clock("2026-08-12T12:00:00Z")
        t2 = post_txn(card["id"], 1000, "M-CA3", channel="CNP", origin_country="MX")
        assert t2["auth_score"] == 40, f"inside window: cross-border suppressed, 10+5+25+0=40, got {t2['auth_score']}"
        assert t2["decision"] == "APPROVE"
        set_clock("2026-08-20T00:00:00Z")
        t3 = post_txn(card["id"], 1000, "M-CA3", channel="CNP", origin_country="MX")
        assert t3["auth_score"] == 60, f"at end_date (exclusive): cross +20 restored, expected 60, got {t3['auth_score']}"
        assert t3["decision"] == "REVIEW"


def test_scoring_without_active_ruleset_rejected(api):
    """PRD §3.3: "the `ACTIVE` ruleset whose `scope` matches the card's product type
    (`DEBIT_CARD` for a debit card, `CREDIT_CARD` for a credit card), falling back
    to the `ACTIVE` `GLOBAL` ruleset when no product-specific one exists; if
    neither exists, intake is rejected with `ERR_NO_ACTIVE_RULESET`."

    Design: Corner/errors/scoring_without_active_ruleset_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-ER1")
    card = create_card(acct["id"], "PT-ER1")
    # A DRAFT (never activated) ruleset exists but provides no ACTIVE coverage.
    get_success_data(
        api.create_rule_set(
            create_rule_set_payload(high_risk_countries=[]),
            make_analyst_headers("analyst-1"),
        ),
        expected_status=201,
    )
    resp = api.create_auth_transaction(
        {
            "card_id": card["id"],
            "amount_cents": 1000,
            "merchant_id": "M-ER1",
            "merchant_category_code": "5411",
            "channel": "CNP",
            "origin_country": "US",
        },
        TEST_USERS["gateway_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RULESET, expected_status=409)
    txns, meta = validate_paginated(
        api.list_auth_transactions(MANAGER, params={"card_id": card["id"]})
    )
    assert meta["total_count"] == 0, "rejected intake must not persist a transaction"
