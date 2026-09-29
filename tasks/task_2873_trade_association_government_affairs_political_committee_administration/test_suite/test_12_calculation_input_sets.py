"""Constituent matching, the notice input set, and the incumbency constants."""
from test_helpers import (
    COMPLIANCE_2,
    COMPLIANCE_USER_ID_2,
    DEFAULT_CLOCK_STAMP,
    DIRECTOR,
    adopt_position,
    api_client,
    assert_candidate_accumulator_split,
    assert_deductibility_notice,
    assert_instant_equals,
    cast_ballot,
    create_committee,
    create_contribution_payload,
    dispatch_alert,
    draft_position,
    enroll_member,
    launch_campaign,
    open_ballot_round,
    open_fund,
    read_campaign,
    read_candidate,
    read_notice,
    register_candidate,
    seat_member,
    setup_campaign_on_adopted_position,
    setup_open_report_with_activities,
    tally_round,
    validate_error,
    validate_success,
)

ALERT = {
    "target_district_code": "CA-12",
    "target_chamber": "US_HOUSE",
    "message_subject": "Call your representative",
    "unit_cost_cents": 30_000,
}


def test_the_match_set_ranks_by_engagement_and_breaks_ties_on_created_at():
    """Two members share a score, so only the created_at tie-break makes it total.

    PRD 3.7: "Qualifying members are then ordered: by `engagement_score` from highest
    to lowest, and, where two members share an engagement score, by `created_at` from
    earliest to latest."
    PRD 3.7: "The tie-break is `created_at` and never the identifier, which makes the
    ordering total and reproducible."

    Design: Corner/Calculations/constituent_match_ranks_by_engagement_then_created_at
    """
    state = setup_campaign_on_adopted_position(
        engagement_scores=[70, 70, 50],
        campaign_overrides={"name": "Tariff Scope Action"},
        position_overrides={"title": "Oppose Section 232 Expansion"},
    )
    alpha, beta, gamma = state["members"]

    alert = dispatch_alert(state["campaign"]["id"], **ALERT)
    assert alert["status"] == "DISPATCHED"
    assert_instant_equals(alert["dispatched_at"], DEFAULT_CLOCK_STAMP, "dispatched_at")
    assert alert["matched_member_count"] == 3
    assert alert["matched_member_ids"] == [alpha["id"], beta["id"], gamma["id"]]
    assert alert["cost_cents"] == 90_000

    campaign = read_campaign(state["campaign"]["id"])
    assert campaign["status"] == "LIVE"
    assert campaign["alert_count"] == 1
    assert campaign["matched_member_total"] == 3
    assert campaign["cumulative_cost_cents"] == 90_000
    assert campaign["unmatched_alert_count"] == 0
    assert_instant_equals(campaign["last_alert_at"], DEFAULT_CLOCK_STAMP, "last_alert_at")
    assert campaign["disclosure_required"] is False


def test_the_match_set_excludes_unseated_optout_out_of_district_and_inactive_members():
    """Three high-scoring decoys each fail exactly one of the four predicates.

    PRD 3.7: "A member qualifies when all four hold: the member's `status` is `ACTIVE`;
    the member's `advocacy_optout` is false; the member's `home_district_code` is exactly
    equal to the alert's `target_district_code`; and that member holds a committee seat
    whose `status` is `ACTIVE` or `DAMPENED` on the very committee that owns the
    campaign's position."
    PRD 3.7: "Every other member is excluded, including a member whose district matches
    perfectly but who sits on no seat of that committee, and including a dampened-seat
    member — damping reduces weight, it does not remove a member from the mobilisation
    list."

    Design: Corner/Calculations/constituent_match_excludes_unseated_optout_and_inactive_members
    """
    alpha = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", engagement_score=80
    )
    beta = enroll_member(
        legal_name="Beta Foundry Co", membership_tier="FULL", engagement_score=60
    )
    gamma = enroll_member(
        legal_name="Gamma Tooling Co",
        membership_tier="ASSOCIATE",
        home_district_code="NY-05",
        engagement_score=40,
    )
    delta = enroll_member(
        legal_name="Delta Castings Co", membership_tier="PREMIER", engagement_score=100
    )
    echo = enroll_member(
        legal_name="Echo Extrusions Co",
        membership_tier="ASSOCIATE",
        engagement_score=100,
        advocacy_optout=True,
    )
    foxtrot = enroll_member(
        legal_name="Foxtrot Fasteners Co",
        membership_tier="PREMIER",
        engagement_score=100,
        status="SUSPENDED",
    )

    committee = create_committee(name="Federal Tax Policy Committee")
    seat_member(committee["id"], alpha["id"], seat_role="CHAIR")
    seat_member(committee["id"], beta["id"])
    seat_member(committee["id"], gamma["id"])
    seat_member(committee["id"], echo["id"])

    position = draft_position(committee["id"], title="Oppose Section 232 Expansion")
    open_ballot_round(position["id"])
    cast_ballot(position["id"], alpha["id"], "SUPPORT")
    cast_ballot(position["id"], beta["id"], "SUPPORT")
    cast_ballot(position["id"], echo["id"], "SUPPORT")
    cast_ballot(position["id"], gamma["id"], "OPPOSE")
    tallied = tally_round(position["id"])
    assert float(tallied["quorum_pct"]) == 100.00
    assert float(tallied["consensus_pct"]) == 85.71
    assert tallied["status"] == "CONSENSUS_REACHED"

    adopt_position(position["id"])
    campaign = launch_campaign(position["id"], name="Tariff Scope Action")

    alert = dispatch_alert(campaign["id"], **ALERT)
    assert alert["matched_member_count"] == 2
    assert alert["matched_member_ids"] == [alpha["id"], beta["id"]]
    assert delta["id"] not in alert["matched_member_ids"]
    assert echo["id"] not in alert["matched_member_ids"]
    assert foxtrot["id"] not in alert["matched_member_ids"]
    assert gamma["id"] not in alert["matched_member_ids"]
    assert alert["cost_cents"] == 60_000
    assert read_campaign(campaign["id"])["cumulative_cost_cents"] == 60_000


def test_only_certified_reports_enter_the_deductibility_notice():
    """An OPEN report contributes nothing; certification makes it count at once.

    PRD 3.6: "Gather every report whose `status` is `CERTIFIED` and whose `period_code`
    begins with the four digits of the member's `dues_year`; reports that are `OPEN` or
    `SUPERSEDED` are excluded."
    PRD 3.6: "`ratio_pct` is one hundred times `lobbying_spend_cents` divided by the
    association's annual budget of 120,000,000 cents — 1.2 million dollars — rounded half
    up to two decimals, and then capped so that it never exceeds 100.00."

    Design: Corner/Calculations/deductibility_notice_counts_only_certified_reports
    """
    state = setup_open_report_with_activities(
        [{"activity_date": "2026-02-15", "hours": 2.000, "expenditure_cents": 500_000}],
        period_code="2026Q1",
        basis="METHOD_A",
    )
    member = state["members"][0]
    report = state["report"]
    assert report["status"] == "OPEN"
    assert report["method_a_total_cents"] == 500_000
    assert report["period_end_date"] == "2026-03-31"
    assert report["due_date"] == "2026-04-20"

    before = read_notice(member["id"])
    assert_deductibility_notice(before)
    assert before["lobbying_spend_cents"] == 0
    assert float(before["ratio_pct"]) == 0.00
    assert before["notice_method"] == "RATIO"
    assert float(before["nondeductible_pct"]) == 0.00
    assert before["nondeductible_amount_cents"] == 0
    assert before["deductible_amount_cents"] == 400_000

    certified = validate_success(
        api_client.certify_expenditure_report(report["id"], COMPLIANCE_2), 200
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == COMPLIANCE_USER_ID_2
    assert_instant_equals(certified["certified_at"], DEFAULT_CLOCK_STAMP, "certified_at")
    assert certified["late"] is True

    after = read_notice(member["id"])
    assert after["lobbying_spend_cents"] == 500_000
    assert float(after["ratio_pct"]) == 0.42
    assert float(after["nondeductible_pct"]) == 0.42
    assert after["nondeductible_amount_cents"] == 1_680
    assert after["deductible_amount_cents"] == 398_320
    assert after["dues_year"] == 2026


def test_the_open_seat_incumbency_constant_decides_the_tier_and_the_ceiling():
    """OPEN_SEAT contributes sixteen points, landing just above the score floor.

    PRD 3.9: "The score is then forty-five hundredths of `voting_alignment_pct`, plus
    twenty-five hundredths of `committee_relevance_score`, plus twenty hundredths of an
    incumbency factor of 100 for an `INCUMBENT`, 60 for a `CHALLENGER` or 80 for an
    `OPEN_SEAT`, plus ten hundredths of the district engagement; that assembled sum is
    rounded half up to two decimals exactly once, at the end."
    PRD 3.9: "The score then selects a share of that limit: a `support_score` of at
    least 85.00 earns the full limit, a score of at least 70.00 earns half of it, and a
    score of at least 55.00 earns a quarter of it."

    Design: Corner/Calculations/candidate_score_applies_the_open_seat_incumbency_constant
    """
    fund = open_fund(name="NMA Federal PAC", min_reserve_cents=0)
    open_seat = register_candidate(
        name="Dana Whitfield",
        district_code="CA-30",
        incumbency="OPEN_SEAT",
        voting_alignment_pct=60.00,
        committee_relevance_score=50,
    )

    contribution = validate_success(
        api_client.create_pac_contribution(
            create_contribution_payload(fund["id"], open_seat["id"], amount_cents=125_000),
            DIRECTOR,
        ),
        201,
    )
    assert float(contribution["support_score"]) == 55.50
    assert contribution["max_allowed_cents"] == 125_000
    assert contribution["status"] == "PENDING_BOARD"

    stored = read_candidate(open_seat["id"])
    assert float(stored["latest_support_score"]) == 55.50
    assert_candidate_accumulator_split(stored, pending=125_000, committed=0, disbursed=0)

    incumbent = register_candidate(
        name="Dana Whitfield",
        district_code="CA-30",
        incumbency="INCUMBENT",
        voting_alignment_pct=60.00,
        committee_relevance_score=50,
    )
    incumbent_contribution = validate_success(
        api_client.create_pac_contribution(
            create_contribution_payload(fund["id"], incumbent["id"], amount_cents=1),
            DIRECTOR,
        ),
        201,
    )
    assert float(incumbent_contribution["support_score"]) == 59.50

    challenger = register_candidate(
        name="Dana Whitfield",
        district_code="CA-30",
        incumbency="CHALLENGER",
        voting_alignment_pct=60.00,
        committee_relevance_score=50,
    )
    validate_error(
        api_client.create_pac_contribution(
            create_contribution_payload(fund["id"], challenger["id"], amount_cents=1),
            DIRECTOR,
        ),
        "ERR_SCORE_BELOW_FLOOR",
        422,
    )
