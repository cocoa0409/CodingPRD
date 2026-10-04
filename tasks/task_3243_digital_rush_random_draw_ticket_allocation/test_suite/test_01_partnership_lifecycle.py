"""Partnership registration, market declaration and the suspension cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    assert_production, assert_market, assert_patron,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_partnership_registration_opens_in_draft_with_its_declared_default(api):
    """PRD §3.1: "An `OpsManager` registers it by supplying a `title`, the
    `producer_org` behind it, and the commercial terms the producer has
    conceded: a `refund_window_hours` figure describing how many hours before a
    performance's start a rush seat remains returnable, an `exchange_fee_cents`
    flat fee charged when a return-to-different-inventory is approved, and an
    `exchange_allowed` flag that must be supplied explicitly if it is to be
    anything other than its default of false."
    PRD §3.1: "Registration leaves the partnership in `DRAFT` with `version` at
    1, and nothing downstream can be sold under it yet."

    Design: Corner/entities/production_creation_applies_defaults_and_opens_in_draft
    """
    X.set_clock(C.BASE_CLOCK)
    response = api.create_production(
        {
            "title": "Draft Play",
            "producer_org": "Draft Partners",
            "refund_window_hours": 24,
            "exchange_fee_cents": 250,
        },
        X.OPS,
    )
    data = validate_success(response, expected_status=201)

    assert_production(data)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["exchange_allowed"] is False, \
        "an omitted exchange_allowed must default to false"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["refund_window_hours"] == 24
    assert data["exchange_fee_cents"] == 250
    assert response.json()["response_type"] == "object"
    assert response.json()["meta"]["api_request_id"].startswith("req_")
    assert response.json()["meta"]["api_request_timestamp"]


def test_patron_registration_needs_no_identity_and_starts_clean(api):
    """PRD §3.5: "A new patron begins in `ACTIVE` standing with a
    `draw_violation_count` of zero and a `version` of 1."
    PRD §3.5: "Registration is the only operation in the domain that requires no
    identity headers at all, which is what makes it reachable before anyone
    holds an account, and it is also the only operation an `Anonymous` caller
    may attempt."

    Design: Corner/entities/patron_creation_starts_active_with_zero_violations
    """
    X.set_clock(C.BASE_CLOCK)
    X.declare_market()
    response = api.register_patron(
        {
            "email": "fresh_patron@example.com",
            "display_name": "Fresh Patron",
            "market_code": "NYC",
        }
    )
    data = validate_success(response, expected_status=201)

    assert_patron(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["draw_violation_count"] == 0, \
        f"a new patron must carry no violations, got {data['draw_violation_count']}"
    assert data["version"] == 1
    assert data["email"] == "fresh_patron@example.com"
    assert data["display_name"] == "Fresh Patron"


def test_non_push_market_is_declared_with_its_first_desk_and_round_trips(api):
    """PRD §3.1: "When the declared model is anything but `MOBILE_PUSH` the same
    call may carry a `desk_code` and a `daily_capacity`, in which case the market
    is created together with its first concierge desk; a `MOBILE_PUSH` market
    ignores both fields."
    PRD §3.1: "A market and its handoff model are readable afterwards by the
    operating and analyst roles."

    Design: Corner/entities/market_creation_deploys_a_desk_only_for_non_mobile_models
    """
    X.set_clock(C.BASE_CLOCK)
    created = api.create_market(
        {
            "market_code": "LDN",
            "city": "London",
            "handoff_model": "CONCIERGE_DESK",
            "desk_code": "LDN-W1",
            "daily_capacity": 3,
        },
        X.OPS,
    )
    data = validate_success(created, expected_status=201)
    assert_market(data)
    assert data["handoff_model"] == "CONCIERGE_DESK"
    assert data["market_code"] == "LDN"
    assert data["city"] == "London"

    read = api.get_market(data["id"], X.DESK)
    read_back = validate_success(read)
    assert read_back["handoff_model"] == "CONCIERGE_DESK", \
        "the declared handoff model must round-trip unchanged"
    assert read_back["market_code"] == "LDN"


def test_push_market_purchases_never_require_a_handoff(api):
    """PRD §3.10: "A `MOBILE_PUSH` market needs no physical act at all: a
    purchase in such a market carries a `handoff_status` of `NOT_REQUIRED`, its
    `handoff_token` stays null for the whole life of the purchase, its
    `handoff_verified_at` and `handoff_failed_at` stay null, and no desk is ever
    attached to it."

    Design: Corner/entities/market_creation_deploys_a_desk_only_for_non_mobile_models
    """
    production, performance, allocation = X.setup_released_allocation()
    _, purchase = X.setup_buyer(performance, allocation, quantity=1,
                                email="push_market_buyer@example.com")
    assert purchase["handoff_status"] == "NOT_REQUIRED", \
        f"a push market must not require a desk, got {purchase['handoff_status']}"
    assert purchase["handoff_token"] is None, \
        "a push market issues no handoff token"
    assert purchase["handoff_verified_at"] is None
    assert purchase["handoff_failed_at"] is None


def test_suspension_cascades_to_allocations_queues_and_holds(api):
    """PRD §3.1: "Every allocation of the partnership sitting in `RELEASED`
    moves to `SUSPENDED` and stops dispensing seats, and every queue position of
    the partnership's performances that is still `WAITING` moves to `ABANDONED`,
    because a queue that can no longer reach a sale should not hold its place.
    Holds are not left stranded either: every `HELD` `ALLOCATION` hold of those
    performances moves to `ORPHANED`, since a suspended partnership cannot keep
    inventory reserved."

    Design: Difficulty/transitive_cascade/transitive_cascade_production_suspension_depth_four
    """
    production, performance, allocation, hold, positions = \
        X.setup_suspension_cascade()

    X.suspend_production(production)

    refreshed = X.get_allocation(performance, allocation["id"])
    assert refreshed["status"] == "SUSPENDED", \
        f"hop 1: a released allocation must suspend with its partnership, got {refreshed['status']}"

    for position in positions:
        read = get_success_data(api.list_queue_positions(
            performance["id"], X.OPS, params={"limit": 100}))
        rows = read.get("data", read) if isinstance(read, dict) else read
        row = next(r for r in rows if r["id"] == position["id"])
        assert row["status"] == "ABANDONED", \
            f"hop 2: a waiting position must be abandoned, got {row['status']}"

    holds = get_success_data(api.list_seat_holds(
        performance["id"], X.OPS, params={"limit": 100}))
    hold_rows = holds.get("data", holds) if isinstance(holds, dict) else holds
    orphaned = next(h for h in hold_rows if h["id"] == hold["id"])
    assert orphaned["status"] == "ORPHANED", \
        f"hop 3: a held allocation hold must be orphaned, got {orphaned['status']}"


def test_suspension_advances_the_partnership_version_by_exactly_one(api):
    """PRD §3.1: "A partnership may cycle between `ACTIVE` and `SUSPENDED` any
    number of times before closure, and each crossing advances `version` by one."

    Design: Difficulty/transitive_cascade/transitive_cascade_production_suspension_depth_four
    """
    production, performance, allocation, hold, positions = \
        X.setup_suspension_cascade()
    before = X.live_production(production)["version"]

    suspended = X.suspend_production(production)

    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == before + 1, \
        f"expected one version advance from {before}, got {suspended['version']}"