"""Validation-ladder priority conflicts: trade qualification versus the program window."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_national_account,
    create_territory,
    create_work_order,
    get_work_order,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


def _tight_window_portfolio():
    """Brand MS requiring MASTER certification, two territories and two
    agreements whose technicians hold APPRENTICE and MASTER respectively, and a
    program whose own window is 4 hours."""
    set_clock("2026-09-01T00:00:00Z")
    brand = create_brand(
        brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
        royalty_rate=0.06, national_ad_fund_rate=0.01,
        min_certification_level="MASTER", audit_cycle_months=12,
        cross_brand_fee_table={},
    )
    franchisee = create_franchisee()
    ter_low = create_territory(brand["id"], franchisee_id=franchisee["id"])
    ter_ok = create_territory(brand["id"], franchisee_id=franchisee["id"])
    agt_low = create_agreement(
        franchisee["id"], brand["id"], ter_low["id"], certification_level="APPRENTICE",
    )
    agt_ok = create_agreement(
        franchisee["id"], brand["id"], ter_ok["id"], certification_level="MASTER",
    )
    for territory, agreement in ((ter_low, agt_low), (ter_ok, agt_ok)):
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
    account = create_national_account(
        account_name="Tight Window Trust",
        account_type="NATIONAL_ACCOUNT",
        contracted_brands=[brand["id"]],
        service_level_hours=4,
        sla_credit_per_breach_cents=7500,
        breach_tolerance=3,
        annual_commitment_cents=10000000,
    )
    wo_low = create_work_order(
        agt_low["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
        service_level_hours=6, parts_cents=0, national_account_id=account["id"],
    )
    wo_ok = create_work_order(
        agt_ok["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
        service_level_hours=6, parts_cents=0, national_account_id=account["id"],
    )
    return brand, franchisee, ter_low, ter_ok, agt_low, agt_ok, account, wo_low, wo_ok


class TestDispatchQualificationBeatsProgramWindow:
    def test_dispatch_failing_both_gates_reports_the_safety_error(self, api):
        """PRD §2.5: "Trade qualification holds seventh, reporting
        `ERR_CERTIFICATION_TOO_LOW` alongside `ERR_ACCOUNT_BRAND_NOT_CONTRACTED`
        and `ERR_SHARED_SERVICES_REQUIRED`, all 422, as described in §2.4."
        PRD §2.5: "Logical-clock windows hold tenth, reporting
        `ERR_SLA_WINDOW_EXCEEDS_PROGRAM` at 422".

        Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_priority_7_safety_beats_priority_10_temporal
        """
        _, franchisee, _, _, _, _, _, wo_low, _ = _tight_window_portfolio()

        resp = api.dispatch_work_order(
            wo_low["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_TOO_LOW)
        error = resp.json()["data"]
        assert error["error_id"] != ApiErrorId.ERR_SLA_WINDOW_EXCEEDS_PROGRAM.value, (
            "a dispatch that fails both the certification gate and the program "
            "window must report the qualification failure"
        )

    def test_the_refused_dispatch_leaves_the_work_order_undispatched(self, api):
        """PRD §3.4: "On success the dispatch instant is stamped as
        `dispatched_clock_iso`, the status becomes `DISPATCHED`, and the
        deadline is set."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_priority_7_safety_beats_priority_10_temporal
        """
        _, franchisee, _, _, _, _, _, wo_low, _ = _tight_window_portfolio()

        api.dispatch_work_order(
            wo_low["id"], make_franchisee_operator_headers(franchisee["id"]),
        )

        refused = get_work_order(wo_low["id"])
        assert refused["status"] == "CREATED"
        assert refused["dispatched_clock_iso"] is None

        resp = api.list_work_orders(ADMIN, {"agreement_id": wo_low["agreement_id"],
                                            "status": "DISPATCHED"})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, (
            f"the refused work order must not appear as DISPATCHED, got {meta['total_count']}"
        )

    def test_a_qualified_agreement_falls_through_to_the_window_gate(self, api):
        """PRD §3.4: "Where a program applies, the work order's own
        `service_level_hours` may not exceed the program's `service_level_hours`;
        a longer window is refused with `ERR_SLA_WINDOW_EXCEEDS_PROGRAM`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_priority_7_safety_beats_priority_10_temporal
        """
        _, franchisee, _, _, _, _, _, _, wo_ok = _tight_window_portfolio()

        resp = api.dispatch_work_order(
            wo_ok["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLA_WINDOW_EXCEEDS_PROGRAM)
        assert get_work_order(wo_ok["id"])["status"] == "CREATED"