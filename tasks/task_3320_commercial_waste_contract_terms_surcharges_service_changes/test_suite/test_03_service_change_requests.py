"""Service change request tests: quoting variants, approval gates, occupancy."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    ApiErrorId,
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_service_change,
    approve_service_change,
    make_rate_notice,
    get_contract_version,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestQuoteVsFinalAfterRateNotice:
    def _setup(self):
        """ACTIVE contract, line CY_4 4x/wk @ 400000; approved change 4->5
        effective 2026-09-05; notice +5% effective 2026-09-10."""
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(
            legal_name="Acme Manufacturing", billing_email="ap@acme.example"
        )
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=4, base_rate_cents=400000,
        )
        activate_contract(contract["id"])
        change = make_service_change(
            customer["id"], line["id"],
            new_container_size="CY_4", new_frequency_per_week=5,
            effective_date="2026-09-05T00:00:00Z",
        )
        approve_service_change(change["id"])
        make_rate_notice(
            contract["id"], pct_increase=0.05,
            effective_date="2026-09-10T00:00:00Z",
        )
        return customer, contract, line, change

    def test_quote_frozen_at_creation_base_while_final_reprices(self, api):
        """PRD section 3.3: "If the contract happens to have a pending service
        change request whose quote was computed at the old base, that quote is
        deliberately not re-quoted when the notice applies — the stored
        `quoted_new_rate_cents` stays as originally quoted, and the final price
        is instead repriced from the new base when the change is applied (see
        section 3.4)."
        PRD section 3.4: "On application the final price is recomputed with the
        same quoting rule, but reading the line's `base_rate_cents` as it
        stands at apply time — an intervening rate notice changes the result —
        and stored in `final_applied_rate_cents`".

        Design: Difficulty/dual_variant_calc/service_change_quote_vs_final_after_rate_notice
        """
        customer, contract, line, change = self._setup()
        # Quote at creation on the pre-notice base 400000:
        # round_half_up(400000/4 * 5 * 1.10) = 550000.
        assert change["quoted_new_rate_cents"] == 550000
        assert change["old_rate_cents"] == 400000

        # Advance the clock so the notice applies (base becomes 420000) and the
        # change's effective_date is reached.
        set_clock("2026-09-12T00:00:00Z")
        version = get_contract_version(contract["id"])
        applied = validate_success(
            api.apply_service_change(
                change["id"], {"expected_contract_version": version}, OPS
            )
        )
        # Final repriced from the post-notice base 420000:
        # round_half_up(420000/4 * 5 * 1.10) = 577500.
        assert applied["quoted_new_rate_cents"] == 550000, (
            "the stored quote must not be re-quoted when the notice applies"
        )
        assert applied["final_applied_rate_cents"] == 577500
        line_after = validate_success(api.get_service_line(line["id"], OPS))
        assert line_after["base_rate_cents"] == 577500

    def test_applied_change_writes_ledger_and_updates_line_fields(self, api):
        """PRD section 3.4: "The line's `base_rate_cents` is set to that final
        rate, its `container_size` becomes the `new_container_size`, and its
        `frequency_per_week` becomes the `new_frequency_per_week`. The
        contract's `base_monthly_total_cents` is recomputed, a `LedgerEntry`
        with `source` equal to `SERVICE_CHANGE` is written, and the contract's
        `version` increments by 1."

        Design: Difficulty/dual_variant_calc/service_change_quote_vs_final_after_rate_notice
        """
        customer, contract, line, change = self._setup()
        set_clock("2026-09-12T00:00:00Z")
        version_before = get_contract_version(contract["id"])
        applied = validate_success(
            api.apply_service_change(
                change["id"], {"expected_contract_version": version_before}, OPS
            )
        )
        assert applied["status"] == "APPLIED"
        line_after = validate_success(api.get_service_line(line["id"], OPS))
        assert line_after["container_size"] == "CY_4"
        assert line_after["frequency_per_week"] == 5
        assert line_after["base_rate_cents"] == 577500

        contract_after = validate_success(api.get_contract(contract["id"], OPS))
        assert contract_after["base_monthly_total_cents"] == 577500
        assert contract_after["version"] == version_before + 1

        entries_resp = api.list_contract_ledger_entries(contract["id"], OPS)
        rows, _meta = validate_paginated(entries_resp)
        sources = [r["source"] for r in rows]
        assert "RATE_NOTICE" in sources
        assert "SERVICE_CHANGE" in sources


class TestServiceChangeApproveRequiresContractActive:
    def test_approve_on_draft_contract_rejected(self, api):
        """PRD section 3.4: "An `OpsManager` approves a `PENDING` request only
        when the owning contract is `ACTIVE` and no other request on the same
        service line is already `APPROVED`; a second approved change on one
        line is rejected with `ERR_DUPLICATE_PENDING`, and approval against a
        non-active contract is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/service_change_approve_requires_contract_active
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Dep Co", billing_email="d@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        change = make_service_change(
            customer["id"], line["id"],
            new_container_size="CY_6", new_frequency_per_week=3,
            effective_date="2026-09-10T00:00:00Z",
        )
        resp = api.approve_service_change(change["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_service_change_request(change["id"], OPS))
        assert after["status"] == "PENDING"

    def test_approve_succeeds_once_contract_active(self, api):
        """PRD section 3.4: "Approval moves the request from `PENDING` to
        `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/service_change_approve_requires_contract_active
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Dep2 Co", billing_email="d2@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        change = make_service_change(
            customer["id"], line["id"],
            new_container_size="CY_6", new_frequency_per_week=3,
            effective_date="2026-09-10T00:00:00Z",
        )
        activate_contract(contract["id"])
        approved = validate_success(api.approve_service_change(change["id"], OPS))
        assert approved["status"] == "APPROVED"


class TestSingleApprovedChangeOccupancyPerLine:
    def _setup_two_lines(self):
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Occ Co", billing_email="o@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line_a = add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=2, base_rate_cents=100000,
        )
        line_b = add_service_line(
            contract["id"], container_size="CY_6",
            frequency_per_week=3, base_rate_cents=120000,
        )
        activate_contract(contract["id"])
        return customer, contract, line_a, line_b

    def test_second_approve_on_same_line_rejected_but_other_line_ok(self, api):
        """PRD section 3.4: "An `OpsManager` approves a `PENDING` request only
        when the owning contract is `ACTIVE` and no other request on the same
        service line is already `APPROVED`; a second approved change on one
        line is rejected with `ERR_DUPLICATE_PENDING`".

        Design: Difficulty/resource_temporal_overlap/single_approved_change_occupancy_per_line
        """
        customer, contract, line_a, line_b = self._setup_two_lines()
        change_a1 = make_service_change(
            customer["id"], line_a["id"], new_container_size="CY_6",
            new_frequency_per_week=3, effective_date="2026-09-10T00:00:00Z",
        )
        change_a2 = make_service_change(
            customer["id"], line_a["id"], new_container_size="CY_8",
            new_frequency_per_week=4, effective_date="2026-09-15T00:00:00Z",
        )
        change_b1 = make_service_change(
            customer["id"], line_b["id"], new_container_size="CY_8",
            new_frequency_per_week=4, effective_date="2026-09-10T00:00:00Z",
        )
        approve_service_change(change_a1["id"])

        resp = api.approve_service_change(change_a2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PENDING)
        after = validate_success(
            api.get_service_change_request(change_a2["id"], OPS)
        )
        assert after["status"] == "PENDING"

        approved_b = validate_success(api.approve_service_change(change_b1["id"], OPS))
        assert approved_b["status"] == "APPROVED"

    def test_occupancy_released_after_application(self, api):
        """PRD section 3.4: "no other request on the same service line is
        already `APPROVED`" — once the approved change is applied, the line is
        free for a new approval.

        Design: Difficulty/resource_temporal_overlap/single_approved_change_occupancy_per_line
        """
        customer, contract, line_a, line_b = self._setup_two_lines()
        change_a1 = make_service_change(
            customer["id"], line_a["id"], new_container_size="CY_6",
            new_frequency_per_week=3, effective_date="2026-09-10T00:00:00Z",
        )
        approve_service_change(change_a1["id"])
        set_clock("2026-09-10T00:00:00Z")
        version = get_contract_version(contract["id"])
        applied = validate_success(
            api.apply_service_change(
                change_a1["id"], {"expected_contract_version": version}, OPS
            )
        )
        assert applied["status"] == "APPLIED"

        change_a2 = make_service_change(
            customer["id"], line_a["id"], new_container_size="CY_8",
            new_frequency_per_week=4, effective_date="2026-09-15T00:00:00Z",
        )
        approved = validate_success(api.approve_service_change(change_a2["id"], OPS))
        assert approved["status"] == "APPROVED"
