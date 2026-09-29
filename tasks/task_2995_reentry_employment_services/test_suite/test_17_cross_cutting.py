"""
Optimistic concurrency and derived state across entity boundaries.

The three version guards are each proved the same way: a version captured before an
unrelated write is refused with the parent's own stale code, the failed write leaves the
parent's version exactly where it was, and the retry with the refreshed number succeeds.
The remaining tests follow counters that only ever move through cascades.
"""

from test_helpers.api_errors import (
    ERR_STALE_GRANT_VERSION,
    ERR_STALE_JOB_OPENING_VERSION,
    ERR_STALE_PARTICIPANT_VERSION,
)
from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_opening_seat_identity,
    ids_of,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    CATEGORY_ID_FEE,
    CATEGORY_TRANSIT_PASS,
    DECISION_APPROVED,
    EMPLOYMENT_ACTIVE,
    EMPLOYMENT_SEPARATED,
    OFFER_RESPONSE_ACCEPTED,
    OPENING_FILLED,
    OPENING_OPEN,
    RECORD_DRUG_OFFENSE,
    RELEASE_PLAN_DRAFT,
    RELEASE_PLAN_NONE,
    SEPARATION_LAYOFF,
    STAGE_POST_RELEASE,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    participant_headers,
)

ID_FEE_LINE = "State ID replacement fee"
ID_FEE_JUSTIFICATION = "Replacement state identification"


def _opening_with_one_offer(api, build):
    """A two-seat opening carrying one outstanding offer, plus a second candidate."""
    grant = build.grant(
        authorized_cents=30000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    first = build.participant_released()
    build.case_authorized(first["id"], 480, 1020)
    placement = build.placement_offered(first["id"], opening["id"], grant["id"])
    second = build.participant_released(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    return grant, partnership, opening, first, placement, second


def test_a_stale_participant_version_on_a_release_plan_write_is_rejected(api, build):
    """
    The number the client is holding was invalidated by a write it never made — an
    assessment on the same row — so the plan revision is refused, nothing of the plan is
    stored, and the refusal itself does not advance the version it complained about.

    PRD section 2.6: "The first guard protects release-plan revisions. Storing a
    release-plan revision requires `expected_participant_version` matching the target
    participant's current `version`."

    PRD section 2.6: "If the supplied value differs from the parent's current `version`
    at the moment the write is evaluated, the write is refused with the parent-specific
    stale-version code and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/a_stale_participant_version_on_a_release_plan_write_is_rejected
    """
    participant = build.participant()
    stale_version = build.participant_version(participant["id"])
    assert stale_version == 1

    assessed = validate_unpaginated(
        api.record_assessment(participant["id"], f.assessment_payload(), CASE_MANAGER)
    )
    assert_int_field(assessed, "version", 2)

    refused = api.put_release_plan(
        participant["id"], f.release_plan_payload(stale_version), CASE_MANAGER
    )
    validate_error(refused, ERR_STALE_PARTICIPANT_VERSION, 412)

    untouched = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert_int_field(untouched, "version", 2)
    assert untouched["release_plan_status"] == RELEASE_PLAN_NONE
    assert untouched["housing_plan_type"] is None

    fresh_version = build.participant_version(participant["id"])
    assert fresh_version == 2

    stored = validate_unpaginated(
        api.put_release_plan(
            participant["id"], f.release_plan_payload(fresh_version), CASE_MANAGER
        )
    )
    assert stored["release_plan_status"] == RELEASE_PLAN_DRAFT
    assert_int_field(stored, "version", 3)


def test_a_stale_grant_version_on_support_request_create_is_rejected(api, build):
    """
    What invalidated this client's view of the grant was somebody else's approval moving
    the ledger, not a write to the grant itself, and the refusal has to fire even though
    the request it carries is otherwise fundable.

    PRD section 2.6: "The second guard protects supportive-services requests. Creating a
    support request requires `expected_grant_version` matching the target grant's current
    `version`. Every accepted create raises the grant's `open_request_count` and advances
    the grant's version, and every review moves `committed_cents`, so a mismatched
    version means the client chose which grant to charge from an outdated view of
    `available_cents` and `funding_posture`. The refusal is `ERR_STALE_GRANT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_grant_version_on_support_request_create_is_rejected
    """
    grant = build.grant(
        authorized_cents=100000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    mine = build.participant_zero_barrier_draft(record_categories=[RECORD_DRUG_OFFENSE])
    theirs = build.participant_zero_barrier_draft(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    stale_version = build.grant_version(grant["id"])

    other_request = build.support_request(
        theirs["id"],
        grant["id"],
        [f.line_item("Monthly transit pass", 4000)],
        category=CATEGORY_TRANSIT_PASS,
        justification="Commute to interviews for the second participant",
    )
    assert_money_cents(other_request, "total_charge_cents", 4000)
    validate_unpaginated(
        api.review_support_request(
            other_request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )

    refused = api.create_support_request(
        f.support_request_payload(
            mine["id"],
            grant["id"],
            stale_version,
            [f.line_item(ID_FEE_LINE, 3000)],
            category=CATEGORY_ID_FEE,
            justification=ID_FEE_JUSTIFICATION,
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_STALE_GRANT_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_support_requests(CASE_MANAGER, f.page_params(participant_id=mine["id"]))
    )
    assert meta["total_count"] == 0
    assert rows == []

    before = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(before, "committed_cents", 4000)
    assert_int_field(before, "open_request_count", 0)
    assert_ledger_identity(before)

    created = validate_unpaginated(
        api.create_support_request(
            f.support_request_payload(
                mine["id"],
                grant["id"],
                build.grant_version(grant["id"]),
                [f.line_item(ID_FEE_LINE, 3000)],
                category=CATEGORY_ID_FEE,
                justification=ID_FEE_JUSTIFICATION,
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_money_cents(created, "requested_cents", 3000)
    assert_money_cents(created, "admin_fee_cents", 0)
    assert_money_cents(created, "total_charge_cents", 3000)

    after = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_int_field(after, "open_request_count", 1)
    assert_money_cents(after, "committed_cents", 4000)
    assert_ledger_identity(after)


def test_a_stale_job_opening_version_on_placement_create_is_rejected(api, build):
    """
    Two case managers race for the last seat and the loser is holding a version from
    before the winner's placement existed. The concurrency band is reported ahead of every
    business gate on that opening, so the 412 wins even though this same call would also
    have been refused as a duplicate placement, and no seat is consumed.

    PRD section 2.6: "The third guard protects placements. Creating a placement requires
    `expected_job_opening_version` matching the target job opening's current `version`.
    Each accepted create raises `offered_count` and lowers `remaining_openings`, so a
    mismatched version means the client selected the opening believing more seats were
    free than actually are. The refusal is `ERR_STALE_JOB_OPENING_VERSION` (HTTP 412),
    and because concurrency sits at band seven it is reported ahead of every business gate
    on that opening."

    Design: Corner/cross_cutting_complexity_layers/a_stale_job_opening_version_on_placement_create_is_rejected
    """
    grant, _partnership, opening, _first, first_placement, second = (
        _opening_with_one_offer(api, build)
    )
    stale_version = build.opening_version(opening["id"])

    second_placement = build.placement_offered(
        second["id"], opening["id"], grant["id"]
    )
    version_before_refusal = build.opening_version(opening["id"])
    assert version_before_refusal != stale_version

    refused = api.create_placement(
        f.placement_payload(
            second["id"],
            opening["id"],
            stale_version,
            grant["id"],
            start_date="2026-08-04",
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_STALE_JOB_OPENING_VERSION, 412)

    untouched = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(untouched, "offered_count", 2)
    assert_int_field(untouched, "filled_count", 0)
    assert_int_field(untouched, "remaining_openings", 0)
    assert untouched["status"] == OPENING_FILLED
    assert_opening_seat_identity(untouched)
    assert_int_field(untouched, "version", version_before_refusal)

    rows, meta = validate_paginated(api.list_placements(CASE_MANAGER))
    assert meta["total_count"] == 2
    assert set(ids_of(rows)) == {first_placement["id"], second_placement["id"]}


def test_the_opening_version_increments_on_cascaded_writes_too(api, build):
    """
    Nobody ever writes to the opening directly, yet its version has to advance twice —
    once when a placement is created against it and once when that offer becomes a filled
    seat — and the employer row it never touches has to move too.

    PRD section 2.4: "`version` increments are not confined to writes a client aims
    directly at a row. A row mutated only as the downstream consequence of a cascade — a
    job opening whose seat counters shift because a placement was declined, a placement
    whose subsidy projection falls because a shift was cancelled, a grant whose ledger
    columns move because a request was voided — has both its `updated_at` refreshed and
    its `version` advanced exactly as if it had been written directly."

    PRD section 3.6: "On acceptance the opening's `offered_count` falls by one while
    `filled_count` rises by one, leaving `remaining_openings` unchanged; the partnership's
    `active_placement_count` rises by one"

    Design: Corner/cross_cutting_complexity_layers/the_opening_version_increments_on_cascaded_writes_too
    """
    grant = build.grant(
        authorized_cents=30000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_offered(participant["id"], opening["id"], grant["id"])

    after_offer = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(after_offer, "version", 2)
    assert_int_field(after_offer, "offered_count", 1)
    assert_int_field(after_offer, "filled_count", 0)

    accepted = validate_unpaginated(
        api.respond_to_offer(
            placement["id"],
            f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
            participant_headers(participant["id"]),
        )
    )
    assert accepted["employment_status"] == EMPLOYMENT_ACTIVE

    after_accept = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(after_accept, "version", 3)
    assert after_accept["version"] > after_offer["version"]
    assert_int_field(after_accept, "offered_count", 0)
    assert_int_field(after_accept, "filled_count", 1)
    assert_int_field(after_accept, "remaining_openings", 1)
    assert_opening_seat_identity(after_accept)

    employer = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert employer["version"] >= 2
    assert_int_field(employer, "active_placement_count", 1)


def test_the_partnership_placement_counter_reconciles_across_the_lifecycle(api, build):
    """
    The employer's live headcount is a cross-entity count, so it has to be right at all
    three snapshots and it has to come back to exactly zero: an outstanding offer is not
    yet a body on the floor, acceptance makes it one, and separation returns both the seat
    and the count without drifting.

    PRD section 2.9: "A third counter spans two entity types: an employer partnership's
    `active_placement_count` is the number of placements whose job opening belongs to that
    partnership and whose `employment_status` is `ACTIVE`. It rises when an offer is
    accepted and falls on separation, and it is the quantity the partnership's
    `max_concurrent_placements` ceiling is compared against."

    PRD section 3.7: "The opening's `filled_count` falls by one, raising
    `remaining_openings` and possibly flipping the opening `FILLED → OPEN`, and the
    employer partnership's `active_placement_count` falls by one."

    Design: Corner/cross_cutting_complexity_layers/the_partnership_placement_counter_reconciles_across_the_lifecycle
    """
    grant = build.grant(
        authorized_cents=30000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_offered(participant["id"], opening["id"], grant["id"])

    after_create = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(after_create, "active_placement_count", 0)

    validate_unpaginated(
        api.respond_to_offer(
            placement["id"],
            f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
            participant_headers(participant["id"]),
        )
    )
    after_accept = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(after_accept, "active_placement_count", 1)

    build.clock.set("2026-08-04T09:00:00.000Z")
    separated = validate_unpaginated(
        api.separate_placement(
            placement["id"],
            f.separation_payload(SEPARATION_LAYOFF, "2026-08-03"),
            EMPLOYER_LIAISON,
        )
    )
    assert separated["employment_status"] == EMPLOYMENT_SEPARATED
    assert separated["separation_reason"] == SEPARATION_LAYOFF
    assert separated["separation_date"] == "2026-08-03"

    after_separate = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(after_separate, "active_placement_count", 0)

    returned = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(returned, "offered_count", 0)
    assert_int_field(returned, "filled_count", 0)
    assert_int_field(returned, "remaining_openings", 2)
    assert returned["status"] == OPENING_OPEN
    assert_opening_seat_identity(returned)

    walked_back = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert walked_back["stage"] == STAGE_POST_RELEASE
