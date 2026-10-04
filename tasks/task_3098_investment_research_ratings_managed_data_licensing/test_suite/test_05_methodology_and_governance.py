"""Methodology windows, methodology-change pipeline, holdings snapshot
validation, optimistic concurrency, and RBAC tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_change_ok,
    compute_quantitative_rating,
    create_category,
    create_fund,
    create_fund_company,
    create_licensee,
    get_agreement_version,
    get_success_data,
    grant_seat_ok,
    ingest_holdings,
    make_analyst_headers,
    propose_change_ok,
    record_notice_ok,
    setup_licensee_with_active_agreement,
    setup_rateable_fund,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["research_ops_headers"]
LIC = TEST_USERS["license_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestMethodologyWindowOverlap:
    def test_overlap_rejected_but_abutment_allowed(self, api):
        """PRD §3.3: "Activation is refused with `ERR_TEMPORAL_OVERLAP` when
        another same-code methodology is already `EFFECTIVE` with an
        overlapping window — where the window runs from `effective_from`
        inclusive to `effective_to` exclusive, so two windows that merely
        abut, one ending exactly where the other begins, are legal."
        PRD §3.3: "When the new version's window abuts or overlaps a
        currently `EFFECTIVE` same-code version, that prior version moves to
        `SUPERSEDED` and its `effective_to` is clipped to the successor's
        `effective_from`"

        Design: Difficulty/resource_temporal_overlap/methodology_window_overlap_rejected_but_abutment_allowed
        """
        from test_helpers import create_methodology_payload

        common = dict(
            methodology_code="QV8",
            methodology_kind="QUANTITATIVE",
            weight_return_bp=6000,
            weight_risk_bp=4000,
            rating_ceilings=[7000, 5000, 3000, 1000],
        )
        m1 = get_success_data(
            api.create_methodology(
                create_methodology_payload(
                    version_number=1,
                    effective_from="2026-01-01",
                    effective_to="2026-07-01",
                    **common,
                ),
                OPS,
            )
        )
        get_success_data(api.activate_methodology(m1["id"], OPS))
        m2 = get_success_data(
            api.create_methodology(
                create_methodology_payload(
                    version_number=2, effective_from="2026-06-01", **common
                ),
                OPS,
            )
        )
        m3 = get_success_data(
            api.create_methodology(
                create_methodology_payload(
                    version_number=3, effective_from="2026-07-01", **common
                ),
                OPS,
            )
        )
        resp_overlap = api.activate_methodology(m2["id"], OPS)
        validate_error(resp_overlap, ApiErrorId.ERR_TEMPORAL_OVERLAP, expected_status=422)

        m3_active = validate_success(api.activate_methodology(m3["id"], OPS))
        assert m3_active["methodology_status"] == "EFFECTIVE"
        m1_after = get_success_data(api.get_methodology(m1["id"], OPS))
        assert m1_after["methodology_status"] == "SUPERSEDED"
        assert m1_after["effective_to"] == "2026-07-01"

    def test_abutment_supersedes_incumbent_with_clipped_window(self, api):
        """PRD §3.3: "two windows that merely abut, one ending exactly where
        the other begins, are legal."
        PRD §3.3: "the same clipping applies whenever a newer same-code
        version activates with an `effective_from` on or before the
        incumbent's `effective_to`."

        Design: Difficulty/resource_temporal_overlap/methodology_window_overlap_rejected_but_abutment_allowed
        """
        from test_helpers import create_methodology_payload

        common = dict(
            methodology_code="QV8B",
            methodology_kind="QUANTITATIVE",
            weight_return_bp=6000,
            weight_risk_bp=4000,
            rating_ceilings=[7000, 5000, 3000, 1000],
        )
        m1 = get_success_data(
            api.create_methodology(
                create_methodology_payload(
                    version_number=1,
                    effective_from="2026-01-01",
                    effective_to="2026-08-01",
                    **common,
                ),
                OPS,
            )
        )
        get_success_data(api.activate_methodology(m1["id"], OPS))
        m2 = get_success_data(
            api.create_methodology(
                create_methodology_payload(
                    version_number=2, effective_from="2026-08-01", **common
                ),
                OPS,
            )
        )
        m2_active = validate_success(api.activate_methodology(m2["id"], OPS))
        assert m2_active["methodology_status"] == "EFFECTIVE"
        m1_after = get_success_data(api.get_methodology(m1["id"], OPS))
        assert m1_after["methodology_status"] == "SUPERSEDED"
        assert m1_after["effective_to"] == "2026-08-01"


class TestMethodologyChangeBranching:
    def test_withdraw_vs_effectuate_branching(self, api):
        """PRD §3.4: "Approval moves `change_status` from `PROPOSED` to
        `APPROVED`, effectuation from `APPROVED` to `EFFECTIVE`, and
        withdrawal — legal from either `PROPOSED` or `APPROVED` — to the
        terminal `WITHDRAWN`."
        PRD §3.4: "When the change's `restatement_required` is true, every
        `PUBLISHED` rating computed under the changed methodology moves to
        `RESTATED`, a successor rating is created for each — in `PROVISIONAL`
        for quantitative ratings or `COMMITTEE_REVIEW` for analyst ratings,
        each successor's `restatement_of_id` pointing at the rating it
        replaces — and the change's `restated_rating_count` is set to the
        number of ratings restated."

        Design: Difficulty/non_linear_state_machine/methodology_change_branching_withdraw_vs_effectuate
        """
        from test_helpers import create_and_activate_methodology

        methodology = create_and_activate_methodology(methodology_code="QV3")
        chg1 = propose_change_ok(methodology["id"], restatement_required=False)
        chg2 = propose_change_ok(methodology["id"], restatement_required=False)
        approve_change_ok(chg1["id"])
        approve_change_ok(chg2["id"])

        withdrawn = validate_success(api.withdraw_change(chg1["id"], OPS))
        assert withdrawn["change_status"] == "WITHDRAWN"

        licensee = create_licensee("Notice Recipient")
        record_notice_ok(chg2["id"], licensee["id"], channel="PORTAL")
        effected = validate_success(api.effectuate_change(chg2["id"], OPS))
        assert effected["change_status"] == "EFFECTIVE"
        assert effected["restated_rating_count"] == 0

    def test_withdrawn_change_carries_no_restatement_effects(self, api):
        """PRD §3.4: "A change may instead be withdrawn from either `PROPOSED`
        or `APPROVED`, moving it to the terminal `WITHDRAWN` state with no
        further effects."
        PRD §3.4: "`restated_rating_count` remains null until effectuation."

        Design: Difficulty/non_linear_state_machine/methodology_change_branching_withdraw_vs_effectuate
        """
        from test_helpers import create_and_activate_methodology

        methodology = create_and_activate_methodology(methodology_code="QV3B")
        change = propose_change_ok(methodology["id"], restatement_required=True)
        approve_change_ok(change["id"])
        withdrawn = validate_success(api.withdraw_change(change["id"], OPS))
        assert withdrawn["change_status"] == "WITHDRAWN"
        assert withdrawn["restated_rating_count"] is None
        # Effectuating a withdrawn change is an illegal transition.
        resp = api.effectuate_change(change["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


class TestMethodologyChangeTemporalGate:
    def test_future_effective_date_blocks_effectuate(self, api):
        """PRD §3.4: "Effectuating an approved change is legal only from
        `APPROVED`, only once `client_notice_sent` is true, and only once the
        logical-clock date has reached the `effective_date` (a premature
        attempt is rejected with `ERR_FUTURE_EFFECTIVE_DATE`)."

        Design: Corner/validations/future_effective_date_blocks_effectuate
        """
        from test_helpers import create_and_activate_methodology

        methodology = create_and_activate_methodology(methodology_code="QF1")
        change = propose_change_ok(
            methodology["id"], restatement_required=False, effective_date="2026-10-01"
        )
        approve_change_ok(change["id"])
        licensee = create_licensee("Future Notice")
        record_notice_ok(change["id"], licensee["id"], channel="EMAIL")

        resp = api.effectuate_change(change["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FUTURE_EFFECTIVE_DATE, expected_status=422)

        get_success_data(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, OPS))
        effected = validate_success(api.effectuate_change(change["id"], OPS))
        assert effected["change_status"] == "EFFECTIVE"

    def test_effectuate_without_client_notice_blocked(self, api):
        """PRD §3.4: "Effectuating an approved change is legal only from
        `APPROVED`, only once `client_notice_sent` is true, and only once the
        logical-clock date has reached the `effective_date`"

        Design: Corner/validations/effectuate_without_client_notice_blocked
        """
        from test_helpers import create_and_activate_methodology

        methodology = create_and_activate_methodology(methodology_code="QN1")
        change = propose_change_ok(
            methodology["id"], restatement_required=False, effective_date="2026-09-01"
        )
        approve_change_ok(change["id"])

        resp = api.effectuate_change(change["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        after = get_success_data(api.get_methodology_change(change["id"], OPS))
        assert after["change_status"] == "APPROVED"


class TestRestatementCascade:
    def test_restatement_cascade_counts_restated_ratings(self, api):
        """PRD §3.4: "When the change's `restatement_required` is true, every
        `PUBLISHED` rating computed under the changed methodology moves to
        `RESTATED`, a successor rating is created for each — in `PROVISIONAL`
        for quantitative ratings or `COMMITTEE_REVIEW` for analyst ratings,
        each successor's `restatement_of_id` pointing at the rating it
        replaces — and the change's `restated_rating_count` is set to the
        number of ratings restated."

        Design: Corner/cross_cutting_layers/methodology_restatement_cascade_counts_restated_ratings
        """
        from test_helpers import create_and_activate_methodology

        company = create_fund_company(legal_name="Restate Co")
        fund1 = create_fund(
            company["id"],
            ticker="FRST1",
            trailing_return_3y_bp=8000,
            trailing_return_5y_bp=8000,
            risk_score_bp=2000,
        )
        fund2 = create_fund(
            company["id"],
            ticker="FRST2",
            trailing_return_3y_bp=6000,
            trailing_return_5y_bp=6000,
            risk_score_bp=3000,
        )
        create_category(category_code="RS_C")
        ingest_holdings(fund1["id"])
        ingest_holdings(fund2["id"])
        methodology = create_and_activate_methodology(methodology_code="QRS")

        r1 = compute_quantitative_rating(fund1["id"], methodology["id"])
        get_success_data(api.publish_rating(r1["id"], OPS))
        r2 = compute_quantitative_rating(fund2["id"], methodology["id"])
        get_success_data(api.publish_rating(r2["id"], OPS))

        change = propose_change_ok(
            methodology["id"], restatement_required=True, effective_date="2026-09-01"
        )
        approve_change_ok(change["id"])
        licensee = create_licensee("Restate Notice")
        record_notice_ok(change["id"], licensee["id"], channel="API")
        effected = validate_success(api.effectuate_change(change["id"], OPS))
        assert effected["change_status"] == "EFFECTIVE"
        assert effected["restated_rating_count"] == 2

        r1_after = get_success_data(api.get_rating(r1["id"], OPS))
        r2_after = get_success_data(api.get_rating(r2["id"], OPS))
        assert r1_after["rating_status"] == "RESTATED"
        assert r2_after["rating_status"] == "RESTATED"

        ratings1, _ = validate_paginated(api.list_fund_ratings(fund1["id"], OPS))
        successors = [r for r in ratings1 if r.get("restatement_of_id") == r1["id"]]
        assert len(successors) == 1
        assert successors[0]["rating_status"] == "PROVISIONAL"
        ratings2, _ = validate_paginated(api.list_fund_ratings(fund2["id"], OPS))
        successors2 = [r for r in ratings2 if r.get("restatement_of_id") == r2["id"]]
        assert len(successors2) == 1
        assert successors2[0]["rating_status"] == "PROVISIONAL"


class TestUniquenessConstraints:
    def test_uniqueness_ticker_violation(self, api):
        """PRD §2.11: "The platform enforces the following uniqueness rules,
        each violation rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409): a
        fund's `ticker` is globally unique; the combination of a methodology's
        `methodology_code` and `version_number` is unique; a category's
        `category_code` is unique; an index definition's `index_code` is
        unique; and within a license agreement, an `ACTIVE` seat entitlement's
        `workstation_user_id` is unique (a revoked seat frees the identity for
        re-grant)."

        Design: Corner/validations/uniqueness_ticker_violation
        """
        c1 = create_fund_company(legal_name="U One")
        c2 = create_fund_company(legal_name="U Two")
        create_fund(c1["id"], ticker="DUP")
        resp = api.create_fund(
            {
                "fund_company_id": c2["id"],
                "ticker": "DUP",
                "inception_date": "2021-01-01",
                "trailing_return_3y_bp": 5000,
                "risk_score_bp": 1000,
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION, expected_status=409)


class TestHoldingsSnapshotValidation:
    def test_weight_sum_boundary_and_empty_eligible_set(self, api):
        """PRD §3.2: "the weights across the snapshot must sum to exactly
        10000 basis points, the `as_of_date` must not lie in the future
        relative to the logical clock, and a given snapshot date may be
        ingested only once per fund. Any violation is rejected with
        `ERR_SNAPSHOT_INVALID` (HTTP 422)."
        PRD §3.2: "An explicit `ResearchOps` re-run of assignment from the
        latest snapshot fails with `ERR_NO_ELIGIBLE_CATEGORY` (HTTP 422) when
        no active category clears its threshold."
        PRD §3.2: "Ingestion completing triggers category assignment on a
        best-effort basis: if no category qualifies, the snapshot is still
        persisted and the fund's `category_id` simply stays as it was (null if
        never assigned); the failure is only surfaced as an error by the
        explicit re-run."

        Design: Difficulty/boundary_precision_check/holdings_snapshot_weight_sum_boundary_and_empty_eligible_set
        """
        company = create_fund_company(legal_name="Boundary Sponsor")
        fund = create_fund(company["id"], ticker="FBND")
        create_category(
            category_code="STRICT6",
            dominant_asset_class="EQUITY",
            dominant_sector="MIXED",
            min_weight_bp=6000,
        )
        # sum = 9999 -> rejected
        resp_bad = api.ingest_holdings(
            fund["id"],
            {
                "as_of_date": "2026-08-31",
                "holdings": [
                    {"security_ticker": "A1", "asset_class": "EQUITY", "sector": "TECH", "weight_bp": 5999},
                    {"security_ticker": "A2", "asset_class": "BOND", "sector": "FINANCE", "weight_bp": 4000},
                ],
            },
            OPS,
        )
        validate_error(resp_bad, ApiErrorId.ERR_SNAPSHOT_INVALID, expected_status=422)

        # sum = exactly 10000 -> accepted
        resp_ok = api.ingest_holdings(
            fund["id"],
            {
                "as_of_date": "2026-08-31",
                "holdings": [
                    {"security_ticker": "A1", "asset_class": "EQUITY", "sector": "TECH", "weight_bp": 5000},
                    {"security_ticker": "A2", "asset_class": "BOND", "sector": "FINANCE", "weight_bp": 5000},
                ],
            },
            OPS,
        )
        validate_success(resp_ok, expected_status=201)

        # Explicit re-run: equity aggregate 5000 < min_weight_bp 6000 -> empty eligible set
        resp_assign = api.assign_category(fund["id"], OPS)
        validate_error(resp_assign, ApiErrorId.ERR_NO_ELIGIBLE_CATEGORY, expected_status=422)

        fund_after = get_success_data(api.get_fund(fund["id"], OPS))
        assert fund_after["category_id"] is None
        assert fund_after["category_assignment_revision"] == 0

    def test_snapshot_sum_one_below_and_one_above_rejected(self, api):
        """PRD §3.2: "the weights across the snapshot must sum to exactly
        10000 basis points, the `as_of_date` must not lie in the future
        relative to the logical clock, and a given snapshot date may be
        ingested only once per fund. Any violation is rejected with
        `ERR_SNAPSHOT_INVALID` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/holdings_snapshot_weight_sum_boundary_and_empty_eligible_set
        """
        company = create_fund_company(legal_name="Boundary Two")
        fund = create_fund(company["id"], ticker="FBND2")
        for date, weights in (("2026-08-30", 9999), ("2026-08-29", 10001)):
            resp = api.ingest_holdings(
                fund["id"],
                {
                    "as_of_date": date,
                    "holdings": [
                        {"security_ticker": "B1", "asset_class": "EQUITY", "sector": "TECH", "weight_bp": weights},
                    ],
                },
                OPS,
            )
            validate_error(resp, ApiErrorId.ERR_SNAPSHOT_INVALID, expected_status=422)

    def test_duplicate_snapshot_date_rejected(self, api):
        """PRD §3.2: "the weights across the snapshot must sum to exactly
        10000 basis points, the `as_of_date` must not lie in the future
        relative to the logical clock, and a given snapshot date may be
        ingested only once per fund. Any violation is rejected with
        `ERR_SNAPSHOT_INVALID` (HTTP 422)."

        Design: Corner/validations/duplicate_snapshot_date_rejected
        """
        company = create_fund_company(legal_name="Dup Snap Co")
        fund = create_fund(company["id"], ticker="FDS")
        ingest_holdings(
            fund["id"],
            holdings=[
                {"security_ticker": "DS1", "asset_class": "EQUITY", "sector": "TECH", "weight_bp": 10000}
            ],
        )
        resp = api.ingest_holdings(
            fund["id"],
            {
                "as_of_date": "2026-08-31",
                "holdings": [
                    {"security_ticker": "DS2", "asset_class": "EQUITY", "sector": "HEALTH", "weight_bp": 10000}
                ],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_INVALID, expected_status=422)


class TestCategoryAssignment:
    def test_category_assignment_tie_break_by_category_code(self, api):
        """PRD §3.2: "The eligible category with the highest score wins; a tie
        in score is broken by ascending `category_code`, never by identifier."
        PRD §3.2: "Whenever assignment — from ingestion, from the explicit
        re-run, or from an accepted category dispute — changes the fund's
        category, the fund's `category_id` is updated, its
        `category_assignment_revision` increments by 1"

        Design: Corner/calculations/category_assignment_tie_break_by_category_code
        """
        company = create_fund_company(legal_name="Tie Co")
        fund = create_fund(company["id"], ticker="FTIE")
        create_category(
            category_code="Z_TECH",
            dominant_asset_class="EQUITY",
            dominant_sector="TECH",
            min_weight_bp=5000,
        )
        a_tech = create_category(
            category_code="A_TECH",
            dominant_asset_class="EQUITY",
            dominant_sector="TECH",
            min_weight_bp=5000,
        )
        ingest_holdings(
            fund["id"],
            holdings=[
                {"security_ticker": "T1", "asset_class": "EQUITY", "sector": "TECH", "weight_bp": 10000}
            ],
        )
        fund_after = get_success_data(api.get_fund(fund["id"], OPS))
        assert fund_after["category_id"] == a_tech["id"]
        assert fund_after["category_assignment_revision"] == 1


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_seat_grant(self, api):
        """PRD §2.8: "Granting a seat entitlement requires
        `expected_agreement_version` matching the target license agreement's
        current `version`. Because every grant or revocation advances the
        agreement's version (its `seats_in_use` changes), a client whose view
        of remaining capacity predates another writer's grant or revocation is
        refused rather than allowed to oversubscribe the agreement."
        PRD §2.8: "if the supplied value does not match the parent entity's
        current `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"

        Design: Corner/endpoints/occ_stale_version_on_seat_grant
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="OCC Seats", tier="DISPLAY", seat_limit=5
        )
        v0 = get_agreement_version(agreement["id"])
        first = api.grant_seat(
            agreement["id"],
            {"workstation_user_id": "occ-1", "expected_agreement_version": v0},
            LIC,
        )
        validate_success(first, expected_status=201)
        second = api.grant_seat(
            agreement["id"],
            {"workstation_user_id": "occ-2", "expected_agreement_version": v0},
            LIC,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        ag_after = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_after["seats_in_use"] == 1

    def test_occ_stale_version_on_methodology_change_proposal(self, api):
        """PRD §2.8: "Proposing a methodology change requires
        `expected_methodology_version` matching the target methodology's
        current `version`, refusing a proposal whose baseline predates a
        competing change or a re-activation."
        PRD §2.8: "if the supplied value does not match the parent entity's
        current `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"

        Design: Corner/endpoints/occ_stale_version_on_methodology_change_proposal
        """
        from test_helpers import create_and_activate_methodology

        methodology = create_and_activate_methodology(methodology_code="MOCC")
        v0 = get_success_data(api.get_methodology(methodology["id"], OPS))["version"]
        payload = {
            "restatement_required": False,
            "effective_date": "2026-09-01",
            "expected_methodology_version": v0,
        }
        first = api.propose_methodology_change(methodology["id"], payload, OPS)
        validate_success(first, expected_status=201)
        second = api.propose_methodology_change(methodology["id"], dict(payload), OPS)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestRbacAndAuth:
    def test_analyst_cannot_suspend_fund_company(self, api):
        """PRD §2.1: "A request whose authenticated role is not permitted to
        invoke the endpoint per the authorization matrix is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /research/fund-companies/{id}/suspend — ResearchOps only.

        Design: Corner/rbac/analyst_cannot_suspend_fund_company
        """
        company = create_fund_company(legal_name="RBAC Co")
        resp = api.suspend_fund_company(company["id"], make_analyst_headers("analyst-x"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = get_success_data(api.get_fund_company(company["id"], OPS))
        assert after["company_status"] == "ACTIVE"

    def test_researchops_cannot_waive_conflict_flag(self, api):
        """PRD §2.7: "Only a `ComplianceOfficer` may waive a flag; waiver
        moves `flag_status` from `OPEN` to `WAIVED`, flips `blocking` to
        false, and unblocks publication unless another open commercial-conflict
        flag remains on the same fund."
        PRD §2.1: "A request whose authenticated role is not permitted to
        invoke the endpoint per the authorization matrix is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/researchops_cannot_waive_conflict_flag
        """
        company, fund, methodology = setup_rateable_fund(
            legal_name="Waive Co",
            commercial_relationship="LICENSED_CLIENT",
            fund_overrides={"ticker": "FCOF"},
            methodology_overrides=dict(methodology_code="QCO"),
        )
        compute_quantitative_rating(fund["id"], methodology["id"])
        flags, _meta = validate_paginated(api.list_fund_conflict_flags(fund["id"], COMPLIANCE))
        assert len(flags) >= 1
        flag = flags[0]

        resp = api.waive_conflict_flag(flag["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        waived = validate_success(api.waive_conflict_flag(flag["id"], COMPLIANCE))
        assert waived["flag_status"] == "WAIVED"
        assert waived["blocking"] is False

    def test_licenseadmin_cannot_compute_ratings(self, api):
        """PRD §2.1: "A request whose authenticated role is not permitted to
        invoke the endpoint per the authorization matrix is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /research/ratings/compute — ResearchOps only.

        Design: Corner/rbac/licenseadmin_cannot_compute_ratings
        """
        _company, fund, methodology = setup_rateable_fund(
            legal_name="RBAC2 Co",
            fund_overrides={"ticker": "FRB2"},
            methodology_overrides=dict(methodology_code="QRB2"),
        )
        resp = api.compute_rating(
            {"fund_id": fund["id"], "methodology_id": methodology["id"]}, LIC
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        that is not one of these five, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        resp = api.list_fund_companies(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestImmediateConsistency:
    def test_seat_grant_visible_immediately(self, api):
        """PRD §3.8: "Each grant increments the agreement's `seats_in_use` by
        1 and advances the agreement's `version`."
        PRD §3.8: "A granted seat — a seat entitlement whose `agreement_id`
        links it to its parent agreement — begins with `seat_status` set to
        `ACTIVE` and with its `entitled_data_scope` derived from the
        agreement's tier at grant time"

        Design: Corner/consistency_model/immediate_consistency_same_request_response
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Immediate Co", tier="DISPLAY", seat_limit=3
        )
        seat = grant_seat_ok(agreement["id"], "ic-1")
        assert seat["seat_status"] == "ACTIVE"
        assert seat["entitled_data_scope"] == "DISPLAY"
        ag_after = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_after["seats_in_use"] == 1
