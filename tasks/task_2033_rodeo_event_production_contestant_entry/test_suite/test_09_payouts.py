"""Purse construction, payout variants, tie-splitting, and the completion /
settlement gates (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assignment_for_entry,
    complete_performance,
    compute_payout,
    drive_go_round,
    execute_draw,
    get_success_data,
    place_line_for,
    place_lines_for,
    record_rough_result,
    record_timed_result,
    set_clock,
    setup_in_progress,
    setup_riders_with_mixed_results,
    TEST_USERS,
    transition_rodeo,
    validate_error,
    verify_result,
)

ADMIN = TEST_USERS["committee_admin_headers"]


# Pinned money for the standard 4-rider scenario: added 100000, fee 2000,
# contribution 1160 each -> purse 104640; go-round pool 73248; average 31392.
def _mixed_verification_scenario():
    """Four riders scored 85/80/75/90; the 90-point ride stays RECORDED."""
    return setup_riders_with_mixed_results(
        scores=[(43, 42), (40, 40), (38, 37), (45, 45)],
        verified_mask=[True, True, True, False],
        added_money_cents=100000,
        payout_places=2,
        card_prefix="PRCA-10",
    )


def test_provisional_payout_ranks_unverified_recorded_result(api):
    """PRD §3.7: "The two variants differ only in which results feed the
    ranking: the provisional variant includes results in `RECORDED` or
    `VERIFIED` status, while the final variant ranks `VERIFIED` results only —
    so identical underlying data with a single unverified recorded result
    produces different place lines under the two variants."

    Design: Difficulty/dual_variant_calc/payout_provisional_includes_recorded_vs_final_verified_only
    """
    sc = _mixed_verification_scenario()
    c_a, c_b, c_c, c_d = [c["id"] for c in sc["contestants"]]

    payout = compute_payout(sc["event"]["id"], "PROVISIONAL")
    assert payout["computed_variant"] == "PROVISIONAL"
    assert payout["purse_cents"] == 104640

    # The unverified 90-point ride wins the go-round provisionally.
    g1 = place_lines_for(payout, "GO_ROUND_1")
    assert place_line_for(payout, "GO_ROUND_1", c_d)["amount_cents"] == 43949
    assert place_line_for(payout, "GO_ROUND_1", c_d)["place"] == 1
    assert place_line_for(payout, "GO_ROUND_1", c_a)["amount_cents"] == 29299
    assert place_line_for(payout, "GO_ROUND_1", c_a)["place"] == 2
    assert len(g1) == 2

    avg = place_lines_for(payout, "AVERAGE")
    assert place_line_for(payout, "AVERAGE", c_d)["amount_cents"] == 18835
    assert place_line_for(payout, "AVERAGE", c_a)["amount_cents"] == 12557
    assert len(avg) == 2


def test_final_payout_excludes_unverified_recorded_result(api):
    """PRD §3.7: "The two variants differ only in which results feed the
    ranking: the provisional variant includes results in `RECORDED` or
    `VERIFIED` status, while the final variant ranks `VERIFIED` results only —
    so identical underlying data with a single unverified recorded result
    produces different place lines under the two variants."

    Design: Difficulty/dual_variant_calc/payout_provisional_includes_recorded_vs_final_verified_only
    """
    sc = _mixed_verification_scenario()
    c_a, c_b, c_c, c_d = [c["id"] for c in sc["contestants"]]

    payout = compute_payout(sc["event"]["id"], "FINAL")
    assert payout["computed_variant"] == "FINAL"
    assert payout["purse_cents"] == 104640

    # The RECORDED 90-point ride vanishes from the final placing.
    assert place_line_for(payout, "GO_ROUND_1", c_a)["amount_cents"] == 43949
    assert place_line_for(payout, "GO_ROUND_1", c_b)["amount_cents"] == 29299
    assert place_line_for(payout, "AVERAGE", c_a)["amount_cents"] == 18835
    assert place_line_for(payout, "AVERAGE", c_b)["amount_cents"] == 12557
    d_lines = [
        l for l in payout["place_lines"] if l["contestant_id"] == c_d
    ]
    assert d_lines == [], "an unverified result earns nothing under FINAL"


def _tied_at_top_scenario():
    """Four riders all VERIFIED: A and D tie at 85, then B 80, C 75."""
    return setup_riders_with_mixed_results(
        scores=[(43, 42), (40, 40), (38, 37), (42, 43)],
        verified_mask=[True, True, True, True],
        added_money_cents=100000,
        payout_places=2,
        card_prefix="PRCA-30",
    )


def test_two_way_tie_splits_combined_go_round_amounts(api):
    """PRD §3.7: "When m contestants tie at place k — covering m consecutive
    places — they split the combined amount of places k through k+m−1 equally:
    each tied contestant receives the combined sum divided by m, rounded
    half-up to whole cents, and the leftover cents (the combined sum minus m
    times that share) go to the tied contestant whose result was verified
    earliest by `verified_at`, with a tie on that instant broken by the
    result's `created_at` ascending — never by any resource identifier."
    PRD §3.7: "For one place the pool pays 100 percent; for two places, 60 and
    40 percent".

    Design: Difficulty/combinatorial_formula/payout_places_tiered_with_two_way_tie_split
    """
    sc = _tied_at_top_scenario()
    c_a, c_b, c_c, c_d = [c["id"] for c in sc["contestants"]]

    payout = compute_payout(sc["event"]["id"], "FINAL")
    assert payout["purse_cents"] == 104640

    # Tie at place 1 pools 43949 + 29299 = 73248 and splits evenly.
    line_a = place_line_for(payout, "GO_ROUND_1", c_a)
    line_d = place_line_for(payout, "GO_ROUND_1", c_d)
    assert line_a["place"] == 1 and line_d["place"] == 1
    assert line_a["tied_count"] == 2 and line_d["tied_count"] == 2
    assert line_a["amount_cents"] == 36624
    assert line_d["amount_cents"] == 36624

    # The tie absorbs both paid places: no go-round line for B or C.
    g1 = place_lines_for(payout, "GO_ROUND_1")
    assert len(g1) == 2
    assert all(l["contestant_id"] in (c_a, c_d) for l in g1)


def test_two_way_tie_splits_combined_average_amounts(api):
    """PRD §3.7: "Ties in the aggregate are ties for placing and split exactly
    as go-round ties do." and "When m contestants tie at place k — covering m
    consecutive places — they split the combined amount of places k through
    k+m−1 equally".

    Design: Difficulty/combinatorial_formula/payout_places_tiered_with_two_way_tie_split
    """
    sc = _tied_at_top_scenario()
    c_a, c_b, c_c, c_d = [c["id"] for c in sc["contestants"]]

    payout = compute_payout(sc["event"]["id"], "FINAL")

    # Average pool is 31392; the tie pools 18835 + 12557 and splits evenly.
    line_a = place_line_for(payout, "AVERAGE", c_a)
    line_d = place_line_for(payout, "AVERAGE", c_d)
    assert line_a["tied_count"] == 2 and line_d["tied_count"] == 2
    assert line_a["amount_cents"] == 15696
    assert line_d["amount_cents"] == 15696

    avg = place_lines_for(payout, "AVERAGE")
    assert len(avg) == 2


def _empty_go_round_scenario():
    """Two-go-round BULL_RIDING event; go-round 1 all NO_SCORE, go-round 2
    both qualified (80 and 75); rodeo COMPLETED. Returns the scenario dict."""
    sc = setup_in_progress(
        event_code="BULL_RIDING", num_contestants=2,
        animal_tags=("A100", "A200", "A300", "A400"),
        event_overrides={"go_rounds": 2, "added_money_cents": 50000,
                         "payout_places": 2, "per_performance_slots": 10},
        judge_certification="PRCA_GOLD", judge_card="J-11",
        card_prefix="PRCA-11",
    )
    judge_id = sc["judge"]["id"]
    # Go-round 1: both riders score 0 unqualified -> NO_SCORE (verified).
    for entry in sc["entries"]:
        da = assignment_for_entry(entry["id"], status="PENDING")
        result = record_rough_result(da["id"], judge_id, 0, 0, qualified=False)
        verify_result(result["id"])
    # Go-round 2: 80 and 75, both qualified.
    drive_go_round(sc, 2, rough_scores=[(40, 40, True), (38, 37, True)])
    complete_performance(sc["performance"]["id"])
    transition_rodeo(sc["rodeo"]["id"], "COMPLETE_RODEO")
    return sc


def test_empty_go_round_pool_rolls_into_average_pool(api):
    """PRD §3.7: "A go-round with zero qualified ranked contestants is empty,
    and its pool rolls into the average: `average_pool_cents` is the purse
    minus the sum of the non-empty go-round pools, so every residual cent
    lands in the average."
    PRD §3.7: "Its purse — `purse_cents` — is the event's `added_money_cents`
    plus, summed over all of the event's entries regardless of their status,
    each entry's `contribution_charges_cents` minus its
    `refunded_contribution_cents`."

    Design: Difficulty/boundary_precision_check/go_round_with_zero_qualified_rolls_pool_to_average
    """
    sc = _empty_go_round_scenario()
    payout = compute_payout(sc["event"]["id"], "FINAL")

    assert payout["purse_cents"] == 52320, (
        f"50000 added + 2 x 1160, got {payout['purse_cents']}"
    )
    # The non-empty go-round's pool is round_half_up(52320 x 0.70 / 2) = 18312,
    # and the empty round's pool rolls into the average.
    assert {"go_round": 2, "pool_cents": 18312} in payout["go_round_pools"], (
        f"go-round 2 keeps its 18312 pool: {payout['go_round_pools']}"
    )
    assert payout["average_pool_cents"] == 34008, (
        f"52320 - 18312 with the empty round rolled in, got "
        f"{payout['average_pool_cents']}"
    )


def test_empty_go_round_pays_no_places_and_average_empty(api):
    """PRD §3.7: "Ranking uses only `QUALIFIED` results: rough stock ranks by
    `total_score` descending, timed events by `total_time_ms` ascending."
    PRD §3.7: "Eligibility for the average is strict: a contestant must hold
    a qualified in-scope result in every go-round from 1 through the event's
    `go_rounds`."

    Design: Difficulty/boundary_precision_check/go_round_with_zero_qualified_rolls_pool_to_average
    """
    sc = _empty_go_round_scenario()
    c1, c2 = [c["id"] for c in sc["contestants"]]
    payout = compute_payout(sc["event"]["id"], "FINAL")

    # Go-round 2 pays its two places (60/40 of 18312 with residual to last).
    line1 = place_line_for(payout, "GO_ROUND_2", c1)
    line2 = place_line_for(payout, "GO_ROUND_2", c2)
    assert (line1["place"], line1["amount_cents"]) == (1, 10987)
    assert (line2["place"], line2["amount_cents"]) == (2, 7325)

    # Nobody qualified in go-round 1, so nobody is average-eligible.
    assert place_lines_for(payout, "GO_ROUND_1") == []
    assert place_lines_for(payout, "AVERAGE") == []


def test_average_requires_qualified_every_go_round(api):
    """PRD §3.7: "Eligibility for the average is strict: a contestant must
    hold a qualified in-scope result in every go-round from 1 through the
    event's `go_rounds`. The aggregate is the sum of `total_score` across the
    go-rounds for rough stock, ranked descending, or the sum of
    `total_time_ms` across the go-rounds for timed events, ranked ascending."
    PRD §3.4: "The `outcome` derives from the flags in a fixed order:
    `DISQUALIFIED` whenever `disqualified_flag` is set; otherwise `QUALIFIED`
    when `qualified_flag` is set; otherwise `NO_SCORE` for rough stock or
    `NO_TIME` for timed events."

    Design: Corner/calculations/average_requires_qualified_every_go_round
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=2, animal_tags=(),
        event_overrides={"go_rounds": 2, "added_money_cents": 50000,
                         "payout_places": 1, "per_performance_slots": 10},
        judge_position="TIMER", judge_card="J-30", card_prefix="PRCA-30",
    )
    judge_id = sc["judge"]["id"]
    e1, e2 = sc["entries"]
    c1, c2 = e1["contestant_id"], e2["contestant_id"]

    # Go-round 1: both qualified, C1 fastest.
    for entry, raw in ((e1, 14000), (e2, 14500)):
        da = assignment_for_entry(entry["id"], status="PENDING")
        verify_result(record_timed_result(da["id"], judge_id, raw)["id"])
    # Go-round 2: C1 breaks out (NO_TIME), C2 qualified.
    execute_draw(sc["event"]["id"], go_round_number=2)
    da1 = assignment_for_entry(e1["id"], status="PENDING")
    breakout = record_timed_result(da1["id"], judge_id, 15000, qualified=False)
    assert breakout["outcome"] == "NO_TIME"
    verify_result(breakout["id"])
    da2 = assignment_for_entry(e2["id"], status="PENDING")
    verify_result(record_timed_result(da2["id"], judge_id, 14100)["id"])

    complete_performance(sc["performance"]["id"])
    transition_rodeo(sc["rodeo"]["id"], "COMPLETE_RODEO")
    payout = compute_payout(sc["event"]["id"], "FINAL")

    assert place_line_for(payout, "GO_ROUND_1", c1)["amount_cents"] == 18312
    assert place_line_for(payout, "GO_ROUND_2", c2)["amount_cents"] == 18312

    avg = place_lines_for(payout, "AVERAGE")
    assert len(avg) == 1, f"only the everywhere-qualified rider is eligible: {avg}"
    assert avg[0]["contestant_id"] == c2
    assert avg[0]["amount_cents"] == 15696


def test_tie_remainder_to_earliest_verified(api):
    """PRD §3.7: "each tied contestant receives the combined sum divided by m,
    rounded half-up to whole cents, and the leftover cents (the combined sum
    minus m times that share) go to the tied contestant whose result was
    verified earliest by `verified_at`, with a tie on that instant broken by
    the result's `created_at` ascending — never by any resource identifier."

    Design: Corner/calculations/tie_remainder_to_earliest_verified
    """
    sc = setup_in_progress(
        event_code="BULL_RIDING", num_contestants=3,
        animal_tags=("A100", "A200", "A300"),
        event_overrides={"added_money_cents": 10806, "payout_places": 3,
                         "per_performance_slots": 10},
        judge_certification="PRCA_GOLD", judge_card="J-31",
        card_prefix="PRCA-31",
    )
    judge_id = sc["judge"]["id"]
    c_a, c_b, c_c = [c["id"] for c in sc["contestants"]]

    # Three identical 85-point rides; verify in A, B, C order at distinct
    # logical-clock instants so verified_at ordering is pinned.
    recorded = []
    for entry, (j1, j2) in zip(sc["entries"], [(43, 42), (42, 43), (42, 43)]):
        da = assignment_for_entry(entry["id"], status="PENDING")
        recorded.append(record_rough_result(da["id"], judge_id, j1, j2))
    for result, stamp in zip(
        recorded,
        ["2026-08-14T20:00:00Z", "2026-08-14T20:05:00Z", "2026-08-14T20:10:00Z"],
    ):
        set_clock(stamp)
        verify_result(result["id"])

    payout = compute_payout(sc["event"]["id"], "FINAL")
    assert payout["purse_cents"] == 14286
    assert payout["go_round_pools"] == [{"go_round": 1, "pool_cents": 10000}]
    assert payout["average_pool_cents"] == 4286

    # Three-way tie over 10000: 3333 each, the 1-cent remainder to the
    # earliest verified.
    for cid in (c_a, c_b, c_c):
        line = place_line_for(payout, "GO_ROUND_1", cid)
        assert line["place"] == 1 and line["tied_count"] == 3
    assert place_line_for(payout, "GO_ROUND_1", c_a)["amount_cents"] == 3334
    assert place_line_for(payout, "GO_ROUND_1", c_b)["amount_cents"] == 3333
    assert place_line_for(payout, "GO_ROUND_1", c_c)["amount_cents"] == 3333
    assert sum(
        place_line_for(payout, "GO_ROUND_1", cid)["amount_cents"]
        for cid in (c_a, c_b, c_c)
    ) == 10000

    # Same tie over the 4286 average pool: shares of 1429 leave a -1
    # remainder, absorbed by the earliest verified.
    assert place_line_for(payout, "AVERAGE", c_a)["amount_cents"] == 1428
    assert place_line_for(payout, "AVERAGE", c_b)["amount_cents"] == 1429
    assert place_line_for(payout, "AVERAGE", c_c)["amount_cents"] == 1429


def test_complete_rodeo_rejected_with_unverified_results(api):
    """PRD §3.7: "Completion demands two things: every performance of the
    rodeo is `COMPLETED` or `CANCELLED`, and no result belonging to the
    rodeo's entries remains in `RECORDED` or `AMENDED` status — a straggler
    rejects the transition with `ERR_RESULTS_PENDING`."

    Design: Corner/validations/complete_rodeo_rejected_with_unverified_results
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        judge_position="TIMER", judge_card="J-49", card_prefix="PRCA-490",
    )
    da = assignment_for_entry(sc["entries"][0]["id"])
    result = record_timed_result(da["id"], sc["judge"]["id"], 14250)
    assert result["status"] == "RECORDED"
    complete_performance(sc["performance"]["id"])

    resp = api.rodeo_transition(sc["rodeo"]["id"], {"action": "COMPLETE_RODEO"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESULTS_PENDING)

    rodeo = get_success_data(api.get_rodeo(sc["rodeo"]["id"], ADMIN), 200)
    assert rodeo["posture"] == "IN_PROGRESS"


def test_settle_rejected_without_final_payout(api):
    """PRD §3.7: "Settlement (`SETTLE_RODEO`: `COMPLETED` → `SETTLED`) then
    requires every event of the rodeo to hold a payout in `FINAL` status,
    rejecting with `ERR_PAYOUT_NOT_FINAL` while any event's payout is missing
    or merely provisional."

    Design: Corner/validations/settle_rejected_without_final_payout
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        judge_position="TIMER", judge_card="J-491", card_prefix="PRCA-491",
    )
    da = assignment_for_entry(sc["entries"][0]["id"])
    verify_result(record_timed_result(da["id"], sc["judge"]["id"], 14250)["id"])
    complete_performance(sc["performance"]["id"])
    transition_rodeo(sc["rodeo"]["id"], "COMPLETE_RODEO")

    # No payout has ever been computed for the event.
    resp = api.rodeo_transition(sc["rodeo"]["id"], {"action": "SETTLE_RODEO"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_FINAL)

    rodeo = get_success_data(api.get_rodeo(sc["rodeo"]["id"], ADMIN), 200)
    assert rodeo["posture"] == "COMPLETED"
