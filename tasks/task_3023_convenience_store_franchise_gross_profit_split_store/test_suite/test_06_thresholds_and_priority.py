"""Numeric thresholds, the renewal score, and which rule answers first."""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, ADMIN, get_success_data, set_clock, create_franchisee,
    create_store, create_agreement, create_open_settlement, add_revenue_lines,
    post_rebate, reconcile_settlement, setup_store_with_agreement,
    setup_settlement_with_lines, setup_settlement_with_rebate,
    refresh_store, make_franchisee_headers,
)


class TestGrossProfitTierThreshold:
    """The tier bonus boundary sits at 20,000,000 cents and is inclusive."""

    def test_a_split_base_exactly_on_the_threshold_takes_the_high_tier_bonus(self):
        """PRD §3.3: "The tier bonus is 0.02 when the settlement's gross profit
        reaches at least 20,000,000 cents, 0.01 when it reaches at least
        10,000,000 cents, and 0.00 otherwise; both thresholds are inclusive, so a
        store sitting exactly on a threshold takes the higher bonus."
        PRD §3.3: "`franchisee_split_cents` is the gross profit multiplied by
        `eligible_split_pct`; `franchisor_share_cents` is whatever remains of the
        gross profit after the operator's share is taken".

        Design: Difficulty/boundary_precision_check/settlement_gross_profit_exactly_20000000_earns_the_high_tier_bonus
        """
        context = setup_settlement_with_rebate(
            rebate_cents=12_500_000,
            lines=[("MERCHANDISE", 30_000_000, 22_000_000),
                   ("FUEL", 20_000_000, 18_500_000),
                   ("SERVICES", 5_000_000, 2_000_000)],
            split_pct=0.50, rebate_pass_pct=0.60,
            vendor_code="PSC-01", trailing_avg=5_000_000,
            franchisee_overrides={"entity_type": "CORPORATION"},
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        final = reconcile_settlement(settle_id)

        # The lines contribute 12,500,000 of gross profit and the rebate 7,500,000.
        assert final["gross_profit_cents"] == pytest.approx(20_000_000.00, abs=0.01)
        assert final["rebate_credit_cents"] == pytest.approx(7_500_000.00, abs=0.01)
        # Exactly on the threshold: the >= comparison awards the 0.02 bonus.
        assert final["eligible_split_pct"] == pytest.approx(0.52, abs=1e-9)
        assert final["franchisee_split_cents"] == pytest.approx(10_400_000.00, abs=0.01)
        assert final["franchisor_share_cents"] == pytest.approx(9_600_000.00, abs=0.01)

    def test_one_cent_below_the_threshold_earns_only_the_mid_tier_bonus(self):
        """PRD §3.3: "The tier bonus is 0.02 when the settlement's gross profit
        reaches at least 20,000,000 cents, 0.01 when it reaches at least
        10,000,000 cents, and 0.00 otherwise".
        PRD §3.3: "`franchisee_split_cents` is the gross profit multiplied by
        `eligible_split_pct`".

        Design: Difficulty/boundary_precision_check/settlement_gross_profit_exactly_20000000_earns_the_high_tier_bonus
        """
        # One cent less of line gross profit than the threshold instance.
        context = setup_settlement_with_rebate(
            rebate_cents=12_500_000,
            lines=[("MERCHANDISE", 30_000_000, 22_000_000),
                   ("FUEL", 20_000_000, 18_500_000),
                   ("SERVICES", 5_000_000, 2_000_001)],
            split_pct=0.50, rebate_pass_pct=0.60,
            vendor_code="PSC-02", trailing_avg=5_000_000,
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        final = reconcile_settlement(settle_id)

        assert final["gross_profit_cents"] == pytest.approx(19_999_999.00, abs=0.01)
        # Just below the high threshold, the mid bonus of 0.01 applies instead.
        assert final["eligible_split_pct"] == pytest.approx(0.51, abs=1e-9)
        assert final["franchisee_split_cents"] == pytest.approx(10_199_999.49, abs=0.01)
        # A one-cent input difference produces a 200,000.51 payout difference.
        assert (final["franchisee_split_cents"] - 10_400_000.00
                == pytest.approx(-200_000.51, abs=0.01))

    def test_the_agreement_tier_label_follows_the_same_money_as_the_bonus(self):
        """PRD §3.3: "Once the week's gross profit is known, the covering
        agreement's `performance_tier` is re-derived from it: `PREMIER` when the
        gross profit reaches at least 20,000,000 cents, `PREFERRED` when it
        reaches at least 10,000,000 cents, and `STANDARD` otherwise, with the
        thresholds inclusive in the same way as the bonus."

        Design: Difficulty/boundary_precision_check/settlement_gross_profit_exactly_20000000_earns_the_high_tier_bonus
        """
        context = setup_settlement_with_lines(
            lines=[("MERCHANDISE", 30_000_000, 15_000_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=5_000_000,
        )
        assert context["agreement"]["performance_tier"] == "STANDARD"

        reconcile_settlement(context["settlement"]["id"])
        final = reconcile_settlement(context["settlement"]["id"])
        assert final["gross_profit_cents"] == pytest.approx(15_000_000.00, abs=0.01)

        agreement = get_success_data(
            api_client.get_agreement(context["agreement"]["id"], ADMIN))
        assert agreement["performance_tier"] == "PREFERRED"


class TestRenewalEligibilityScore:
    """The net-worth band is keyed off the provisional score, never the final one."""

    def test_open_renewal_computes_the_weighted_score_and_the_mid_band(self):
        """PRD §3.9: "The first component is a sales-activity score: 40 when the
        store has three or more finalized settlements inside the term, 25 when it
        has one or two, and 10 when it has none. The second is a settlement
        score, which starts at 30 and loses 5 for each settlement for the store
        that stood in `DISPUTED` status during the term, floored at zero. The
        third is an audit score: 20 when no finalized shrink audit for the store
        inside the term shows a positive `shrink_cents`, and 10 when at least one
        does."
        PRD §3.9: "Only then is the net-worth band keyed off that provisional
        score: the required band is 15,000,000 cents when the provisional score
        is at least 75, 10,000,000 cents when it is at least 55, and 7,500,000
        cents otherwise. The net-worth component then consumes that band — 10
        when the operator's `audit_adjusted_net_worth_cents` clears the required
        band".

        Design: Corner/calculations/renewal_eligibility_band_is_keyed_off_the_provisional_score_not_the_final_score
        """
        set_clock("2026-08-01T00:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=30_000_000)
        store = create_store(franchisee["id"])
        agreement = create_agreement(
            franchisee["id"], store["id"],
            minimum_net_worth_cents=10_000_000,
            term_start="2025-01-01T00:00:00Z", term_end="2027-01-01T00:00:00Z",
            renewal_window_days=180)

        # No settlement and no audit exists for the term, so the components are
        # sales_activity 10, settlement 30 and audit 20 -- a provisional 60.
        opened = validate_success(api_client.open_renewal(agreement["id"], ADMIN), 200)
        assert opened["status"] == "RENEWAL_PENDING"
        assert opened["renewal_eligibility_score"] == 70

        # The provisional 60 keys the MID band of 10,000,000, and the net-worth
        # sub-score of 10 then lifts the final score to 70.
        assert opened["renewal_eligibility_score"] == 60 + 10

        # No settlement has driven a tier promotion yet.
        assert opened["performance_tier"] == "STANDARD"

    def test_reopening_an_already_open_renewal_is_a_state_error(self):
        """PRD §3.9: "A `FranchisorAdmin` opens the renewal window on an `ACTIVE`
        agreement, and three gates apply. The agreement must be `ACTIVE`."
        PRD §3.9: "A successful opening moves the agreement to `RENEWAL_PENDING`
        and computes the score."

        Design: Corner/calculations/renewal_eligibility_band_is_keyed_off_the_provisional_score_not_the_final_score
        """
        set_clock("2026-08-01T00:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=30_000_000)
        store = create_store(franchisee["id"])
        agreement = create_agreement(
            franchisee["id"], store["id"],
            term_start="2025-01-01T00:00:00Z", term_end="2027-01-01T00:00:00Z",
            renewal_window_days=180)
        validate_success(api_client.open_renewal(agreement["id"], ADMIN), 200)

        validate_error(api_client.open_renewal(agreement["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)

    def test_a_renewal_opened_before_its_window_opens_is_refused(self):
        """PRD §3.9: "The logical clock must have reached the point that is the
        agreement's `term_end` minus its `renewal_window_days`; opening a renewal
        earlier than that is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409)."

        Design: Corner/calculations/renewal_eligibility_band_is_keyed_off_the_provisional_score_not_the_final_score
        """
        set_clock("2026-01-01T00:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=30_000_000)
        store = create_store(franchisee["id"])
        agreement = create_agreement(
            franchisee["id"], store["id"],
            term_start="2025-01-01T00:00:00Z", term_end="2027-01-01T00:00:00Z",
            renewal_window_days=180)
        assert agreement["status"] == "ACTIVE"

        response = api_client.open_renewal(agreement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN, expected_status=409)
        assert get_success_data(
            api_client.get_agreement(agreement["id"], ADMIN))["status"] == "ACTIVE"


class TestPriorityOrderingBetweenRules:
    """Where several rules are broken at once, the earlier one answers."""

    def test_the_store_state_rule_answers_before_the_fiscal_shortfall_on_activation(self):
        """PRD §3.2: "Activation is a back-office step, and it is gated on two
        conditions evaluated in a fixed order. The covering store must be in
        status `ACTIVE`; when it is not, the activation is rejected with
        `ERR_STORE_NOT_ACTIVE` (HTTP 409). Only then is the operator's fiscal
        floor examined: the operator's `stated_net_worth_cents` must be at least
        the agreement's `minimum_net_worth_cents`, and a shortfall is rejected
        with `ERR_MIN_NET_WORTH_NOT_MET` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/stated_net_worth_failure_precedes_store_not_active_on_agreement_activate
        """
        set_clock("2026-09-01T12:00:00Z")
        # The operator states less than the agreement will demand...
        franchisee = create_franchisee(stated_net_worth_cents=5_000_000)
        store = create_store(franchisee["id"])
        # ...and the termination cascade has already driven the store out of ACTIVE.
        validate_success(api_client.terminate_franchisee(franchisee["id"], ADMIN), 200)
        assert refresh_store(store["id"])["status"] == "TERMINATED"

        agreement = create_agreement(
            franchisee["id"], store["id"], activate=False,
            minimum_net_worth_cents=10_000_000)

        # The request breaks both rules; the store-state check is the one PRD
        # orders first, so the fiscal shortfall never gets examined.
        response = api_client.activate_agreement(agreement["id"], ADMIN)
        error = validate_error(response, ApiErrorId.ERR_STORE_NOT_ACTIVE, expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_MIN_NET_WORTH_NOT_MET.value

        still = get_success_data(api_client.get_agreement(agreement["id"], ADMIN))
        assert still["status"] == "DRAFT"

    def test_the_reconcile_state_rule_answers_before_the_agreement_and_store_rules(self):
        """PRD §3.4: "Passing both gates moves the settlement to `RECONCILED`".
        PRD §2.12: "Where an operation depends on a parent's operational status,
        that status is evaluated first."
        PRD §3.3: "Opening requires that the store have a covering agreement in
        `ACTIVE` or `RENEWAL_PENDING` status — an operator with no live agreement
        cannot settle — and a breach of that requirement is reported as
        `ERR_NO_OPEN_AGREEMENT` (HTTP 409)."

        Design: Corner/validations/settlement_state_precondition_beats_the_no_open_agreement_rule_on_reconcile
        """
        set_clock("2026-09-16T00:00:00Z")
        context = setup_settlement_with_lines(
            lines=[("SERVICES", 2_000_000, 800_000)],
            clock="2026-09-16T00:00:00Z",
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        reconciled = reconcile_settlement(settle_id)
        assert reconciled["status"] == "RECONCILED"

        # Terminating the operator cascades the store and the agreement down,
        # but leaves the RECONCILED settlement where it stands.
        validate_success(api_client.terminate_franchisee(context["franchisee"]["id"], ADMIN), 200)
        assert get_success_data(
            api_client.get_agreement(context["agreement"]["id"], ADMIN))["status"] == "TERMINATED"
        assert refresh_store(context["store"]["id"])["status"] == "TERMINATED"
        assert get_success_data(
            api_client.get_settlement(settle_id, ADMIN))["status"] == "RECONCILED"

        response = api_client.reconcile_settlement(settle_id, ADMIN)
        error = validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert error["error_id"] not in (
            ApiErrorId.ERR_NO_OPEN_AGREEMENT.value,
            ApiErrorId.ERR_STORE_NOT_ACTIVE.value,
        )
        assert get_success_data(api_client.get_settlement(settle_id, ADMIN))["status"] == "RECONCILED"


class TestStaleVersionGuards:
    """Optimistic concurrency protects the three snapshotting writes."""

    def test_creating_a_settlement_against_a_stale_store_version_is_refused(self):
        """PRD §2.8: "Opening a weekly settlement carries `expected_store_version`,
        the store's version as the client last observed it. A mismatch means the
        store-side franchise configuration the settlement is about to snapshot
        has already moved, so the create is rejected with `ERR_STALE_VERSION` and
        HTTP 412."
        PRD §2.5: "Several operations in this document explicitly increment the
        `version` of a resource the caller did not directly address".

        Design: Corner/cross_cutting_complexity_layers/occ_settlement_create_against_a_stale_store_version_is_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T00:00:00Z")
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]

        # A settlement opened against this store advances its version.
        create_open_settlement(context["store"], context["franchisee"], trailing_avg=1_000_000)
        current = refresh_store(store_id)["version"]
        stale = current - 1

        payload = {
            "store_id": store_id, "franchisee_id": franchisee_id,
            "period_start": "2026-09-08T00:00:00Z",
            "period_end": "2026-09-15T00:00:00Z",
            "trailing_avg_gross_profit_cents": 1_000_000,
            "expected_store_version": stale,
        }
        validate_error(api_client.create_settlement(payload, ADMIN),
                       ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        listed, _meta = validate_paginated(
            api_client.list_settlements(ADMIN, {"store_id": store_id}))
        assert len(listed) == 1, "the stale create must not have been persisted"

        # Retrying with the current version succeeds.
        payload["expected_store_version"] = current
        validate_success(api_client.create_settlement(payload, ADMIN), 201)
        listed, _meta = validate_paginated(
            api_client.list_settlements(ADMIN, {"store_id": store_id}))
        assert len(listed) == 2

    def test_appending_a_revenue_line_against_a_stale_settlement_version_is_refused(self):
        """PRD §2.8: "Appending a revenue line carries
        `expected_settlement_version`, the settlement's version as the client
        last observed it. A mismatch means the settlement's accumulated totals
        already reflect another writer's line, so the append is rejected with
        `ERR_STALE_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_revenue_line_against_a_stale_settlement_version_is_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T00:00:00Z")
        settlement = create_open_settlement(
            context["store"], context["franchisee"], trailing_avg=1_000_000)
        first_version = settlement["version"]

        add_revenue_lines(settlement, [("MERCHANDISE", 2_000_000, 1_400_000)])
        current = get_success_data(
            api_client.get_settlement(settlement["id"], ADMIN))["version"]
        assert current > first_version

        stale_payload = {
            "category": "FUEL", "gross_sales_cents": 1_000_000,
            "cost_of_goods_cents": 900_000,
            "expected_settlement_version": first_version,
        }
        validate_error(api_client.add_revenue_line(settlement["id"], stale_payload, ADMIN),
                       ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        listed, _meta = validate_paginated(
            api_client.list_revenue_lines(ADMIN, {"settlement_id": settlement["id"]}))
        assert len(listed) == 1, "the stale append must not have been persisted"

        stale_payload["expected_settlement_version"] = current
        validate_success(api_client.add_revenue_line(settlement["id"], stale_payload, ADMIN), 201)
        listed, _meta = validate_paginated(
            api_client.list_revenue_lines(ADMIN, {"settlement_id": settlement["id"]}))
        assert len(listed) == 2

    def test_deciding_a_transfer_against_a_stale_store_version_is_refused(self):
        """PRD §3.9: "The decision is the second step, taken by a `FranchisorAdmin`
        through a call carrying a `decision` whose value is `APPROVE` or `DENY`,
        together with `expected_store_version` — the store's version as the client
        last observed it. If the store's version has advanced past that value the
        decision is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.9: "A denial is the simpler branch, and it is not a dead end.
        Denying a pending transfer returns the store's transfer dimension to
        `DENIED`".

        Design: Corner/cross_cutting_complexity_layers/occ_settlement_create_against_a_stale_store_version_is_rejected
        """
        from test_helpers import create_two_franchisees_and_store
        set_clock("2026-09-01T00:00:00Z")
        context = create_two_franchisees_and_store(minimum_net_worth_cents=10_000_000)
        store_id = context["store"]["id"]
        transferee_id = context["transferee"]["id"]

        requested = validate_success(api_client.request_store_transfer(
            store_id, {"transfer_target_franchisee_id": transferee_id,
                       "transfer_price_cents": 45_000_000}, ADMIN), 200)
        # The request response is the store row as of the bump its own call
        # produced, so the caller's last-observed version is the response's,
        # not the one carried on the row before the request.
        current = requested["version"]
        assert current == refresh_store(store_id)["version"]
        stale = current - 1

        stale_decision = {
            "decision": "DENY",
            "expected_store_version": stale,
        }
        validate_error(api_client.decide_store_transfer(store_id, stale_decision, ADMIN),
                       ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_success_data(
            api_client.get_store(store_id, ADMIN))["transfer_status"] == "PENDING"

        # Retrying with the current version lands the denial.
        stale_decision["expected_store_version"] = current
        denied = validate_success(
            api_client.decide_store_transfer(store_id, stale_decision, ADMIN), 200)
        assert denied["transfer_status"] == "DENIED"