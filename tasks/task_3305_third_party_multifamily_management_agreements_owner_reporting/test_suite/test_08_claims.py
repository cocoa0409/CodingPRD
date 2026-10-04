"""Claims: settlement shares, OCC, immutability, reserve/exit guards (PRD §3.9, §3.7, §2.5)."""
from test_helpers import (
    ApiErrorId,
    assert_claim_settlement,
    assert_settlement_invariants,
    create_claim_payload,
    get_success_data,
    make_owner_rep_headers,
    setup_managed_property,
    setup_owner,
    setup_property,
    start_onboarding,
    setup_resident,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import create_claim_under_review
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
ACCT = TEST_USERS["acct_headers"]
RISK = TEST_USERS["risk_headers"]


class TestSettlementSharesDiverge:
    def test_claim_settlement_shares_diverge_by_indemnification_domain(self, api):
        """PRD §3.9: "When `indemnified_by` is `MANAGER`, the manager's share
        is the settlement amount capped at 100000000 cents (the manager
        indemnity cap): the lesser of `amount_cents` and the cap. When it is
        `OWNER`, the manager's share is zero. When it is `SHARED`, the
        manager's share is the settlement amount multiplied by 0.25, rounded
        half-up to whole cents. In all three branches, `owner_share_cents` is
        the amount minus `manager_share_cents`."

        Design: Difficulty/dual_variant_calc/claim_settlement_shares_diverge_by_indemnification_domain
        """
        fx = setup_managed_property(legal_name="Share Owner LLC",
                                    property_name="Share Property", unit_count=100)
        prop = fx["prop"]
        c_owner = create_claim_under_review(
            prop, claim_type="RESIDENT_INCIDENT", reserved_amount_cents=0,
            indemnified_by="OWNER", incident_date="2026-09-10T00:00:00Z",
        )
        c_shared = create_claim_under_review(
            prop, claim_type="EMPLOYMENT", reserved_amount_cents=0,
            indemnified_by="SHARED", incident_date="2026-09-11T00:00:00Z",
        )

        get_success_data(
            api.settle_claim(
                c_owner["id"],
                {"amount_cents": 4000000,
                 "expected_claim_version": c_owner["version"]},
                RISK,
            )
        )
        get_success_data(
            api.settle_claim(
                c_shared["id"],
                {"amount_cents": 4000000,
                 "expected_claim_version": c_shared["version"]},
                RISK,
            )
        )

        s_owner, _ = validate_paginated(
            api.list_claim_settlements(c_owner["id"], RISK)
        )
        s_shared, _ = validate_paginated(
            api.list_claim_settlements(c_shared["id"], RISK)
        )
        assert len(s_owner) == 1 and len(s_shared) == 1
        so, ss = s_owner[0], s_shared[0]
        assert so["manager_share_cents"] == 0
        assert so["owner_share_cents"] == 4000000
        assert ss["manager_share_cents"] == 1000000, (
            f"round(4000000 * 0.25) == 1000000, got {ss['manager_share_cents']}"
        )
        assert ss["owner_share_cents"] == 3000000
        assert_settlement_invariants(so)
        assert_settlement_invariants(ss)

    def test_claim_settlement_manager_share_capped_at_indemnity_cap(self, api):
        """PRD §3.9: "When `indemnified_by` is `MANAGER`, the manager's share
        is the settlement amount capped at 100000000 cents (the manager
        indemnity cap): the lesser of `amount_cents` and the cap."

        Design: Difficulty/dual_variant_calc/claim_settlement_shares_diverge_by_indemnification_domain
        """
        fx = setup_managed_property(legal_name="Cap Owner LLC",
                                    property_name="Cap Property", unit_count=100)
        prop = fx["prop"]
        # In-term incident under MANAGER indemnification, amount above the cap.
        c = create_claim_under_review(
            prop, claim_type="RESIDENT_INCIDENT", reserved_amount_cents=0,
            indemnified_by="MANAGER", incident_date="2026-09-12T00:00:00Z",
        )
        get_success_data(
            api.settle_claim(
                c["id"],
                {"amount_cents": 150000000,
                 "expected_claim_version": c["version"]},
                RISK,
            )
        )
        rows, _ = validate_paginated(api.list_claim_settlements(c["id"], RISK))
        assert len(rows) == 1
        s = rows[0]
        assert s["manager_share_cents"] == 100000000, (
            f"manager share must be capped at 100000000, got {s['manager_share_cents']}"
        )
        assert s["owner_share_cents"] == 50000000
        assert_settlement_invariants(s)


class TestSettlementImmutability:
    def test_claim_settlement_has_no_update_endpoint_immutable(self, api):
        """PRD §2.5: "`ClaimSettlement` is the single exception: it is created
        once, at the moment a claim settles, and never mutated thereafter. It
        carries only `id` and `created_at`; both `updated_at` and `version`
        are absent from it."

        Design: Corner/entities/claim_settlement_has_no_update_endpoint_immutable
        """
        fx = setup_managed_property(legal_name="Imm Owner LP",
                                    property_name="Imm Property", unit_count=20)
        prop = fx["prop"]
        c = create_claim_under_review(
            prop, claim_type="RESIDENT_INCIDENT", reserved_amount_cents=0,
            indemnified_by="OWNER", incident_date="2026-09-03T00:00:00Z",
        )
        get_success_data(
            api.settle_claim(
                c["id"],
                {"amount_cents": 1000000,
                 "expected_claim_version": c["version"]},
                RISK,
            )
        )
        rows, _ = validate_paginated(api.list_claim_settlements(c["id"], RISK))
        assert len(rows) == 1
        s = rows[0]
        assert_claim_settlement(s)
        assert s["amount_cents"] == 1000000
        assert s["manager_share_cents"] == 0
        assert s["owner_share_cents"] == 1000000


class TestClaimSettleOcc:
    def test_occ_stale_version_on_claim_settle(self, api):
        """PRD §2.8: "Settling a claim requires `expected_claim_version`,
        carrying the `version` of the `Claim` the client last read. Settlement
        terms depend on the claim's current reserve and indemnification
        fields; if those changed after the client's read, the settle is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/occ_stale_version_on_claim_settle
        """
        fx = setup_managed_property(legal_name="OCC2 Owner LP",
                                    property_name="OCC2 Property", unit_count=10)
        prop = fx["prop"]
        c = create_claim_under_review(
            prop, claim_type="RESIDENT_INCIDENT", reserved_amount_cents=0,
            indemnified_by="OWNER", incident_date="2026-09-04T00:00:00Z",
        )
        current_v = c["version"]

        stale = api.settle_claim(
            c["id"],
            {"amount_cents": 500000, "expected_claim_version": current_v - 1},
            RISK,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(
            api.settle_claim(
                c["id"],
                {"amount_cents": 500000, "expected_claim_version": current_v},
                RISK,
            )
        )
        assert fresh["status"] == "SETTLED"

        rows, _ = validate_paginated(api.list_claim_settlements(c["id"], RISK))
        assert len(rows) == 1, "the stale attempt must not create a settlement row"
        assert rows[0]["amount_cents"] == 500000


class TestIncidentOutsideTerm:
    def test_manager_indemnified_out_of_term_incident_rejected(self, api):
        """PRD §3.9: "when `indemnified_by` is `MANAGER`, the `incident_date`
        must fall within the agreement's term, from `effective_date` through
        `term_end_date` inclusive (the manager indemnifies only incidents
        inside the term; an out-of-term incident is rejected with
        `ERR_INCIDENT_OUTSIDE_TERM`)".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_claim_settle_and_vendor_review
        """
        fx = setup_managed_property(legal_name="Prio Two LP",
                                    property_name="Prio Two Property", unit_count=70)
        prop = fx["prop"]
        # Incident BEFORE effective_date 2026-08-01 -> outside the term.
        c = create_claim_under_review(
            prop, claim_type="EMPLOYMENT", reserved_amount_cents=0,
            indemnified_by="MANAGER", incident_date="2026-07-01T00:00:00Z",
        )
        resp = api.settle_claim(
            c["id"],
            {"amount_cents": 1000000, "expected_claim_version": c["version"]},
            RISK,
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_OUTSIDE_TERM)

    def test_vendor_review_completion_blocked_by_pending_contract(self, api, pm_headers, acct_headers):
        """PRD §3.3: "Completing vendor review is blocked while any contract
        for the property remains `PENDING` — the attempt is rejected with
        `ERR_VENDOR_CONTRACTS_PENDING` — and otherwise moves the onboarding
        to `READY`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_claim_settle_and_vendor_review
        """
        owner = setup_owner(legal_name="Prio Two B LP")
        prop = setup_property(owner, name="Prio Two B", unit_count=40)
        ob = start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")
        setup_resident(prop, unit_label="10B", full_name="Res TenB",
                       lease_end_date="2027-08-31T00:00:00Z")
        get_success_data(
            api.create_vendor_contract(
                prop["id"],
                {"vendor_name": "PestCo", "service_type": "PEST",
                 "monthly_cost_cents": 12000,
                 "start_date": "2026-09-01T00:00:00Z",
                 "end_date": "2027-08-31T00:00:00Z"},
                acct_headers,
            )
        )
        get_success_data(api.verify_resident_data(ob["id"], acct_headers))
        get_success_data(
            api.import_ledger(
                ob["id"],
                {"deposits_received_cents": 0, "prepaid_rent_cents": 0,
                 "delinquency_cents": 0},
                acct_headers,
            )
        )
        get_success_data(api.begin_vendor_review(ob["id"], acct_headers))

        resp = api.complete_vendor_review(ob["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_VENDOR_CONTRACTS_PENDING)


class TestOpenClaimsBlockExit:
    def test_error_open_claims_block_termination_completion(self, api, pm_headers):
        """PRD §3.7: "no `Claim` for the property is in `OPEN` or
        `UNDER_REVIEW` — open claims block the exit with
        `ERR_OPEN_CLAIMS_BLOCK_EXIT`".

        Design: Corner/errors/error_open_claims_block_termination_completion
        """
        fx = setup_managed_property(legal_name="Claims Owner LP",
                                    property_name="Claims Property", unit_count=20)
        owner, prop, ag = fx["owner"], fx["prop"], fx["agreement"]
        hdrs = make_owner_rep_headers(owner["id"])
        c = get_success_data(
            api.create_claim(
                prop["id"],
                create_claim_payload(claim_type="EMPLOYMENT",
                                     reserved_amount_cents=0,
                                     indemnified_by="OWNER",
                                     incident_date="2026-09-02T00:00:00Z"),
                RISK,
            )
        )
        get_success_data(
            api.terminate_agreement(ag["id"], {"terminated_reason": "CAUSE"}, hdrs)
        )

        resp = api.complete_termination(ag["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS_BLOCK_EXIT)

        # Zero-reserve OPEN claim may close directly (PRD §3.9).
        get_success_data(api.close_claim(c["id"], RISK))
        done = validate_success(api.complete_termination(ag["id"], pm_headers))
        assert done["status"] == "TERMINATED"
