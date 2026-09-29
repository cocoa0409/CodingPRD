"""Difficulty: transitive cascades, validation-priority pairs and exact boundaries.

Three design rules are exercised here, all of them multi-hop or single-hundredth
distinctions that a partially correct implementation gets wrong in a way no
smoke test notices:

* `transitive_cascade` — the five-hop imposition cascade of PRD §3.8 and the
  four-hop overturn cascade of PRD §3.9, each of which must reach a *sibling*
  case of the same student and re-price its office band.
* `priority_pair_validation_conflict` — the two collisions PRD §2.9 spells out
  by name: state (rank 13) over notice period (rank 38) on hearing scheduling,
  and the gradebook lookup (rank 32) over the effective-date check (rank 44) on
  formal sanction creation.
* `boundary_precision_check` — the 45.00 / 44.99 similarity band boundary of
  PRD §3.3 and the three simultaneously-exact strict inequalities behind
  `monitoring_flag` in PRD §3.1.

Every asserted literal is re-derived from PRD §3 in the docstring that claims
it.  The harness restarts the server before each test, so each test rebuilds
its whole world through public endpoints from an empty store with the clock at
`2026-08-01T00:00:00Z`.
"""
from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_reporter_headers, make_student_headers

# ---------------------------------------------------------------------------
# Local world builders.
#
# `fixtures.seed_actors` mints its own officer / dean / registrar headers
# internally, so it cannot be handed the acting identities this suite receives
# from `conftest`.  The actor spine is therefore assembled here from the same
# frozen leaf helpers, producing the identical `world` key set — which lets
# every later (phased, world-advancing) `fixtures` composite be reused
# unchanged, while the `officer`, `dean` and `registrar` fixtures stay the only
# source of acting identities.
# ---------------------------------------------------------------------------


def _seed_actors(api, officer, dean, registrar, clock=fixtures.CLOCK_T0, **dept_overrides):
    """Clock, department, trained reporter, student and the ENGL-201 offering."""
    fixtures.set_clock(clock, officer, api)
    dept = fixtures.create_department(officer, api, **dept_overrides)
    reporter = fixtures.create_faculty(dept["id"], trained=True, headers=officer, client=api)
    student = fixtures.create_student(officer, api, class_year=3)
    offering = fixtures.create_offering(dept["id"], reporter["id"], officer, api)
    return {
        "clock": clock,
        "officer": officer,
        "dean": dean,
        "registrar": registrar,
        "dept": dept,
        "reporter": reporter,
        "reporter_h": make_reporter_headers(reporter["id"]),
        "student": student,
        "student_h": make_student_headers(student["id"]),
        "offering": offering,
        "evidence": [],
        "votes": [],
        "panelists": [],
    }


def _sibling_view(world):
    """A shallow copy whose `case` is the sibling, so the composites drive it.

    Mutating `view["case"]` never disturbs `world["case"]`, and the shared
    actor rows (reporter, student, room, panel) are deliberately the same.
    """
    view = dict(world)
    view["case"] = world["sibling"]
    return view


def _notification_kinds(api, case_id, headers):
    """Every notification kind on record for a case (PRD §2.3: paginated)."""
    rows, _meta = assertions.validate_list(
        api.list_case_notifications(case_id, headers, params={"limit": 100})
    )
    return [row["kind"] for row in rows]


def _case(api, case_id, headers):
    """The STORED case row.  `GET /integrity/cases/{id}` never recomputes."""
    return validate_success(api.get_case(case_id, headers))


def _impose_cascade_world(api, officer, dean, registrar):
    """Case A DECIDED with a PROPOSED rank-4 sanction; sibling B INFORMAL_PROPOSED.

    Case A (ENGL-201) is decided RESPONSIBLE on a panel recommendation of 4, so
    its band is [3, 5] and a rank-4 `TRANSCRIPT_NOTATION_ONLY` proposal is
    legal.  Case B (ENGL-202) already carries a rank-3 `GRADE_PENALTY_COURSE`
    proposal inside its then-current informal band [1, 3].  Nothing is imposed
    yet, so the student's `prior_upheld_count` and `active_sanction_points` are
    both 0 at the moment of the trigger.
    """
    world = _seed_actors(api, officer, dean, registrar)
    fixtures.seed_draft_report(world, True, api)
    fixtures.seed_submitted_report(world, api)
    fixtures.seed_accepted_report(world, api)
    fixtures.seed_case(world, api)

    # Sibling case B on a DIFFERENT course code, opened before any finding.
    fixtures.seed_sibling_case(world, api, course_code="ENGL-202")
    sibling = _sibling_view(world)
    fixtures.set_pathway(sibling, "INFORMAL", api)
    fixtures.send_allegation_notice(sibling, 5, api)
    fixtures.propose_informal_resolution(sibling, 3, "2026-08-25T00:00:00Z", api)
    world["sibling"] = sibling["case"]
    world["sibling_sanction"] = sibling["sanction"]

    # Case A through the formal hearing to a PROPOSED rank-4 sanction.
    fixtures.set_pathway(world, "FORMAL", api)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.acknowledge_notice(world, api)
    fixtures.seed_panel(world, 3, client=api)
    fixtures.schedule_hearing(world, client=api)
    fixtures.convene_hearing(world, client=api)
    fixtures.cast_vote(world, 0, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(world, 1, "RESPONSIBLE", 6, api)
    fixtures.cast_vote(world, 2, "NOT_RESPONSIBLE", None, api)
    fixtures.decide_hearing(world, api)
    fixtures.propose_sanction(world, 4, "2026-08-21T00:00:00Z", api)
    return world


# ---------------------------------------------------------------------------
# transitive_cascade — the five-hop imposition cascade (PRD §3.8)
# ---------------------------------------------------------------------------


def test_impose_cascade_hops_one_to_three_price_the_sanction_the_case_and_the_student(
    api, officer, dean, registrar
):
    """One impose call walks the first three hops of the §3.8 cascade.

    PRD §3.8: "Hop one, on the sanction itself: `status` becomes `IMPOSED` and
    `imposed_at` is set to the current logical clock." — the clock sits at the
    session start 2026-08-20T10:00:00Z.  "Hop two, on the case:
    `adjudication_status` becomes `SANCTION_IMPOSED` ... and `notation_status`
    becomes `PENDING_POSTING` when the sanction's `ladder_rank` is 4 or
    greater".  "Hop three, on the student: `prior_upheld_count` is recomputed
    and now includes this case, `active_sanction_points` increases by the
    sanction's `ladder_rank`, and `standing` is re-derived".  PRD §3.2 pins the
    re-derivation: "`standing` is ... `PROBATION` when any imposed sanction has
    `ladder_rank` exactly 5, otherwise `GOOD_STANDING` — note that a rank-4
    sanction leaves the student in good standing."  Hop four re-assesses only
    the student's OTHER cases, so case A's own `severity_index` stays 44.00
    (PLAGIARISM base 20.00 + 60.00 x 0.40 evidence contribution + 0 cross).

    Design: Difficulty/transitive_cascade/impose_cascade_five_hops_reaches_a_sibling_case_and_vacates_its_proposal
    """
    world = _impose_cascade_world(api, officer, dean, registrar)
    case_a_id = world["case"]["id"]
    sanction_a_id = world["sanction"]["id"]

    imposed = validate_success(api.impose_sanction(sanction_a_id, officer))

    # HOP 1 — on the sanction itself.
    assert imposed["status"] == "IMPOSED"
    assertions.assert_instant_equals(
        imposed["imposed_at"], "2026-08-20T10:00:00Z", "imposed_at"
    )
    stored_sanction = validate_success(api.get_sanction(sanction_a_id, officer))
    assert stored_sanction["status"] == "IMPOSED"
    assert stored_sanction["ladder_rank"] == 4
    assert stored_sanction["kind"] == "TRANSCRIPT_NOTATION_ONLY"
    assertions.assert_instant_equals(
        stored_sanction["imposed_at"], "2026-08-20T10:00:00Z", "stored imposed_at"
    )

    # HOP 2 — both of case A's independent state dimensions (PRD §2.10).
    case_a = _case(api, case_a_id, officer)
    assert case_a["adjudication_status"] == "SANCTION_IMPOSED"
    assert case_a["notation_status"] == "PENDING_POSTING"
    assert case_a["expungement_eligible_at"] is None

    # HOP 3 — the student aggregate.
    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["prior_upheld_count"] == 1
    assert student["active_sanction_points"] == 4
    assert student["standing"] == "GOOD_STANDING"

    # Hop four never touches the case that triggered the cascade.
    assertions.assert_pct_equals(case_a["severity_index"], 44.00, "case A severity_index")
    assertions.assert_pct_equals(
        case_a["provisional_severity_index"], 44.00, "case A provisional"
    )
    assert case_a["cross_course_pattern_points"] == 0
    assert case_a["prior_escalation_points"] == 0
    assert case_a["recommended_ladder_rank"] == 4


def test_impose_cascade_hops_four_and_five_vacate_the_sibling_proposal_at_56_00(
    api, officer, dean, registrar
):
    """Hops four and five land on a DIFFERENT case and vacate its proposal.

    PRD §3.8: "Hop four, on the student's other cases: every other case of the
    same student whose `adjudication_status` is neither `CLOSED` nor
    `DISMISSED` is re-assessed ... For each, `cross_course_pattern_points`,
    `prior_upheld_count_at_assessment`, `prior_escalation_points`,
    `provisional_severity_index`, `severity_index` and
    `recommended_ladder_rank` are recomputed from the student's new
    `prior_upheld_count`."  "Hop five ... any sanction still in `PROPOSED`
    whose `ladder_rank` now falls outside that case's recomputed office band
    moves to `VACATED` with `vacated_reason` `LADDER_RECOMPUTE`, and a
    notification of kind `SANCTION_RECOMPUTE_NOTICE` is created on that sibling
    case."  The numbers: ENGL-201 is now one distinct OTHER course code, so
    §3.4 gives 4 cross points; provisional = 20.00 + 24.00 + 4 = 48.00; §3.4
    selects escalation "from the **provisional** index, not the final one: ...
    8 with exactly one prior and a provisional index below 50.00"; severity =
    56.00, tier 5 (below 70.00), band [4, 6] — so rank 3 falls outside.  PRD
    §3.4 also pins the informal variant: "`cross_course_pattern_points` and
    `prior_escalation_points` are excluded entirely", leaving 44.00 / rank 3.

    Design: Difficulty/transitive_cascade/impose_cascade_five_hops_reaches_a_sibling_case_and_vacates_its_proposal
    """
    world = _impose_cascade_world(api, officer, dean, registrar)
    case_b_id = world["sibling"]["id"]
    sanction_b_id = world["sibling_sanction"]["id"]

    validate_success(api.impose_sanction(world["sanction"]["id"], officer))

    # HOP 4 — read the STORED sibling row first; it is not recomputed on read.
    case_b = _case(api, case_b_id, officer)
    assert case_b["cross_course_pattern_points"] == 4
    assert case_b["prior_upheld_count_at_assessment"] == 1
    assertions.assert_pct_equals(
        case_b["provisional_severity_index"], 48.00, "case B provisional"
    )
    assert case_b["prior_escalation_points"] == 8, "escalation reads the provisional 48.00"
    assertions.assert_pct_equals(case_b["severity_index"], 56.00, "case B severity_index")
    assert case_b["severity_index"] != 62.00
    assert case_b["recommended_ladder_rank"] == 5

    # The band and the distinct-code count come from the computed read (§3.4).
    assessment = validate_success(api.get_severity_assessment(case_b_id, officer))
    assert assessment["distinct_other_course_codes"] == 1
    assert assessment["tier_rank"] == 5
    assert assessment["permitted_band_min"] == 4
    assert assessment["permitted_band_max"] == 6

    # HOP 5 — the sibling's PROPOSED rank-3 sanction is now out of band.
    sanction_b = validate_success(api.get_sanction(sanction_b_id, officer))
    assert sanction_b["status"] == "VACATED"
    assert sanction_b["vacated_reason"] == "LADDER_RECOMPUTE"
    assert sanction_b["ladder_rank"] == 3
    assert "SANCTION_RECOMPUTE_NOTICE" in _notification_kinds(api, case_b_id, officer)

    # The recompute vacates the proposal without moving case B's state machine.
    assert case_b["adjudication_status"] == "INFORMAL_PROPOSED"
    assertions.assert_pct_equals(
        case_b["informal_severity_index"], 44.00, "case B informal index"
    )
    assert case_b["informal_recommended_ladder_rank"] == 3

    # The vacated proposal was never IMPOSED, so it never entered the ledger.
    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["active_sanction_points"] == 4


# ---------------------------------------------------------------------------
# transitive_cascade — the four-hop overturn cascade (PRD §3.9)
# ---------------------------------------------------------------------------


def _overturn_cascade_world(api, officer, dean, registrar):
    """Case A imposed, posted and UNDER_REVIEW; sibling B DECIDED at rank 6.

    Ordering note.  Case B is opened and decided while case A is
    unambiguously in `SANCTION_IMPOSED`, so the `prior_upheld_count` that PRD
    §3.2 defines over cases "whose `adjudication_status` is `SANCTION_IMPOSED`
    or `CLOSED`" is 1 on every reading, and case B therefore opens with 4 cross
    points, 8 escalation points, a severity index of 56.00 and the band [4, 6]
    that admits its rank-6 proposal.  The appeal is filed before the clock
    leaves the ten-day window of PRD §3.9 and screened afterwards.
    """
    world = _seed_actors(api, officer, dean, registrar)
    fixtures.seed_draft_report(world, True, api)
    fixtures.seed_submitted_report(world, api)
    fixtures.seed_accepted_report(world, api)
    fixtures.seed_case(world, api)
    fixtures.set_pathway(world, "FORMAL", api)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.acknowledge_notice(world, api)
    fixtures.seed_panel(world, 3, client=api)
    fixtures.schedule_hearing(world, client=api)
    fixtures.convene_hearing(world, client=api)
    fixtures.cast_vote(world, 0, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(world, 1, "RESPONSIBLE", 6, api)
    fixtures.cast_vote(world, 2, "NOT_RESPONSIBLE", None, api)
    fixtures.decide_hearing(world, api)
    fixtures.propose_sanction(world, 4, "2026-08-21T00:00:00Z", api)
    fixtures.impose_sanction(world, client=api)
    fixtures.post_notation(world, api)
    # Filed at decided_at itself, well inside the ten-day window.
    fixtures.file_appeal(world, "EVIDENCE", api)

    # Sibling case B, opened while case A is still SANCTION_IMPOSED.
    fixtures.seed_sibling_case(world, api, course_code="ENGL-202")
    sibling = _sibling_view(world)
    fixtures.set_pathway(sibling, "FORMAL", api)
    fixtures.send_allegation_notice(sibling, 5, api)
    fixtures.acknowledge_notice(sibling, api)
    fixtures.schedule_hearing(
        sibling, "2026-09-05T10:00:00Z", "2026-09-05T11:30:00Z", api
    )
    fixtures.convene_hearing(sibling, "2026-09-05T10:00:00Z", api)
    fixtures.cast_vote(sibling, 0, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(sibling, 1, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(sibling, 2, "NOT_RESPONSIBLE", None, api)
    fixtures.decide_hearing(sibling, api)
    fixtures.propose_sanction(sibling, 6, "2026-09-06T00:00:00Z", api)
    world["sibling"] = sibling["case"]
    world["sibling_sanction"] = sibling["sanction"]
    world["clock"] = "2026-09-05T10:00:00Z"

    # Case A is still SANCTION_IMPOSED, so screening is legal and records it.
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)
    return world


def test_overturn_cascade_hops_one_to_three_expunge_the_notation_and_the_ledgers(
    api, officer, dean, registrar
):
    """OVERTURNED unwinds the sanction, the notation and all three ledgers.

    PRD §3.9: "Hop one: the appeal's `status` becomes `OVERTURNED` and
    `decided_at` is set to the clock.  Hop two, on the case: `overturned`
    becomes true, `responsibility_finding` becomes `NOT_RESPONSIBLE`,
    `finding_basis` becomes `APPEAL`, `adjudication_status` becomes `CLOSED`,
    `pre_appeal_adjudication_status` returns to null, `notation_status` becomes
    `EXPUNGED` if it was `POSTED` ... and every sanction of the case in
    `PROPOSED`, `ACCEPTED` or `IMPOSED` moves to `VACATED` with
    `vacated_reason` `APPEAL_OVERTURNED`.  Hop three, on the student:
    `prior_upheld_count` is recomputed and this case no longer counts,
    `active_sanction_points` falls by the `ladder_rank` of every sanction that
    had been imposed, `standing` and `transcript_notation` are re-derived, and
    the department's `open_case_count` falls by one."  PRD §2.11 pins the room
    ledger against the same call: it "always equals, summed over the room's
    hearing sessions whose status is `SCHEDULED`, `CONVENED`, `DECIDED` or
    `ADJOURNED`, the whole minutes ... plus twice the room's `buffer_minutes`"
    — two 90-minute DECIDED sessions at a 30-minute buffer, so 2 x 150 = 300.

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_four_hops_unwinds_the_notation_and_the_sibling_band
    """
    world = _overturn_cascade_world(api, officer, dean, registrar)
    case_a_id = world["case"]["id"]
    student_id = world["student"]["id"]
    appeal_id = world["appeal"]["id"]
    sanction_a_id = world["sanction"]["id"]

    before = validate_success(api.get_student(student_id, officer))
    assert before["active_sanction_points"] == 4
    assert before["transcript_notation"] == "POSTED"
    dept_before = validate_success(api.get_department(world["dept"]["id"], officer))
    assert dept_before["open_case_count"] == 2

    decided = validate_success(
        api.decide_appeal(
            appeal_id,
            factories.appeal_decision_payload(
                "OVERTURNED",
                decision_reason=(
                    "The similarity match is self-plagiarism of the appellant's "
                    "own prior work."
                ),
            ),
            dean,
        )
    )

    # HOP 1 — the appeal row.
    assert decided["status"] == "OVERTURNED"
    assertions.assert_instant_equals(
        decided["decided_at"], "2026-09-05T10:00:00Z", "appeal decided_at"
    )
    assert validate_success(api.get_appeal(appeal_id, officer))["status"] == "OVERTURNED"

    # HOP 2 — the case and its sanction.
    case_a = _case(api, case_a_id, officer)
    assert case_a["overturned"] is True
    assert case_a["responsibility_finding"] == "NOT_RESPONSIBLE"
    assert case_a["finding_basis"] == "APPEAL"
    assert case_a["adjudication_status"] == "CLOSED"
    assert case_a["pre_appeal_adjudication_status"] is None
    assert case_a["notation_status"] == "EXPUNGED"
    sanction_a = validate_success(api.get_sanction(sanction_a_id, officer))
    assert sanction_a["status"] == "VACATED"
    assert sanction_a["vacated_reason"] == "APPEAL_OVERTURNED"

    # HOP 3 — the student aggregate and the department ledger.
    student = validate_success(api.get_student(student_id, officer))
    assert student["prior_upheld_count"] == 0
    assert student["active_sanction_points"] == 0
    assert student["standing"] == "GOOD_STANDING"
    assert student["transcript_notation"] == "EXPUNGED"
    dept = validate_success(api.get_department(world["dept"]["id"], officer))
    assert dept["open_case_count"] == 1

    # The room ledger is untouched by the appeal outcome (PRD §2.11).
    room = validate_success(api.get_hearing_room(world["room"]["id"], officer))
    assert room["booked_minutes_total"] == 300
    assert "APPEAL_OUTCOME_NOTICE" in _notification_kinds(api, case_a_id, officer)


def test_overturn_cascade_hop_four_rederives_the_sibling_band_and_vacates_its_proposal(
    api, officer, dean, registrar
):
    """The fourth hop re-prices a DIFFERENT case and voids its rank-6 proposal.

    PRD §3.9: "Hop four, on the student's other cases: every other case whose
    `adjudication_status` is neither `CLOSED` nor `DISMISSED` is re-assessed in
    `created_at` ascending order, recomputing `cross_course_pattern_points`,
    `prior_upheld_count_at_assessment`, `prior_escalation_points`,
    `provisional_severity_index`, `severity_index` and
    `recommended_ladder_rank`, and any sibling sanction in `PROPOSED` that now
    falls outside its recomputed office band moves to `VACATED` with
    `vacated_reason` `LADDER_RECOMPUTE`."  The overturn strips case A from both
    detectors at once — PRD §3.2 counts only cases "whose
    `responsibility_finding` is `RESPONSIBLE`, whose `overturned` is false", and
    §3.4 filters the pattern detector the same way — so case B falls from 4
    cross points and one prior to 0 and 0: provisional 20.00 + 24.00 = 44.00,
    escalation 0, severity 44.00.  PRD §3.4: "below 55.00 gives 3", and "a case
    whose tier rank is 3 but whose panel recommended 4 ends with a recommended
    rank of 4 and a band from 3 to 5" — so the rank-6 proposal that was legal
    inside the pre-appeal band [4, 6] is now out of band.

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_four_hops_unwinds_the_notation_and_the_sibling_band
    """
    world = _overturn_cascade_world(api, officer, dean, registrar)
    case_b_id = world["sibling"]["id"]
    sanction_b_id = world["sibling_sanction"]["id"]

    # Pre-trigger: case B was priced WITH case A's upheld finding.
    before = _case(api, case_b_id, officer)
    assert before["cross_course_pattern_points"] == 4
    assert before["prior_upheld_count_at_assessment"] == 1
    assertions.assert_pct_equals(
        before["provisional_severity_index"], 48.00, "case B provisional before"
    )
    assert before["prior_escalation_points"] == 8
    assertions.assert_pct_equals(before["severity_index"], 56.00, "case B severity before")
    assert before["recommended_ladder_rank"] == 5
    assert before["panel_severity_recommendation"] == 4
    sanction_before = validate_success(api.get_sanction(sanction_b_id, officer))
    assert sanction_before["status"] == "PROPOSED"
    assert sanction_before["ladder_rank"] == 6
    assert sanction_before["kind"] == "SUSPENSION_ONE_TERM"
    assert sanction_before["vacated_reason"] is None

    validate_success(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload(
                "OVERTURNED",
                decision_reason=(
                    "The panel relied on an exhibit the appellant was never shown."
                ),
            ),
            dean,
        )
    )

    # HOP 4 — the STORED sibling row, which a read never recomputes.
    case_b = _case(api, case_b_id, officer)
    assert case_b["cross_course_pattern_points"] == 0
    assert case_b["prior_upheld_count_at_assessment"] == 0
    assertions.assert_pct_equals(
        case_b["provisional_severity_index"], 44.00, "case B provisional after"
    )
    assert case_b["prior_escalation_points"] == 0
    assertions.assert_pct_equals(case_b["severity_index"], 44.00, "case B severity after")
    assert case_b["severity_index"] != 56.00
    assert case_b["recommended_ladder_rank"] == 4
    assert case_b["panel_severity_recommendation"] == 4

    # The recomputed band, from the read that re-runs the assessment (§3.4).
    assessment = validate_success(api.get_severity_assessment(case_b_id, officer))
    assert assessment["distinct_other_course_codes"] == 0
    assert assessment["tier_rank"] == 3
    assert assessment["recommended_ladder_rank"] == 4
    assert assessment["permitted_band_min"] == 3
    assert assessment["permitted_band_max"] == 5

    # Rank 6 now sits above the band, so the proposal is vacated — and the
    # reason distinguishes hop four from the appeal's own hop two.
    sanction_b = validate_success(api.get_sanction(sanction_b_id, officer))
    assert sanction_b["status"] == "VACATED"
    assert sanction_b["vacated_reason"] == "LADDER_RECOMPUTE"
    assert sanction_b["vacated_reason"] != "APPEAL_OVERTURNED"
    assert sanction_b["ladder_rank"] == 6

    # Case B is re-priced, not re-routed: its state machine does not move.
    assert case_b["adjudication_status"] == "DECIDED"
    assert case_b["responsibility_finding"] == "RESPONSIBLE"
    assert case_b["overturned"] is False

    # And case B stays open, so only case A left the department ledger.
    assert validate_success(api.get_department(world["dept"]["id"], officer))[
        "open_case_count"
    ] == 1


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict — rank 13 over rank 38 (PRD §2.9, §3.7)
# ---------------------------------------------------------------------------

_SHORT_NOTICE_START = "2026-08-03T10:00:00Z"
_SHORT_NOTICE_END = "2026-08-03T11:30:00Z"


def _scheduled_case_world(api, officer, dean, registrar):
    """A FORMAL case in HEARING_SCHEDULED, notice sent at 2026-08-01T00:00:00Z.

    The clock stays at `2026-08-01T00:00:00Z` throughout, so the allegation
    notice's `sent_at` is that instant and the ten-day notice floor opens on
    2026-08-11.  The first session sits at 2026-08-20T10:00:00Z, comfortably
    past the floor, and charges the room 90 + 2 x 30 = 150 minutes.
    """
    world = _seed_actors(api, officer, dean, registrar)
    fixtures.seed_draft_report(world, True, api)
    fixtures.seed_submitted_report(world, api)
    fixtures.seed_accepted_report(world, api)
    fixtures.seed_case(world, api)
    fixtures.set_pathway(world, "FORMAL", api)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.seed_panel(world, 3, client=api)
    fixtures.schedule_hearing(world, client=api)
    return world


def _session_ids_for_case(api, case_id, headers):
    rows, _meta = assertions.validate_list(
        api.list_hearing_sessions(headers, params={"case_id": case_id, "limit": 100})
    )
    return [row["id"] for row in rows]


def _short_notice_session_payload(world):
    """The SAME request in both rank-13 and rank-38 tests: only the state differs."""
    return factories.hearing_session_payload(
        world["case"]["id"],
        world["room"]["id"],
        world["chair"]["id"],
        [p["id"] for p in world["panelists"]],
        _SHORT_NOTICE_START,
        _SHORT_NOTICE_END,
    )


def test_state_check_at_priority_13_outranks_the_notice_period_check_at_priority_38(
    api, officer, dean, registrar
):
    """One request breaks both gates; only the rank-13 state error may come back.

    PRD §2.9: "On hearing scheduling, the state check at rank 13 outranks the
    notice-period check at rank 38: a case that is already `HEARING_SCHEDULED`
    and is handed a second session whose `start_at` is only two days after the
    governing notice reports `ERR_CASE_STATE_INVALID`, not
    `ERR_NOTICE_PERIOD_TOO_SHORT`."  Rank 13 covers "the case's
    `adjudication_status` does not admit the operation ... on
    `POST /integrity/hearing-sessions`", and §3.7 fixes the entry set: "The
    case's `adjudication_status` must be `NOTIFIED` or `FORMAL_REFERRED`".
    §2.9 also pins the store: "a rejected request leaves the store
    byte-identical to its pre-request state, including every derived counter and
    ledger."

    Design: Difficulty/priority_pair_validation_conflict/state_check_priority_13_outranks_notice_period_priority_38_and_returns_case_state_invalid
    """
    world = _scheduled_case_world(api, officer, dean, registrar)
    case_id = world["case"]["id"]
    room_id = world["room"]["id"]
    first_session_id = world["session"]["id"]

    assert _case(api, case_id, officer)["adjudication_status"] == "HEARING_SCHEDULED"

    error = validate_error(
        api.create_hearing_session(_short_notice_session_payload(world), officer),
        ApiErrorId.ERR_CASE_STATE_INVALID,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT.value, (
        "start_at 2026-08-03T10:00:00Z is only two days after the notice sent_at "
        "2026-08-01T00:00:00Z, but rank 13 must win over rank 38"
    )

    # No partial write: one session, one round, and the ledger still at 150.
    assert _session_ids_for_case(api, case_id, officer) == [first_session_id]
    case = _case(api, case_id, officer)
    assert case["hearing_round"] == 1
    assert case["adjudication_status"] == "HEARING_SCHEDULED"
    assert validate_success(api.get_hearing_room(room_id, officer))[
        "booked_minutes_total"
    ] == 150


def test_notice_period_error_surfaces_only_once_the_state_gate_is_cleared(
    api, officer, dean, registrar
):
    """The identical request reports rank 38 once the case is FORMAL_REFERRED.

    This is what makes the previous test an ordering proof rather than a
    coincidence: the payload is byte-identical, and only the case's stored
    `adjudication_status` changes.  PRD §3.7: cancellation "sets `status` to
    `CANCELLED`, releases exactly the minutes that scheduling reserved from the
    room's `booked_minutes_total`, and returns the case to `FORMAL_REFERRED`
    with `version` advanced.  `hearing_round` is **not** decremented".  With the
    rank-13 gate satisfied, §3.7's notice rule bites: "`start_at` must be at or
    after that notice's `sent_at` plus 10 days, otherwise
    `ERR_NOTICE_PERIOD_TOO_SHORT`" — the governing notice is unchanged, because
    cancelling creates no `REHEARING_NOTICE`.

    Design: Difficulty/priority_pair_validation_conflict/state_check_priority_13_outranks_notice_period_priority_38_and_returns_case_state_invalid
    """
    world = _scheduled_case_world(api, officer, dean, registrar)
    case_id = world["case"]["id"]
    room_id = world["room"]["id"]
    cancelled_session_id = world["session"]["id"]

    fixtures.cancel_hearing(world, api)

    cleared = _case(api, case_id, officer)
    assert cleared["adjudication_status"] == "FORMAL_REFERRED"
    assert cleared["hearing_round"] == 1, "cancellation never decrements the round"
    assert validate_success(api.get_hearing_room(room_id, officer))[
        "booked_minutes_total"
    ] == 0

    error = validate_error(
        api.create_hearing_session(_short_notice_session_payload(world), officer),
        ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_CASE_STATE_INVALID.value

    # Still rejected before any side effect, so the cancelled session stands alone.
    assert _session_ids_for_case(api, case_id, officer) == [cancelled_session_id]
    after = _case(api, case_id, officer)
    assert after["hearing_round"] == 1
    assert after["adjudication_status"] == "FORMAL_REFERRED"
    assert validate_success(api.get_hearing_room(room_id, officer))[
        "booked_minutes_total"
    ] == 0


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict — rank 32 over rank 44 (PRD §2.9, §3.8)
# ---------------------------------------------------------------------------

_BEFORE_DECISION = "2026-08-19T00:00:00Z"
_DECIDED_AT = "2026-08-20T10:00:00Z"


def _decided_case_world(api, officer, dean, registrar, panel_recommendation=2):
    """DECIDED at 2026-08-20T10:00:00Z on a panel recommendation of 2.

    The band is deliberately [2, 4] built from a panel recommendation of 2, not
    4: PRD §3.4 makes `recommended_ladder_rank` "the greater of the tier rank
    and the panel recommendation", and the tier rank of the canonical 44.00
    index is 3, so the recommendation of 2 cannot raise it.  Rank 2 therefore
    sits inside the band and neither §2.9 rank 54 nor rank 55 can mask the pair
    under test.  The offering's gradebook holds exactly ESSAY, MIDTERM, PROJECT
    and FINAL — there is no LAB component anywhere in the store.
    """
    world = _seed_actors(api, officer, dean, registrar)
    fixtures.seed_draft_report(world, True, api)
    fixtures.seed_submitted_report(world, api)
    fixtures.seed_accepted_report(world, api)
    fixtures.seed_case(world, api)
    fixtures.set_pathway(world, "FORMAL", api)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.acknowledge_notice(world, api)
    fixtures.seed_panel(world, 3, client=api)
    fixtures.schedule_hearing(world, client=api)
    fixtures.convene_hearing(world, client=api)
    fixtures.cast_responsible_majority(world, panel_recommendation, api)
    fixtures.decide_hearing(world, api)
    return world


def _sanction_count_for_case(api, case_id, headers):
    _rows, meta = assertions.validate_list(
        api.list_sanctions(headers, params={"case_id": case_id, "limit": 100})
    )
    return meta["total_count"]


def test_grade_component_lookup_at_priority_32_outranks_the_effective_date_check_at_44(
    api, officer, dean, registrar
):
    """The 404 referential check wins, so even the status class flips to 404.

    PRD §2.9: "On formal sanction creation, the gradebook-lookup check at rank
    32 outranks the effective-date check at rank 44: a decided case handed an
    assignment-grade-penalty proposal whose `grade_component_code` is absent
    from the offering and whose `effective_from` predates the finding reports
    `ERR_GRADE_COMPONENT_NOT_FOUND`, not
    `ERR_SANCTION_EFFECTIVE_BEFORE_DECISION`."  Rank 32 is
    "`ERR_GRADE_COMPONENT_NOT_FOUND` (404)" while rank 44 is HTTP 409, so the
    ordering decides the status class as well as the id.  §2.9 also guarantees
    that "a rejected request leaves the store byte-identical to its pre-request
    state" — including the optimistic-concurrency `version` that §2.8 makes the
    client re-read.

    Design: Difficulty/priority_pair_validation_conflict/referential_check_priority_32_outranks_effective_date_priority_44_on_sanction_create
    """
    world = _decided_case_world(api, officer, dean, registrar)
    case_id = world["case"]["id"]

    decided = _case(api, case_id, officer)
    assertions.assert_instant_equals(decided["decided_at"], _DECIDED_AT, "decided_at")
    assert decided["panel_severity_recommendation"] == 2
    assert decided["recommended_ladder_rank"] == 3
    version_before = decided["version"]

    response = api.create_sanction(
        factories.sanction_payload(
            case_id,
            version_before,
            2,
            _BEFORE_DECISION,
            kind="GRADE_PENALTY_ASSIGNMENT",
            grade_component_code="LAB",
        ),
        officer,
    )
    error = validate_error(response, ApiErrorId.ERR_GRADE_COMPONENT_NOT_FOUND, 404)
    assert response.status_code == 404, "the rank-32 error is a 404, not a 409"
    assert error["error_id"] != ApiErrorId.ERR_SANCTION_EFFECTIVE_BEFORE_DECISION.value, (
        "2026-08-19T00:00:00Z precedes decided_at 2026-08-20T10:00:00Z, but rank 32 "
        "must win over rank 44"
    )

    # The band was satisfied, so no ladder rule could have produced the error.
    assessment = validate_success(api.get_severity_assessment(case_id, officer))
    assert assessment["permitted_band_min"] == 2
    assert assessment["permitted_band_max"] == 4
    assert assessment["recommended_ladder_rank"] == 3

    # Nothing was written, and the rejected proposal did not consume a version.
    assert _sanction_count_for_case(api, case_id, officer) == 0
    after = _case(api, case_id, officer)
    assert after["version"] == version_before
    assert after["adjudication_status"] == "DECIDED"


def test_effective_date_error_surfaces_once_the_grade_component_resolves(
    api, officer, dean, registrar
):
    """Swap LAB for the real ESSAY code and the same request reports rank 44.

    Only the one field the rank-32 lookup reads changes, which is what makes the
    previous test an ordering proof: `effective_from` is still 2026-08-19.  PRD
    §2.9 rank 44: "`effective_from` is earlier than the case's `decided_at`, on
    `POST /integrity/sanctions` ... → `ERR_SANCTION_EFFECTIVE_BEFORE_DECISION`"
    (HTTP 409).  Because the bound is "earlier than", the same proposal dated
    exactly at `decided_at` is accepted, and PRD §3.8 fixes what it writes: "the
    sanction is created in `PROPOSED` with `origin` `OFFICE_PROPOSAL`,
    `imposed_at` null, `completed_at` null, `vacated_reason` null".

    Design: Difficulty/priority_pair_validation_conflict/referential_check_priority_32_outranks_effective_date_priority_44_on_sanction_create
    """
    world = _decided_case_world(api, officer, dean, registrar)
    case_id = world["case"]["id"]
    version_before = _case(api, case_id, officer)["version"]

    response = api.create_sanction(
        factories.sanction_payload(
            case_id,
            version_before,
            2,
            _BEFORE_DECISION,
            kind="GRADE_PENALTY_ASSIGNMENT",
            grade_component_code=constants.CANONICAL_GRADE_COMPONENTS[0]["code"],
        ),
        officer,
    )
    error = validate_error(
        response, ApiErrorId.ERR_SANCTION_EFFECTIVE_BEFORE_DECISION, 409
    )
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_GRADE_COMPONENT_NOT_FOUND.value

    assert _sanction_count_for_case(api, case_id, officer) == 0
    assert _case(api, case_id, officer)["version"] == version_before

    # The bound is exclusive, so the identical proposal dated at the finding
    # itself is accepted — proving nothing else in the request was wrong.
    created = validate_success(
        api.create_sanction(
            factories.sanction_payload(
                case_id,
                version_before,
                2,
                _DECIDED_AT,
                kind="GRADE_PENALTY_ASSIGNMENT",
                grade_component_code=constants.CANONICAL_GRADE_COMPONENTS[0]["code"],
            ),
            officer,
        ),
        201,
    )
    assert created["status"] == "PROPOSED"
    assert created["ladder_rank"] == 2
    assert created["kind"] == "GRADE_PENALTY_ASSIGNMENT"
    assert created["origin"] == "OFFICE_PROPOSAL"
    assert created["imposed_at"] is None
    assert created["vacated_reason"] is None
    assert _sanction_count_for_case(api, case_id, officer) == 1


# ---------------------------------------------------------------------------
# boundary_precision_check — the 45.00 / 44.99 similarity band (PRD §3.3)
# ---------------------------------------------------------------------------


def _submitted_similarity_report(api, world, similarity_pct, sha256, student=None):
    """One DRAFT report with exactly one 4-page SIMILARITY_REPORT, then submitted.

    Everything except `similarity_pct` is held constant: 4 pages give 2.00 page
    points, the single kind gives 1.00 x 10 = 10.00 diversity points, and one
    distinct kind means no corroboration bonus.
    """
    subject = student if student is not None else world["student"]
    report = fixtures.create_report(
        world["offering"]["id"], subject["id"], world["reporter_h"], api
    )
    fixtures.attach_similarity_evidence(
        report["id"],
        world["reporter_h"],
        api,
        similarity_pct=similarity_pct,
        sha256=sha256,
    )
    return validate_success(api.submit_report(report["id"], world["reporter_h"]))


def test_similarity_45_00_adjusts_to_40_00_and_takes_the_1_20_band_for_60_00(
    api, officer, dean, registrar
):
    """The adjusted 40.00 lands exactly on the 1.20 band and scores 60.00.

    PRD §3.3: "the adjusted similarity percentage is the greatest
    `similarity_pct` among the report's `SIMILARITY_REPORT` items, less an
    excluded-quote allowance of 5.00 ... the band multiplier is chosen from that
    adjusted value, not from the raw one: 1.20 when the adjusted value is 40.00
    or greater".  The worked example is explicit: "A single similarity report at
    45.00 with 4 pages adjusts to 40.00, takes the 1.20 band for 48.00
    similarity points, adds 2.00 page points and 10.00 diversity points with no
    corroboration, and scores 60.00."  The band bound is inclusive at 40.00, so
    this is the tightest point at which the multiplier still applies.

    Design: Difficulty/boundary_precision_check/similarity_band_boundary_45_00_versus_44_99_after_the_quote_allowance
    """
    world = _seed_actors(api, officer, dean, registrar)
    report = fixtures.create_report(
        world["offering"]["id"], world["student"]["id"], world["reporter_h"], api
    )
    assertions.assert_pct_equals(
        report["evidence_strength_score"], 0.00, "score before evidence"
    )
    assert report["evidence_complete"] is False

    # PRD §3.3: "Attaching an item recomputes the report's
    # `evidence_strength_score` and `evidence_complete` immediately."
    fixtures.attach_similarity_evidence(
        report["id"], world["reporter_h"], api, similarity_pct=45.00
    )
    on_attach = validate_success(api.get_report(report["id"], officer))
    assertions.assert_pct_equals(
        on_attach["evidence_strength_score"], 60.00, "score on attach"
    )
    assert on_attach["evidence_complete"] is True

    submitted = validate_success(api.submit_report(report["id"], world["reporter_h"]))
    assertions.assert_pct_equals(
        submitted["evidence_strength_score"], 60.00, "score on submit"
    )
    assert submitted["status"] == "SUBMITTED"
    assertions.assert_instant_equals(
        submitted["submitted_at"], fixtures.CLOCK_T0, "submitted_at"
    )

    stored = validate_success(api.get_report(report["id"], officer))
    assertions.assert_pct_equals(
        stored["evidence_strength_score"], 60.00, "stored score"
    )
    # 48.00 + 2.00 + 10.00 exactly; the 0.70 and 1.00 bands would give 30.00
    # similarity points and 40.00 points respectively.
    assert stored["evidence_strength_score"] != 40.00
    assert stored["evidence_strength_score"] != 51.99
    assert (
        stored["evidence_strength_score"]
        >= constants.THRESHOLDS["TRIAGE_ACCEPT_MIN_EVIDENCE_SCORE"]
    )


def test_similarity_44_99_falls_to_the_1_00_band_for_51_99_not_59_99(
    api, officer, dean, registrar
):
    """One hundredth less input drops the band and opens an 8.01-point gap.

    PRD §3.3: "The same item at 44.99 adjusts to 39.99, falls to the 1.00 band
    for 39.99 similarity points, and scores 51.99."  Two wrong readings are
    ruled out by exact literals: 59.99 comes from choosing the 1.20 band from
    the RAW 44.99 and applying it to the adjusted 39.99, and 65.99 comes from
    skipping the 5.00 allowance entirely (44.99 x 1.20 = 53.99, plus 2.00 plus
    10.00).  PRD §2.7 pins the representation: these values "carry exactly 2
    decimal places and are produced with decimal arithmetic, never binary
    floating point."

    Design: Difficulty/boundary_precision_check/similarity_band_boundary_45_00_versus_44_99_after_the_quote_allowance
    """
    world = _seed_actors(api, officer, dean, registrar)
    other_student = fixtures.create_student(officer, api, class_year=2)

    high = _submitted_similarity_report(api, world, 45.00, constants.SHA256_A)
    low = _submitted_similarity_report(
        api, world, 44.99, constants.SHA256_C, student=other_student
    )

    assertions.assert_pct_equals(
        low["evidence_strength_score"], 51.99, "44.99 score"
    )
    assert low["evidence_strength_score"] != 59.99, (
        "59.99 picks the 1.20 band from the raw 44.99 and applies it to the "
        "adjusted 39.99"
    )
    assert low["evidence_strength_score"] != 65.99, (
        "65.99 skips the 5.00 excluded-quote allowance entirely"
    )
    assertions.assert_pct_equals(high["evidence_strength_score"], 60.00, "45.00 score")

    # An 8.01-point gap from a 0.01-point difference in the input.
    gap = Decimal(str(high["evidence_strength_score"])) - Decimal(
        str(low["evidence_strength_score"])
    )
    assert gap == Decimal("8.01"), f"expected an 8.01 gap, got {gap}"

    # Nothing else differs between the two reports, and both clear triage.
    for label, row in (("45.00", high), ("44.99", low)):
        stored = validate_success(api.get_report(row["id"], officer))
        assertions.assert_two_decimals(
            stored["evidence_strength_score"], f"{label} stored score"
        )
        assert stored["status"] == "SUBMITTED"
        assert stored["evidence_complete"] is True
        assert (
            stored["evidence_strength_score"]
            >= constants.THRESHOLDS["TRIAGE_ACCEPT_MIN_EVIDENCE_SCORE"]
        )


# ---------------------------------------------------------------------------
# boundary_precision_check — three simultaneous strict edges (PRD §3.1)
# ---------------------------------------------------------------------------

_EXACTLY_730_DAYS_OLD = "2024-08-01T00:00:00Z"
_EXACTLY_731_DAYS_OLD = "2024-07-31T00:00:00Z"


def _oversight_world(api, officer, dean, registrar):
    """Exactly TWO departments, so the peer median is an even-count median.

    ENGL: census 2000 enrolled / 5 headcount, four faculty rows of which three
    completed training recently and the fourth completed exactly 730 days before
    the clock, plus three SUBMITTED reports.  HIST: census 1000 / 4, two recent
    completions and two at 731 days, and no reports at all.
    """
    world = _seed_actors(api, officer, dean, registrar)
    engl_id = world["dept"]["id"]

    # Three more ENGL members: two comfortably current, one exactly on the edge.
    fixtures.create_faculty(
        engl_id,
        trained=True,
        completed_at="2026-02-01T00:00:00Z",
        headers=officer,
        client=api,
    )
    fixtures.create_faculty(
        engl_id,
        trained=True,
        completed_at="2026-03-01T00:00:00Z",
        headers=officer,
        client=api,
    )
    world["engl_edge"] = fixtures.create_faculty(
        engl_id,
        trained=True,
        completed_at=_EXACTLY_730_DAYS_OLD,
        headers=officer,
        client=api,
    )

    world["hist"] = fixtures.create_department(
        officer, api, **constants.TEST_DEFAULTS["DEPT_HIST"]
    )
    hist_id = world["hist"]["id"]
    for completed_at in ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"):
        fixtures.create_faculty(
            hist_id,
            trained=True,
            completed_at=completed_at,
            headers=officer,
            client=api,
        )
    world["hist_lapsed"] = [
        fixtures.create_faculty(
            hist_id,
            trained=True,
            completed_at=_EXACTLY_731_DAYS_OLD,
            headers=officer,
            client=api,
        )
        for _ in range(2)
    ]

    # Three ENGL reports, each SUBMITTED at the clock, against three students.
    subjects = [
        world["student"],
        fixtures.create_student(officer, api, class_year=2),
        fixtures.create_student(officer, api, class_year=4),
    ]
    digests = (constants.SHA256_A, constants.SHA256_C, constants.SHA256_D)
    world["engl_reports"] = [
        _submitted_similarity_report(api, world, 45.00, digest, student=subject)
        for subject, digest in zip(subjects, digests)
    ]
    return world


def test_engl_at_the_exact_peer_threshold_and_the_exact_training_floor_is_normal(
    api, officer, dean, registrar
):
    """Rate == threshold and training == floor: both strict tests must not fire.

    PRD §3.1: "branch two selects `ELEVATED` when the rate is strictly greater
    than twice the peer median rounded to two decimals; branch three selects
    `TRAINING_DEFICIT` when `training_completion_pct` is strictly less than
    80.00".  The worked example is exactly this world: "With only two
    departments at 0.00 and 1.50 the median is 0.75 and the threshold is 1.50,
    so the department at 1.50 is `NORMAL` — the comparison is strict at the
    exact boundary."  The rate is 3 x 1000 / 2000 = 1.50 and the training
    percentage is 4 x 100 / 5 = 80.00, because "a completion exactly 730 days
    old still counts as current" — §3.1's own example, "five headcount with four
    current members gives 80.00".

    Design: Difficulty/boundary_precision_check/monitoring_flag_strict_inequalities_at_the_peer_threshold_and_the_training_floor
    """
    world = _oversight_world(api, officer, dean, registrar)

    metrics = validate_success(
        api.get_department_reporting_metrics(world["dept"]["id"], officer)
    )
    assert metrics["department_id"] == world["dept"]["id"]
    assert metrics["basis"] == "SUBMITTED"
    assertions.assert_instant_equals(metrics["as_of"], fixtures.CLOCK_T0, "as_of")
    assert metrics["window_days"] == 365

    # The rate: three submitted reports over a 2000-student census.
    assert metrics["numerator"] == 3
    assert metrics["enrolled_student_count"] == 2000
    assertions.assert_pct_equals(metrics["reporting_rate_per_1k"], 1.50, "ENGL rate")

    # The even-count median of {0.00, 1.50} and twice it.
    assertions.assert_pct_equals(metrics["peer_median_rate"], 0.75, "peer median")
    assert metrics["peer_median_rate"] != 1.50
    assert metrics["peer_median_rate"] != 0.00
    assertions.assert_pct_equals(
        metrics["elevated_threshold_rate"], 1.50, "elevated threshold"
    )

    # The training floor, hit exactly, with the 730-day member still counted.
    assert metrics["faculty_current_count"] == 4
    assert metrics["faculty_headcount"] == 5
    assertions.assert_pct_equals(
        metrics["training_completion_pct"], 80.00, "ENGL training pct"
    )
    edge = validate_success(api.get_faculty_member(world["engl_edge"]["id"], officer))
    assert edge["training_status"] == "CURRENT", "exactly 730 days is still current"
    assertions.assert_instant_equals(
        edge["training_completed_at"], _EXACTLY_730_DAYS_OLD, "edge completed_at"
    )

    # Neither strict comparison fires, so branch four wins.
    assert metrics["monitoring_flag"] == "NORMAL"
    assert metrics["monitoring_flag"] != "ELEVATED"
    assert metrics["monitoring_flag"] != "TRAINING_DEFICIT"

    # The SUBMITTED basis persists what it computed (PRD §3.1).
    stored = validate_success(api.get_department(world["dept"]["id"], officer))
    assertions.assert_pct_equals(
        stored["reporting_rate_per_1k_submitted"], 1.50, "stored ENGL rate"
    )
    assertions.assert_pct_equals(
        stored["training_completion_pct"], 80.00, "stored ENGL training pct"
    )
    assert stored["monitoring_flag"] == "NORMAL"


def test_hist_zero_rate_wins_over_its_training_deficit_and_the_731_day_members_lapse(
    api, officer, dean, registrar
):
    """A department satisfying branches one and three must report branch one.

    PRD §3.1: "`monitoring_flag` is chosen by evaluating four branches in a
    pinned order, first match winning; a department can satisfy several branches
    at once, and evaluating them in another order yields a different flag ...
    branch one selects `UNDER_REPORTING` when this department's rate equals
    exactly 0.00 ... branch three selects `TRAINING_DEFICIT` when
    `training_completion_pct` is strictly less than 80.00."  HIST satisfies both
    — 0.00 and 50.00 — and §3.1's example settles the tie in favour of branch
    one: "the department at 0.00 is `UNDER_REPORTING` even though its 50.00
    training percentage would also satisfy branch three."  The 50.00 comes from
    §3.1's other worked figure, "four headcount with two current members gives
    50.00", because "a completion exactly 730 days old still counts as current,
    while one 731 days old does not".

    Design: Difficulty/boundary_precision_check/monitoring_flag_strict_inequalities_at_the_peer_threshold_and_the_training_floor
    """
    world = _oversight_world(api, officer, dean, registrar)

    metrics = validate_success(
        api.get_department_reporting_metrics(world["hist"]["id"], officer)
    )
    assert metrics["numerator"] == 0
    assert metrics["enrolled_student_count"] == 1000
    assertions.assert_pct_equals(metrics["reporting_rate_per_1k"], 0.00, "HIST rate")
    assert metrics["faculty_current_count"] == 2
    assert metrics["faculty_headcount"] == 4
    assertions.assert_pct_equals(
        metrics["training_completion_pct"], 50.00, "HIST training pct"
    )

    # Branch one wins although branch three is also satisfied.
    assert metrics["monitoring_flag"] == "UNDER_REPORTING"
    assert metrics["monitoring_flag"] != "TRAINING_DEFICIT"
    assert metrics["monitoring_flag"] != "NORMAL"

    # The 731-day completions are the reason the count is 2 and not 4.
    for member in world["hist_lapsed"]:
        stored_member = validate_success(api.get_faculty_member(member["id"], officer))
        assert stored_member["training_status"] == "LAPSED", "731 days is not current"
        assertions.assert_instant_equals(
            stored_member["training_completed_at"],
            _EXACTLY_731_DAYS_OLD,
            "lapsed completed_at",
        )
    edge = validate_success(api.get_faculty_member(world["engl_edge"]["id"], officer))
    assert edge["training_status"] == "CURRENT"

    # One day of input difference, two different derived statuses.
    assert (
        validate_success(api.get_department(world["hist"]["id"], officer))[
            "monitoring_flag"
        ]
        == "UNDER_REPORTING"
    )
