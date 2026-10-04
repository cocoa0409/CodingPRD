"""Agreement amendments (OCC) and the dual-variant equity index."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_agreement,
    assert_instant_equals,
    create_agreement_payload,
    make_account,
    make_agreement,
    make_review,
    make_territory,
    make_transfer,
    make_wholesaler,
    post_audit,
    qualification_review,
    setup_awarded_territory,
    setup_qualified_transfer,
    validate_error,
    validate_success,
    get_success_data,
)

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestAmendment:
    def test_agreement_amend_in_place_bumps_version_and_logs(self, api, admin_headers):
        """PRD §3.2: "Every amendment request must carry
        `expected_agreement_version` under the optimistic-concurrency rule of
        §2.7 — a supplied version that no longer matches is rejected with
        `ERR_STALE_VERSION`, while amending a `TERMINATED` agreement is
        rejected with `ERR_AGREEMENT_NOT_ACTIVE`."
        PRD §3.2: "On success, the agreement's initially empty `amendment_log`
        gains an entry recording `amended_at` — read from the logical clock —
        together with the `fields_changed`; the agreement's `version`
        increments by one and its status remains `ACTIVE`."

        Design: Corner/state_machines/agreement_amend_in_place_bumps_version_and_logs
        """
        _, _, agreement = setup_awarded_territory(territory_name="Amend Territory")
        assert agreement["version"] == 1

        resp = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": agreement["version"],
             "share_target_pct": 50, "declared_share_pct": 45},
            admin_headers,
        )
        amended = validate_success(resp, 200)
        assert_agreement(amended)
        assert amended["version"] == 2
        assert amended["status"] == "ACTIVE"
        assert amended["share_target_pct"] == 50
        assert amended["declared_share_pct"] == 45
        assert amended["distribution_target_pct"] == 80, (
            "untouched fields keep their values"
        )
        log = amended["amendment_log"]
        assert len(log) == 1, f"expected exactly 1 amendment entry, got {len(log)}"
        assert_instant_equals(log[0]["amended_at"], "2026-09-01T00:00:00Z",
                              label="amended_at")
        assert set(log[0]["fields_changed"]) == {"share_target_pct",
                                                 "declared_share_pct"}

    def test_occ_stale_version_amendment_returns_412(self, api, admin_headers):
        """PRD §2.7: "When the supplied value does not match the agreement's
        current `version` — because another writer has amended the agreement
        since the client read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently
        overwriting terms it has not observed."

        Design: Corner/complexity_layers/occ_stale_version_amendment_returns_412
        """
        _, _, agreement = setup_awarded_territory(territory_name="OCC Territory")
        observed = agreement["version"]

        first = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": observed, "share_target_pct": 50},
            admin_headers,
        )
        after_first = validate_success(first, 200)
        assert after_first["version"] == 2

        second = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": observed, "share_target_pct": 60},
            admin_headers,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)

        current = validate_success(api.get_agreement(agreement["id"], admin_headers))
        assert current["share_target_pct"] == 50, (
            "the losing amendment changed nothing"
        )
        assert len(current["amendment_log"]) == 1

    def test_amend_terminated_agreement_rejected(self, api, admin_headers):
        """PRD §2.7: "Ordering matters here: the stale-version check runs
        immediately after the state precondition, so amending a `TERMINATED`
        agreement reports `ERR_AGREEMENT_NOT_ACTIVE` even when the supplied
        version is also stale."

        Design: Corner/validations/amend_terminated_agreement_rejected
        """
        env = setup_qualified_transfer(rofr=False, buyer_scores=80)
        transfer = env["transfer"]
        agreement = env["agreement"]
        resp = api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                     COMPLIANCE)
        validate_success(resp, 200)
        consummated = api.consummate_transfer(transfer["id"], admin_headers)
        validate_success(consummated, 200)

        dead = validate_success(api.get_agreement(agreement["id"], admin_headers))
        assert dead["status"] == "TERMINATED"
        assert dead["version"] == 2, (
            "termination is a mutation: version advanced from 1 (PRD §2.4)"
        )

        resp = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": dead["version"], "share_target_pct": 55},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


@pytest.fixture
def equity_scenario(api):
    """Agreement (declared 80/90/50, STANDARD) + one FAIL audit making pooled
    Q3 freshness 80.00 + a 2026-Q3 review (distribution 70, share 60)."""
    territory = make_territory(name="North Texas", state_code="TX")
    wholesaler = make_wholesaler(
        legal_name="Plains Distributing", tier="GOLD",
        financial_capacity_score=80, warehouse_capacity_score=80,
        market_coverage_score=80)
    agreement = make_agreement(
        territory["id"], wholesaler["id"],
        brand_scope=["BUD", "BUD-LTD"],
        distribution_target_pct=85, freshness_target_index=90,
        share_target_pct=45, declared_distribution_pct=80,
        declared_freshness_index=90, declared_share_pct=50, term_years=5)
    account = make_account(wholesaler["id"], name="Downtown Tap", state_code="TX")
    audit_resp = post_audit(
        account["id"],
        conducted_at="2026-09-10T00:00:00Z",
        line_cleaning_last_at="2026-09-03T00:00:00Z",
        kegs=[
            {"brand_code": "BUD", "filled_at": "2026-08-31T00:00:00Z",
             "volume_bbl": 80},
            {"brand_code": "BUD", "filled_at": "2026-06-07T00:00:00Z",
             "volume_bbl": 20},
        ],
    )
    if audit_resp.status_code != 201:
        raise AssertionError(f"Setup failed at audit: {audit_resp.text[:300]}")
    audit = get_success_data(audit_resp)
    review = make_review(wholesaler["id"], period_year=2026, period_quarter="Q3",
                         distribution_pct=70, share_pct=60)
    return {"territory": territory, "wholesaler": wholesaler,
            "agreement": agreement, "account": account,
            "audit": audit, "review": review}


class TestEquityIndexDualVariant:
    def test_equity_index_provisional_variant_uses_declared_metrics(
        self, api, equity_scenario
    ):
        """PRD §3.2: "Under the default `PROVISIONAL` variant, the three
        components are the agreement's own declared metrics —
        `declared_distribution_pct`, `declared_freshness_index`, and
        `declared_share_pct` — and the response's `components_source` reads
        `DECLARED`."
        PRD §3.2: "the index itself is the same weighted blend: one-half of the
        distribution component, plus three-tenths of the freshness component,
        plus one-fifth of the share component, rounded half-up to two decimal
        places."

        Design: Difficulty/dual_variant_calc/equity_index_provisional_vs_audited
        """
        sc = equity_scenario
        assert sc["audit"]["result"] == "FAIL"
        assert sc["audit"]["stale_keg_count"] == 1
        assert sc["review"]["freshness_index"] == pytest.approx(80.00, abs=1e-9)
        assert sc["review"]["composite_score"] == pytest.approx(70.00, abs=1e-9)

        resp = api.get_equity_index(sc["agreement"]["id"], ADMIN,
                                    params={"variant": "PROVISIONAL"})
        data = validate_success(resp, 200)
        assert data["equity_index"] == pytest.approx(77.00, abs=1e-9), (
            "0.5*80 + 0.3*90 + 0.2*50 = 77.00"
        )
        assert data["components_source"] == "DECLARED"
        assert data["distribution_component"] == pytest.approx(80, abs=1e-9)
        assert data["freshness_component"] == pytest.approx(90, abs=1e-9)
        assert data["share_component"] == pytest.approx(50, abs=1e-9)

    def test_equity_index_audited_variant_uses_latest_review(
        self, api, equity_scenario, compliance_headers
    ):
        """PRD §3.2: "Under the `AUDITED` variant, the components come instead
        from the latest performance review of the agreement's wholesaler —
        latest by `period_year` and then `period_quarter`, in any review
        status: that review's `distribution_pct`, `freshness_index`, and
        `share_pct` become the components and `components_source` reads
        `LATEST_REVIEW`."

        Design: Difficulty/dual_variant_calc/equity_index_provisional_vs_audited
        """
        sc = equity_scenario
        resp = api.get_equity_index(sc["agreement"]["id"], compliance_headers,
                                    params={"variant": "AUDITED"})
        data = validate_success(resp, 200)
        assert data["equity_index"] == pytest.approx(71.00, abs=1e-9), (
            "0.5*70 + 0.3*80.00 + 0.2*60 = 71.00"
        )
        assert data["components_source"] == "LATEST_REVIEW"

        prov = validate_success(
            api.get_equity_index(sc["agreement"]["id"], ADMIN,
                                 params={"variant": "PROVISIONAL"})
        )
        assert prov["equity_index"] != data["equity_index"], (
            "variant selection, not data, moves the index"
        )


class TestEquityIndexNoReview:
    def test_equity_index_audited_null_without_review(self, api, admin_headers):
        """PRD §3.2: "When the wholesaler has no performance review at all, the
        audited index cannot be computed: `equity_index` is null and
        `components_source` reads `NO_REVIEW`."

        Design: Corner/calculations/equity_index_audited_null_without_review
        """
        _, _, agreement = setup_awarded_territory(
            territory_name="Null Territory",
            agreement_overrides={
                "distribution_target_pct": 85, "freshness_target_index": 90,
                "share_target_pct": 45, "declared_distribution_pct": 80,
                "declared_freshness_index": 90, "declared_share_pct": 50,
            },
        )
        audited = validate_success(
            api.get_equity_index(agreement["id"], admin_headers,
                                 params={"variant": "AUDITED"})
        )
        assert audited["equity_index"] is None
        assert audited["components_source"] == "NO_REVIEW"

        provisional = validate_success(
            api.get_equity_index(agreement["id"], admin_headers,
                                 params={"variant": "PROVISIONAL"})
        )
        assert provisional["equity_index"] == pytest.approx(77.00, abs=1e-9)
        assert provisional["components_source"] == "DECLARED"
