"""Depth tests: two contended resources whose interval semantics disagree.

A shell under maintenance is contended with HALF-OPEN intervals, so a window
that starts at the exact instant the incumbent ends is legal. A term's overall
continuity capacity is contended with CLOSED intervals and a ceiling of two, so
the very same endpoint-touching case is a violation there. Both are exercised
against real interval arithmetic rather than against equality of bounds.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    factories as fac,
    fixtures as fx,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["lms_admin_headers"]

SEP_10 = "2026-09-10T00:00:00Z"
SEP_11 = "2026-09-11T00:00:00Z"
SEP_12 = "2026-09-12T00:00:00Z"
SEP_13 = "2026-09-13T00:00:00Z"
SEP_14 = "2026-09-14T00:00:00Z"
SEP_15 = "2026-09-15T00:00:00Z"
SEP_18 = "2026-09-18T00:00:00Z"
SEP_20 = "2026-09-20T00:00:00Z"
SEP_22 = "2026-09-22T00:00:00Z"
SEP_25 = "2026-09-25T00:00:00Z"
SEP_26 = "2026-09-26T00:00:00Z"
SEP_28 = "2026-09-28T00:00:00Z"
SEP_30 = "2026-09-30T00:00:00Z"


def _refused_window(api, term_id, kind, start, end, expected_term_version, error_id,
                    **extra):
    """Attempt a window create that must be refused, and return the error body."""
    response = api.create_continuity_window(
        fac.create_continuity_window_payload(
            term_id, kind, start, end, expected_term_version, **extra
        ),
        ADMIN,
    )
    return validate_error(response, error_id)


def _shell_with_one_maintenance_window(api):
    """An IN_SESSION term, an empty PROVISIONED shell, one OPEN MAINTENANCE window.

    The window covers the shell from 2026-09-10T00:00:00Z to 2026-09-12T00:00:00Z.
    The term's version is captured both immediately before and immediately after
    the create, because a window create bumps the term.
    """
    setup = fx.provisioned_shell_setup(api, "IN_SESSION")
    setup["term_before_w1"] = fx.read_term(api, setup["term"]["id"])
    setup["w1"] = fx.open_window(
        api, setup["term_before_w1"], "MAINTENANCE", SEP_10, SEP_12,
        shell_id=setup["shell"]["id"],
    )
    setup["term_after_w1"] = fx.read_term(api, setup["term"]["id"])
    return setup


def test_overlapping_shell_maintenance_window_is_refused_and_creates_no_row(api):
    """PRD §3.9: "The first is a per-shell exclusion. When `shell_id` is present,
    no other window with the same `shell_id`, the same `kind` and `window_state`
    `OPEN` may intersect the new interval **half-open**, treating the interval as
    including its start and excluding its end; a collision is refused with
    `ERR_WINDOW_OVERLAP`."
    PRD §3.9: "A newly opened window records `affected_enrollment_count` — the
    shell's `active_enrollment_count` for a shell-scoped window, or the term's
    `total_active_enrollments` for a term-wide one — and, for a window whose
    `kind` is `EXTENSION`, records `extension_days_granted` as the window's length
    in seconds divided by 86,400 and rounded **up** to a whole day, so that any
    partial day counts as a full granted day; every other kind records 0."
    PRD §3.9: "Creating a window increments the **term's** `version` by one, which
    is what makes two clients racing to open windows against the same term visible
    to each other."
    PRD §2.7: "A mismatch with the term's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412). A successful create increments the term's
    `version` by one, so a superseding window must re-read the term."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/resource_temporal_overlap/shell_scoped_maintenance_windows_use_half_open_intervals_so_abutment_is_legal
    """
    s = _shell_with_one_maintenance_window(api)

    assert s["w1"]["window_state"] == "OPEN"
    assert s["w1"]["affected_enrollment_count"] == 0, (
        "a shell-scoped window snapshots the shell's active_enrollment_count, "
        "and this shell carries no enrollments"
    )
    assert s["w1"]["extension_days_granted"] == 0, (
        "every kind other than EXTENSION records 0 granted days"
    )
    assert s["term_after_w1"]["version"] == s["term_before_w1"]["version"] + 1, (
        "the create bumps the term's version, not merely the window's"
    )

    _refused_window(
        api, s["term"]["id"], "MAINTENANCE", SEP_11, SEP_13,
        s["term_after_w1"]["version"], ApiErrorId.ERR_WINDOW_OVERLAP.value,
        shell_id=s["shell"]["id"],
    )

    term_now = fx.read_term(api, s["term"]["id"])
    assert term_now["version"] == s["term_after_w1"]["version"], (
        "only a successful create increments the term, so the refusal must leave "
        "the version untouched"
    )
    rows, meta = validate_paginated(
        api.list_continuity_windows(ADMIN, params={"shell_id": s["shell"]["id"]})
    )
    assert meta["total_count"] == 1, (
        "the refused request must not have persisted a second window row"
    )
    assert [row["id"] for row in rows] == [s["w1"]["id"]]


def test_abutting_and_different_kind_shell_windows_are_both_accepted(api):
    """PRD §3.9: "Two windows that merely touch — one ending at the exact instant
    the next begins — therefore do not collide, and both may be open at once."
    PRD §3.9: "The first is a per-shell exclusion. When `shell_id` is present, no
    other window with the same `shell_id`, the same `kind` and `window_state`
    `OPEN` may intersect the new interval **half-open**, treating the interval as
    including its start and excluding its end; a collision is refused with
    `ERR_WINDOW_OVERLAP`."
    PRD §3.9: "A newly opened window records `affected_enrollment_count` — the
    shell's `active_enrollment_count` for a shell-scoped window, or the term's
    `total_active_enrollments` for a term-wide one — and, for a window whose
    `kind` is `EXTENSION`, records `extension_days_granted` as the window's length
    in seconds divided by 86,400 and rounded **up** to a whole day, so that any
    partial day counts as a full granted day; every other kind records 0."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by `created_at` ascending."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/resource_temporal_overlap/shell_scoped_maintenance_windows_use_half_open_intervals_so_abutment_is_legal
    """
    s = _shell_with_one_maintenance_window(api)
    shell_id = s["shell"]["id"]

    _refused_window(
        api, s["term"]["id"], "MAINTENANCE", SEP_11, SEP_13,
        s["term_after_w1"]["version"], ApiErrorId.ERR_WINDOW_OVERLAP.value,
        shell_id=shell_id,
    )

    abutting = fx.open_window(
        api, s["term_after_w1"], "MAINTENANCE", SEP_12, SEP_14, shell_id=shell_id
    )
    assert abutting["window_state"] == "OPEN", (
        "a window opening at the exact instant the incumbent ends shares no "
        "instant with it under half-open semantics"
    )

    covering = fx.open_window_for(
        api, s["term"]["id"], "EXTENSION", SEP_10, SEP_12, shell_id=shell_id
    )
    assert covering["window_state"] == "OPEN", (
        "the exclusion is scoped to the shell AND the kind, so a fully covering "
        "EXTENSION is untouched by the MAINTENANCE incumbent"
    )
    assert covering["extension_days_granted"] == 2, (
        "172800 seconds over 86400, rounded up, is 2 granted days"
    )
    assert abutting["extension_days_granted"] == 0
    assert s["w1"]["extension_days_granted"] == 0

    rows, meta = validate_paginated(
        api.list_continuity_windows(
            ADMIN, params={"shell_id": shell_id, "window_state": "OPEN"}
        )
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [
        s["w1"]["id"], abutting["id"], covering["id"]
    ], "three OPEN windows on one shell, in created_at ascending order"
    assert rows[0]["kind"] == "MAINTENANCE"


def _term_at_the_outage_cap(api):
    """An IN_SESSION term with no shells and two overlapping OPEN OUTAGE windows.

    W1 runs 2026-09-10 to 2026-09-20 and W2 runs 2026-09-15 to 2026-09-25, so the
    term is sitting at exactly two concurrent outage windows.
    """
    term = fx.create_term_in_state(api, "IN_SESSION")
    w1 = fx.open_window(api, term, "OUTAGE", SEP_10, SEP_20)
    w2 = fx.open_window_for(api, term["id"], "OUTAGE", SEP_15, SEP_25)
    return {
        "term": term,
        "w1": w1,
        "w2": w2,
        "term_at_cap": fx.read_term(api, term["id"]),
    }


def test_third_overlapping_outage_window_breaches_the_two_window_ceiling(api):
    """PRD §3.9: "The second is a term-wide capacity rule that applies only when
    `kind` is `OUTAGE`. Counting the new window itself, no more than two open
    outage windows of one term may cover any single instant."
    PRD §3.9: "Equivalently: at most **one** existing open outage window of that
    term may intersect the new interval treated as **closed** — including both of
    its endpoints, so windows that only touch at an endpoint *do* count as sharing
    that instant. A third overlapping outage is refused with
    `ERR_CONTINUITY_CAP_EXCEEDED`."
    PRD §2.10: "The continuity concurrency ceiling: at most two of a term's open
    outage windows may cover any single instant, on `POST /continuity-windows` —
    otherwise `ERR_CONTINUITY_CAP_EXCEEDED`. Each window is individually legal;
    only the collective is not."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/resource_temporal_overlap/term_wide_outage_windows_use_closed_intervals_with_a_concurrency_cap_of_two
    """
    s = _term_at_the_outage_cap(api)
    term_id = s["term"]["id"]
    at_cap = s["term_at_cap"]["version"]

    assert s["w2"]["window_state"] == "OPEN", (
        "two mutually overlapping outage windows are legal; the ceiling is two"
    )

    _refused_window(
        api, term_id, "OUTAGE", SEP_18, SEP_28, at_cap,
        ApiErrorId.ERR_CONTINUITY_CAP_EXCEEDED.value,
    )
    _refused_window(
        api, term_id, "OUTAGE", SEP_20, SEP_22, at_cap,
        ApiErrorId.ERR_CONTINUITY_CAP_EXCEEDED.value,
    )

    clear_of_w2 = fx.open_window(api, s["term_at_cap"], "OUTAGE", SEP_26, SEP_30)
    assert clear_of_w2["window_state"] == "OPEN", (
        "an interval that starts after W2 ends shares an instant with neither "
        "incumbent, so the rule is interval-scoped rather than a per-term ceiling"
    )

    rows, meta = validate_paginated(
        api.list_continuity_windows(
            ADMIN, params={"term_id": term_id, "window_state": "OPEN"}
        )
    )
    assert meta["total_count"] == 3, (
        "neither refused request may leave a window row behind"
    )
    assert {row["id"] for row in rows} == {
        s["w1"]["id"], s["w2"]["id"], clear_of_w2["id"]
    }


def test_closing_one_outage_window_frees_capacity_for_the_refused_interval(api):
    """PRD §3.9: "Equivalently: at most **one** existing open outage window of that
    term may intersect the new interval treated as **closed** — including both of
    its endpoints, so windows that only touch at an endpoint *do* count as sharing
    that instant. A third overlapping outage is refused with
    `ERR_CONTINUITY_CAP_EXCEEDED`."
    PRD §3.9: "A window is **closed** (`CLOSE`) from `OPEN`, which stamps
    `closed_at` from the logical clock"
    PRD §3.9: "Creating a window increments the **term's** `version` by one, which
    is what makes two clients racing to open windows against the same term visible
    to each other."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/resource_temporal_overlap/term_wide_outage_windows_use_closed_intervals_with_a_concurrency_cap_of_two
    """
    s = _term_at_the_outage_cap(api)
    term_id = s["term"]["id"]
    at_cap = s["term_at_cap"]["version"]

    _refused_window(
        api, term_id, "OUTAGE", SEP_20, SEP_22, at_cap,
        ApiErrorId.ERR_CONTINUITY_CAP_EXCEEDED.value,
    )
    assert fx.read_term(api, term_id)["version"] == at_cap, (
        "a refused create leaves the term's version alone"
    )

    clear_of_w2 = fx.open_window(api, s["term_at_cap"], "OUTAGE", SEP_26, SEP_30)
    assert clear_of_w2["window_state"] == "OPEN"

    closed = fx.transition_window(api, s["w2"]["id"], "CLOSE")
    assert closed["window_state"] == "CLOSED"
    after_close = fx.read_term(api, term_id)
    assert after_close["version"] == at_cap + 1, (
        "only the accepted create bumped the term; closing a window mutates the "
        "window alone"
    )

    retry = fx.open_window(api, after_close, "OUTAGE", SEP_20, SEP_22)
    assert retry["window_state"] == "OPEN", (
        "the byte-identical interval is accepted once only one open outage window "
        "still covers 2026-09-20T00:00:00Z, so a refusal is never permanent"
    )
    final_term = fx.read_term(api, term_id)
    assert final_term["version"] == at_cap + 2, (
        "exactly two accepted creates bumped the term across the whole sequence"
    )

    rows, meta = validate_paginated(
        api.list_continuity_windows(
            ADMIN, params={"term_id": term_id, "window_state": "OPEN"}
        )
    )
    assert meta["total_count"] == 3
    ids = {row["id"] for row in rows}
    assert ids == {s["w1"]["id"], clear_of_w2["id"], retry["id"]}
    assert s["w2"]["id"] not in ids, "a CLOSED window no longer consumes capacity"
