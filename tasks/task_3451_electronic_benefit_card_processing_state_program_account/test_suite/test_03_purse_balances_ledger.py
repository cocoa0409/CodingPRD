"""Purse balance views (ledger vs spendable), the append-only ledger shape,
single-resource existence, and list pagination envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    instants_equal,
    validate_error,
    validate_paginated,
)
from test_helpers import assertions as A
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestPurseDualBalanceViews:
    def test_scheduled_posting_counts_in_ledger_but_not_spendable(self, api):
        """PRD §2.7: "`spendable_balance_cents` is the signed sum over the same
        rows, except that two categories are excluded: (a) `POST_CREDIT` entries
        whose linked posting is currently in `SCHEDULED` or `FORFEITED` status,
        and (b) all `FORFEIT_DEBIT` entries."
        PRD §3.4: "Each posting is born with `posting_status` `SCHEDULED`, and a
        `POST_CREDIT` ledger entry is created immediately for each posting —
        scheduled money, which raises the purse's ledger balance at once but
        remains invisible to the spendable balance until availability"

        Design: Difficulty/dual_variant_calc/purse_spendable_vs_ledger_with_scheduled_posting
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000003")  # bucket 3
        fx.fund_case(api, ctx)  # 30000 SCHEDULED, available 2026-09-04T06:00Z
        fx.set_clock(api, "2026-09-02T12:00:00Z")  # before availability

        purse_id = ctx.purses["FOOD"]["id"]
        purse = fx.get_purse(api, purse_id)
        A.assert_purse(purse)
        A.assert_purse_balances(purse, ledger_balance_cents=30000,
                                spendable_balance_cents=0)
        assert purse["ledger_balance_cents"] != purse["spendable_balance_cents"]
        posting = fx.list_postings(api, purse_id)[0]
        assert posting["posting_status"] == "SCHEDULED"

    def test_availability_collapses_the_two_views(self, api):
        """PRD §2.7: "The lifecycle cross-checks that follow from the
        definition: while a posting is `SCHEDULED`, its credit raises only the
        ledger balance; once `AVAILABLE`, it raises both"
        PRD §3.4: "On the availability sweep — step 1 of the clock pipeline — a
        `SCHEDULED` posting whose `available_at` the current clock has reached
        or passed flips to `AVAILABLE`, provided its owning purse is not
        `CLOSED`; a `FROZEN` purse still receives availability."

        Design: Difficulty/dual_variant_calc/purse_spendable_vs_ledger_with_scheduled_posting
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000003")  # bucket 3
        fx.fund_case(api, ctx)
        purse_id = ctx.purses["FOOD"]["id"]

        fx.set_clock(api, "2026-09-02T12:00:00Z")
        before = fx.get_purse(api, purse_id)
        assert before["ledger_balance_cents"] == 30000
        assert before["spendable_balance_cents"] == 0

        fx.set_clock(api, "2026-09-04T06:00:00Z")  # posting becomes AVAILABLE
        after = fx.get_purse(api, purse_id)
        A.assert_purse_balances(after, ledger_balance_cents=30000,
                                spendable_balance_cents=30000)
        posting = fx.list_postings(api, purse_id)[0]
        assert posting["posting_status"] == "AVAILABLE"
        assert instants_equal(posting["available_at"], "2026-09-04T06:00:00Z")


class TestLedgerShape:
    def test_ledger_entries_are_append_only_without_version(self, api):
        """PRD §2.5: "Ledger rows are immutable and append-only, so a
        `LedgerEntry` carries only `id` and `created_at`; both `updated_at` and
        `version` are absent."
        PRD §3.4: "Each posting is born with `posting_status` `SCHEDULED`, and a
        `POST_CREDIT` ledger entry is created immediately for each posting —
        scheduled money, which raises the purse's ledger balance at once but
        remains invisible to the spendable balance until availability"

        Design: Corner/entities/ledger_entries_are_append_only_without_version
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        fx.fund_case(api, ctx)  # one POST_CREDIT of 30000
        entries = fx.list_ledger(api, ctx.purses["FOOD"]["id"])
        assert len(entries) == 1, f"expected exactly one entry, got {len(entries)}"
        entry = entries[0]
        A.assert_ledger_entry(entry)  # id + created_at present; no updated_at/version
        assert "id" in entry and "created_at" in entry
        assert "version" not in entry and "updated_at" not in entry
        assert entry["entry_type"] == "POST_CREDIT"
        assert entry["amount_cents"] == 30000


class TestExistenceAndListing:
    def test_get_nonexistent_purse_returns_not_found(self, api):
        """PRD §2.9: "For any endpoint whose path contains resource identifiers,
        the system validates the existence of each identifier in sequential
        left-to-right order and rejects the request with `ERR_NOT_FOUND` at the
        first identifier that does not correspond to an existing resource."

        Design: Corner/entities/get_nonexistent_purse_returns_not_found
        """
        fx.create_contract(api)
        resp = api.get_purse(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        ctx = fx.setup_active_contract(api, program_types=("FOOD", "CASH"))
        fx.add_case(api, ctx)  # two purses
        resp = api.list_purses(
            ADMIN, params={"case_account_id": ctx.case["id"], "limit": 1}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return 1 row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with 'req_'"
        )
