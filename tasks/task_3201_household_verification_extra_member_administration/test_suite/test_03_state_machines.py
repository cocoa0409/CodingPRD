"""State machine behavior: account cycle, challenge cycle, device/slot/household
transitions and side effects."""
from test_helpers import (
    ApiErrorId,
    WRONG_CODE,
    admin_headers,
    create_account,
    create_account_with_device,
    create_account_with_slot,
    get_account,
    get_success_data,
    grant_pass,
    instants_equal,
    issue_challenge,
    set_clock,
    validate_error,
)


def test_account_suspension_cycle_with_parallel_posture_status(api):
    """PRD §3.1: "An account's lifecycle runs `ACTIVE` → `SUSPENDED` → `ACTIVE`
    as a repeatable cycle". PRD §3.1: "each account carries a parallel dimension
    `verification_posture` that evolves independently".

    Design: Difficulty/non_linear_state_machine/account_suspension_cycle_with_parallel_posture
    """
    account, owner_h = create_account(email="sm1@x.com")
    assert account["version"] == 1

    suspended = get_success_data(api.suspend_account(account["id"], admin_headers()))
    assert suspended["status"] == "SUSPENDED"

    reactivated = get_success_data(api.reactivate_account(account["id"], admin_headers()))
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["verification_posture"] == "VERIFIED", "posture untouched by the status cycle"
    assert reactivated["version"] == 3, "suspend +1, reactivate +1"


def test_account_suspension_cycle_repeatable(api):
    """PRD §3.1: "An account's lifecycle runs `ACTIVE` → `SUSPENDED` → `ACTIVE`
    as a repeatable cycle" and "Reactivation returns a `SUSPENDED` account to
    `ACTIVE` and increments `version` by 1".

    Design: Difficulty/non_linear_state_machine/account_suspension_cycle_with_parallel_posture
    """
    account, owner_h = create_account(email="sm1b@x.com")
    for _ in range(2):
        suspended = get_success_data(api.suspend_account(account["id"], admin_headers()))
        assert suspended["status"] == "SUSPENDED"
        reactivated = get_success_data(api.reactivate_account(account["id"], admin_headers()))
        assert reactivated["status"] == "ACTIVE"
    after = get_account(account["id"])
    assert after["version"] == 5, "two full cycles from version 1"


def test_challenge_expire_reissue_cycle_status_and_code(api):
    """PRD §2.9: "a `PENDING` verification challenge becomes `EXPIRED` the first
    time it is read or submitted against after its `expires_at`". PRD §3.4:
    "Reissue returns the challenge to `PENDING` with a freshly generated 6-digit
    code, `attempts_used` reset to 0".

    Design: Difficulty/non_linear_state_machine/challenge_expire_reissue_cycle
    """
    account, owner_h = create_account(email="sm2@x.com")
    challenge = issue_challenge(account["id"], channel="EMAIL", challenge_reason="NEW_DEVICE")
    code_1 = challenge["code"]

    set_clock("2026-09-01T00:20:00Z")  # past 900s expiry and past the 300s cooldown
    read = get_success_data(api.get_challenge(challenge["id"], admin_headers()))
    assert read["status"] == "EXPIRED"

    reissued = get_success_data(api.reissue_challenge(challenge["id"], owner_h))
    assert reissued["status"] == "PENDING"
    assert reissued["attempts_used"] == 0
    assert reissued["code"] != code_1
    assert reissued["code"] != WRONG_CODE


def test_challenge_expire_reissue_cycle_repeatable(api):
    """PRD §3.4: "The `PENDING` → `EXPIRED` → `PENDING` cycle may repeat, subject
    to that cooldown buffer."

    Design: Difficulty/non_linear_state_machine/challenge_expire_reissue_cycle
    """
    account, owner_h = create_account(email="sm2b@x.com")
    challenge = issue_challenge(account["id"])

    for expiry_read_time in ("2026-09-01T00:20:00Z", "2026-09-01T00:40:00Z"):
        set_clock(expiry_read_time)
        read = get_success_data(api.get_challenge(challenge["id"], admin_headers()))
        assert read["status"] == "EXPIRED"
        reissued = get_success_data(api.reissue_challenge(challenge["id"], owner_h))
        assert reissued["status"] == "PENDING"
        assert reissued["attempts_used"] == 0


def test_device_removed_terminal_lockdown(api):
    """PRD §3.3: "Removing a device — permitted from either `TRUSTED` or
    `UNTRUSTED` — is terminal: the device becomes `REMOVED`". PRD §3.3: "Marking
    a device trusted ... the device must currently be `UNTRUSTED`".

    Design: Corner/state_machines/device_removed_terminal_lockdown
    """
    account, household, device, owner_h = create_account_with_device(
        email="corner-term@x.com", trust=True
    )
    removed = get_success_data(api.remove_device(device["id"], owner_h))
    assert removed["trust_status"] == "REMOVED"

    resp = api.trust_device(device["id"], owner_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_device(device["id"], owner_h))
    assert after["trust_status"] == "REMOVED"


def test_slot_revoked_assign_invalid_state(api):
    """PRD §3.6: "Assigning an `OFFERED` slot is an `AccountOwner` operation" —
    assignment is defined only from `OFFERED`; a `REVOKED` slot "can be returned
    to `OFFERED` by the `AccountOwner` while the account is `ACTIVE`" via reoffer
    first. Assigning directly from REVOKED violates the entity state gate
    (`ERR_INVALID_STATE`, HTTP 409, PRD §5).

    Design: Corner/state_machines/slot_revoked_assign_invalid_state
    """
    account, slot, owner_h = create_account_with_slot(email="corner-slot@x.com")
    get_success_data(
        api.assign_slot(slot["id"], {"email": "extra-slot@x.com", "display_name": "Extra S", "member_region": "NA"}, owner_h)
    )
    revoked = get_success_data(api.revoke_slot(slot["id"], owner_h))
    assert revoked["status"] == "REVOKED"

    resp = api.assign_slot(
        slot["id"], {"email": "extra-slot2@x.com", "display_name": "Extra S2", "member_region": "NA"}, owner_h
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_slot(slot["id"], owner_h))
    assert after["status"] == "REVOKED"


def test_travel_pass_convert_side_effects(api):
    """PRD §3.5: "the pass becomes `CONVERTED`, and the device transitions
    `UNTRUSTED` → `TRUSTED` directly, bypassing the confidence threshold of §3.3
    (the household's `trusted_device_count` increments by 1)".

    Design: Corner/state_machines/travel_pass_convert_side_effects
    """
    account, household, device, owner_h = create_account_with_device(
        email="corner-conv@x.com",
        device_network="fp-away-1",
        device_geo="geo-away-1",
        device_type="MOBILE",
        trust=False,
    )
    pass_ = grant_pass(device["id"], owner_h)
    # Traveler comes home: signal from the household network.
    get_success_data(
        api.signal_device(device["id"], {"network_fingerprint": "fp-home-1", "geo_cell": "geo-home-1"}, owner_h)
    )

    converted = get_success_data(api.convert_travel_pass(pass_["id"], owner_h))
    assert converted["status"] == "CONVERTED"

    device_after = get_success_data(api.get_device(device["id"], owner_h))
    assert device_after["trust_status"] == "TRUSTED"
    household_after = get_success_data(api.get_household(household["id"], owner_h))
    assert household_after["trusted_device_count"] == 1


def test_household_relocation_untrust_cycle(api):
    """PRD §3.2: "The household transitions `ESTABLISHED` → `RELOCATING`, its
    three anchor fields are overwritten with the new values, and — exactly as
    under account suspension — every `TRUSTED` device becomes `UNTRUSTED`" and
    "The household returns `RELOCATING` → `ESTABLISHED` when any device of the
    household records a network signal whose `network_fingerprint` equals the
    household's new anchor; at that moment `last_verified_at` is set to the
    current logical time."

    Design: Corner/state_machines/household_relocation_untrust_cycle
    """
    account, household, device, owner_h = create_account_with_device(
        email="corner-relo@x.com", trust=True
    )
    relocated = get_success_data(
        api.relocate_household(
            household["id"],
            {"primary_location": "9 Oak Ave", "network_fingerprint": "fp-home-2", "geo_cell": "geo-home-2"},
            owner_h,
        )
    )
    assert relocated["status"] == "RELOCATING"

    device_after = get_success_data(api.get_device(device["id"], owner_h))
    assert device_after["trust_status"] == "UNTRUSTED"

    get_success_data(
        api.signal_device(device["id"], {"network_fingerprint": "fp-home-2", "geo_cell": "geo-home-2"}, owner_h)
    )
    household_after = get_success_data(api.get_household(household["id"], owner_h))
    assert household_after["status"] == "ESTABLISHED"
    assert instants_equal(household_after["last_verified_at"], "2026-09-01T00:00:00Z")
    assert household_after["network_fingerprint"] == "fp-home-2"
    assert household_after["geo_cell"] == "geo-home-2"
