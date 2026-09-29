"""Two slot-occupancy regimes with deliberately opposite interval semantics.

An insurance slot (PRD S3.5) is half-open and unbuffered, so zero-gap adjacency
is legal and a later start supersedes rather than collides.  A designation slot
(PRD S3.4) is closed at both ends and widened by a one-day buffer on each end
before comparison, so adjacency collides and there is no supersede path at all.
Each regime is probed on both sides of its own edge.
"""

from test_helpers import (
    ApiErrorId,
    REGISTRY_ADMIN,
    THREE_STATES,
    assert_designation,
    assert_insurance_filing,
    authority_version,
    cancel_filing,
    designate_states,
    designation_payload,
    file_insurance,
    filing_payload,
    list_designations,
    make_insurer_headers,
    read_authority,
    set_clock,
    setup_published_authority,
    validate_error,
    validate_paginated,
    validate_success,
)

T_PUBLISH_CANON = "2026-08-05T00:00:00.000Z"
SUPERSEDE_AT = "2026-08-10T00:00:00Z"
SUPERSEDE_AT_CANON = "2026-08-10T00:00:00.000Z"
CANCEL_AT = "2026-08-20T00:00:00Z"
CANCEL_AT_CANON = "2026-08-20T00:00:00.000Z"


def _published_authority_with_one_bipd_filing(api):
    """A PENDING authority whose single BIPD slot holds one ACTIVE filing."""
    env = setup_published_authority(api)
    env.filing = file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        env.authority["required_bipd_limit_cents"],
        filing_type="BIPD",
        effective_at="2026-08-05T00:00:00Z",
        policy_number="BIPD-1",
    )
    env.filing_id = env.filing["id"]
    env.authority = read_authority(api, env.authority_id)
    return env


def _file_bipd(api, env, *, effective_at, policy_number):
    """Post one BIPD filing under the current version guard, unvalidated."""
    return api.create_filing(
        filing_payload(
            env.authority_id,
            env.insurer_id,
            env.authority["required_bipd_limit_cents"],
            authority_version(api, env.authority_id),
            filing_type="BIPD",
            policy_number=policy_number,
            effective_at=effective_at,
        ),
        make_insurer_headers(env.insurer_id),
    )


# ---------------------------------------------------------------------------
# The insurance slot: half-open, unbuffered, supersede on a later start
# ---------------------------------------------------------------------------
def test_same_instant_filing_on_an_occupied_slot_is_rejected(api):
    """PRD S3.5: "When the new filing's `effective_at` is at or before the
    incumbent's `effective_at` — a back-dated or same-instant filing — the
    request is rejected with `ERR_FILING_INTERVAL_OVERLAP`."
    PRD S3.5: "Each `(authority_id, filing_type)` pair is a single coverage
    slot, and at most one `ACTIVE` filing may occupy a slot at a time."

    Design: Difficulty/resource_temporal_overlap/filing_slot_uses_half_open_intervals_and_permits_zero_gap_adjacency
    """
    env = _published_authority_with_one_bipd_filing(api)
    assert env.filing["effective_at"] == T_PUBLISH_CANON
    assert env.filing["status"] == "ACTIVE"

    response = _file_bipd(
        api, env, effective_at="2026-08-05T00:00:00Z", policy_number="BIPD-2"
    )
    validate_error(response, ApiErrorId.FILING_INTERVAL_OVERLAP)

    incumbent = validate_success(api.get_filing(env.filing_id, REGISTRY_ADMIN))
    assert incumbent["status"] == "ACTIVE", "the incumbent must be untouched"
    assert incumbent["cancellation_effective_at"] is None

    filings, meta = validate_paginated(
        api.list_filings(REGISTRY_ADMIN, authority_id=env.authority_id)
    )
    assert meta["total_count"] == 1, "the rejected filing must not be persisted"
    assert [row for row in filings if row["policy_number"] == "BIPD-2"] == []


def test_back_dated_filing_on_an_occupied_slot_is_rejected(api):
    """PRD S3.5: "When the new filing's `effective_at` is at or before the
    incumbent's `effective_at` — a back-dated or same-instant filing — the
    request is rejected with `ERR_FILING_INTERVAL_OVERLAP`."
    PRD S3.5: "the new filing overlaps the incumbent when the new `effective_at`
    falls strictly before the end of the incumbent's interval (treating a null
    end as infinitely far in the future)."

    Design: Difficulty/resource_temporal_overlap/filing_slot_uses_half_open_intervals_and_permits_zero_gap_adjacency
    """
    env = _published_authority_with_one_bipd_filing(api)

    response = _file_bipd(
        api, env, effective_at="2026-08-01T00:00:00Z", policy_number="BIPD-2"
    )
    validate_error(response, ApiErrorId.FILING_INTERVAL_OVERLAP)

    incumbent = validate_success(api.get_filing(env.filing_id, REGISTRY_ADMIN))
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["effective_at"] == T_PUBLISH_CANON
    assert incumbent["cancellation_effective_at"] is None
    assert incumbent["supersedes_filing_id"] is None


def test_later_starting_filing_supersedes_and_truncates_the_incumbent(api):
    """PRD S3.5: "When the new filing's `effective_at` is strictly after the
    incumbent's `effective_at`, the new filing **supersedes** the incumbent: the
    incumbent moves `ACTIVE → CANCELLED`, its `cancellation_effective_at` is
    rewritten to the new filing's `effective_at` so the two intervals meet
    exactly, and the new row's `supersedes_filing_id` records the incumbent's
    `id`."
    PRD S3.5: "A supersede that replaces coverage with an equal-or-higher limit
    starting at the same or a later instant leaves `insurance_status` unchanged,
    because the new filing covers the current logical time from its
    `effective_at` onward."

    Design: Difficulty/resource_temporal_overlap/filing_slot_uses_half_open_intervals_and_permits_zero_gap_adjacency
    """
    env = _published_authority_with_one_bipd_filing(api)

    set_clock(api, SUPERSEDE_AT)
    successor = validate_success(
        _file_bipd(api, env, effective_at=SUPERSEDE_AT, policy_number="BIPD-2"),
        expected_status=201,
    )
    assert_insurance_filing(successor)
    assert successor["status"] == "ACTIVE"
    assert successor["effective_at"] == SUPERSEDE_AT_CANON
    assert successor["cancellation_effective_at"] is None
    assert successor["supersedes_filing_id"] == env.filing_id

    incumbent = validate_success(api.get_filing(env.filing_id, REGISTRY_ADMIN))
    assert incumbent["status"] == "CANCELLED"
    assert incumbent["cancellation_effective_at"] == SUPERSEDE_AT_CANON, (
        "the truncated incumbent must meet its successor exactly"
    )

    after = read_authority(api, env.authority_id)
    assert after["insurance_status"] == "FILED"
    assert after["authority_status"] == "PENDING"


def test_zero_gap_successor_at_the_cancellation_instant_is_accepted(api):
    """PRD S3.5: "Insurance intervals are **half-open**: a filing covers instants
    from its `effective_at` inclusive up to, but not including, its
    `cancellation_effective_at`, with a null `cancellation_effective_at` meaning
    it never ends. Adjacency is therefore allowed, and there is no buffer — a new
    filing starting at exactly the incumbent's `cancellation_effective_at` does
    not collide."
    PRD S3.5: "`CANCELLED` filings are invisible to this comparison."
    PRD S3.5: "If the slot was empty, `supersedes_filing_id` stays null."
    PRD S3.5: "`LAPSED → FILED` when every required slot is again satisfied by an
    `ACTIVE` filing whose interval contains the current logical time — this is
    what closes the `FILED → LAPSED → FILED` cycle."

    Design: Difficulty/resource_temporal_overlap/filing_slot_uses_half_open_intervals_and_permits_zero_gap_adjacency
    """
    env = _published_authority_with_one_bipd_filing(api)
    assert env.authority["insurance_status"] == "FILED"

    set_clock(api, CANCEL_AT)
    cancelled = cancel_filing(api, env.insurer_id, env.filing_id, CANCEL_AT)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_effective_at"] == CANCEL_AT_CANON
    lapsed = read_authority(api, env.authority_id)
    assert lapsed["insurance_status"] == "LAPSED", (
        "the half-open interval excludes its own end instant, so coverage lapses"
    )

    env.authority = lapsed
    successor = validate_success(
        _file_bipd(api, env, effective_at=CANCEL_AT, policy_number="BIPD-2"),
        expected_status=201,
    )
    assert_insurance_filing(successor)
    assert successor["status"] == "ACTIVE", (
        "a filing starting exactly at the incumbent's cancellation instant is "
        "adjacent, not overlapping"
    )
    assert successor["effective_at"] == CANCEL_AT_CANON
    assert successor["supersedes_filing_id"] is None
    assert successor["meets_required_minimum"] is True

    after = read_authority(api, env.authority_id)
    assert after["insurance_status"] == "FILED"
    assert after["authority_status"] == "PENDING"


# ---------------------------------------------------------------------------
# The designation slot: closed, buffered by one day on each end, no supersede
# ---------------------------------------------------------------------------
INCUMBENT_FROM = "2026-08-05T00:00:00Z"
INCUMBENT_TO = "2026-08-31T00:00:00Z"
INCUMBENT_TO_CANON = "2026-08-31T00:00:00.000Z"
ADJACENT_FROM = "2026-09-01T00:00:00Z"
BEYOND_BUFFER_FROM = "2026-09-02T00:00:00Z"
BEYOND_BUFFER_FROM_CANON = "2026-09-02T00:00:00.000Z"


def _authority_with_closed_designations(api):
    """A PENDING authority whose three required states are designated
    for the closed window 2026-08-05 .. 2026-08-31."""
    env = setup_published_authority(api)
    # PRD S3.4: required_jurisdictions is the distinct union of the application's
    # requested_operating_states and the carrier's domicile_state, "sorted
    # ascending by state code" -- not the order the applicant listed them in.
    assert env.authority["required_jurisdictions"] == sorted(THREE_STATES)
    env.designations = designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=THREE_STATES,
        effective_from=INCUMBENT_FROM,
        effective_to=INCUMBENT_TO,
    )
    env.authority = read_authority(api, env.authority_id)
    return env


def _designate(api, env, *, effective_from, effective_to=None):
    """Post one designation request for all three states, unvalidated."""
    kwargs = {} if effective_to is None else {"effective_to": effective_to}
    return api.create_designations(
        env.authority_id,
        designation_payload(
            env.agent_id,
            state_codes=THREE_STATES,
            effective_from=effective_from,
            **kwargs,
        ),
        env.carrier_headers,
    )


def test_successor_designation_on_the_buffered_upper_edge_is_rejected(api):
    """PRD S3.4: "Designation intervals are **closed** at both ends and are
    expanded by a mandatory transition buffer of one day on each end before
    comparison, so adjacency is forbidden and even a one-day gap collides."
    PRD S3.4: "Concretely, for each existing `ACTIVE` designation on the same
    authority and the same state code — walked in `created_at` ascending order,
    with `REVOKED` rows ignored entirely — take that designation's
    `effective_from` minus one day as its low edge and its `effective_to` plus
    one day as its high edge (treating a null `effective_to` as extending
    forever); take the requested interval's own `effective_from` as its low edge
    and its `effective_to`, or forever when null, as its high edge. If the
    requested low edge is at or before the existing high edge **and** the
    requested high edge is at or after the existing low edge, the two intervals
    intersect and the whole request is rejected with
    `ERR_DESIGNATION_INTERVAL_CONFLICT`."
    PRD S3.4: "There is no supersede path here: unlike insurance, a colliding
    designation is refused outright."

    Design: Difficulty/resource_temporal_overlap/designation_slot_uses_closed_intervals_with_a_one_day_transition_buffer
    """
    env = _authority_with_closed_designations(api)

    response = _designate(api, env, effective_from=ADJACENT_FROM)
    validate_error(response, ApiErrorId.DESIGNATION_INTERVAL_CONFLICT)

    rows = list_designations(api, env.authority_id)
    assert len(rows) == 3, "a colliding request writes no row at all"
    for row in rows:
        assert_designation(row)
        assert row["status"] == "ACTIVE"
        assert row["effective_from"] == T_PUBLISH_CANON
        assert row["effective_to"] == INCUMBENT_TO_CANON, (
            "the incumbent interval must not be rewritten by a collision"
        )
        assert row["revoked_at"] is None


def test_predecessor_designation_on_the_buffered_lower_edge_is_rejected(api):
    """PRD S3.4: "Designation intervals are **closed** at both ends and are
    expanded by a mandatory transition buffer of one day on each end before
    comparison, so adjacency is forbidden and even a one-day gap collides."
    PRD S3.4: "If the requested low edge is at or before the existing high edge
    **and** the requested high edge is at or after the existing low edge, the
    two intervals intersect and the whole request is rejected with
    `ERR_DESIGNATION_INTERVAL_CONFLICT`."
    PRD S3.4: "The request is strictly all-or-nothing: if **any** requested state
    code fails either of the two checks below, no row at all is created."

    Design: Difficulty/resource_temporal_overlap/designation_slot_uses_closed_intervals_with_a_one_day_transition_buffer
    """
    env = _authority_with_closed_designations(api)

    response = _designate(
        api,
        env,
        effective_from="2026-07-20T00:00:00Z",
        effective_to="2026-08-04T00:00:00Z",
    )
    validate_error(response, ApiErrorId.DESIGNATION_INTERVAL_CONFLICT)

    rows = list_designations(api, env.authority_id)
    assert len(rows) == 3
    assert {row["effective_from"] for row in rows} == {T_PUBLISH_CANON}
    after = read_authority(api, env.authority_id)
    assert after["designated_state_count"] == 3
    assert after["designation_coverage_complete"] is True


def test_successor_designation_one_day_past_the_buffer_is_accepted(api):
    """PRD S3.4: "Concretely, for each existing `ACTIVE` designation on the same
    authority and the same state code — walked in `created_at` ascending order,
    with `REVOKED` rows ignored entirely — take that designation's
    `effective_from` minus one day as its low edge and its `effective_to` plus
    one day as its high edge (treating a null `effective_to` as extending
    forever); take the requested interval's own `effective_from` as its low edge
    and its `effective_to`, or forever when null, as its high edge. If the
    requested low edge is at or before the existing high edge **and** the
    requested high edge is at or after the existing low edge, the two intervals
    intersect and the whole request is rejected with
    `ERR_DESIGNATION_INTERVAL_CONFLICT`."
    PRD S3.4: "One `ProcessAgentDesignation` row is created per requested state
    code, each carrying the authority from the path, the single `state_code` it
    covers, the shared `effective_from` and `effective_to`, `status` `ACTIVE` and
    `revoked_at` null."
    PRD S3.4: "`effective_from` is the inclusive start of the designation's
    occupation of the `(authority_id, state_code)` slot; `effective_to` is the
    inclusive end, and null — its default — means open-ended."

    Design: Difficulty/resource_temporal_overlap/designation_slot_uses_closed_intervals_with_a_one_day_transition_buffer
    """
    env = _authority_with_closed_designations(api)

    created = validate_success(
        _designate(api, env, effective_from=BEYOND_BUFFER_FROM), expected_status=201
    )
    assert [row["state_code"] for row in created] == THREE_STATES, (
        "rows are created in the order the state_codes array lists them"
    )
    for row in created:
        assert_designation(row)
        assert row["authority_id"] == env.authority_id
        assert row["process_agent_id"] == env.agent_id
        assert row["status"] == "ACTIVE"
        assert row["effective_from"] == BEYOND_BUFFER_FROM_CANON, (
            "a start one day past the buffered high edge clears the conflict"
        )
        assert row["effective_to"] is None
        assert row["revoked_at"] is None

    rows = list_designations(api, env.authority_id)
    assert len(rows) == 6, "both windows coexist on the three slots"
    after = read_authority(api, env.authority_id)
    assert after["designated_state_count"] == 3
    assert after["designation_coverage_complete"] is True
