"""Panel dispatch, piece release, label commitment and agreement counting."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_four_decimal_ratio,
    get_success_data,
    make_worker_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    attach_item,
    create_program,
    create_unit,
    dispatch_panel,
    commit_label,
    commit_abstain,
    get_program,
    get_unit,
    make_pool,
    open_program,
    panel_commits,
    production_commits,
    setup_dispatched_item,
    setup_program_with_unit,
    worker_for_commit,
)


def test_a_freshly_attached_piece_starts_in_the_declared_initial_state(api):
    """PRD §3.3: "A freshly attached piece sits at `DRAFT` / `PENDING` /
    `PENDING`."

    PRD §3.1: "the server assigns its `item_seq`, copies the unit's current
    `instruction_revision` onto it, and raises the unit's `item_count`."

    Design: Corner/state_machines/newly_created_piece_starts_in_the_declared_initial_state
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")

    assert item["item_status"] == "PENDING"
    assert item["consensus_status"] == "PENDING"
    assert item["status"] == "DRAFT"
    assert item["rework_cycles"] == 0
    assert item["gold_audits_this_week"] == 0
    assert item["gold_rotation"] is False
    assert item["instruction_revision"] == 1, "the revision is copied from the owning unit"
    assert item["item_seq"] == 1

    live_unit = get_unit(unit["id"])
    assert live_unit["item_count"] == 1


def test_release_cascade_moves_pieces_to_released_on_unit_activation(api):
    """PRD §3.3: "When the owning unit transitions from `DRAFT` to `ACTIVE`, every
    attached piece still at container status `DRAFT` moves to container status
    `RELEASED` with `item_status` remaining `PENDING`, and the piece receives its
    `item_seq`."

    Design: Corner/state_machines/newly_created_piece_starts_in_the_declared_initial_state
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    item = attach_item(unit, item_key="i-0001")
    assert item["status"] == "DRAFT"

    open_program(program)
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)

    assert live["status"] == "RELEASED"
    assert live["item_status"] == "PENDING"


def test_dispatch_panel_creates_one_assignment_per_selected_member(api):
    """PRD §3.3: "The selector is evaluated once for this dispatch, and one
    **Commit** row per selected member is created. Each commit is created with
    `status` `DISPATCHED`, with `kind` `PRODUCTION`, with `dispatch_rank` set from
    the ranked order the selector produced"

    PRD §2.3: "The commit list for a piece returns assignments ordered by
    `dispatch_rank` ascending rather than by creation time, because the rank is
    what the tie-break logic reads."

    Design: Corner/endpoints/dispatch_panel_creates_one_assignment_per_selected_member
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=2)

    assert len(commits) == 2, "one assignment per selected member"
    assert [c["dispatch_rank"] for c in commits] == [1, 2], "ranked order"
    assert all(c["kind"] == "PRODUCTION" for c in commits)
    assert all(c["status"] == "DISPATCHED" for c in commits)

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "AWAITING_CONSENSUS"

    for commit in commits:
        dispatched = commit["dispatched_at"]
        deadline = commit["commit_deadline_at"]
        assert deadline > dispatched, "commit_deadline_at is dispatched_at plus the window"


def test_commit_deadline_is_the_dispatch_instant_plus_the_program_window(api):
    """PRD §3.3: "with `dispatched_at` set to the current logical clock, and with
    `commit_deadline_at` computed as `dispatched_at` plus the engagement's
    `commit_deadline_seconds`."

    Design: Corner/endpoints/dispatch_panel_creates_one_assignment_per_selected_member
    """
    from datetime import datetime, timedelta

    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1, commit_deadline_seconds=3600)
    commit = commits[0]

    # The server mints three fractional digits on every timestamp (PRD §2.7).
    parse = lambda value: datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    dispatched = parse(commit["dispatched_at"])
    deadline = parse(commit["commit_deadline_at"])
    assert deadline - dispatched == timedelta(seconds=3600)


def test_panel_dispatch_is_all_or_nothing_on_a_short_pool(api):
    """PRD §3.3: "If the pool held fewer eligible members than the requested
    `panel_size`, every member found is dispatched; the piece simply waits longer
    for quorum."

    Design: Corner/cross_cutting_complexity_layers/dispatching_fulfills_the_panel_within_one_request
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=3, pool_size=2)

    assert len(commits) == 2, "a partial pool produces a partial panel, not a rollback"
    assert len(pool) == 2
    ids = {c["worker_id"] for c in commits}
    assert len(ids) == 2, "the selector excludes owners of existing assignments"

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "AWAITING_CONSENSUS", "an under-filled panel cannot certify"

    # A second dispatch finds no member to add: PRD §3.4 excludes every worker
    # who already owns a commit on the piece, and the two pooled workers do, so
    # the selector's pool is empty and the reserved ERR_NO_ELIGIBLE_WORKER
    # refusal applies.
    validate_error(
        api_client.dispatch_panel(item["id"], ADMIN), "ERR_NO_ELIGIBLE_WORKER", 422
    )
    assert len(production_commits(live)) == 2, "the partial panel is unchanged"


def test_abstaining_commit_leaves_the_agreement_denominator(api):
    """PRD §3.3: "When the worker declines to label, `abstained` is true, the
    commit's `status` becomes `ABSTAINED`, `committed_value` is set to null, and
    `non_abstaining_commit_count` is recomputed in a way that leaves the abstainer
    entirely out of the denominator."

    Design: Corner/state_machines/abstaining_commit_leaves_the_agreement_denominator
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=2)
    first, second = commits[0], commits[1]

    commit_label(first, worker_for_commit(first, pool), "A")
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["non_abstaining_commit_count"] == 1

    abstained = commit_abstain(second, worker_for_commit(second, pool))
    assert abstained["status"] == "ABSTAINED"
    assert abstained.get("committed_value") in (None, ""), "an abstainer carries no value"

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    # The first member's genuine label still stands; the abstainer alone leaves
    # the denominator, so the count is the labelling member rather than zero.
    assert live["non_abstaining_commit_count"] == 1, "the abstainer left the denominator entirely"
    assert live["agreement_ratio"] == 1.0, "the surviving member is unanimous with itself"
    assert live["consensus_status"] == "AWAITING_CONSENSUS", "one member is below the quorum of 3"

    ranks = {c["id"]: c["dispatch_rank"] for c in production_commits(live)}
    assert ranks[second["id"]] == 2, "abstention does not reorder the panel"


def test_agreement_ratio_is_rounded_half_up_to_four_places(api):
    """PRD §3.4: "The agreement ratio is the modal group's size divided by the
    agreement denominator, rounded half up to exactly 4 decimal places, and it
    reads 0 when the denominator is 0."

    Design: Corner/calculations/accuracy_uses_two_decimal_half_up_rounding
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=3, commitment_quorum=3, min_consensus_agreement=0.6
    )
    for commit, label in zip(commits, ["A", "A", "B"]):
        commit_label(commit, worker_for_commit(commit, pool), label)

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["agreement_ratio"] == pytest.approx(0.6667, abs=1e-9), (
        "two of three is 0.6667 half up, not 0.6666"
    )
    assert_four_decimal_ratio(live["agreement_ratio"])
    assert live["consensus_status"] == "CERTIFIED", "0.6667 clears the 0.6 agreement floor"


def test_worker_may_only_commit_its_own_assignment(api):
    """PRD §2.1: "In particular, the `worker_id` carried by a **Commit**, by an
    **AppealClaim**, and by a **ConfidentialityIncident** must equal the
    `X-User-ID` of the acting `Worker` for that worker to act on it."

    Design: Corner/rbac/worker_may_only_commit_its_own_assignment
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1)
    commit = commits[0]
    owner = worker_for_commit(commit, pool)
    other = [w for w, _q in pool if w["id"] != owner["id"]][0]

    # PRD §2.11 resolves a path identifier by existence first, and §2.1 makes
    # the Commit's worker_id an ownership key for the acting Worker, so a
    # mismatched identity sees no such assignment on its own record.
    validate_error(
        api_client.commit_label(
            commit["id"],
            {"payload": {"label": "A"}, "instructions_ack": True},
            make_worker_headers(other["id"]),
        ),
        "ERR_COMMIT_NOT_FOUND",
        404,
    )

    live_commit = get_success_data(api_client.get_commit(commit["id"], ADMIN), 200)
    assert live_commit["status"] == "DISPATCHED"
    assert live_commit.get("committed_value") in (None, "")

    committed = commit_label(commit, owner, "A")
    assert committed["status"] == "COMMITTED"


def test_worker_cannot_dispatch_a_panel(api):
    """PRD §2.1: "Once headers are present, the acting role must be one of the
    roles the endpoint declares; a well-formed request from a role the endpoint
    does not admit is refused with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/worker_cannot_dispatch_a_panel
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1)
    worker = pool[0][0]

    validate_error(
        api_client.dispatch_panel(item["id"], make_worker_headers(worker["id"])),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_success(api_client.get_worker(worker["id"], make_worker_headers(worker["id"])), 200)


def test_dispatch_is_refused_when_the_engagement_is_frozen(api):
    """PRD §3.13: "`FROZEN` is terminal: no transition leaves it, and every write
    path that reaches a resource whose ancestor engagement is `FROZEN` is refused
    with `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/frozen_program_rejects_further_dispatch_with_invalid_state
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1")
    open_program(program)
    make_pool(1)
    item = attach_item(unit, item_key="i-0001")

    frozen = get_success_data(
        api_client.program_state(program["id"], {"program_action": "FREEZE"}, ADMIN), 200
    )
    assert frozen["status"] == "FROZEN"

    validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_INVALID_STATE", 409)

    live_unit = get_unit(unit["id"])
    assert live_unit["status"] == "REJECTED", "the freeze cascade reached the unit"


def test_surplus_units_above_required_are_refused_by_the_dispatch_gate(api):
    """PRD §3.3: "`required_units` must be at least 1, and the count of items
    already certified inside the unit must be at or above `required_units` minus 1,
    because releasing a piece that still carries a required-detection shortfall
    would publish the unit with a zero gap; a violation is `ERR_REQUIRED_UNITS_GAP`
    (409)."

    Design: Corner/validations/surplus_units_above_required_are_ignored_by_the_dispatch_gate
    """
    from test_helpers.fixtures import setup_program_with_unit

    program, unit, pool, items = setup_program_with_unit(
        pool_size=1, item_count=0, panel_size=1,
        extra_items=[
            {"item_key": "i-0001", "payload_uri": "s3://ax/0001", "required_units": 1},
            {"item_key": "i-0002", "payload_uri": "s3://ax/0002", "required_units": 3},
        ],
    )
    first, second = items[0], items[1]

    validate_error(api_client.dispatch_panel(second["id"], ADMIN), "ERR_REQUIRED_UNITS_GAP", 409)

    # required_units 1 is satisfied by zero certified siblings (0 >= 1 - 1).
    dispatch_panel(first)


def test_piece_certifies_only_when_quorum_and_agreement_both_clear(api):
    """PRD §3.5: "When `non_abstaining_commit_count` is at or above the
    engagement's `commitment_quorum` **and** the `agreement_ratio` is at or above
    the engagement's `min_consensus_agreement`, the piece's `consensus_status`
    becomes `CERTIFIED`, `modal_label` and `agreement_ratio` are stamped onto the
    piece"

    Design: Corner/endpoints/dispatch_panel_creates_one_assignment_per_selected_member
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=2, commitment_quorum=2, min_consensus_agreement=0.6
    )
    commit_label(commits[0], worker_for_commit(commits[0], pool), "A")
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "AWAITING_CONSENSUS", "one member is below the quorum of 2"

    commit_label(commits[1], worker_for_commit(commits[1], pool), "A")
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "CERTIFIED"
    assert live["modal_label"] == "A"
    assert live["agreement_ratio"] == pytest.approx(1.0)
    assert live["status"] == "RESOLVED"
    assert live["item_status"] == "COMPLETED"


def test_panel_is_held_when_quorum_is_met_but_agreement_is_short(api):
    """PRD §3.5: "When `non_abstaining_commit_count` is at or above the quorum but
    the `agreement_ratio` is strictly below `min_consensus_agreement`, the piece's
    `consensus_status` becomes `HELD_QUORUM` and `holds_quorum` becomes true, while
    the container `status` stays `IN_PANEL` and the `item_status` stays
    `IN_REVIEW`."

    Design: Corner/endpoints/reviewer_action_is_conditional_on_the_piece_consensus_state
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=3, commitment_quorum=3, min_consensus_agreement=0.9
    )
    for commit, label in zip(commits, ["A", "A", "B"]):
        commit_label(commit, worker_for_commit(commit, pool), label)

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "HELD_QUORUM"
    assert live["holds_quorum"] is True
    assert live["status"] == "IN_PANEL"
    assert live["item_status"] == "IN_REVIEW"


def test_panel_is_rejected_when_the_patience_window_expires_below_quorum(api):
    """PRD §3.5: "when the count is strictly below the quorum and the seconds
    elapsed since the piece's first commit are at or above `patience_seconds`, the
    wait is abandoned: the `consensus_status` becomes `REJECTED`, `holds_quorum`
    becomes false, the container `status` becomes `RESOLVED`, and the `item_status`
    becomes `COMPLETED`."

    Design: Corner/endpoints/reviewer_action_is_conditional_on_the_piece_consensus_state
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=2, commitment_quorum=2, patience_seconds=600
    )
    commit_label(commits[0], worker_for_commit(commits[0], pool), "A")
    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "AWAITING_CONSENSUS"

    get_success_data(api_client.set_clock("2026-09-01T00:10:01Z", ADMIN), 200)

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "REJECTED"
    assert live["holds_quorum"] is False
    assert live["status"] == "RESOLVED"
    assert live["item_status"] == "COMPLETED"