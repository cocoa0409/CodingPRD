"""Competing offer / right-of-first-refusal tests (PRD section 3.9)."""
from test_helpers import (
    ApiErrorId,
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_competing_offer,
    get_contract_version,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestRofrMatchProportionalAllocation:
    def _setup(self):
        """ACTIVE rofr_enabled contract (window 15d) with lines
        50000/30000/10000 (total 90000) and a SUBMITTED offer of 85501."""
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Match Co", billing_email="m@x.example")
        contract = make_contract(
            customer["id"], term_months=12,
            rofr_enabled=True, rofr_window_days=15,
        )
        line1 = add_service_line(
            contract["id"], container_size="CY_8",
            frequency_per_week=5, base_rate_cents=50000,
        )
        line2 = add_service_line(
            contract["id"], container_size="CY_6",
            frequency_per_week=3, base_rate_cents=30000,
        )
        line3 = add_service_line(
            contract["id"], container_size="CY_2",
            frequency_per_week=1, base_rate_cents=10000,
        )
        activate_contract(contract["id"])
        offer = make_competing_offer(
            customer["id"], contract["id"], competitor_monthly_cents=85501,
        )
        return customer, contract, (line1, line2, line3), offer

    def test_proportional_allocation_with_remainder_on_largest_line(self, api):
        """PRD section 3.9: "The match price is the competitor's total minus an
        undercut of 500 cents, floored at zero: the matched rate is the greater
        of 0 and `competitor_monthly_cents` minus 500."
        PRD section 3.9: "Lines are processed in order of `base_rate_cents`
        descending with ties broken by `created_at` ascending, and any rounding
        remainder — the matched rate minus the sum of the per-line results — is
        added to the first line in that order, so the new line rates sum to the
        matched rate exactly."

        Design: Difficulty/combinatorial_formula/rofr_match_proportional_allocation_with_remainder
        """
        customer, contract, (line1, line2, line3), offer = self._setup()
        version = get_contract_version(contract["id"])
        matched = validate_success(
            api.match_competing_offer(
                offer["id"], {"expected_contract_version": version}, OPS
            )
        )
        assert matched["status"] == "MATCHED"
        # matched rate = 85501 - 500 = 85001; proportional rounding gives
        # 47223+28334+9445 = 85002, so the largest line absorbs the -1.
        l1 = validate_success(api.get_service_line(line1["id"], OPS))
        l2 = validate_success(api.get_service_line(line2["id"], OPS))
        l3 = validate_success(api.get_service_line(line3["id"], OPS))
        assert l1["base_rate_cents"] == 47222
        assert l2["base_rate_cents"] == 28334
        assert l3["base_rate_cents"] == 9445
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["base_monthly_total_cents"] == 85001, (
            "the new total must equal the matched rate exactly, not the naive "
            f"rounded sum, got {contract_after['base_monthly_total_cents']}"
        )

    def test_match_writes_rofr_ledger_entry_and_bumps_version(self, api):
        """PRD section 3.9: "The contract's `base_monthly_total_cents` is then
        set to the matched rate, a `LedgerEntry` with `source` equal to
        `ROFR_MATCH` is written, the contract's `version` increments by 1, and
        the offer moves from `SUBMITTED` to `MATCHED`."

        Design: Difficulty/combinatorial_formula/rofr_match_proportional_allocation_with_remainder
        """
        from prd_bench_local_runner.testing import validate_paginated

        customer, contract, _lines, offer = self._setup()
        version = get_contract_version(contract["id"])
        validate_success(
            api.match_competing_offer(
                offer["id"], {"expected_contract_version": version}, OPS
            )
        )
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["version"] == version + 1
        rows, _meta = validate_paginated(
            api.list_contract_ledger_entries(contract["id"], OPS)
        )
        rofr_entries = [r for r in rows if r["source"] == "ROFR_MATCH"]
        assert len(rofr_entries) == 1
        assert rofr_entries[0]["old_base_monthly_cents"] == 90000
        assert rofr_entries[0]["new_base_monthly_cents"] == 85001


class TestRofrMatchWindow:
    def _setup(self, offer_day="2026-09-01"):
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Win Co", billing_email="wi@x.example")
        contract = make_contract(
            customer["id"], term_months=12,
            rofr_enabled=True, rofr_window_days=15,
        )
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        offer = make_competing_offer(
            customer["id"], contract["id"], competitor_monthly_cents=90000,
        )
        return customer, contract, offer

    def test_match_after_window_rejected_and_pricing_untouched(self, api):
        """PRD section 3.9: "Matching requires three preconditions: the logical
        clock must be on or before the offer's `created_at` plus the contract's
        `rofr_window_days` days; no other offer on the same contract may be
        `SUBMITTED`; and the contract must be `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/rofr_match_window_and_single_submitted_dependency
        """
        customer, contract, offer = self._setup()
        # 16 days after creation: past the 15-day window.
        set_clock("2026-09-17T00:00:00Z")
        version = get_contract_version(contract["id"])
        resp = api.match_competing_offer(
            offer["id"], {"expected_contract_version": version}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)
        offer_after = validate_success(api.get_competing_offer(offer["id"], OPS))
        assert offer_after["status"] == "SUBMITTED"
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["base_monthly_total_cents"] == 100000

    def test_match_within_window_succeeds(self, api):
        """PRD section 3.9: "the logical clock must be on or before the offer's
        `created_at` plus the contract's `rofr_window_days` days".

        Design: Difficulty/cross_entity_state_dependency/rofr_match_window_and_single_submitted_dependency
        """
        customer, contract, offer = self._setup()
        # 15 days after creation: exactly at the window boundary (on or before).
        set_clock("2026-09-16T00:00:00Z")
        version = get_contract_version(contract["id"])
        matched = validate_success(
            api.match_competing_offer(
                offer["id"], {"expected_contract_version": version}, OPS
            )
        )
        assert matched["status"] == "MATCHED"
        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["base_monthly_total_cents"] == 89500


class TestMissingVersionFieldWinsOverOcc:
    def test_match_without_expected_version_is_invalid_request(self, api):
        """PRD section 2.10: "A request that violates more than one rule is
        rejected with the error belonging to the earliest applicable priority
        in this ordering."
        PRD section 2.10: "fourth request shape — required fields present,
        well-typed values, enums within their declared sets, numeric ranges
        respected (`ERR_INVALID_REQUEST`, HTTP 400); fifth state admissibility
        of the target resource (`ERR_INVALID_STATE`, HTTP 409); sixth the
        optimistic-concurrency version match on the two OCC-guarded writes
        (`ERR_STALE_VERSION`)".
        PRD section 2.8: "Each of these requests must carry
        `expected_contract_version`, a non-optional input field holding the
        `version` of the contract as the client last observed it."

        Design: Difficulty/priority_pair_validation_conflict/missing_photo_vs_stale_version_on_match
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Prio Co", billing_email="p@x.example")
        contract = make_contract(
            customer["id"], term_months=12, rofr_enabled=True,
        )
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        offer = make_competing_offer(
            customer["id"], contract["id"], competitor_monthly_cents=90000,
        )
        # No expected_contract_version at all: the required-field check at the
        # request-shape priority fires before any OCC comparison.
        resp = api.match_competing_offer(offer["id"], {}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        offer_after = validate_success(api.get_competing_offer(offer["id"], OPS))
        assert offer_after["status"] == "SUBMITTED"

    def test_match_with_stale_version_is_stale_version_error(self, api):
        """PRD section 2.8: "If that value does not match the contract's
        current `version` — because a prior match, a rate-notice application,
        a service-change application, an activation, a renewal, or any other
        contract mutation has advanced it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-observe the
        contract's pricing before re-pricing it".

        Design: Difficulty/priority_pair_validation_conflict/missing_photo_vs_stale_version_on_match
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Prio3 Co", billing_email="p3@x.example")
        contract = make_contract(
            customer["id"], term_months=12, rofr_enabled=True,
        )
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        offer = make_competing_offer(
            customer["id"], contract["id"], competitor_monthly_cents=90000,
        )
        stale_version = get_contract_version(contract["id"]) - 1
        resp = api.match_competing_offer(
            offer["id"], {"expected_contract_version": stale_version}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        offer_after = validate_success(api.get_competing_offer(offer["id"], OPS))
        assert offer_after["status"] == "SUBMITTED"


class TestCompetingOfferRequiresRofrEnabled:
    def test_offer_against_non_rofr_contract_rejected(self, api):
        """PRD section 3.9: "Submitting against a contract whose `rofr_enabled`
        is false is rejected with `ERR_ROFR_NOT_ENABLED`."

        Design: Corner/validations/competing_offer_requires_rofr_enabled
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="NoRofr Co", billing_email="nr@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        resp = api.create_competing_offer(
            {
                "contract_id": contract["id"],
                "competitor_monthly_cents": 90000,
                "evidence_doc_url": "https://docs.example/o.pdf",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROFR_NOT_ENABLED)
