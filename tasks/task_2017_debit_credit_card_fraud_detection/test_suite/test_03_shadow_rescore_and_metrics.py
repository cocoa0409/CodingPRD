"""Shadow rescore divergence and per-ruleset trade-off metrics."""
from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    api_client,
    create_account,
    create_card,
    create_active_ruleset,
    create_rule_set_payload,
    post_txn,
    set_clock,
    get_success_data,
    make_analyst_headers,
    make_manager_headers,
    claim_alert,
    create_and_complete_contact,
    resolve_alert,
    create_manual_alert,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _create_and_activate(payload, creator="analyst-1", activator="mgr-1"):
    rs = get_success_data(
        api_client.create_rule_set(payload, make_analyst_headers(creator)),
        expected_status=201,
    )
    return get_success_data(
        api_client.activate_rule_set(rs["id"], make_manager_headers(activator))
    )


class TestShadowRescoreUnderSupersedingRuleset:
    def _setup_divergence(self, api):
        """RS1 active; one txn scores 75/REVIEW under RS1; RS2 (CNP 35, review 50,
        decline 80) supersedes RS1."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-DV1", cardholder_name="Dee Vee")
        card = create_card(acct["id"], "PT-DV1", product_type="CREDIT", network="VISA")
        rs1 = _create_and_activate(create_rule_set_payload())
        txn = post_txn(card["id"], 99999, "M-1", channel="CNP", origin_country="MX")
        rs2 = _create_and_activate(
            create_rule_set_payload(
                review_threshold=50,
                decline_threshold=80,
                channel_weights={"CHIP": 0, "CONTACTLESS": 5, "CNP": 35, "ATM": 30},
            )
        )
        return acct, card, rs1, rs2, txn

    def test_shadow_score_diverges_from_pinned_realtime(self, api):
        """PRD §3.3: "Every read of a transaction additionally computes a **shadow
        rescore**: the identical formula evaluated under whichever ruleset is
        `ACTIVE` at read time for the transaction's scope." and "the ruleset is
        pinned on the transaction as `ruleset_id` with the score persisted as
        `auth_score`."

        Design: Difficulty/dual_variant_calc/shadow_rescore_under_superseding_ruleset
        """
        _acct, _card, rs1, rs2, txn = self._setup_divergence(api)
        fetched = validate_success(api.get_auth_transaction(txn["id"], MANAGER))
        assert fetched["auth_score"] == 75
        assert fetched["decision"] == "REVIEW"
        assert fetched["ruleset_id"] == rs1["id"]
        assert fetched["shadow_score"] == 85, f"shadow under RS2: 10+20+35+20=85, got {fetched['shadow_score']}"
        assert fetched["shadow_decision"] == "DECLINE"
        assert fetched["shadow_ruleset_id"] == rs2["id"]

    def test_superseded_ruleset_is_retired(self, api):
        """PRD §3.2: "Activating a `DRAFT` ruleset moves it to `ACTIVE`, stamps
        `activated_by_user_id`, and supersedes any currently `ACTIVE` ruleset of
        the same `scope`, which becomes `RETIRED`".

        Design: Difficulty/dual_variant_calc/shadow_rescore_under_superseding_ruleset
        """
        _acct, _card, rs1, rs2, _txn = self._setup_divergence(api)
        old = validate_success(api.get_rule_set(rs1["id"], MANAGER))
        assert old["ruleset_status"] == "RETIRED"
        new = validate_success(api.get_rule_set(rs2["id"], MANAGER))
        assert new["ruleset_status"] == "ACTIVE"


class TestFpRateReviewVsDeclineBasis:
    def _setup_fp_population(self, api):
        """Two REVIEW txns (R1 legit, R2 fraud) + one DECLINE txn (D1 legit)."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-FP1", cardholder_name="Eff Pee")
        card = create_card(acct["id"], "PT-FP1", product_type="CREDIT", network="VISA")
        rs = _create_and_activate(create_rule_set_payload())
        r1 = post_txn(card["id"], 99999, "M-FP", channel="CNP", origin_country="MX")
        r2 = post_txn(card["id"], 99999, "M-FP", channel="CNP", origin_country="MX")
        d1 = post_txn(card["id"], 100000, "M-FP", channel="CNP", origin_country="RU")
        assert r1["decision"] == "REVIEW" and r2["decision"] == "REVIEW" and d1["decision"] == "DECLINE"

        def auto_alert_for(txn_id):
            data, _ = validate_paginated(
                api.list_fraud_alerts(MANAGER, params={"auth_transaction_id": txn_id})
            )
            assert len(data) == 1
            return data[0]

        a1 = auto_alert_for(r1["id"])
        a2 = auto_alert_for(r2["id"])
        # R1 -> LEGIT
        claim_alert(a1["id"])
        create_and_complete_contact(a1["id"], "CONFIRMED_LEGIT")
        resolve_alert(a1["id"], "LEGIT")
        # R2 -> FRAUD
        set_clock("2026-08-01T01:01:00Z")
        claim_alert(a2["id"])
        create_and_complete_contact(a2["id"], "CONFIRMED_FRAUD", channel="SMS")
        resolve_alert(a2["id"], "FRAUD")
        # D1 -> manual alert resolved LEGIT
        set_clock("2026-08-01T02:02:00Z")
        a3 = create_manual_alert(acct["id"], card["id"], auth_transaction_id=d1["id"])
        claim_alert(a3["id"])
        create_and_complete_contact(a3["id"], "CONFIRMED_LEGIT", channel="EMAIL")
        resolve_alert(a3["id"], "LEGIT")
        return acct, card, rs

    def test_two_bases_diverge_on_same_population(self, api):
        """PRD §3.11: "The review-basis rate, `fp_rate_review_basis_bp`, divides the
        count of legitimately-disposed `REVIEW` transactions by the count of
        `REVIEW` transactions with any disposition other than `UNDISPOSED`, scales
        to basis points by ten thousand, and rounds half up to an integer"; "The
        decline-basis rate, `fp_rate_decline_basis_bp`, applies the identical
        formula over `DECLINE` transactions."

        Design: Difficulty/dual_variant_calc/fp_rate_review_vs_decline_basis
        """
        _acct, _card, rs = self._setup_fp_population(api)
        metrics = validate_success(api.get_rule_set_metrics(rs["id"], MANAGER))
        assert metrics["review_count"] == 2
        assert metrics["declined_count"] == 1
        assert metrics["fp_rate_review_basis_bp"] == 5000, (
            f"1 legit of 2 disposed REVIEW -> 5000bp, got {metrics['fp_rate_review_basis_bp']}"
        )
        assert metrics["fp_rate_decline_basis_bp"] == 10000, (
            f"1 legit of 1 disposed DECLINE -> 10000bp, got {metrics['fp_rate_decline_basis_bp']}"
        )
        assert metrics["fp_rate_review_basis_bp"] != metrics["fp_rate_decline_basis_bp"]

    def test_population_counts_split_by_decision_and_disposition(self, api):
        """PRD §3.11: "The view reports `scored_count`, `approved_count`,
        `review_count`, and `declined_count` as the population split by `decision`;
        `confirmed_fraud_count` and `confirmed_legit_count` as the split by
        `final_disposition`".

        Design: Difficulty/dual_variant_calc/fp_rate_review_vs_decline_basis
        """
        _acct, _card, rs = self._setup_fp_population(api)
        metrics = validate_success(api.get_rule_set_metrics(rs["id"], MANAGER))
        assert metrics["scored_count"] == 3
        assert metrics["confirmed_fraud_count"] == 1
        assert metrics["confirmed_legit_count"] == 2


class TestMetricsMissedDeclinesCounter:
    def _setup_missed_decline(self, api):
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CA4", cardholder_name="Calc Four")
        card = create_card(acct["id"], "PT-CA4", product_type="CREDIT", network="VISA")
        rs1 = _create_and_activate(create_rule_set_payload())
        txn = post_txn(card["id"], 99999, "M-CA4", channel="CNP", origin_country="MX")
        rs2 = _create_and_activate(
            create_rule_set_payload(
                review_threshold=50,
                decline_threshold=80,
                channel_weights={"CHIP": 0, "CONTACTLESS": 5, "CNP": 35, "ATM": 30},
            )
        )
        return acct, card, rs1, rs2, txn

    def test_missed_declines_counted_on_retired_ruleset(self, api):
        """PRD §3.11: "`missed_declines_under_current` counts transactions of the
        population whose realtime `decision` was not `DECLINE` but whose
        `shadow_decision` under the currently active ruleset is `DECLINE`".

        Design: Corner/calculations/metrics_missed_declines_counter
        """
        _acct, _card, rs1, rs2, _txn = self._setup_missed_decline(api)
        metrics = validate_success(api.get_rule_set_metrics(rs1["id"], MANAGER))
        assert metrics["scored_count"] == 1
        assert metrics["review_count"] == 1
        assert metrics["missed_declines_under_current"] == 1, (
            f"shadow 85 >= 80 under RS2 must count as missed decline, got {metrics['missed_declines_under_current']}"
        )

    def test_population_pinned_by_ruleset_id(self, api):
        """PRD §3.11: "computed over the population of transactions pinned to that
        ruleset via `ruleset_id`".

        Design: Corner/calculations/metrics_missed_declines_counter
        """
        _acct, _card, rs1, rs2, _txn = self._setup_missed_decline(api)
        metrics2 = validate_success(api.get_rule_set_metrics(rs2["id"], MANAGER))
        assert metrics2["scored_count"] == 0, (
            f"RS2 never scored an intake; population must be empty, got {metrics2['scored_count']}"
        )


def test_metrics_endpoint_returns_declared_fields(api):
    """PRD §3.11: "The view reports `scored_count`, `approved_count`,
    `review_count`, and `declined_count` as the population split by `decision` ...
    and `gross_confirmed_loss_cents` as the sum of `final_amount_cents` over
    losses"; "when no `REVIEW` transaction has been disposed, the rate is 0."

    Design: Corner/endpoints/metrics_endpoint_returns_declared_fields
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-EP3", cardholder_name="Ep Three")
    card = create_card(acct["id"], "PT-EP3")
    rs = _create_and_activate(create_rule_set_payload())
    txn = post_txn(card["id"], 1000, "M-EP3", channel="CNP", origin_country="US")
    assert txn["decision"] == "APPROVE"

    metrics = validate_success(api.get_rule_set_metrics(rs["id"], MANAGER))
    for field in (
        "scored_count", "approved_count", "review_count", "declined_count",
        "confirmed_fraud_count", "confirmed_legit_count",
        "fp_rate_review_basis_bp", "fp_rate_decline_basis_bp",
        "missed_declines_under_current", "gross_confirmed_loss_cents",
    ):
        assert field in metrics, f"metrics missing field {field}"
    assert metrics["scored_count"] == 1
    assert metrics["approved_count"] == 1
    assert metrics["review_count"] == 0
    assert metrics["declined_count"] == 0
    assert metrics["fp_rate_review_basis_bp"] == 0
    assert metrics["fp_rate_decline_basis_bp"] == 0
    assert metrics["missed_declines_under_current"] == 0
