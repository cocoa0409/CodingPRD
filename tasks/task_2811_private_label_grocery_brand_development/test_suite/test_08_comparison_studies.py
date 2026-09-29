"""Benchmarking against the national brand: parity indices, preference shares
and the tier gate they open."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_item_state,
    assert_status,
    assert_two_decimal_value,
    assert_version_is,
)
from test_helpers.constants import (
    ITEM_BENCHMARKED,
    POSTURE_GREEN,
    STUDY_CONSUMER_PANEL,
    STUDY_FINALIZED,
    VERDICT_INFERIOR,
    VERDICT_PARITY,
    VERDICT_SUPERIOR,
)
from test_helpers.fixtures import build_chain, read_item
from test_helpers.test_users import QUALITY_HEADERS


def test_preference_share_of_exactly_forty_five_reads_parity(api):
    """The PARITY threshold is inclusive, so exactly 45.00 is not INFERIOR.

    PRD 3.4: "The `verdict` is `SUPERIOR` when the share is at least 55.00;
    failing that, `PARITY` when the share is at least 45.00; otherwise
    `INFERIOR`."

    PRD 3.4: "A panel of 140 recording 45 preferring the private label, 55
    preferring the national brand and 40 expressing no preference reads exactly
    45.00 and therefore `PARITY` at the inclusive boundary"

    Design: Difficulty/boundary_precision_check/panel_preference_share_exactly_45_is_parity
    """
    ctx = build_chain(api, upto=15)

    panel = validate_success(
        api.finalize_study(ctx["panel_study_id"], QUALITY_HEADERS)
    )

    assert_two_decimal_value(
        panel["preference_share_pct"], 45.00, "preference_share_pct"
    )
    assert panel["verdict"] == VERDICT_PARITY
    assert_status(panel, STUDY_FINALIZED, "comparison study")
    assert panel["parity_index"] is None, "a consumer panel's parity_index stays null"


def test_no_preference_panelists_are_excluded_from_the_share_denominator(api):
    """Folding the undecided panelists in would read 32.14 and INFERIOR instead.

    PRD 3.4: "The denominator is `prefer_pl_count` plus `prefer_nb_count` —
    `no_preference_count` sits inside `n_panelists` but is deliberately
    **excluded** from the denominator."

    PRD 3.4: "A panel of 140 recording 45 preferring the private label, 55
    preferring the national brand and 40 expressing no preference reads exactly
    45.00 and therefore `PARITY` at the inclusive boundary — whereas folding the
    no-preference panelists into the denominator would read 32.14 and `INFERIOR`."

    PRD 3.4: "An `NBE` item needs a finalized bench-top study whose `parity_index`
    is at least 85.00 **and** a finalized consumer panel whose `verdict` is
    `PARITY` or `SUPERIOR`."

    Design: Difficulty/boundary_precision_check/panel_preference_share_exactly_45_is_parity
    """
    ctx = build_chain(api, upto=15)

    panel = validate_success(
        api.finalize_study(ctx["panel_study_id"], QUALITY_HEADERS)
    )

    assert panel["n_panelists"] == 140
    assert panel["prefer_pl_count"] == 45
    assert panel["prefer_nb_count"] == 55
    assert panel["no_preference_count"] == 40
    assert_two_decimal_value(
        panel["preference_share_pct"], 45.00, "preference_share_pct"
    )
    assert panel["verdict"] == VERDICT_PARITY

    bench = validate_success(api.get_study(ctx["bench_study_id"], QUALITY_HEADERS))
    assert_two_decimal_value(bench["parity_index"], 93.00, "parity_index")
    assert bench["verdict"] == VERDICT_PARITY
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_BENCHMARKED, POSTURE_GREEN)


def test_bench_top_superior_needs_a_strictly_positive_flavor_delta(api, sourced_item):
    """Two studies with the same index split on the sign of the flavor delta.

    PRD 3.4: "The `verdict` is then `SUPERIOR` when the parity index is at least
    95.00 **and** `flavor_delta` is strictly positive; failing that, `PARITY` when
    the parity index is at least 85.00; otherwise `INFERIOR`."

    PRD 3.4: "Because the penalty uses absolute magnitudes, being better than the
    national brand still costs index points — and because `SUPERIOR` additionally
    demands a strictly positive flavor delta, a high index earned by being
    different in the wrong direction can never read `SUPERIOR`."

    Design: Corner/calculations/bench_top_superior_verdict_requires_strictly_positive_flavor_delta
    """
    item_id = sourced_item["item_id"]
    better = validate_success(
        api.create_study(
            f.bench_top_payload(
                item_id,
                nb_control_lot_code="SB-2026-201",
                appearance_delta=0.0,
                aroma_delta=0.0,
                texture_delta=0.0,
                flavor_delta=0.5,
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )
    better = validate_success(api.finalize_study(better["id"], QUALITY_HEADERS))
    worse = validate_success(
        api.create_study(
            f.bench_top_payload(
                item_id,
                nb_control_lot_code="SB-2026-202",
                appearance_delta=0.0,
                aroma_delta=0.0,
                texture_delta=0.0,
                flavor_delta=-0.5,
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )

    worse = validate_success(api.finalize_study(worse["id"], QUALITY_HEADERS))

    assert_two_decimal_value(better["parity_index"], 96.00, "parity_index")
    assert better["verdict"] == VERDICT_SUPERIOR
    assert_two_decimal_value(worse["parity_index"], 96.00, "parity_index")
    assert worse["verdict"] == VERDICT_PARITY, (
        "the same index with a negative flavor delta cannot read SUPERIOR"
    )
    assert_status(worse, STUDY_FINALIZED, "comparison study")
    assert worse["preference_share_pct"] is None


def test_panel_with_no_stated_preference_reads_zero_and_inferior(api, sourced_item):
    """An all-undecided panel is defined to 0.00, not an arithmetic error.

    PRD 3.4: "When that denominator is zero the share is defined as 0.00;
    otherwise the share is the private-label preference count multiplied by 100
    and divided by the denominator, rounded half up to two decimals."

    Design: Corner/calculations/panel_preference_share_zero_denominator_yields_inferior_not_error
    """
    undecided = validate_success(
        api.create_study(
            f.consumer_panel_payload(
                sourced_item["item_id"],
                nb_control_lot_code="SB-2026-203",
                n_panelists=120,
                prefer_pl_count=0,
                prefer_nb_count=0,
                no_preference_count=120,
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )
    assert undecided["study_type"] == STUDY_CONSUMER_PANEL

    finalized = validate_success(api.finalize_study(undecided["id"], QUALITY_HEADERS))

    assert_two_decimal_value(
        finalized["preference_share_pct"], 0.00, "preference_share_pct"
    )
    assert finalized["verdict"] == VERDICT_INFERIOR
    assert_status(finalized, STUDY_FINALIZED, "comparison study")
    assert finalized["parity_index"] is None
    assert_version_is(finalized, 2, "comparison study")


def test_finalizing_a_study_twice_is_rejected(api):
    """Finalization is terminal and cannot recompute the index it already wrote.

    PRD 3.4: "Finalizing a study moves it `DRAFT → FINALIZED`, which is terminal;
    finalizing one that is already `FINALIZED` is refused with
    `ERR_STUDY_NOT_DRAFT` (HTTP 409)."

    Design: Corner/state_machines/study_finalize_twice_rejected
    """
    ctx = build_chain(api, upto=14)

    response = api.finalize_study(ctx["bench_study_id"], QUALITY_HEADERS)
    validate_error(response, ApiErrorId.ERR_STUDY_NOT_DRAFT.value, 409)

    bench = validate_success(api.get_study(ctx["bench_study_id"], QUALITY_HEADERS))
    assert_status(bench, STUDY_FINALIZED, "comparison study")
    assert_two_decimal_value(bench["parity_index"], 93.00, "parity_index")
    assert bench["verdict"] == VERDICT_PARITY
