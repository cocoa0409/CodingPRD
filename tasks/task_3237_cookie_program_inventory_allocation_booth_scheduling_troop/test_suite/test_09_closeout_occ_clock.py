"""Season reconciliation/close-out, OCC-guarded writes, the logical clock, and
filtered listing channels."""
from test_helpers import (
    ApiErrorId,
    add_site,
    create_agreement,
    create_season,
    create_transfer,
    create_troop_with_account,
    get_account,
    get_agreement,
    get_season,
    make_council_admin_headers,
    set_clock,
    setup_reconciliation_season,
    setup_selling_season,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReconciliationGates:
    def test_reconciliation_gated_by_transfer_and_booth_states(self, api):
        """PRD §3.9: "The move is refused with `ERR_TRANSFER_IN_FLIGHT` while
        any transfer of the season sits in `REQUESTED`, `SHIPPER_SIGNED`, or
        `RECEIVER_SIGNED` — inventory in motion must land first — and with
        `ERR_BOOTH_REQUEST_PENDING` while any booth request remains `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/reconciliation_gated_by_transfer_and_booth_states
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(purchase_qty=600, confirm_qty=480,
                                   packages_per_case=12, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        create_transfer(
            season["id"], product["id"], 12, ctx["leader"],
            source_troop_id=ctx["troop"]["id"], dest_troop_id=troop2["id"],
        )
        resp = api.begin_reconciliation(season["id"], admin)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_IN_FLIGHT, 409)
        read = get_season(season["id"], admin=admin)
        assert read["status"] == "SELLING"

    def test_error_unresolved_uncollected_blocks_closeout(self, api):
        """PRD §3.9: "every troop account's `uncollected_amount_cents` must be
        zero or all of its `PENDING` agreements must already be `FORFEITED`,
        else `ERR_UNRESOLVED_UNCOLLECTED`"."

        Design: Corner/errors/error_unresolved_uncollected_blocks_closeout
        """
        admin = make_council_admin_headers()
        ctx = setup_reconciliation_season(purchase_qty=100, confirm_qty=80, admin=admin)
        season = ctx["season"]
        create_agreement(
            season["id"], ctx["troop"], leader=ctx["leader"],
            assigned_packages=10, paid_amount_cents=0,
        )
        resp = api.close_out_season(season["id"], admin)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_UNCOLLECTED, 409)
        read = get_season(season["id"], admin=admin)
        assert read["status"] == "RECONCILIATION"


class TestCloseOutWaterfall:
    def test_proceeds_settlement_offset_vs_payable_troop_domain(self, api):
        """PRD §3.9: "for each troop account, the offset is the lesser of the
        account's `proceeds_accrued_cents` and the positive part of its
        `balance_cents`; the offset is subtracted from `balance_cents`, and
        whatever proceeds remain beyond the offset become the
        `proceeds_payable_cents` owed back to the troop."

        Design: Difficulty/dual_variant_calc/proceeds_settlement_offset_vs_payable_troop_domain
        """
        admin = make_council_admin_headers()
        ctx = setup_reconciliation_season(purchase_qty=150, confirm_qty=120, admin=admin)
        season, account = ctx["season"], ctx["account"]
        close_out = validate_success(api.close_out_season(season["id"], admin))
        # Confirmed order: charge 120*600 = 72000; proceeds 120*100 = 12000.
        # proceeds < debt -> offset = 12000, payable = 0.
        assert close_out["total_proceeds_offset_cents"] == 12000
        acct = get_account(account["id"], admin=admin)
        assert acct["balance_cents"] == 60000
        read = get_season(season["id"], admin=admin)
        assert read["status"] == "CLOSED"

    def test_closeout_waterfall_mode_c_order_pinned_forfeit_then_offset(self, api):
        """PRD §3.9: "First, the forfeiture sweep: every agreement still
        `PENDING` or `DISPUTED` is moved to `FORFEITED` and its
        `outstanding_cents` posted as a charge against its troop's account.
        Second — only after those charges have landed — the proceeds waterfall:
        for each troop account, the offset is the lesser of the account's
        `proceeds_accrued_cents` and the positive part of its `balance_cents`;
        the offset is subtracted from `balance_cents`, and whatever proceeds
        remain beyond the offset become the `proceeds_payable_cents` owed back
        to the troop. Swapping this order would change balances whenever
        proceeds fall short of charges, which is why forfeiture always posts
        first."

        Design: Difficulty/combinatorial_formula/closeout_waterfall_mode_c_order_pinned_forfeit_then_offset
        """
        admin = make_council_admin_headers()
        ctx = setup_reconciliation_season(purchase_qty=150, confirm_qty=120, admin=admin)
        season, account = ctx["season"], ctx["account"]
        agreement = create_agreement(
            season["id"], ctx["troop"], leader=ctx["leader"],
            assigned_packages=10, paid_amount_cents=0,
        )
        # PRD §3.9 guard blocks close-out while uncollected is non-zero AND any
        # PENDING agreement is un-forfeited; a DISPUTED agreement (no PENDING
        # left) passes the guard and is forfeited by the sweep.
        validate_success(
            api.dispute_agreement(agreement["id"], {"reason": "contested"}, ctx["leader"])
        )
        close_out = validate_success(api.close_out_season(season["id"], admin))
        assert close_out["forfeited_agreements"] == 1
        assert close_out["total_proceeds_offset_cents"] == 12000
        acct = get_account(account["id"], admin=admin)
        # 72000 charge + 6000 forfeiture - 12000 proceeds offset, pinned order.
        assert acct["balance_cents"] == 66000
        ag = get_agreement(agreement["id"], admin=admin)
        assert ag["status"] == "FORFEITED"

    def test_bulk_closeout_donation_sweep_reports_unsold(self, api):
        """PRD §3.9: "Third, the unsold-inventory sweep: for each product, the
        units purchased but neither committed to orders nor fulfilled digitally
        are donated, producing bulk donation entries per site that are surfaced
        through the close-out response alongside the settlement summary —
        `settled_accounts`, `total_proceeds_offset_cents`,
        `donated_unsold_units`, and `forfeited_agreements`."

        Design: Corner/complexity_layers/bulk_closeout_donation_sweep_reports_unsold
        """
        admin = make_council_admin_headers()
        ctx = setup_reconciliation_season(purchase_qty=100, confirm_qty=80, admin=admin)
        close_out = validate_success(api.close_out_season(ctx["season"]["id"], admin))
        assert close_out["donated_unsold_units"] == 20
        assert close_out["settled_accounts"] == 1


class TestOptimisticConcurrency:
    def test_occ_site_create_stale_season_version(self, api):
        """PRD §2.7: "Creating a distribution site against a season requires
        the request to carry `expected_season_version`, equal to the season's
        current `version` as the client last observed it. If another writer has
        advanced the season's version since that read — an order confirmation
        or purchase-order placement legitimately recomputes the season ledger
        and bumps the version — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"."

        Design: Corner/complexity_layers/occ_site_create_stale_season_version
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        stale_version = season["version"]
        add_site(season, admin=admin)  # bumps the season version
        resp = api.create_site(
            season["id"],
            {
                "name": "Depot 2",
                "address": "2 Depot Way",
                "capacity_units": 5000,
                "expected_season_version": stale_version,
            },
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_occ_site_create_current_version_succeeds(self, api):
        """PRD §2.7: "Creating a distribution site against a season requires
        the request to carry `expected_season_version`, equal to the season's
        current `version` as the client last observed it." PRD §3.1: "creating
        the site itself advances the season's `version` by one."

        Design: Corner/complexity_layers/occ_site_create_current_version_succeeds
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        add_site(season, admin=admin)
        fresh = get_season(season["id"], admin=admin)
        site2 = validate_success(
            api.create_site(
                season["id"],
                {
                    "name": "Depot 2",
                    "address": "2 Depot Way",
                    "capacity_units": 5000,
                    "expected_season_version": fresh["version"],
                },
                admin,
            ),
            expected_status=201,
        )
        assert site2["season_id"] == season["id"]
        after = get_season(season["id"], admin=admin)
        assert after["version"] == fresh["version"] + 1


class TestClock:
    def test_clock_default_is_fixed_startup_time(self, api):
        """PRD §2.9: "At server startup the logical clock reads exactly
        2026-09-01T00:00:00Z, and until it is explicitly set it continues to
        read that default. A `CouncilAdmin`-only test-driving capability
        advances the logical clock to a supplied `to_iso8601` instant and
        returns the resulting `current_utc`"."

        Design: Corner/endpoints/clock_default_is_fixed_startup_time
        """
        admin = make_council_admin_headers()
        data = set_clock("2027-03-01T00:00:00Z", admin=admin)
        assert data["current_utc"] == "2027-03-01T00:00:00Z"


class TestFilteredListings:
    def test_filtered_list_reverse_reachability_transfers(self, api):
        """PRD §4: "GET | /cookie-program/transfers | List transfers,
        filterable by season, source troop, destination troop, site, product,
        signers, counter-transfer, and status"."

        Design: Corner/endpoints/filtered_list_reverse_reachability_transfers
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(purchase_qty=600, confirm_qty=480,
                                   packages_per_case=12, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        transfer = create_transfer(
            season["id"], product["id"], 12, ctx["leader"],
            source_troop_id=ctx["troop"]["id"], dest_troop_id=troop2["id"],
        )
        data, meta = validate_paginated(
            api.list_transfers(admin, params={"season_id": season["id"], "status": "REQUESTED"})
        )
        assert meta["total_count"] == 1
        assert [t["id"] for t in data] == [transfer["id"]]
