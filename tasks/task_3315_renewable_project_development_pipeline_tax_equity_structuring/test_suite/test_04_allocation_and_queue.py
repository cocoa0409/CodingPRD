"""Interconnection allocation arithmetic, withdrawal cascade, and the
queue-position permutation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_interconnection_request,
    create_project,
    get_success_data,
    validate_error,
)


def _get_request(api, request_id, headers):
    return get_success_data(api.get_interconnection_request(request_id, headers))


def test_upgrade_allocation_remainder_to_earliest_created(
    api, developer_admin_headers, origination_manager_headers, platform_admin_headers
):
    """PRD §3.2: "If the rounded shares sum to less or more than the total, the
    remainder — the total minus the sum of the shares — is added to the share
    of the pool request with the largest `requested_capacity_mw`, breaking ties
    by earliest `created_at` and never by id. Every request in the pool then
    has `upgrade_allocated` set to true and `last_upgrade_total_usd` set to the
    supplied total."

    Design: Corner/calculations/upgrade_allocation_remainder_to_earliest_created
    """
    ps = [create_project(name=f"Rem Farm {i}", technology="SOLAR",
                         target_capacity_mw=1, resource_class="C")
          for i in (1, 2, 3)]
    rs = [create_interconnection_request(p["id"], "CL-R", 1) for p in ps]
    # Allocation callable via any cluster member.
    get_success_data(
        api.allocate_upgrade_costs(rs[1]["id"], {"total_upgrade_cost_usd": 100.00},
                                   platform_admin_headers)
    )
    shares = [_get_request(api, r["id"], origination_manager_headers) for r in rs]
    # 100.00 / 3 = 33.33 each; +0.01 remainder to earliest created (rs[0]).
    assert shares[0]["upgrade_cost_share_usd"] == pytest.approx(33.34, abs=0.001)
    assert shares[1]["upgrade_cost_share_usd"] == pytest.approx(33.33, abs=0.001)
    assert shares[2]["upgrade_cost_share_usd"] == pytest.approx(33.33, abs=0.001)
    total = sum(s["upgrade_cost_share_usd"] for s in shares)
    assert total == pytest.approx(100.00, abs=0.001)
    for s in shares:
        assert s["upgrade_allocated"] is True
        assert s["last_upgrade_total_usd"] == pytest.approx(100.00, abs=0.001)


def test_withdrawal_reseat_reallocation_chain(
    api, developer_admin_headers, origination_manager_headers, platform_admin_headers
):
    """PRD §3.2: "First, the withdrawn request's `queue_position` is set to 0.
    Second, the cluster reseats: every non-`WITHDRAWN` request in the same
    cluster whose position was greater than the withdrawn position is
    decremented by one ... Third, the reseat itself triggers a recomputation
    of upgrade cost shares across the remaining non-`WITHDRAWN` cluster
    requests using the mirrored `last_upgrade_total_usd`".
    PRD §3.2: "Each request's `upgrade_cost_share_usd` is the total upgrade
    cost multiplied by its `requested_capacity_mw` and divided by the sum of
    `requested_capacity_mw` across the pool, rounded half-up to 2 decimal
    places".

    Design: Difficulty/transitive_cascade/withdrawal_reseat_reallocation_chain
    """
    p1 = create_project(name="Q1", target_capacity_mw=60)
    p2 = create_project(name="Q2", target_capacity_mw=100)
    p3 = create_project(name="Q3", technology="SOLAR", target_capacity_mw=150,
                        resource_class="B")
    r1 = create_interconnection_request(p1["id"], "CL-Q", 60)
    r2 = create_interconnection_request(p2["id"], "CL-Q", 100)
    r3 = create_interconnection_request(p3["id"], "CL-Q", 150)
    assert r1["queue_position"] == 1
    get_success_data(
        api.allocate_upgrade_costs(r1["id"], {"total_upgrade_cost_usd": 900000},
                                   platform_admin_headers)
    )
    # 900000 * cap / 310, rounded half-up; remainder +0.01 to largest (150 MW).
    assert _get_request(api, r1["id"], origination_manager_headers)["upgrade_cost_share_usd"] == pytest.approx(174193.55, abs=0.001)
    assert _get_request(api, r2["id"], origination_manager_headers)["upgrade_cost_share_usd"] == pytest.approx(290322.58, abs=0.001)
    assert _get_request(api, r3["id"], origination_manager_headers)["upgrade_cost_share_usd"] == pytest.approx(435483.87, abs=0.001)

    get_success_data(
        api.transition_interconnection_request(r1["id"], {"to": "WITHDRAWN"},
                                               origination_manager_headers)
    )
    r1_now = _get_request(api, r1["id"], origination_manager_headers)
    r2_now = _get_request(api, r2["id"], origination_manager_headers)
    r3_now = _get_request(api, r3["id"], origination_manager_headers)
    assert r1_now["status"] == "WITHDRAWN"
    assert r1_now["queue_position"] == 0
    # Historical share preserved on the withdrawn request.
    assert r1_now["upgrade_cost_share_usd"] == pytest.approx(174193.55, abs=0.001)
    # Reseat + re-allocation over the remaining 250 MW pool.
    assert r2_now["queue_position"] == 1
    assert r3_now["queue_position"] == 2
    assert r2_now["upgrade_cost_share_usd"] == pytest.approx(360000.00, abs=0.001)
    assert r3_now["upgrade_cost_share_usd"] == pytest.approx(540000.00, abs=0.001)


def test_withdrawal_reseat_skips_reallocation_when_no_allocation_run(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "Third, the reseat itself triggers a recomputation of upgrade
    cost shares across the remaining non-`WITHDRAWN` cluster requests using the
    mirrored `last_upgrade_total_usd` — this recomputation is skipped when
    `last_upgrade_total_usd` is 0".

    Design: Difficulty/transitive_cascade/withdrawal_reseat_reallocation_chain
    """
    p1 = create_project(name="NoAlloc Q1", target_capacity_mw=50)
    p2 = create_project(name="NoAlloc Q2", target_capacity_mw=70)
    r1 = create_interconnection_request(p1["id"], "CL-QNA", 50)
    r2 = create_interconnection_request(p2["id"], "CL-QNA", 70)
    get_success_data(
        api.transition_interconnection_request(r1["id"], {"to": "WITHDRAWN"},
                                               origination_manager_headers)
    )
    r1_now = _get_request(api, r1["id"], origination_manager_headers)
    r2_now = _get_request(api, r2["id"], origination_manager_headers)
    assert r1_now["queue_position"] == 0
    # Reseat still runs; re-allocation skipped (last_upgrade_total_usd == 0).
    assert r2_now["queue_position"] == 1
    assert r2_now["upgrade_allocated"] is False
    assert r2_now["last_upgrade_total_usd"] == 0.0


def test_queue_position_permutation_conserved(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "the cluster reseats: every non-`WITHDRAWN` request in the
    same cluster whose position was greater than the withdrawn position is
    decremented by one, processed in ascending `queue_position` order, so that
    after the reseat the positions of the remaining non-`WITHDRAWN` requests
    are exactly the consecutive integers from 1 up to the count of remaining
    requests."
    PRD §3.2: "its `queue_position` is assigned as one more than the highest
    position among non-`WITHDRAWN` requests in the same cluster — or 1 when the
    cluster is empty."

    Design: Difficulty/compensating_invariant/queue_position_permutation_conserved
    """
    ps = [create_project(name=f"Perm Farm {i}", target_capacity_mw=40 + 10 * i)
          for i in (1, 2, 3, 4)]
    r1 = create_interconnection_request(ps[0]["id"], "CL-I", 50)
    r2 = create_interconnection_request(ps[1]["id"], "CL-I", 60)
    r3 = create_interconnection_request(ps[2]["id"], "CL-I", 70)
    get_success_data(
        api.transition_interconnection_request(r1["id"], {"to": "WITHDRAWN"},
                                               origination_manager_headers)
    )
    after = [
        _get_request(api, r["id"], origination_manager_headers) for r in (r1, r2, r3)
    ]
    assert after[0]["queue_position"] == 0
    assert sorted(x["queue_position"] for x in after[1:]) == [1, 2]
    # Compensating creation takes max active + 1 over the compacted set.
    r4 = create_interconnection_request(ps[3]["id"], "CL-I", 40)
    assert r4["queue_position"] == 3
    active = [x["queue_position"] for x in
              (_get_request(api, r["id"], origination_manager_headers) for r in (r2, r3, r4))]
    assert sorted(active) == [1, 2, 3]


def test_queue_position_first_request_in_empty_cluster(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "its `queue_position` is assigned as one more than the highest
    position among non-`WITHDRAWN` requests in the same cluster — or 1 when the
    cluster is empty."

    Design: Difficulty/compensating_invariant/queue_position_permutation_conserved
    """
    p1 = create_project(name="Empty Q1", target_capacity_mw=10)
    p2 = create_project(name="Empty Q2", target_capacity_mw=20)
    r1 = create_interconnection_request(p1["id"], "CL-E", 10)
    r2 = create_interconnection_request(p2["id"], "CL-E", 20)
    assert r1["queue_position"] == 1
    assert r2["queue_position"] == 2
    get_success_data(
        api.transition_interconnection_request(r1["id"], {"to": "WITHDRAWN"},
                                               origination_manager_headers)
    )
    get_success_data(
        api.transition_interconnection_request(r2["id"], {"to": "WITHDRAWN"},
                                               origination_manager_headers)
    )
    p3 = create_project(name="Empty Q3", target_capacity_mw=30)
    r3 = create_interconnection_request(p3["id"], "CL-E", 30)
    # All prior requests withdrawn: the cluster is empty again.
    assert r3["queue_position"] == 1


def test_withdrawn_request_cannot_advance(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "Withdrawing an interconnection request is permitted from any
    status other than `IN_SERVICE` or `WITHDRAWN` itself (an attempt from
    either of those fails with `ERR_INVALID_STATE`)."
    PRD §3.2: "First, the withdrawn request's `queue_position` is set to 0."

    Design: Corner/state_machines/withdrawn_request_cannot_advance
    """
    p = create_project(name="Lock Farm", target_capacity_mw=40)
    r = create_interconnection_request(p["id"], "CL-L", 40)
    get_success_data(
        api.transition_interconnection_request(r["id"], {"to": "WITHDRAWN"},
                                               origination_manager_headers)
    )
    resp = api.transition_interconnection_request(
        r["id"], {"to": "FEASIBILITY_STUDY"}, origination_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = _get_request(api, r["id"], origination_manager_headers)
    assert current["queue_position"] == 0
