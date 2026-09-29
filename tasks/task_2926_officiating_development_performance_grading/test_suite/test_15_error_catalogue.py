"""The error catalogue as a surface: every not-found code reachable, the declared
order in which body identifiers are resolved, and the state and staffing guards that
no happy path ever reaches.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.constants import UNKNOWN_ID


# ─── Eleven not-found codes ────────────────────────────

@pytest.fixture
def open_program_and_an_unknown_id():
    """An OPEN program, so a body reference check is not short-circuited by the
    program write gate."""
    return fx.create_open_program()


def test_every_addressed_read_of_an_unknown_id_names_its_own_code(
    open_program_and_an_unknown_id,
):
    """Each single read of the never-minted identifier returns that resource kind's
    own 404 code inside the standard error envelope.

    PRD §2.9: "Every identifier resolves to a live row — path identifiers first, in
    left-to-right path order, then body identifiers in the order the endpoint declares
    its inputs. The first unresolved identifier determines which of the not-found
    errors is returned (`ERR_SEASON_PROGRAM_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_PLAY_GRADE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_REPLAY_STATION_NOT_FOUND`, `ERR_REPLAY_REVIEW_NOT_FOUND`,
    `ERR_POOL_REPORT_NOT_FOUND`, `ERR_DISCIPLINE_ACTION_NOT_FOUND`), all at HTTP
    404."

    Design: Corner/errors/every_not_found_error_is_triggerable_with_an_unknown_id
    """
    reads = [
        (api_client.get_season_program(UNKNOWN_ID, fx.DIRECTOR),
         "ERR_SEASON_PROGRAM_NOT_FOUND"),
        (api_client.get_official(UNKNOWN_ID, fx.DIRECTOR), "ERR_OFFICIAL_NOT_FOUND"),
        (api_client.get_advancement_application(UNKNOWN_ID, fx.EVALUATOR),
         "ERR_APPLICATION_NOT_FOUND"),
        (api_client.get_game(UNKNOWN_ID, fx.DIRECTOR), "ERR_GAME_NOT_FOUND"),
        (api_client.get_crew_assignment(UNKNOWN_ID, fx.SCHEDULER),
         "ERR_ASSIGNMENT_NOT_FOUND"),
        (api_client.get_play_grade(UNKNOWN_ID, fx.GRADER), "ERR_PLAY_GRADE_NOT_FOUND"),
        (api_client.get_grade_appeal(UNKNOWN_ID, fx.GRADER), "ERR_APPEAL_NOT_FOUND"),
        (api_client.get_replay_station(UNKNOWN_ID, fx.REPLAY),
         "ERR_REPLAY_STATION_NOT_FOUND"),
        (api_client.get_replay_review(UNKNOWN_ID, fx.REPLAY),
         "ERR_REPLAY_REVIEW_NOT_FOUND"),
        (api_client.get_pool_report(UNKNOWN_ID, fx.COMMUNICATIONS),
         "ERR_POOL_REPORT_NOT_FOUND"),
        (api_client.get_discipline_action(UNKNOWN_ID, fx.DIRECTOR),
         "ERR_DISCIPLINE_ACTION_NOT_FOUND"),
    ]

    for response, expected_error_id in reads:
        validate_error(response, expected_error_id, 404)
        assert response.json()["meta"]["api_request_id"].startswith("req_")


def test_an_unresolvable_body_reference_reports_the_same_code(
    open_program_and_an_unknown_id,
):
    """A registration naming a program that does not exist reports the program's
    not-found code, exactly as an unresolvable path identifier would.

    PRD §2.9: "When a single request violates more than one rule, the response is
    determined by the violated rule that stands highest in the following precedence
    order, and no lower rule is evaluated."

    Design: Corner/errors/every_not_found_error_is_triggerable_with_an_unknown_id
    """
    validate_error(
        api_client.create_official(
            f.official_payload(
                UNKNOWN_ID,
                full_name="Orphan",
                position="UMPIRE",
                seasons_experience=2,
                home_market_code="PHI",
            ),
            fx.DIRECTOR,
        ),
        "ERR_SEASON_PROGRAM_NOT_FOUND",
        404,
    )


# ─── Body identifiers resolve in declared order ────────

@pytest.fixture
def a_real_game_and_a_real_official():
    """A one-slot program with a SCHEDULED game and a cleared umpire, so each bad
    identifier can be isolated against a good one."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    return {
        "program": program,
        "official": official,
        "game": fx.schedule_game(program["id"]),
    }


def test_the_first_unresolvable_body_identifier_in_order_decides(
    a_real_game_and_a_real_official,
):
    """With both references bad the proposal reports the game, and with only the
    official bad it reports the official — so the order is being walked rather than a
    single code hardcoded.

    PRD §2.11: "The same left-to-right discipline governs body identifiers once the
    path has resolved, in the order the endpoint declares them."

    Design: Corner/errors/body_ids_are_resolved_in_the_declared_input_order
    """
    game = a_real_game_and_a_real_official["game"]

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                UNKNOWN_ID, UNKNOWN_ID, "UMPIRE", game["version"]
            ),
            fx.SCHEDULER,
        ),
        "ERR_GAME_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game["id"], UNKNOWN_ID, "UMPIRE", game["version"]
            ),
            fx.SCHEDULER,
        ),
        "ERR_OFFICIAL_NOT_FOUND",
        404,
    )


def test_the_same_order_holds_on_a_report_and_shape_outranks_existence(
    a_real_game_and_a_real_official,
):
    """A pool report naming two dead references reports the game as well, while a
    proposal whose position is not a declared value is malformed even though its game
    is also unresolvable.

    PRD §2.9: "The request body is well-formed: every required input field is present,
    no unknown field is honored, every enum-valued field carries a declared value,
    every score lies within the inclusive range 0.00 through 100.00, every timestamp
    parses as an ISO 8601 UTC instant, integers are non-negative, and a `MODIFIED`
    appeal decision carries a `revised_grade_code` that differs from the grade's
    current `grade_code`."

    Design: Corner/errors/body_ids_are_resolved_in_the_declared_input_order
    """
    validate_error(
        api_client.create_pool_report(
            f.pool_report_payload(
                UNKNOWN_ID, UNKNOWN_ID, body="Nothing resolves here."
            ),
            fx.COMMUNICATIONS,
        ),
        "ERR_GAME_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                UNKNOWN_ID,
                a_real_game_and_a_real_official["official"]["id"],
                "NOT_A_POSITION",
                a_real_game_and_a_real_official["game"]["version"],
            ),
            fx.SCHEDULER,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )


# ─── The guards no happy path reaches ──────────────────

def test_kickoff_is_refused_while_the_crew_is_only_proposed(
    a_real_game_and_a_real_official,
):
    """Kickoff is refused on a game with no crew at all, and refused again once a
    proposal exists, because posture counts confirmed rows only.

    PRD §2.9: "The game's crew posture is `STAFFED` at kickoff, else
    `ERR_CREW_NOT_STAFFED` (409)."

    Design: Corner/errors/residual_state_and_staffing_guards_are_each_triggerable
    """
    game = a_real_game_and_a_real_official["game"]

    validate_error(
        api_client.kickoff_game(game["id"], fx.DIRECTOR), "ERR_CREW_NOT_STAFFED", 409
    )

    fx.propose_assignment(
        game["id"],
        a_real_game_and_a_real_official["official"]["id"],
        "UMPIRE",
        expected_game_version=game["version"],
    )

    validate_error(
        api_client.kickoff_game(game["id"], fx.DIRECTOR), "ERR_CREW_NOT_STAFFED", 409
    )

    after = fx.read_game(game["id"])

    assert after["status"] == "SCHEDULED"
    assert after["confirmed_crew_count"] == 0
    assert after["crew_posture"] == "UNDERSTAFFED"


def test_a_second_publish_is_refused_on_an_already_published_report():
    """The first publish succeeds against a finalized grade; the second is refused
    because `PUBLISHED` no longer declares the transition.

    PRD §3.9: "Publication is legal only from `DRAFT` — a second attempt is refused
    with `ERR_REPORT_STATE_INVALID` — and only when the cited play grade has
    `grade_status` `FINAL` and an `appeal_state` that is not `APPEAL_PENDING`;
    otherwise the department would be commenting publicly on a call still under
    challenge, and the request is refused with `ERR_CITED_GRADE_NOT_FINAL`."

    Design: Corner/errors/residual_state_and_staffing_guards_are_each_triggerable
    """
    ctx = fx.posted_grade_for_appeal()
    fx.finalize_game(ctx["game"]["id"])
    report = fx.draft_pool_report(ctx["game"]["id"], ctx["grade"]["id"])

    published = fx.publish_pool_report(report["id"])

    assert published["status"] == "PUBLISHED"

    validate_error(
        api_client.publish_pool_report(report["id"], fx.COMMUNICATIONS),
        "ERR_REPORT_STATE_INVALID",
        409,
    )

    assert fx.read_pool_report(report["id"])["status"] == "PUBLISHED"


def test_remediation_on_a_cleared_action_is_refused():
    """A warning resolved as cleared is terminal, so assigning a remediation plan to
    it is refused and its cycle count stays at zero.

    PRD §3.8: "`CLEARED`, `ESCALATED` and `SUPERSEDED` are all terminal for a
    discipline action."

    Design: Corner/errors/residual_state_and_staffing_guards_are_each_triggerable
    """
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    action = fx.open_discipline(official["id"], "ATTENDANCE", "WARNING")

    resolved = fx.resolve_discipline(action["id"], "CLEARED", note="resolved on review")

    assert resolved["status"] == "CLEARED"

    validate_error(
        api_client.assign_remediation(
            action["id"],
            f.remediation_payload("too late, the action is closed"),
            fx.DIRECTOR,
        ),
        "ERR_DISCIPLINE_STATE_INVALID",
        409,
    )

    after = validate_success(
        api_client.get_discipline_action(action["id"], fx.DIRECTOR), 200
    )

    assert after["status"] == "CLEARED"
    assert after["remediation_cycle_count"] == 0
