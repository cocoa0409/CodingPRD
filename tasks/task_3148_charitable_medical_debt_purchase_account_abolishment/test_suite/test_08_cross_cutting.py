"""Cross-cutting layers: optimistic concurrency control and the common
version-increment discipline."""
from test_helpers import (
    ApiErrorId,
    create_contract_payload,
    create_org,
    get_success_data,
    make_contract_manager_headers,
    make_donor_relations_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    set_clock,
    setup_standard_priced,
    setup_standard_settled,
    stage_batch,
    validate_error,
    validate_success,
)
class TestOptimisticConcurrency:
    def test_contract_create_occ_stale_version(self, api):
        """PRD §2.8: "Creating a purchase contract against a portfolio requires
        the request to carry `expected_portfolio_version`, set to the
        portfolio's `version` as the client last observed it. If the portfolio's
        current `version` no longer matches — for instance because a re-price
        recomputed the quote since the client read it — the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.4: "Creation snapshots the portfolio's current
        `quoted_price_cents` into `contract_price_cents`, version-pinned, and
        the contract is born `DRAFT`."

        Design: Corner/cross_cutting_layers/contract_create_occ_stale_version
        """
        ctx = setup_standard_priced()
        pf = ctx["portfolio"]
        cm = make_contract_manager_headers()
        # Version observed before the screening run and price quote advanced it
        # (submit bumps the fresh portfolio's version from 1 to 2).
        stale_version = 2
        assert pf["version"] > stale_version
        resp = api.create_contract(
            pf["id"],
            create_contract_payload(stale_version),
            cm,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        # A fresh read succeeds and pins the current quote.
        resp = api.create_contract(
            pf["id"],
            create_contract_payload(pf["version"]),
            cm,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["contract_price_cents"] == 37500

    def test_batch_create_occ_stale_version(self, api):
        """PRD §2.8: "Creating an abolishment batch against a portfolio likewise
        requires `expected_portfolio_version`. A mismatch with the portfolio's
        current `version` — for instance because another batch's finalize
        changed the abolished totals — is rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the client to re-read the portfolio before composing
        the batch."
        PRD §3.6: "The batch is born `STAGING` with `account_count` set to the
        length of the list and `total_abolished_cents` computed as the sum, over
        the listed accounts, of each account's final relief value — its
        `balance_cents` plus `accrued_adjustment_cents`."

        Design: Corner/cross_cutting_layers/batch_create_occ_stale_version
        """
        fin = make_finance_officer_headers()
        settled = setup_standard_settled()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "General Relief Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                make_donor_relations_headers(),
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 1600000},
                make_donor_relations_headers(),
            )
        )
        get_success_data(api.receive_donation(donation["id"], fin))
        portfolio = settled["portfolio"]
        a1, a2 = settled["accounts"][0]["id"], settled["accounts"][1]["id"]
        pre_finalize_version = portfolio["version"]
        batch1 = stage_batch(portfolio, [a1])
        get_success_data(api.commit_abolishment_batch(batch1["id"], fin))
        get_success_data(api.finalize_abolishment_batch(batch1["id"], fin))
        # The finalize advanced the portfolio version; the pre-finalize version
        # is now stale.
        resp = api.create_abolishment_batch(
            portfolio["id"],
            {
                "account_ids": [a2],
                "expected_portfolio_version": pre_finalize_version,
            },
            fin,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        # A fresh read succeeds.
        current = get_success_data(api.get_portfolio(portfolio["id"], fin))
        resp = api.create_abolishment_batch(
            portfolio["id"],
            {
                "account_ids": [a2],
                "expected_portfolio_version": current["version"],
            },
            fin,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "STAGING"
        assert data["total_abolished_cents"] == 500000


class TestCommonFieldVersioning:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` — an integer starting at 1 that increments on
        every mutation of the resource."
        PRD §3.1: "When a seller relationship sours, the administrator may
        suspend the organization — a transition allowed only from `ACTIVE`,
        failing with `ERR_INVALID_STATE` otherwise."
        PRD §3.1: "Reactivation returns a `SUSPENDED` organization to `ACTIVE`
        and restores normal operations."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        set_clock()
        admin = make_platform_admin_headers()
        org = create_org()
        assert org["version"] == 1
        resp = api.suspend_source_organization(org["id"], admin)
        data = validate_success(resp, 200)
        assert data["version"] == 2
        assert data["status"] == "SUSPENDED"
        resp = api.reactivate_source_organization(org["id"], admin)
        data = validate_success(resp, 200)
        assert data["version"] == 3
        assert data["status"] == "ACTIVE"
