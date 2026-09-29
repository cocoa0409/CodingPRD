"""Settlement windows are half-open, so they may abut but never intersect, and the
exclusion is scoped to one partner."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_batch,
    create_settlement_batch_payload,
    get_success_data,
    read_partner,
    setup_live_partner,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PO

OVERLAP_START = "2026-07-14T23:59:59Z"
OVERLAP_END = "2026-07-16T00:00:00Z"


def _live_partner(legal_name, open_the_cycle):
    return setup_live_partner(
        partner_overrides={
            "legal_name": legal_name,
            "business_model": "PAYMENT_FACILITATION",
            "funding_stage": "SERIES_A",
            "months_runway": 24,
            "disclosed_complaints_per_10k": 2.00,
            "end_user_account_count": 1500,
        },
        agreement_overrides={
            "reserve_requirement_bps": 500,
            "termination_triggers": ["VOLUNTARY"],
        },
        fbo_balance_cents=5_000_000,
        reserve_balance_cents=312_500,
        open_the_cycle=open_the_cycle,
    )


def _subject_with_a_first_window():
    ctx = _live_partner("Meridian Settlements Inc", True)
    ctx["first"] = create_batch(
        ctx["partner"]["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-15T00:00:00Z",
        gross_settlement_cents=3_000_000,
        interchange_cents=0,
        returns_cents=0,
        partner_reported_net_cents=3_000_000,
    )
    assert ctx["first"]["reconciliation_status"] == "UNRECONCILED", (
        "the exclusion is independent of the reconciliation dimension"
    )
    return ctx


class TestSettlementWindowExclusion:
    def test_windows_may_touch_on_either_side_but_not_intersect(self):
        """Two windows for the same partner may abut but never overlap: a new batch may start at
        exactly a prior batch's `window_end`, and may end at exactly a prior batch's `window_start`.
        Intersection — meaning the new `window_start` is strictly before an existing `window_end`
        *and* that existing `window_start` is strictly before the new `window_end` — is refused with
        `ERR_SETTLEMENT_WINDOW_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/settlement_windows_may_abut_but_never_intersect_for_one_partner
        """
        ctx = _subject_with_a_first_window()
        partner_id = ctx["partner"]["id"]

        after = api_client.create_settlement_batch(
            create_settlement_batch_payload(
                partner_id,
                window_start="2026-07-15T00:00:00Z",
                window_end="2026-07-29T00:00:00Z",
                gross_settlement_cents=1_000_000,
                interchange_cents=0,
                returns_cents=0,
                partner_reported_net_cents=1_000_000,
            ),
            PO,
        )
        validate_success(after, 201)

        before = api_client.create_settlement_batch(
            create_settlement_batch_payload(
                partner_id,
                window_start="2026-06-17T00:00:00Z",
                window_end="2026-07-01T00:00:00Z",
                gross_settlement_cents=900_000,
                interchange_cents=0,
                returns_cents=0,
                partner_reported_net_cents=900_000,
            ),
            PO,
        )
        validate_success(before, 201)

        intersecting = api_client.create_settlement_batch(
            create_settlement_batch_payload(
                partner_id,
                window_start=OVERLAP_START,
                window_end=OVERLAP_END,
                gross_settlement_cents=500_000,
                interchange_cents=0,
                returns_cents=0,
                partner_reported_net_cents=500_000,
            ),
            PO,
        )
        validate_error(intersecting, ApiErrorId.ERR_SETTLEMENT_WINDOW_OVERLAP, 409)

        rows = get_success_data(
            api_client.list_settlement_batches(PO, {"partner_id": partner_id, "limit": 100})
        )
        assert len(rows) == 3, [r["window_start"] for r in rows]
        partner = read_partner(partner_id)
        assert partner["oversight_posture"] == "OPEN"
        assert partner["reserve_shortfall_cents"] == 0

    def test_the_same_overlapping_window_is_free_on_another_partner(self):
        """Settlement windows for one partner are half-open, running from `window_start` inclusive up
        to `window_end` exclusive, and `window_end` must be strictly later than `window_start`, else
        `ERR_INVALID_INTERVAL`.

        Design: Difficulty/resource_temporal_overlap/settlement_windows_may_abut_but_never_intersect_for_one_partner
        """
        ctx = _subject_with_a_first_window()
        partner_id = ctx["partner"]["id"]
        control = _live_partner("Quadrant Settlements Inc", False)
        control_id = control["partner"]["id"]

        validate_error(
            api_client.create_settlement_batch(
                create_settlement_batch_payload(
                    partner_id,
                    window_start=OVERLAP_START,
                    window_end=OVERLAP_END,
                    gross_settlement_cents=500_000,
                    interchange_cents=0,
                    returns_cents=0,
                    partner_reported_net_cents=500_000,
                ),
                PO,
            ),
            ApiErrorId.ERR_SETTLEMENT_WINDOW_OVERLAP,
            409,
        )

        accepted = validate_success(
            api_client.create_settlement_batch(
                create_settlement_batch_payload(
                    control_id,
                    window_start=OVERLAP_START,
                    window_end=OVERLAP_END,
                    gross_settlement_cents=500_000,
                    interchange_cents=0,
                    returns_cents=0,
                    partner_reported_net_cents=500_000,
                ),
                PO,
            ),
            201,
        )
        assert_same_instant(accepted["window_start"], OVERLAP_START, "window_start")
        assert_same_instant(accepted["window_end"], OVERLAP_END, "window_end")

        subject_rows = get_success_data(
            api_client.list_settlement_batches(PO, {"partner_id": partner_id, "limit": 100})
        )
        control_rows = get_success_data(
            api_client.list_settlement_batches(PO, {"partner_id": control_id, "limit": 100})
        )
        assert len(subject_rows) == 1
        assert len(control_rows) == 1
