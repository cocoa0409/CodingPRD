"""Cost-of-care claims and the monthly settlement close: adjudication,
finalize cascades, void, duplicate-settlement uniqueness, settlement OCC,
filtered listing, and the contribution ledger invariant."""
from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    api_client,
    create_center,
    create_cost_claim_payload,
    create_monthly_settlement_payload,
    create_open_center,
    create_open_settlement,
    create_patient,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

NET = TEST_USERS["network_operator_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]


def _finalized_settlement(center_id, period_month="2026-08", clock_after="2026-09-15T00:00:00Z"):
    """Open, provisionally close, and finalize a claim-free settlement.
    Returns the FINALIZED settlement."""
    settlement = create_open_settlement(center_id, period_month)
    set_clock(clock_after)
    center_now = get_success_data(api_client.get_center(center_id, NET))
    get_success_data(
        api_client.close_provisional_settlement(
            settlement["id"], {"expected_center_version": center_now["version"]}, FA
        )
    )
    return get_success_data(api_client.finalize_settlement(settlement["id"], FC))


class TestAdjudicationPriority:
    def test_adjudicate_amount_within_range_succeeds(self, api):
        """PRD §3.8: "adjudicates a `SUBMITTED` claim (`ERR_CLAIM_NOT_SUBMITTED` otherwise)
        by supplying `adjudicated_amount_cents`, which must be at least 0 and no more than
        the claimed `amount_cents` (`ERR_ADJUDICATED_AMOUNT_INVALID`)."
        PRD §3.8: "Adjudication moves the claim to `ADJUDICATED`, sets its
        `adjudicated_amount_cents`, and recomputes the settlement's
        `total_cost_of_care_cents`."

        Design: Difficulty/priority_pair_validation_conflict/adjudicate_wrong_amount_vs_finalized_settlement_conflict
        """
        center, team, room = create_open_center()
        patient = create_patient()
        claim = get_success_data(
            api.create_cost_claim(
                create_cost_claim_payload(
                    center["id"], patient["id"],
                    service_month="2026-09", category="PHARMACY", amount_cents=5000,
                ),
                ADJ,
            )
        )
        adjudicated = adjudicate_claim(claim["id"], 5000)
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["adjudicated_amount_cents"] == 5000


class TestFinalize:
    def test_claim_settled_automatically_when_settlement_finalizes(self, api):
        """PRD §3.8: "When a settlement finalizes, all of its `ADJUDICATED` claims move
        automatically to the terminal `SETTLED` state."

        Design: Corner/state_machines/claim_settled_automatically_when_settlement_finalizes
        """
        center, team, room = create_open_center()
        patient = create_patient()
        claim = get_success_data(
            api.create_cost_claim(
                create_cost_claim_payload(
                    center["id"], patient["id"],
                    service_month="2026-09", category="SPECIALIST", amount_cents=7000,
                ),
                ADJ,
            )
        )
        adjudicate_claim(claim["id"], 7000)

        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        get_success_data(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            )
        )
        validate_success(api.finalize_settlement(settlement["id"], FC), 200)

        claim_after = get_success_data(api.get_cost_claim(claim["id"], ADJ))
        assert claim_after["status"] == "SETTLED"

    def test_finalize_with_submitted_claims_rejected(self, api):
        """PRD §3.8: "Finalizing requires the settlement to be `CLOSED_PROVISIONAL`
        (`ERR_SETTLEMENT_NOT_PROVISIONAL`) and no `SUBMITTED` claims to remain for the
        center and period (`ERR_CLAIMS_STILL_PENDING`)."

        Design: Corner/state_machines/claim_settled_automatically_when_settlement_finalizes
        """
        center, team, room = create_open_center()
        patient = create_patient()
        get_success_data(
            api.create_cost_claim(
                create_cost_claim_payload(
                    center["id"], patient["id"],
                    service_month="2026-09", category="ED_VISIT", amount_cents=1000,
                ),
                ADJ,
            )
        )
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        get_success_data(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            )
        )
        resp = api.finalize_settlement(settlement["id"], FC)
        validate_error(resp, ApiErrorId.ERR_CLAIMS_STILL_PENDING.value, expected_status=409)


class TestSettlementStates:
    def test_close_provisional_from_finalized_returns_invalid_state(self, api):
        """PRD §3.8: "Provisional close is then performed by the `FinanceAnalyst` with
        `expected_center_version` per §2.7; the settlement must be `OPEN`
        (`ERR_SETTLEMENT_NOT_OPEN`) and the logical clock must sit in a later month than
        `period_month` (`ERR_PERIOD_STILL_OPEN` while still inside the period)."

        Design: Corner/state_machines/settlement_close_provisional_from_finalized_returns_invalid_state
        """
        center, team, room = create_open_center()
        settlement = _finalized_settlement(center["id"])
        center_now = get_success_data(api.get_center(center["id"], NET))
        resp = api.close_provisional_settlement(
            settlement["id"], {"expected_center_version": center_now["version"]}, FA
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_OPEN.value, expected_status=409)
        after = get_success_data(api.get_monthly_settlement(settlement["id"], FA))
        assert after["status"] == "FINALIZED"

    def test_close_provisional_while_period_still_open_rejected(self, api):
        """PRD §3.8: "Provisional close is then performed by the `FinanceAnalyst` with
        `expected_center_version` per §2.7; the settlement must be `OPEN`
        (`ERR_SETTLEMENT_NOT_OPEN`) and the logical clock must sit in a later month than
        `period_month` (`ERR_PERIOD_STILL_OPEN` while still inside the period)."

        Design: Corner/state_machines/settlement_close_provisional_from_finalized_returns_invalid_state
        """
        center, team, room = create_open_center()
        settlement = create_open_settlement(center["id"], "2026-09")
        center_now = get_success_data(api.get_center(center["id"], NET))
        # Clock is still 2026-09-01 (default): inside period_month 2026-09.
        resp = api.close_provisional_settlement(
            settlement["id"], {"expected_center_version": center_now["version"]}, FA
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_STILL_OPEN.value, expected_status=409)


class TestVoidInvariant:
    def test_settlement_void_leaves_contribution_unchanged(self, api):
        """PRD §3.8: "A `FinanceController` may instead void a settlement while it is `OPEN`
        (`ERR_SETTLEMENT_NOT_OPEN`) provided no `ADJUDICATED` claims reference the period
        (`ERR_CLAIMS_ALREADY_ADJUDICATED`), moving it to the terminal `VOIDED` state."
        PRD §2.8: "A settlement posting (provisional close or finalize) is the only
        mechanism that mutates this ledger field, and each posting increments the
        center's `version`."

        Design: Difficulty/compensating_invariant/settlement_void_leaves_contribution_unchanged
        """
        center, team, room = create_open_center()
        center_before = get_success_data(api.get_center(center["id"], NET))
        c0 = center_before["cumulative_contribution_cents"]

        settlement = create_open_settlement(center["id"], "2026-10")
        voided = validate_success(api.void_settlement(settlement["id"], FC), 200)
        assert voided["status"] == "VOIDED"

        center_after = get_success_data(api.get_center(center["id"], NET))
        assert center_after["cumulative_contribution_cents"] == c0

    def test_void_with_adjudicated_claims_rejected(self, api):
        """PRD §3.8: "A `FinanceController` may instead void a settlement while it is `OPEN`
        (`ERR_SETTLEMENT_NOT_OPEN`) provided no `ADJUDICATED` claims reference the period
        (`ERR_CLAIMS_ALREADY_ADJUDICATED`), moving it to the terminal `VOIDED` state."

        Design: Difficulty/compensating_invariant/settlement_void_leaves_contribution_unchanged
        """
        center, team, room = create_open_center()
        patient = create_patient()
        claim = get_success_data(
            api.create_cost_claim(
                create_cost_claim_payload(
                    center["id"], patient["id"],
                    service_month="2026-09", category="INPATIENT", amount_cents=2000,
                ),
                ADJ,
            )
        )
        adjudicate_claim(claim["id"], 2000)
        settlement = create_open_settlement(center["id"], "2026-09")
        resp = api.void_settlement(settlement["id"], FC)
        validate_error(
            resp, ApiErrorId.ERR_CLAIMS_ALREADY_ADJUDICATED.value, expected_status=409
        )


class TestDuplicateSettlement:
    def test_error_duplicate_settlement_triggerable(self, api):
        """PRD §2.8: "A period's settlement is unique per center and month: attempting to
        open a second settlement for the same center and `period_month` is rejected with
        `ERR_DUPLICATE_SETTLEMENT`."

        Design: Corner/errors/error_duplicate_settlement_triggerable
        """
        center, team, room = create_open_center()
        create_open_settlement(center["id"], "2026-09")
        resp = api.create_monthly_settlement(
            create_monthly_settlement_payload(center["id"], period_month="2026-09"), FA
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SETTLEMENT.value, expected_status=409)

    def test_same_period_different_centers_allowed(self, api):
        """PRD §2.8: "A period's settlement is unique per center and month: attempting to
        open a second settlement for the same center and `period_month` is rejected with
        `ERR_DUPLICATE_SETTLEMENT`."

        Design: Corner/errors/error_duplicate_settlement_triggerable
        """
        c1, _, _ = create_open_center()
        c2 = create_center(name="Other", neighborhood_code="CHI-OTHER-01")
        create_open_settlement(c1["id"], "2026-09")
        second = validate_success(
            api.create_monthly_settlement(
                create_monthly_settlement_payload(c2["id"], period_month="2026-09"), FA
            ),
            201,
        )
        assert second["center_id"] == c2["id"]


class TestSettlementOcc:
    def test_occ_settlement_close_stale_center_version(self, api):
        """PRD §2.7: "Provisionally closing a monthly settlement requires the request to
        carry `expected_center_version` matching the center's current `version`. If
        another settlement posting has advanced the center's `version` since the client
        last read it — mutating `cumulative_contribution_cents` — the close is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_settlement_close_stale_center_version
        """
        center, team, room = create_open_center()
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        resp = api.close_provisional_settlement(
            settlement["id"],
            {"expected_center_version": center_now["version"] - 1},
            FA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    def test_close_provisional_with_current_version_bumps_center_version(self, api):
        """PRD §2.7: "Provisionally closing a monthly settlement requires the request to
        carry `expected_center_version` matching the center's current `version`. If
        another settlement posting has advanced the center's `version` since the client
        last read it — mutating `cumulative_contribution_cents` — the close is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "A settlement posting (provisional close or finalize) is the only
        mechanism that mutates this ledger field, and each posting increments the
        center's `version`."

        Design: Corner/complexity_layers/occ_settlement_close_stale_center_version
        """
        center, team, room = create_open_center()
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        closed = validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        assert closed["status"] == "CLOSED_PROVISIONAL"
        center_after = get_success_data(api.get_center(center["id"], NET))
        assert center_after["version"] == center_now["version"] + 1


class TestSettlementDerivedFields:
    def test_settlement_finalize_reconciles_derived_center_fields(self, api):
        """PRD §3.8: "Finalize recomputes `accrued_revenue_cents` with the forward-looking
        (proration-reconciled) variant, applies the delta versus provisional to the
        center's `cumulative_contribution_cents`, settles all `ADJUDICATED` claims for the
        period, recomputes the center's `maturity_months`, `panel_fill_ratio`, and
        `profitability_tier`, moves the settlement to the terminal `FINALIZED` state, and
        increments the center's `version`."

        Design: Corner/complexity_layers/settlement_finalize_reconciles_derived_center_fields
        """
        center, team, room = create_open_center()
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_pre = get_success_data(api.get_center(center["id"], NET))
        get_success_data(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_pre["version"]}, FA
            )
        )
        center_prov = get_success_data(api.get_center(center["id"], NET))
        finalized = validate_success(api.finalize_settlement(settlement["id"], FC), 200)
        assert finalized["status"] == "FINALIZED"

        center_post = get_success_data(api.get_center(center["id"], NET))
        assert center_post["version"] == center_prov["version"] + 1
        # No panel and no claims: revenue 0, cost 0, contribution 0 both stages.
        assert center_post["cumulative_contribution_cents"] == 0

    def test_finalize_posts_provisional_then_delta(self, api):
        """PRD §3.8: "Provisional close computes `accrued_revenue_cents` with the
        chronological (actuals) variant of panel revenue accrual, computes
        `total_cost_of_care_cents` and `contribution_cents`, moves the settlement to
        `CLOSED_PROVISIONAL`, posts `contribution_cents` into the center's
        `cumulative_contribution_cents` as a provisional posting, and increments the
        center's `version`."
        PRD §3.8: "Finalize recomputes `accrued_revenue_cents` with the forward-looking
        (proration-reconciled) variant, applies the delta versus provisional to the
        center's `cumulative_contribution_cents`, settles all `ADJUDICATED` claims for the
        period, recomputes the center's `maturity_months`, `panel_fill_ratio`, and
        `profitability_tier`, moves the settlement to the terminal `FINALIZED` state, and
        increments the center's `version`."

        Design: Corner/complexity_layers/settlement_finalize_reconciles_derived_center_fields
        """
        center, team, room = create_open_center()
        patient = create_patient()
        claim = get_success_data(
            api.create_cost_claim(
                create_cost_claim_payload(
                    center["id"], patient["id"],
                    service_month="2026-09", category="ED_VISIT", amount_cents=4000,
                ),
                ADJ,
            )
        )
        adjudicate_claim(claim["id"], 4000)

        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        get_success_data(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            )
        )
        center_prov = get_success_data(api.get_center(center["id"], NET))
        # Provisional posting: revenue 0 minus the 4000-cent adjudicated claim.
        assert center_prov["cumulative_contribution_cents"] == -4000

        validate_success(api.finalize_settlement(settlement["id"], FC), 200)
        center_final = get_success_data(api.get_center(center["id"], NET))
        # Full-month vs day-proration delta is zero here (no ACTIVE panel), so
        # the finalize delta is zero and the ledger nets to the final contribution.
        assert center_final["cumulative_contribution_cents"] == -4000
        claim_after = get_success_data(api.get_cost_claim(claim["id"], ADJ))
        assert claim_after["status"] == "SETTLED"


class TestSettlementListing:
    def test_settlements_filtered_list_by_center(self, api):
        """PRD §3.8: "Settlements are listable with optional `center_id` and `status`
        filters and fetchable individually by finance roles."

        Design: Corner/endpoints/settlements_filtered_list_by_center
        """
        c1, _, _ = create_open_center()
        c2 = create_center(name="Second", neighborhood_code="CHI-SECOND-01")
        s1 = create_open_settlement(c1["id"], "2026-09")
        create_open_settlement(c2["id"], "2026-09")

        data, meta = validate_paginated(
            api.list_monthly_settlements(FA, params={"center_id": c1["id"]})
        )
        assert len(data) == 1
        assert all(row["center_id"] == c1["id"] for row in data)
        assert data[0]["id"] == s1["id"]
