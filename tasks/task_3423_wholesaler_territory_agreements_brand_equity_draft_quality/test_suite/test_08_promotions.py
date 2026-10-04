"""Promotion programs: three-tier limits, half-open windows, opt-ins."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_promotion_payload,
    make_promotion,
    make_wholesaler_headers,
    setup_awarded_territory,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestThreeTierLimits:
    def test_promotion_with_mandated_retail_price_rejected(self, api, admin_headers):
        """PRD §2.8: "The brewer may never dictate retail price. A promotion
        program submitted with a `mandated_retail_price_cents` value present
        and non-null is rejected with `ERR_RETAIL_PRICE_MANDATE_PROHIBITED`
        (HTTP 422); the field must be null or absent."

        Design: Corner/validations/promotion_with_mandated_retail_price_rejected
        """
        resp = api.create_promotion(
            create_promotion_payload(mandated_retail_price_cents=599),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RETAIL_PRICE_MANDATE_PROHIBITED)

    def test_promotion_inverted_window_rejected(self, api, admin_headers):
        """PRD §3.9: "The end must be strictly after the start, else creation
        is rejected with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/promotion_inverted_window_rejected
        """
        resp = api.create_promotion(
            create_promotion_payload(starts_at="2026-10-01T00:00:00Z",
                                     ends_at="2026-10-01T00:00:00Z"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


@pytest.fixture
def adjacent_windows(api):
    """Existing OPEN BUD window [2026-10-01, 2026-11-01); then an adjacent
    BUD window, an overlapping BUD window, and the same window for MIC."""
    p1 = make_promotion(brand_code="BUD", starts_at="2026-10-01T00:00:00Z",
                        ends_at="2026-11-01T00:00:00Z", suggested_discount_pct=5)
    adjacent = api.create_promotion(
        create_promotion_payload(brand_code="BUD",
                                 starts_at="2026-09-01T00:00:00Z",
                                 ends_at="2026-10-01T00:00:00Z",
                                 suggested_discount_pct=3), ADMIN)
    overlapping = api.create_promotion(
        create_promotion_payload(brand_code="BUD",
                                 starts_at="2026-10-15T00:00:00Z",
                                 ends_at="2026-11-15T00:00:00Z",
                                 suggested_discount_pct=4), ADMIN)
    other_brand = api.create_promotion(
        create_promotion_payload(brand_code="MIC",
                                 starts_at="2026-10-15T00:00:00Z",
                                 ends_at="2026-11-15T00:00:00Z",
                                 suggested_discount_pct=4), ADMIN)
    return {"p1": p1, "adjacent": adjacent, "overlapping": overlapping,
            "other_brand": other_brand}


class TestHalfOpenWindowSemantics:
    def test_adjacent_window_accepted(self, api, adjacent_windows):
        """PRD §3.9: "Two programs for the same `brand_code` may not overlap
        while both are non-`CLOSED`; adjacency is allowed, so one program's
        `ends_at` may equal another's `starts_at` — anything tighter is
        rejected with `ERR_PROMOTION_WINDOW_OVERLAP`."
        PRD §3.9: "The window is half-open: `starts_at` is inclusive and
        `ends_at` is exclusive."

        Design: Difficulty/resource_temporal_overlap/promotion_half_open_window_adjacency
        """
        adjacent = validate_success(adjacent_windows["adjacent"], 201)
        assert adjacent["status"] == "OPEN", (
            "ends_at 2026-10-01 == existing starts_at 2026-10-01 is not overlap"
        )

    def test_overlap_rejected_but_scoped_per_brand(self, api, adjacent_windows):
        """PRD §3.9: "Two programs for the same `brand_code` may not overlap
        while both are non-`CLOSED`; adjacency is allowed, so one program's
        `ends_at` may equal another's `starts_at` — anything tighter is
        rejected with `ERR_PROMOTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/promotion_half_open_window_adjacency
        """
        validate_error(adjacent_windows["overlapping"],
                       ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP)
        other = validate_success(adjacent_windows["other_brand"], 201)
        assert other["status"] == "OPEN", (
            "overlap is scoped per brand_code; MIC is unaffected"
        )


class TestOptIns:
    def test_promotion_duplicate_opt_in_rejected(self, api):
        """PRD §3.9: "each wholesaler opts in at most once per program, a
        second attempt drawing `ERR_DUPLICATE_OPT_IN`."

        Design: Corner/validations/promotion_duplicate_opt_in_rejected
        """
        _, wo1, _ = setup_awarded_territory(territory_name="Opt Territory 1")
        _, wo2, _ = setup_awarded_territory(territory_name="Opt Territory 2")
        program = make_promotion(brand_code="BUD",
                                 starts_at="2026-09-01T00:00:00Z",
                                 ends_at="2026-12-01T00:00:00Z")

        first = api.opt_in(program["id"], make_wholesaler_headers(wo1["id"]))
        validate_success(first, 201)

        dup = api.opt_in(program["id"], make_wholesaler_headers(wo1["id"]))
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_OPT_IN)

        other = api.opt_in(program["id"], make_wholesaler_headers(wo2["id"]))
        data = validate_success(other, 201)
        assert len(data["opt_ins"]) == 2, (
            "uniqueness is per wholesaler, not per program"
        )

    def test_promotion_close_sweep_blocks_opt_in(self, api, admin_headers):
        """PRD §2.5: "Promotion programs whose window has ended close: a
        program in `OPEN` whose `ends_at` is at or before the new clock moves
        to `CLOSED`."
        PRD §3.9: "When the logical clock is set to an instant at or past a
        program's `ends_at`, the sweep of §2.5 moves the program `OPEN` →
        `CLOSED`, and from then on every opt-in attempt is rejected with
        `ERR_OPT_IN_WINDOW_CLOSED`."

        Design: Corner/state_machines/promotion_close_sweep_blocks_opt_in
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Promo Territory")
        program = make_promotion(brand_code="BUD",
                                 starts_at="2026-08-01T00:00:00Z",
                                 ends_at="2026-09-15T00:00:00Z")

        sweep = validate_success(
            api.set_clock({"to_iso8601": "2026-09-16T00:00:00Z"}, ADMIN), 200
        )
        assert sweep["promotions_closed_count"] == 1

        resp = api.opt_in(program["id"], make_wholesaler_headers(wholesaler["id"]))
        validate_error(resp, ApiErrorId.ERR_OPT_IN_WINDOW_CLOSED)
