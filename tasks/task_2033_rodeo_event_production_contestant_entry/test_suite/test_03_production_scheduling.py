"""Performance arena overlap, judge buffered conflicts, and uniqueness rules
(PRD §2.8, §3.1, §3.2, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_performance,
    create_judge_assignment_payload,
    create_judge_payload,
    create_performance_payload,
    create_rodeo,
    create_stock_animal_payload,
    create_stock_contract_payload,
    register_contestant,
    register_judge,
    setup_entries_open,
    TEST_USERS,
    transition_rodeo,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]


def test_back_to_back_performances_allowed_and_overlap_rejected(api):
    """PRD §3.1: "Two performances of the same rodeo in the same arena may not
    overlap while `SCHEDULED`: each occupies a half-open interval that includes
    its `starts_at` instant and excludes its `ends_at` instant, so back-to-back
    performances — one ending exactly when the next begins — are permitted,
    while any true intersection is rejected with `ERR_PERFORMANCE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/arena_performance_half_open_adjacency_allowed
    """
    rodeo = create_rodeo(name="Twin Falls Rodeo", city="Twin Falls")
    first = validate_success(
        api.create_performance(
            create_performance_payload(
                rodeo["id"], label="Matinee",
                starts_at="2026-08-14T14:00:00Z", ends_at="2026-08-14T16:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert first["status"] == "SCHEDULED"

    # Adjacent: starts exactly when the first ends — half-open, so permitted.
    adjacent = validate_success(
        api.create_performance(
            create_performance_payload(
                rodeo["id"], label="Evening",
                starts_at="2026-08-14T16:00:00Z", ends_at="2026-08-14T18:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"

    # True intersection with both existing windows: rejected.
    overlapping = api.create_performance(
        create_performance_payload(
            rodeo["id"], label="Overlap",
            starts_at="2026-08-14T15:00:00Z", ends_at="2026-08-14T17:00:00Z",
        ),
        ADMIN,
    )
    validate_error(overlapping, ApiErrorId.ERR_PERFORMANCE_OVERLAP)


def test_same_window_on_different_arena_allowed(api):
    """PRD §3.1: "Two performances of the same rodeo in the same arena may not
    overlap while `SCHEDULED`" — the overlap rule keys on the (rodeo, arena)
    pair, so a different arena sharing the time window is permitted.

    Design: Difficulty/resource_temporal_overlap/arena_performance_half_open_adjacency_allowed
    """
    rodeo = create_rodeo(name="Twin Falls Rodeo", city="Twin Falls")
    validate_success(
        api.create_performance(
            create_performance_payload(
                rodeo["id"], label="Matinee", arena="Main",
                starts_at="2026-08-14T14:00:00Z", ends_at="2026-08-14T16:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    warmup = validate_success(
        api.create_performance(
            create_performance_payload(
                rodeo["id"], label="Warmup Slate", arena="Warmup",
                starts_at="2026-08-14T14:00:00Z", ends_at="2026-08-14T16:00:00Z",
                arena_capacity=100,
            ),
            ADMIN,
        ),
        201,
    )
    assert warmup["arena"] == "Warmup"


def test_buffered_conflict_rejects_adjacent_assignment(api):
    """PRD §3.4: "Assignments also respect a buffered conflict rule: each
    assignment occupies a window running from 45 minutes before its
    performance's `starts_at` to 45 minutes after its `ends_at`, including the
    start of that window and excluding its end, and a new assignment whose
    buffered window intersects another buffered window of the same judge is
    rejected with `ERR_JUDGE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/judge_buffered_travel_interval_blocks_adjacent_gigs
    """
    rodeo = create_rodeo(name="Moab Rodeo", city="Moab")
    p1 = add_performance(rodeo["id"], label="P1", starts_at="2026-08-14T14:00:00Z",
                         ends_at="2026-08-14T16:00:00Z")
    p2 = add_performance(rodeo["id"], label="P2", starts_at="2026-08-14T16:00:00Z",
                         ends_at="2026-08-14T18:00:00Z")
    judge = register_judge("J-14", "Judge Quatorze", "PRCA_GOLD")

    first = validate_success(
        api.create_judge_assignment(
            create_judge_assignment_payload(judge["id"], p1["id"], position="ARENA_1"),
            ADMIN,
        ),
        201,
    )
    assert first["position"] == "ARENA_1"

    # Raw intervals only touch at 16:00, but the buffered windows
    # [13:15, 16:45) and [15:15, 18:45) intersect — conflict.
    conflict = api.create_judge_assignment(
        create_judge_assignment_payload(judge["id"], p2["id"], position="ARENA_1"),
        ADMIN,
    )
    validate_error(conflict, ApiErrorId.ERR_JUDGE_CONFLICT)


def test_buffered_window_disjoint_or_different_judge_succeeds(api):
    """PRD §3.4: "each assignment occupies a window running from 45 minutes
    before its performance's `starts_at` to 45 minutes after its `ends_at` ...
    and a new assignment whose buffered window intersects another buffered
    window of the same judge is rejected with `ERR_JUDGE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/judge_buffered_travel_interval_blocks_adjacent_gigs
    """
    rodeo = create_rodeo(name="Moab Rodeo", city="Moab")
    p1 = add_performance(rodeo["id"], label="P1", starts_at="2026-08-14T14:00:00Z",
                         ends_at="2026-08-14T16:00:00Z")
    p2 = add_performance(rodeo["id"], label="P2", starts_at="2026-08-14T16:00:00Z",
                         ends_at="2026-08-14T18:00:00Z")
    p3 = add_performance(rodeo["id"], label="P3", starts_at="2026-08-14T18:00:00Z",
                         ends_at="2026-08-14T20:00:00Z")
    judge = register_judge("J-14", "Judge Quatorze", "PRCA_GOLD")
    other = register_judge("J-15", "Judge Quinze", "PRCA_GOLD")

    validate_success(
        api.create_judge_assignment(
            create_judge_assignment_payload(judge["id"], p1["id"], position="ARENA_1"),
            ADMIN,
        ),
        201,
    )

    # P3 18:00-20:00: buffered [17:15, 20:45) is disjoint from [13:15, 16:45).
    third = validate_success(
        api.create_judge_assignment(
            create_judge_assignment_payload(judge["id"], p3["id"], position="TIMER"),
            ADMIN,
        ),
        201,
    )
    assert third["position"] == "TIMER"

    # The conflict rule is scoped to the same judge: another judge may hold
    # the adjacent performance.
    other_p2 = validate_success(
        api.create_judge_assignment(
            create_judge_assignment_payload(other["id"], p2["id"], position="ARENA_1"),
            ADMIN,
        ),
        201,
    )
    assert other_p2["judge_id"] == other["id"]


def test_barrier_position_requires_gold_certification(api):
    """PRD §3.4: "The barrier position demands the gold card: a `BARRIER`
    assignment for a judge whose certification is not `PRCA_GOLD` is rejected
    with `ERR_VALIDATION`."

    Design: Corner/validations/barrier_position_requires_gold_certification
    """
    rodeo = create_rodeo(name="Cert Rodeo", city="Cert")
    performance = add_performance(rodeo["id"], label="Fri")
    judge = register_judge("J-47", "Judge Card", "PRCA_CARD")

    barrier = api.create_judge_assignment(
        create_judge_assignment_payload(judge["id"], performance["id"],
                                        position="BARRIER"),
        ADMIN,
    )
    validate_error(barrier, ApiErrorId.ERR_VALIDATION)

    arena = validate_success(
        api.create_judge_assignment(
            create_judge_assignment_payload(judge["id"], performance["id"],
                                            position="ARENA_1"),
            ADMIN,
        ),
        201,
    )
    assert arena["judge_id"] == judge["id"]


def test_duplicate_card_rejected_on_contestant_create(api):
    """PRD §3.2: "a `card_number` — the PRCA card, unique across all
    contestants, with duplicates rejected as `ERR_DUPLICATE_CARD`".
    PRD §3.4: "A judge is registered with a globally unique `card_number`
    (`ERR_DUPLICATE_CARD` on collision)" — a separate registry from the
    contestants', so a judge may carry the same card string.

    Design: Corner/validations/duplicate_card_rejected_on_contestant_create
    """
    register_contestant("PRCA-400", "Rider First")

    dup = api.create_contestant(
        {"card_number": "PRCA-400", "full_name": "Rider Second"}, OFFICE
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_CARD)

    judge = validate_success(
        api.create_judge(
            create_judge_payload(
                card_number="PRCA-400", full_name="Judge Cross",
                certification="PRCA_CARD",
            ),
            ADMIN,
        ),
        201,
    )
    assert judge["card_number"] == "PRCA-400"


def test_duplicate_tag_within_contract_rejected(api):
    """PRD §3.3: "Animals are registered under a contract via `contract_id`,
    with a `tag_number` unique within that contract (`ERR_DUPLICATE_TAG` on
    collision)" — the same tag under a different contract is permitted.

    Design: Corner/validations/duplicate_tag_within_contract_rejected
    """
    rodeo = create_rodeo(name="Tag Rodeo", city="Tag City")
    k1 = validate_success(
        api.create_stock_contract(
            create_stock_contract_payload(rodeo["id"], contractor_name="C1"), ADMIN
        ),
        201,
    )
    k2 = validate_success(
        api.create_stock_contract(
            create_stock_contract_payload(rodeo["id"], contractor_name="C2"), ADMIN
        ),
        201,
    )
    validate_success(
        api.create_stock_animal(
            create_stock_animal_payload(k1["id"], tag_number="A100"), ADMIN
        ),
        201,
    )

    dup = api.create_stock_animal(
        create_stock_animal_payload(k1["id"], tag_number="A100"), ADMIN
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_TAG)

    other = validate_success(
        api.create_stock_animal(
            create_stock_animal_payload(k2["id"], tag_number="A100"), ADMIN
        ),
        201,
    )
    assert other["contract_id"] == k2["id"]


def test_contract_activate_requires_rodeo_pre_lock(api):
    """PRD §3.3: "The contract begins `PROPOSED` and can be activated
    (`ACTIVATE`: `PROPOSED` → `ACTIVE`) only while the rodeo is `DRAFT` or
    `ENTRIES_OPEN`."
    PRD §2.8: "7. Rodeo posture gate — entries and re-entries require
    `ENTRIES_OPEN`; draws require `DRAW_LOCKED` or `IN_PROGRESS`; result
    recording requires `IN_PROGRESS`; payout finalization requires `COMPLETED`
    (`ERR_RODEO_NOT_OPEN`)."

    Design: Corner/state_machines/contract_activate_requires_rodeo_pre_lock
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BULL_RIDING"},
        rodeo_overrides={"name": "Roswell Rodeo"},
    )
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")
    contract = validate_success(
        api.create_stock_contract(
            create_stock_contract_payload(sc["rodeo"]["id"],
                                          contractor_name="Late Signing Co"),
            ADMIN,
        ),
        201,
    )
    assert contract["status"] == "PROPOSED"

    resp = api.stock_contract_transition(contract["id"], {"action": "ACTIVATE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RODEO_NOT_OPEN)

    after = validate_success(api.get_stock_contract(contract["id"], ADMIN), 200)
    assert after["status"] == "PROPOSED"
