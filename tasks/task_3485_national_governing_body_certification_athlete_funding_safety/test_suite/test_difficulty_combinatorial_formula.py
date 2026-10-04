"""Difficulty tests: combinatorial_formula — pinned evaluation orders whose
result differs from any unpinned reading (revenue-split rounding order and
the season-points -> quota-bonus -> composite-ranking selector order).
"""
import pytest

from test_helpers import (
    activate_deal,
    add_verified_results,
    consent_deal,
    create_commercial_deal,
    setup_certified_body,
    setup_eligible_athlete,
    setup_nominated_roster,
)


def test_commercial_split_rounding_order(api, committee_admin_headers):
    """PRD commercial-rights section: "Under `NET_BASIS`, an agency fee of 10
    percent of `gross_value_cents`, rounded half up to whole cents, is
    deducted first, and the split base is the gross minus that fee".
    PRD commercial-rights section: "The committee's `committee_share_cents` is
    30 percent of the base rounded half up to whole cents; the body's
    `ngb_share_cents` is 40 percent of the base rounded half up to whole
    cents; and the athlete's `athlete_share_cents` is whatever remains of the
    base after those two shares, so the athlete absorbs the rounding and the
    three shares always sum exactly to the base."

    Design: Difficulty/combinatorial_formula/commercial_split_rounding_order
    """
    body = setup_certified_body(
        api=api,
        name="US Gymnastics",
        sport_code="GYMN",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Dana Volt", date_of_birth="2000-02-02"
    )
    deal = create_commercial_deal(
        athlete["id"],
        api=api,
        sponsor_name="Acme Watches",
        gross_value_cents=999999,
        basis="NET_BASIS",
        exclusivity_start="2027-01-01T00:00:00Z",
        exclusivity_end="2027-06-30T00:00:00Z",
    )
    deal = consent_deal(deal, athlete["id"], api=api)
    deal = activate_deal(deal, api=api)

    # NET_BASIS: fee round_half_up(999999*0.10)=100000, base 899999.
    assert deal["committee_share_cents"] == 270000, (
        "committee share must be round_half_up(899999*0.30)=270000, "
        f"got {deal['committee_share_cents']!r}"
    )
    assert deal["ngb_share_cents"] == 360000, (
        "ngb share must be round_half_up(899999*0.40)=360000, "
        f"got {deal['ngb_share_cents']!r}"
    )
    # The athlete absorbs the remainder: 899999 - 270000 - 360000 = 269999,
    # NOT round_half_up(899999*0.30) = 270000.
    assert deal["athlete_share_cents"] == 269999, (
        f"athlete share must be the remainder 269999, got {deal['athlete_share_cents']!r}"
    )
    total = (
        deal["committee_share_cents"]
        + deal["ngb_share_cents"]
        + deal["athlete_share_cents"]
    )
    assert total == 899999, (
        f"the three shares must sum exactly to the 899999 base, got {total}"
    )


def test_quota_bonus_evaluation_order(api, committee_admin_headers):
    """PRD selection section: "The selector's evaluation order is pinned:
    season points first, quota bonus second, composite ranking third."
    PRD selection section: "The quota bonus sums the three highest
    season-point totals among athletes holding `QUALIFIED` entries — when
    fewer than three athletes are qualified, it sums all of them — and when
    that sum reaches 250 the roster's `bonus_slot_applied` is set true and
    `quota_effective` becomes `quota_slots` plus one bonus slot; below 250,
    `bonus_slot_applied` is false and `quota_effective` equals `quota_slots`
    unchanged."
    PRD selection section: "Each candidate's `composite_score` is a weighted
    blend of 0.7 times their `trials_score` — the entry's recorded `score` —
    and 0.3 times their season points, rounded half up to two decimal places."
    PRD selection section: "The first `quota_effective` candidates fill
    `PRIMARY` slots ranked 1 through N, and the next 2 candidates fill
    `ALTERNATE` slots."

    Design: Difficulty/combinatorial_formula/quota_bonus_evaluation_order
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=8_000_000,
        sport_science_pool_hours=100,
    )
    # 2026-season results: A1=100 (1st/A + 1st/C), A2=80 (1st/A + 4th/C),
    # A3=74 (2nd/A + 3rd/C), A4=36 (4th/C + 5th/C); top-3 sum 254 >= 250.
    season_specs = {
        "a1": [
            {"event_name": "June Meet", "event_grade": "A", "placing": 1,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "July Meet", "event_grade": "C", "placing": 1,
             "event_date": "2026-07-01T00:00:00Z"},
        ],
        "a2": [
            {"event_name": "June Meet", "event_grade": "A", "placing": 1,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "July Meet", "event_grade": "C", "placing": 4,
             "event_date": "2026-07-01T00:00:00Z"},
        ],
        "a3": [
            {"event_name": "June Meet", "event_grade": "A", "placing": 2,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "July Meet", "event_grade": "C", "placing": 3,
             "event_date": "2026-07-01T00:00:00Z"},
        ],
        "a4": [
            {"event_name": "June Meet", "event_grade": "C", "placing": 4,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "July Meet", "event_grade": "C", "placing": 5,
             "event_date": "2026-07-01T00:00:00Z"},
        ],
    }
    athletes = {}
    for key, dob in (
        ("a1", "1998-01-01"), ("a2", "1998-01-02"),
        ("a3", "1998-01-03"), ("a4", "1998-01-04"),
    ):
        athletes[key] = setup_eligible_athlete(
            body["id"], api=api, full_name=f"Athlete {key}", date_of_birth=dob
        )
        add_verified_results(athletes[key]["id"], season_specs[key], api=api)

    _proc, roster = setup_nominated_roster(
        body["id"],
        {athletes["a1"]["id"]: 95, athletes["a2"]["id"]: 90,
         athletes["a3"]["id"]: 85, athletes["a4"]["id"]: 80},
        api=api,
        quota_slots=2,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )

    assert roster["status"] == "NOMINATED"
    # Bonus evaluated BEFORE ranking: 100 + 80 + 74 = 254 >= 250.
    assert roster["bonus_slot_applied"] is True, (
        "top-3 season sum 254 reaches the 250 bonus threshold"
    )
    assert roster["quota_effective"] == 3, (
        f"quota_slots 2 + 1 bonus slot = 3, got {roster['quota_effective']!r}"
    )

    slots_by_rank = {slot["rank"]: slot for slot in roster["slots"]}
    assert set(slots_by_rank) == {1, 2, 3, 4}

    rank1 = slots_by_rank[1]
    assert rank1["athlete_id"] == athletes["a1"]["id"]
    assert rank1["slot_type"] == "PRIMARY"
    assert rank1["composite_score"] == pytest.approx(96.5, abs=1e-9)  # 0.7*95+0.3*100

    rank2 = slots_by_rank[2]
    assert rank2["athlete_id"] == athletes["a2"]["id"]
    assert rank2["slot_type"] == "PRIMARY"
    assert rank2["composite_score"] == pytest.approx(87.0, abs=1e-9)  # 0.7*90+0.3*80

    # The 3rd PRIMARY exists only because the bonus slot was applied first.
    rank3 = slots_by_rank[3]
    assert rank3["athlete_id"] == athletes["a3"]["id"]
    assert rank3["slot_type"] == "PRIMARY", (
        "A3 lands a PRIMARY slot only under the pinned bonus-before-ranking order"
    )
    assert rank3["composite_score"] == pytest.approx(81.7, abs=1e-9)  # 0.7*85+0.3*74

    # A4's trials 80 == qualifying_score 80 qualifies (inclusive), then ranks
    # 4th and fills the first ALTERNATE slot.
    rank4 = slots_by_rank[4]
    assert rank4["athlete_id"] == athletes["a4"]["id"]
    assert rank4["slot_type"] == "ALTERNATE"
    assert rank4["composite_score"] == pytest.approx(66.8, abs=1e-9)  # 0.7*80+0.3*36
