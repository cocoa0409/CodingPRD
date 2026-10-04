"""Remaining breadth: occupancy mounting, the two entry gates, and receipt shape."""
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
    declare_patronization_record,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_a_host_that_requires_self_containment_refuses_a_bare_rig(api):
    """PRD §3.1: "the host may not declare `self_contained_required` as false" and
    "`self_contained_required` defaults to true, meaning members must arrive in rigs
    that carry their own water, waste and power."
    PRD §3.4: "a host that requires self-contained rigs refuses a request whose rig
    does not carry the self-contained flag or does not have an inspection record on
    file, with `ERR_VEHICLE_NOT_SELF_CONTAINED` (HTTP 422)."

    Design: Corner/errors/self_containment_gate_rejects_a_non_contained_rig
    """
    set_clock("2026-06-01T00:00:00Z")
    strict = declare_host(category="WINERY", state_code="CA",
                          self_contained_required=True)
    declare_sites(strict["id"], 1, labels=["S1"])
    approve_host(strict["id"])

    parts = setup_basic_scenario(site_count=1)
    member = parts["member"]
    # The rig is declared with the self-containment flag false.
    bare = validate_success(
        api.create_vehicle(
            member["id"],
            {"vehicle_class": "CONVERSION_VAN", "length_feet": 22,
             "self_contained": False, "inspection_state_code": "TX"},
            make_member_headers(member["id"]),
        ),
        201,
    )
    resp = try_file_stay(strict["id"], member["id"], bare["id"],
                         arrival_date="2026-06-20", nights=2)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_SELF_CONTAINED, 422)


def test_a_tolerant_host_admits_the_same_bare_rig(api):
    """PRD §2.11: "A host whose `state_code` and `category` pair appears in no profile
    is uncapped and is not forced to require self-contained rigs"
    PRD §3.4: "a host that requires self-contained rigs refuses a request whose rig
    does not carry the self-contained flag"

    Design: Corner/errors/self_containment_gate_rejects_a_non_contained_rig
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1, self_contained_required=False)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    bare = validate_success(
        api.create_vehicle(
            member_id,
            {"vehicle_class": "CONVERSION_VAN", "length_feet": 22,
             "self_contained": False, "inspection_state_code": "TX"},
            make_member_headers(member_id),
        ),
        201,
    )
    admitted = file_stay(host_id, member_id, bare["id"],
                         arrival_date="2026-06-20", nights=2)
    assert admitted["request_status"] == "REQUESTED"

    rigs = validate_success(
        api.list_vehicles(member_id, make_member_headers(member_id))
    )
    bare_row = [r for r in rigs if r["id"] == bare["id"]][0]
    assert bare_row["self_contained"] is False, (
        "the tolerance came from the host declaration and not from a vehicle mutation"
    )

    stays = validate_success(
        api.list_stay_requests(
            make_member_headers(member_id),
            {"member_id": member_id, "limit": 50, "offset": 0},
        )
    )
    assert len(stays) == 1, "only the accepted request exists"