"""Build completion side effects, terminal lockdown, OCC, immediate consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_build_by_master,
    advance_build_payload,
    assert_build_stage_log,
    assert_instrument,
    create_apprentice,
    create_craftsman_set,
    get_build_order,
    get_success_data,
    list_instruments,
    make_apprentice_headers,
    make_master_craftsman_headers,
    setup_build_in_stage,
    setup_commissioned_build,
    setup_completed_instrument,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    validate_paginated,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_instrument_created_only_via_build_completion(api):
    """PRD section 3.2: "The advance into `COMPLETED` also mints the finished
    instrument: it starts in `SHOWROOM` with `condition_grade` `A`,
    `certified_authentic` true, the `model` copied from the order, a server-minted
    sequential `serial_number` in the format PIN-########".

    Design: Corner/entities/instrument_created_only_via_build_completion
    """
    ctx = setup_build_in_stage("MODEL_O", "VOICING")
    build_id = ctx["build"]["id"]
    rows, meta = validate_paginated(
        api.list_instruments(WM, params={"build_order_id": build_id})
    )
    assert meta["total_count"] == 0 and rows == []
    advance_build_by_master(ctx["build"], "COMPLETED", 160, ctx["craftsmen"]["VOICING"])
    rows, meta = validate_paginated(
        api.list_instruments(WM, params={"build_order_id": build_id})
    )
    assert meta["total_count"] == 1 and len(rows) == 1
    instrument = rows[0]
    assert_instrument(instrument)
    assert instrument["status"] == "SHOWROOM"
    assert instrument["condition_grade"] == "A"
    assert instrument["certified_authentic"] is True
    assert instrument["model"] == "MODEL_O"
    assert instrument["build_order_id"] == build_id


def test_build_completed_terminal_lockdown(api):
    """PRD section 3.2: the chain is fixed, "COMMISSIONED" through "COMPLETED", and
    "Asking for any target other than the legal next stage — skipping ahead, or
    repeating the current stage — is rejected"; a completed order has no legal next
    stage, so the rejection is one of the state/stage errors and nothing mutates.

    Design: Corner/state_machines/build_completed_terminal_lockdown
    """
    ctx = setup_completed_instrument("MODEL_O")
    build = get_build_order(ctx["build"]["id"])
    resp = api.advance_build_order(
        build["id"],
        advance_build_payload("VOICING", 5, build["version"]),
        make_master_craftsman_headers(ctx["craftsmen"]["VOICING"]["id"]),
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_BUILD_STAGE_INVALID]
    )
    after = get_build_order(build["id"])
    assert after["status"] == "COMPLETED"
    assert after["version"] == build["version"]
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert len(logs) == 5


def test_occ_stale_then_fresh_version(api):
    """PRD section 2.7: "If that value no longer matches the order's current
    `version` — because an earlier advance or a wood-reject rework cascade has
    already mutated the order since the caller's last read — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_then_fresh_version
    """
    craftsmen = create_craftsman_set()
    ctx = setup_commissioned_build("MODEL_B", craftsmen=craftsmen)
    build = ctx["build"]
    advanced = advance_build_by_master(build, "RIM_BENT", 100, craftsmen["RIM_BENDING"])
    assert advanced["version"] == build["version"] + 1
    stale = api.advance_build_order(
        build["id"],
        advance_build_payload("SEASONING", 30, build["version"]),
        make_master_craftsman_headers(craftsmen["SEASONING_CHECK"]["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    fresh = advance_build_by_master(advanced, "SEASONING", 30, craftsmen["SEASONING_CHECK"])
    assert fresh["status"] == "SEASONING"
    assert fresh["version"] == advanced["version"] + 1
    logs = validate_success(api.list_build_stage_logs(build["id"], WM), 200)
    assert len(logs) == 2
    for entry in logs:
        assert_build_stage_log(entry)


def test_immediate_visibility_after_advance(api):
    """PRD section 2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD section 2.5: "`version` (integer): a system-managed integer that increments
    by one on every mutation".

    Design: Corner/consistency_model/immediate_visibility_after_advance
    """
    cr_rim = create_craftsman_set()["RIM_BENDING"]
    reader = create_apprentice("Reading Apprentice")
    ctx = setup_commissioned_build("MODEL_O")
    build = ctx["build"]
    advanced = advance_build_by_master(build, "RIM_BENT", 100, cr_rim)
    assert advanced["status"] == "RIM_BENT"
    assert advanced["version"] == build["version"] + 1
    reread = get_success_data(
        api.get_build_order(build["id"], make_apprentice_headers(reader["id"]))
    )
    assert reread["status"] == "RIM_BENT"
    assert reread["version"] == advanced["version"]
