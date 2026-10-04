"""License fees, audits and penalty cascades, seats, and index tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_constituent_ok,
    compute_quantitative_rating,
    create_fund,
    create_fund_company,
    create_licensee,
    create_published_quant_rating,
    get_agreement_version,
    get_success_data,
    grant_seat_ok,
    ingest_holdings,
    setup_licensed_index,
    setup_licensee_with_active_agreement,
    setup_rateable_fund,
    validate_error,
    validate_paginated,
    validate_success,
)

LIC = TEST_USERS["license_admin_headers"]
OPS = TEST_USERS["research_ops_headers"]


class TestFeeQuote:
    def test_tiered_discount_and_surcharge_interaction(self, api):
        """PRD §3.8: "The per-seat rate is 120000 cents for `DISPLAY`, 250000
        cents for `REDISTRIBUTION`, and 500000 cents for `DERIVED_WORKS`. A
        volume discount applies to the seat component only, by `seat_limit`:
        no discount for 1 to 10 seats, 1000 basis points for 11 to 50, 2000
        basis points for 51 to 200, and 3000 basis points above 200. A
        derived-works surcharge of 2500 basis points applies when the tier is
        `DERIVED_WORKS`, and 0 otherwise."
        PRD §3.8: "first, the raw seat component is the per-seat rate
        multiplied by `seat_limit`; second, the discounted seat component is
        the raw component minus the raw component multiplied by the
        volume-discount basis points floor-divided by 10000; third, the
        pre-surcharge subtotal is the `base_fee_cents` plus the discounted
        seat component; fourth, the total fee is the pre-surcharge subtotal
        plus that subtotal multiplied by the surcharge basis points
        floor-divided by 10000."

        Design: Difficulty/combinatorial_formula/license_fee_tiered_discount_and_surcharge_interaction
        """
        resp = api.fee_quote(
            {"tier": "DERIVED_WORKS", "seat_limit": 11, "base_fee_cents": 2000000}, LIC
        )
        data = validate_success(resp)
        # 500000*11=5500000; -10% = 4950000; +2000000 = 6950000; +25% = 8687500
        assert data["total_fee_cents"] == 8687500

        resp2 = api.fee_quote(
            {"tier": "DISPLAY", "seat_limit": 11, "base_fee_cents": 2000000}, LIC
        )
        data2 = validate_success(resp2)
        # 120000*11=1320000; -10% = 1188000; +2000000 = 3188000; no surcharge
        assert data2["total_fee_cents"] == 3188000

    def test_discount_band_boundary_at_eleven_seats(self, api):
        """PRD §3.8: "A volume discount applies to the seat component only, by
        `seat_limit`: no discount for 1 to 10 seats, 1000 basis points for 11
        to 50, 2000 basis points for 51 to 200, and 3000 basis points above
        200."

        Design: Difficulty/combinatorial_formula/license_fee_tiered_discount_and_surcharge_interaction
        """
        ten = validate_success(
            api.fee_quote({"tier": "DISPLAY", "seat_limit": 10, "base_fee_cents": 0}, LIC)
        )
        eleven = validate_success(
            api.fee_quote({"tier": "DISPLAY", "seat_limit": 11, "base_fee_cents": 0}, LIC)
        )
        # 10 seats: no discount -> 120000*10 = 1200000
        assert ten["total_fee_cents"] == 1200000
        # 11 seats: 1000bp discount on 1320000 -> 1188000
        assert eleven["total_fee_cents"] == 1188000

    def test_fee_quote_is_side_effect_free(self, api):
        """PRD §3.8: "The annual fee for an agreement follows a fixed quoted
        structure, also exposed as a fee preview that takes a `tier`,
        `seat_limit`, and `base_fee_cents` and returns `total_fee_cents`."

        Design: Corner/endpoints/fee_quote_endpoint_is_side_effect_free
        """
        payload = {"tier": "REDISTRIBUTION", "seat_limit": 51, "base_fee_cents": 500000}
        q1 = validate_success(api.fee_quote(payload, LIC))
        q2 = validate_success(api.fee_quote(payload, LIC))
        # 250000*51=12750000; -20% = 10200000; +500000 = 10700000
        assert q1["total_fee_cents"] == 10700000
        assert q2["total_fee_cents"] == 10700000
        # No agreement rows are persisted by fee preview calls.
        lic = create_licensee("Quote Probe")
        agreements, meta2 = validate_paginated(
            api.list_licensee_agreements(lic["id"], LIC)
        )
        assert agreements == []
        assert meta2["total_count"] == 0


class TestAuditPenaltyVariants:
    def _file_and_close(self, api, agreement_id, uses, outcome="PENALTY"):
        audit = get_success_data(api.open_audit({"agreement_id": agreement_id}, LIC))
        get_success_data(api.file_findings(audit["id"], {"unlicensed_uses_found": uses}, LIC))
        return get_success_data(api.close_audit(audit["id"], {"outcome": outcome}, LIC))

    def test_standard_vs_repeat_offender_penalty_diverge(self, api):
        """PRD §3.9: "When the licensee has any prior audit on any of its
        agreements that closed `CLOSED_WITH_PENALTY`, a repeat-offender uplift
        of 5000 basis points applies to the raw penalty before the floor;
        otherwise no uplift applies."
        PRD §3.9: "The per-use rate is 50000 cents for `DISPLAY`, 150000 cents
        for `REDISTRIBUTION`, and 400000 cents for `DERIVED_WORKS`; the raw
        penalty is that rate multiplied by `unlicensed_uses_found`."

        Design: Difficulty/dual_variant_calc/audit_penalty_standard_vs_repeat_offender
        """
        _l1, ag1 = setup_licensee_with_active_agreement(
            licensee_name="First Offense LLC X", tier="REDISTRIBUTION", seat_limit=10
        )
        a1 = self._file_and_close(api, ag1["id"], 3)
        assert a1["penalty_cents"] == 450000  # 150000*3, no prior penalty

        _l2, ag2 = setup_licensee_with_active_agreement(
            licensee_name="Repeat Offense LLC", tier="REDISTRIBUTION", seat_limit=10
        )
        b1 = self._file_and_close(api, ag2["id"], 1)
        assert b1["penalty_cents"] == 150000  # 150000*1 >= 100000 floor
        b2 = self._file_and_close(api, ag2["id"], 3)
        # repeat offender: 450000 + 450000*5000/10000 = 675000
        assert b2["penalty_cents"] == 675000
        assert b2["penalty_cents"] > a1["penalty_cents"]

    def test_repeat_offender_pays_strictly_more_above_floor(self, api):
        """PRD §3.9: "a repeat offender always pays strictly more than a first
        offender for the same finding count whenever the raw penalty is
        already at least the minimum."

        Design: Difficulty/dual_variant_calc/audit_penalty_standard_vs_repeat_offender
        """
        _lx, ag_x = setup_licensee_with_active_agreement(
            licensee_name="Fresh Offender", tier="REDISTRIBUTION", seat_limit=10
        )
        first = self._file_and_close(api, ag_x["id"], 3)
        second = self._file_and_close(api, ag_x["id"], 3)
        assert first["penalty_cents"] == 450000
        assert second["penalty_cents"] == 675000
        assert second["penalty_cents"] > first["penalty_cents"]


class TestAuditPenaltyCascade:
    def test_penalty_cascades_to_licensee_suspension_and_seat_revocation(self, api):
        """PRD §3.9: "A penalty close adds the computed `penalty_cents` to the
        licensee's `arrears_cents`. When that leaves arrears above 0, the
        licensee moves automatically from `ACTIVE` to `SUSPENDED`, every
        `ACTIVE` seat entitlement under the licensee's agreements moves to
        `REVOKED`, and each affected agreement's `seats_in_use` is recomputed
        to 0."

        Design: Difficulty/transitive_cascade/audit_penalty_cascades_to_licensee_suspension_and_seat_revocation
        """
        licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Cascade Client", tier="DERIVED_WORKS", seat_limit=2
        )
        grant_seat_ok(agreement["id"], "ws-1")
        grant_seat_ok(agreement["id"], "ws-2")
        ag_mid = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_mid["seats_in_use"] == 2

        audit = get_success_data(api.open_audit({"agreement_id": agreement["id"]}, LIC))
        get_success_data(api.file_findings(audit["id"], {"unlicensed_uses_found": 2}, LIC))
        closed = get_success_data(api.close_audit(audit["id"], {"outcome": "PENALTY"}, LIC))
        assert closed["penalty_cents"] == 800000  # 400000 * 2, first offense

        licensee_after = get_success_data(api.get_licensee(licensee["id"], LIC))
        assert licensee_after["licensee_status"] == "SUSPENDED"
        assert licensee_after["arrears_cents"] == 800000

        ag_after = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_after["seats_in_use"] == 0

        seats, _meta = validate_paginated(api.list_agreement_seats(agreement["id"], LIC))
        assert len(seats) == 2
        assert all(s["seat_status"] == "REVOKED" for s in seats)

    def test_suspension_blocks_new_seat_grants_after_cascade(self, api):
        """PRD §3.9: "When that leaves arrears above 0, the licensee moves
        automatically from `ACTIVE` to `SUSPENDED`"
        PRD §3.8: "The grant is refused with `ERR_SEAT_LIMIT_REACHED`
        (HTTP 422) when the agreement's `seats_in_use` has reached its
        `seat_limit`, or when either the agreement or the licensee is not
        `ACTIVE`"

        Design: Difficulty/transitive_cascade/audit_penalty_cascades_to_licensee_suspension_and_seat_revocation
        """
        licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Cascade Block", tier="DERIVED_WORKS", seat_limit=3
        )
        audit = get_success_data(api.open_audit({"agreement_id": agreement["id"]}, LIC))
        get_success_data(api.file_findings(audit["id"], {"unlicensed_uses_found": 1}, LIC))
        get_success_data(api.close_audit(audit["id"], {"outcome": "PENALTY"}, LIC))
        assert get_success_data(api.get_licensee(licensee["id"], LIC))["licensee_status"] == "SUSPENDED"

        version = get_agreement_version(agreement["id"])
        resp = api.grant_seat(
            agreement["id"],
            {"workstation_user_id": "ws-x", "expected_agreement_version": version},
            LIC,
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_LIMIT_REACHED, expected_status=422)


class TestSeatQuotaBoundary:
    def test_seat_quota_boundary_exactly_at_limit(self, api):
        """PRD §3.8: "The grant is refused with `ERR_SEAT_LIMIT_REACHED`
        (HTTP 422) when the agreement's `seats_in_use` has reached its
        `seat_limit`"

        Design: Difficulty/boundary_precision_check/seat_quota_boundary_exactly_at_limit
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Boundary Buyer", tier="DISPLAY", seat_limit=2
        )
        s1 = grant_seat_ok(agreement["id"], "bw-1")
        s2 = grant_seat_ok(agreement["id"], "bw-2")
        assert s1["seat_status"] == "ACTIVE" and s2["seat_status"] == "ACTIVE"

        version = get_agreement_version(agreement["id"])
        resp = api.grant_seat(
            agreement["id"],
            {"workstation_user_id": "bw-3", "expected_agreement_version": version},
            LIC,
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_LIMIT_REACHED, expected_status=422)
        ag_after = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_after["seats_in_use"] == 2

    def test_seat_at_limit_minus_one_succeeds(self, api):
        """PRD §3.8: "The grant is refused with `ERR_SEAT_LIMIT_REACHED`
        (HTTP 422) when the agreement's `seats_in_use` has reached its
        `seat_limit`"

        Design: Difficulty/boundary_precision_check/seat_quota_boundary_exactly_at_limit
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Boundary Buyer Two", tier="DISPLAY", seat_limit=2
        )
        grant_seat_ok(agreement["id"], "bw-1")
        ag_mid = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_mid["seats_in_use"] == 1
        # The grant taking seats_in_use from limit-1 to exactly limit succeeds.
        grant_seat_ok(agreement["id"], "bw-2")
        ag_after = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_after["seats_in_use"] == 2


class TestSeatInvariant:
    def test_seat_grant_revoke_conserves_seats_in_use(self, api):
        """PRD §3.8: "Each grant increments the agreement's `seats_in_use` by
        1 and advances the agreement's `version`. Revoking a seat moves
        `seat_status` to `REVOKED`, decrements `seats_in_use` by 1, and
        advances both the seat's and the agreement's versions"

        Design: Difficulty/compensating_invariant/seat_grant_revoke_conserves_seats_in_use
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Invariant Inc", tier="REDISTRIBUTION", seat_limit=3
        )
        assert get_success_data(api.get_license_agreement(agreement["id"], LIC))["seats_in_use"] == 0
        seat = grant_seat_ok(agreement["id"], "inv-1")
        assert get_success_data(api.get_license_agreement(agreement["id"], LIC))["seats_in_use"] == 1

        resp = api.revoke_seat(seat["id"], LIC)
        seat_after = validate_success(resp)
        assert seat_after["seat_status"] == "REVOKED"
        ag_after = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        assert ag_after["seats_in_use"] == 0
        seats, _meta = validate_paginated(
            api.list_agreement_seats(agreement["id"], LIC, params={"seat_status": "ACTIVE"})
        )
        assert len(seats) == 0

    def test_seats_in_use_reconciles_with_active_seat_rows(self, api):
        """PRD §3.8: "Each grant increments the agreement's `seats_in_use` by
        1 and advances the agreement's `version`."

        Design: Difficulty/compensating_invariant/seat_grant_revoke_conserves_seats_in_use
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Invariant Two", tier="REDISTRIBUTION", seat_limit=3
        )
        grant_seat_ok(agreement["id"], "inv-a")
        seat_b = grant_seat_ok(agreement["id"], "inv-b")
        get_success_data(api.revoke_seat(seat_b["id"], LIC))
        ag = get_success_data(api.get_license_agreement(agreement["id"], LIC))
        seats, _meta = validate_paginated(
            api.list_agreement_seats(agreement["id"], LIC, params={"seat_status": "ACTIVE"})
        )
        assert len(seats) == ag["seats_in_use"] == 1


class TestAgreementTemporalOverlap:
    def test_agreement_window_overlap_same_tier_but_not_cross_tier(self, api):
        """PRD §3.8: "no other agreement for the same licensee and same tier
        is already `ACTIVE` with an overlapping window; abutting windows are
        legal, and violations are rejected with `ERR_TEMPORAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_window_overlap_same_tier_but_not_cross_tier
        """
        from test_helpers import create_agreement_payload

        licensee = create_licensee("Overlap Org")
        o1 = get_success_data(
            api.create_license_agreement(
                create_agreement_payload(
                    licensee["id"], tier="DISPLAY", effective_from="2026-01-01"
                ),
                LIC,
            )
        )
        get_success_data(api.activate_agreement(o1["id"], LIC))
        o2 = get_success_data(
            api.create_license_agreement(
                create_agreement_payload(
                    licensee["id"], tier="DISPLAY", effective_from="2026-06-01"
                ),
                LIC,
            )
        )
        o3 = get_success_data(
            api.create_license_agreement(
                create_agreement_payload(
                    licensee["id"], tier="REDISTRIBUTION", effective_from="2026-06-01"
                ),
                LIC,
            )
        )
        resp_overlap = api.activate_agreement(o2["id"], LIC)
        validate_error(resp_overlap, ApiErrorId.ERR_TEMPORAL_OVERLAP, expected_status=422)
        resp_ok = api.activate_agreement(o3["id"], LIC)
        assert validate_success(resp_ok)["agreement_status"] == "ACTIVE"
        o2_after = get_success_data(api.get_license_agreement(o2["id"], LIC))
        assert o2_after["agreement_status"] == "DRAFT"

    def test_same_window_different_tier_activates(self, api):
        """PRD §3.8: "no other agreement for the same licensee and same tier
        is already `ACTIVE` with an overlapping window; abutting windows are
        legal, and violations are rejected with `ERR_TEMPORAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_window_overlap_same_tier_but_not_cross_tier
        """
        from test_helpers import create_agreement_payload

        licensee = create_licensee("Cross Tier Org")
        for tier in ("DISPLAY", "REDISTRIBUTION", "DERIVED_WORKS"):
            ag = get_success_data(
                api.create_license_agreement(
                    create_agreement_payload(
                        licensee["id"], tier=tier, effective_from="2026-01-01"
                    ),
                    LIC,
                )
            )
            activated = validate_success(api.activate_agreement(ag["id"], LIC))
            assert activated["agreement_status"] == "ACTIVE"


class TestAuditOutcomeValidation:
    def test_penalty_close_with_zero_uses_rejected(self, api):
        """PRD §3.9: "Closing with `PENALTY` — moving `audit_status` to
        `CLOSED_WITH_PENALTY` — requires `unlicensed_uses_found` greater than
        0 — a penalty close with zero unlicensed uses is rejected with
        `ERR_AUDIT_OUTCOME_INVALID` (HTTP 422)"
        PRD §3.9: "Closing with `NO_ACTION` is legal from `FINDINGS_FILED` and
        moves the audit to `CLOSED_NO_ACTION` with `penalty_cents` at 0."

        Design: Corner/validations/audit_close_penalty_with_zero_uses_rejected
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Clean Client", tier="DISPLAY", seat_limit=5
        )
        audit = get_success_data(api.open_audit({"agreement_id": agreement["id"]}, LIC))
        get_success_data(api.file_findings(audit["id"], {"unlicensed_uses_found": 0}, LIC))

        resp = api.close_audit(audit["id"], {"outcome": "PENALTY"}, LIC)
        validate_error(resp, ApiErrorId.ERR_AUDIT_OUTCOME_INVALID, expected_status=422)

        closed = get_success_data(api.close_audit(audit["id"], {"outcome": "NO_ACTION"}, LIC))
        assert closed["audit_status"] == "CLOSED_NO_ACTION"
        assert closed["penalty_cents"] == 0


class TestAgreementTermination:
    def test_terminate_agreement_with_active_seats_blocked(self, api):
        """PRD §3.8: "Terminating an agreement — legal from `DRAFT`, `ACTIVE`,
        or `SUSPENDED` — requires `seats_in_use` to be 0 when done manually;
        seats still outstanding produce `ERR_SEATS_STILL_ACTIVE` (HTTP 409)."

        Design: Corner/validations/terminate_agreement_with_active_seats_blocked
        """
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Terminate Seats", tier="DISPLAY", seat_limit=2
        )
        seat = grant_seat_ok(agreement["id"], "ts-1")
        resp = api.terminate_agreement(agreement["id"], LIC)
        validate_error(resp, ApiErrorId.ERR_SEATS_STILL_ACTIVE, expected_status=409)

        get_success_data(api.revoke_seat(seat["id"], LIC))
        terminated = get_success_data(api.terminate_agreement(agreement["id"], LIC))
        assert terminated["agreement_status"] == "TERMINATED"


class TestIndexRebalance:
    def test_index_rebalance_cap_and_redistribute_then_discard(self, api):
        """PRD §3.10: "In the first pass, each constituent's final weight is
        set to the smaller of its `target_weight_bp` and the
        `single_constituent_cap_bp`, and whatever was capped away accumulates
        as excess. In the second pass, while excess remains, the walk repeats
        in the same order, adding to each constituent the smaller of the
        remaining excess and the headroom between the cap and that
        constituent's current final weight; when a full pass adds nothing to
        any constituent, redistribution stops and any leftover excess is
        discarded — so the total final weight may legitimately fall below
        10000 basis points, which is by design and not an error."

        Design: Corner/calculations/index_rebalance_cap_and_redistribute_then_discard
        """
        _company, fund_a, methodology = setup_rateable_fund(
            legal_name="Rebalance Co",
            fund_overrides={
                "ticker": "RBA",
                "trailing_return_3y_bp": 9000,
                "trailing_return_5y_bp": 9000,
                "risk_score_bp": 1000,
            },
            methodology_overrides=dict(methodology_code="QRB"),
        )
        rating_a = compute_quantitative_rating(fund_a["id"], methodology["id"])
        get_success_data(api.publish_rating(rating_a["id"], OPS))

        fund_b = create_fund(
            fund_a["fund_company_id"],
            ticker="RBB",
            trailing_return_3y_bp=8000,
            trailing_return_5y_bp=8000,
            risk_score_bp=1000,
        )
        ingest_holdings(fund_b["id"])
        fund_c = create_fund(
            fund_a["fund_company_id"],
            ticker="RBC",
            trailing_return_3y_bp=7000,
            trailing_return_5y_bp=7000,
            risk_score_bp=1000,
        )
        ingest_holdings(fund_c["id"])
        for f in (fund_b, fund_c):
            r = compute_quantitative_rating(f["id"], methodology["id"])
            get_success_data(api.publish_rating(r["id"], OPS))

        licensee, agreement, _ = setup_licensed_index(
            methodology, index_overrides={"index_code": "IXPRE", "single_constituent_cap_bp": 9000}
        )

        # Index 1: single constituent 8000 target, cap 3000 -> final 3000,
        # unplaceable 5000 bp excess discarded without error.
        from test_helpers import create_index_payload

        idx1 = get_success_data(
            api.create_index(
                create_index_payload(
                    methodology["id"], index_code="IRB1", single_constituent_cap_bp=3000
                ),
                LIC,
            )
        )
        get_success_data(
            api.link_license(idx1["id"], {"licensed_agreement_id": agreement["id"]}, LIC)
        )
        add_constituent_ok(idx1["id"], fund_a["id"], 8000)

        # Index 2: cap 4000 with targets 5000/3000/2000 -> 4000/4000/2000.
        idx2 = get_success_data(
            api.create_index(
                create_index_payload(
                    methodology["id"], index_code="IRB2", single_constituent_cap_bp=4000
                ),
                LIC,
            )
        )
        get_success_data(
            api.link_license(idx2["id"], {"licensed_agreement_id": agreement["id"]}, LIC)
        )
        add_constituent_ok(idx2["id"], fund_a["id"], 5000)
        add_constituent_ok(idx2["id"], fund_b["id"], 3000)
        add_constituent_ok(idx2["id"], fund_c["id"], 2000)

        launched1 = validate_success(api.launch_index(idx1["id"], LIC))
        launched2 = validate_success(api.launch_index(idx2["id"], LIC))
        assert launched1["index_status"] == "LIVE"
        assert launched2["index_status"] == "LIVE"

        cons1, _ = validate_paginated(api.list_index_constituents(idx1["id"], LIC))
        assert len(cons1) == 1
        assert cons1[0]["fund_id"] == fund_a["id"]
        assert cons1[0]["final_weight_bp"] == 3000

        cons2, _ = validate_paginated(api.list_index_constituents(idx2["id"], LIC))
        by_fund = {c["fund_id"]: c["final_weight_bp"] for c in cons2}
        assert by_fund[fund_a["id"]] == 4000
        assert by_fund[fund_b["id"]] == 4000  # 3000 + 1000 redistributed
        assert by_fund[fund_c["id"]] == 2000


class TestIndexLaunchDependencies:
    def test_index_launch_gated_on_agreement_tier_and_rating_state(self, api):
        """PRD §3.10: "Before an index can go live it must be licensed:
        linking a license sets `licensed_agreement_id` to an agreement that is
        `ACTIVE` with tier `DERIVED_WORKS`, and launching — whether the first
        launch from `DRAFT` or a relaunch from `SUSPENDED` — requires that
        linked agreement to be `ACTIVE` and `DERIVED_WORKS` with the licensee
        `ACTIVE` (tier or status failures are rejected with
        `ERR_LICENSE_TIER_INSUFFICIENT`, HTTP 422), requires the tracked
        methodology to be `EFFECTIVE` (otherwise
        `ERR_METHODOLOGY_NOT_EFFECTIVE`), and requires at least one
        constituent and no more than `max_constituents` (unmet launch
        preconditions are rejected with `ERR_INDEX_NOT_LICENSABLE`,
        HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/index_launch_gated_on_agreement_tier_and_fund_rating_state
        """
        _company, fund, methodology, _rating = create_published_quant_rating()
        _licensee, agreement = setup_licensee_with_active_agreement(
            licensee_name="Index Licensee", tier="DISPLAY"
        )
        from test_helpers import create_index_payload

        index = get_success_data(
            api.create_index(
                create_index_payload(
                    methodology["id"], index_code="IX1", single_constituent_cap_bp=5000
                ),
                LIC,
            )
        )
        resp_link = api.link_license(
            index["id"], {"licensed_agreement_id": agreement["id"]}, LIC
        )
        validate_error(resp_link, ApiErrorId.ERR_LICENSE_TIER_INSUFFICIENT, expected_status=422)

        add_constituent_ok(index["id"], fund["id"], 4000)
        resp_launch = api.launch_index(index["id"], LIC)
        validate_error(resp_launch, ApiErrorId.ERR_INDEX_NOT_LICENSABLE, expected_status=409)

        index_after = get_success_data(api.get_index(index["id"], LIC))
        assert index_after["index_status"] == "DRAFT"

    def test_launch_requires_published_rating_under_index_methodology(self, api):
        """PRD §3.10: "Constituents are added by naming a `fund_id` and a
        requested `target_weight_bp`; each constituent row's `index_id` ties
        it to its parent index, the fund must be `ACTIVE` and hold a
        `PUBLISHED` rating under the index's methodology, and the constituent
        count must not exceed `max_constituents`."

        Design: Difficulty/cross_entity_state_dependency/index_launch_gated_on_agreement_tier_and_fund_rating_state
        """
        # Fund with a merely PROVISIONAL rating under the index methodology
        _company, fund, methodology = setup_rateable_fund(
            methodology_overrides=dict(methodology_code="QV7B")
        )
        compute_quantitative_rating(fund["id"], methodology["id"])  # stays PROVISIONAL
        _licensee, _agreement, index = setup_licensed_index(
            methodology, index_overrides={"index_code": "IXP"}
        )
        resp = api.add_constituent(
            index["id"], {"fund_id": fund["id"], "target_weight_bp": 4000}, LIC
        )
        # Admission requires a PUBLISHED rating; a PROVISIONAL-only fund is refused.
        assert resp.status_code in (409, 422), (
            f"Expected constituent admission refusal, got {resp.status_code}: {resp.text}"
        )
