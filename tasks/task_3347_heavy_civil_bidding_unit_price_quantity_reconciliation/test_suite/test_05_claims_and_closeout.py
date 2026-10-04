"""Differing site conditions, retention settlement and project closeout."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    approve_measurement,
    create_measurement,
    document_condition,
    get_success_data,
    pay_measurement,
    release_retention,
    report_condition,
    setup_active_project,
    setup_active_project_with_claim,
    setup_active_project_with_measurement,
    setup_bonded_awarded_project,
    setup_open_project,
    setup_under_review_claim_with_draft_measurement,
    validate_error,
    validate_success,
    void_measurement,
)


class TestNoticeClock:
    def test_notice_clock_counts_whole_days_from_reported_at(self, api, estimator_headers):
        """PRD §3.11: "The elapsed notice figure is the whole number of days
        between the condition's `reported_at` instant and the current logical
        clock, obtained by taking the difference in seconds, dividing by 86,400 to
        convert to days, and discarding the fractional part so that only whole
        days count."
        PRD §3.11: "The figure is recomputed whenever the condition is documented,
        whenever a claim is submitted, and on every read of the condition"

        Design: Corner/calculations/notice_clock_counts_whole_days_from_reported_at
        """
        ctx = setup_active_project(project_code="CALTRANS-04-1J5712")
        condition = report_condition(
            ctx["project"]["id"],
            reported_at="2026-12-01T00:00:00Z",
            claimed_amount_cents=1_000_000,
        )
        advance_clock("2026-12-11T00:00:00Z")
        read = validate_success(api.get_condition(condition["id"], estimator_headers))
        assert read["notice_days_elapsed"] == 10
        assert read["condition_status"] == "REPORTED"


class TestClaimDocumentation:
    def test_empty_documentation_package_returns_incomplete(self, api, estimator_headers):
        """PRD §3.11: "A `ProjectManager` documents a `REPORTED` condition by
        supplying `documentation_package_urls`, which must be a non-empty array;
        an empty or absent array is rejected with `ERR_DOCUMENTATION_INCOMPLETE`
        (HTTP 422)."

        Design: Corner/validations/empty_documentation_package_returns_incomplete
        """
        ctx = setup_active_project_with_claim(
            condition_status="REPORTED",
            claimed_amount_cents=2_000_000,
            project_code="CALTRANS-04-1J5714",
        )
        response = api.document_condition(
            ctx["condition"]["id"],
            {"documentation_package_urls": []},
            _headers("project_manager_headers"),
        )
        validate_error(response, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)
        assert response.status_code == 422

        after = validate_success(api.get_condition(ctx["condition"]["id"], estimator_headers))
        assert after["condition_status"] == "REPORTED"
        assert after["documentation_complete"] is False

    def test_claim_with_zero_amount_is_rejected_at_submission(self, api, estimator_headers):
        """PRD §3.11: "And the condition's `claimed_amount_cents` must be strictly
        greater than zero, because a claim for nothing is not a claim; a zero
        amount is rejected with `ERR_CLAIM_AMOUNT_REQUIRED` (HTTP 422)."

        Design: Corner/validations/unique_construction_worker_cannot_approve_its_own_claim
        """
        ctx = setup_active_project_with_claim(
            condition_status="DOCUMENTED",
            claimed_amount_cents=0,
            project_code="CALTRANS-04-1J5713",
        )
        response = api.submit_claim(
            ctx["condition"]["id"], _headers("project_manager_headers")
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_AMOUNT_REQUIRED)
        assert response.status_code == 422

        after = validate_success(api.get_condition(ctx["condition"]["id"], estimator_headers))
        assert after["condition_status"] == "DOCUMENTED"

    def test_denying_a_determined_condition_returns_invalid_state(
        self, api, estimator_headers
    ):
        """PRD §3.11: "An `Engineer` denies a condition that is in `REPORTED`,
        `DOCUMENTED` or `UNDER_REVIEW` status, moving it directly to `DENIED`"
        PRD §3.11: "`DENIED` is terminal."
        PRD §2.5: "The fifth band is state: if the target resource is not in the
        state that the requested transition requires, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/denying_a_determined_condition_returns_invalid_state
        """
        ctx = setup_active_project_with_claim(
            condition_status="UNDER_REVIEW", project_code="CALTRANS-04-1J5709"
        )
        determination = validate_success(
            api.engineer_determination(
                ctx["condition"]["id"],
                {"determination_type": "TIME_EXTENSION", "days_granted": 14},
                _headers("engineer_headers"),
            )
        )
        assert determination["determination_status"] == "ISSUED"

        response = api.deny_condition(
            ctx["condition"]["id"], _headers("engineer_headers")
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert response.status_code == 409

        after = validate_success(api.get_condition(ctx["condition"]["id"], estimator_headers))
        assert after["condition_status"] == "DETERMINED"
        kept = validate_success(
            api.get_determination(determination["id"], estimator_headers)
        )
        assert kept["determination_status"] == "ISSUED"


class TestCloseoutGates:
    def test_open_claim_blocks_finalize_before_measurement_gap(self, api):
        """PRD §3.12: "the finalization requires, in the precedence order
        established in §2.5, that no differing site condition on the project sits
        in `REPORTED`, `DOCUMENTED` or `UNDER_REVIEW` — an open claim blocks
        closeout and is rejected with `ERR_OPEN_CLAIM_BLOCKS_CLOSEOUT` (HTTP 422)"
        PRD §2.5: "The bulk of this band is concentrated on the reconciliation
        finalization, where the open-claim test outranks the pending-measurement
        test"

        Design: Difficulty/priority_pair_validation_conflict/open_claim_blocks_finalize_before_measurement_gap
        """
        ctx = setup_under_review_claim_with_draft_measurement(
            project_code="CALTRANS-04-1J5613"
        )
        response = api.finalize_reconciliation(
            ctx["project"]["id"],
            ctx["reconciliation"]["id"],
            {"expected_project_version": _project_version(ctx["project"]["id"])},
            _headers("contracting_officer_headers"),
        )
        validate_error(response, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_CLOSEOUT)
        assert response.status_code == 422

        project = validate_success(api.get_project(ctx["project"]["id"], _headers("contracting_officer_headers")))
        assert project["project_status"] == "ACTIVE"
        reconciliation = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert reconciliation["reconciliation_status"] == "OPEN"

    def test_existence_band_outranks_the_open_claim_band(self, api):
        """PRD §2.5: "The third band is referential existence, and within it the
        checks run in a fixed order"
        PRD §2.5: "then `ERR_RECONCILIATION_NOT_FOUND` (HTTP 404) when a
        reconciliation identifier resolves to no `QuantityReconciliation` or to
        one belonging to a different project"
        PRD §2.7: "a reconciliation reached through one project's path that
        belongs to another yields `ERR_RECONCILIATION_NOT_FOUND`"

        Design: Difficulty/priority_pair_validation_conflict/open_claim_blocks_finalize_before_measurement_gap
        """
        ctx = setup_under_review_claim_with_draft_measurement(
            project_code="CALTRANS-04-1J5613"
        )
        response = api.finalize_reconciliation(
            ctx["project"]["id"],
            "00000000-0000-4000-8000-000000000000",
            {"expected_project_version": _project_version(ctx["project"]["id"])},
            _headers("contracting_officer_headers"),
        )
        validate_error(response, ApiErrorId.ERR_RECONCILIATION_NOT_FOUND)
        assert response.status_code == 404

        reconciliation = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert reconciliation["reconciliation_status"] == "OPEN"

    def test_project_manager_cannot_finalize_quantity_reconciliation(self, api):
        """PRD §2.1: "`ContractingOfficer` is the owner-side authority, who opens
        and recalls bids, selects or rejects quotes, releases capacity
        commitments, finalizes the quantity reconciliation, and releases
        retention."
        PRD §2.1: "A request whose declared role is not permitted on the
        operation being attempted is rejected with `ERR_FORBIDDEN` and an HTTP 403
        status."

        Design: Corner/rbac/project_manager_cannot_finalize_quantity_reconciliation
        """
        ctx = setup_active_project(project_code="CALTRANS-04-1J5723")
        response = api.finalize_reconciliation(
            ctx["project"]["id"],
            ctx["reconciliation"]["id"],
            {"expected_project_version": _project_version(ctx["project"]["id"])},
            _headers("project_manager_headers"),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert response.status_code == 403
        reconciliation = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert reconciliation["reconciliation_status"] == "OPEN"


class TestRetentionSettlement:
    def test_retention_percentage_basis_versus_pace_grade(self, api, estimator_headers):
        """PRD §3.10: "The retention held is that gross payable figure multiplied
        by the project's `retention_rate_pct` and divided by 100, rounded half up
        exactly once, on the gross payable base, to a whole cent."
        PRD §3.10: "When the gross payable figure falls below the monthly pace,
        the pace-based retention held is the monthly pace multiplied by the
        project's `retention_rate_pct` and divided by 100, rounded half up to a
        whole cent."

        Design: Difficulty/dual_variant_calc/retention_percentage_basis_versus_pace_grade
        """
        ctx = setup_active_project_with_measurement(
            1000,
            approve=True,
            pay=True,
            project_code="CALTRANS-04-1J5605",
            bid_unit_price_cents=2000,
        )
        reconciliation = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert reconciliation["retention_held_cents"] == 100_000
        assert reconciliation["pace_basis_retention_cents"] == 16_666_667
        assert reconciliation["retention_released_cents"] == 0

    def test_pace_grade_releases_retention_where_the_percentage_basis_still_holds_it(
        self, api, estimator_headers
    ):
        """PRD §3.10: "When the gross payable figure is at least that monthly
        pace, the pace-based retention held is zero, because a project moving work
        at or above the graded pace releases retention entirely."
        PRD §3.10: "Note the deliberate asymmetry with the contractual figure: the
        comparison to the pace is at or above, so a project whose gross payable
        exactly equals the monthly pace releases retention in full under this
        grade while the contractual percentage basis would still hold it."

        Design: Difficulty/dual_variant_calc/retention_percentage_basis_versus_pace_grade
        """
        ctx = setup_active_project_with_measurement(
            166_667,
            approve=True,
            pay=True,
            project_code="CALTRANS-04-1J5605",
            bid_unit_price_cents=2000,
            estimated_quantity=1000,
        )
        reconciliation = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        # 166,667 units at 2,000 cents is 333,334,000 gross payable, which is at
        # or above the 333,333,333-cent monthly pace.
        assert reconciliation["pace_basis_retention_cents"] == 0
        assert reconciliation["retention_held_cents"] == 16_666_700

    def test_retention_balance_tracks_a_voided_measurement(self, api, estimator_headers):
        """PRD §3.10: "The project's `retention_balance_cents` is then the
        retention held minus the retention released, and the retention released
        is zero until a release succeeds"
        PRD §3.8: "Voiding moves the measurement to `VOIDED`, zeroes its payable
        amount, recomputes the item's running measured quantity, its signed
        variance percentage and its renegotiation flag, recomputes the project's
        retention settlement"

        Design: Corner/cross_cutting_layers/retention_balance_tracks_a_voided_measurement
        """
        ctx = setup_active_project_with_measurement(
            1000,
            approve=True,
            pay=True,
            project_code="CALTRANS-04-1J5727",
            bid_unit_price_cents=2000,
        )
        held = validate_success(
            api.get_reconciliation(
                ctx["reconciliation"]["id"], _headers("contracting_officer_headers")
            )
        )
        assert held["retention_held_cents"] == 100_000
        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["retention_balance_cents"] == 100_000

        voided = validate_success(
            api.void_measurement(
                ctx["measurement"]["id"], _headers("project_manager_headers")
            )
        )
        assert voided["payable_amount_cents"] == 0

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
        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["measured_quantity"] == pytest.approx(0)


class TestCloseoutCascade:
    def test_retention_release_cascade_closes_items_project_and_surety(
        self, api, platform_admin_headers, estimator_headers
    ):
        """PRD §3.12: "First, every pay item of the project that is in `ACTIVE`
        status is moved to `CLOSED`, which is the pay item's terminal state."
        PRD §3.12: "Second, when every pay item of the project has reached
        `CLOSED`, the project's delivery dimension becomes `COMPLETE` and its
        claim window is shut by clearing the `claim_window_open` flag."
        PRD §3.12: "Third, every surety commitment on the project that is in
        `RESERVED` or `ACTIVE` status becomes `RELEASED` with its released-at
        instant taken from the logical clock, and every bond on the project that
        is in `ISSUED` status becomes `RELEASED`"

        Design: Difficulty/transitive_cascade/retention_release_cascade_closes_items_project_and_surety
        """
        ctx = setup_active_project(
            project_code="CALTRANS-04-1J5611",
            bid_unit_price_cents=2000,
            commitment_amount_cents=12_000_000,
        )
        measurement = create_measurement(ctx["bid_item"]["id"], 1000)
        approve_measurement(measurement["id"])
        pay_measurement(measurement["id"])
        finalized = validate_success(
            api.finalize_reconciliation(
                ctx["project"]["id"],
                ctx["reconciliation"]["id"],
                {"expected_project_version": _project_version(ctx["project"]["id"])},
                _headers("contracting_officer_headers"),
            )
        )
        assert finalized["reconciliation_status"] == "FINALIZED"

        closed = validate_success(
            api.release_retention(
                ctx["project"]["id"],
                ctx["reconciliation"]["id"],
                _headers("contracting_officer_headers"),
            )
        )
        assert closed["reconciliation_status"] == "CLOSED"
        assert closed["retention_released_cents"] == 100_000

        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["item_status"] == "CLOSED"
        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["project_status"] == "COMPLETE"
        assert project["claim_window_open"] is False

        surety = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert surety["capacity_consumed_cents"] == 0
        assert surety["available_capacity_cents"] == 200_000_000

    def test_surety_capacity_moves_because_the_project_completed(
        self, api, platform_admin_headers
    ):
        """PRD §2.11: "The consumed amount is the sum of the capacity consumed by
        that surety's bonds plus the sum of the committed amounts of that surety's
        commitments that are either reserved or active"
        PRD §2.11: "releasing the bond sets its consumed amount to zero and
        therefore returns exactly that amount to the available total"
        PRD §3.12: "the surety exposure is then recomputed for every surety bound
        to the project"

        Design: Difficulty/transitive_cascade/retention_release_cascade_closes_items_project_and_surety
        """
        ctx = setup_active_project(
            project_code="CALTRANS-04-1J5611",
            bid_unit_price_cents=2000,
            commitment_amount_cents=12_000_000,
        )
        measurement = create_measurement(ctx["bid_item"]["id"], 1000)
        approve_measurement(measurement["id"])
        pay_measurement(measurement["id"])
        validate_success(
            api.finalize_reconciliation(
                ctx["project"]["id"],
                ctx["reconciliation"]["id"],
                {"expected_project_version": _project_version(ctx["project"]["id"])},
                _headers("contracting_officer_headers"),
            )
        )
        drawn = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert drawn["capacity_consumed_cents"] == 24_000_000
        assert drawn["available_capacity_cents"] == 176_000_000

        release_retention(
            ctx["project"]["id"], ctx["reconciliation"]["id"]
        )
        restored = validate_success(api.get_surety(ctx["surety"]["id"], platform_admin_headers))
        assert restored["capacity_consumed_cents"] == 0
        assert restored["available_capacity_cents"] == 200_000_000
        assert restored["aggregate_capacity_cents"] == 200_000_000


class TestMobilizationGate:
    def test_empty_carried_quote_set_yields_zero_dbe_credit(self, api, estimator_headers):
        """PRD §3.7: "the project must satisfy its disadvantaged-business
        obligation, which is satisfied when the project's credited
        `dbe_participation_pct` is at least the project's
        `advertised_dbe_goal_pct`"
        PRD §3.3: "When the denominator is zero — a project with no carried or
        selected quotes at all — the participation percentage is exactly 0 rather
        than undefined or null."
        PRD §3.7: "A mobilization that fails the disadvantaged-business test is
        rejected with `ERR_DBE_GOOD_FAITH_MISSING` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/empty_carried_quote_set_yields_zero_dbe_credit
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5615",
            bid_unit_price_cents=2000,
            estimated_quantity=1000,
            advertised_dbe_goal_pct=10.0,
            bond_amount_cents=12_000_000,
            issue_bond_now=True,
        )
        response = api.start_work(ctx["project"]["id"], _headers("project_manager_headers"))
        validate_error(response, ApiErrorId.ERR_DBE_GOOD_FAITH_MISSING)
        assert response.status_code == 422

        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["dbe_participation_pct"] == pytest.approx(0)
        assert project["project_status"] == "AWARDED"

    def test_documented_good_faith_effort_opens_the_mobilization_gate(
        self, api, estimator_headers
    ):
        """PRD §3.7: "or, failing that, when any subcontractor quote on the
        project documents a good-faith-effort basis of `SOLICITED_DBE`,
        `DOCUMENTED_UNAVAILABLE` or `OUTREACH_EVENT`"
        PRD §3.7: "First, the project's delivery dimension becomes `ACTIVE` and
        its claim window is opened by setting the `claim_window_open` flag true"

        Design: Difficulty/boundary_precision_check/empty_carried_quote_set_yields_zero_dbe_credit
        """
        ctx = setup_open_project(
            project_code="CALTRANS-04-1J5615",
            bid_unit_price_cents=2000,
            estimated_quantity=1000,
            advertised_dbe_goal_pct=10.0,
            bond_amount_cents=12_000_000,
            issue_bond_now=True,
            quote_overrides={
                "trade_code": "SWPPP",
                "contact_name": "Dana Reyes",
                "quoted_amount_cents": 18_000_000,
                "unicap_registered": False,
                "good_faith_effort_basis": "SOLICITED_DBE",
            },
            carry_quote=False,
        )
        assert ctx["quote"]["quote_status"] == "RECEIVED"
        started = validate_success(
            api.start_work(ctx["project"]["id"], _headers("project_manager_headers"))
        )
        assert started["project_status"] == "ACTIVE"
        assert started["claim_window_open"] is True
        assert started["dbe_participation_pct"] == pytest.approx(0)

    def test_performance_bond_and_surety_status_gate_work_start(self, api, estimator_headers):
        """PRD §3.7: "The project must carry a performance bond — that is, a
        `Bond` with `bond_type` `PERFORMANCE` — that is in `ISSUED` status. The
        surety backing that bond must itself be `ACTIVE`, so a surety suspended
        between issue and mobilization will hold the project at the gate."
        PRD §2.5: "The sixth band is business safety, where a suspended surety is
        rejected first with `ERR_SURETY_SUSPENDED` (HTTP 422) before any capacity
        arithmetic is attempted"

        Design: Difficulty/cross_entity_state_dependency/performance_bond_issued_and_surety_active_gate_work_start
        """
        ctx = setup_bonded_awarded_project(
            project_code="CALTRANS-04-1J5616",
            bid_unit_price_cents=2000,
            suspend_surety=True,
        )
        response = api.start_work(ctx["project"]["id"], _headers("project_manager_headers"))
        validate_error(response, ApiErrorId.ERR_SURETY_SUSPENDED)
        assert response.status_code == 422

        project = validate_success(api.get_project(ctx["project"]["id"], estimator_headers))
        assert project["project_status"] == "AWARDED"
        bond = validate_success(api.get_bond(ctx["bond"]["id"], estimator_headers))
        assert bond["bond_status"] == "ISSUED"
        surety = validate_success(api.get_surety(ctx["surety"]["id"], estimator_headers))
        assert surety["surety_status"] == "SUSPENDED"

    def test_reinstating_the_surety_restores_the_mobilization_gate(self, api, estimator_headers):
        """PRD §3.6: "a `PlatformAdmin` reinstates a `SUSPENDED` surety, returning
        it to `ACTIVE` and recomputing its available capacity."
        PRD §3.7: "Second, every pay item on the project in `AWARDED` status is
        promoted to `ACTIVE`, and each such item has its running measured quantity
        reset to zero"
        PRD §3.7: "Third, every surety commitment on the project that is in
        `RESERVED` status becomes `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/performance_bond_issued_and_surety_active_gate_work_start
        """
        ctx = setup_bonded_awarded_project(
            project_code="CALTRANS-04-1J5616",
            bid_unit_price_cents=2000,
            suspend_surety=True,
        )
        validate_success(
            api.reinstate_surety(ctx["surety"]["id"], _headers("platform_admin_headers"))
        )
        started = validate_success(
            api.start_work(ctx["project"]["id"], _headers("project_manager_headers"))
        )
        assert started["project_status"] == "ACTIVE"
        assert started["claim_window_open"] is True
        item = validate_success(api.get_bid_item(ctx["bid_item"]["id"], estimator_headers))
        assert item["item_status"] == "ACTIVE"
        assert item["measured_quantity"] == pytest.approx(0)


def _headers(role_fixture_name):
    from test_helpers import TEST_USERS

    return TEST_USERS[role_fixture_name]


def _project_version(project_id):
    project = get_success_data(
        api_client.get_project(project_id, _headers("contracting_officer_headers"))
    )
    return project["version"]
