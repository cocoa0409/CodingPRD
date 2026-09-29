"""Corner cases of the access grid: the grid is per endpoint rather than per
collection, InternalAudit writes exactly two settlement endpoints, and the
FintechPartner read surface is filtered by its own id."""
from test_helpers import (
    CO,
    IA,
    PO,
    RC,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_batch,
    create_diligence_review_payload,
    create_partner,
    file_complaint,
    get_success_data,
    make_fintech_partner_headers,
    oversight_summary,
    read_partner,
    reconcile_batch,
    setup_live_partner,
    validate_error,
    validate_paginated,
)


class TestEachRoleHoldsItsOwnExclusiveWrite:
    def test_the_grid_is_per_endpoint_so_one_collection_splits_across_two_roles(self):
        """It submits artefacts for decision but never decides them: diligence and marketing
        outcomes belong to `ComplianceOfficer`, and agreement and wind-down outcomes belong to
        `RiskCommittee`. It is also the only role permitted to advance the logical clock.

        Design: Corner/rbac/each_role_performs_its_own_exclusive_write_and_is_refused_every_other_roles
        """
        partner = create_partner(legal_name="Kingsmere Wallet Inc")
        partner_id = partner["id"]

        for headers, label in ((CO, "ComplianceOfficer"), (RC, "RiskCommittee")):
            validate_error(
                api_client.create_partner(
                    {
                        "legal_name": f"Forbidden {label} Inc",
                        "business_model": "PAYMENT_FACILITATION",
                        "funding_stage": "SEED",
                        "months_runway": 12,
                        "disclosed_complaints_per_10k": 1.00,
                        "end_user_account_count": 100,
                    },
                    headers,
                ),
                ApiErrorId.ERR_ROLE_NOT_PERMITTED,
                403,
            )
        _partners, partner_meta = validate_paginated(api_client.list_partners(PO))
        assert partner_meta["total_count"] == 1, (
            f"a refused write leaves no row behind, got {partner_meta['total_count']}"
        )

        review = get_success_data(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner_id, partner["version"]), PO
            )
        )
        validate_error(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, PO),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, RC),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert get_success_data(api_client.get_diligence_review(review["id"], PO))["status"] == (
            "DRAFT"
        ), "the review is still DRAFT, yet role authorisation is reported ahead of the state guard"

        get_success_data(api_client.submit_diligence_review(review["id"], {}, PO))
        passed = get_success_data(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO)
        )
        assert passed["status"] == "PASSED", "the very same call succeeds for the permitted role"

        current = read_partner(partner_id)
        agreement = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(partner_id, current["version"]), PO
            )
        )
        validate_error(
            api_client.submit_agreement_for_approval(agreement["id"], {}, CO),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        get_success_data(api_client.submit_agreement_for_approval(agreement["id"], {}, PO))
        validate_error(
            api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, PO),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        complaint = file_complaint(partner_id, headers=PO)
        assert complaint["status"] == "RECEIVED", (
            "the complaints collection is shared by three roles, so the officer may intake"
        )
        validate_error(
            api_client.assign_complaint_root_cause(
                complaint["id"],
                {
                    "root_cause_code": "FEE_CONFIG_ERROR",
                    "investigation_note": "the fee posting job ran twice",
                },
                PO,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        diagnosed = get_success_data(
            api_client.assign_complaint_root_cause(
                complaint["id"],
                {
                    "root_cause_code": "FEE_CONFIG_ERROR",
                    "investigation_note": "the fee posting job ran twice",
                },
                CO,
            )
        )
        assert diagnosed["root_cause_code"] == "FEE_CONFIG_ERROR", (
            "the same collection splits across two grid cells: intake is shared, diagnosis is not"
        )
        assert diagnosed["status"] == "ROOT_CAUSE_ASSIGNED"

        validate_error(
            api_client.set_current_utc("2026-08-10T00:00:00Z", RC),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )


class TestInternalAuditWritesExactlyTwoSettlementEndpoints:
    def test_audit_reconciles_and_clears_a_variance_and_is_refused_every_other_write(self):
        """It holds read access across every collection and exactly two settlement-integrity writes:
        it may reconcile a settlement batch, an ability it shares with `ProgramOfficer`, and it is
        the only role that may clear a settlement variance once one has been raised. It authors no
        partner, diligence, agreement, marketing, complaint, alert, cycle or wind-down record and
        never releases or claws back funds.

        Design: Corner/rbac/internal_audit_reads_everything_and_writes_only_the_two_reconciliation_endpoints
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Lowbridge Payments Inc",
                "business_model": "PAYMENT_FACILITATION",
                "end_user_account_count": 5_000,
            },
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]
        batch = create_batch(
            partner_id,
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )

        opened = reconcile_batch(batch["id"], 8_200_000, headers=IA)
        assert opened["reconciliation_status"] == "VARIANCE_OPEN", (
            "the first of the two audit writes succeeds"
        )
        assert opened["variance_cents"] == 100_000, opened["variance_cents"]

        cleared = get_success_data(
            api_client.clear_settlement_variance(
                batch["id"],
                {
                    "variance_adjustment_cents": 100_000,
                    "root_cause_note": "an interchange file posted after the partner cut the batch",
                },
                IA,
            )
        )
        assert cleared["reconciliation_status"] == "VARIANCE_CLEARED", (
            "clearing a variance is the one write reserved to audit alone"
        )

        validate_error(
            api_client.fund_settlement_batch(
                batch["id"], {"funding_reference": "WIRE-IA-1"}, IA
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api_client.create_complaint(
                {
                    "partner_id": partner_id,
                    "channel": "EMAIL",
                    "category": "FEES",
                    "severity": "LOW",
                    "received_at": "2026-07-10T00:00:00Z",
                    "narrative": "an auditor may not lodge a consumer complaint",
                },
                IA,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api_client.create_cycle(
                {
                    "cycle_label": "2026-09",
                    "period_start": "2026-09-01T00:00:00Z",
                    "period_end": "2026-10-01T00:00:00Z",
                },
                IA,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api_client.clawback_settlement_batch(
                batch["id"], {"clawback_reason": "RECONCILIATION_ERROR"}, IA
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        audit_summary = get_success_data(api_client.get_oversight_summary(partner_id, IA))
        assert audit_summary["partner_id"] == partner_id, (
            "the bank-internal computed read is open to third-line assurance"
        )
        _plans, plan_meta = validate_paginated(
            api_client.list_wind_down_plans(IA, {"partner_id": partner_id})
        )
        assert plan_meta["total_count"] == 0, "an empty collection still reads for audit"
        _entries, entry_meta = validate_paginated(
            api_client.list_ledger_entries(IA, {"partner_id": partner_id})
        )
        assert entry_meta["total_count"] == 2, (
            f"the two seeded custody movements read for audit, got {entry_meta['total_count']}"
        )


class TestFintechPartnerReadSurfaceIsScoped:
    def test_a_shared_list_filters_to_the_callers_own_rows_while_a_foreign_row_read_is_refused(self):
        """The same rule confines partner-visible list and read endpoints to rows bearing its own
        `partner_id`. It cannot read the bank-internal oversight summary for any partner, cannot
        decide or approve anything, cannot move program funds, and can never see another partner's
        data.

        Design: Corner/rbac/the_fintech_partner_read_surface_is_scoped_to_its_own_rows_on_every_shared_list
        """
        partner_a = create_partner(legal_name="Marlowe Cash Inc")
        partner_b = create_partner(legal_name="Netherby Wallet Inc")
        a_id, b_id = partner_a["id"], partner_b["id"]
        fp_a = make_fintech_partner_headers(a_id)
        fp_b = make_fintech_partner_headers(b_id)

        complaint_a = file_complaint(a_id, channel="EMAIL")
        complaint_b = file_complaint(b_id, channel="EMAIL")
        batch_a = create_batch(a_id)
        batch_b = create_batch(b_id)

        own_complaints, own_meta = validate_paginated(api_client.list_complaints(fp_a))
        assert own_meta["total_count"] == 1, (
            "the shared list is filtered to the caller's own rows rather than refused, got "
            f"{own_meta['total_count']}"
        )
        assert [row["id"] for row in own_complaints] == [complaint_a["id"]]

        _bank_view, bank_meta = validate_paginated(api_client.list_complaints(CO))
        assert bank_meta["total_count"] == 2, (
            f"the identical unfiltered request shows a bank role both partners, got {bank_meta}"
        )

        validate_error(
            api_client.get_complaint(complaint_b["id"], fp_a),
            ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api_client.get_partner(b_id, fp_a),
            ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION,
            403,
        )

        own_partners, own_partner_meta = validate_paginated(api_client.list_partners(fp_a))
        assert own_partner_meta["total_count"] == 1, (
            f"the partner list collapses to the caller's own record, got {own_partner_meta}"
        )
        assert own_partners[0]["id"] == a_id

        a_batches, a_batch_meta = validate_paginated(api_client.list_settlement_batches(fp_a))
        assert a_batch_meta["total_count"] == 1
        assert a_batches[0]["id"] == batch_a["id"]
        b_batches, b_batch_meta = validate_paginated(api_client.list_settlement_batches(fp_b))
        assert b_batch_meta["total_count"] == 1, (
            "the identical request scopes purely by X-User-ID, got "
            f"{b_batch_meta['total_count']}"
        )
        assert b_batches[0]["id"] == batch_b["id"]
        assert batch_a["id"] != batch_b["id"]

        validate_error(
            api_client.get_oversight_summary(a_id, fp_a),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert oversight_summary(a_id)["partner_id"] == a_id, (
            "role authorisation is reported ahead of partner scope, so even the partner's own id "
            "is refused on the summary while a bank role reads it"
        )
