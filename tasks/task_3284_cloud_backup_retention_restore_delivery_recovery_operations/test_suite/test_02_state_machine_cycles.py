"""Non-linear state machines: self-loops and rejection cycles."""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    ApiErrorId,
    GB_100,
    GB_200,
    GB_300,
    RETENTION,
    SYS,
    BACKUP,
    complete_initial,
    create_retention_request,
    begin_cooling_off,
    record_version,
    setup_active_set,
    setup_personal_scenario,
    group_version,
)


def test_active_backup_set_self_loop_records_incrementals_without_leaving_active():
    """PRD §3.3: "Once a set is `ACTIVE` it takes the incremental capture as a
    self-loop: each accepted change keeps the set `ACTIVE` while advancing
    `last_backup_at` to the change's `event_utc`."
    PRD §3.3: "The reported depth is the value after the final version, so a
    delete collapses the chain to zero and a later modify restarts it at one."

    Design: Difficulty/non_linear_state_machine/backup_set_active_self_loop_records_incrementals
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_100,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    activated = complete_initial(set_id)
    version_after_active = activated["version"]

    first = record_version(set_id, "/home/u/archive.tar", 2, "MODIFY", GB_200,
                           "sha256-arc-v2", "2026-09-20T00:00:00Z")
    second = record_version(set_id, "/home/u/archive.tar", 3, "MODIFY", GB_300,
                            "sha256-arc-v3", "2026-09-21T00:00:00Z")

    final = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert first["backup_set_id"] == set_id
    assert second["backup_set_id"] == set_id
    assert final["state"] == "ACTIVE"
    assert final["version_chain_depth"] == 3
    assert final["storage_gb"] == 300.0
    assert final["version"] == version_after_active + 2


def test_active_backup_set_self_loop_advances_the_agents_change_sequence():
    """PRD §3.3: "The agent's `last_change_sequence` is the highest
    `version_number` recorded across its sets."
    PRD §2.4: "`version`, an integer that begins at its creation value and
    increments by one on every accepted mutation."

    Design: Difficulty/non_linear_state_machine/backup_set_active_self_loop_records_incrementals
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    agent_id = scenario["agent"]["id"]
    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_100,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    after_initial = complete_initial(set_id)

    record_version(set_id, "/home/u/archive.tar", 2, "MODIFY", GB_200,
                   "sha256-arc-v2", "2026-09-20T00:00:00Z")
    after_incrementals = get_success_data(api.get_backup_set(set_id, BACKUP))
    agent = get_success_data(api.get_agent(agent_id, BACKUP))

    assert after_initial["state"] == "ACTIVE"
    assert after_incrementals["state"] == "ACTIVE"
    assert after_incrementals["version_chain_depth"] == 2
    assert agent["last_change_sequence"] == 2


def test_rejected_retention_request_returns_to_submitted_with_a_new_value():
    """PRD §3.4: "A rejected request does not have to be abandoned — a
    `RetentionOfficer` may resubmit it back to `SUBMITTED`, but only with a
    `requested_retention_days` that differs from the rejected value, since
    resubmitting the identical value is rejected with `ERR_DUPLICATE_REQUEST`;
    resubmission clears `cooling_off_until_utc`."
    PRD §3.4: "rejection instead reaches the terminal `REJECTED` state and
    leaves the group window untouched."

    Design: Difficulty/non_linear_state_machine/retention_change_rejected_then_resubmitted_cycle
    """
    scenario = setup_personal_scenario()
    group_id = scenario["group"]["id"]
    request = create_retention_request(scenario, requested_retention_days=700,
                                       reason_code="UPGRADE")
    cooling = begin_cooling_off(request["id"])
    assert cooling["state"] == "COOLING_OFF"

    rejected = get_success_data(api.reject_retention_change(request["id"], RETENTION))
    assert rejected["state"] == "REJECTED"

    duplicate = api.resubmit_retention_change(request["id"],
                                              {"requested_retention_days": 700}, RETENTION)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_REQUEST)

    still_rejected = get_success_data(api.get_retention_change_request(request["id"], RETENTION))
    assert still_rejected["state"] == "REJECTED"

    resubmitted = get_success_data(api.resubmit_retention_change(
        request["id"], {"requested_retention_days": 120}, RETENTION))
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["requested_retention_days"] == 120


def test_the_rejection_path_never_mutates_the_group_retention_window():
    """PRD §3.4: "rejection instead reaches the terminal `REJECTED` state and
    leaves the group window untouched."

    Design: Difficulty/non_linear_state_machine/retention_change_rejected_then_resubmitted_cycle
    """
    scenario = setup_personal_scenario()
    group_id = scenario["group"]["id"]

    request = create_retention_request(scenario, requested_retention_days=700,
                                       reason_code="UPGRADE")
    begin_cooling_off(request["id"])
    get_success_data(api.reject_retention_change(request["id"], RETENTION))
    get_success_data(api.resubmit_retention_change(
        request["id"], {"requested_retention_days": 120}, RETENTION))

    group = get_success_data(api.get_backup_group(group_id, RETENTION))
    assert group["group_retention_days"] == 45
    assert group["retention_days_override"] == 45