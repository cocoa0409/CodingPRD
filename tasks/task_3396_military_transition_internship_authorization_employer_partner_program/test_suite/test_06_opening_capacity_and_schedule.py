"""Opening capacity, member schedule half-open overlap, the slot ledger
round-trip, and the manual opening close."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, factories, fixtures, make_employer_rep_headers


def _capacity_world(api, capacity, member_count):
    """N members with APPROVED applications plus one opening of ``capacity``."""
    w = fixtures.setup_members_with_approved_applications(api, member_count)
    eo = fixtures.setup_employer_with_opening(api, capacity=capacity)
    return w, eo.employer, eo.opening


def _proposal(api, app_id, opening_id, employer_id, start, end):
    opening = fixtures.get_opening(api, opening_id)
    payload = factories.create_match_payload(app_id, opening_id, opening["version"], start, end)
    return api.create_match(payload, make_employer_rep_headers(employer_id))


def test_opening_capacity_two_overlapping_fit(api):
    """PRD §3.4: "Last of all, per the standard priority grouping that runs quota
    checks last, capacity is enforced: the number of non-terminal matches on the
    opening whose half-open intervals overlap the proposed interval must remain
    strictly below `capacity`, else `ERR_OPENING_AT_CAPACITY`."

    With capacity 2, the first two fully-overlapping proposals see counts 0 and 1,
    both strictly below 2.

    Design: Difficulty/boundary_precision_check/opening_capacity_exact_overlap_count
    """
    w, employer, opening = _capacity_world(api, capacity=2, member_count=2)
    first = _proposal(api, w.applications[0]["id"], opening["id"], employer["id"], "2026-11-01", "2026-12-01")
    validate_success(first, 201)
    second = _proposal(api, w.applications[1]["id"], opening["id"], employer["id"], "2026-11-01", "2026-12-01")
    validate_success(second, 201)
    assert fixtures.get_opening(api, opening["id"])["filled_count"] == 2


def test_opening_capacity_third_overlap_rejected_adjacent_accepted(api):
    """PRD §3.4: "Last of all, per the standard priority grouping that runs quota
    checks last, capacity is enforced: the number of non-terminal matches on the
    opening whose half-open intervals overlap the proposed interval must remain
    strictly below `capacity`, else `ERR_OPENING_AT_CAPACITY`."
    PRD §3.4: "The member's schedule must stay free of overlaps under half-open
    interval semantics: the proposal is rejected with `ERR_MEMBER_SCHEDULE_OVERLAP`
    if any other non-terminal match of the member fails to satisfy either disjunct
    of the separation test — the proposal's `end_date` on or before the existing
    match's `start_date`, or the proposal's `start_date` on or after the existing
    match's `end_date` — which means back-to-back adjacency, where the new match
    starts exactly when an existing one ends, is allowed."
    PRD §2.10: "An opening's `filled_count` and a member's `active_match_count`
    each count that entity's InternshipMatches whose `match_status` is one of the
    three non-terminal statuses — `PROPOSED`, `INSTALLATION_APPROVED`, or `ACTIVE`;
    matches in `INSTALLATION_DENIED`, `COMPLETED`, `TERMINATED_EARLY`, or
    `MATCH_VOIDED` never count."

    Design: Difficulty/boundary_precision_check/opening_capacity_exact_overlap_count
    """
    w, employer, opening = _capacity_world(api, capacity=2, member_count=4)
    validate_success(_proposal(api, w.applications[0]["id"], opening["id"], employer["id"], "2026-11-01", "2026-12-01"), 201)
    validate_success(_proposal(api, w.applications[1]["id"], opening["id"], employer["id"], "2026-11-01", "2026-12-01"), 201)

    third = _proposal(api, w.applications[2]["id"], opening["id"], employer["id"], "2026-11-15", "2026-12-15")
    validate_error(third, ApiErrorId.ERR_OPENING_AT_CAPACITY)

    adjacent = _proposal(api, w.applications[3]["id"], opening["id"], employer["id"], "2026-12-01", "2026-12-31")
    validate_success(adjacent, 201)
    assert fixtures.get_opening(api, opening["id"])["filled_count"] == 3, (
        "the ledger counts all three non-terminal matches, not just overlapping ones"
    )


def _member_with_one_match(api):
    """One member with an APPROVED application and a PROPOSED match
    [2026-11-01, 2026-12-01) on a capacity-3 opening."""
    w = fixtures.setup_member_with_application(api)
    eo = fixtures.setup_employer_with_opening(api, capacity=3)
    match1 = fixtures.propose_match(api, w.application["id"], eo.opening["id"], "2026-11-01", "2026-12-01")
    return w, eo.employer, eo.opening, match1


def test_member_schedule_interior_overlap_rejected(api):
    """PRD §3.4: "The member's schedule must stay free of overlaps under half-open
    interval semantics: the proposal is rejected with `ERR_MEMBER_SCHEDULE_OVERLAP`
    if any other non-terminal match of the member fails to satisfy either disjunct
    of the separation test — the proposal's `end_date` on or before the existing
    match's `start_date`, or the proposal's `start_date` on or after the existing
    match's `end_date` — which means back-to-back adjacency, where the new match
    starts exactly when an existing one ends, is allowed."

    Design: Difficulty/resource_temporal_overlap/member_schedule_half_open_adjacency
    """
    w, employer, opening, _ = _member_with_one_match(api)
    interior = _proposal(api, w.application["id"], opening["id"], employer["id"], "2026-11-15", "2026-12-15")
    validate_error(interior, ApiErrorId.ERR_MEMBER_SCHEDULE_OVERLAP)


def test_member_schedule_adjacency_accepted(api):
    """PRD §3.4: "The member's schedule must stay free of overlaps under half-open
    interval semantics: the proposal is rejected with `ERR_MEMBER_SCHEDULE_OVERLAP`
    if any other non-terminal match of the member fails to satisfy either disjunct
    of the separation test — the proposal's `end_date` on or before the existing
    match's `start_date`, or the proposal's `start_date` on or after the existing
    match's `end_date` — which means back-to-back adjacency, where the new match
    starts exactly when an existing one ends, is allowed."

    Design: Difficulty/resource_temporal_overlap/member_schedule_half_open_adjacency
    """
    w, employer, opening, _ = _member_with_one_match(api)
    adjacent = _proposal(api, w.application["id"], opening["id"], employer["id"], "2026-12-01", "2026-12-31")
    validate_success(adjacent, 201)
    assert fixtures.get_member(api, w.member["id"])["active_match_count"] == 2


def _capacity_one_with_two(api):
    """Capacity-1 opening already holding back-to-back matches
    [2026-11-01, 2026-12-01) and [2026-12-01, 2027-01-01) for two members; a
    third member's application is ready."""
    w, employer, opening = _capacity_world(api, capacity=1, member_count=3)
    mt_a = _proposal(api, w.applications[0]["id"], opening["id"], employer["id"], "2026-11-01", "2026-12-01")
    validate_success(mt_a, 201)
    mt_b = _proposal(api, w.applications[1]["id"], opening["id"], employer["id"], "2026-12-01", "2027-01-01")
    validate_success(mt_b, 201)
    return w, employer, opening


def test_opening_back_to_back_fits_capacity_one(api):
    """PRD §3.4: "Last of all, per the standard priority grouping that runs quota
    checks last, capacity is enforced: the number of non-terminal matches on the
    opening whose half-open intervals overlap the proposed interval must remain
    strictly below `capacity`, else `ERR_OPENING_AT_CAPACITY`."

    Capacity 1 still admits the back-to-back second match: its interval shares no
    instant with the first, so the overlapping count stays 0 < 1.

    Design: Difficulty/resource_temporal_overlap/opening_concurrency_threshold_allows_back_to_back
    """
    _, _, opening = _capacity_one_with_two(api)
    assert fixtures.get_opening(api, opening["id"])["filled_count"] == 2


def test_opening_midwindow_overlap_rejected_capacity_one(api):
    """PRD §3.4: "Last of all, per the standard priority grouping that runs quota
    checks last, capacity is enforced: the number of non-terminal matches on the
    opening whose half-open intervals overlap the proposed interval must remain
    strictly below `capacity`, else `ERR_OPENING_AT_CAPACITY`."

    The mid-window proposal [2026-11-20, 2026-12-20) overlaps both existing
    matches, driving concurrent occupancy to 2 against capacity 1.

    Design: Difficulty/resource_temporal_overlap/opening_concurrency_threshold_allows_back_to_back
    """
    w, employer, opening = _capacity_one_with_two(api)
    resp = _proposal(api, w.applications[2]["id"], opening["id"], employer["id"], "2026-11-20", "2026-12-20")
    validate_error(resp, ApiErrorId.ERR_OPENING_AT_CAPACITY)


def _slot_ledger_world(api):
    """Capacity-1 opening holding match1 [2026-11-01, 2026-12-01) for member 1;
    member 2's application is ready."""
    w, employer, opening = _capacity_world(api, capacity=1, member_count=2)
    match1 = fixtures.propose_match(api, w.applications[0]["id"], opening["id"], "2026-11-01", "2026-12-01")
    after_create = fixtures.get_opening(api, opening["id"])
    return w, employer, opening, match1, after_create


def test_slot_ledger_fill_release_cycle(api):
    """PRD §3.6: "Termination moves the match to `TERMINATED_EARLY`, recomputes
    `filled_count` and `active_match_count`, and increments the match's `version`."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by 1
    with every modification to the resource, including modifications driven by
    sweeps and cascades."

    Design: Difficulty/compensating_invariant/opening_slot_ledger_roundtrip
    """
    w, employer, opening, match1, after_create = _slot_ledger_world(api)
    assert after_create["filled_count"] == 1

    blocked = _proposal(api, w.applications[1]["id"], opening["id"], employer["id"], "2026-11-10", "2026-12-10")
    validate_error(blocked, ApiErrorId.ERR_OPENING_AT_CAPACITY)

    terminated = fixtures.terminate_match(api, match1["id"], reason="VOLUNTARY", as_employer_id=employer["id"])
    assert terminated["match_status"] == "TERMINATED_EARLY"
    after_terminate = fixtures.get_opening(api, opening["id"])
    assert after_terminate["filled_count"] == 0, "the compensating terminate releases the slot"
    # NOTE (two-reader weakening): no opening-version bump is asserted here.
    # PRD §3.6 names only "the match's `version`" for termination, and §2.10
    # labels filled_count a *computed* counter, so whether its recompute is a
    # version-bumping "modification" (§2.5) is not uniquely derivable.


def test_slot_ledger_retry_after_release_succeeds(api):
    """PRD §2.10: "An opening's `filled_count` and a member's `active_match_count`
    each count that entity's InternshipMatches whose `match_status` is one of the
    three non-terminal statuses — `PROPOSED`, `INSTALLATION_APPROVED`, or `ACTIVE`;
    matches in `INSTALLATION_DENIED`, `COMPLETED`, `TERMINATED_EARLY`, or
    `MATCH_VOIDED` never count."

    Design: Difficulty/compensating_invariant/opening_slot_ledger_roundtrip
    """
    w, employer, opening, match1, _ = _slot_ledger_world(api)
    fixtures.terminate_match(api, match1["id"], reason="VOLUNTARY", as_employer_id=employer["id"])

    retry = _proposal(api, w.applications[1]["id"], opening["id"], employer["id"], "2026-11-10", "2026-12-10")
    validate_success(retry, 201)
    assert fixtures.get_opening(api, opening["id"])["filled_count"] == 1


def test_opening_manual_close_voids_proposals(api):
    """PRD §3.4: "Closing requires the opening to be `OPEN` — a double-close is
    rejected with `ERR_OPENING_NOT_OPEN` — and requires `X-User-ID` to equal the
    opening's `employer_id`, else `ERR_FORBIDDEN_OWNERSHIP`. Closing moves the
    opening to `CLOSED`, voids every match on it still in `PROPOSED` or
    `INSTALLATION_APPROVED` (each becomes `MATCH_VOIDED`), leaves `ACTIVE` matches
    untouched because they are already in flight, and recomputes `filled_count`
    plus the `active_match_count` of every affected member."
    PRD §3.4: "Beyond the universal checks, the gates fire in this pinned order:
    body foreign keys exist in declared input order — the application first
    (`ERR_APPLICATION_NOT_FOUND`), then the opening (`ERR_OPENING_NOT_FOUND`); the
    opening's version matches (`ERR_STALE_VERSION`); the caller owns the opening's
    employer (`ERR_FORBIDDEN_OWNERSHIP`); the application is `APPROVED`
    (`ERR_APPLICATION_NOT_APPROVED`); the opening is `OPEN` (`ERR_OPENING_NOT_OPEN`);
    the employer is `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`); the applicant
    member is `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."

    Design: Corner/state_machines/opening_manual_close_voids_proposals
    """
    ns = fixtures.setup_match(api)  # PROPOSED match on the opening
    opening_id, employer_id = ns.opening["id"], ns.employer["id"]

    closed = validate_success(api.close_opening(opening_id, make_employer_rep_headers(employer_id)))
    assert closed["status"] == "CLOSED"
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "MATCH_VOIDED"
    assert fixtures.get_opening(api, opening_id)["filled_count"] == 0
    assert fixtures.get_employer(api, employer_id)["authorization_status"] == "AUTHORIZED"

    double_close = api.close_opening(opening_id, make_employer_rep_headers(employer_id))
    validate_error(double_close, ApiErrorId.ERR_OPENING_NOT_OPEN)

    repropose = _proposal(api, ns.application["id"], opening_id, employer_id, "2026-10-01", "2026-10-31")
    validate_error(repropose, ApiErrorId.ERR_OPENING_NOT_OPEN)
