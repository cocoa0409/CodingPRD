"""Composite setup helpers.

Every test starts against an empty database, so each test builds all of its own
preconditions through the public API. These helpers are the shared vocabulary
for doing that.

Two rules shape their design.

*Phasing.* A helper never performs a hop that invalidates a hop it performed
itself. Capturing a dispatchable location supersedes the device's previous one,
and a resubmission supersedes the current CSR snapshot, so helpers stop at the
last state that remains internally consistent and leave the next hop to the
caller (for example `provision_bridge` stops at `PROVISIONED` and never
activates).

*Concurrency tokens.* Two endpoints carry an optimistic-concurrency token. The
reservation helper always re-reads the block's `version` immediately before it
posts, and the snapshot helper always re-reads the port request's `version`,
so a helper called twice in a row never fails on a token it stalened itself.

Setup calls use the lenient `get_success_data`, which accepts any 2xx and
raises a clear "setup step failed" message, so a broken precondition is never
mistaken for the assertion under test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    make_account_payload,
    make_call_attempt_payload,
    make_calling_restriction_payload,
    make_carrier_payload,
    make_clock_payload,
    make_csr_snapshot_payload,
    make_cutover_slot_payload,
    make_device_payload,
    make_e911_registration_payload,
    make_fee_assessment_payload,
    make_jurisdiction_payload,
    make_matching_csr_snapshot_payload,
    make_network_report_payload,
    make_number_block_payload,
    make_number_reservation_payload,
    make_phone_number_payload,
    make_port_request_payload,
    make_reject_payload,
    make_remittance_run_payload,
    make_resubmit_payload,
    make_schedule_payload,
    make_temporary_bridge_payload,
    make_verify_payload,
    make_void_payload,
)
from .test_users import (
    BILLING_USER_ID,
    BILLING_USER_ID_ALT,
    LIAISON_USER_ID,
    PORTING_USER_ID,
    make_account_admin_headers,
    make_billing_admin_headers,
    make_carrier_liaison_headers,
    make_e911_validator_headers,
    make_numbering_admin_headers,
    make_platform_admin_headers,
    make_porting_specialist_headers,
    make_security_analyst_headers,
)


# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
def set_clock(current_utc: str) -> dict:
    """Move the logical clock; mutates no domain state."""
    return get_success_data(
        api_client.set_clock(make_clock_payload(current_utc), make_platform_admin_headers())
    )


# ----------------------------------------------------------------------
# Reference data
# ----------------------------------------------------------------------
def seed_account(account_number: str = "ACCT1000", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_platform_admin_headers()
    return get_success_data(
        api_client.create_account(
            make_account_payload(account_number=account_number, **overrides),
            headers,
        )
    )


def seed_carrier(ocn: str = "AA10", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_platform_admin_headers()
    return get_success_data(
        api_client.create_carrier(
            make_carrier_payload(ocn=ocn, **overrides), headers
        )
    )


def seed_jurisdiction(
    state_code: str = "CA", county_fips: str = "06001", **overrides
) -> dict:
    headers = overrides.pop("headers", None) or make_platform_admin_headers()
    return get_success_data(
        api_client.create_jurisdiction(
            make_jurisdiction_payload(
                state_code=state_code, county_fips=county_fips, **overrides
            ),
            headers,
        )
    )


def seed_number_block(jurisdiction_id: str, npa_nxx: str = "415600", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_numbering_admin_headers()
    return get_success_data(
        api_client.create_number_block(
            make_number_block_payload(jurisdiction_id, npa_nxx=npa_nxx, **overrides),
            headers,
        )
    )


def seed_phone_number(block_id: str, line_number: str = "3001", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_numbering_admin_headers()
    return get_success_data(
        api_client.mint_phone_number(
            block_id,
            make_phone_number_payload(line_number=line_number, **overrides),
            headers,
        )
    )


def read_number_block(block_id: str) -> dict:
    return get_success_data(
        api_client.get_number_block(block_id, make_numbering_admin_headers())
    )


def read_phone_number(number_id: str) -> dict:
    return get_success_data(
        api_client.get_phone_number(number_id, make_numbering_admin_headers())
    )


def block_version(block_id: str) -> int:
    """The block's current concurrency token, read fresh."""
    return read_number_block(block_id)["version"]


# ----------------------------------------------------------------------
# Reservations
# ----------------------------------------------------------------------
def seed_reservation(block_id: str, account_id: str, **overrides) -> dict:
    """Hold a number, supplying a freshly read block version every time.

    Each accepted reservation increments the block's `version`, so the token is
    re-read here rather than cached by the caller; a caller that wants to test
    a deliberately stale token passes `expected_number_block_version` itself.
    """
    headers = overrides.pop("headers", None) or make_numbering_admin_headers()
    version = overrides.pop("expected_number_block_version", None)
    if version is None:
        version = block_version(block_id)
    return get_success_data(
        api_client.create_number_reservation(
            make_number_reservation_payload(
                block_id, account_id, version, **overrides
            ),
            headers,
        )
    )


def read_reservation(reservation_id: str) -> dict:
    return get_success_data(
        api_client.get_number_reservation(reservation_id, make_numbering_admin_headers())
    )


def release_reservation(reservation_id: str) -> dict:
    return get_success_data(
        api_client.release_number_reservation(
            reservation_id, make_numbering_admin_headers()
        )
    )


# ----------------------------------------------------------------------
# Devices, dispatchable locations and calls
# ----------------------------------------------------------------------
def seed_device(account_id: str, mac_address: str = "AABBCC003001", **overrides) -> dict:
    """Register a device. Uses the owning account's own administrator so the
    ownership comparison of the entity-backed role is always satisfied."""
    headers = overrides.pop("headers", None) or make_account_admin_headers(account_id)
    return get_success_data(
        api_client.create_device(
            make_device_payload(account_id, mac_address=mac_address, **overrides), headers
        )
    )


def read_device(device_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_device(device_id, headers or make_platform_admin_headers())
    )


def seed_registration(device_id: str, jurisdiction_id: str, account_id: str, **overrides) -> dict:
    """Capture a dispatchable location for a device.

    This supersedes any registration the device already had, so a caller that
    wants two live registrations must use two devices.
    """
    headers = overrides.pop("headers", None) or make_account_admin_headers(account_id)
    return get_success_data(
        api_client.create_e911_registration(
            make_e911_registration_payload(device_id, jurisdiction_id, **overrides), headers
        )
    )


def verify_registration(registration_id: str, outcome: str = "VERIFIED", **overrides) -> dict:
    """Record a validator outcome on an UNVERIFIED or STALE registration."""
    headers = overrides.pop("headers", None) or make_e911_validator_headers()
    return get_success_data(
        api_client.verify_e911_registration(
            registration_id,
            make_verify_payload(outcome, **overrides),
            headers,
        )
    )


def read_registration(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_e911_registration(
            registration_id, headers or make_platform_admin_headers()
        )
    )


def report_network_location(
    device_id: str, account_id: str, reported_state_code: str = "CA",
    reported_postal_code: str = "94105", **overrides,
) -> dict:
    headers = overrides.pop("headers", None) or make_account_admin_headers(account_id)
    return get_success_data(
        api_client.create_network_report(
            device_id,
            make_network_report_payload(
                reported_state_code=reported_state_code,
                reported_postal_code=reported_postal_code,
                **overrides,
            ),
            headers,
        )
    )


def place_call(device_id: str, account_id: str, **overrides) -> dict:
    """Place an attempt that is expected to be allowed.

    A refused attempt is an error response, so tests that expect a refusal call
    the endpoint directly and assert on the error rather than using this helper.
    """
    headers = overrides.pop("headers", None) or make_account_admin_headers(account_id)
    return get_success_data(
        api_client.create_call_attempt(
            device_id, make_call_attempt_payload(**overrides), headers
        )
    )


def apply_restriction(device_id: str, action: str = "BLOCK_INTL", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_security_analyst_headers()
    return get_success_data(
        api_client.create_calling_restriction(
            device_id,
            make_calling_restriction_payload(action, **overrides),
            headers,
        )
    )


def read_account(account_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_account(account_id, headers or make_platform_admin_headers())
    )


def read_jurisdiction(jurisdiction_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_jurisdiction(jurisdiction_id, headers or make_platform_admin_headers())
    )


# ----------------------------------------------------------------------
# Port requests
# ----------------------------------------------------------------------
def seed_port_request(account_id: str, losing_carrier_id: str, **overrides) -> dict:
    """File a port request as the porting specialist `porting-1`.

    The acting id becomes `created_by_user_id`, which is the comparand of the
    segregation-of-duties rule, so it is fixed and knowable.
    """
    headers = overrides.pop("headers", None) or make_porting_specialist_headers(PORTING_USER_ID)
    return get_success_data(
        api_client.create_port_request(
            make_port_request_payload(account_id, losing_carrier_id, **overrides), headers
        )
    )


def read_port_request(port_request_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_port_request(
            port_request_id, headers or make_porting_specialist_headers()
        )
    )


def port_request_version(port_request_id: str) -> int:
    """The port request's current concurrency token, read fresh."""
    return read_port_request(port_request_id)["version"]


def post_csr_snapshot(port_request_id: str, **overrides) -> dict:
    """Transcribe a carrier record, re-reading the version token first.

    Every accepted snapshot and every resubmission increments the port
    request's `version`, so the token is never cached across calls.
    """
    headers = overrides.pop("headers", None) or make_carrier_liaison_headers(LIAISON_USER_ID)
    version = overrides.pop("expected_port_request_version", None)
    if version is None:
        version = port_request_version(port_request_id)
    return get_success_data(
        api_client.create_csr_snapshot(
            port_request_id, make_csr_snapshot_payload(version, **overrides), headers
        )
    )


def post_matching_csr_snapshot(port_request_id: str, port_request_payload: dict, **overrides) -> dict:
    """Transcribe a record that agrees with every claim, scoring a full 100."""
    headers = overrides.pop("headers", None) or make_carrier_liaison_headers(LIAISON_USER_ID)
    version = overrides.pop("expected_port_request_version", None)
    if version is None:
        version = port_request_version(port_request_id)
    return get_success_data(
        api_client.create_csr_snapshot(
            port_request_id,
            make_matching_csr_snapshot_payload(version, port_request_payload, **overrides),
            headers,
        )
    )


def resubmit_port_request(port_request_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_porting_specialist_headers(PORTING_USER_ID)
    return get_success_data(
        api_client.resubmit_port_request(
            port_request_id, make_resubmit_payload(**overrides), headers
        )
    )


def reject_port_request(port_request_id: str, reason_code: str = "CSR_MISMATCH", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_carrier_liaison_headers(LIAISON_USER_ID)
    return get_success_data(
        api_client.reject_port_request(
            port_request_id, make_reject_payload(reason_code, **overrides), headers
        )
    )


def seed_cutover_slot(carrier_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_porting_specialist_headers()
    return get_success_data(
        api_client.create_cutover_slot(
            make_cutover_slot_payload(carrier_id, **overrides), headers
        )
    )


def read_cutover_slot(slot_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_cutover_slot(slot_id, headers or make_porting_specialist_headers())
    )


def book_slot(port_request_id: str, cutover_slot_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_porting_specialist_headers()
    return get_success_data(
        api_client.schedule_port_request(
            port_request_id, make_schedule_payload(cutover_slot_id, **overrides), headers
        )
    )


def provision_bridge(port_request_id: str, reservation_id: str, **overrides) -> dict:
    """Provision a bridge and stop there.

    Activation is a separate hop with its own window precondition, so this
    helper deliberately leaves the bridge `PROVISIONED`.
    """
    headers = overrides.pop("headers", None) or make_porting_specialist_headers()
    return get_success_data(
        api_client.create_temporary_bridge(
            make_temporary_bridge_payload(port_request_id, reservation_id, **overrides),
            headers,
        )
    )


def activate_bridge(bridge_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.activate_temporary_bridge(
            bridge_id, headers or make_porting_specialist_headers()
        )
    )


# ----------------------------------------------------------------------
# Fees
# ----------------------------------------------------------------------
def assess_fee(account_id: str, jurisdiction_id: str, period_month: str = "2026-08", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_billing_admin_headers(BILLING_USER_ID)
    return get_success_data(
        api_client.create_fee_assessment(
            make_fee_assessment_payload(account_id, jurisdiction_id, period_month, **overrides),
            headers,
        )
    )


def void_fee_assessment(assessment_id: str, **overrides) -> dict:
    """Void as `billing-2`, which differs from the assessing `billing-1`."""
    headers = overrides.pop("headers", None) or make_billing_admin_headers(BILLING_USER_ID_ALT)
    return get_success_data(
        api_client.void_fee_assessment(
            assessment_id, make_void_payload(**overrides), headers
        )
    )


def run_remittance(jurisdiction_id: str, period_month: str = "2026-08", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_billing_admin_headers(BILLING_USER_ID)
    return get_success_data(
        api_client.create_remittance_run(
            jurisdiction_id, make_remittance_run_payload(period_month, **overrides), headers
        )
    )


# ----------------------------------------------------------------------
# Composite scenarios
# ----------------------------------------------------------------------
def setup_account_and_block(
    account_number: str = "ACCT1000",
    npa_nxx: str = "415600",
    state_code: str = "CA",
    county_fips: str = "06001",
    account_overrides: dict = None,
    jurisdiction_overrides: dict = None,
    block_overrides: dict = None,
) -> dict:
    """An account, a jurisdiction and an empty inventory block in it."""
    account = seed_account(account_number, **(account_overrides or {}))
    jurisdiction = seed_jurisdiction(
        state_code, county_fips, **(jurisdiction_overrides or {})
    )
    block = seed_number_block(
        jurisdiction["id"], npa_nxx=npa_nxx, **(block_overrides or {})
    )
    return {"account": account, "jurisdiction": jurisdiction, "block": block}


def setup_device_with_number(
    account_number: str = "ACCT1000",
    npa_nxx: str = "415600",
    line_number: str = "3001",
    mac_address: str = "AABBCC003001",
    device_overrides: dict = None,
    **scenario_overrides,
) -> dict:
    """A minted number taken immediately by a newly registered device.

    The device therefore enters the account's compliance population at once,
    with no dispatchable location yet.
    """
    scenario = setup_account_and_block(
        account_number=account_number, npa_nxx=npa_nxx, **scenario_overrides
    )
    number = seed_phone_number(scenario["block"]["id"], line_number)
    extras = dict(device_overrides or {})
    extras.pop("assigned_number_id", None)
    device = seed_device(
        scenario["account"]["id"],
        mac_address,
        assigned_number_id=number["id"],
        **extras,
    )
    scenario.update({"number": number, "device": device})
    return scenario


def setup_registered_device(
    account_number: str = "ACCT1000",
    npa_nxx: str = "415600",
    line_number: str = "3001",
    mac_address: str = "AABBCC003001",
    registration_overrides: dict = None,
    **scenario_overrides,
) -> dict:
    """A number-holding device whose captured location is still UNVERIFIED."""
    scenario = setup_device_with_number(
        account_number=account_number,
        npa_nxx=npa_nxx,
        line_number=line_number,
        mac_address=mac_address,
        **scenario_overrides,
    )
    registration = seed_registration(
        scenario["device"]["id"],
        scenario["jurisdiction"]["id"],
        scenario["account"]["id"],
        **(registration_overrides or {}),
    )
    scenario["registration"] = registration
    return scenario


def setup_compliant_device(
    account_number: str = "ACCT1000",
    npa_nxx: str = "415600",
    line_number: str = "3001",
    mac_address: str = "AABBCC003001",
    registration_overrides: dict = None,
    **scenario_overrides,
) -> dict:
    """The fully settled base state: a number-holding device with a VERIFIED
    dispatchable location, so the device is REGISTERED and the account COMPLIANT.

    The verification is the last hop, and nothing after it re-captures a
    location, so the state this helper leaves behind is stable.
    """
    scenario = setup_registered_device(
        account_number=account_number,
        npa_nxx=npa_nxx,
        line_number=line_number,
        mac_address=mac_address,
        registration_overrides=registration_overrides,
        **scenario_overrides,
    )
    scenario["registration"] = verify_registration(scenario["registration"]["id"])
    scenario["device"] = read_device(scenario["device"]["id"])
    scenario["account"] = read_account(scenario["account"]["id"])
    return scenario


def setup_submitted_port_request(
    account_number: str = "ACCT1000",
    ocn: str = "AA10",
    carrier_overrides: dict = None,
    account_overrides: dict = None,
    **port_overrides,
) -> dict:
    """An account, a losing carrier and a freshly filed port request.

    The claimed values are returned alongside so a caller can build a snapshot
    that either agrees or disagrees with them deliberately.
    """
    account = seed_account(account_number, **(account_overrides or {}))
    carrier = seed_carrier(ocn, **(carrier_overrides or {}))
    payload = make_port_request_payload(account["id"], carrier["id"], **port_overrides)
    port_request = get_success_data(
        api_client.create_port_request(
            payload, make_porting_specialist_headers(PORTING_USER_ID)
        )
    )
    return {
        "account": account,
        "carrier": carrier,
        "port_request": port_request,
        "claimed": payload,
    }


def setup_validated_port_request(
    account_number: str = "ACCT1000",
    ocn: str = "AA10",
    carrier_overrides: dict = None,
    account_overrides: dict = None,
    **port_overrides,
) -> dict:
    """A port request carried to VALIDATED by a perfectly matching record."""
    scenario = setup_submitted_port_request(
        account_number=account_number,
        ocn=ocn,
        carrier_overrides=carrier_overrides,
        account_overrides=account_overrides,
        **port_overrides,
    )
    scenario["snapshot"] = post_matching_csr_snapshot(
        scenario["port_request"]["id"], scenario["claimed"]
    )
    scenario["port_request"] = read_port_request(scenario["port_request"]["id"])
    return scenario


def setup_scheduled_port_request(
    account_number: str = "ACCT1000",
    ocn: str = "AA10",
    window_start: str = "2026-08-06T14:00:00.000Z",
    window_end: str = "2026-08-06T18:00:00.000Z",
    carrier_overrides: dict = None,
    account_overrides: dict = None,
    **port_overrides,
) -> dict:
    """A VALIDATED request with an OPEN slot of its own carrier booked for it."""
    scenario = setup_validated_port_request(
        account_number=account_number,
        ocn=ocn,
        carrier_overrides=carrier_overrides,
        account_overrides=account_overrides,
        **port_overrides,
    )
    slot = seed_cutover_slot(
        scenario["carrier"]["id"], window_start=window_start, window_end=window_end
    )
    scenario["port_request"] = book_slot(scenario["port_request"]["id"], slot["id"])
    scenario["slot"] = read_cutover_slot(slot["id"])
    return scenario
