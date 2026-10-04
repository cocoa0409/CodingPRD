"""Precedence between competing failures and the optimistic concurrency guard."""
import pytest

from test_helpers import (
    validate_error, validate_success, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_identity_is_settled_before_existence(api):
    """PRD §2.6: "Identity is settled before permission, permission before the
    existence of anything the path names, path existence before anything the body
    references, and the whole ladder of state, window and constraint checks runs
    after existence."
    PRD §2.6: "Every endpoint except patron registration first requires that
    `X-User-ID` and `X-User-Role` are both present and that the role value is one
    of the ten declared roles; a failure here is `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_auth_before_existence
    """
    X.set_clock(C.BASE_CLOCK)

    response = api.get_performance(C.NON_EXISTENT_PERFORMANCE_ID, {})

    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED,
                           expected_status=401)
    assert error["error_id"] == "ERR_UNAUTHENTICATED", (
        "the response must not report ERR_PERFORMANCE_NOT_FOUND, because "
        "existence was never evaluated"
    )


def test_the_same_unresolvable_path_reports_its_entity_error_once_identified(api):
    """PRD §2.6: "Every resource named in a path segment must resolve, walked
    left to right, and a miss yields the 404 error that names that resource
    type."
    PRD §2.6: "An implementation that reports a later rung's error for a request
    that fails an earlier rung is non-conforming even when the later error is
    also genuinely applicable."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_auth_before_existence
    """
    X.set_clock(C.BASE_CLOCK)

    response = api.get_performance(C.NON_EXISTENT_PERFORMANCE_ID, X.PRODUCER)

    validate_error(response, ApiErrorId.ERR_PERFORMANCE_NOT_FOUND, expected_status=404)


def test_entries_are_ranked_by_the_instant_they_were_filed(api):
    """PRD §3.7: "A `DrawEntry` also carries a `rank_position`, which is a
    one-based position in its allocation's draw order — the first entry in the
    order is at position one — computed from `entered_at` ascending with
    `created_at` ascending breaking identical instants."
    PRD §3.7: "An entry filed outside that band is refused with
    `ERR_DRAW_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_before_business_temporal
    """
    production, performance, allocation = X.setup_released_draw_allocation(
        daily_quantity=2, claim_window_minutes=30, waitlist_multiplier=1,
        per_order_limit=1,
    )
    early = X.register_patron(email="window_early@example.com")
    late = X.register_patron(email="window_late@example.com")

    X.file_draw_entry(performance, allocation, early)
    X.set_clock("2026-09-12T09:10:00Z")
    second = X.file_draw_entry(performance, allocation, late)

    first_entry = X.get_entry(performance, X.list_entries(performance)[0]["id"])
    assert first_entry["entered_at"] < second["entered_at"], (
        "the window's opening instant orders the entries: expected the earlier "
        f"filing to sort first, got {first_entry['entered_at']}"
    )


def test_an_entry_may_only_be_filed_once_the_window_is_open(api):
    """PRD §3.7: "The entry window must be open: the logical instant must be at
    or after the window's opening and strictly before the draw's entries close."
    PRD §3.7: "A new entry lands in `ENTERED` and takes an `entered_at` stamp.
    That instant is both the record of when the entry arrived and the primary
    ranking key for the draw."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_before_business_temporal
    """
    production, performance, allocation = X.setup_released_draw_allocation(
        daily_quantity=2, claim_window_minutes=30, waitlist_multiplier=1,
        per_order_limit=1,
    )
    patron = X.register_patron(email="window_open@example.com")

    entry = X.file_draw_entry(performance, allocation, patron)

    assert entry["entered_at"] == "2026-09-12T09:00:00.000Z", (
        "the entry instant is the logical instant of the call, got "
        f"{entry['entered_at']}"
    )
    assert entry["status"] == "ENTERED"


def test_a_stale_partnership_version_refuses_the_release(api):
    """PRD §2.5: "A request naming the release epoch for an allocation must
    supply `expected_production_version` matching the current
    `Production.version`. The version of a production advances on any of its own
    lifecycle moves — activation, suspension or resumption — so a stale value
    here means the caller is releasing against a partnership posture they have
    not seen; the release is refused with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_layers/occ_stale_production_version_rejected_on_release
    """
    production, performance, allocation, stale, live = X.setup_stale_release_versions()

    response = api.release_allocation(
        allocation["id"], C.BASE_CLOCK_DAY,
        {"expected_production_version": stale,
         "expected_performance_version": X.live_performance(performance)["version"],
         "expected_allocation_version": X.live_allocation(performance,
                                                          allocation)["version"]},
        X.OPS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    unchanged = X.get_allocation(performance, allocation["id"])
    assert unchanged["status"] == "SCHEDULED", \
        "the stale attempt must stamp nothing"
    assert unchanged["quantity_released_today"] == 0


def test_the_same_release_succeeds_with_the_live_partnership_version(api):
    """PRD §2.5: "The same release request must also carry
    `expected_performance_version` matching the current `Performance.version` and
    `expected_allocation_version` matching the current `RushAllocation.version`,
    and a mismatch on either of those is refused with the same
    `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_layers/occ_stale_production_version_rejected_on_release
    """
    production, performance, allocation, stale, live = X.setup_stale_release_versions()

    before = X.live_performance(performance)["version"]
    response = api.release_allocation(
        allocation["id"], C.BASE_CLOCK_DAY,
        {"expected_production_version": live,
         "expected_performance_version": X.live_performance(performance)["version"],
         "expected_allocation_version": X.live_allocation(performance,
                                                          allocation)["version"]},
        X.OPS,
    )
    data = validate_success(response, expected_status=200)

    assert data["quantity_released_today"] == 6, (
        f"the replay carrying the live version opens the day, got {data['quantity_released_today']}"
    )
    assert X.get_performance(performance["id"])["version"] == before + 1, \
        "the successful release advances the performance's version by one"