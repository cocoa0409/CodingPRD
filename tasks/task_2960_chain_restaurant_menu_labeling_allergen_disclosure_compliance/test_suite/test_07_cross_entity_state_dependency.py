"""Two operations each blocked by the state of a row on another aggregate.

A board cannot go live while its brand's disclosure packet is still `DRAFT`, and
an escalation cannot land while a granted variance covers the cited
requirement. In both cases the identical call succeeds once the other row moves.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_CITATION_SHIELDED_BY_VARIANCE,
    ERR_NO_PUBLISHED_PACKET,
)
from test_helpers.assertions import (
    assert_board_state,
    assert_brand_counters,
    assert_date_only,
    assert_instant_equals,
    assert_money_cents,
    validate_unpaginated,
)
from test_helpers.constants import (
    ACTION_ESCALATED,
    ACTION_RESPONSE_SUBMITTED,
    ACTION_TYPE_ESCALATE,
    ACTION_TYPE_REQUEST_INFO,
    CHANNEL_IN_STORE_BINDER,
    CHANNEL_QR_HANDOUT,
    CITATION_SUCCINCT_STATEMENT_MISSING,
    CLOCK_EPOCH_COMPACT,
    COMPLIANCE_CURRENT,
    PACKET_DRAFT,
    PACKET_PUBLISHED,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    REQUIREMENT_SUCCINCT_STATEMENT,
    RESPONSE_VARIANCE_CITED,
    STATEMENT_STATE_EXTENDED,
    VARIANCE_EXPIRED,
    VARIANCE_GRANTED,
)
from test_helpers.factories import board_publish_payload, regulator_action_payload
from test_helpers.fixtures import (
    BoardBundle,
    Env,
    ItemBundle,
    certified_sandwich,
    draft_and_publish_packet,
    draft_packet,
    file_response,
    grant_variance,
    listed_board,
    open_citation,
    publish_packet,
    seed_registry,
    set_clock,
)

# The granted relief runs 2026-08-01 through 2026-08-31 inclusive; the sweep
# instant below is the first Saturday past its end.
GRANT_STARTS = "2026-08-01"
GRANT_ENDS = "2026-08-31"
CLOCK_PAST_THE_GRANT = "2026-09-05T00:00:00Z"


# ---------------------------------------------------------------------------
# A board waiting on a packet that has never been published
# ---------------------------------------------------------------------------
def _listed_board_behind_a_draft_packet(
    api: ApiClient,
) -> Tuple[Env, ItemBundle, Dict[str, Any], BoardBundle]:
    env = seed_registry(api)
    item = certified_sandwich(env)
    packet = draft_packet(
        env, written_info_channels=[CHANNEL_IN_STORE_BINDER, CHANNEL_QR_HANDOUT]
    )
    board = listed_board(env, item.item_id)
    return env, item, packet, board


def test_a_board_cannot_go_live_behind_an_unpublished_packet(api):
    """PRD §3.7: "The brand must hold a disclosure packet whose `status` is
    `PUBLISHED`, else `ERR_NO_PUBLISHED_PACKET` — which is precisely why a packet
    turning `STALE` locks a brand out of publishing new boards."

    Design: Difficulty/cross_entity_state_dependency/board_publication_gated_on_disclosure_packet_status
    """
    env, _item, packet, board = _listed_board_behind_a_draft_packet(api)

    assert env.read_packet(packet["id"])["status"] == PACKET_DRAFT
    assert_brand_counters(env.read_brand(), has_published_disclosure_packet=False)

    validate_error(
        env.api.publish_menu_board(
            board.board_id,
            board_publish_payload(effective_from=CLOCK_EPOCH_COMPACT),
            env.publisher,
        ),
        ERR_NO_PUBLISHED_PACKET,
        409,
    )

    refused = env.read_board(board.board_id)
    assert_board_state(refused, publication_status=PUBLICATION_DRAFT)
    assert refused["effective_from"] is None


def test_publishing_the_packet_stamps_it_and_flips_the_brand_flag(api):
    """PRD §3.5: "On success the packet moves from `DRAFT` to `PUBLISHED`,
    `published_at` is stamped from the logical clock,
    `Brand.has_published_disclosure_packet` becomes true". PRD §3.5:
    "`cross_contact_statement_required` is true when any component of any
    `APPROVED` recipe of any non-exempt item of the brand has a
    `cross_contact_risk` other than `NONE`."

    Design: Difficulty/cross_entity_state_dependency/board_publication_gated_on_disclosure_packet_status
    """
    env, _item, packet, _board = _listed_board_behind_a_draft_packet(api)

    publish_packet(env, packet["id"])

    live = env.read_packet(packet["id"])
    assert live["status"] == PACKET_PUBLISHED
    assert_instant_equals(live["published_at"], CLOCK_EPOCH_COMPACT, "published_at")
    assert live["covered_item_count"] == 1
    assert live["allergen_matrix_complete"] is True
    assert live["cross_contact_statement_required"] is False

    assert_brand_counters(env.read_brand(), has_published_disclosure_packet=True)


def test_the_same_publish_call_succeeds_once_the_packet_is_live(api):
    """PRD §3.7: "Publication moves `publication_status` from `DRAFT` to
    `PUBLISHED`, writes `effective_from` and `effective_to` from the request".
    "It does not touch `calorie_compliance_status`, which stays wherever it was."

    Design: Difficulty/cross_entity_state_dependency/board_publication_gated_on_disclosure_packet_status
    """
    env, _item, packet, board = _listed_board_behind_a_draft_packet(api)
    validate_error(
        env.api.publish_menu_board(
            board.board_id,
            board_publish_payload(effective_from=CLOCK_EPOCH_COMPACT),
            env.publisher,
        ),
        ERR_NO_PUBLISHED_PACKET,
        409,
    )

    publish_packet(env, packet["id"])

    live = validate_unpaginated(
        env.api.publish_menu_board(
            board.board_id,
            board_publish_payload(effective_from=CLOCK_EPOCH_COMPACT),
            env.publisher,
        )
    )
    assert live["publication_status"] == PUBLICATION_PUBLISHED

    reread = env.read_board(board.board_id)
    assert_instant_equals(
        reread["effective_from"], CLOCK_EPOCH_COMPACT, "effective_from"
    )
    assert reread["effective_to"] is None
    assert_board_state(
        reread,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_CURRENT,
    )


# ---------------------------------------------------------------------------
# A citation shielded by a grant for the requirement it names
# ---------------------------------------------------------------------------
def _citation_shielded_by_a_grant(
    api: ApiClient,
) -> Tuple[Env, Dict[str, Any], Dict[str, Any]]:
    """A SUCCINCT_STATEMENT_MISSING file at RESPONSE_SUBMITTED under a grant."""
    env = seed_registry(
        api,
        code="MA-EXT",
        name="Massachusetts",
        unit_label="MA-0001",
        unit_label_prefix="MA-B",
        required_succinct_statement_variant=STATEMENT_STATE_EXTENDED,
    )
    certified_sandwich(env)
    draft_and_publish_packet(env)
    variance = grant_variance(
        env,
        REQUIREMENT_SUCCINCT_STATEMENT,
        requested_start_date=GRANT_STARTS,
        requested_end_date=GRANT_ENDS,
    )
    action = open_citation(
        env,
        CITATION_SUCCINCT_STATEMENT_MISSING,
        inspection_note="Board carries federal wording only",
    )
    file_response(
        env,
        action["id"],
        RESPONSE_VARIANCE_CITED,
        response_note="Variance on file for SUCCINCT_STATEMENT",
    )
    _request_info(env, action["id"])
    file_response(
        env,
        action["id"],
        RESPONSE_VARIANCE_CITED,
        response_note="Docket MA-2026-0412 attached",
    )
    return env, variance, action


def _request_info(env: Env, action_id: str) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_REQUEST_INFO,
                action_note="Provide the variance docket number",
            ),
            env.regulator,
        )
    )


def _attempt_escalation(env: Env, action_id: str, note: str):
    return env.api.create_regulator_action(
        action_id,
        regulator_action_payload(action_type=ACTION_TYPE_ESCALATE, action_note=note),
        env.regulator,
    )


def test_a_grant_for_the_mapped_requirement_shields_the_citation(api):
    """PRD §3.9: "no variance request of the cited brand in the citing authority
    whose `status` is `GRANTED` and whose `requirement_code` maps to the file's
    `citation_code` may cover the logical clock's calendar date, else
    `ERR_CITATION_SHIELDED_BY_VARIANCE`." "`SUCCINCT_STATEMENT_MISSING` maps to
    `SUCCINCT_STATEMENT`".

    Design: Difficulty/cross_entity_state_dependency/escalation_gated_on_granted_variance_for_the_cited_requirement
    """
    env, variance, action = _citation_shielded_by_a_grant(api)

    granted = env.read_variance(variance["id"])
    assert granted["status"] == VARIANCE_GRANTED
    assert_date_only(granted["effective_start_date"], GRANT_STARTS)
    assert_date_only(granted["effective_end_date"], GRANT_ENDS)

    before = env.read_action(action["id"])
    assert before["info_round_count"] == 1
    assert before["response_count"] == 2

    validate_error(
        _attempt_escalation(env, action["id"], "Escalating despite the claimed variance"),
        ERR_CITATION_SHIELDED_BY_VARIANCE,
        409,
    )

    after = env.read_action(action["id"])
    assert after["status"] == ACTION_RESPONSE_SUBMITTED
    assert_brand_counters(
        env.read_brand(),
        open_enforcement_escalated_count=0,
        compliance_posture=POSTURE_COMPLIANT,
    )


def test_the_clock_sweep_expires_the_grant_and_reports_the_count(api):
    """PRD §3.7: "Every variance request whose `status` is `GRANTED` and whose
    `effective_end_date` falls before the calendar date of the new clock moves to
    `EXPIRED`, and stops shielding citations from the moment it does. The response
    reports the resulting `current_utc` along with `boards_marked_overdue` and
    `variances_expired`, the counts of rows the sweep moved in each population."

    Design: Difficulty/cross_entity_state_dependency/escalation_gated_on_granted_variance_for_the_cited_requirement
    """
    env, variance, _action = _citation_shielded_by_a_grant(api)

    sweep = set_clock(env.api, CLOCK_PAST_THE_GRANT)

    assert sweep["variances_expired"] == 1
    assert sweep["boards_marked_overdue"] == 0
    assert_instant_equals(sweep["current_utc"], CLOCK_PAST_THE_GRANT, "current_utc")
    assert env.read_variance(variance["id"])["status"] == VARIANCE_EXPIRED


def test_the_escalation_lands_once_the_shield_has_lifted(api):
    """PRD §3.8: "Both effects end the instant the clock pushes the grant to
    `EXPIRED`." PRD §3.9: "A successful escalation moves the file to `ESCALATED`,
    increments `Brand.open_enforcement_escalated_count` by 1, and recomputes
    `compliance_posture` to `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/escalation_gated_on_granted_variance_for_the_cited_requirement
    """
    env, _variance, action = _citation_shielded_by_a_grant(api)
    validate_error(
        _attempt_escalation(env, action["id"], "Escalating despite the claimed variance"),
        ERR_CITATION_SHIELDED_BY_VARIANCE,
        409,
    )

    set_clock(env.api, CLOCK_PAST_THE_GRANT)

    escalated = validate_unpaginated(
        _attempt_escalation(env, action["id"], "Variance lapsed on 2026-08-31")
    )
    assert escalated["status"] == ACTION_ESCALATED
    assert_money_cents(escalated["penalty_total_cents"], 0, "penalty_total_cents")

    assert_brand_counters(
        env.read_brand(),
        open_enforcement_escalated_count=1,
        compliance_posture=POSTURE_FROZEN,
    )
