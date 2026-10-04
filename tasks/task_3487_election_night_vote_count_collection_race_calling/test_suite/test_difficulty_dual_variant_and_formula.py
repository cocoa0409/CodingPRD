"""Difficulty-design tests: dual-variant calculations and combinatorial formulas.

Covers the outstanding-vote estimate variants (historical vs survey), the two
reliability-score windows (CAREER vs RECENT_FORM), the multi-input publish
gate, and the pinned round-then-sum invoice pricing (PRD §3.3, §3.5, §3.6, §3.8).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    ANALYST_NINA_ID,
    CHIEF_RAY_ID,
    assert_tabulation_board,
    get_contest,
    get_stringer,
    get_tabulation,
    list_customer_deliveries,
    make_analyst_headers,
    propose_call,
    publish_call,
    setup_standard_universe,
    setup_universe_with_reports,
    solano_payload,
    create_assignment,
    create_stringer_with_no_show_history,
    generate_invoice,
)


def test_outstanding_estimate_historical_vs_survey_diverge(api):
    """PRD §3.5: "The historical estimate scales the county's `expected_vote_total`
    by the share of precincts not yet reporting: the expected total multiplied by
    the ratio of remaining precincts to `expected_precincts`, rounded down to a
    whole vote, with a county that has no accepted report counting zero precincts
    reported."
    PRD §3.5: "The survey estimate, defined only when the county's
    `survey_turnout_estimate` is not null, is that estimate minus the votes
    already reported for the county, floored at zero; when the survey estimate
    is null, the survey estimate falls back to the historical estimate."
    PRD §3.5: "The county's outstanding figure is the larger of the two variants,
    and the contest's `outstanding_estimate` is the sum of those per-county
    figures — so a fully reported county contributes zero."

    Design: Difficulty/dual_variant_calc/outstanding_estimate_historical_vs_survey_diverge
    """
    # Solano joins with survey_turnout_estimate=9000 and no report, so its
    # survey variant (9000) dominates its historical variant (3000) — the
    # mirror of Alameda, where the historical variant dominates. The pinned
    # contest-level `outstanding_estimate` therefore witnesses the per-county
    # max() composition in both directions: historical-only would sum 12000,
    # survey-only 14000, correct max() 18000. (PRD pins the per-county detail
    # array but never its entry key names, so the composition is asserted
    # through the contest-level total.)
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
        advance_to="TABULATION",
        extra_counties=[("solano", solano_payload(survey_turnout_estimate=9000))],
    )
    contest_id = universe["contest"]["id"]
    report = universe["reports"][0]
    assert report["status"] == "ACCEPTED"
    assert report["reported_total"] == 7000
    assert report["deviation_ratio"] == 0.3

    board = get_tabulation(contest_id, headers=make_analyst_headers())
    assert_tabulation_board(board)
    # Alameda:  historical floor(10000*(10-5)/10)=5000 vs survey 8000-7000=1000
    # Contra Costa (unreported): historical 4000; survey null -> falls back
    # Solano (unreported): historical 3000 vs survey 9000 -> survey wins
    assert board["outstanding_estimate"] == 18000
    assert len(board["outstanding_detail"]) == 3


def test_reliability_career_vs_recent_form_diverge(api):
    """PRD §3.3: "The `CAREER` variant counts those outcomes over every election
    event in which the stringer holds or ever held an assignment. The
    `RECENT_FORM` variant counts only events whose `event_date` falls later than
    the date three hundred sixty-five days before the evaluated event's own
    `event_date`, so old no-shows age out: a stringer who no-showed two years ago
    and has been clean since scores 100 on `RECENT_FORM` but 75 on `CAREER`."
    PRD §3.3: "a bare roster read evaluates `RECENT_FORM` against the greatest
    `event_date` among the stringer's assignments"

    Design: Difficulty/dual_variant_calc/reliability_career_vs_recent_form_diverge
    """
    history = create_stringer_with_no_show_history()
    sally = history["stringer"]
    # Give Sally a 2026-11-03 assignment so the bare roster read evaluates
    # RECENT_FORM against 2026-11-03, aging the 2024-11-05 no-show out.
    universe = setup_standard_universe(advance_to="SETUP")
    create_assignment(
        universe["event"]["id"],
        universe["counties"]["alameda"]["id"],
        stringer_id=sally["id"],
    )

    sally = get_stringer(sally["id"])
    assert sally["no_show_count"] == 1
    assert sally["reliability_career"] == 75
    assert sally["reliability_recent_form"] == 100


def test_call_certainty_multi_input_rank_gate(api):
    """PRD §3.6: "For a single-seat contest, W is callable only when W's total
    strictly exceeds every other candidate's total plus the contest's
    `outstanding_estimate`; exact equality fails, because a trailing candidate
    could still tie, and a tie is not certainty."
    PRD §3.6: "A successful proposal increments the contest's `version` by one,
    records the analyst's `X-User-ID` as the call's `proposed_by`, and lands the
    call in `PROPOSED`."
    PRD §3.6: "The call stamps `published_at` from the logical clock, records the
    chief's `X-User-ID` as `published_by`, increments the contest's `version` by
    one, and fires the `CALL` delivery fan-out of §3.8."

    Design: Difficulty/combinatorial_formula/call_certainty_multi_input_rank_gate
    """
    universe = setup_universe_with_reports(
        [
            {"county": "alameda", "precincts_reporting": 8,
             "votes": {"wanda": 5000, "tom": 2500, "ivy": 500}},
            {"county": "contra_costa", "precincts_reporting": 4,
             "votes": {"wanda": 2000, "tom": 1000, "ivy": 300}},
        ],
        advance_to="TABULATION",
        extra_candidates=[("ivy", "Ivy Irwin", "IND")],
    )
    contest_id = universe["contest"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]

    call = propose_call(contest_id, wanda_id)
    published = publish_call(call["id"])

    assert published["status"] == "PUBLISHED"
    assert published["proposed_by"] == ANALYST_NINA_ID
    assert published["published_by"] == CHIEF_RAY_ID
    contest = get_contest(contest_id)
    assert contest["call_status"] == "CALLED"
    assert contest["called_candidate_id"] == wanda_id
    assert contest["margin_pct"] == 0.309735
    assert contest["outstanding_estimate"] == 2800
    assert contest["total_votes"] == 11300


def test_invoice_per_line_rounding_differs_from_sum_rounding(api):
    """PRD §3.8: "The invoice total is a plain integer sum of per-delivery fees:
    the rounding happened at delivery creation, and summing unrounded products
    with a single rounding at the end is forbidden."
    PRD §3.8: "For example, three `VOTE_UPDATE` deliveries to a `BASIC` customer
    bill three times the rounded value of 999 times 0.35 — three times 350, that
    is 1050 cents — and never the single-rounded alternative of 1049 cents."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_differs_from_sum_rounding
    """
    universe = setup_universe_with_reports(
        [
            {"county": "alameda", "precincts_reporting": 5,
             "votes": {"wanda": 4000, "tom": 3000}},
            {"county": "contra_costa", "precincts_reporting": 2,
             "votes": {"wanda": 1000, "tom": 800}},
            {"county": "solano", "precincts_reporting": 3,
             "votes": {"wanda": 1500, "tom": 1200}},
        ],
        extra_counties=[("solano", solano_payload())],
        customers=("basic",),
    )
    customer = universe["customers"]["basic"]

    invoice = generate_invoice(customer["id"], "2026-11")
    assert invoice["delivery_count"] == 3
    assert invoice["total_fee_cents"] == 1050

    rows, meta = list_customer_deliveries(customer["id"])
    assert meta["total_count"] == 3
    for row in rows:
        assert row["content_type"] == "VOTE_UPDATE"
        assert row["fee_cents"] == 350
