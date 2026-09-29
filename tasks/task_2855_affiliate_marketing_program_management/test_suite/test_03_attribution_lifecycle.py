"""Running attribution on an order: the single run, its fork paths and its audit rows."""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_CONVERSION_ALREADY_ATTRIBUTED
from test_helpers.assertions import (
    assert_cents,
    assert_bps,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_null,
    assert_pagination_meta,
    assert_version_bumped,
    assert_version_unchanged,
    rows_by,
)
from test_helpers.constants import (
    VARIANT_INCREMENTALITY_ADJUSTED,
    VARIANT_LAST_CLICK_RAW,
)
from test_helpers.fixtures import (
    attribute,
    attributed_order,
    build_program,
    create_conversion,
    ingest_click,
    read_affiliate,
    read_conversion,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    TRACKING_INGESTOR,
)

CLOCK = f.JUL_05_00_00
CLICK_AT = f.JUL_04_10_00
FORCED_CLICK_AT = f.JUL_04_11_00
PLACED_AT = f.JUL_04_12_00
#: One millisecond after the winning click — a strictly later non-affiliate touch.
TOUCH_ONE_MS_LATER = "2026-07-04T10:00:00.001Z"
#: Exactly the winning click's instant — the tie that keeps credit with the affiliate.
TOUCH_AT_CLICK_INSTANT = f.JUL_04_10_00

LINK_KWARGS = {"cookie_window_days": 30, "device_graph_enabled": False}


def _decisions(api, conversion_id, params=None):
    """Read an order's attribution decisions and return ``(rows, meta)``."""
    query = {"limit": 10, "offset": 0}
    query.update(params or {})
    return assert_list_response(
        api.list_attribution_decisions(conversion_id, COMPLIANCE_ANALYST, query)
    )


class TestAttributionRunIsTerminalOnTheCreditDimension:
    def test_second_attribution_run_on_an_attributed_order_is_refused(self, api):
        """An order that already carries credit cannot be run through attribution again.

        PRD §3.5: "Attribution is then resolved in a single run, guarded by
        `expected_conversion_version`, and only while the order is still `UNATTRIBUTED`
        — a second run on an order whose credit dimension has already moved is refused
        with `ERR_CONVERSION_ALREADY_ATTRIBUTED`."

        Design: Corner/state_machines/attribute_twice_on_same_conversion_rejected
        """
        program = build_program(api, setup_clock=CLOCK, link_kwargs=LINK_KWARGS)
        booked = attributed_order(
            api,
            program,
            order_total_cents=100000,
            is_new_customer=False,
            click_at=CLICK_AT,
            placed_at=PLACED_AT,
            order_ref="ORD-DUP-1",
        )
        conversion_id = booked["conversion_id"]

        # §3.5: "The raw commission — stored as `gross_commission_cents` — is the
        # order's `order_total_cents` multiplied by that rate in basis points, divided
        # by 10,000, and rounded half up to a whole cent."  100000 × 400 / 10000 = 4000.
        before = read_conversion(api, conversion_id)
        assert_fields(before, {"attribution_status": "AFFILIATE_ATTRIBUTED"})
        assert_cents(before, "gross_commission_cents", 4000)
        assert_cents(before, "payable_commission_cents", 4000)
        partner_before = read_affiliate(api, program["affiliate_id"])

        # The guard field carries the version the client has just observed, so §2.10
        # rule 20 decides the response rather than the rule 30 stale-version guard.
        response = api.attribute_conversion(
            conversion_id, f.attribute_payload(before["version"]), TRACKING_INGESTOR
        )

        assert_error_response(response, ERR_CONVERSION_ALREADY_ATTRIBUTED, 409)

        after = read_conversion(api, conversion_id)
        assert_fields(after, {"attribution_status": "AFFILIATE_ATTRIBUTED"})
        assert_cents(after, "gross_commission_cents", 4000)
        assert_cents(after, "payable_commission_cents", 4000)
        assert_version_unchanged(after, before["version"], "conversion")

        # §3.5: "An `ACCRUAL` ledger entry is appended for the partner in the amount of
        # the payable commission" — exactly once, for the one run that succeeded.
        entries, meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"conversion_id": conversion_id, "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(meta, total_count=1, has_more=False)
        assert_field(entries[0], "entry_type", "ACCRUAL")
        assert_cents(entries[0], "amount_cents", 4000)

        partner_after = read_affiliate(api, program["affiliate_id"])
        assert_field(partner_after, "attributed_conversion_count", 1)
        assert_cents(partner_after, "accrued_balance_cents", 4000)
        assert_version_unchanged(
            partner_after, partner_before["version"], "affiliate"
        )


class TestAttributionForkPaths:
    """The three outcomes one shared click set can produce for three orders."""

    def test_attribution_over_an_empty_eligible_set_succeeds_and_books_nothing(self, api):
        """An order placed on a device no organic click was seen on keeps no credit at all.

        PRD §3.5: "If the eligible set is empty the run still succeeds with 200:
        `candidate_click_count` is 0, the order stays `UNATTRIBUTED`,
        `gross_commission_cents` and `payable_commission_cents` are 0, no ledger entry is
        appended, and — because the order remains `UNATTRIBUTED` — a later run after a
        fresh click arrives can still win it. Two audit rows are written even in this
        case, one per algorithm variant, each with `candidate_click_count` 0,
        `credit_share_bps` 0, `computed_commission_cents` 0 and a `dedup_reason` of
        `NO_ELIGIBLE_CLICK`, and the order's `version` increments by 1."

        Design: Corner/state_machines/attribute_fork_paths_empty_click_set_dedup_and_dedup_tie_boundary
        """
        program = build_program(api, setup_clock=CLOCK, link_kwargs=LINK_KWARGS)
        ingest_click(api, program["link_id"], occurred_at=CLICK_AT, device_id="D1")
        ingest_click(
            api,
            program["link_id"],
            occurred_at=FORCED_CLICK_AT,
            device_id="D1",
            click_type="FORCED_CLICK",
            referrer_domain="shady.example",
        )
        # §3.5 step one requires that "the click matches the order's device", and this
        # order was placed on a device no click was ever seen on.
        created = create_conversion(
            api,
            order_ref="ORD-FORK-A",
            order_total_cents=100000,
            is_new_customer=False,
            placed_at=PLACED_AT,
            device_id="D9",
            other_channel_touch="NONE",
        )

        order = attribute(api, created["id"], created["version"])

        assert_fields(
            order,
            {"attribution_status": "UNATTRIBUTED", "candidate_click_count": 0},
        )
        assert_cents(order, "gross_commission_cents", 0)
        assert_cents(order, "payable_commission_cents", 0)
        assert_null(order, "attributed_affiliate_id")
        assert_version_bumped(order, created["version"], "conversion")

        rows, meta = _decisions(api, created["id"])
        assert_pagination_meta(meta, total_count=2, has_more=False)
        by_variant = rows_by(rows, "algorithm_variant")
        assert set(by_variant) == {VARIANT_LAST_CLICK_RAW, VARIANT_INCREMENTALITY_ADJUSTED}, (
            "one audit row per declared variant must be written even with no eligible click"
        )
        for row in by_variant.values():
            assert_field(row, "conversion_id", created["id"])
            assert_field(row, "candidate_click_count", 0)
            assert_field(row, "dedup_reason", "NO_ELIGIBLE_CLICK")
            assert_bps(row, "credit_share_bps", 0)
            assert_cents(row, "computed_commission_cents", 0)
            # §3.5: the winning click instant is "left null when the candidate set was empty".
            assert_null(row, "winning_click_occurred_at")
        # §3.5: "a `selected` boolean that is true on exactly one row per run".
        assert sum(1 for row in rows if row["selected"]) == 1, (
            "exactly one audit row per run carries selected true"
        )

        _entries, ledger_meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"affiliate_id": program["affiliate_id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(ledger_meta, total_count=0, has_more=False)

    def test_other_channel_touch_after_the_winning_click_dedupes_the_affiliate_out(
        self, api
    ):
        """A non-affiliate touch one millisecond after the winning click takes last click.

        PRD §3.5: "The order moves `UNATTRIBUTED → DEDUPED_TO_OTHER_CHANNEL`, its
        `attributed_affiliate_id` is left null while `attributed_click_id` still records
        the winning click, both `gross_commission_cents` and `payable_commission_cents`
        are 0, and the two audit rows are written with `credit_share_bps` 0,
        `computed_commission_cents` 0 and a `dedup_reason` of
        `OTHER_CHANNEL_LATER_TOUCH`, with the raw last-click variant marked as the
        selected one."

        Design: Corner/state_machines/attribute_fork_paths_empty_click_set_dedup_and_dedup_tie_boundary
        """
        program = build_program(api, setup_clock=CLOCK, link_kwargs=LINK_KWARGS)
        organic = ingest_click(
            api, program["link_id"], occurred_at=CLICK_AT, device_id="D1"
        )
        # §3.5: "its `click_type` is `ORGANIC_CLICK`, so a `FORCED_CLICK` and an
        # `IFRAME_IMPRESSION` never attribute at all" — this later click stays out.
        ingest_click(
            api,
            program["link_id"],
            occurred_at=FORCED_CLICK_AT,
            device_id="D1",
            click_type="FORCED_CLICK",
            referrer_domain="shady.example",
        )
        created = create_conversion(
            api,
            order_ref="ORD-FORK-B",
            order_total_cents=100000,
            is_new_customer=False,
            placed_at=PLACED_AT,
            device_id="D1",
            other_channel_touch="PAID_SOCIAL",
            other_channel_touch_at=TOUCH_ONE_MS_LATER,
        )
        partner_before = read_affiliate(api, program["affiliate_id"])

        order = attribute(api, created["id"], created["version"])

        assert_fields(
            order,
            {
                "attribution_status": "DEDUPED_TO_OTHER_CHANNEL",
                "candidate_click_count": 1,
                "attributed_click_id": organic["id"],
            },
        )
        assert_cents(order, "gross_commission_cents", 0)
        assert_cents(order, "payable_commission_cents", 0)
        assert_null(order, "attributed_affiliate_id")
        assert_version_bumped(order, created["version"], "conversion")

        rows, meta = _decisions(api, created["id"])
        assert_pagination_meta(meta, total_count=2, has_more=False)
        by_variant = rows_by(rows, "algorithm_variant")
        for row in by_variant.values():
            assert_field(row, "dedup_reason", "OTHER_CHANNEL_LATER_TOUCH")
            assert_bps(row, "credit_share_bps", 0)
            assert_cents(row, "computed_commission_cents", 0)
        assert_field(by_variant[VARIANT_LAST_CLICK_RAW], "selected", True)
        assert_field(by_variant[VARIANT_INCREMENTALITY_ADJUSTED], "selected", False)

        # §3.5: "No ledger entry is appended and every counter and balance on every
        # partner is left exactly as it was; only the order's `version` increments."
        _entries, ledger_meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"affiliate_id": program["affiliate_id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(ledger_meta, total_count=0, has_more=False)
        partner_after = read_affiliate(api, program["affiliate_id"])
        assert_field(partner_after, "attributed_conversion_count", 0)
        assert_cents(partner_after, "accrued_balance_cents", 0)
        assert_version_unchanged(partner_after, partner_before["version"], "affiliate")

    def test_other_channel_touch_tied_with_the_winning_click_keeps_full_credit(self, api):
        """A non-affiliate touch at exactly the click instant does not dedupe the sale.

        PRD §3.5: "A tie does **not** dedupe: an `other_channel_touch_at` exactly equal
        to the winning click's `occurred_at` leaves the credit with the affiliate."

        Design: Corner/state_machines/attribute_fork_paths_empty_click_set_dedup_and_dedup_tie_boundary
        """
        program = build_program(api, setup_clock=CLOCK, link_kwargs=LINK_KWARGS)
        organic = ingest_click(
            api, program["link_id"], occurred_at=CLICK_AT, device_id="D1"
        )
        ingest_click(
            api,
            program["link_id"],
            occurred_at=FORCED_CLICK_AT,
            device_id="D1",
            click_type="FORCED_CLICK",
            referrer_domain="shady.example",
        )
        created = create_conversion(
            api,
            order_ref="ORD-FORK-C",
            order_total_cents=100000,
            is_new_customer=False,
            placed_at=PLACED_AT,
            device_id="D1",
            other_channel_touch="EMAIL",
            other_channel_touch_at=TOUCH_AT_CLICK_INSTANT,
        )

        order = attribute(api, created["id"], created["version"])

        assert_fields(
            order,
            {
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "candidate_click_count": 1,
                "attributed_click_id": organic["id"],
                "attributed_affiliate_id": program["affiliate_id"],
                "commission_policy_id": program["policy_id"],
            },
        )
        # §3.5: a `MEDIUM` partner takes the raw variant, where "`credit_share_bps` is
        # 10000, so the payable commission equals the gross commission exactly".
        assert_cents(order, "gross_commission_cents", 4000)
        assert_cents(order, "payable_commission_cents", 4000)
        assert_version_bumped(order, created["version"], "conversion")

        entries, ledger_meta = assert_list_response(
            api.list_ledger_entries(
                FINANCE_ANALYST,
                {"affiliate_id": program["affiliate_id"], "limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(ledger_meta, total_count=1, has_more=False)
        assert_field(entries[0], "entry_type", "ACCRUAL")
        assert_cents(entries[0], "amount_cents", 4000)

        partner_after = read_affiliate(api, program["affiliate_id"])
        assert_field(partner_after, "attributed_conversion_count", 1)
        assert_cents(partner_after, "accrued_balance_cents", 4000)


class TestAttributionDecisionRead:
    def test_attribution_decisions_read_filters_by_algorithm_variant(self, api):
        """Both variants are readable per order, and the counterfactual one is filterable.

        PRD §3.5: "Every attribution run writes exactly one row per declared variant
        against the order's `conversion_id`, so both algorithms remain inspectable even
        though only one drives the ledger."

        PRD §3.5: "These rows are append-only and are listable per order with an
        optional `algorithm_variant` filter."

        Design: Corner/endpoints/attribution_decisions_read_filters_by_algorithm_variant
        """
        program = build_program(api, setup_clock=CLOCK, link_kwargs=LINK_KWARGS)
        booked = attributed_order(
            api,
            program,
            order_total_cents=100000,
            is_new_customer=False,
            click_at=CLICK_AT,
            placed_at=PLACED_AT,
            order_ref="ORD-DECISIONS-1",
        )
        conversion_id = booked["conversion_id"]

        rows, meta = _decisions(api, conversion_id)

        assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
        assert len(rows) == 2, "both declared variants are always materialised"

        raw_rows, raw_meta = _decisions(
            api, conversion_id, {"algorithm_variant": VARIANT_LAST_CLICK_RAW}
        )
        assert_pagination_meta(raw_meta, total_count=1, has_more=False)
        raw = raw_rows[0]
        assert_fields(
            raw,
            {
                "algorithm_variant": VARIANT_LAST_CLICK_RAW,
                "conversion_id": conversion_id,
                "selected": True,
                "candidate_click_count": 1,
                "winning_click_occurred_at": CLICK_AT,
                # §3.5: "`DEVICE_EXACT` when the winner matched on the device identifier".
                "device_match_mode": "DEVICE_EXACT",
            },
        )
        # §3.5: a `MEDIUM` `CONTENT` partner drives the raw variant, under which
        # "`credit_share_bps` is 10000, so the payable commission equals the gross
        # commission exactly".
        assert_bps(raw, "credit_share_bps", 10000)
        assert_cents(raw, "computed_commission_cents", 4000)

        adjusted_rows, adjusted_meta = _decisions(
            api, conversion_id, {"algorithm_variant": VARIANT_INCREMENTALITY_ADJUSTED}
        )
        assert_pagination_meta(adjusted_meta, total_count=1, has_more=False)
        adjusted = adjusted_rows[0]
        assert_fields(
            adjusted,
            {
                "algorithm_variant": VARIANT_INCREMENTALITY_ADJUSTED,
                "conversion_id": conversion_id,
                "selected": False,
            },
        )
        # §3.5: "Under it `credit_share_bps` is 3000, so the payable commission is thirty
        # per cent of the gross rounded half up to a whole cent" — 4000 × 3000 / 10000.
        assert_bps(adjusted, "credit_share_bps", 3000)
        assert_cents(adjusted, "computed_commission_cents", 1200)
