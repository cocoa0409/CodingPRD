"""Bid lifecycle: sealing, recalling, resetting, opening and the award cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    LOGICAL_CLOCK_START,
    advance_clock,
    create_project,
    setup_priced_item,
    setup_sealed_project,
    validate_error,
    validate_success,
)


class TestBidDimension:
    def test_project_starts_in_draft_bid_status(self, api, estimator_headers):
        """PRD §3.1: "Opening the record sets the project's bid-window-open
        instant to the current logical clock, stamps the sealed-bid dimension to
        `DRAFT`, and stamps the delivery dimension to `PRE_BID`."

        Design: Corner/state_machines/project_starts_in_draft_bid_status
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5705")
        assert project["bid_status"] == "DRAFT"

    def test_sealing_a_sealed_project_returns_invalid_state(self, api, estimator_headers):
        """PRD §3.4: "The project's bid dimension must still be `DRAFT`."
        PRD §2.5: "The fifth band is state: if the target resource is not in the
        state that the requested transition requires, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/sealing_a_sealed_project_returns_invalid_state
        """
        ctx = setup_sealed_project(project_code="CALTRANS-04-1J5706")
        assert ctx["project"]["total_bid_cents"] == 3_000_000

        response = api.seal_bid(ctx["project"]["id"], estimator_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert response.status_code == 409

        after = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert after["bid_status"] == "SEALED"
        assert after["total_bid_cents"] == 3_000_000

    def test_bid_dimension_cycles_back_to_draft_and_can_be_sealed_again(
        self, api, estimator_headers, contracting_officer_headers
    ):
        """PRD §3.4: "Resetting closes the loop. A `ContractingOfficer` returns a
        `RECALLED` bid to `DRAFT`, and the same act returns the delivery dimension
        to `PRE_BID`, so that the project is back in the state it held before any
        bid was prepared."
        PRD §3.4: "This four-step cycle — `DRAFT` to `SEALED`, `SEALED` to
        `RECALLED`, `RECALLED` to `DRAFT` — is the only permitted route back from
        a sealed bid to preparation"

        Design: Difficulty/non_linear_state_machine/project_bid_dimension_cycles_through_recall
        """
        ctx = setup_sealed_project(project_code="CALTRANS-04-1J5608")
        project = ctx["project"]
        item = ctx["bid_item"]

        validate_success(
            api.recall_bid(
                project["id"], {"reason_code": "OWNER_ADDENDUM"}, contracting_officer_headers
            )
        )
        reset = validate_success(api.reset_bid(project["id"], contracting_officer_headers))
        assert reset["bid_status"] == "DRAFT"
        assert reset["project_status"] == "PRE_BID"

        # The same takeoff is re-priced and re-sealed after the cycle.
        repriced = validate_success(
            api.price_bid_item(
                project["id"],
                item["id"],
                {
                    "bid_unit_price_cents": 3500,
                    "crew_day_labor_cents": 1_200_000,
                    "crew_day_equipment_cents": 800_000,
                    "daily_productivity_units": 1000,
                },
                estimator_headers,
            )
        )
        assert repriced["item_status"] == "PRICED"
        validate_success(api.submit_bid_item(project["id"], item["id"], estimator_headers))
        resealed = validate_success(api.seal_bid(project["id"], estimator_headers))

        assert resealed["bid_status"] == "SEALED"
        assert resealed["project_status"] == "PRE_BID"
        assert resealed["total_bid_cents"] == 3_500_000
        final_item = validate_success(api.get_bid_item(item["id"], estimator_headers))
        assert final_item["item_status"] == "SUBMITTED"

    def test_recall_unwinds_the_bid_composition(
        self, api, estimator_headers, contracting_officer_headers
    ):
        """PRD §3.4: "Recalling unwinds the bid's composition: every pay item on
        the project in `SUBMITTED` status returns to `DRAFT`, every quote on the
        project in `CARRIED` status returns to `RECEIVED` with its `version_round`
        incremented by one — reopening the negotiation round exactly as an
        explicit withdrawal would — and the project's `total_bid_cents` is reset
        to 0."

        Design: Difficulty/non_linear_state_machine/project_bid_dimension_cycles_through_recall
        """
        ctx = setup_sealed_project(project_code="CALTRANS-04-1J5608")
        recalled = validate_success(
            api.recall_bid(
                ctx["project"]["id"],
                {"reason_code": "ERROR_IN_BID"},
                contracting_officer_headers,
            )
        )
        assert recalled["bid_status"] == "RECALLED"
        assert recalled["total_bid_cents"] == 0

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["item_status"] == "DRAFT"

    def test_quote_negotiation_round_reopens_on_recall(
        self, api, estimator_headers, contracting_officer_headers
    ):
        """PRD §3.4: "every quote on the project in `CARRIED` status returns to
        `RECEIVED` with its `version_round` incremented by one — reopening the
        negotiation round exactly as an explicit withdrawal would — and the
        project's `total_bid_cents` is reset to 0."

        Design: Difficulty/non_linear_state_machine/quote_negotiation_reopens_on_recall
        """
        ctx = setup_sealed_project(
            project_code="CALTRANS-04-1J5609",
            quote_overrides={
                "trade_code": "SWPPP",
                "contact_name": "Dana Reyes",
                "quoted_amount_cents": 18_000_000,
                "unicap_registered": True,
                "good_faith_effort_basis": "SOLICITED_DBE",
            },
            carry_quote=True,
        )
        assert ctx["quote"]["quote_status"] == "CARRIED"
        assert ctx["project"]["total_bid_cents"] == 21_000_000

        recalled = validate_success(
            api.recall_bid(
                ctx["project"]["id"],
                {"reason_code": "ERROR_IN_BID"},
                contracting_officer_headers,
            )
        )
        quote = validate_success(api.get_quote(ctx["quote"]["id"], estimator_headers))

        assert quote["quote_status"] == "RECEIVED"
        assert quote["version_round"] == 2
        assert quote["carried_in_bid"] is False
        assert recalled["total_bid_cents"] == 0

    def test_recalled_quote_can_be_carried_again_after_the_cycle(
        self, api, estimator_headers, contracting_officer_headers
    ):
        """PRD §3.4: "Recall is not terminal: the recalled bid can be re-prepared
        at leisure and sealed again once the deadline allows."
        PRD §3.3: "An `Estimator` carries a quote that is in `RECEIVED` status,
        which moves it to `CARRIED` and sets its carried-in-bid flag true."

        Design: Difficulty/non_linear_state_machine/quote_negotiation_reopens_on_recall
        """
        ctx = setup_sealed_project(
            project_code="CALTRANS-04-1J5609",
            quote_overrides={
                "trade_code": "SWPPP",
                "contact_name": "Dana Reyes",
                "quoted_amount_cents": 18_000_000,
                "unicap_registered": True,
                "good_faith_effort_basis": "SOLICITED_DBE",
            },
            carry_quote=True,
        )
        validate_success(
            api.recall_bid(
                ctx["project"]["id"],
                {"reason_code": "ERROR_IN_BID"},
                contracting_officer_headers,
            )
        )
        recarried = validate_success(api.carry_quote(ctx["quote"]["id"], estimator_headers))
        assert recarried["quote_status"] == "CARRIED"
        assert recarried["carried_in_bid"] is True
        assert recarried["version_round"] == 2, "the reopened round is the one that is carried"


class TestAwardCascade:
    def test_open_bid_awards_items_and_recomputes_reconciliation_then_project(
        self, api, contracting_officer_headers, estimator_headers
    ):
        """PRD §3.5: "Second, the project's awarded `contract_value_cents` is set
        equal to its `total_bid_cents`, capturing the bid total as the starting
        contract value that reconciliation will later adjust."
        PRD §3.5: "Third, every pay item on the project in `SUBMITTED` status is
        promoted to `AWARDED`, and for each pay item that enters `AWARDED` the
        system recomputes the quantity variance adjustment on the project's
        non-closed quantity reconciliation covering that item."
        PRD §3.5: "Fourth, those same reconciliations have their retention
        settlement recomputed — the signed net adjustment, the final contract
        value and the retention held — and the recomputed contract value and
        retention balance are written back onto the project."

        Design: Difficulty/transitive_cascade/open_bid_cascade_awards_items_then_recomputes_reconciliation_then_project
        """
        ctx = setup_sealed_project(
            project_code="CALTRANS-04-1J5610",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
            open_reconciliation_before_seal=True,
        )
        advance_clock("2026-12-01T00:00:00Z")
        validate_success(api.open_bid(ctx["project"]["id"], contracting_officer_headers))

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["item_status"] == "AWARDED"
        # No measurement has been recorded, so the committed measured quantity is
        # zero and the variance against the 1,000-unit estimate is -100.0.
        assert item["variance_pct"] == pytest.approx(-100.0)
        assert item["renegotiation_required"] is True

        reconciliation = validate_success(
            api.get_reconciliation(ctx["reconciliation"]["id"], contracting_officer_headers)
        )
        assert reconciliation["net_adjustment_cents"] == 0
        assert reconciliation["final_contract_value_cents"] == 3_000_000

        project = validate_success(
            api.get_project(ctx["project"]["id"], contracting_officer_headers)
        )
        assert project["project_status"] == "AWARDED"
        assert project["contract_value_cents"] == 3_000_000
        assert project["retention_balance_cents"] == 0

    def test_open_bid_promotes_only_submitted_items_but_awards_the_whole_bid_total(
        self, api, contracting_officer_headers, estimator_headers
    ):
        """PRD §3.5: "Third, every pay item on the project in `SUBMITTED` status
        is promoted to `AWARDED`"
        PRD §3.2: "A `SUBMITTED` item can be pulled back to `PRICED` again while
        the project's bid dimension is anything other than `OPEN`"
        PRD §3.2: "The population of included pay items is every item on the
        project whose `item_status` is not `DRAFT`."

        Design: Difficulty/transitive_cascade/open_bid_cascade_awards_items_then_recomputes_reconciliation_then_project
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5610")
        submitted = setup_priced_item(
            project["id"],
            item_code="2025-390108",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
        )
        priced_only = setup_priced_item(
            project["id"],
            item_code="2025-390109",
            estimated_quantity=500,
            bid_unit_price_cents=2000,
            submit=False,
        )
        validate_success(api.seal_bid(project["id"], estimator_headers))
        advance_clock("2026-12-01T00:00:00Z")
        opened = validate_success(api.open_bid(project["id"], contracting_officer_headers))

        assert opened["contract_value_cents"] == 4_000_000
        awarded = validate_success(api.get_bid_item(submitted["id"], estimator_headers))
        still_priced = validate_success(api.get_bid_item(priced_only["id"], estimator_headers))
        assert awarded["item_status"] == "AWARDED"
        assert still_priced["item_status"] == "PRICED"
