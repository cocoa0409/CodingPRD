"""Student surveys, volunteer hours, evaluation report, recognition tier (PRD §3.5, §3.8)."""
import pytest

from test_helpers import (
    COORDINATOR,
    DIRECTOR,
    FUNDER,
    ApiErrorId,
    TUESDAYS_4,
    TUESDAYS_5,
    WEDNESDAYS_4,
    add_partner_with_volunteer,
    add_roster,
    add_session,
    api_client,
    assert_evaluation_report,
    base_world,
    get_agreement,
    get_delivery,
    get_evaluation,
    get_session,
    get_student,
    get_volunteer,
    make_delivery,
    plan_delivery,
    record_funding,
    record_session_delivery,
    schedule_delivery,
    set_clock,
    transition_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_students_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; when not
    provided it defaults to 10, with a minimum of 1 and a maximum of 100.
    `offset` sets how many items are skipped and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/corner_students_list_paginates_with_total_count_and_has_more
    """
    world = base_world()
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=4)
    students = add_roster(delivery["id"], 3)
    assert len(students) == 3

    page1, meta1 = validate_paginated(
        api_client.list_students(COORDINATOR, params={"delivery_id": delivery["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3, "total_count spans the filtered set, not the page"
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_students(COORDINATOR, params={"delivery_id": delivery["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta_all = validate_paginated(
        api_client.list_students(COORDINATOR, params={"delivery_id": delivery["id"]})
    )
    assert len(all_rows) == 3
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0


def test_survey_score_out_of_range_rejected(api):
    """PRD §3.8: "SUBMIT_PRE moves NONE to PRE_SUBMITTED, requires the delivery
    to be PLANNED, SCHEDULED, or IN_PROGRESS, else `ERR_INVALID_STATE`, and
    carries a `score` that must be present, else `ERR_VALIDATION`, and within
    0 to 100 inclusive, else `ERR_SURVEY_SCORE_OUT_OF_RANGE`; it stores
    `pre_score`."

    Design: Corner/validations/corner_survey_score_out_of_range_rejected
    """
    world = base_world()
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=4)
    students = add_roster(delivery["id"], 1)
    plan_delivery(delivery["id"])
    stu = students[0]["id"]

    resp = api_client.transition_student(stu, {"action": "SUBMIT_PRE", "score": 101}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SURVEY_SCORE_OUT_OF_RANGE)
    after = get_student(stu)
    assert after["survey_status"] == "NONE"
    assert after["pre_score"] is None

    ok = api_client.transition_student(stu, {"action": "SUBMIT_PRE", "score": 100}, COORDINATOR)
    data = validate_success(ok, 200)
    assert data["survey_status"] == "PRE_SUBMITTED", "100 is the inclusive upper bound"
    assert data["pre_score"] == 100


def test_post_survey_before_delivery_completed_rejected(api):
    """PRD §3.8: "SUBMIT_POST moves PRE_SUBMITTED to PAIRED under a stricter
    gate — the delivery must be COMPLETED, else `ERR_INVALID_STATE` — with the
    same score rules, storing `post_score`."

    Design: Corner/validations/corner_post_survey_before_delivery_completed_rejected
    """
    world = base_world(assemble=20)
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=4)
    students = add_roster(delivery["id"], 1)
    plan_delivery(delivery["id"])
    sessions = [add_session(delivery["id"], world["volunteer"]["id"], d, confirm=True) for d in TUESDAYS_4]
    schedule_delivery(delivery["id"])
    record_session_delivery(sessions[0]["id"], "2026-09-08")  # delivery IN_PROGRESS
    stu = students[0]["id"]
    pre = api_client.transition_student(stu, {"action": "SUBMIT_PRE", "score": 60}, COORDINATOR)
    validate_success(pre, 200)

    resp = api_client.transition_student(stu, {"action": "SUBMIT_POST", "score": 80}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_student(stu)
    assert after["survey_status"] == "PRE_SUBMITTED"
    assert after["post_score"] is None


def test_volunteer_hours_round_per_session_then_sum(api):
    """PRD §2.10: "Volunteer hours are decimal but rounded per session first:
    each session's hours are its duration in minutes divided by 60, rounded
    half-up to exactly two decimal places, and only then summed into any total
    — never sum-then-round."

    Design: Corner/calculations/corner_volunteer_hours_round_per_session_then_sum
    """
    world = base_world(assemble=20)
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=10)
    plan_delivery(delivery["id"])
    sessions = [
        add_session(delivery["id"], world["volunteer"]["id"], d, start_minutes=540, end_minutes=560, confirm=True)
        for d in TUESDAYS_4
    ]
    schedule_delivery(delivery["id"])
    for session, date in zip(sessions[:3], TUESDAYS_4[:3]):
        record_session_delivery(session["id"], date)

    hours = get_volunteer(world["volunteer"]["id"])["hours_contributed"]
    # 3 x round_half_up(20/60, 2) = 3 x 0.33 = 0.99, not sum-then-round 1.0
    assert hours == pytest.approx(0.99, abs=1e-9), f"per-session rounding is law, got {hours}"
    assert abs(hours - 1.0) > 1e-9, "1.0 would be the forbidden sum-then-round value"
    assert get_session(sessions[3]["id"])["status"] == "SCHEDULED", "the fourth session contributes nothing"


def test_evaluation_read_forbidden_for_program_coordinator(api):
    """PRD §2.1: "On the read side, all six roles may query every resource
    collection; the single exception is the computed evaluation report, which
    only `AreaDirector`, `PartnershipManager`, and `Funder` may read."

    Design: Corner/rbac/corner_evaluation_read_forbidden_for_program_coordinator
    """
    world = base_world()
    agr_id = world["agreement"]["id"]
    resp = api_client.get_evaluation(agr_id, COORDINATOR, params={"variant": "PROVISIONAL"})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    ok = api_client.get_evaluation(agr_id, FUNDER, params={"variant": "PROVISIONAL"})
    data = validate_success(ok, 200)
    assert data["variant"] == "PROVISIONAL"
    assert data["agreement_id"] == agr_id


# ---------------------------------------------------------------------------
# Difficulty: PROVISIONAL vs FINAL evaluation divergence (two tests)
# ---------------------------------------------------------------------------

def _evaluation_world():
    """Two SCHEDULED 4-session deliveries under one agreement.

    d1: lead vol1 (sponsor partner1), enrolled 4, roster of 4; all four
    sessions DELIVERED; surveys stu1 60/80 VALIDATED, stu2 70/85 VALIDATED,
    stu3 50/60 PAIRED, stu4 90 PRE_SUBMITTED; delivery COMPLETED.
    d2: lead vol2 (partner2), enrolled 10; sessions 1-2 (vol2) DELIVERED,
    sessions 3-4 (vol1) still SCHEDULED; delivery IN_PROGRESS.
    """
    world = base_world(program_code="JA-BIZ", assemble=20)
    second = add_partner_with_volunteer()
    vol1 = world["volunteer"]["id"]
    vol2 = second["volunteer"]["id"]

    d1 = make_delivery(world["agreement"]["id"], vol1, enrolled_count=4, classroom_label="Room 1")
    students = add_roster(d1["id"], 4)
    plan_delivery(d1["id"])
    d1_sessions = [add_session(d1["id"], vol1, d, confirm=True) for d in TUESDAYS_4]
    schedule_delivery(d1["id"])

    d2 = make_delivery(world["agreement"]["id"], vol2, enrolled_count=10, classroom_label="Room 2")
    plan_delivery(d2["id"])
    d2_s1 = add_session(d2["id"], vol2, WEDNESDAYS_4[0], confirm=True)
    d2_s2 = add_session(d2["id"], vol2, WEDNESDAYS_4[1], confirm=True)
    add_session(d2["id"], vol1, WEDNESDAYS_4[2], confirm=True)
    add_session(d2["id"], vol1, WEDNESDAYS_4[3], confirm=True)
    schedule_delivery(d2["id"])

    record_session_delivery(d1_sessions[0]["id"], "2026-09-08")
    for stu, score in zip(students, (60, 70, 50, 90)):
        resp = api_client.transition_student(stu["id"], {"action": "SUBMIT_PRE", "score": score}, COORDINATOR)
        validate_success(resp, 200)
    record_session_delivery(d2_s1["id"], "2026-09-09")
    record_session_delivery(d1_sessions[1]["id"], "2026-09-15")
    record_session_delivery(d2_s2["id"], "2026-09-16")
    record_session_delivery(d1_sessions[2]["id"], "2026-09-22")
    record_session_delivery(d1_sessions[3]["id"], "2026-09-29")

    completed = transition_delivery(d1["id"], "COMPLETE")
    assert completed["status"] == "COMPLETED"
    for stu, score in zip(students[:3], (80, 85, 60)):
        resp = api_client.transition_student(stu["id"], {"action": "SUBMIT_POST", "score": score}, COORDINATOR)
        validate_success(resp, 200)
    for stu in students[:2]:
        resp = api_client.transition_student(stu["id"], {"action": "VALIDATE"}, COORDINATOR)
        validate_success(resp, 200)
    return {"agreement_id": world["agreement"]["id"]}


def test_evaluation_provisional_counts_broad_student_and_session_pools(api):
    """PRD §3.8: "PROVISIONAL counts roster students across all of the
    agreement's deliveries whose `survey_status` is PRE_SUBMITTED, PAIRED, or
    VALIDATED; FINAL counts VALIDATED students only, and either way the count
    lands in `students_included`."
    PRD §3.8: "The hour totals draw on a session pool: DELIVERED sessions only
    under FINAL, or DELIVERED plus TENTATIVE, SCHEDULED, and NEEDS_SUBSTITUTE
    under PROVISIONAL."

    Design: Difficulty/dual_variant_calc/evaluation_provisional_vs_final_diverge_on_student_inclusion_and_hours
    """
    ctx = _evaluation_world()
    prov = get_evaluation(ctx["agreement_id"], variant="PROVISIONAL")
    assert_evaluation_report(prov)
    assert prov["variant"] == "PROVISIONAL"
    assert prov["students_included"] == 4
    assert prov["students_paired"] == 3
    assert prov["avg_growth_score"] == pytest.approx(15.0, abs=1e-9)  # (20+15+10)/3
    assert prov["sessions_delivered"] == 6
    assert prov["sessions_scheduled"] == 2
    assert prov["total_volunteer_hours"] == pytest.approx(8.0, abs=1e-9)
    assert prov["sponsor_volunteer_hours"] == pytest.approx(6.0, abs=1e-9)
    assert prov["completion_rate_pct"] == pytest.approx(75.0, abs=1e-9)  # 6 of 8 required


def test_evaluation_final_counts_validated_students_and_delivered_hours(api):
    """PRD §3.8: "`students_paired` is the number of included students with
    both scores present, and `avg_growth_score` is the mean of each paired
    student's post-minus-pre difference, rounded half-up to one decimal place
    — null when no paired students exist."
    PRD §3.8: "`sessions_delivered` counts the agreement's sessions in
    DELIVERED; `sessions_scheduled` counts those in TENTATIVE, SCHEDULED, or
    NEEDS_SUBSTITUTE."

    Design: Difficulty/dual_variant_calc/evaluation_provisional_vs_final_diverge_on_student_inclusion_and_hours
    """
    ctx = _evaluation_world()
    fin = get_evaluation(ctx["agreement_id"], variant="FINAL")
    assert_evaluation_report(fin)
    assert fin["variant"] == "FINAL"
    assert fin["students_included"] == 2
    assert fin["students_paired"] == 2
    assert fin["avg_growth_score"] == pytest.approx(17.5, abs=1e-9)  # (20+15)/2
    assert fin["total_volunteer_hours"] == pytest.approx(6.0, abs=1e-9)
    assert fin["sponsor_volunteer_hours"] == pytest.approx(4.0, abs=1e-9)
    assert fin["sessions_delivered"] == 6, "session counts are variant-independent"
    assert fin["sessions_scheduled"] == 2


# ---------------------------------------------------------------------------
# Difficulty: persisted EARNED tier vs PROJECTED tier (two tests)
# ---------------------------------------------------------------------------

def _recognition_world():
    """Pledge fully funded (500000); 5x120-minute sessions, four DELIVERED by
    the sponsor's volunteer and the fifth still SCHEDULED."""
    world = base_world(
        session_count=5, minutes_per_session=120, program_code="JA-FIN",
        pledge_cents=500000, assemble=50,
    )
    record_funding(world["agreement"]["id"], 500000)
    vol1 = world["volunteer"]["id"]
    delivery = make_delivery(world["agreement"]["id"], vol1, enrolled_count=10, classroom_label="Room 3")
    plan_delivery(delivery["id"])
    sessions = [
        add_session(delivery["id"], vol1, d, start_minutes=540, end_minutes=660, confirm=True)
        for d in TUESDAYS_5
    ]
    schedule_delivery(delivery["id"])
    for session, date in zip(sessions[:4], TUESDAYS_5[:4]):
        record_session_delivery(session["id"], date)
    return {"agreement_id": world["agreement"]["id"], "fifth_session_id": sessions[4]["id"]}


def test_recognition_tier_earned_persists_none_below_bronze_hours(api):
    """PRD §3.3: "The persisted `recognition_tier` is the EARNED variant,
    counting DELIVERED sessions only, and it is recomputed on every funding
    record and on every delivered session."
    PRD §3.3: "failing that, BRONZE requires at least 10 hours together with at
    least 500,000 cents, or funding alone of at least 2,000,000 cents;
    otherwise the tier is NONE."

    Design: Difficulty/dual_variant_calc/recognition_tier_earned_none_vs_projected_bronze
    """
    ctx = _recognition_world()
    agr = get_agreement(ctx["agreement_id"])
    assert agr["sponsor_volunteer_hours"] == pytest.approx(8.0, abs=1e-9), "4 x 2.0 delivered"
    assert agr["recognition_tier"] == "NONE", "8.0 hours < 10: the BRONZE gate stays shut"


def test_recognition_tier_projected_counts_scheduled_session(api):
    """PRD §3.8: "`recognition_tier_projected` applies the same ladder to
    sponsor hours counting TENTATIVE, SCHEDULED, NEEDS_SUBSTITUTE, and
    DELIVERED sessions alike, giving funders a look ahead; the projection
    lives only in this report and is never stored."

    Design: Difficulty/dual_variant_calc/recognition_tier_earned_none_vs_projected_bronze
    """
    ctx = _recognition_world()
    prov = get_evaluation(ctx["agreement_id"], variant="PROVISIONAL")
    assert prov["recognition_tier_earned"] == "NONE"
    assert prov["recognition_tier_projected"] == "BRONZE", (
        "8.0 delivered + 2.0 scheduled == 10.0 hours with 500000 funding opens BRONZE"
    )
    assert prov["sponsor_volunteer_hours"] == pytest.approx(10.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Difficulty: recognition tier AND/OR gate (two tests)
# ---------------------------------------------------------------------------

def _and_or_gate_world():
    """All five 120-minute sessions DELIVERED by the sponsor's volunteer;
    pledge 500000 with no funding recorded yet (hours 10.0, funding 0)."""
    world = base_world(
        session_count=5, minutes_per_session=120, program_code="JA-FIN2",
        pledge_cents=500000, assemble=50,
    )
    vol1 = world["volunteer"]["id"]
    delivery = make_delivery(world["agreement"]["id"], vol1, enrolled_count=10, classroom_label="Room 5")
    plan_delivery(delivery["id"])
    sessions = [
        add_session(delivery["id"], vol1, d, start_minutes=540, end_minutes=660, confirm=True)
        for d in TUESDAYS_5
    ]
    schedule_delivery(delivery["id"])
    for session, date in zip(sessions, TUESDAYS_5):
        record_session_delivery(session["id"], date)
    return {"agreement_id": world["agreement"]["id"]}


def test_recognition_tier_hours_alone_do_not_open_bronze(api):
    """PRD §3.3: "The ladder runs in strict precedence: GOLD requires at least
    40 sponsor hours and at least 2,000,000 cents of recorded funding; failing
    that, SILVER requires at least 25 hours together with at least 1,000,000
    cents, or at least 60 hours alone; failing that, BRONZE requires at least
    10 hours together with at least 500,000 cents, or funding alone of at
    least 2,000,000 cents; otherwise the tier is NONE."

    Design: Difficulty/combinatorial_formula/recognition_tier_multi_input_and_or_gate
    """
    ctx = _and_or_gate_world()
    agr = get_agreement(ctx["agreement_id"])
    assert agr["sponsor_volunteer_hours"] == pytest.approx(10.0, abs=1e-9)
    assert agr["funding_received_cents"] == 0
    assert agr["recognition_tier"] == "NONE", (
        "10.0 hours alone satisfy neither the AND gate nor the 2,000,000-cent funding-only path"
    )


def test_recognition_tier_funding_record_flips_same_hours_to_bronze(api):
    """PRD §3.3: "A successful record adds the amount to
    `funding_received_cents` and recomputes the sponsor recognition tier."
    PRD §3.3: "Note the asymmetry: a funding-only path exists to BRONZE, but
    GOLD never passes without the 40-hour threshold."

    Design: Difficulty/combinatorial_formula/recognition_tier_multi_input_and_or_gate
    """
    ctx = _and_or_gate_world()
    resp = api_client.transition_partnership_agreement(
        ctx["agreement_id"], {"action": "RECORD_FUNDING", "amount_cents": 500000},
        DIRECTOR,
    )
    data = validate_success(resp, 200)
    assert data["funding_received_cents"] == 500000, "received == pledge: inclusive boundary"
    assert data["recognition_tier"] == "BRONZE", "10.0 hours AND 500000 cents opens BRONZE"
    assert data["recognition_tier"] != "GOLD", "GOLD's AND gate needs 2,000,000 cents"
    assert get_agreement(ctx["agreement_id"])["recognition_tier"] == "BRONZE"


# ---------------------------------------------------------------------------
# Difficulty: hours conserved across substitution and no-show (two tests)
# ---------------------------------------------------------------------------

def _hours_conservation_world():
    """4x90-minute sessions (vol1); s1 DELIVERED, s2 substituted to vol2 then
    DELIVERED, s3 recorded NO_SHOW, s4 left SCHEDULED."""
    world = base_world(program_code="JA-BIZ5", minutes_per_session=90, assemble=20)
    second = add_partner_with_volunteer()
    vol1 = world["volunteer"]["id"]
    vol2 = second["volunteer"]["id"]
    delivery = make_delivery(world["agreement"]["id"], vol1, enrolled_count=10, classroom_label="Room 19")
    plan_delivery(delivery["id"])
    sessions = [
        add_session(delivery["id"], vol1, d, start_minutes=540, end_minutes=630, confirm=True)
        for d in TUESDAYS_4
    ]
    schedule_delivery(delivery["id"])

    record_session_delivery(sessions[0]["id"], "2026-09-08")  # vol1 += 1.5
    version = get_delivery(delivery["id"])["version"]
    sub = api_client.substitute_session(
        sessions[1]["id"], {"new_volunteer_id": vol2, "expected_delivery_version": version}, COORDINATOR
    )
    sub_data = validate_success(sub, 200)
    record_session_delivery(sessions[1]["id"], "2026-09-15")  # vol2 += 1.5
    set_clock("2026-09-22T09:00:00Z")
    no_show = api_client.transition_session(sessions[2]["id"], {"action": "RECORD_NO_SHOW"}, COORDINATOR)
    validate_success(no_show, 200)  # credits nothing
    return {
        "agreement_id": world["agreement"]["id"],
        "vol1": vol1,
        "vol2": vol2,
        "substituted": sub_data,
        "delivery_id": delivery["id"],
    }


def test_substitution_credits_new_volunteer_not_original(api):
    """PRD §3.5: "Success credits the volunteer session hours — the session's
    duration in minutes divided by 60, rounded half-up to two decimal places
    for that session before joining any sum — and then recomputes everything
    the session feeds: the volunteer's `hours_contributed`, the agreement's
    `sponsor_volunteer_hours` and EARNED recognition tier, and the delivery's
    `sessions_delivered_count`."
    PRD §3.5: "Success writes `volunteer_id`, recomputes
    `sessions_blocked_count`, and increments the delivery's `version` by 1."

    Design: Difficulty/compensating_invariant/volunteer_hours_conserved_across_substitution_and_no_show
    """
    ctx = _hours_conservation_world()
    assert ctx["substituted"]["volunteer_id"] == ctx["vol2"]
    assert ctx["substituted"]["status"] == "SCHEDULED"
    assert get_volunteer(ctx["vol1"])["hours_contributed"] == pytest.approx(1.5, abs=1e-9), (
        "only the first session credits vol1; the substituted session does not"
    )
    assert get_volunteer(ctx["vol2"])["hours_contributed"] == pytest.approx(1.5, abs=1e-9)


def test_no_show_contributes_nothing_and_hours_conserve(api):
    """PRD §3.5: "NO_SHOW and CANCELLED sessions contribute no hours to any
    total."
    PRD §3.8: "`total_volunteer_hours` sums the whole pool;
    `sponsor_volunteer_hours` sums only pool sessions whose assigned volunteer
    belongs to the sponsor partner."

    Design: Difficulty/compensating_invariant/volunteer_hours_conserved_across_substitution_and_no_show
    """
    ctx = _hours_conservation_world()
    fin = get_evaluation(ctx["agreement_id"], variant="FINAL")
    assert_evaluation_report(fin)
    assert fin["total_volunteer_hours"] == pytest.approx(3.0, abs=1e-9), "1.5 + 1.5 conserved"
    assert fin["sessions_delivered"] == 2, "the NO_SHOW session is not counted"
    assert fin["sponsor_volunteer_hours"] == pytest.approx(1.5, abs=1e-9), (
        "only vol1 belongs to the sponsor partner"
    )
