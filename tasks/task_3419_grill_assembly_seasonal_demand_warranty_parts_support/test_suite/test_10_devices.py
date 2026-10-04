"""Connected grills: pairing as a registration side effect, the synchronous
firmware update pass-through, unpair lockout, and the one-live-device rule.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_device_pair_payload,
    firmware_payload,
    pair_device,
    setup_in_season_with_sale,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]
APP_USER = TEST_USERS["app_user_headers"]


def test_device_firmware_update_cycles_and_unpair_locks(api):
    """PRD 3.9: "The device's `firmware_version` is initialized from the grill model's
    `current_firmware_version` at pairing time."
    PRD 3.9: "Pairing doubles as registration: if the sale is still `SOLD`, it moves
    to `REGISTERED` in the same request with `registered_at` stamped and the
    `proof_of_purchase_token` synthesized as "APP-PAIR""
    PRD 3.9: "the device must currently be `PAIRED`, else `ERR_DEVICE_NOT_PAIRED`. The
    device passes `PAIRED → UPDATING → PAIRED` within the single request — the update
    applies synchronously — emerging with `firmware_version` rewritten to the
    `target_version`"
    PRD 3.9: "The devices of a sale are listed through the sale's device view, which
    returns zero or one entries"
    PRD 2.8: "the system validates the existence of each identifier in strict
    left-to-right order and rejects the request immediately with the 404 code of the
    first identifier that does not resolve"

    Design: Corner/state_machines/device_firmware_update_cycles_and_unpair_locks
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    sale = bundle["sale"]
    assert sale["status"] == "SOLD", "created without proof of purchase"
    ghost = api.device_firmware("00000000-0000-4000-8000-000000000009",
                                firmware_payload("UPDATE", "2.1.0"), headers=APP_USER)
    validate_error(ghost, ApiErrorId.ERR_DEVICE_NOT_FOUND)
    device = validate_success(api.pair_device(
        create_device_pair_payload(sale["id"], "acct-77"), headers=APP_USER), 201)
    assert device["firmware_version"] == "1.0.0", "initialized from the model's current firmware"
    assert device["pairing_token"], "a server-issued pairing proof is returned at creation"
    sale_after = validate_success(api.get_sale(sale["id"], headers=AGENT), 200)
    assert sale_after["status"] == "REGISTERED", "pairing registers the sale as a side effect"
    updated = validate_success(api.device_firmware(
        device["id"], firmware_payload("UPDATE", "2.1.0"), headers=APP_USER), 200)
    assert updated["firmware_version"] == "2.1.0"
    assert updated["status"] == "PAIRED", "the synchronous UPDATING pass-through lands back on PAIRED"
    devices, meta = validate_paginated(api.list_sale_devices(sale["id"], headers=AGENT))
    assert meta["total_count"] == 1, "the sale's device view returns zero or one entries"
    assert devices[0]["firmware_version"] == "2.1.0", "the sale's device view shows the paired record"
    unpaired = validate_success(api.device_firmware(
        device["id"], firmware_payload("UNPAIR"), headers=APP_USER), 200)
    assert unpaired["status"] == "UNPAIRED"
    locked = api.device_firmware(device["id"], firmware_payload("UPDATE", "2.2.0"), headers=APP_USER)
    validate_error(locked, ApiErrorId.ERR_DEVICE_NOT_PAIRED)


def test_second_pairing_for_same_sale_rejected(api):
    """PRD 3.9: "A sale supports at most one device in `PAIRED` or `UPDATING`; pairing
    over an existing live device is `ERR_DEVICE_ALREADY_PAIRED`."

    Design: Corner/validations/second_pairing_for_same_sale_rejected
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    pair_device(bundle["sale"]["id"], "acct-1")
    second = api.pair_device(create_device_pair_payload(bundle["sale"]["id"], "acct-2"), headers=APP_USER)
    validate_error(second, ApiErrorId.ERR_DEVICE_ALREADY_PAIRED)


def test_service_agent_cannot_pair_device_returns_unauthorized(api):
    """PRD 2.1: "An attempt to perform an operation outside the caller's designated
    role — or an action the role is not permitted for on that endpoint — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD 4: `POST /grillops/devices/pair` is authorized for AppUser only.

    Design: Corner/rbac/service_agent_cannot_pair_device_returns_unauthorized
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    resp = api.pair_device(create_device_pair_payload(bundle["sale"]["id"], "acct-x"), headers=AGENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    devices, meta = validate_paginated(api.list_sale_devices(bundle["sale"]["id"], headers=AGENT))
    assert meta["total_count"] == 0, "no device may be persisted by the rejected pairing"
