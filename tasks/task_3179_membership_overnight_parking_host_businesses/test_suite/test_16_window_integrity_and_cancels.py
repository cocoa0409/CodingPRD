"""Remaining breadth: the stay-request junction, window integrity, and cancels."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_basic_scenario,
    setup_confirmed_stay,
    file_stay,
    confirm_stay,
    decline_stay,
    try_file_stay,
    read_stay,
    read_capacity_summary,
    read_host,
    resolve_site_id,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_a_window_whose_override_is_below_its_reserved_sites_is_refused(api):
    """PRD §2.13: "The integrity of a window is checked on declaration and on
    amendment: `capacity_override` must be at least `reserved_sites`, and `end_date`
    must be strictly after `start_date`, with a violation reported as
    `ERR_WINDOW_CAPACITY_BELOW_RESERVED` (HTTP 422)."

    Design: Corner/endpoints/capacity_summary_computed_read_matches_its_underlying_counters
    """
    set_clock("2026-06-01T00:00:00Z")
    host = declare_host()
    declare_sites(host["id"], 1, labels=["K1"], has_electric=True,
                  electric_service_code="ELECTRIC_30A")
    approve_host(host["id"])

    resp = api.create_window(
        {"host_id": host["id"], "kind": "EVENT", "label": "Bad Window",
         "start_date": "2026-06-01", "end_date": "2026-06-20",
         "capacity_override": 5, "reserved_sites": 9},
        make_host_operator_headers(host["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_BELOW_RESERVED, 422)


def test_a_window_ending_before_it_starts_is_refused(api):
    """PRD §2.13: "an inclusive `start_date` and an exclusive `end_date` that must
    fall strictly after the start date"
    PRD §2.13: "`end_date` must be strictly after `start_date`, with a violation
    reported as `ERR_WINDOW_CAPACITY_BELOW_RESERVED` (HTTP 422)."

    Design: Corner/endpoints/capacity_summary_computed_read_matches_its_underlying_counters
    """
    set_clock("2026-06-01T00:00:00Z")
    host = declare_host()
    declare_sites(host["id"], 1, labels=["K1"], has_electric=True,
                  electric_service_code="ELECTRIC_30A")
    approve_host(host["id"])

    resp = api.create_window(
        {"host_id": host["id"], "kind": "SEASONAL", "label": "Inverted Window",
         "start_date": "2026-06-20", "end_date": "2026-06-20",
         "capacity_override": 5, "reserved_sites": 1},
        make_host_operator_headers(host["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_BELOW_RESERVED, 422)


def test_cancelling_an_active_window_recomputes_the_host_capacity_arithmetic(api):
    """PRD §3.2: "A window that is no longer wanted — whether still `SCHEDULED` or
    already `ACTIVE` — is `CANCELLED`, and if it was active the host's capacity
    arithmetic is recomputed once more."

    Design: Corner/cross_cutting_layers/window_activation_cascade_gates_stay_requests_through_host_posture
    """
    set_clock("2026-10-05T00:00:00Z")
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 6, labels=[f"S{i + 1}" for i in range(6)])
    approve_host(host["id"])
    window = validate_success(
        api.create_window(
            {"host_id": host["id"], "kind": "EVENT", "label": "Festival",
             "start_date": "2026-10-01", "end_date": "2026-10-20",
             "capacity_override": 30, "reserved_sites": 24},
            make_host_operator_headers(host["id"]),
        ),
        201,
    )
    live = read_capacity_summary(host["id"])
    assert live["capacity_basis"] == "live"
    assert live["effective_capacity"] == 6, (
        "30 - 24 = 6 on the live basis, replacing the physical site count"
    )

    validate_success(
        api.cancel_window(window["id"], make_host_operator_headers(host["id"]))
    )
    after = read_capacity_summary(host["id"])
    assert after["capacity_basis"] == "base"
    assert after["effective_capacity"] == 6, (
        "the physical count of six sites is restored as the basis"
    )
    assert after["active_window_id"] is None


def test_a_decline_advances_the_request_depth_exactly_once(api):
    """PRD §3.4: "it advances `request_depth` to exactly 1 on this response — that is
    the mechanism that admits the member's later counter-request exactly once."
    PRD §3.4: "On a decline the request moves to `DECLINED`, the host's occupancy is
    recomputed, and the member's `standing_score`, `strike_count`,
    `total_stays_completed` and `guest_passes_remaining` are all recomputed in the same
    pass."

    Design: Corner/entity_topology/stay_request_references_span_four_peer_entities
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    stay = file_stay(host_id, member_id, parts["vehicle"]["id"],
                     arrival_date="2026-06-20", nights=2)
    before = read_capacity_summary(host_id)
    assert before["committed_sites_reserved_basis"] == 1

    declined = decline_stay(host_id, stay["id"])
    assert declined["request_status"] == "DECLINED"
    assert declined["request_depth"] == 1

    after = read_capacity_summary(host_id)
    assert after["committed_sites_reserved_basis"] == 0, (
        "a DECLINED stay never counts toward the occupancy"
    )
    assert after["free_sites"] == 2


def test_cancelling_a_first_round_request_is_free_of_consequence(api):
    """PRD §3.5: "A request still sitting at `REQUESTED` may be withdrawn by the
    member who owns it, moving to `CANCELLED` with no charge, no depth advance and no
    conduct consequence; only the host's `committed_sites` and `free_sites` are
    recomputed, since a first-round request was holding a site."

    Design: Corner/cross_cutting_layers/capacity_and_posture_changes_are_visible_in_the_same_request
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    stay = file_stay(host_id, member_id, parts["vehicle"]["id"],
                     arrival_date="2026-06-20", nights=2)
    assert read_capacity_summary(host_id)["committed_sites_reserved_basis"] == 1

    cancelled = validate_success(
        api.cancel_stay_request(stay["id"], make_member_headers(member_id))
    )
    assert cancelled["request_status"] == "CANCELLED"
    assert cancelled["request_depth"] == 0, "no depth advance on a first-round withdraw"
    assert cancelled["cancellation_fee_cents"] == 0

    assert read_capacity_summary(host_id)["committed_sites_reserved_basis"] == 0


def test_the_two_occupancy_bases_move_together_on_the_same_read(api):
    """PRD §2.5: "Recomputation counts as mutation. Whenever a rule in this document
    recomputes a derived field on a resource — capacity, posture, a rating average, a
    standing score, a guest-pass pool — that write refreshes the resource's
    `updated_at` and increments its `version`."
    PRD §2.4: "`committed_sites` is simply the count of the host's stays whose
    `count_toward_capacity` is true."

    Design: Corner/cross_cutting_layers/capacity_and_posture_changes_are_visible_in_the_same_request
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2, labels=["N1", "N2"])
    host_id = parts["host"]["id"]
    stay = file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
                     arrival_date="2026-06-20", nights=2)

    pre = read_capacity_summary(host_id)
    assert pre["committed_sites_occupied_basis"] == 0
    assert pre["committed_sites_reserved_basis"] == 1, (
        "a first-round request already held the reservation"
    )
    assert pre["free_sites"] == 1
    assert pre["posture"] == "LIMITED", (
        "one free site of two sits inside the ceiling of the rounded-up band "
        "ceil(2 * 0.20) = 1, and the band comparison is inclusive"
    )

    confirmed = confirm_stay(host_id, stay["id"], site_label="N1")
    assert confirmed["confirmed_site_id"] is not None

    post = read_capacity_summary(host_id)
    assert post["committed_sites_occupied_basis"] == 1, (
        "the occupied basis moves on the immediately following read, with no lag"
    )
    assert post["committed_sites_reserved_basis"] == 1
    assert post["free_sites"] == 1, "the host has two sites"
    assert post["posture"] == "LIMITED"
    assert read_host(host_id)["committed_sites"] == post[
        "committed_sites_reserved_basis"
    ]