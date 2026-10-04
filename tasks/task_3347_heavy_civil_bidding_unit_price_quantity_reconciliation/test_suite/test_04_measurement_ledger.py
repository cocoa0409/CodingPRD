"""Field measurement: the running quantity ledger, variance bands and OCC guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    LOGICAL_CLOCK_START,
    advance_clock,
    api_client,
    approve_measurement,
    create_bond,
    create_measurement,
    create_project,
    create_surety,
    get_success_data,
    issue_bond,
    pay_measurement,
    setup_active_project,
    setup_active_project_with_measurement,
    setup_awarded_project_with_measurement,
    setup_priced_item,
    validate_error,
    validate_paginated,
    validate_success,
    void_measurement,
)


class TestQuantityVarianceBands:
    def test_variance_exactly_at_overrun_threshold_does_not_trigger(
        self, api, estimator_headers
    ):
        """PRD §3.9: "A variance exactly equal to the overrun band does not
        trigger, and a variance exactly equal to minus the underrun band does not
        trigger either."
        PRD §3.9: "an item measured exactly 15 percent over its estimate on the
        default bands is not renegotiable"

        Design: Difficulty/boundary_precision_check/variance_exactly_at_overrun_threshold_does_not_trigger
        """
        ctx = setup_active_project_with_measurement(
            1150, project_code="CALTRANS-04-1J5614", bid_unit_price_cents=2000
        )
        item = ctx["bid_item"]
        assert item["measured_quantity"] == pytest.approx(1150)
        assert item["variance_pct"] == pytest.approx(15.0)
        assert item["renegotiation_required"] is False

    def test_variance_exactly_at_minus_underrun_threshold_does_not_trigger(
        self, api, estimator_headers
    ):
        """PRD §3.9: "Renegotiation is required when the variance percentage is
        strictly greater than the item's `overrun_threshold_pct`, or when the
        variance percentage is strictly less than the negative of the item's
        `underrun_threshold_pct` — that is, when it falls below minus that band."
        PRD §3.9: "A variance exactly equal to the overrun band does not trigger,
        and a variance exactly equal to minus the underrun band does not trigger
        either."

        Design: Difficulty/boundary_precision_check/variance_exactly_at_overrun_threshold_does_not_trigger
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5614")
        at_band = setup_priced_item(
            project["id"],
            item_code="2025-390112",
            estimated_quantity=1000,
            bid_unit_price_cents=2000,
        )
        below_band = setup_priced_item(
            project["id"],
            item_code="2025-390113",
            estimated_quantity=1000,
            bid_unit_price_cents=2000,
        )
        # Mobilize through the surety/bond gate.
        surety = create_surety()
        bond = create_bond(project["id"], surety["id"], bond_amount_cents=12_000_000)
        validate_success(api.seal_bid(project["id"], estimator_headers))
        advance_clock("2026-12-01T00:00:00Z")
        validate_success(
            api.open_bid(project["id"], _headers("contracting_officer_headers"))
        )
        issue_bond(bond["id"], surety["id"])
        validate_success(api.start_work(project["id"], _headers("project_manager_headers")))

        m_at = create_measurement(at_band["id"], 850)
        approve_measurement(m_at["id"])
        m_below = create_measurement(below_band["id"], 849)
        approve_measurement(m_below["id"])

        item_at = get_success_data(api.get_bid_item(at_band["id"], estimator_headers))
        item_below = get_success_data(api.get_bid_item(below_band["id"], estimator_headers))
        assert item_at["variance_pct"] == pytest.approx(-15.0)
        assert item_at["renegotiation_required"] is False
        assert item_below["variance_pct"] == pytest.approx(-15.1)
        assert item_below["renegotiation_required"] is True


class TestMeasurementApproval:
    def test_measurement_approval_requires_active_line_item(self, api, estimator_headers):
        """PRD §3.8: "the approval requires the measurement's `measured_quantity`
        to be strictly greater than zero and the parent pay item to be in `ACTIVE`
        status; an approval against a pay item that is not `ACTIVE` is rejected
        with `ERR_ITEM_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/measurement_approval_requires_active_line_item
        """
        ctx = setup_awarded_project_with_measurement(500, project_code="CALTRANS-04-1J5617")
        response = api.approve_measurement(
            ctx["measurement"]["id"], _headers("project_manager_headers")
        )
        validate_error(response, ApiErrorId.ERR_ITEM_NOT_ACTIVE)
        assert response.status_code == 409

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["item_status"] == "AWARDED"
        measurement = validate_success(
            api.get_measurement(ctx["measurement"]["id"], estimator_headers)
        )
        assert measurement["measurement_status"] == "DRAFT"

    def test_measurement_approval_succeeds_once_the_item_is_active(
        self, api, estimator_headers
    ):
        """PRD §3.8: "Second, every pay item on the project in `AWARDED` status is
        promoted to `ACTIVE`, and each such item has its running measured quantity
        reset to zero"
        PRD §3.8: "Approval moves the measurement to `APPROVED`, recomputes the
        item's running measured quantity, signed variance percentage and
        renegotiation flag"

        Design: Difficulty/cross_entity_state_dependency/measurement_approval_requires_active_line_item
        """
        ctx = setup_active_project_with_measurement(
            500, approve=False, project_code="CALTRANS-04-1J5617", bid_unit_price_cents=2000
        )
        assert ctx["bid_item"]["item_status"] == "ACTIVE"

        approved = validate_success(
            api.approve_measurement(
                ctx["measurement"]["id"], _headers("project_manager_headers")
            )
        )
        assert approved["measurement_status"] == "APPROVED"
        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["measured_quantity"] == pytest.approx(500)
        assert item["variance_pct"] == pytest.approx(-50.0)

    def test_approving_an_already_payable_measurement_returns_invalid_state(
        self, api, estimator_headers
    ):
        """PRD §3.8: "A `ProjectManager` approves a measurement that is in `DRAFT`
        status"
        PRD §3.8: "A `ProjectManager` marks an approved measurement payable, which
        moves it from `APPROVED` to `PAYABLE` and freezes its payable amount at
        the value computed at approval"
        PRD §2.5: "The fifth band is state: if the target resource is not in the
        state that the requested transition requires, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/approving_an_already_payable_measurement_returns_invalid_state
        """
        ctx = setup_active_project_with_measurement(
            400,
            approve=True,
            pay=True,
            project_code="CALTRANS-04-1J5707",
            bid_unit_price_cents=2000,
        )
        assert ctx["measurement"]["measurement_status"] == "PAYABLE"
        assert ctx["measurement"]["payable_amount_cents"] == 800_000

        response = api.approve_measurement(
            ctx["measurement"]["id"], _headers("project_manager_headers")
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert response.status_code == 409

        after = validate_success(
            api.get_measurement(ctx["measurement"]["id"], estimator_headers)
        )
        assert after["measurement_status"] == "PAYABLE"
        assert after["payable_amount_cents"] == 800_000

    def test_measurement_approval_response_carries_cascaded_figures_immediately(
        self, api, estimator_headers
    ):
        """PRD §3.8: "The measurement's `payable_amount_cents` is then the
        measurement's `measured_quantity` multiplied by its
        `applied_unit_price_cents`, rounded half up to a whole cent."
        PRD §3.8: "Approval also recomputes the project's retention settlement and
        the owner's pace-based retention figure, refreshes the project's retention
        balance, and advances the project's `version`."
        PRD §2.12: "Reads that recompute a roll-up before answering refresh those
        computed figures on the returned representation as well"

        Design: Corner/consistency_model/measurement_approval_response_carries_cascaded_figures_immediately
        """
        ctx = setup_active_project_with_measurement(
            1200,
            approve=False,
            project_code="CALTRANS-04-1J5729",
            bid_unit_price_cents=2000,
        )
        approved = validate_success(
            api.approve_measurement(
                ctx["measurement"]["id"], _headers("project_manager_headers")
            )
        )
        assert approved["measurement_status"] == "APPROVED"
        assert approved["applied_unit_price_cents"] == 2000
        assert approved["payable_amount_cents"] == 2_400_000

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["measured_quantity"] == pytest.approx(1200)
        assert item["variance_pct"] == pytest.approx(20.0)

        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["retention_balance_cents"] == 120_000
        reconciliation = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert reconciliation["retention_held_cents"] == 120_000


class TestVoidReversal:
    def test_voiding_payable_measurement_restores_measured_quantity(
        self, api, estimator_headers
    ):
        """PRD §3.8: "Voiding moves the measurement to `VOIDED`, zeroes its
        payable amount, recomputes the item's running measured quantity, its
        signed variance percentage and its renegotiation flag, recomputes the
        project's retention settlement, and advances the project's `version`."
        PRD §3.8: "Because the counted population excludes `VOIDED` rows entirely,
        a voided measurement is invisible to the ledger once voided, which is what
        makes the reversal exact rather than an estimate."

        Design: Difficulty/compensating_invariant/voiding_payable_measurement_restores_measured_quantity
        """
        ctx = setup_active_project_with_measurement(
            500,
            approve=True,
            pay=True,
            project_code="CALTRANS-04-1J5621",
            bid_unit_price_cents=2000,
        )
        assert ctx["bid_item"]["measured_quantity"] == pytest.approx(500)

        voided = validate_success(
            api.void_measurement(
                ctx["measurement"]["id"], _headers("project_manager_headers")
            )
        )
        assert voided["measurement_status"] == "VOIDED"
        assert voided["payable_amount_cents"] == 0

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["measured_quantity"] == pytest.approx(0)
        assert item["variance_pct"] == pytest.approx(-100.0)
        assert item["renegotiation_required"] is True

    def test_voiding_payable_measurement_restores_the_withheld_retention(
        self, api, estimator_headers
    ):
        """PRD §3.10: "The project's `retention_balance_cents` is then the
        retention held minus the retention released, and the retention released
        is zero until a release succeeds, so while a project is in progress the
        balance equals the retention held."
        PRD §3.10: "The base for retention is the gross payable figure: the exact
        sum of the `payable_amount_cents` of every progress measurement on the
        project whose `measurement_status` is `APPROVED` or `PAYABLE`."

        Design: Difficulty/compensating_invariant/voiding_payable_measurement_restores_measured_quantity
        """
        ctx = setup_active_project_with_measurement(
            500,
            approve=True,
            pay=True,
            project_code="CALTRANS-04-1J5621",
            bid_unit_price_cents=2000,
        )
        held = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert held["retention_held_cents"] == 50_000
        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["retention_balance_cents"] == 50_000

        validate_success(
            api.void_measurement(
                ctx["measurement"]["id"], _headers("project_manager_headers")
            )
        )
        after = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert after["retention_held_cents"] == 0
        project_after = validate_success(
            api.get_project(ctx["project"]["id"], estimator_headers)
        )
        assert project_after["retention_balance_cents"] == 0

    def test_measurement_voided_reversal_leaves_low_variance_no_renegotiation(
        self, api, estimator_headers
    ):
        """PRD §3.8: "Because the counted population excludes `VOIDED` rows
        entirely, a voided measurement is invisible to the ledger once voided"
        PRD §3.9: "The item's derived `measured_quantity` is the sum of the counted
        measurements' quantities."

        Design: Corner/validations/measurement_voided_reversal_leaves_low_variance_no_renegotiation
        """
        ctx = setup_active_project_with_measurement(
            1000,
            approve=True,
            project_code="CALTRANS-04-1J5715",
            bid_unit_price_cents=2000,
        )
        second = create_measurement(
            ctx["bid_item"]["id"], 500, measured_at="2026-12-03T00:00:00Z"
        )
        approve_measurement(second["id"])
        pay_measurement(second["id"])

        validate_success(
            api.void_measurement(second["id"], _headers("project_manager_headers"))
        )
        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["measured_quantity"] == pytest.approx(1000)
        assert item["variance_pct"] == pytest.approx(0.0)
        assert item["renegotiation_required"] is False
        voided = validate_success(api.get_measurement(second["id"], estimator_headers))
        assert voided["measurement_status"] == "VOIDED"


class TestReconciliationArithmetic:
    def test_net_adjustment_is_zero_when_measurement_equals_the_estimate(
        self, api, estimator_headers
    ):
        """PRD §3.12: "A successful finalization sets the reconciliation to
        `FINALIZED` and its closeout marker to `PENDING_RETENTION`, recomputes the
        quantity variance adjustment over all of the project's pay items —
        producing the overrun item count, the underrun item count and the signed
        net adjustment — and recomputes the retention settlement, producing the
        final contract value and the retention held."
        PRD §3.10: "The `final_contract_value_cents` on the reconciliation is the
        project's `contract_value_cents` plus the reconciliation's
        `net_adjustment_cents`"

        Design: Difficulty/combinatorial_formula/net_adjustment_circular_evaluation_order_pinned
        """
        ctx = setup_active_project(
            project_code="CALTRANS-04-1J5607",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
        )
        measurement = create_measurement(ctx["bid_item"]["id"], 1000)
        approve_measurement(measurement["id"])

        finalized = validate_success(
            api.finalize_reconciliation(
                ctx["project"]["id"],
                ctx["reconciliation"]["id"],
                {"expected_project_version": _project_version(ctx["project"]["id"])},
                _headers("contracting_officer_headers"),
            )
        )
        assert finalized["reconciliation_status"] == "FINALIZED"
        assert finalized["net_adjustment_cents"] == 0
        assert finalized["final_contract_value_cents"] == 3_000_000
        assert finalized["retention_held_cents"] == 150_000
        assert finalized["overrun_item_count"] == 0
        assert finalized["underrun_item_count"] == 0

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["measured_quantity"] == pytest.approx(1000)
        assert item["variance_pct"] == pytest.approx(0.0)
        assert item["renegotiation_required"] is False

    def test_retention_base_is_gross_payable_not_the_reconciled_contract_value(
        self, api, estimator_headers
    ):
        """PRD §3.10: "The retention held is that gross payable figure multiplied
        by the project's `retention_rate_pct` and divided by 100, rounded half up
        exactly once, on the gross payable base, to a whole cent."
        PRD §3.10: "This figure is written back onto the project's
        `contract_value_cents` when the reconciliation finalizes, so that the
        project's awarded value becomes the reconciled value and a later read of
        the project shows the settled number rather than the bid number."

        Design: Difficulty/combinatorial_formula/net_adjustment_circular_evaluation_order_pinned
        """
        ctx = setup_active_project(
            project_code="CALTRANS-04-1J5607",
            bid_unit_price_cents=3000,
            estimated_quantity=1000,
        )
        measurement = create_measurement(ctx["bid_item"]["id"], 850)
        approve_measurement(measurement["id"])

        finalized = validate_success(
            api.finalize_reconciliation(
                ctx["project"]["id"],
                ctx["reconciliation"]["id"],
                {"expected_project_version": _project_version(ctx["project"]["id"])},
                _headers("contracting_officer_headers"),
            )
        )
        # 850 units at 3,000 cents is 2,550,000 gross payable; the item sits
        # exactly on minus its underrun band, so no uplift applies.
        assert finalized["net_adjustment_cents"] == 0
        assert finalized["final_contract_value_cents"] == 3_000_000
        assert finalized["retention_held_cents"] == 127_500

        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["contract_value_cents"] == 3_000_000
        assert project["retention_balance_cents"] == 127_500


class TestOptimisticConcurrency:
    def test_stale_bid_item_version_rejects_second_measurement(self, api, estimator_headers):
        """PRD §2.9: "Recording a new progress measurement against a pay item
        requires the body to carry `expected_bid_item_version`, holding the
        client's last observed `version` of that pay item."
        PRD §2.9: "If the value supplied does not equal the pay item's current
        `version` at the moment the write is processed, the request is rejected
        with `ERR_STALE_BID_ITEM_VERSION` and an HTTP 412 status."

        Design: Corner/cross_cutting_layers/stale_bid_item_version_rejects_second_measurement
        """
        ctx = setup_active_project(project_code="CALTRANS-04-1J5724")
        observed = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        stale_version = observed["version"]

        first = validate_success(
            api.create_measurement(
                ctx["bid_item"]["id"],
                {
                    "measured_quantity": 300,
                    "measured_at": "2026-12-02T00:00:00Z",
                    "expected_bid_item_version": stale_version,
                },
                _headers("project_manager_headers"),
            ),
            201,
        )
        assert first["measurement_status"] == "DRAFT"

        response = api.create_measurement(
            ctx["bid_item"]["id"],
            {
                "measured_quantity": 300,
                "measured_at": "2026-12-03T00:00:00Z",
                "expected_bid_item_version": stale_version,
            },
            _headers("project_manager_headers"),
        )
        validate_error(response, ApiErrorId.ERR_STALE_BID_ITEM_VERSION)
        assert response.status_code == 412

        # The rejected write left the ledger alone: the only row on the item is
        # still the first, still DRAFT, with its quantity unchanged.
        listed = api.list_measurements(
            estimator_headers, {"bid_item_id": ctx["bid_item"]["id"]}
        )
        rows, meta = validate_paginated(listed)
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["measured_quantity"] == pytest.approx(300)
        assert rows[0]["measurement_status"] == "DRAFT"

    def test_stale_project_version_rejects_reconciliation_finalize(self, api, estimator_headers):
        """PRD §2.9: "Finalizing a quantity reconciliation requires the body to
        carry `expected_project_version`, holding the client's last observed
        `version` of the parent project."
        PRD §2.9: "This guard exists because another writer may have issued an
        engineer determination or approved a measurement on the same project since
        the client last looked, both of which legitimately advance the project's
        version"

        Design: Corner/cross_cutting_layers/stale_project_version_rejects_reconciliation_finalize
        """
        ctx = setup_active_project(project_code="CALTRANS-04-1J5725")
        measurement = create_measurement(ctx["bid_item"]["id"], 400)
        observed = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        stale_version = observed["version"]

        approve_measurement(measurement["id"])

        response = api.finalize_reconciliation(
            ctx["project"]["id"],
            ctx["reconciliation"]["id"],
            {"expected_project_version": stale_version},
            _headers("contracting_officer_headers"),
        )
        validate_error(response, ApiErrorId.ERR_STALE_PROJECT_VERSION)
        assert response.status_code == 412
        after = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert after["reconciliation_status"] == "OPEN"


class TestMeasurementListing:
    def test_measurement_list_paginates_within_a_bid_item_filter(
        self, api, estimator_headers
    ):
        """PRD §2.3: "`total_count` is the number of records matching the filter
        before paging is applied, and `has_more` is true when further records
        remain beyond the returned window."
        PRD §2.3: "Unless a description says otherwise, every list endpoint
        returns its records ordered by creation timestamp ascending, so the oldest
        record appears first."

        Design: Corner/cross_cutting_layers/measurement_list_paginates_within_a_bid_item_filter
        """
        ctx = setup_active_project_with_measurement(
            400,
            approve=True,
            project_code="CALTRANS-04-1J5726",
            bid_unit_price_cents=2000,
        )
        draft = create_measurement(
            ctx["bid_item"]["id"], 600, measured_at="2026-12-03T00:00:00Z"
        )
        response = api.list_measurements(
            estimator_headers,
            {
                "bid_item_id": ctx["bid_item"]["id"],
                "measurement_status": "APPROVED",
                "limit": 1,
                "offset": 0,
            },
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["measured_quantity"] == pytest.approx(400)
        assert rows[0]["measurement_status"] == "APPROVED"
        assert rows[0]["id"] != draft["id"]
        assert draft["measurement_status"] == "DRAFT"


def _headers(role_fixture_name):
    from test_helpers import TEST_USERS

    return TEST_USERS[role_fixture_name]


def _project_version(project_id):
    from test_helpers import TEST_USERS

    project = get_success_data(api_client.get_project(project_id, TEST_USERS["contracting_officer_headers"]))
    return project["version"]
