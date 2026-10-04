"""Members, purchases, per-day caps, refunds, safety gates, and ancillary
department sales."""
from test_helpers import (
    ApiErrorId,
    assert_club,
    create_active_item,
    create_club,
    create_member,
    create_region,
    create_vendor,
    record_purchase,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DM, MD


def _club_item_with_cap(cap=5, member_overrides=None):
    """Region + club + vendor + ACTIVE item with the given member cap + member."""
    region = create_region()
    vendor = create_vendor()
    club = create_club(region["id"])
    item = create_active_item(vendor["id"], member_purchase_cap=cap)
    member = create_member(club["id"], **(member_overrides or {}))
    return region, vendor, club, item, member


class TestMemberCap:
    def test_at_cap_purchase_allowed_one_over_rejected(self, api):
        """PRD §3.5: "The purchase passes when that usage plus the requested `unit_qty` is at most the cap —
        equality is allowed — and is rejected with `ERR_MEMBER_CAP_EXCEEDED` (HTTP 422)
        only when the sum would exceed the cap."
        PRD §3.5: "The system stamps `purchased_at` from the logical clock and sets `cap_window` to the
        current logical date: cap windows are per-day."

        Design: Difficulty/boundary_precision_check/member_cap_equality_allowed_plus_one_rejected
        """
        _, _, club, item, member = _club_item_with_cap(cap=5)
        purchase = record_purchase(member["id"], club["id"], item["id"], 5)
        assert purchase["status"] == "COMPLETED"
        assert purchase["cap_window"] == "2026-09-01", (
            f"cap_window is the current logical date, got {purchase['cap_window']}"
        )
        resp = api.create_purchase(
            {"member_id": member["id"], "club_id": club["id"], "item_id": item["id"],
             "unit_qty": 1}, MD,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_CAP_EXCEEDED)

    def test_below_and_at_cap_split_across_purchases(self, api):
        """PRD §3.5: "Usage is the sum of `unit_qty` over the member's `COMPLETED` purchases of that item
        whose `cap_window` equals the current logical date. The purchase passes when
        that usage plus the requested `unit_qty` is at most the cap — equality is
        allowed — and is rejected with `ERR_MEMBER_CAP_EXCEEDED` (HTTP 422) only when
        the sum would exceed the cap."

        Design: Difficulty/boundary_precision_check/member_cap_equality_allowed_plus_one_rejected
        """
        _, _, club, item, member = _club_item_with_cap(cap=5)
        record_purchase(member["id"], club["id"], item["id"], 4)
        at_cap = record_purchase(member["id"], club["id"], item["id"], 1)
        assert at_cap["status"] == "COMPLETED", "4 + 1 = 5 equals the cap: allowed"
        resp = api.create_purchase(
            {"member_id": member["id"], "club_id": club["id"], "item_id": item["id"],
             "unit_qty": 1}, MD,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_CAP_EXCEEDED)

    def test_cap_precedence_inactive_item_within_cap_still_cap_path(self, api):
        """PRD §2.9: "and only then the business gates — safety gates, department enablement,
        frozen-club posture, appointment-window conflicts, cutoff timing, uniqueness and
        consistency constraints, same-day cross-dock, member caps, club capacity, markdown rules,
        active-reference checks, and referential guards, in the order those gates appear in §3.
        A request that would fail two business checks surfaces the earlier one in this ordering."
        PRD §3.5: "the item must be `ACTIVE`, else `ERR_INACTIVE_REFERENCE`."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_purchase_over_cap_on_draft_item
        """
        region = create_region()
        vendor = create_vendor()
        club = create_club(region["id"])
        from test_helpers import create_draft_item
        item = create_draft_item(vendor["id"], member_purchase_cap=5)
        member = create_member(club["id"])
        # Within the cap but against a DRAFT item: the cap check passes, so the
        # later active-reference check surfaces instead.
        resp = api.create_purchase(
            {"member_id": member["id"], "club_id": club["id"], "item_id": item["id"],
             "unit_qty": 5}, MD,
        )
        validate_error(resp, ApiErrorId.ERR_INACTIVE_REFERENCE)


class TestRefund:
    def test_refund_restores_cap_usage(self, api):
        """PRD §3.5: "A purchase begins `COMPLETED`; refunding it moves it to `REFUNDED` and reduces the
        member's cap usage for that `cap_window` by the purchase's `unit_qty`, since
        refunded purchases no longer count."

        Design: Difficulty/compensating_invariant/purchase_refund_restores_member_cap_usage_invariant
        """
        _, _, club, item, member = _club_item_with_cap(cap=5)
        purchase = record_purchase(member["id"], club["id"], item["id"], 4)
        refunded = validate_success(api.refund_purchase(purchase["id"], MD))
        assert refunded["status"] == "REFUNDED"
        # With usage restored to 0, a full-cap purchase succeeds.
        second = record_purchase(member["id"], club["id"], item["id"], 5)
        assert second["status"] == "COMPLETED", (
            "refund restored the window usage; without it 4 + 5 > 5 would fail"
        )

    def test_refund_excludes_purchase_from_cap_window(self, api):
        """PRD §3.5: "Usage is the sum of `unit_qty` over the member's `COMPLETED` purchases of that item
        whose `cap_window` equals the current logical date."
        PRD §3.5: "A purchase begins `COMPLETED`; refunding it moves it to `REFUNDED` and reduces the
        member's cap usage for that `cap_window` by the purchase's `unit_qty`, since
        refunded purchases no longer count."

        Design: Difficulty/compensating_invariant/purchase_refund_restores_member_cap_usage_invariant
        """
        _, _, club, item, member = _club_item_with_cap(cap=5)
        first = record_purchase(member["id"], club["id"], item["id"], 5)
        validate_success(api.refund_purchase(first["id"], MD))
        # Usage is 0 again (REFUNDED rows excluded): another 5-unit purchase passes.
        second = record_purchase(member["id"], club["id"], item["id"], 5)
        assert second["status"] == "COMPLETED"


class TestSuspendedMember:
    def test_suspended_member_cannot_purchase(self, api):
        """PRD §3.5: "The purchasing member must be `ACTIVE` — a suspended member buying
        merchandise, filing a complaint, or purchasing an ancillary service is rejected with
        `ERR_SAFETY_GATE`"

        Design: Corner/validations/suspended_member_cannot_purchase
        """
        _, _, club, item, member = _club_item_with_cap(cap=0)
        validate_success(api.suspend_member(member["id"], MD))
        resp = api.create_purchase(
            {"member_id": member["id"], "club_id": club["id"], "item_id": item["id"],
             "unit_qty": 1}, MD,
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_GATE)


class TestDepartmentSales:
    def test_disabled_department_rejected_enabled_allowed(self, api):
        """PRD §3.5: "The member must be `ACTIVE` (the same safety gate), and the named department must be
        enabled in the club's `ancillary_flags`; a sale to a disabled department is
        rejected with `ERR_DEPARTMENT_DISABLED` (HTTP 422)."

        Design: Corner/validations/department_sale_disabled_department_rejected
        """
        region = create_region()
        club = create_club(region["id"],
                           ancillary_flags={"gas": True, "pharmacy": False, "optical": False})
        member = create_member(club["id"])
        gas = validate_success(
            api.create_department_sale(
                {"club_id": club["id"], "member_id": member["id"], "department": "GAS",
                 "amount_cents": 5000}, MD,
            ), 201,
        )
        assert gas["department"] == "GAS"
        resp = api.create_department_sale(
            {"club_id": club["id"], "member_id": member["id"], "department": "PHARMACY",
             "amount_cents": 2000}, MD,
        )
        validate_error(resp, ApiErrorId.ERR_DEPARTMENT_DISABLED)


class TestReverseReachability:
    def test_club_members_subresource_and_filtered_list(self, api):
        """PRD §4: "List a club's members (`limit`, `offset`, `status`)"
        PRD §4: "List members (`limit`, `offset`, `club_id`, `status`, `tier`)"

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        region = create_region()
        club = create_club(region["id"], club_number=4301)
        member = create_member(club["id"], membership_number="M000001301")
        sub, _ = validate_paginated(api.list_club_members(club["id"], MD))
        assert len(sub) == 1
        assert sub[0]["id"] == member["id"], "sub-resource form reaches the member"
        filtered, _ = validate_paginated(api.list_members(MD, params={"club_id": club["id"]}))
        assert len(filtered) == 1
        assert filtered[0]["id"] == member["id"], "filtered-list form reaches the member"
