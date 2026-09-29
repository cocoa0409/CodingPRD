"""Request-level validation bounds, rate-card supersession and derived-state reads.

The rules exercised here are the ones that decide a request before any business
work happens — the global rule ordering of §2.10, the pagination bounds of §2.3,
the uniqueness constraints on `order_ref` and on a live application, and the
sub-affiliate nesting limits — plus the one permitted rate-card overlap and the
guarantee that every derived figure a write produces is final in that write's own
response and on the very next read.
"""

import pytest

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AFFILIATE_SUSPENDED,
    ERR_CIRCULAR_SUB_AFFILIATE,
    ERR_DUPLICATE_APPLICATION,
    ERR_DUPLICATE_ORDER_REF,
    ERR_PAGINATION_INVALID,
    ERR_SUB_AFFILIATE_DEPTH_EXCEEDED,
    ERR_TRACKING_LINK_DISABLED,
)
from test_helpers.assertions import (
    assert_append_only_row,
    assert_cents,
    assert_created,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_null,
    assert_object_response,
    assert_pagination_meta,
    assert_version_bumped,
)
from test_helpers.fixtures import (
    build_program,
    create_conversion,
    create_network,
    draft_policy,
    file_application,
    ingest_click,
    pin_clock,
    register_affiliate,
    reinstate_partner,
    suspend_partner,
    valid_tax_document,
)
from test_helpers.test_users import (
    ANONYMOUS,
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

CLOCK = f.JUL_05_00_00
SETTLEMENT_CLOCK = f.AUG_05_00_00


class TestClickIngestOnASuspendedPartnersDisabledLink:
    def test_click_on_suspended_partner_reports_suspension_not_the_disabled_link(
        self, api
    ):
        """A click into a suspended partner's auto-disabled link answers the suspension.

        PRD §2.10 rule 17: "The partner whose resource is being written is neither
        `SUSPENDED` nor `TERMINATED` — otherwise `ERR_AFFILIATE_SUSPENDED` (409). Applies
        to minting a tracking link, filing an application, ingesting a click, and
        resubmitting an application."

        Design: Corner/validations/suspended_affiliate_check_outranks_disabled_link_on_click_ingest
        """
        program = build_program(api, setup_clock=CLOCK, with_policy=False)
        suspend_partner(
            api,
            program["affiliate_id"],
            reason="manual compliance hold pending trademark review",
        )

        # §3.7: the suspension cascade disables the partner's `ACTIVE` tracking links
        # "with `disabled_reason` `AFFILIATE_SUSPENDED`", so rule 28 would also match.
        link = assert_object_response(
            api.get_tracking_link(program["link_id"], PROGRAM_ADMIN)
        )
        assert_fields(
            link, {"status": "DISABLED", "disabled_reason": "AFFILIATE_SUSPENDED"}
        )

        response = api.ingest_click(
            program["link_id"],
            f.click_payload(
                occurred_at="2026-07-05T10:00:00.000Z",
                device_id="D1",
                click_type="ORGANIC_CLICK",
                referrer_domain="beacon.example",
            ),
            TRACKING_INGESTOR,
        )

        # §2.10: "Rules are evaluated in strictly ascending order of the numbers below,
        # and the **first** rule whose condition fails decides the response".
        assert_error_response(response, ERR_AFFILIATE_SUSPENDED, 409)

        _rows, meta = assert_list_response(
            api.list_clicks(
                program["link_id"], COMPLIANCE_ANALYST, {"limit": 10, "offset": 0}
            )
        )
        assert_pagination_meta(meta, total_count=0)

    def test_reinstated_partner_still_has_a_disabled_link_so_the_click_reports_the_link(
        self, api
    ):
        """Reinstatement clears the suspension but leaves the link disabled for good.

        PRD §3.7: "Reinstatement restores `status` to `ACTIVE` and `suspension_cause` to
        `NONE` and nothing else: tracking links are **not** re-enabled, so the partner
        must be minted new ones, and payout-line holds are **not** released, so a
        `FinanceController` must release each line explicitly."

        Design: Corner/validations/suspended_affiliate_check_outranks_disabled_link_on_click_ingest
        """
        program = build_program(api, setup_clock=CLOCK, with_policy=False)
        suspend_partner(
            api,
            program["affiliate_id"],
            reason="manual compliance hold pending trademark review",
        )

        reinstated = reinstate_partner(
            api,
            program["affiliate_id"],
            reason="trademark review closed with no findings",
        )
        assert_fields(reinstated, {"status": "ACTIVE", "suspension_cause": "NONE"})

        link = assert_object_response(
            api.get_tracking_link(program["link_id"], PROGRAM_ADMIN)
        )
        assert_fields(
            link, {"status": "DISABLED", "disabled_reason": "AFFILIATE_SUSPENDED"}
        )

        response = api.ingest_click(
            program["link_id"],
            f.click_payload(
                occurred_at="2026-07-05T11:00:00.000Z",
                device_id="D1",
                click_type="ORGANIC_CLICK",
                referrer_domain="beacon.example",
            ),
            TRACKING_INGESTOR,
        )

        # §2.10 rule 28: "The tracking link's `status` is `ACTIVE` — otherwise
        # `ERR_TRACKING_LINK_DISABLED` (409). Applies to click ingestion and to link
        # disabling, so a disabled link can neither receive clicks nor be disabled a
        # second time."
        assert_error_response(response, ERR_TRACKING_LINK_DISABLED, 409)

        _rows, meta = assert_list_response(
            api.list_clicks(
                program["link_id"], COMPLIANCE_ANALYST, {"limit": 10, "offset": 0}
            )
        )
        assert_pagination_meta(meta, total_count=0)


class TestPaginationBoundsOnTheAffiliateList:
    @pytest.mark.parametrize(
        "limit,offset",
        [
            pytest.param(0, 0, id="limit_zero_is_below_the_floor"),
            pytest.param(101, 0, id="limit_101_is_above_the_ceiling"),
            pytest.param(10, -1, id="offset_minus_one_is_below_the_floor"),
        ],
    )
    def test_out_of_range_pagination_parameters_are_rejected(self, api, limit, offset):
        """Each out-of-range paging parameter is refused on its own with a 400.

        PRD §2.3: "A `limit` of 0, a `limit` of 101, and an `offset` of -1 are all
        rejected with `ERR_PAGINATION_INVALID` (HTTP 400); omitting both parameters
        entirely applies the defaults of 10 and 0 rather than erroring."

        Design: Corner/validations/pagination_limit_and_offset_bounds_return_invalid_request
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        register_affiliate(api, network["id"], partner_type="CONTENT")
        register_affiliate(api, network["id"], partner_type="COUPON")

        response = api.list_affiliates(PROGRAM_ADMIN, {"limit": limit, "offset": offset})

        assert_error_response(response, ERR_PAGINATION_INVALID, 400)

    def test_pagination_parameters_at_the_declared_bounds_are_accepted(self, api):
        """A limit of exactly 100 and an offset of 1 both page the two partners.

        PRD §2.3: "`limit` is the maximum number of rows to return; it defaults to 10
        when omitted, and an explicitly supplied value must be an integer of at least 1
        and at most 100. `offset` is the number of rows to skip; it defaults to 0 and an
        explicitly supplied value must be an integer of 0 or greater."

        Design: Corner/validations/pagination_limit_and_offset_bounds_return_invalid_request
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        register_affiliate(api, network["id"], partner_type="CONTENT")
        register_affiliate(api, network["id"], partner_type="COUPON")

        # 100 is the inclusive ceiling, so it must page rather than reject.
        full_rows, full_meta = assert_list_response(
            api.list_affiliates(PROGRAM_ADMIN, {"limit": 100, "offset": 0})
        )
        assert_pagination_meta(
            full_meta, limit=100, offset=0, total_count=2, has_more=False
        )
        assert len(full_rows) == 2, "both registered partners fit inside a limit of 100"

        tail_rows, tail_meta = assert_list_response(
            api.list_affiliates(PROGRAM_ADMIN, {"limit": 1, "offset": 1})
        )
        assert_pagination_meta(
            tail_meta, limit=1, offset=1, total_count=2, has_more=False
        )
        assert len(tail_rows) == 1, (
            "skipping one of two rows and taking one leaves exactly one row on the page"
        )


class TestUniquenessConstraintsOnOrdersAndApplications:
    def test_second_order_reusing_an_order_ref_is_rejected_and_persists_nothing(
        self, api
    ):
        """A double-fired conversion pixel reusing an `order_ref` books no second order.

        PRD §2.10 rule 41: "`order_ref` is unique across all orders — otherwise
        `ERR_DUPLICATE_ORDER_REF` (409). Applies to order creation, and deduplicates
        double-fired conversion pixels on the retailer side."

        Design: Corner/validations/duplicate_order_ref_and_second_open_application_rejected
        """
        pin_clock(api, CLOCK)
        first = create_conversion(
            api,
            order_ref="ORD-UNIQ-1",
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref="CUST-1",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            other_channel_touch="NONE",
        )

        response = api.create_conversion(
            f.conversion_payload(
                order_ref="ORD-UNIQ-1",
                order_total_cents=7777,
                product_category="HOME",
                customer_ref="CUST-9",
                is_new_customer=True,
                placed_at="2026-07-04T13:00:00.000Z",
                device_id="D9",
                other_channel_touch="NONE",
            ),
            TRACKING_INGESTOR,
        )

        # Uniqueness is global across orders, so a different total, category, buyer,
        # device and instant do not make the reused reference acceptable.
        assert_error_response(response, ERR_DUPLICATE_ORDER_REF, 409)

        rows, meta = assert_list_response(
            api.list_conversions(PROGRAM_ADMIN, {"limit": 10, "offset": 0})
        )
        assert_pagination_meta(meta, total_count=1)
        assert_field(rows[0], "id", first["id"])
        assert_cents(rows[0], "order_total_cents", 100000)

    def test_second_application_while_one_is_live_is_rejected_and_persists_nothing(
        self, api
    ):
        """A partner already holding a `SUBMITTED` application cannot file a second one.

        PRD §2.10 rule 40: "The partner has no application in a non-terminal review state
        — otherwise `ERR_DUPLICATE_APPLICATION` (409). Applies to application filing: one
        live application per partner, though a rejected history does not block a fresh
        filing."

        Design: Corner/validations/duplicate_order_ref_and_second_open_application_rejected
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        application = file_application(
            api,
            partner["id"],
            site_url="https://beacon.example",
            primary_traffic_source="ORGANIC_SEARCH",
            monthly_traffic_estimate=200000,
            declared_promo_methods=["EDITORIAL_CONTENT"],
            product_categories=["APPAREL"],
        )
        assert_field(application, "review_state", "SUBMITTED")

        response = api.create_application(
            partner["id"],
            f.application_payload(
                site_url="https://beacon.example/v2",
                primary_traffic_source="CONTENT_NEWSLETTER",
                monthly_traffic_estimate=210000,
                declared_promo_methods=["EMAIL"],
                product_categories=["APPAREL"],
            ),
            PARTNER_MANAGER,
        )

        assert_error_response(response, ERR_DUPLICATE_APPLICATION, 409)

        rows, meta = assert_list_response(
            api.list_applications(
                PARTNER_MANAGER,
                {"affiliate_id": partner["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        assert_fields(
            rows[0],
            {
                "id": application["id"],
                "review_state": "SUBMITTED",
                "revision_round_count": 0,
                "site_url": "https://beacon.example",
                "version": 1,
            },
        )


class TestSubAffiliateNestingLimits:
    def test_child_of_a_sub_network_is_depth_one_and_a_grandchild_is_refused(self, api):
        """One level of nesting is allowed; the level below it does not exist.

        PRD §2.10 rule 42: "The prospective sub-affiliate depth is at most 1 — otherwise
        `ERR_SUB_AFFILIATE_DEPTH_EXCEEDED` (422). Applies to partner registration."

        Design: Corner/validations/sub_affiliate_depth_and_non_sub_network_parent_rejected
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        parent = assert_created(
            api.create_affiliate(
                f.affiliate_payload(
                    network["id"],
                    partner_type="SUB_NETWORK",
                    legal_name="MetaNet Partners LLC",
                    contact_email="meta@example.com",
                ),
                ANONYMOUS,
            )
        )
        assert_field(parent, "sub_affiliate_depth", 0)

        child = assert_created(
            api.create_affiliate(
                f.affiliate_payload(
                    network["id"],
                    partner_type="SUB_NETWORK",
                    legal_name="MetaNet Child One LLC",
                    contact_email="child1@example.com",
                    parent_affiliate_id=parent["id"],
                ),
                PROGRAM_ADMIN,
            )
        )
        # §3.1: "The system derives `sub_affiliate_depth` from the parent chain: it is 0
        # when no parent is supplied, and otherwise one greater than the parent's own
        # depth."
        assert_fields(
            child, {"sub_affiliate_depth": 1, "parent_affiliate_id": parent["id"]}
        )

        response = api.create_affiliate(
            f.affiliate_payload(
                network["id"],
                partner_type="CONTENT",
                legal_name="MetaNet Grandchild LLC",
                contact_email="gchild@example.com",
                parent_affiliate_id=child["id"],
            ),
            PROGRAM_ADMIN,
        )

        assert_error_response(response, ERR_SUB_AFFILIATE_DEPTH_EXCEEDED, 422)

        rows, meta = assert_list_response(
            api.list_affiliates(
                PROGRAM_ADMIN,
                {"parent_affiliate_id": parent["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        assert_field(rows[0], "id", child["id"])

    def test_parent_that_is_not_a_sub_network_is_refused_after_the_depth_check_passes(
        self, api
    ):
        """Nesting under a content partner clears the depth gate and fails the type gate.

        PRD §2.10 rule 43: "A supplied `parent_affiliate_id` names a partner whose
        `partner_type` is `SUB_NETWORK`, and is not the row being created — otherwise
        `ERR_CIRCULAR_SUB_AFFILIATE` (422). Applies to partner registration."

        Design: Corner/validations/sub_affiliate_depth_and_non_sub_network_parent_rejected
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        content_parent = assert_created(
            api.create_affiliate(
                f.affiliate_payload(
                    network["id"],
                    partner_type="CONTENT",
                    legal_name="Beacon Content LLC",
                    contact_email="beacon@example.com",
                ),
                ANONYMOUS,
            )
        )
        assert_field(content_parent, "sub_affiliate_depth", 0)

        response = api.create_affiliate(
            f.affiliate_payload(
                network["id"],
                partner_type="CONTENT",
                legal_name="Wrong Parent LLC",
                contact_email="wrong@example.com",
                parent_affiliate_id=content_parent["id"],
            ),
            PROGRAM_ADMIN,
        )

        # The prospective depth is 1, so the lower-numbered depth rule passes and the
        # parent-type rule is the one that decides. §3.1: "Only a partner whose own
        # `partner_type` is `SUB_NETWORK` may parent another".
        assert_error_response(response, ERR_CIRCULAR_SUB_AFFILIATE, 422)

        _rows, meta = assert_list_response(
            api.list_affiliates(
                PROGRAM_ADMIN,
                {"parent_affiliate_id": content_parent["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=0)


class TestRateCardSupersessionOnActivation:
    def test_activating_an_identically_windowed_card_supersedes_the_incumbent(self, api):
        """An exactly equal window is the one overlap that supersedes instead of failing.

        PRD §3.3: "When the incumbent's window is **exactly equal** to the activating
        card's window, both bounds matching, the activation succeeds and supersedes the
        incumbent: the older card moves `ACTIVE → SUPERSEDED`, its
        `superseded_by_policy_id` is set to the activating card's identifier, and its
        `version` increments."

        Design: Corner/endpoints/activating_an_identical_window_policy_supersedes_the_incumbent
        """
        program = build_program(api, setup_clock=CLOCK, with_link=False)
        incumbent_before = program["policy"]
        successor = draft_policy(
            api,
            policy_code="APPAREL-CONTENT-V2",
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=800,
            returning_customer_rate_bps=300,
            effective_from=f.YEAR_2026_START,
            effective_to=f.YEAR_2027_START,
        )

        activated = assert_object_response(
            api.activate_commission_policy(
                successor["id"],
                f.activate_policy_payload(successor["version"]),
                PROGRAM_ADMIN,
            )
        )

        assert_field(activated, "status", "ACTIVE")
        assert_null(activated, "superseded_by_policy_id")

        incumbent = assert_object_response(
            api.get_commission_policy(incumbent_before["id"], PROGRAM_ADMIN)
        )
        assert_fields(
            incumbent,
            {
                "status": "SUPERSEDED",
                "superseded_by_policy_id": successor["id"],
            },
        )
        assert_version_bumped(
            incumbent, incumbent_before["version"], label="superseded rate card"
        )

        active_rows, active_meta = assert_list_response(
            api.list_commission_policies(
                PROGRAM_ADMIN,
                {
                    "status": "ACTIVE",
                    "product_category": "APPAREL",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert_pagination_meta(active_meta, total_count=1)
        assert_field(active_rows[0], "id", successor["id"])

        chain_rows, chain_meta = assert_list_response(
            api.list_commission_policies(
                PROGRAM_ADMIN,
                {
                    "superseded_by_policy_id": successor["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert_pagination_meta(chain_meta, total_count=1)
        assert_field(chain_rows[0], "id", incumbent_before["id"])

    def test_order_after_supersession_prices_at_the_successors_rate(self, api):
        """Only the surviving active card can price an order placed after supersession.

        PRD §3.5: "The candidate set is every rate card whose `status` is `ACTIVE`, whose
        `product_category` equals the order's `product_category`, whose
        `partner_type_scope` contains the winning partner's `partner_type`, and whose
        half-open window contains the order's `placed_at` — that is, `effective_from` is
        at or before `placed_at` and `effective_to` is strictly after it."

        Design: Corner/endpoints/activating_an_identical_window_policy_supersedes_the_incumbent
        """
        program = build_program(api, setup_clock=CLOCK)
        successor = draft_policy(
            api,
            policy_code="APPAREL-CONTENT-V2",
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=800,
            returning_customer_rate_bps=300,
            effective_from=f.YEAR_2026_START,
            effective_to=f.YEAR_2027_START,
        )
        assert_object_response(
            api.activate_commission_policy(
                successor["id"],
                f.activate_policy_payload(successor["version"]),
                PROGRAM_ADMIN,
            )
        )
        ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_10_00, device_id="D1"
        )
        order = create_conversion(
            api,
            order_ref="ORD-SUPERSEDE-1",
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref="CUST-1",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            other_channel_touch="NONE",
        )

        attributed = assert_object_response(
            api.attribute_conversion(
                order["id"],
                f.attribute_payload(order["version"]),
                TRACKING_INGESTOR,
            )
        )

        assert_fields(
            attributed,
            {
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "commission_policy_id": successor["id"],
            },
        )
        # A returning buyer prices at the successor's 300 bps: 100000 * 300 / 10000, and
        # a `MEDIUM`-tier `CONTENT` partner keeps the full 10000 bps credit share.
        assert_cents(attributed, "gross_commission_cents", 3000)
        assert_cents(attributed, "payable_commission_cents", 3000)


class TestDerivedFiguresAreReadableImmediatelyAfterTheWrite:
    def test_attribution_response_is_final_and_the_next_order_read_agrees(self, api):
        """The attribute call answers the fully priced order; the next read repeats it.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/derived_balances_and_batch_totals_are_readable_immediately_after_each_write
        """
        program = build_program(api, setup_clock=CLOCK)
        ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_10_00, device_id="D1"
        )
        order = create_conversion(
            api,
            order_ref="ORD-IMMEDIATE-1",
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref="CUST-1",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            other_channel_touch="NONE",
        )

        attributed = assert_object_response(
            api.attribute_conversion(
                order["id"], f.attribute_payload(order["version"]), TRACKING_INGESTOR
            )
        )

        # A returning buyer at the card's 400 bps: 100000 * 400 / 10000, and §3.5 leaves
        # the payable figure equal to the gross under the full 10000 bps credit share.
        assert_field(attributed, "attribution_status", "AFFILIATE_ATTRIBUTED")
        assert_cents(attributed, "gross_commission_cents", 4000)
        assert_cents(attributed, "payable_commission_cents", 4000)
        assert_version_bumped(attributed, order["version"], label="attributed order")
        assert_field(attributed, "attributed_affiliate_id", program["affiliate_id"])

        reread = assert_object_response(api.get_conversion(order["id"], FINANCE_ANALYST))
        assert_fields(
            reread,
            {
                "id": attributed["id"],
                "attribution_status": attributed["attribution_status"],
                "attributed_affiliate_id": attributed["attributed_affiliate_id"],
                "attributed_click_id": attributed["attributed_click_id"],
                "commission_policy_id": attributed["commission_policy_id"],
                "gross_commission_cents": 4000,
                "payable_commission_cents": 4000,
                "version": attributed["version"],
            },
        )

    def test_partner_balance_and_accrual_entry_are_visible_on_the_next_read(self, api):
        """The accrual and the balance it moved are both readable with no settling step.

        PRD §3.5: "An `ACCRUAL` ledger entry is appended for the partner in the amount of
        the payable commission, positive in sign. That ledger append raises the partner's
        `accrued_balance_cents` by the same amount."

        Design: Corner/consistency_model/derived_balances_and_batch_totals_are_readable_immediately_after_each_write
        """
        program = build_program(api, setup_clock=CLOCK)
        ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_10_00, device_id="D1"
        )
        order = create_conversion(
            api,
            order_ref="ORD-IMMEDIATE-1",
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref="CUST-1",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            other_channel_touch="NONE",
        )
        assert_object_response(
            api.attribute_conversion(
                order["id"], f.attribute_payload(order["version"]), TRACKING_INGESTOR
            )
        )

        partner = assert_object_response(
            api.get_affiliate(program["affiliate_id"], FINANCE_ANALYST)
        )
        assert_cents(partner, "accrued_balance_cents", 4000)
        # §3.9 moves money into `reserved_balance_cents` only on batch approval, and
        # `lifetime_paid_cents` only on payment, so both are still 0 here.
        assert_cents(partner, "reserved_balance_cents", 0)
        assert_cents(partner, "lifetime_paid_cents", 0)
        assert_field(partner, "attributed_conversion_count", 1)

        rows, meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"conversion_id": order["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=1)
        assert_append_only_row(rows[0])
        assert_fields(
            rows[0],
            {
                "entry_type": "ACCRUAL",
                "affiliate_id": program["affiliate_id"],
                "conversion_id": order["id"],
            },
        )
        assert_cents(rows[0], "amount_cents", 4000)
        # §3.6: "Its `payout_batch_id` is null while the entry is unbatched".
        assert_null(rows[0], "payout_batch_id")

    def test_batch_generation_totals_match_the_next_batch_read_and_stamp_the_accrual(
        self, api
    ):
        """The generation response's totals are final and the accrual is already stamped.

        PRD §3.9: "Generation happens in a fixed sequence inside that one request." "Each
        claimed entry has this batch stamped onto its `payout_batch_id`, and one **payout
        line** is created per distinct partner among them."

        Design: Corner/consistency_model/derived_balances_and_batch_totals_are_readable_immediately_after_each_write
        """
        program = build_program(api, setup_clock=CLOCK)
        valid_tax_document(api, program["affiliate_id"], treaty_withholding_bps=0)
        ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_10_00, device_id="D1"
        )
        order = create_conversion(
            api,
            order_ref="ORD-IMMEDIATE-1",
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref="CUST-1",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            other_channel_touch="NONE",
        )
        assert_object_response(
            api.attribute_conversion(
                order["id"], f.attribute_payload(order["version"]), TRACKING_INGESTOR
            )
        )
        accrual_rows, _accrual_meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"conversion_id": order["id"], "limit": 10, "offset": 0},
            )
        )
        accrual_id = accrual_rows[0]["id"]
        pin_clock(api, SETTLEMENT_CLOCK, headers=FINANCE_ANALYST)

        batch = assert_created(
            api.create_payout_batch(
                f.payout_batch_payload(
                    program["network_id"],
                    period_start=f.PERIOD_START_JUL,
                    period_end=f.PERIOD_END_AUG,
                ),
                FINANCE_ANALYST,
            )
        )

        # The network charges 0 bps and 0 cents flat and the partner's most recent tax
        # document is `VALID` at a treaty rate of 0 bps, so the single line's net equals
        # its 4000-cent gross and the batch totals are the sums of that one line.
        expected_totals = {
            "gross_commission_cents": 4000,
            "clawback_cents": 0,
            "network_fee_cents": 0,
            "withholding_cents": 0,
            "net_payable_cents": 4000,
        }
        for field, value in expected_totals.items():
            assert_cents(batch, field, value)
        assert_fields(batch, {"line_count": 1, "state": "DRAFT", "version": 1})

        reread = assert_object_response(
            api.get_payout_batch(batch["id"], FINANCE_ANALYST)
        )
        for field, value in expected_totals.items():
            assert_cents(reread, field, value)
        assert_fields(
            reread, {"line_count": 1, "state": "DRAFT", "version": batch["version"]}
        )

        stamped_rows, stamped_meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"payout_batch_id": batch["id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(stamped_meta, total_count=1)
        assert_fields(
            stamped_rows[0], {"id": accrual_id, "payout_batch_id": batch["id"]}
        )
