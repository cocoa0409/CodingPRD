"""Task funding arithmetic: commission bands, fee tiers, escrow and refunds."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_hit_payload,
    create_cancel_payload,
    assert_hit,
    assert_hit_invariants,
    assert_requester_invariants,
    make_requester_headers,
    register_requester,
    fund_requester,
    get_requester,
    get_hit,
    create_task,
    publish_task,
    create_published_task,
    setup_requester,
    setup_requester_and_hit,
    set_clock,
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
)


# ═════════════════════════════════════════════════════════════════════════════
# The pinned evaluation order of the required-funds figure
# ═════════════════════════════════════════════════════════════════════════════

def test_funds_required_is_driven_by_the_intermediate_pre_fee_amount(api, admin_headers):
    """PRD §3.1: "it is the *intermediate* amount — not the gross pool — that
    selects the per-assignment fee tier: below 20,000 cents every assignment is
    charged 5 cents, and at 20,000 cents or above the fee drops to 3 cents per
    assignment."
    PRD §3.1: "The final `funds_required_cents` is that intermediate amount plus
    the per-assignment fee multiplied by the pool size."

    A 1750c x 10 pool has a gross pool of 17,500c — below the 20,000c fee line —
    but the 15% commission lifts the intermediate amount to 20,125c, so the
    cheaper 3c fee applies: 20,125 + 10 * 3 == 20,155.

    Design: Difficulty/combinatorial_formula/hit_funds_required_circular_tier_evaluation_order
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Tier")
    requester = fund_requester(requester, 50_000)

    res = api.create_hit(
        create_hit_payload(
            requester["id"], title="Tier Probe", reward_cents=1750,
            max_assignments=10, assignment_duration_minutes=60,
            time_limit_minutes=120,
        ),
        make_requester_headers(requester["id"]),
    )
    hit = validate_success(res, 201)
    assert hit["funds_required_cents"] == 20155, (
        f"expected the 3c fee tier selected off the intermediate amount, got "
        f"{hit['funds_required_cents']}"
    )


def test_publish_escrows_the_intermediate_tier_figure(api, admin_headers):
    """PRD §3.1: "on success the requester's `escrowed_cents` rises by
    `funds_required_cents` and the task's own `escrowed_cents` is set to that
    same figure, so the platform now holds the entire lifetime cost of the task"
    PRD §3.1: "at 50,000 cents or above the rate is 10 percent"

    The 1750c x 10 pool sits at a gross of 17,500c, so the mid 15% commission
    applies and the whole 20,155c moves into escrow on publish.

    Design: Difficulty/combinatorial_formula/hit_funds_required_circular_tier_evaluation_order
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Tier Escrow")
    requester = fund_requester(requester, 50_000)
    hit = create_task(
        requester["id"], title="Tier Escrow", reward_cents=1750, max_assignments=10,
        assignment_duration_minutes=60, time_limit_minutes=120,
    )
    assert hit["funds_required_cents"] == 20155, "Setup: unexpected funds_required_cents"

    published = publish_task(hit["id"], requester["id"])
    assert published["status"] == "PUBLISHED"
    assert published["escrowed_cents"] == 20155

    fresh = get_requester(requester["id"])
    assert fresh["escrowed_cents"] == 20155
    assert fresh["prepaid_balance_cents"] == 50_000 - 20155


# ═════════════════════════════════════════════════════════════════════════════
# Commission-band boundary
# ═════════════════════════════════════════════════════════════════════════════

def test_funds_required_at_gross_pool_exactly_10000_uses_the_mid_band(api, admin_headers):
    """PRD §3.1: "from 10,000 cents up to but not including 50,000 cents the rate
    is 15 percent"
    PRD §3.1: "The band boundary is inclusive on its lower edge, so a gross pool
    of exactly 10,000 cents takes the 15 percent rate"

    A 1000c x 10 pool has a gross of exactly 10,000c: commission 1,500 (not the
    20% band's 2,000), intermediate 11,500 below the 20,000 fee line, so 5c per
    assignment: 11,500 + 50 == 11,550.

    Design: Corner/calculations/hit_funds_required_boundary_at_gross_pool_exactly_10000
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Boundary")

    res = api.create_hit(
        create_hit_payload(
            requester["id"], title="Boundary Probe", reward_cents=1000,
            max_assignments=10, assignment_duration_minutes=60,
            time_limit_minutes=120,
        ),
        make_requester_headers(requester["id"]),
    )
    hit = validate_success(res, 201)
    assert hit["funds_required_cents"] == 11550, (
        f"the inclusive lower band edge must select the 15% rate, got "
        f"{hit['funds_required_cents']}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Creation state and the computed funds figure
# ═════════════════════════════════════════════════════════════════════════════

def test_hit_create_starts_in_draft_with_no_escrow(api, admin_headers):
    """PRD §3.1: "a task is always minted in `DRAFT` status with `escrowed_cents`
    at zero and no funds yet committed."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/state_machines/hit_create_starts_in_draft_with_no_escrow
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Initial")

    res = api.create_hit(
        create_hit_payload(requester["id"], title="Initial Probe", reward_cents=100,
                           max_assignments=1),
        make_requester_headers(requester["id"]),
    )
    hit = validate_success(res, 201)
    assert hit["status"] == "DRAFT"
    assert hit["escrowed_cents"] == 0
    assert hit["accepted_count"] == 0
    assert get_requester(requester["id"])["escrowed_cents"] == 0


def test_new_hit_reports_the_computed_funds_required(api, admin_headers):
    """PRD §3.1: "Creation also computes `funds_required_cents` immediately"
    PRD §3.1: "below 10,000 cents the rate is 20 percent"
    PRD §3.1: "below 20,000 cents every assignment is charged 5 cents"

    A 100c single-slot pool with no bonus: gross 100, 20% commission 20,
    intermediate 120, 5c fee -> 125.

    Design: Corner/entities/hit_funds_required_is_computed_on_create
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Compprobe")
    hit = create_task(requester["id"], title="Computed Probe", reward_cents=100,
                      max_assignments=1, assignment_duration_minutes=60,
                      time_limit_minutes=120)

    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["funds_required_cents"] == 125
    assert stored["escrowed_cents"] == 0
    assert stored["accepted_count"] == 0
    assert stored["status"] == "DRAFT"
    assert stored["committed_assignments"] == 0


def test_hit_create_without_title_returns_invalid_request(api, admin_headers):
    """PRD §3.1: "A `Requester` drafts a task by supplying a `title` for display,
    a per-assignment `reward_cents`, a `max_assignments` pool size, an
    `assignment_duration_minutes` working window, and a `time_limit_minutes` hold
    window."
    PRD §2.10: "`ERR_INVALID_REQUEST` (HTTP 400) rejects a malformed body, a
    missing required field, or a value outside its declared enum or type"

    Design: Corner/entities/hit_create_without_title_returns_invalid_request
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Required")
    payload = create_hit_payload(requester["id"], reward_cents=100, max_assignments=1)
    payload.pop("title")

    res = api.create_hit(payload, make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    listed = api_client.list_hits(
        make_requester_headers(requester["id"]), params={"requester_id": requester["id"]}
    )
    assert listed.json()["data"] == []


# ═════════════════════════════════════════════════════════════════════════════
# Publishing: funding, refusal paths, and refund conservation
# ═════════════════════════════════════════════════════════════════════════════

def test_publish_moves_draft_to_published_and_holds_funds(api, admin_headers):
    """PRD §3.1: "on success the requester's `escrowed_cents` rises by
    `funds_required_cents` and the task's own `escrowed_cents` is set to that
    same figure"

    Design: Corner/state_machines/hit_publish_moves_draft_to_published_and_holds_funds
    """
    set_clock(CLOCK_EPOCH)
    requester, hit = setup_requester_and_hit(publish=False, deposit_cents=2_000,
                                             name="Acme Publish")

    published = publish_task(hit["id"], requester["id"])
    assert published["status"] == "PUBLISHED"
    assert published["escrowed_cents"] == 125

    fresh = get_requester(requester["id"])
    assert fresh["prepaid_balance_cents"] == 1875
    assert fresh["escrowed_cents"] == 125


def test_publish_response_reflects_escrow_immediately(api, admin_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.1: "the requester's `escrowed_cents` rises by `funds_required_cents`
    and the task's own `escrowed_cents` is set to that same figure"

    Design: Corner/consistency_model/immediate_consistency_reflects_escrow_in_the_publish_response
    """
    set_clock(CLOCK_EPOCH)
    requester, hit = setup_requester_and_hit(publish=False, deposit_cents=2_000,
                                             name="Acme Immediate")

    res = api.publish_hit(hit["id"], make_requester_headers(requester["id"]))
    published = validate_success(res, 200)
    assert published["status"] == "PUBLISHED"

    fresh = get_requester(requester["id"])
    assert fresh["prepaid_balance_cents"] == 1875
    assert fresh["escrowed_cents"] == 125


def test_publish_below_funds_required_returns_insufficient_funds(api, admin_headers):
    """PRD §3.1: "since money is checked last, the requester's
    `prepaid_balance_cents` must be at least the task's `funds_required_cents`,
    failing with `ERR_INSUFFICIENT_FUNDS` (HTTP 402) otherwise."

    Design: Corner/errors/publish_without_balance_returns_insufficient_funds
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Short")
    requester = fund_requester(requester, 100)
    hit = create_task(requester["id"], title="Short Probe", reward_cents=100,
                      max_assignments=1, assignment_duration_minutes=60,
                      time_limit_minutes=120)

    res = api.publish_hit(hit["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS, 402)

    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["status"] == "DRAFT"
    assert stored["escrowed_cents"] == 0
    assert get_requester(requester["id"])["prepaid_balance_cents"] == 100


def test_second_publish_reports_the_state_error_not_the_fiscal_one(api, admin_headers):
    """PRD §2.10: "Validations across the platform do not fire as an unordered
    set; they fire in a fixed nine-step order, and a request that violates an
    earlier step never reaches a later one."
    PRD §2.10: "4. **State** (`ERR_INVALID_STATE`, HTTP 409)"

    A requester drained to zero by the first publish violates both the state rule
    (the task is no longer DRAFT) and the fiscal rule, and the state rule wins.

    Design: Corner/validations/conflict_between_state_and_fiscal_on_an_empty_balance_publish
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Ladder")
    requester = fund_requester(requester, 125)
    hit = create_task(requester["id"], title="Ladder Probe", reward_cents=100,
                      max_assignments=1, assignment_duration_minutes=60,
                      time_limit_minutes=120)
    publish_task(hit["id"], requester["id"])

    res = api.publish_hit(hit["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_requester(requester["id"])["prepaid_balance_cents"] == 0


def test_publish_then_cancel_conserves_the_requester_balances(api, admin_headers):
    """PRD §3.1: "Cancelling a published task is a refund: the task's entire
    `escrowed_cents` returns to the requester's `prepaid_balance_cents`, the
    requester's `escrowed_cents` falls by the same amount, the task's
    `escrowed_cents` is zeroed, and the task reaches `CANCELLED`, a terminal
    state from which it never moves again."

    Before the cancel the pair reads (1875 prepaid, 125 escrow); afterwards it
    reads (2000, 0), so the sum is conserved at 2000 across the compensating pair.

    Design: Difficulty/compensating_invariant/requester_prepaid_plus_escrow_conserved_across_publish_and_cancel
    """
    set_clock(CLOCK_EPOCH)
    requester, hit = setup_requester_and_hit(publish=False, deposit_cents=2_000,
                                             name="Acme Conserve")
    published = publish_task(hit["id"], requester["id"])

    before = get_requester(requester["id"])
    assert before["prepaid_balance_cents"] == 1875
    assert before["escrowed_cents"] == 125

    res = api.cancel_hit(
        hit["id"], create_cancel_payload(published["version"]),
        make_requester_headers(requester["id"]),
    )
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["escrowed_cents"] == 0

    after = get_requester(requester["id"])
    assert after["prepaid_balance_cents"] == 2000
    assert after["escrowed_cents"] == 0
    assert before["prepaid_balance_cents"] + before["escrowed_cents"] == (
        after["prepaid_balance_cents"] + after["escrowed_cents"]
    )


def test_cancel_of_draft_task_leaves_the_balance_untouched(api, admin_headers):
    """PRD §3.1: "Cancelling a drafted task releases nothing, since a `DRAFT`
    holds no funds."
    PRD §3.1: "the task reaches `CANCELLED`, a terminal state from which it never
    moves again"

    Design: Difficulty/compensating_invariant/requester_prepaid_plus_escrow_conserved_across_publish_and_cancel
    """
    set_clock(CLOCK_EPOCH)
    requester, hit = setup_requester_and_hit(publish=False, deposit_cents=2_000,
                                             name="Acme Draft Cancel")

    res = api.cancel_hit(
        hit["id"], create_cancel_payload(hit["version"]),
        make_requester_headers(requester["id"]),
    )
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["escrowed_cents"] == 0

    after = get_requester(requester["id"])
    assert after["prepaid_balance_cents"] == 2000
    assert after["escrowed_cents"] == 0