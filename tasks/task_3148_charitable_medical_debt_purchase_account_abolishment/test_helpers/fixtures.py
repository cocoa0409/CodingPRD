"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database,
so each fixture builds its preconditions from scratch using only public
endpoints. Setup calls use ``get_success_data`` so a failed step raises a
clear "Setup failed" error instead of a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_account_payload,
    create_contract_payload,
    create_donor_campaign_payload,
    create_donation_payload,
    create_eligibility_policy_payload,
    create_portfolio_payload,
    create_source_organization_payload,
)
from .test_users import (
    make_contract_manager_headers,
    make_donor_relations_headers,
    make_eligibility_officer_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    make_portfolio_analyst_headers,
)

# Default segregation-of-duties pair: the contract executor and settler
# must carry different X-User-ID values (PRD §3.4).
EXECUTOR_USER_ID = "cm-1"
SETTLER_USER_ID = "fin-9"


# ---------------------------------------------------------------------------
# Standard account file: A1 (income 5000000, +50000 adjustment, reported to
# EQUIFAX), A2 (income exactly at the x4.0 size-1 cap of 6260000), and A3
# (income 9999999, ineligible). Under the standard x4.0 policy A1 and A2 are
# ELIGIBLE; A3 is INELIGIBLE.
# ---------------------------------------------------------------------------
def standard_accounts():
    return [
        create_account_payload(
            "A1",
            debtor_household_key="H1",
            debtor_zip="75001",
            annual_income_cents=5000000,
            balance_cents=1000000,
            accrued_adjustment_cents=50000,
            reported_to_bureau=True,
            bureau_name="EQUIFAX",
            mailing_address="1 Main St",
        ),
        create_account_payload(
            "A2",
            debtor_household_key="H1",
            debtor_zip="75002",
            annual_income_cents=6260000,
            balance_cents=500000,
            accrued_adjustment_cents=0,
            mailing_address="2 Oak Ave",
        ),
        create_account_payload(
            "A3",
            debtor_household_key="H2",
            debtor_zip="75003",
            annual_income_cents=9999999,
            balance_cents=700000,
            accrued_adjustment_cents=0,
            mailing_address="3 Pine Rd",
        ),
    ]


def set_clock(to_iso8601=CLOCK_START_ISO):
    """Advance the logical clock; every subsequent server stamp uses it."""
    return get_success_data(
        api_client.set_clock(to_iso8601, make_platform_admin_headers())
    )


def create_org(**overrides):
    payload = create_source_organization_payload(**overrides)
    return get_success_data(
        api_client.create_source_organization(payload, make_platform_admin_headers())
    )


def create_policy(**overrides):
    payload = create_eligibility_policy_payload(**overrides)
    return get_success_data(
        api_client.create_eligibility_policy(
            payload, make_eligibility_officer_headers()
        )
    )


def create_active_policy(**overrides):
    policy = create_policy(**overrides)
    get_success_data(
        api_client.activate_eligibility_policy(
            policy["id"], make_eligibility_officer_headers()
        )
    )
    return policy


def create_portfolio_with_accounts(org_id, accounts=None, **portfolio_overrides):
    """DRAFT portfolio plus a bulk import; returns (portfolio, accounts)."""
    portfolio = get_success_data(
        api_client.create_portfolio(
            create_portfolio_payload(org_id, **portfolio_overrides),
            make_portfolio_analyst_headers(),
        )
    )
    if accounts is None:
        accounts = standard_accounts()
    imported = get_success_data(
        api_client.import_accounts(
            portfolio["id"], accounts, make_portfolio_analyst_headers()
        )
    )
    return portfolio, imported


def create_submitted_portfolio(org_id, accounts=None, **portfolio_overrides):
    """Portfolio imported and submitted. Returns (portfolio, accounts)."""
    portfolio, imported = create_portfolio_with_accounts(
        org_id, accounts=accounts, **portfolio_overrides
    )
    get_success_data(
        api_client.submit_portfolio(portfolio["id"], make_portfolio_analyst_headers())
    )
    return portfolio, imported


def create_priced_portfolio(org_id, policy_id, accounts=None, **portfolio_overrides):
    """Portfolio submitted, screened, and price-quoted (PRICED).

    Returns (portfolio_dict_at_PRICED, accounts, screening_run).
    """
    portfolio, imported = create_submitted_portfolio(
        org_id, accounts=accounts, **portfolio_overrides
    )
    run = get_success_data(
        api_client.create_screening_run(
            portfolio["id"], policy_id, make_eligibility_officer_headers()
        )
    )
    get_success_data(
        api_client.execute_screening_run(run["id"], make_eligibility_officer_headers())
    )
    priced = get_success_data(
        api_client.price_quote_portfolio(
            portfolio["id"], make_portfolio_analyst_headers()
        )
    )
    return priced, imported, run


def create_draft_contract(portfolio_at_priced, **contract_overrides):
    """DRAFT contract pinning the portfolio's current quote."""
    return get_success_data(
        api_client.create_contract(
            portfolio_at_priced["id"],
            create_contract_payload(
                portfolio_at_priced["version"], **contract_overrides
            ),
            make_contract_manager_headers(),
        )
    )


def create_executed_contract(portfolio_at_priced, **contract_overrides):
    """DRAFT -> EXECUTED contract. Portfolio advances to CONTRACTED."""
    contract = create_draft_contract(portfolio_at_priced, **contract_overrides)
    get_success_data(
        api_client.execute_contract(
            contract["id"],
            make_contract_manager_headers(EXECUTOR_USER_ID),
        )
    )
    return contract


def create_settled_portfolio(org_id, policy_id, accounts=None, **portfolio_overrides):
    """Full pipeline through settlement.

    Returns (portfolio_dict_at_SETTLED, accounts, contract).
    """
    priced, imported, _run = create_priced_portfolio(
        org_id, policy_id, accounts=accounts, **portfolio_overrides
    )
    contract = create_executed_contract(priced)
    get_success_data(
        api_client.settle_contract(
            contract["id"], make_finance_officer_headers(SETTLER_USER_ID)
        )
    )
    settled = get_success_data(
        api_client.get_portfolio(priced["id"], make_finance_officer_headers())
    )
    return settled, imported, contract


def setup_standard_priced():
    """Org + ACTIVE policy + standard portfolio through PRICED.

    Returns dict(org, policy, portfolio, accounts, run).
    """
    set_clock()
    org = create_org()
    policy = create_active_policy()
    portfolio, accounts, run = create_priced_portfolio(org["id"], policy["id"])
    return {
        "org": org,
        "policy": policy,
        "portfolio": portfolio,
        "accounts": accounts,
        "run": run,
    }


def setup_standard_settled():
    """Standard portfolio through settlement.

    Returns dict(org, policy, portfolio, accounts, contract). At this point
    A1 and A2 are PURCHASED and A3 is EXCLUDED.
    """
    set_clock()
    org = create_org()
    policy = create_active_policy()
    portfolio, accounts, contract = create_settled_portfolio(org["id"], policy["id"])
    return {
        "org": org,
        "policy": policy,
        "portfolio": portfolio,
        "accounts": accounts,
        "contract": contract,
    }


def create_campaign(**overrides):
    return get_success_data(
        api_client.create_donor_campaign(
            create_donor_campaign_payload(**overrides),
            make_donor_relations_headers(),
        )
    )


def create_received_donation(campaign_id, gross_cents, **overrides):
    """Pledged donation immediately received; returns the RECEIVED donation."""
    donation = get_success_data(
        api_client.create_donation(
            campaign_id,
            create_donation_payload(gross_cents=gross_cents, **overrides),
            make_donor_relations_headers(),
        )
    )
    return get_success_data(
        api_client.receive_donation(
            donation["id"], make_finance_officer_headers()
        )
    )


def setup_funded_campaign(gross_cents=1600000, **campaign_overrides):
    """GENERAL campaign holding one received donation. Returns (campaign, donation)."""
    campaign = create_campaign(**campaign_overrides)
    donation = create_received_donation(campaign["id"], gross_cents)
    refreshed = get_success_data(
        api_client.get_donor_campaign(campaign["id"], make_finance_officer_headers())
    )
    return refreshed, donation


def stage_batch(portfolio, account_ids):
    """Stage an abolishment batch against the portfolio's current version."""
    return get_success_data(
        api_client.create_abolishment_batch(
            portfolio["id"],
            {
                "account_ids": list(account_ids),
                "expected_portfolio_version": portfolio["version"],
            },
            make_finance_officer_headers(),
        )
    )


def setup_committed_batch(accounts=None, gross_cents=1600000):
    """Standard settled chain plus one funded campaign and a COMMITTED batch.

    Default batch covers [A1, A2] (total 1050000 + 500000 = 1550000) funded
    by a GENERAL campaign with net 1553600. Returns dict(org, policy,
    portfolio, accounts, contract, campaign, donation, batch).
    """
    ctx = setup_standard_settled()
    campaign, donation = setup_funded_campaign(gross_cents)
    selected = accounts or [ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]]
    current = get_success_data(
        api_client.get_portfolio(
            ctx["portfolio"]["id"], make_finance_officer_headers()
        )
    )
    batch = stage_batch(current, selected)
    get_success_data(
        api_client.commit_abolishment_batch(batch["id"], make_finance_officer_headers())
    )
    batch = get_success_data(
        api_client.get_abolishment_batch(batch["id"], make_finance_officer_headers())
    )
    ctx.update({"campaign": campaign, "donation": donation, "batch": batch})
    return ctx


def setup_finalized_batch(accounts=None, gross_cents=1600000):
    """Standard chain through batch finalization.

    Default batch covers [A1, A2]: A1 ends ABOLISHED + DELETION_REQUESTED
    with an auto-SUBMITTED deletion request; A2 ends ABOLISHED +
    NOT_REPORTED. Returns dict(..., batch, letters, cdrs, tax_records).
    """
    ctx = setup_committed_batch(accounts=accounts, gross_cents=gross_cents)
    get_success_data(
        api_client.finalize_abolishment_batch(
            ctx["batch"]["id"], make_finance_officer_headers()
        )
    )
    batch = get_success_data(
        api_client.get_abolishment_batch(
            ctx["batch"]["id"], make_finance_officer_headers()
        )
    )
    letters = get_success_data(
        api_client.list_notification_letters(
            make_donor_relations_headers(), params={"batch_id": batch["id"]}
        )
    )
    cdrs = get_success_data(
        api_client.list_credit_deletion_requests(
            make_donor_relations_headers(), params={"batch_id": batch["id"]}
        )
    )
    portfolio = get_success_data(
        api_client.get_portfolio(
            ctx["portfolio"]["id"], make_finance_officer_headers()
        )
    )
    ctx.update(
        {
            "batch": batch,
            "letters": letters,
            "cdrs": cdrs,
            "portfolio": portfolio,
        }
    )
    return ctx


def get_account(account_id):
    return get_success_data(
        api_client.get_account(account_id, make_finance_officer_headers())
    )


def get_portfolio(portfolio_id):
    return get_success_data(
        api_client.get_portfolio(portfolio_id, make_finance_officer_headers())
    )


def get_campaign(campaign_id):
    return get_success_data(
        api_client.get_donor_campaign(campaign_id, make_finance_officer_headers())
    )
