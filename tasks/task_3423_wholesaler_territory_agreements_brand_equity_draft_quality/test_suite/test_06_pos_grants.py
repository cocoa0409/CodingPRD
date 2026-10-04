"""POS material: state-law value caps, voids, pagination."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    issue_grant,
    make_account,
    post_critical_audit,
    setup_account_with_grants,
    setup_awarded_territory,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


@pytest.fixture
def cap_boundary(api):
    """TX account with 29700 chargeable cents (3 x 9900); then a 300-cent
    grant landing exactly on the 30000 cap and a 1-cent overflow attempt."""
    _, account, grants = setup_account_with_grants(
        [9900, 9900, 9900], territory_name="Boundary Territory")
    on_cap = api.create_pos_grant(
        {"account_id": account["id"], "item_description": "sign 4 lands exactly on cap",
         "value_cents": 300}, ADMIN)
    over_cap = api.create_pos_grant(
        {"account_id": account["id"], "item_description": "one cent over",
         "value_cents": 1}, ADMIN)
    return {"account": account, "grants": grants,
            "on_cap": on_cap, "over_cap": over_cap}


class TestPosCapInclusiveBoundary:
    def test_grant_landing_exactly_on_cap_accepted(self, api, cap_boundary):
        """PRD §3.7: "The cap is inclusive — a grant that lands the running
        total exactly on the cap is accepted, while one cent beyond it is
        rejected with `ERR_POS_VALUE_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pos_cap_inclusive_cent_boundary
        """
        grant = validate_success(cap_boundary["on_cap"], 201)
        assert grant["status"] == "ISSUED", (
            "29700 + 300 == 30000 == TX cap, inclusive boundary"
        )
        rows, _ = validate_paginated(
            api.list_account_pos_grants(cap_boundary["account"]["id"], ADMIN))
        issued = [r for r in rows if r["status"] == "ISSUED"]
        assert len(issued) == 4
        assert sum(r["value_cents"] for r in issued) == 30000

    def test_one_cent_over_cap_rejected(self, api, cap_boundary):
        """PRD §3.7: "The cap is inclusive — a grant that lands the running
        total exactly on the cap is accepted, while one cent beyond it is
        rejected with `ERR_POS_VALUE_CAP_EXCEEDED`."
        PRD §3.7: "30000 cents for Texas, 25000 cents for California, and 20000
        cents for every other state."

        Design: Difficulty/boundary_precision_check/pos_cap_inclusive_cent_boundary
        """
        validate_error(cap_boundary["over_cap"],
                       ApiErrorId.ERR_POS_VALUE_CAP_EXCEEDED)


@pytest.fixture
def state_vs_fiscal(api):
    """TX account at 29700 YTD, then SERVICE_SUSPENDED by a CRITICAL_FAIL
    audit; a 400-cent grant violates both the state gate and the cap."""
    _, account, _ = setup_account_with_grants(
        [9900, 9900, 9900], territory_name="Prio Territory")
    post_critical_audit(account["id"])
    attempt = api.create_pos_grant(
        {"account_id": account["id"], "item_description": "cooler wrap",
         "value_cents": 400}, ADMIN)
    return {"account": account, "attempt": attempt}


class TestStateGateBeatsFiscalCap:
    def test_suspended_account_grant_reports_state_error(
        self, api, state_vs_fiscal
    ):
        """PRD §2.10: "Concretely: a POS grant that would both target a
        suspended account and breach the value cap is reported as
        `ERR_ACCOUNT_NOT_ACTIVE`, never as the cap error, because the state
        tier outranks the fiscal tier."

        Design: Difficulty/priority_pair_validation_conflict/pos_grant_state_gate_beats_fiscal_cap
        """
        env = state_vs_fiscal
        acct = validate_success(api.get_retail_account(env["account"]["id"], ADMIN))
        assert acct["status"] == "SERVICE_SUSPENDED"

        resp = env["attempt"]
        assert resp.status_code == 409, (
            f"state tier (409) outranks fiscal tier (422); got {resp.status_code}"
        )
        body = resp.json()["data"]
        assert body["error_id"] == ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value

        rows, _ = validate_paginated(
            api.list_account_pos_grants(env["account"]["id"], ADMIN))
        issued = [r for r in rows if r["status"] == "ISSUED"]
        assert len(issued) == 3
        assert sum(r["value_cents"] for r in issued) == 29700

    def test_fiscal_cap_fires_on_active_account(self, api, state_vs_fiscal):
        """PRD §3.7: "Grants to a `SERVICE_SUSPENDED` account are refused
        outright with `ERR_ACCOUNT_NOT_ACTIVE`, independent of the cap."
        PRD §3.7: "A new grant is allowed only when that running total plus the
        new grant's `value_cents` does not exceed the cap selected by the
        account's `state_code`"

        Design: Difficulty/priority_pair_validation_conflict/pos_grant_state_gate_beats_fiscal_cap
        """
        # Same fiscal violation on an ACTIVE account surfaces the cap error.
        _, account, _ = setup_account_with_grants(
            [26000], territory_name="Fiscal Only Territory")
        resp = api.create_pos_grant(
            {"account_id": account["id"], "item_description": "over",
             "value_cents": 5000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_POS_VALUE_CAP_EXCEEDED)


@pytest.fixture
def void_cycle(api):
    """TX account with one 26000-cent ISSUED grant; a blocked 5000-cent
    pre-void attempt; then the void and the identical replacement grant."""
    _, account, grants = setup_account_with_grants(
        [26000], territory_name="Void Territory")
    pre_void = api.create_pos_grant(
        {"account_id": account["id"], "item_description": "blocked pre-void",
         "value_cents": 5000}, ADMIN)
    voided = api.void_pos_grant(grants[0]["id"], ADMIN)
    if voided.status_code != 200:
        raise AssertionError(f"Setup failed at void: {voided.text[:300]}")
    replacement = api.create_pos_grant(
        {"account_id": account["id"], "item_description": "replacement felt",
         "value_cents": 5000}, ADMIN)
    return {"account": account, "grant": grants[0], "pre_void": pre_void,
            "voided": voided, "replacement": replacement}


class TestIssueVoidConservation:
    def test_cap_bites_before_void_and_void_stamps_clock(self, api, void_cycle):
        """PRD §3.7: "A `BrewerAdmin` may void an `ISSUED` grant, moving it
        `ISSUED` → `VOIDED` and stamping `voided_at` from the logical clock."

        Design: Difficulty/compensating_invariant/issue_void_conserves_pos_lifetime_value
        """
        env = void_cycle
        validate_error(env["pre_void"], ApiErrorId.ERR_POS_VALUE_CAP_EXCEEDED)

        voided = validate_success(env["voided"], 200)
        assert voided["status"] == "VOIDED"
        assert_instant_equals(voided["voided_at"], "2026-09-01T00:00:00Z",
                              label="voided_at")
        assert voided["granted_year"] == 2026

    def test_void_reopens_headroom_and_conserves_lifetime_value(
        self, api, void_cycle
    ):
        """PRD §3.7: "A voided grant stops counting toward the account's
        chargeable year-to-date value — voiding can therefore reopen headroom
        under the cap — while the lifetime granted value on record is
        unchanged."

        Design: Difficulty/compensating_invariant/issue_void_conserves_pos_lifetime_value
        """
        env = void_cycle
        replacement = validate_success(env["replacement"], 201)
        assert replacement["status"] == "ISSUED", (
            "the void restored exactly 26000 cents of headroom"
        )
        assert replacement["granted_year"] == 2026

        rows, _ = validate_paginated(
            api.list_account_pos_grants(env["account"]["id"], ADMIN))
        issued = [r for r in rows if r["status"] == "ISSUED"]
        voided = [r for r in rows if r["status"] == "VOIDED"]
        chargeable = sum(r["value_cents"] for r in issued)
        lifetime = chargeable + sum(r["value_cents"] for r in voided)
        assert chargeable == 5000
        assert lifetime == 31000


class TestPosGrantPagination:
    def test_pos_grants_pagination_defaults_and_offsets(
        self, api, compliance_headers, ws_headers
    ):
        """PRD §2.3: "When omitted, `limit` defaults to 10 and must lie between
        a minimum of 1 and a maximum of 100; `offset` defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pos_grants_pagination_defaults_and_offsets
        """
        wholesaler, account, grants = setup_account_with_grants(
            [100] * 12, territory_name="Page Territory")

        page1, meta1 = validate_paginated(
            api.list_account_pos_grants(account["id"], compliance_headers))
        assert len(page1) == 10, "default limit 10 applied"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_account_pos_grants(
                account["id"], compliance_headers,
                params={"limit": 10, "offset": 10}))
        assert len(page2) == 2
        assert meta2["total_count"] == 12, (
            "total_count spans the whole filtered set, not the page"
        )
        assert meta2["has_more"] is False

        page3, meta3 = validate_paginated(
            api.list_account_pos_grants(
                account["id"], ws_headers(wholesaler["id"]),
                params={"limit": 5, "offset": 0}))
        assert len(page3) == 5
        assert meta3["has_more"] is True

        for row in page1 + page2:
            assert row["status"] == "ISSUED"
            assert row["granted_year"] == 2026
