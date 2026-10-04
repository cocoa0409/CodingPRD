"""Capacity bases: the base basis, the live basis, and the two occupancy bases."""
import pytest

from test_helpers import validate_success
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_active_member,
    file_stay,
    confirm_stay,
    read_capacity_summary,
    read_host,
    declare_window,
    set_clock,
    host_version,
    make_host_operator_headers,
)


def _declare_tx_farm_with_sites(count, state_code="TX", category="FARM"):
    """A TX host with `count` active sites; the first carries a pedestal so the
    onboarding decision's amenity test can pass."""
    host = declare_host(category=category, state_code=state_code,
                        self_contained_required=False)
    sites = declare_sites(
        host["id"], count,
        labels=[f"S{i + 1}" for i in range(count)],
        site_class="PULL_THROUGH",
        max_vehicle_length_feet=40,
        has_electric=(count > 0),
        electric_service_code="ELECTRIC_30A" if count else "NONE",
    )
    return host, sites


def test_public_card_bases_diverge_while_a_first_round_request_is_outstanding(api):
    """PRD §3.9: "A host's live capacity read reports which basis is currently in
    force through `capacity_basis`, the physical active-site count as
    `base_capacity`, the current `effective_capacity`, the occupancy figure under
    each of the two bases as `committed_sites_reserved_basis` and
    `committed_sites_occupied_basis`, the resulting `free_sites`, the identifier
    and member ceiling of the window currently in force as `active_window_id` and
    `active_window_member_ceiling`, the `latest_checkout_at` edge, and the derived
    `posture`."
    PRD §3.9: "A degree of divergence between the two occupancy figures is expected
    whenever first-round requests are outstanding, since the reserved basis counts
    them and the occupied basis does not."

    Design: Difficulty/dual_variant_calc/capacity_basis_reserved_vs_occupied_on_host
    """
    host, sites = _declare_tx_farm_with_sites(8)
    host = approve_host(host["id"])
    assert host["onboarding_status"] == "APPROVED"
    member, vehicle = setup_active_member(plan_tier="PLUS", home_state_code="TX")

    # A first-round request holds the site before the host has answered.
    file_stay(
        host["id"], member["id"], vehicle["id"],
        arrival_date="2026-09-10", nights=2, request_depth=0,
    )

    summary = validate_success(
        api.get_host_capacity_summary(host["id"], make_host_operator_headers(host["id"]))
    )
    assert summary["capacity_basis"] == "base"
    assert summary["base_capacity"] == 8
    assert summary["committed_sites_reserved_basis"] == 1, (
        "a first-round REQUESTED request holds a site on the reserved basis"
    )
    assert summary["committed_sites_occupied_basis"] == 0, (
        "the occupied basis counts only CONFIRMED and CHECKED_IN stays"
    )
    assert summary["free_sites"] == 7
    assert summary["posture"] == "OPEN"


def test_confirming_the_outstanding_request_moves_only_the_occupied_basis(api):
    """PRD §2.4: "the **reserved basis** counts `CONFIRMED` stays plus first-round
    `REQUESTED` requests (so a request at `request_depth` 0 already holds a site
    before the host has answered), while the **occupied basis** used for a host's
    public card counts only stays whose `request_status` is `CONFIRMED` or
    `CHECKED_IN`."

    Design: Difficulty/dual_variant_calc/capacity_basis_reserved_vs_occupied_on_host
    """
    host, sites = _declare_tx_farm_with_sites(8)
    approve_host(host["id"])
    member, vehicle = setup_active_member(plan_tier="PLUS", home_state_code="TX")
    stay = file_stay(
        host["id"], member["id"], vehicle["id"],
        arrival_date="2026-09-10", nights=2, request_depth=0,
    )

    before = read_capacity_summary(host["id"])
    stay = confirm_stay(host["id"], stay["id"], site_label="S1")
    assert stay["request_status"] == "CONFIRMED"
    after = read_capacity_summary(host["id"])

    assert before["committed_sites_reserved_basis"] == 1
    assert after["committed_sites_reserved_basis"] == 1, (
        "confirmation moved the request from the first-round hold to a CONFIRMED "
        "stay without changing the reserved basis"
    )
    assert before["committed_sites_occupied_basis"] == 0
    assert after["committed_sites_occupied_basis"] == 1, (
        "the occupied basis picks up the confirmation"
    )


def test_active_event_window_replaces_the_physical_site_count_as_the_basis(api):
    """PRD §2.4: "When exactly one availability window of the host is active,
    capacity runs on the **live basis**: `effective_capacity` equals that window's
    `capacity_override` minus its `reserved_sites`, floored at zero."
    PRD §2.13: "From these the platform derives `member_capacity_ceiling`, the live
    capacity basis while the window is `ACTIVE`: it is the window's
    `capacity_override` minus its `reserved_sites`, floored at zero."

    Design: Difficulty/dual_variant_calc/capacity_basis_base_sites_vs_active_window_override
    """
    set_clock("2026-10-02T00:00:00Z")
    host = declare_host(category="ATTRACTION", state_code="TX",
                        self_contained_required=False)
    declare_sites(
        host["id"], 3, labels=["A1", "A2", "A3"], site_class="PULL_THROUGH",
        max_vehicle_length_feet=45, has_electric=True,
        electric_service_code="ELECTRIC_30A",
    )
    approve_host(host["id"])
    window = declare_window(
        host["id"], kind="EVENT", label="Fall Festival",
        start_date="2026-10-01", end_date="2026-10-15",
        capacity_override=20, reserved_sites=15,
    )
    assert window["window_status"] == "ACTIVE"
    member, vehicle = setup_active_member(plan_tier="CLASSIC", home_state_code="TX")
    for arrival in ("2026-10-05", "2026-10-08", "2026-10-11"):
        file_stay(host["id"], member["id"], vehicle["id"],
                  arrival_date=arrival, nights=2, request_depth=0)

    summary = validate_success(
        api.get_host_capacity_summary(host["id"], make_host_operator_headers(host["id"]))
    )
    assert summary["capacity_basis"] == "live"
    assert summary["active_window_id"] == window["id"]
    assert summary["base_capacity"] == 3, "the physical count is still reported"
    assert summary["effective_capacity"] == 5, (
        "20 - 15 = 5 on the live basis, ignoring the three physical sites"
    )
    assert summary["active_window_member_ceiling"] == 5
    assert summary["free_sites"] == 2
    assert summary["posture"] == "OPEN"


def test_window_declared_ahead_of_its_dates_leaves_the_base_basis_in_force(api):
    """PRD §2.13: "A window's `window_status` is `SCHEDULED` when it is declared
    ahead of its dates, becomes `ACTIVE` when the logical clock reaches its
    `start_date`, and is `CANCELLED` when it is withdrawn or superseded."

    Design: Difficulty/dual_variant_calc/capacity_basis_base_sites_vs_active_window_override
    """
    set_clock("2026-09-15T00:00:00Z")
    host = declare_host(category="ATTRACTION", state_code="TX",
                        self_contained_required=False)
    declare_sites(
        host["id"], 3, labels=["A1", "A2", "A3"], site_class="PULL_THROUGH",
        max_vehicle_length_feet=45, has_electric=True,
        electric_service_code="ELECTRIC_30A",
    )
    approve_host(host["id"])
    window = declare_window(
        host["id"], kind="EVENT", label="Future Festival",
        start_date="2026-10-01", end_date="2026-10-15",
        capacity_override=20, reserved_sites=15,
    )
    assert window["window_status"] == "SCHEDULED"

    summary = read_capacity_summary(host["id"])
    assert summary["capacity_basis"] == "base"
    assert summary["effective_capacity"] == 3, (
        "a SCHEDULED window is never consulted and the base site count stands"
    )
    assert summary["active_window_id"] is None
    assert summary["free_sites"] == 3