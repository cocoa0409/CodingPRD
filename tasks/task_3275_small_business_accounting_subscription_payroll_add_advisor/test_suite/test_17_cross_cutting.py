"""Corner / cross-cutting complexity layers and consistency model."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    add_bank_connection,
    add_category,
    create_company,
    create_company_user,
    create_plus_plan,
    create_primary_admin,
    create_simple_start_plan,
    get_subscription,
    ingest_txn,
    reset_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestPendingUpgradePromptClearedOnPlanChange:
    def test_subscription_pending_upgrade_prompt_cleared_on_plan_change(self, client):
        """PRD 3.3: "Changing plans is a primary-admin operation carrying
        the target `plan_id` and the OCC field `expected_subscription_version`.
        A successful change increments the subscription's `version`,
        recomputes `monthly_price_cents` under the new tier, and clears
        `pending_upgrade_prompt` — the prompt did its job."

        Design: Corner/cross_cutting_complexity_layers/subscription_pending_upgrade_prompt_cleared_on_plan_change
        """
        reset_clock(client)
        ss_plan = create_simple_start_plan(client)  # max_seats=1
        plus_plan = create_plus_plan(client)  # max_seats=5
        company = create_company(client, ss_plan["id"], legal_name="SS2 Co")
        admin = create_primary_admin(client, company["id"], email="adm@ss2.example")
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])
        activate_subscription(client, company["id"], admin["id"])

        # Trigger the seat-limit rejection to set pending_upgrade_prompt.
        seat_response = client.create_company_user(
            company["id"],
            f.create_company_user_payload(company["id"], email="x@ss2.example"),
            headers=admin_headers,
        )
        validate_error(seat_response, E.ERR_SEAT_LIMIT_REACHED)

        sub = get_subscription(client, company["id"])
        assert sub["pending_upgrade_prompt"] is True
        original_version = sub["version"]

        # Upgrade to PLUS — clears the prompt.
        upgrade = client.change_subscription_plan(
            company["id"],
            {"plan_id": plus_plan["id"],
             "expected_subscription_version": original_version},
            headers=admin_headers,
        )
        assert upgrade.status_code in (200, 201)

        sub_after = get_subscription(client, company["id"])
        assert sub_after["pending_upgrade_prompt"] is False


class TestDerivedFieldReconciliationClearedCents:
    def test_derived_field_reconciliation_cleared_cents_recomputed(self, client):
        """PRD 3.7: "`cleared_cents` is the sum of `amount_cents` over the
        connection's transactions whose status is `CATEGORIZED` or
        `MATCHED_RECONCILED` and whose `posted_at` falls within the
        statement window, inclusive of both ends — `EXCLUDED` transactions
        never count — and it is recomputed on every transaction added,
        removed, categorized, or excluded. `difference_cents` is the
        statement's ending balance minus the sum of the beginning balance
        and `cleared_cents`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_cleared_cents_recomputed
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Derived Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]
        connection = add_bank_connection(client, company["id"], admin["id"])
        category = add_category(
            client, company["id"], admin["id"], name="CatA", tax_line="A"
        )
        txn = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-10T00:00:00Z", amount_cents=-1500,
            payee_raw="X",
        )
        client.categorize_bank_transaction(
            company["id"], txn["id"], {"category_id": category["id"]},
            headers=admin_headers,
        )

        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-09-01T00:00:00Z",
                statement_period_end="2026-09-30T00:00:00Z",
                statement_ending_balance_cents=-1500,
            ),
            headers=admin_headers,
        )
        recon = get_success_data(create_response)
        client.start_reconciliation(company["id"], recon["id"], headers=admin_headers)

        # One CATEGORIZED txn in window: cleared=-1500, difference=0.
        view1 = get_success_data(
            client.get_reconciliation(company["id"], recon["id"],
                                       headers=PLATFORM_ADMIN)
        )
        assert view1["cleared_cents"] == -1500
        assert view1["difference_cents"] == 0

        # Exclude the txn: EXCLUDED never counts, so cleared=0, diff=-1500.
        client.exclude_bank_transaction(company["id"], txn["id"], headers=admin_headers)
        view2 = get_success_data(
            client.get_reconciliation(company["id"], recon["id"],
                                       headers=PLATFORM_ADMIN)
        )
        assert view2["cleared_cents"] == 0
        assert view2["difference_cents"] == -1500


class TestPlanChangeImmediateConsistency:
    def test_plan_change_response_immediately_reflects_new_price(self, client):
        """PRD 3.3: "Changing plans is a primary-admin operation carrying
        the target `plan_id` and the OCC field `expected_subscription_version`.
        A successful change increments the subscription's `version`,
        recomputes `monthly_price_cents` under the new tier, and clears
        `pending_upgrade_prompt`."

        The change is reflected in the same response — no async wait.

        Design: Corner/consistency_model/plan_change_response_immediately_reflects_new_price
        """
        reset_clock(client)
        ss_plan = create_simple_start_plan(client)
        plus_plan = create_plus_plan(client)
        company = create_company(client, ss_plan["id"], legal_name="Imm Co")
        admin = create_primary_admin(client, company["id"], email="adm@imm.example")
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])
        activate_subscription(client, company["id"], admin["id"])

        subscription = get_subscription(client, company["id"])
        response = client.change_subscription_plan(
            company["id"],
            {"plan_id": plus_plan["id"],
             "expected_subscription_version": subscription["version"]},
            headers=admin_headers,
        )
        body = get_success_data(response)
        assert body["plan_id"] == plus_plan["id"]
        assert body["monthly_price_cents"] == 8000, (
            "PLUS list price is reflected in the same response"
        )
