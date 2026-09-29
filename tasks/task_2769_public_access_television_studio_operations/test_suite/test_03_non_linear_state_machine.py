"""State machines that loop or fork rather than running as a straight pipeline."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    REVIEWER2_HEADERS,
    REVIEWER_HEADERS,
    USER_REVIEWER,
    USER_REVIEWER_2,
    make_producer_headers,
)


def _cleared_draft_program(client):
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    program = fx.setup_cleared_program(
        client,
        producer["id"],
        title="Neighborhood Notes",
        runtime_seconds=1800,
        is_live=False,
        required_crew_roles=[],
    )
    return producer, program


def _one_revision_round(client, program_id, producer_id, reviewer_headers, notes):
    fx.submit_program(client, program_id, producer_id)
    claimed = fx.claim_review(client, program_id, reviewer_headers)
    refused = fx.request_changes(
        client, program_id, reviewer_headers, finding_notes=notes
    )
    return claimed, refused


def test_review_cycle_releases_the_claim_so_a_second_reviewer_can_take_the_next_pass(client):
    """Each requested-changes decision hands the program back unclaimed.

    PRD 3.3: "A successful submission clears `reviewed_by_user_id` back to null,
    so that any reviewer may claim the next round, and increments the program's
    `version` by 1."

    PRD 3.3: "`UNDER_REVIEW → CHANGES_REQUESTED` raises `revision_round` by 1,
    records the supplied `finding_category` and `finding_notes`, and increments
    `version` by 1; the producer may now resubmit, which is the cycle
    `UNDER_REVIEW → CHANGES_REQUESTED → SUBMITTED → UNDER_REVIEW`."

    PRD 3.3: "A `ContentReviewer` first claims the program, moving `SUBMITTED →
    UNDER_REVIEW` and recording their own `X-User-ID` in `reviewed_by_user_id`."

    Design: Difficulty/non_linear_state_machine/program_review_cycle_loops_and_revision_limit_terminates_it
    """
    producer, program = _cleared_draft_program(client)

    claim1, after1 = _one_revision_round(
        client, program["id"], producer["id"], REVIEWER_HEADERS, "Audio levels clip in reel one"
    )
    assert claim1["reviewed_by_user_id"] == USER_REVIEWER
    assert claim1["review_status"] == "UNDER_REVIEW"
    assert after1["revision_round"] == 1
    assert after1["review_status"] == "CHANGES_REQUESTED"

    claim2, after2 = _one_revision_round(
        client, program["id"], producer["id"], REVIEWER2_HEADERS, "Slate missing"
    )
    assert claim2["reviewed_by_user_id"] == USER_REVIEWER_2
    assert after2["revision_round"] == 2

    _claim3, after3 = _one_revision_round(
        client, program["id"], producer["id"], REVIEWER_HEADERS, "Captions still absent"
    )
    assert after3["revision_round"] == 3


def test_fourth_submission_is_refused_once_the_revision_budget_is_spent(client):
    """The loop terminates on the revision limit, not on any state ordering.

    PRD 3.3: "And the revision budget must not be spent: at most two rounds of
    requested changes are tolerated, so a program whose `revision_round` has
    grown beyond 2 can no longer be resubmitted and the attempt is refused with
    `ERR_REVISION_LIMIT_EXCEEDED` (422) — after the third refusal the only
    remaining path is withdrawal."

    PRD 3.3: "**Two independent state dimensions live on one program row.**
    `review_status` tracks the editorial pipeline, and `clearance_status` tracks
    the legal paperwork."

    Design: Difficulty/non_linear_state_machine/program_review_cycle_loops_and_revision_limit_terminates_it
    """
    producer, program = _cleared_draft_program(client)
    for notes, headers in (
        ("Audio levels clip in reel one", REVIEWER_HEADERS),
        ("Slate missing", REVIEWER2_HEADERS),
        ("Captions still absent", REVIEWER_HEADERS),
    ):
        _one_revision_round(client, program["id"], producer["id"], headers, notes)

    response = client.submit_program(
        program["id"], {}, make_producer_headers(producer["id"])
    )

    a.error_of(response, e.ERR_REVISION_LIMIT_EXCEEDED, 422)
    stalled = fx.read_program(client, program["id"])
    assert stalled["review_status"] == "CHANGES_REQUESTED"
    assert stalled["clearance_status"] == "CLEARED"
    assert stalled["revision_round"] == 3


# ---------------------------------------------------------------------------
# Reservation fork and join
# ---------------------------------------------------------------------------
def _two_confirmed_reservations(client):
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    _r, first = fx.setup_confirmed_reservation(
        client, producer["id"], resource,
        start_at="2026-08-06T10:00:00Z", end_at="2026-08-06T12:00:00Z",
    )
    second = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-07T10:00:00Z", end_at="2026-08-07T12:00:00Z",
    )
    second = fx.confirm_reservation(client, second["id"])
    return producer, resource, first, second


def test_clean_return_fork_settles_immediately_and_refunds_the_whole_hold(client):
    """A return with no damage drives straight to SETTLED and creates no assessment.

    PRD 3.7: "**The clean branch** fires when `damage_observed` is false and
    drives `CHECKED_OUT → SETTLED` directly."

    PRD 3.7: "No damage assessment is created and no suspension point is
    applied."

    Design: Difficulty/non_linear_state_machine/reservation_fork_join_clean_branch_diverges_from_damage_branch
    """
    producer, _resource, first, _second = _two_confirmed_reservations(client)
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=25924)

    fx.set_clock(client, "2026-08-06T10:00:00Z")
    fx.checkout_reservation(client, first["id"], condition_notes="Clean at handover")
    fx.set_clock(client, "2026-08-06T11:00:00Z")
    settled = fx.return_clean(client, first["id"])

    assert settled["status"] == "SETTLED"
    a.assert_cents(settled["deposit_forfeited_cents"], 0, "deposit_forfeited_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    a.assert_cents(settled["late_fee_cents"], 0, "late_fee_cents")
    a.assert_settlement_identities(settled)
    assert fx.list_assessments_for(client, first["id"]) == []


def test_damage_return_fork_retains_the_hold_and_files_an_unassessed_review(client):
    """A return with damage parks the reservation in review with money still held.

    PRD 3.7: "This branch drives `CHECKED_OUT → DAMAGE_REVIEW`. Only the late
    fee is computed at this point; the deposit stays on hold, so the producer's
    `deposit_held_cents` is unchanged and the asset's `open_reservation_count` is
    unchanged as well, because a reservation under damage review still counts as
    open."

    PRD 3.7: "One damage assessment is created in `FILED` status, recording the
    `reservation_id`, the `severity`, the operator's raw `repair_estimate_cents`
    and the `damage_notes`, with `assessed_repair_cents` at 0,
    `suspension_points_assessed` at 0"

    Design: Difficulty/non_linear_state_machine/reservation_fork_join_clean_branch_diverges_from_damage_branch
    """
    producer, resource, first, second = _two_confirmed_reservations(client)
    fx.set_clock(client, "2026-08-06T10:00:00Z")
    fx.checkout_reservation(client, first["id"], condition_notes="Clean at handover")
    fx.set_clock(client, "2026-08-06T11:00:00Z")
    fx.return_clean(client, first["id"])

    fx.set_clock(client, "2026-08-07T10:00:00Z")
    fx.checkout_reservation(client, second["id"], condition_notes="Lens hood intact at handover")
    fx.set_clock(client, "2026-08-07T11:00:00Z")
    forked = fx.return_damaged(
        client, second["id"], "MINOR", 40000, damage_notes="Cracked lens hood"
    )

    assert forked["status"] == "DAMAGE_REVIEW"
    a.assert_cents(forked["deposit_hold_cents"], 12962, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12962)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1

    assessment = fx.list_assessments_for(client, second["id"])[0]
    assert assessment["status"] == "FILED"
    assert assessment["severity"] == "MINOR"
    a.assert_cents(assessment["repair_estimate_cents"], 40000, "repair_estimate_cents")
    a.assert_cents(assessment["assessed_repair_cents"], 0, "assessed_repair_cents")
    assert assessment["suspension_points_assessed"] == 0


def test_both_forks_rejoin_at_settled_when_the_assessment_is_finalized(client):
    """Finalization is the join point where the damage fork reaches SETTLED.

    PRD 3.7: "A filed assessment leaves `FILED` by exactly one of two routes,
    and the reservation's `DAMAGE_REVIEW → SETTLED` transition is the join point
    where both routes reconverge."

    PRD 3.7: "The producer's `deposit_held_cents` falls by the reservation's
    `deposit_hold_cents`, their `deposit_forfeited_total_cents` rises by the
    forfeited amount, and the asset's `open_reservation_count` falls by 1. The
    producer's `suspension_points` rises by `suspension_points_assessed`."

    Design: Difficulty/non_linear_state_machine/reservation_fork_join_clean_branch_diverges_from_damage_branch
    """
    producer, resource, first, second = _two_confirmed_reservations(client)
    fx.set_clock(client, "2026-08-06T10:00:00Z")
    fx.checkout_reservation(client, first["id"], condition_notes="Clean at handover")
    fx.set_clock(client, "2026-08-06T11:00:00Z")
    fx.return_clean(client, first["id"])
    fx.set_clock(client, "2026-08-07T10:00:00Z")
    fx.checkout_reservation(client, second["id"], condition_notes="Lens hood intact at handover")
    fx.set_clock(client, "2026-08-07T11:00:00Z")
    fx.return_damaged(client, second["id"], "MINOR", 40000, damage_notes="Cracked lens hood")
    assessment = fx.list_assessments_for(client, second["id"])[0]

    fx.finalize_assessment(client, assessment["id"])

    joined = fx.read_reservation(client, second["id"])
    assert joined["status"] == "SETTLED"
    a.assert_cents(joined["assessed_repair_cents"], 40000, "assessed_repair_cents")
    a.assert_cents(joined["deposit_forfeited_cents"], 12962, "deposit_forfeited_cents")
    a.assert_cents(joined["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    a.assert_cents(joined["uncovered_liability_cents"], 27038, "uncovered_liability_cents")
    a.assert_settlement_identities(joined)

    after = fx.read_producer(client, producer["id"])
    a.assert_producer_counters(after, held=0, forfeited_total=12962, suspension_points=1)
    assert after["status"] == "ACTIVE"
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 0
