"""Writes on one entity that are gated by state living on another: an
assignment gated on the official's field readiness, a publication gated on the
cited grade's finality, and a kickoff gated on the whole crew.
"""
import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import INSTANT_G1_KICKOFF, INSTANT_G1_POSTGAME


# ─── An assignment needs a field-ready official ────────

@pytest.fixture
def exam_passed_but_no_physical():
    """Dan Ruiz has a passed rules exam and no physical test, so he is on the
    roster but not field-ready. The game is scheduled and uncrewed."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"], cleared=False)
    fx.add_training_record(official["id"], f.rules_exam_payload(84.00, "EX-U1"))
    game = fx.schedule_game(program["id"])
    return {"program": program, "official": official, "game": game}


def test_an_active_but_uncleared_official_cannot_be_crewed(
    exam_passed_but_no_physical,
):
    """The exam made him ACTIVE, but without a physical test he is un-cleared, and
    the proposal reports clearance rather than status.

    PRD §3.2: "An official who has passed the exam but not yet the physical test
    is therefore `ACTIVE` and still un-cleared, and any attempt to crew them is
    rejected with `ERR_PRESEASON_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/crew_assignment_creation_depends_on_official_preseason_clearance
    """
    official = fx.read_official(exam_passed_but_no_physical["official"]["id"])
    game = exam_passed_but_no_physical["game"]

    assert official["status"] == "ACTIVE"
    assert official["preseason_cleared"] is False

    response = api_client.create_crew_assignment(
        f.crew_assignment_payload(
            game["id"], official["id"], "UMPIRE", game["version"]
        ),
        fx.SCHEDULER,
    )
    error = validate_error(response, "ERR_PRESEASON_NOT_CLEARED", 409)

    assert error["error_id"] != "ERR_OFFICIAL_NOT_ACTIVE"


def test_the_refused_proposal_leaves_the_games_crew_and_version_alone(
    exam_passed_but_no_physical,
):
    """No crew member was added and the game's version never moved, so the next
    proposal may still pin the version it was created with.

    PRD §3.4: "The surviving new assignment is written with `status` `PROPOSED` and
    a null `released_at`, increments the proposed official's
    `open_assignment_count` by 1, triggers a recomputation of the game's projected
    crew strength, and bumps the game's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/crew_assignment_creation_depends_on_official_preseason_clearance
    """
    game = exam_passed_but_no_physical["game"]

    api_client.create_crew_assignment(
        f.crew_assignment_payload(
            game["id"],
            exam_passed_but_no_physical["official"]["id"],
            "UMPIRE",
            game["version"],
        ),
        fx.SCHEDULER,
    )
    after = fx.read_game(game["id"])

    assert after["confirmed_crew_count"] == 0
    assert after["version"] == game["version"]


# ─── A publication needs a final grade ─────────────────

@pytest.fixture
def draft_report_citing_a_posted_grade():
    """A played but unfinalized game, one posted missed call, and a draft pool
    report citing it."""
    ctx = fx.posted_grade_for_appeal()
    ctx["report"] = fx.draft_pool_report(
        ctx["game"]["id"],
        ctx["grade"]["id"],
        report_type="POOL_REPORT",
        body="The crew confirmed the missed holding call after the game.",
    )
    return ctx


def test_publication_is_refused_while_the_cited_grade_is_only_posted(
    draft_report_citing_a_posted_grade,
):
    """The report is a draft and its cited grade is still POSTED, so publishing is
    refused.

    PRD §3.9: "Publication is legal only from `DRAFT` — a second attempt is
    refused with `ERR_REPORT_STATE_INVALID` — and only when the cited play grade
    has `grade_status` `FINAL` and an `appeal_state` that is not
    `APPEAL_PENDING`; otherwise the department would be commenting publicly on a
    call still under challenge, and the request is refused with
    `ERR_CITED_GRADE_NOT_FINAL`."

    Design: Difficulty/cross_entity_state_dependency/pool_report_publication_depends_on_cited_grade_finality
    """
    report = draft_report_citing_a_posted_grade["report"]

    assert report["status"] == "DRAFT"

    response = api_client.publish_pool_report(report["id"], fx.COMMUNICATIONS)
    validate_error(response, "ERR_CITED_GRADE_NOT_FINAL", 409)

    grade = fx.read_grade(draft_report_citing_a_posted_grade["grade"]["id"])
    assert grade["grade_status"] == "POSTED"


def test_the_same_publication_succeeds_once_finalization_makes_the_grade_final(
    draft_report_citing_a_posted_grade,
):
    """Finalizing the game carries the cited grade to FINAL, and the identical
    publish call then succeeds and stamps the clock.

    PRD §3.9: "Publication moves the report `DRAFT → PUBLISHED` and stamps
    `published_at` from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/pool_report_publication_depends_on_cited_grade_finality
    """
    report = draft_report_citing_a_posted_grade["report"]
    api_client.publish_pool_report(report["id"], fx.COMMUNICATIONS)

    fx.finalize_game(draft_report_citing_a_posted_grade["game"]["id"])
    grade = fx.read_grade(draft_report_citing_a_posted_grade["grade"]["id"])
    published = fx.publish_pool_report(report["id"])

    assert grade["grade_status"] == "FINAL"
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(
        published["published_at"], INSTANT_G1_POSTGAME, "published_at"
    )


# ─── A kickoff needs the whole crew ────────────────────

@pytest.fixture
def half_confirmed_crew():
    """A crew of two with the referee confirmed and the umpire still merely
    proposed, at the kickoff instant."""
    ctx = fx.crew_game(confirm_umpire=False)
    fx.pin_clock(INSTANT_G1_KICKOFF)
    return ctx


def test_kickoff_is_refused_while_the_crew_is_short(half_confirmed_crew):
    """One confirmation out of the two the program requires leaves the posture
    UNDERSTAFFED, and the game stays scheduled.

    PRD §3.5: "Kickoff is an `OfficiatingDirector` action and is legal only from
    `SCHEDULED`, only while the program is `OPEN`, and only when the game's
    `crew_posture` is `STAFFED`; a short crew is refused with
    `ERR_CREW_NOT_STAFFED`."

    Design: Difficulty/cross_entity_state_dependency/game_kickoff_depends_on_aggregate_crew_confirmation
    """
    game_id = half_confirmed_crew["game"]["id"]
    before = fx.read_game(game_id)

    assert before["confirmed_crew_count"] == 1
    assert before["crew_posture"] == "UNDERSTAFFED"

    response = api_client.kickoff_game(game_id, fx.DIRECTOR)
    validate_error(response, "ERR_CREW_NOT_STAFFED", 409)

    assert fx.read_game(game_id)["status"] == "SCHEDULED"


def test_the_second_confirmation_staffs_the_crew_and_lets_the_game_start(
    half_confirmed_crew,
):
    """Confirming the umpire takes the count to two and the posture to STAFFED, so
    the same kickoff call succeeds, freezes posture at LOCKED and stores the
    projected index of 8.64.

    PRD §3.5: "Kickoff advances the game `SCHEDULED → IN_PROGRESS`, freezes
    `crew_posture` at `LOCKED`, recomputes `crew_strength_index` one last time with
    the `PROJECTED` variant and writes `crew_strength_variant` as `PROJECTED`, and
    bumps the game's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/game_kickoff_depends_on_aggregate_crew_confirmation
    """
    game_id = half_confirmed_crew["game"]["id"]
    api_client.kickoff_game(game_id, fx.DIRECTOR)

    fx.confirm_assignment(half_confirmed_crew["umpire_assignment"]["id"])
    staffed = fx.read_game(game_id)
    started = fx.kickoff(game_id)

    assert staffed["confirmed_crew_count"] == 2
    assert staffed["crew_posture"] == "STAFFED"
    assert started["status"] == "IN_PROGRESS"
    assert started["crew_posture"] == "LOCKED"
    assert started["crew_strength_index"] == 8.64
    assert started["crew_strength_variant"] == "PROJECTED"
