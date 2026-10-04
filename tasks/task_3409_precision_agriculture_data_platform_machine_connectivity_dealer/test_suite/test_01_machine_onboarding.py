"""Machine registration, provisioning basics, and the onboarding walk from
OFFLINE to IN_SERVICE."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SYSTEM,
    activate_plan,
    add_machine,
    begin_provisioning,
    create_machine_payload,
    create_plan,
    ingest_batch,
    provision_modem_success,
    read_machine,
    setup_activated_machine,
    setup_org_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_machine_create_ignores_smuggled_system_fields(api):
    """PRD section 3.1: "A new machine starts with `lifecycle_status` `REGISTERED`,
    `modem_status` `UNPROVISIONED`, `connectivity_posture` `OFFLINE`,
    `provisioning_attempts` 0, `active_license_count` 0, and
    `activating_dealer_id`, `activated_at`, and `modem_firmware_version` all
    null." A create body that smuggles system-managed fields is accepted as a
    normal registration and the server-side initial state wins.

    Design: Corner/entities/machine_create_system_fields_input_ignored
    """
    ctx = setup_org_dealer(api)
    payload = create_machine_payload(
        ctx["org"]["id"],
        ctx["dealer"]["id"],
        serial_number="SN-0001-SMUGGLED",
        modem_imei="IMEI-0001-SMUGGLED",
        lifecycle_status="IN_SERVICE",
        modem_status="PROVISIONED",
        connectivity_posture="CONNECTED",
        version=99,
    )
    response = api.create_machine(payload, headers=ctx["grower_headers"])
    machine = validate_success(response, 201)
    assert machine["lifecycle_status"] == "REGISTERED"
    assert machine["modem_status"] == "UNPROVISIONED"
    assert machine["connectivity_posture"] == "OFFLINE"
    assert machine["version"] == 1
    assert machine["provisioning_attempts"] == 0
    assert machine["active_license_count"] == 0
    assert machine["activating_dealer_id"] is None
    assert machine["activated_at"] is None
    assert machine["modem_firmware_version"] is None


def test_machine_get_with_unknown_id_returns_not_found(api):
    """PRD section 2.10: "**Existence** — path identifiers are resolved left to
    right, then body foreign keys in the endpoint's declared input order; the
    first missing resource yields `ERR_NOT_FOUND` (HTTP 404)." PRD section 2.2:
    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/machine_get_with_unknown_id_returns_not_found
    """
    ctx = setup_org_dealer(api)
    response = api.get_machine(NON_EXISTENT_UUID, headers=ctx["grower_headers"])
    error = validate_error(response, ApiErrorId.ERR_NOT_FOUND)
    assert error["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"]
    body = response.json()
    assert body["response_type"] == "error"


def test_machines_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned: it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100. The `offset` parameter specifies how many items
    to skip and defaults to 0." and "Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope, so a client can always tell whether further pages
    exist."

    Design: Corner/entities/machines_list_paginates_with_total_count_and_has_more
    """
    ctx = setup_org_dealer(api)
    for serial in ("SN-0001", "SN-0002", "SN-0003"):
        add_machine(
            ctx,
            api,
            serial_number=serial,
            modem_imei="IMEI-{0}".format(serial),
        )
    org_id = ctx["org"]["id"]

    rows, meta = validate_paginated(
        api.list_machines(
            headers=ctx["grower_headers"],
            params={"organization_id": org_id, "limit": 2, "offset": 0},
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_machines(
            headers=ctx["grower_headers"],
            params={"organization_id": org_id, "limit": 2, "offset": 2},
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_machines(
            headers=ctx["grower_headers"],
            params={"organization_id": org_id, "lifecycle_status": "REGISTERED"},
        )
    )
    assert len(rows) == 3

    rows, meta = validate_paginated(
        api.list_machines(
            headers=ctx["grower_headers"], params={"organization_id": org_id}
        )
    )
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_modem_provisioning_event_from_unprovisioned_rejected(api):
    """PRD section 3.1 pins the operator callback to the `PROVISIONING` state
    ("`PROVISION_SUCCEEDED` moves the modem to `PROVISIONED` and recomputes
    posture"), and PRD section 2.10 step "**State preconditions** — the
    target resource and any cross-entity state requirements for the requested
    transition" rejects with `ERR_INVALID_STATE_TRANSITION` (HTTP 409).

    Design: Corner/state_machines/modem_provisioning_event_from_unprovisioned_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    response = api.report_modem_provisioning_event(
        machine["id"], "PROVISION_SUCCEEDED", headers=SYSTEM
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    machine = read_machine(ctx, api, machine["id"])
    assert machine["modem_status"] == "UNPROVISIONED"
    assert machine["provisioning_attempts"] == 0


def test_provision_begin_while_provisioning_rejected(api):
    """PRD section 3.1: "Beginning provisioning — by a `DealerTechnician` or a
    `PlatformAdmin` — moves `UNPROVISIONED` or `PROVISION_FAILED` to
    `PROVISIONING` and increments `provisioning_attempts`" — a second begin
    while already `PROVISIONING` is a transition that does not exist and is
    rejected with `ERR_INVALID_STATE_TRANSITION` (PRD section 2.10, state
    preconditions).

    Design: Corner/state_machines/provision_begin_while_provisioning_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    begin_provisioning(ctx, api, machine["id"])
    response = api.provision_modem(machine["id"], headers=ctx["dealer_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    machine = read_machine(ctx, api, machine["id"])
    assert machine["provisioning_attempts"] == 1
    assert machine["modem_status"] == "PROVISIONING"


def test_machine_activate_twice_rejected(api):
    """PRD section 3.1: "On success the machine moves from `REGISTERED` to
    `ACTIVATED`, `activating_dealer_id` records the caller's dealer `id`, and
    `activated_at` records the logical timestamp." Repeating the handshake on
    an `ACTIVATED` machine is a transition that does not exist and fails with
    `ERR_INVALID_STATE_TRANSITION` (PRD section 2.10, state preconditions).

    Design: Corner/state_machines/machine_activate_twice_rejected
    """
    ctx = setup_activated_machine(api)
    machine_id = ctx["machine"]["id"]
    first_dealer = ctx["machine"]["activating_dealer_id"]
    first_at = ctx["machine"]["activated_at"]
    assert first_dealer == ctx["dealer"]["id"]

    response = api.activate_machine(machine_id, headers=ctx["dealer_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    machine = read_machine(ctx, api, machine_id)
    assert machine["lifecycle_status"] == "ACTIVATED"
    assert machine["activating_dealer_id"] == first_dealer
    assert machine["activated_at"] == first_at


def test_first_telemetry_flips_activated_to_in_service_with_posture_progression(api):
    """PRD section 3.1: "`PROVISION_SUCCEEDED` moves the modem to `PROVISIONED`
    and recomputes posture (to `NO_PLAN` if no active plan exists, or to
    `CONNECTED` if an active plan with `NORMAL` usage exists)" and "The final
    step to `IN_SERVICE` is automatic: the first accepted telemetry batch flips
    an `ACTIVATED` machine to `IN_SERVICE` (§3.2)."

    Design: Corner/state_machines/first_telemetry_flips_activated_to_in_service_with_posture_progression
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]

    provision_modem_success(ctx, api, machine_id)
    machine = read_machine(ctx, api, machine_id)
    assert machine["connectivity_posture"] == "NO_PLAN"
    assert machine["lifecycle_status"] == "REGISTERED"

    plan = create_plan(ctx, api, machine_id)
    activate_plan(ctx, api, plan["id"])
    machine = read_machine(ctx, api, machine_id)
    assert machine["connectivity_posture"] == "CONNECTED"
    assert machine["lifecycle_status"] == "REGISTERED"

    response = api.activate_machine(machine_id, headers=ctx["dealer_headers"])
    machine = validate_success(response, 200)
    assert machine["lifecycle_status"] == "ACTIVATED"
    assert machine["connectivity_posture"] == "CONNECTED"

    machine = ingest_batch(
        ctx, api, machine_id, batch_id="b-first", hour_count=2, payload_mb=10
    )
    assert machine["lifecycle_status"] == "IN_SERVICE"
