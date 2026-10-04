"""Error trigger conditions: tax-relief assessment bounds and manual
credit-deletion-request gates."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_compliance_auditor_headers,
    setup_finalized_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTaxReliefAssessment:
    def test_exclusion_over_relief_rejected_and_full_exclusion_exempt(self, api):
        """PRD §3.8: "A `ComplianceAuditor` assesses the record by declaring an
        `insolvency_exclusion_cents` — the amount excluded from income under the
        insolvency rules — which must be at least zero and at most the full
        `relief_amount_cents`, with any out-of-range value rejected as
        `ERR_INVALID_AMOUNT`."
        PRD §3.8: "when the exclusion equals the relief amount in full, the
        reportable remainder is zero, no filing is required, and the record
        moves to terminal `EXEMPT`."

        Design: Corner/errors/tax_assess_exclusion_over_relief_rejected
        """
        ctx = setup_finalized_batch()
        a1 = ctx["accounts"][0]
        auditor = make_compliance_auditor_headers()
        rows, _meta = validate_paginated(
            api.list_tax_relief_records(auditor, params={"account_id": a1["id"]})
        )
        assert len(rows) == 1
        record = rows[0]
        assert record["status"] == "PENDING"
        assert record["relief_amount_cents"] == 1050000
        resp = api.assess_tax_relief_record(record["id"], 1050001, auditor)
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT, 422)
        fetched = get_success_data(api.get_tax_relief_record(record["id"], auditor))
        assert fetched["status"] == "PENDING"
        resp = api.assess_tax_relief_record(record["id"], 1050000, auditor)
        data = validate_success(resp, 200)
        assert data["status"] == "EXEMPT"
        assert data["reportable_amount_cents"] == 0


class TestManualCreditDeletionRequestGates:
    def test_manual_cdr_on_not_reported_account_rejected(self, api):
        """PRD §3.8: "manual creation is permitted only for an account whose
        lifecycle is `ABOLISHED` (`ERR_ACCOUNT_NOT_ABOLISHED`) and whose
        `bureau_status` is `REPORTED` (`ERR_BUREAU_NOT_REPORTED`), and it
        produces a `DRAFT` request with no `batch_id`."

        Design: Corner/errors/manual_cdr_on_not_reported_account_rejected
        """
        ctx = setup_finalized_batch()
        a2 = ctx["accounts"][1]  # never reported to a bureau
        auditor = make_compliance_auditor_headers()
        account = get_success_data(api.get_account(a2["id"], auditor))
        assert account["lifecycle_status"] == "ABOLISHED"
        assert account["bureau_status"] == "NOT_REPORTED"
        resp = api.create_credit_deletion_request(a2["id"], "EQUIFAX", auditor)
        validate_error(resp, ApiErrorId.ERR_BUREAU_NOT_REPORTED, 409)
        rows, meta = validate_paginated(
            api.list_credit_deletion_requests(
                auditor, params={"account_id": a2["id"]}
            )
        )
        assert rows == [] and meta["total_count"] == 0
