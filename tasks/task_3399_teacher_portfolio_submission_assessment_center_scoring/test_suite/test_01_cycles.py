"""Certification-cycle configuration, advancement rules, window geometry, and
the logical clock's startup default."""
from datetime import datetime

from test_helpers import (
    BOARD,
    CLOCK_STARTUP_DEFAULT_ISO,
    DEFAULT_MAX_ATTEMPTS_PER_COMPONENT,
    STANDARD_WORK_CLOCK,
    ApiErrorId,
    CycleStatus,
    assert_cycle,
    create_cycle_payload,
    create_open_cycle,
    cycle_component,
    cycle_transition_payload,
    set_logical_clock,
    validate_created,
    validate_error,
    validate_success,
)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant (Z-suffixed or offset) for clock comparisons."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_cycle_create_applies_defaults_and_starts_draft(api):
    """PRD §3.1: "`max_attempts_per_component` caps how many attempts (the original
    plus retakes) a candidate may make per component and defaults to 2 when omitted."
    PRD §3.1: "A cycle is born `DRAFT`."
    PRD §2.5: "`created_at` is fixed at creation while `updated_at` refreshes on
    every mutation."

    The created_at comparison parses instants: the PRD pins the instant stamped
    from the logical clock, not a particular fractional-digit rendering.

    Design: Corner/entities/cycle_create_applies_defaults_and_starts_draft
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    payload = create_cycle_payload(max_attempts_per_component=None)
    assert "max_attempts_per_component" not in payload, (
        "payload must omit max_attempts_per_component to exercise the server default"
    )

    cycle = validate_created(api.create_cycle(payload, BOARD))

    assert_cycle(cycle)
    assert cycle["max_attempts_per_component"] == DEFAULT_MAX_ATTEMPTS_PER_COMPONENT == 2
    assert cycle["status"] == CycleStatus.DRAFT.value
    assert _parse_iso(cycle["created_at"]) == _parse_iso(STANDARD_WORK_CLOCK)


def test_cycle_create_missing_required_code_returns_invalid_request(api):
    """PRD §3.1: "A `BoardAdministrator` opens a season by creating a certification
    cycle with a unique `code` (for example, NB-2027), a `components` array defining
    the instruments of the cycle, and the window fields `submission_window_open`,
    `submission_window_close`, and `retake_window_close`."
    PRD §2.8: "7. **Structural and numeric constraints** (400/409/422) — required
    fields, weight sums, component membership, score grids, attempt caps, capacity,
    and duplicate-active-resource guards."

    Design: Corner/entities/cycle_create_missing_required_code_returns_invalid_request
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    payload = create_cycle_payload()
    payload.pop("code")

    response = api.create_cycle(payload, BOARD)

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["message"].strip(), "error envelope must carry a non-empty message"


def test_cycle_create_weights_not_summing_to_one_rejected(api):
    """PRD §3.1: "Exactly one component of the cycle may be of `ASSESSMENT` kind,
    and the component weights must sum to exactly 1.000; violating either rule
    rejects the creation with `ERR_WEIGHT_SUM_INVALID` (HTTP 422)."

    Design: Corner/entities/cycle_create_weights_not_summing_to_one_rejected
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    payload = create_cycle_payload(
        components=[
            cycle_component("CKA", "ASSESSMENT", 0.50),
            cycle_component("P1", "PORTFOLIO", 0.20),
            cycle_component("P2", "PORTFOLIO", 0.20),
            cycle_component("P3", "PORTFOLIO", 0.20),
        ]
    )

    response = api.create_cycle(payload, BOARD)

    validate_error(response, ApiErrorId.ERR_WEIGHT_SUM_INVALID)


def test_cycle_scoring_skip_from_draft_rejected(api):
    """PRD §3.1: "A `BoardAdministrator` advances it by naming the desired target in
    a `to` field: `DRAFT` to `OPEN`, then `OPEN` to `SCORING`, then `SCORING` to
    `CLOSED`, which is terminal. Requesting any other move is rejected with
    `ERR_INVALID_CYCLE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/cycle_scoring_skip_from_draft_rejected
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    cycle = validate_created(api.create_cycle(create_cycle_payload(), BOARD))

    response = api.transition_cycle(cycle["id"], cycle_transition_payload("SCORING"), BOARD)

    validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_TRANSITION)
    reread = validate_success(api.get_cycle(cycle["id"], BOARD))
    assert reread["status"] == CycleStatus.DRAFT.value


def test_cycle_scoring_before_window_close_rejected(api):
    """PRD §3.1: "The advance out of `OPEN` additionally requires the logical clock
    to have reached `submission_window_close`; before that instant the request fails
    with `ERR_CYCLE_WINDOW_STILL_OPEN` (HTTP 422), and per §2.8 the state check is
    evaluated before the window check."

    The work clock 2027-01-10 precedes the standard window close 2027-03-01.

    Design: Corner/state_machines/cycle_scoring_before_window_close_rejected
    """
    cycle = create_open_cycle()

    response = api.transition_cycle(cycle["id"], cycle_transition_payload("SCORING"), BOARD)

    validate_error(response, ApiErrorId.ERR_CYCLE_WINDOW_STILL_OPEN)
    reread = validate_success(api.get_cycle(cycle["id"], BOARD))
    assert reread["status"] == CycleStatus.OPEN.value


def test_cycle_transition_missing_auth_header_returns_400(api):
    """PRD §2.1: "Both headers must be present and well-formed on every endpoint
    other than candidate self-registration; a missing or malformed header is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/cycle_transition_missing_auth_header_returns_400
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    cycle = validate_created(api.create_cycle(create_cycle_payload(), BOARD))

    response = api.transition_cycle(cycle["id"], cycle_transition_payload("OPEN"), {})

    validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_cycle_windows_adjacent_touch_is_allowed_not_overlap(api):
    """PRD §2.7: "The same half-open reading governs the window-overlap check
    between cycles, so two cycles whose windows merely touch at an endpoint do not
    overlap and are both allowed."

    The second cycle's open equals the first cycle's close: half-open adjacency.

    Design: Difficulty/resource_temporal_overlap/cycle_windows_half_open_adjacency_allowed
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    cycle_a = validate_created(api.create_cycle(create_cycle_payload(), BOARD))
    assert_cycle(cycle_a)

    # Default window is [2027-01-01, 2027-03-01); this cycle opens exactly at
    # the first cycle's close.
    cycle_b = validate_created(
        api.create_cycle(
            create_cycle_payload(
                submission_window_open="2027-03-01T00:00:00Z",
                submission_window_close="2027-05-01T00:00:00Z",
                retake_window_close="2027-05-15T00:00:00Z",
            ),
            BOARD,
        )
    )
    assert_cycle(cycle_b)
    assert cycle_b["status"] == CycleStatus.DRAFT.value


def test_cycle_windows_partial_overlap_rejected_even_in_draft(api):
    """PRD §3.1: "The new cycle's submission window must not overlap the window of
    any existing cycle in `DRAFT`, `OPEN`, or `SCORING` status under the half-open
    semantics of §2.7 — touching endpoints are allowed — or creation fails with
    `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 409)."

    The pre-existing cycle here is still DRAFT, which is inside the blocking set;
    the new window opens one day before the existing window closes.

    Design: Difficulty/resource_temporal_overlap/cycle_windows_half_open_adjacency_allowed
    """
    set_logical_clock(STANDARD_WORK_CLOCK)
    validate_created(api.create_cycle(create_cycle_payload(), BOARD))

    response = api.create_cycle(
        create_cycle_payload(
            submission_window_open="2027-02-28T00:00:00Z",
            submission_window_close="2027-04-30T00:00:00Z",
            retake_window_close="2027-05-15T00:00:00Z",
        ),
        BOARD,
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)


def test_logical_clock_default_is_fixed_at_startup(api):
    """PRD §2.4: "All temporal rules in this document are evaluated against a
    server-held **logical clock**, never against wall-clock time. At startup the
    clock reads exactly `2026-09-01T00:00:00Z`."

    No clock-set call is made in this test; the freshly restarted server must
    stamp the new cycle's created_at from the documented startup instant.

    Design: Corner/cross-cutting complexity layers/logical_clock_default_is_fixed_at_startup
    """
    cycle = validate_created(api.create_cycle(create_cycle_payload(), BOARD))

    assert_cycle(cycle)
    assert _parse_iso(cycle["created_at"]) == _parse_iso(CLOCK_STARTUP_DEFAULT_ISO)
