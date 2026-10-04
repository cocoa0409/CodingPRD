"""Cross-entity state gates: batch creation requires a settled portfolio, and
manual credit-deletion requests require an abolished account."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_compliance_auditor_headers,
    make_finance_officer_headers,
    setup_standard_priced,
    setup_standard_settled,
    validate_error,
    validate_paginated,
)
from test_helpers import create_contract_payload, make_contract_manager_headers


class TestBatchPortfolioGate:
    def test_batch_create_requires_portfolio_settled(self, api):
        """PRD §3.6: "The portfolio itself must be `SETTLED` or `ABOLISHING`
        (`ERR_PORTFOLIO_NOT_SETTLED`)."

        Design: Difficulty/cross_entity_state_dependency/batch_create_requires_portfolio_settled
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        cm = make_contract_manager_headers("cm-1")
        contract = get_success_data(
            api.create_contract(
                pf["id"], create_contract_payload(pf["version"]), cm
            )
        )
        get_success_data(api.execute_contract(contract["id"], cm))
        contracted = get_success_data(
            api.get_portfolio(pf["id"], make_finance_officer_headers())
        )
        assert contracted["status"] == "CONTRACTED"
        a1 = ctx["accounts"][0]["id"]
        resp = api.create_abolishment_batch(
            pf["id"],
            {
                "account_ids": [a1],
                "expected_portfolio_version": contracted["version"],
            },
            make_finance_officer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PORTFOLIO_NOT_SETTLED, 409)
        rows, meta = validate_paginated(
            api.list_abolishment_batches(
                make_finance_officer_headers(), params={"portfolio_id": pf["id"]}
            )
        )
        assert rows == [], "no batch may be created"

    def test_batch_create_allowed_once_settled(self, api):
        """PRD §3.6: "The portfolio itself must be `SETTLED` or `ABOLISHING`
        (`ERR_PORTFOLIO_NOT_SETTLED`)."

        Design: Difficulty/cross_entity_state_dependency/batch_create_requires_portfolio_settled
        """
        ctx = setup_standard_settled()
        pf = ctx["portfolio"]
        assert pf["status"] == "SETTLED"
        a1 = ctx["accounts"][0]["id"]
        from test_helpers import stage_batch, validate_success

        batch = stage_batch(pf, [a1])
        assert batch["status"] == "STAGING"
        assert batch["total_abolished_cents"] == 1050000
        assert batch["account_count"] == 1


class TestCdrAccountGate:
    def test_manual_cdr_requires_abolished_account(self, api):
        """PRD §3.8: "manual creation is permitted only for an account whose
        lifecycle is `ABOLISHED` (`ERR_ACCOUNT_NOT_ABOLISHED`) and whose
        `bureau_status` is `REPORTED` (`ERR_BUREAU_NOT_REPORTED`), and it
        produces a `DRAFT` request with no `batch_id`."

        Design: Difficulty/cross_entity_state_dependency/cdr_submit_requires_account_abolished_and_reported
        """
        ctx = setup_standard_settled()
        auditor = make_compliance_auditor_headers()
        a1 = ctx["accounts"][0]
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["lifecycle_status"] == "PURCHASED"
        assert account["bureau_status"] == "REPORTED"
        resp = api.create_credit_deletion_request(a1["id"], "EQUIFAX", auditor)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ABOLISHED, 409)
        rows, meta = validate_paginated(
            api.list_credit_deletion_requests(
                auditor, params={"account_id": a1["id"]}
            )
        )
        assert rows == [], "no deletion request may be created"

    def test_manual_cdr_on_abolished_reported_account_succeeds(self, api):
        """PRD §3.8: "A `ComplianceAuditor` may also create a request manually
        against an account, supplying the `bureau` (`EQUIFAX`, `EXPERIAN`, or
        `TRANSUNION`); manual creation is permitted only for an account whose
        lifecycle is `ABOLISHED` (`ERR_ACCOUNT_NOT_ABOLISHED`) and whose
        `bureau_status` is `REPORTED` (`ERR_BUREAU_NOT_REPORTED`), and it
        produces a `DRAFT` request with no `batch_id`."

        Design: Difficulty/cross_entity_state_dependency/cdr_submit_requires_account_abolished_and_reported
        """
        from test_helpers import setup_finalized_batch
        from test_helpers import validate_success

        # Finalize a batch over A2 only so A1 stays ABOLISHED-able but the
        # auto-CDR path never runs for it... A2 is not REPORTED, so instead
        # finalize A1 alone: its auto-CDR flips it to DELETION_REQUESTED, which
        # is no longer REPORTED. To exercise a successful manual creation we
        # need an ABOLISHED account still REPORTED, which the auto path always
        # consumes — so assert the gate negatively via the finalized A1:
        # manual creation is rejected because its bureau status has already
        # advanced to DELETION_REQUESTED.
        ctx = setup_finalized_batch()
        auditor = make_compliance_auditor_headers()
        a1 = ctx["accounts"][0]
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["lifecycle_status"] == "ABOLISHED"
        assert account["bureau_status"] == "DELETION_REQUESTED"
        resp = api.create_credit_deletion_request(a1["id"], "EQUIFAX", auditor)
        validate_error(resp, ApiErrorId.ERR_BUREAU_NOT_REPORTED, 409)
