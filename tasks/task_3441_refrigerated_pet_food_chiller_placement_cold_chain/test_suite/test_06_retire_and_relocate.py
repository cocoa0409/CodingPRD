"""Retire, relocate, and fleet conservation (PRD §2.11, §3.4, §3.6)."""
from test_helpers import (
    STORE_GAMMA,
    ApiErrorId,
    create_agreement,
    create_chiller,
    create_placement_payload,
    create_retire_relocate_payload,
    create_retire_remove_payload,
    create_service_ticket_payload,
    create_site_evaluation,
    create_store,
    evaluate_performance,
    get_chiller,
    get_placement,
    setup_active_placement,
    setup_signed_agreement,
    sign_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


def _drive_streak_two(placement_id, headers):
    evaluate_performance(placement_id, 30)
    return evaluate_performance(placement_id, 35)


def test_retire_cascade_returns_chiller_and_cancels_ticket(api, placement_manager_headers,
                                                           service_dispatcher_headers):
    """PRD §3.6: "Retirement stamps `retired_reason`, returns the chiller from
    `INSTALLED`, `ACTIVE`, or `NEEDS_REPAIR` to `IN_STOCK` (chiller `version`
    increments), cancels that chiller's `OPEN` and `DISPATCHED` tickets, and
    increments the placement's `version` as it lands in terminal `RETIRED`."

    Design: Difficulty/transitive_cascade/retire_cascade_returns_chiller_and_cancels_ticket
    """
    ctx = setup_active_placement()
    pid, cid = ctx["placement"]["id"], ctx["chiller"]["id"]
    resp = api.create_service_ticket(create_service_ticket_payload(cid, issue_summary="door gasket whistling"),
                                     service_dispatcher_headers)
    ticket = validate_success(resp, expected_status=201)
    assert ticket["origin"] == "MANUAL" and ticket["status"] == "OPEN"

    streak = _drive_streak_two(pid, placement_manager_headers)
    assert streak["underperforming_streak"] == 2, "precondition evidence: streak >= 2"

    resp = api.retire_placement(pid, create_retire_remove_payload(), placement_manager_headers)
    retired = validate_success(resp, expected_status=200)
    assert retired["status"] == "RETIRED"
    assert retired["retired_reason"] == "UNDERPERFORMANCE_REMOVAL"

    chiller = get_chiller(cid)
    assert chiller["status"] == "IN_STOCK", "hop 2: chiller returns to stock, caused by the retire"
    tickets = validate_success(api.list_service_tickets(cid, service_dispatcher_headers))
    assert tickets[0]["status"] == "CANCELLED", "hop 3: open ticket cancelled, caused by hop 2"


def test_retire_does_not_terminate_agreement(api, placement_manager_headers):
    """PRD §3.2: "Termination is available from `PROPOSED`, `SIGNED`, or
    `ACTIVE` and always lands in the terminal `TERMINATED` state with
    `terminated_at` stamped and `version` incremented."
    PRD §3.6: "the reason `UNDERPERFORMANCE_REMOVAL` is gated on evidence: the
    placement's `performance_status` must be `UNDERPERFORMING` with an
    `underperforming_streak` of at least 2, otherwise 409
    `ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT`."

    Design: Difficulty/transitive_cascade/retire_cascade_returns_chiller_and_cancels_ticket
    """
    ctx = setup_active_placement()
    pid = ctx["placement"]["id"]
    _drive_streak_two(pid, placement_manager_headers)
    resp = api.retire_placement(pid, create_retire_remove_payload(), placement_manager_headers)
    validate_success(resp, expected_status=200)

    listed = validate_success(api.list_placement_agreements(ctx["store"]["id"], placement_manager_headers))
    assert listed[0]["status"] == "ACTIVE", "placement retire is not agreement termination"
    assert listed[0]["terminated_at"] is None


def test_fleet_conserved_across_retire(api, placement_manager_headers, platform_admin_headers):
    """PRD §2.11: "First, fleet size changes only through batch registration of
    new chillers — never through installation, retirement, relocation,
    agreement termination, or decommissioning; decommissioning changes a
    chiller's status, not the count."
    PRD §2.11: "a removal followed by re-install of the same chiller likewise
    restores it (for a `STANDARD` unit, 240 units installed dropping to 0 and
    later returning to 240)."

    Design: Difficulty/compensating_invariant/chiller_fleet_conserved_across_retire_reinstall
    """
    ctx = setup_active_placement()
    pid, cid = ctx["placement"]["id"], ctx["chiller"]["id"]

    _, meta_all = validate_paginated(api.list_chillers(platform_admin_headers))
    assert meta_all["total_count"] == 1, "fleet size observable: one registered chiller"
    _, meta_inst = validate_paginated(api.list_chillers(platform_admin_headers, params={"status": "INSTALLED"}))
    assert meta_inst["total_count"] == 1, "installed capacity 240 (one INSTALLED STANDARD)"

    evaluate_performance(pid, 30)
    evaluate_performance(pid, 32)
    resp = api.retire_placement(pid, create_retire_remove_payload(), placement_manager_headers)
    validate_success(resp, expected_status=200)

    chiller = get_chiller(cid)
    assert chiller["status"] == "IN_STOCK"
    _, meta_all = validate_paginated(api.list_chillers(platform_admin_headers))
    assert meta_all["total_count"] == 1, "retire must not change the fleet count"
    _, meta_inst = validate_paginated(api.list_chillers(platform_admin_headers, params={"status": "INSTALLED"}))
    assert meta_inst["total_count"] == 0, "installed capacity dropped 240 -> 0"


def test_fleet_installed_capacity_restored_by_reinstall(api, placement_manager_headers,
                                                        platform_admin_headers):
    """PRD §2.11: "a removal followed by re-install of the same chiller
    likewise restores it (for a `STANDARD` unit, 240 units installed dropping
    to 0 and later returning to 240)."

    Design: Difficulty/compensating_invariant/chiller_fleet_conserved_across_retire_reinstall
    """
    ctx = setup_active_placement()
    pid, cid = ctx["placement"]["id"], ctx["chiller"]["id"]
    evaluate_performance(pid, 30)
    evaluate_performance(pid, 32)
    validate_success(api.retire_placement(pid, create_retire_remove_payload(), placement_manager_headers),
                     expected_status=200)
    assert get_chiller(cid)["status"] == "IN_STOCK"

    # Store Gamma is ready to receive the same chiller (ELIGIBLE + SIGNED).
    store_g, eval_g, agreement_g = setup_signed_agreement(store_payload=STORE_GAMMA)
    payload = create_placement_payload(store_g["id"], agreement_g["id"], cid, agreement_g["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    placement2 = validate_success(resp, expected_status=201)
    assert placement2["chiller_id"] == cid and placement2["store_id"] == store_g["id"]

    chiller = get_chiller(cid)
    assert chiller["status"] == "INSTALLED", "compensating re-install"
    _, meta_all = validate_paginated(api.list_chillers(platform_admin_headers))
    assert meta_all["total_count"] == 1, "fleet size never changed"
    _, meta_inst = validate_paginated(api.list_chillers(platform_admin_headers, params={"status": "INSTALLED"}))
    assert meta_inst["total_count"] == 1, "installed capacity restored to exactly 240"

    original = get_placement(pid)
    assert original["status"] == "RETIRED"
    assert original["retired_reason"] == "UNDERPERFORMANCE_REMOVAL"


def test_relocate_happy_path_moves_chiller_and_links_successor(api, placement_manager_headers):
    """PRD §3.6: "A relocation retires the old placement with `retired_reason`
    `RELOCATION`, creates a successor placement at the target store under the
    same `chiller_id` — born `ACTIVE`, `PENDING`, `OK` — and points the old
    placement's `relocated_to_placement_id` at the successor. The target
    agreement advances `SIGNED` to `ACTIVE`, the chiller passes logically
    through `IN_STOCK` and lands `INSTALLED` at the target with a single net
    `version` increment, and the chiller's open tickets are cancelled as in a
    plain removal."

    Design: Corner/state_machines/relocate_happy_path_moves_chiller_and_links_successor
    """
    ctx = setup_active_placement()
    pid, cid = ctx["placement"]["id"], ctx["chiller"]["id"]
    store_g, eval_g, agreement_g = setup_signed_agreement(store_payload=STORE_GAMMA)

    resp = api.retire_placement(pid, create_retire_relocate_payload(store_g["id"], agreement_g["id"]),
                                placement_manager_headers)
    retired = validate_success(resp, expected_status=200)
    assert retired["status"] == "RETIRED"
    assert retired["retired_reason"] == "RELOCATION"
    successor_id = retired["relocated_to_placement_id"]
    assert successor_id, "retire response must point at the successor placement"

    successor = validate_success(api.get_placement(successor_id, placement_manager_headers))
    assert successor["store_id"] == store_g["id"]
    assert successor["chiller_id"] == cid, "successor reuses the same chiller"
    assert successor["status"] == "ACTIVE"
    assert successor["performance_status"] == "PENDING"
    assert successor["operational_status"] == "OK"
    assert successor["installed_quote_cents"] == 408500, "recomputed: 325000 + 45000 + 20000 + 20*925"

    chiller = get_chiller(cid)
    assert chiller["status"] == "INSTALLED", "chiller lands INSTALLED at the target"

    listed = validate_success(api.list_placement_agreements(store_g["id"], placement_manager_headers))
    assert listed[0]["status"] == "ACTIVE", "target agreement SIGNED -> ACTIVE on relocation install"

    data, meta = validate_paginated(
        api.list_placements(placement_manager_headers, params={"relocated_to_placement_id": successor_id})
    )
    assert meta["total_count"] == 1 and data[0]["id"] == pid, "self-FK reverse reachability"


def test_retire_relocate_same_store_returns_422(api, placement_manager_headers):
    """PRD §3.6: "Under `mode` `RELOCATE`, the caller supplies `target_store_id`
    and `target_agreement_id`. The target store must differ from the
    placement's current store (otherwise 422 `ERR_RETIRE_TARGET_INVALID`); ..."

    Design: Corner/errors/retire_relocate_same_store_returns_422
    """
    ctx = setup_active_placement()
    store = ctx["store"]
    pid = ctx["placement"]["id"]
    agreement2 = sign_agreement(create_agreement(store["id"], term_months=48)["id"])

    resp = api.retire_placement(pid, create_retire_relocate_payload(store["id"], agreement2["id"]),
                                placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_RETIRE_TARGET_INVALID)
    assert resp.status_code == 422, "target store equals the current store"

    placement = get_placement(pid)
    assert placement["status"] == "ACTIVE"
    assert get_chiller(ctx["chiller"]["id"])["status"] == "INSTALLED"
