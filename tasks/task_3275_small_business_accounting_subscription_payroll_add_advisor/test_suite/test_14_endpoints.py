"""Corner / endpoints — feature-flag gating, invoice filter, OCC on plan
change.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    add_category,
    create_company,
    create_plus_plan,
    create_primary_admin,
    create_simple_start_plan,
    get_subscription,
    issue_invoice_now,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestCategorizationRulesTierGated:
    def test_post_categorization_rules_tier_gated_feature_flag(self, client):
        """PRD 3.1: "Creating a categorization rule — and rule-based
        auto-categorization generally — requires `feature_bank_rules` to be
        true on the company's current plan; a plan without it leaves
        customers with manual categorization only, and any rule-path attempt
        is rejected with `ERR_FEATURE_NOT_IN_TIER` (HTTP 400), which also
        sets the subscription's `pending_upgrade_prompt` flag."

        Design: Corner/endpoints/post_categorization_rules_tier_gated_feature_flag
        """
        reset_clock(client)
        ss_plan = create_simple_start_plan(client)
        company = create_company(client, ss_plan["id"], legal_name="SS Co")
        admin = create_primary_admin(client, company["id"], email="adm@ss.example")
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])
        activate_subscription(client, company["id"], admin["id"])
        category = add_category(client, company["id"], admin["id"],
                                  name="SSCat", tax_line="T")

        response = client.create_categorization_rule(
            company["id"],
            f.create_rule_payload(
                company["id"], category["id"],
                rule_name="R", match_field="PAYEE_CONTAINS",
                match_value="X", priority=1, auto_apply=True,
            ),
            headers=admin_headers,
        )
        validate_error(response, E.ERR_FEATURE_NOT_IN_TIER)


class TestInvoiceListFilter:
    def test_get_invoices_list_filter_by_status(self, client):
        """PRD 2.3: "Individual list endpoints may additionally declare
        filter query parameters (for example `user_status`, `txn_status`,
        `invoice_status`, ...), each narrowing the result set to rows
        matching the given value."

        Design: Corner/endpoints/get_invoices_list_filter_by_status
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Filter Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]
        subscription = scenario["subscription"]

        # Issue + pay the first invoice (the activation DRAFT covering the
        # first billing period, PRD 3.3/3.5).
        invoice1 = issue_invoice_now(client, company["id"], subscription["id"])
        pay1 = client.pay_invoice(company["id"], invoice1["id"], headers=admin_headers)
        assert pay1.status_code in (200, 201), pay1.text

        # Advance the clock to the second billing date (period 2 ends Oct 31)
        # so the system generates period 2's DRAFT, then issue it.
        set_clock(client, "2026-10-31T00:00:00Z")
        invoice2 = issue_invoice_now(client, company["id"], subscription["id"])
        # Filter by PAID — exactly one row.
        paid_response = client.list_company_invoices(
            company["id"], headers=PLATFORM_ADMIN, params={"invoice_status": "PAID"}
        )
        paid_rows, _meta = validate_paginated(paid_response)
        paid_ids = [row["id"] for row in paid_rows]
        assert paid_ids == [invoice1["id"]]

        # Unfiltered — both invoices.
        all_response = client.list_company_invoices(
            company["id"], headers=PLATFORM_ADMIN
        )
        all_rows, _ = validate_paginated(all_response)
        all_ids = sorted(row["id"] for row in all_rows)
        assert all_ids == sorted([invoice1["id"], invoice2["id"]])


class TestOCCStaleVersion:
    def test_occ_stale_version_returns_412(self, client):
        """PRD 2.6: "A plan change on a subscription must carry
        `expected_subscription_version` matching the subscription's current
        `version`; if another writer has advanced the version since the
        caller last read the subscription — by changing the plan, or by a
        billing transfer completing — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_returns_412
        """
        reset_clock(client)
        ss_plan = create_simple_start_plan(client)
        plus_plan = create_plus_plan(client)
        company = create_company(client, ss_plan["id"], legal_name="OCC Co")
        admin = create_primary_admin(client, company["id"], email="adm@occ.example")
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])

        subscription = get_subscription(client, company["id"])
        original_version = subscription["version"]

        # First change_plan with the current version succeeds and bumps it.
        first = client.change_subscription_plan(
            company["id"],
            {"plan_id": plus_plan["id"],
             "expected_subscription_version": original_version},
            headers=admin_headers,
        )
        assert first.status_code in (200, 201), (
            "first change_plan must succeed: {0}".format(first.text)
        )

        # Second change_plan with the same stale version is rejected.
        second = client.change_subscription_plan(
            company["id"],
            {"plan_id": ss_plan["id"],
             "expected_subscription_version": original_version},
            headers=admin_headers,
        )
        validate_error(second, E.ERR_STALE_VERSION)
