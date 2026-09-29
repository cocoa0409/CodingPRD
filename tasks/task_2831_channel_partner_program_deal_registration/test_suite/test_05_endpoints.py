"""Endpoint behaviour that is not a calculation: the branching direct-pursuit action, two
reverse-reachability listings with their filters, and the role-open logical clock."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECT_REP,
    DIRECT_SALES_REP_USER_ID,
    NON_EXISTENT_UUID,
    add_certification,
    assert_account,
    assert_paging_meta,
    build_user_headers,
    create_account,
    create_and_invoice_order,
    create_order,
    create_partner,
    direct_pursuit_payload,
    draft_registration,
    read_account,
    read_partner,
    set_clock,
    submit_registration,
    validate_paginated,
    validate_success,
)


class TestBranchingActionAndListings:
    def test_direct_pursuit_of_an_open_account_names_it_without_raising_a_case(self, api):
        """PRD §3.2: "Declaring pursuit on an account in `OPEN_CHANNEL` moves it
        `OPEN_CHANNEL → NAMED_DIRECT`, writing the representative's opaque identifier into
        `direct_pursuit_owner_id` and the current logical instant into `direct_pursuit_declared_at`;
        the account's `version` advances by 1."
        PRD §3.5: "A conflict case is never created by a client. It exists only as the product of
        cascade A hop three or cascade D hop one, which is why the case list and the per-account case
        list of §2.10 are the only ways a partner or a direct sales representative learns that one
        has been raised."

        Design: Corner/endpoints/direct_pursuit_on_an_open_channel_account_raises_no_conflict
        """
        set_clock("2026-03-01T00:00:00.000Z")
        account = create_account()
        assert account["coverage_state"] == "OPEN_CHANNEL"
        assert account["version"] == 1

        named = validate_success(
            api.declare_direct_pursuit(account["id"], direct_pursuit_payload(), DIRECT_REP)
        )
        assert_account(named)
        assert named["coverage_state"] == "NAMED_DIRECT"
        assert named["direct_pursuit_owner_id"] == DIRECT_SALES_REP_USER_ID
        assert named["direct_pursuit_declared_at"] == "2026-03-01T00:00:00.000Z"
        assert named["protected_until"] is None
        assert named["protected_partner_id"] is None
        assert named["protected_product_line"] is None
        assert named["version"] == 2, "exactly one mutation of the account row"

        rows, meta = validate_paginated(
            api.list_account_conflict_cases(account["id"], ANALYST)
        )
        assert rows == [], "cascade D never ran, because the account was not protected"
        assert_paging_meta(meta, limit=10, offset=0, total_count=0, has_more=False)

    def test_the_order_listing_narrows_independently_by_partner_and_by_status(self, api):
        """PRD §2.10: "Orders may be filtered by `partner_id`, `registration_id`, `status` and
        `order_type`, and the per-registration order list accepts `status`."
        PRD §2.3: "List responses carry `"response_type": "array"`, and their `meta` object carries
        the four pagination fields `limit`, `offset`, `total_count` and `has_more`, where
        `total_count` is the number of rows matching the filters before paging is applied and
        `has_more` is true exactly when rows remain beyond the current page."

        Design: Corner/endpoints/order_invoice_listing_filters_by_partner_and_status
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner_a = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        partner_b = create_partner(company_name="Borealis Retail", partner_type="RESELLER")

        invoiced_a = create_and_invoice_order(
            partner_a["id"], order_type="DROP_SHIP", list_amount_cents=1_000_000
        )
        pending_a = create_order(
            partner_a["id"], order_type="DROP_SHIP", list_amount_cents=1_000_000
        )
        invoiced_b = create_and_invoice_order(
            partner_b["id"], order_type="DROP_SHIP", list_amount_cents=2_000_000
        )

        rows, meta = validate_paginated(
            api.list_order_invoices(
                ANALYST, params={"partner_id": partner_a["id"], "status": "INVOICED"}
            )
        )
        assert [row["id"] for row in rows] == [invoiced_a["id"]]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert pending_a["id"] not in [row["id"] for row in rows], "excluded by the status filter"
        assert invoiced_b["id"] not in [row["id"] for row in rows], "excluded by the partner filter"

        unfiltered_rows, unfiltered_meta = validate_paginated(
            api.list_order_invoices(ANALYST, params={"partner_id": partner_a["id"]})
        )
        assert unfiltered_meta["total_count"] == 2
        assert sorted(row["id"] for row in unfiltered_rows) == sorted(
            [invoiced_a["id"], pending_a["id"]]
        )

        assert invoiced_b["invoice_amount_cents"] == 1800000
        assert invoiced_b["margin_pct"] == pytest.approx(0.1000, abs=1e-9)
        assert read_partner(partner_b["id"])["trailing_revenue_cents"] == 1800000

    def test_the_nested_registration_listing_shows_drafts_and_narrows_by_product_line(self, api):
        """PRD §2.10: "Deal registrations may be filtered by `partner_id`, `account_id`, `status`,
        `product_line` and `supersedes_registration_id`, the last being the reverse-reachability
        filter for the entity's self-referential foreign key; the per-account registration list
        accepts `status` and `product_line`."
        PRD §2.10: "A sub-resource read such as an account's registrations or a claim's proof
        documents is a reverse-reachability channel only, and the child is always addressable in its
        own right as well."

        Design: Corner/endpoints/account_nested_registration_listing_filters_by_product_line
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Gia Nolan", track="TECH_ASSOCIATE")
        first_account = create_account(account_name="Granite Health")
        second_account = create_account(account_name="Halcyon Logistics")

        submitted = draft_registration(
            partner["id"], first_account["id"], product_line="ANALYTICS_ADDON"
        )
        submit_registration(submitted["id"], partner["id"])
        drafted = draft_registration(
            partner["id"], first_account["id"], product_line="SUPPORT_SERVICES"
        )
        elsewhere = draft_registration(
            partner["id"], second_account["id"], product_line="ANALYTICS_ADDON"
        )

        rows, meta = validate_paginated(
            api.list_account_deal_registrations(first_account["id"], ANALYST)
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted([submitted["id"], drafted["id"]])
        assert elsewhere["id"] not in [row["id"] for row in rows]
        by_id = {row["id"]: row for row in rows}
        assert by_id[submitted["id"]]["status"] == "SUBMITTED"
        assert by_id[drafted["id"]]["status"] == "DRAFT", "a DRAFT row is listed just like the rest"

        filtered_rows, filtered_meta = validate_paginated(
            api.list_account_deal_registrations(
                first_account["id"], ANALYST, params={"product_line": "SUPPORT_SERVICES"}
            )
        )
        assert [row["id"] for row in filtered_rows] == [drafted["id"]]
        assert_paging_meta(filtered_meta, limit=10, offset=0, total_count=1, has_more=False)
        assert set(meta.keys()) >= {"limit", "offset", "total_count", "has_more"}

    def test_the_logical_clock_takes_any_role_and_pins_every_later_created_at(self, api):
        """PRD §2.4: "Before the first such call the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time. Every window,
        deadline, cooldown, expiry sweep and elapsed-day computation in this document reads only that
        clock. This capability is the one endpoint that does not require the identity headers of
        §2.1."
        PRD §2.4: "Every resource also carries `created_at`, the instant the row was inserted, and
        `updated_at`, the instant the row was last mutated; both are ISO 8601 UTC timestamps rendered
        with exactly three fractional digits, and on a freshly created row `updated_at` equals
        `created_at`."

        Design: Corner/endpoints/clock_endpoint_is_open_to_every_role_and_pins_created_at
        """
        as_partner = build_user_headers(NON_EXISTENT_UUID, "Partner")
        first = api.set_current_utc("2026-03-01T00:00:00.000Z", as_partner)
        assert 200 <= first.status_code < 300, (
            f"the clock capability accepts the Partner role: {first.text}"
        )

        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        assert partner["created_at"] == "2026-03-01T00:00:00.000Z"
        assert partner["updated_at"] == "2026-03-01T00:00:00.000Z"
        assert partner["version"] == 1

        second = api.set_current_utc("2027-01-01T00:00:00.000Z", DIRECT_REP)
        assert 200 <= second.status_code < 300, (
            f"the clock capability accepts the DirectSalesRep role: {second.text}"
        )

        account = create_account()
        assert account["created_at"] == "2027-01-01T00:00:00.000Z"

        assert read_partner(partner["id"])["created_at"] == "2026-03-01T00:00:00.000Z", (
            "the clock jump rewrites no stored audit field"
        )
        assert read_account(account["id"])["coverage_state"] == "OPEN_CHANNEL"
