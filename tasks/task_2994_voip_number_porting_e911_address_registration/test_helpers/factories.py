"""Request-payload builders.

Every builder returns a plain dict and applies `**overrides` with `update`
rather than re-passing keyword arguments, so a caller may override any field
(including one the builder itself computed) without ever producing a duplicate
keyword argument. Derived builders pop the keys they consume before forwarding
the remainder.

All literals respect the PRD's format rules:
  - `account_number` 8-12 characters of [A-Z0-9]
  - `ocn` exactly 4 characters of [A-Z0-9]
  - `county_fips` exactly 5 digits, `postal_code` / `claimed_zip` exactly 5 digits
  - `npa_nxx` exactly 6 digits, `line_number` exactly 4 digits
  - `mac_address` exactly 12 characters of [0-9A-F]
  - requested numbers `+1` followed by exactly 10 digits
  - `period_month` formatted YYYY-MM
Money is always a JSON integer of whole cents; instants are always full
ISO-8601 UTC instants, never date-only strings.
"""
from .constants import CLOCK_DEFAULT_ISO


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def make_clock_payload(current_utc: str = CLOCK_DEFAULT_ISO, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Accounts
# ----------------------------------------------------------------------
def make_account_payload(
    account_number: str = "ACCT1000",
    billing_name: str = "Bayview Telecom LLC",
    service_state_code: str = "CA",
    **overrides,
) -> dict:
    payload = {
        "account_number": account_number,
        "billing_name": billing_name,
        "service_state_code": service_state_code,
    }
    payload.update(overrides)
    return payload


def make_intl_enabled_account_payload(
    account_number: str = "ACCT1000",
    intl_daily_cap_cents: int = 2000,
    **overrides,
) -> dict:
    """An account with international calling switched on.

    `intl_daily_cap_cents` is whole cents as a JSON integer.
    """
    base = dict(overrides)
    base.pop("intl_calling_enabled", None)
    base.pop("intl_daily_cap_cents", None)
    return make_account_payload(
        account_number=account_number,
        intl_calling_enabled=True,
        intl_daily_cap_cents=intl_daily_cap_cents,
        **base,
    )


# ----------------------------------------------------------------------
# Carriers
# ----------------------------------------------------------------------
def make_carrier_payload(
    name: str = "Golden Gate Telco",
    ocn: str = "AA10",
    csr_match_policy: str = "STRICT",
    porting_buffer_minutes: int = 30,
    foc_business_days: int = 2,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "ocn": ocn,
        "csr_match_policy": csr_match_policy,
        "porting_buffer_minutes": porting_buffer_minutes,
        "foc_business_days": foc_business_days,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Jurisdictions
# ----------------------------------------------------------------------
def make_jurisdiction_payload(
    state_code: str = "CA",
    county_fips: str = "06001",
    fee_type: str = "PER_LINE",
    monthly_fee_cents: int = 175,
    remit_day_of_month: int = 5,
    **overrides,
) -> dict:
    payload = {
        "state_code": state_code,
        "county_fips": county_fips,
        "fee_type": fee_type,
        "monthly_fee_cents": monthly_fee_cents,
        "remit_day_of_month": remit_day_of_month,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Number blocks and phone numbers
# ----------------------------------------------------------------------
def make_number_block_payload(
    jurisdiction_id: str,
    npa_nxx: str = "415600",
    total_capacity: int = 10,
    max_concurrent_reservations: int = 2,
    **overrides,
) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "npa_nxx": npa_nxx,
        "total_capacity": total_capacity,
        "max_concurrent_reservations": max_concurrent_reservations,
    }
    payload.update(overrides)
    return payload


def make_phone_number_payload(line_number: str = "3001", **overrides) -> dict:
    payload = {"line_number": line_number}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Number reservations
# ----------------------------------------------------------------------
def make_number_reservation_payload(
    block_id: str,
    account_id: str,
    expected_number_block_version: int,
    reserved_from: str = "2026-08-04T00:00:00.000Z",
    reserved_until: str = "2026-08-10T00:00:00.000Z",
    purpose: str = "NEW_LINE",
    **overrides,
) -> dict:
    """A reservation request.

    `expected_number_block_version` is mandatory: the PRD makes this endpoint
    one of only two that carry an optimistic-concurrency token, and omitting it
    is an invalid request rather than a silent success.
    """
    payload = {
        "block_id": block_id,
        "account_id": account_id,
        "purpose": purpose,
        "reserved_from": reserved_from,
        "reserved_until": reserved_until,
        "expected_number_block_version": expected_number_block_version,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Port requests
# ----------------------------------------------------------------------
def make_port_request_payload(
    account_id: str,
    losing_carrier_id: str,
    requested_numbers=None,
    claimed_account_number: str = "ACCT1000",
    claimed_pin: str = "1000",
    claimed_billing_name: str = "Bayview Telecom LLC",
    claimed_address_line1: str = "500 Market Street",
    claimed_zip: str = "94105",
    **overrides,
) -> dict:
    payload = {
        "account_id": account_id,
        "losing_carrier_id": losing_carrier_id,
        "requested_numbers": list(requested_numbers or ["+14155551800"]),
        "claimed_account_number": claimed_account_number,
        "claimed_pin": claimed_pin,
        "claimed_billing_name": claimed_billing_name,
        "claimed_address_line1": claimed_address_line1,
        "claimed_zip": claimed_zip,
    }
    payload.update(overrides)
    return payload


def make_csr_snapshot_payload(
    expected_port_request_version: int,
    account_number_on_file: str = "ACCT1000",
    pin_on_file: str = "1000",
    billing_name_on_file: str = "Bayview Telecom LLC",
    address_line1_on_file: str = "500 Market Street",
    zip_on_file: str = "94105",
    **overrides,
) -> dict:
    """A carrier-of-record snapshot; the version token is mandatory."""
    payload = {
        "account_number_on_file": account_number_on_file,
        "pin_on_file": pin_on_file,
        "billing_name_on_file": billing_name_on_file,
        "address_line1_on_file": address_line1_on_file,
        "zip_on_file": zip_on_file,
        "expected_port_request_version": expected_port_request_version,
    }
    payload.update(overrides)
    return payload


def make_matching_csr_snapshot_payload(
    expected_port_request_version: int, port_request_payload: dict, **overrides
) -> dict:
    """A snapshot whose five on-file values agree with a port request's claims.

    Every comparison point matches, so the snapshot scores the full 100 points
    and satisfies either match policy.
    """
    rest = dict(overrides)
    for key in (
        "account_number_on_file",
        "pin_on_file",
        "billing_name_on_file",
        "address_line1_on_file",
        "zip_on_file",
    ):
        rest.pop(key, None)
    return make_csr_snapshot_payload(
        expected_port_request_version,
        account_number_on_file=port_request_payload["claimed_account_number"],
        pin_on_file=port_request_payload["claimed_pin"],
        billing_name_on_file=port_request_payload["claimed_billing_name"],
        address_line1_on_file=port_request_payload["claimed_address_line1"],
        zip_on_file=port_request_payload["claimed_zip"],
        **rest,
    )


def make_resubmit_payload(**overrides) -> dict:
    """A resubmission may restate any of the claimed fields."""
    payload = {}
    payload.update(overrides)
    return payload


def make_reject_payload(reason_code: str = "CSR_MISMATCH", **overrides) -> dict:
    """A carrier rejection: mandatory `reason_code`, optional free-text `note`."""
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def make_cancel_payload(**overrides) -> dict:
    """A cancellation body; `reason_note` is optional and not persisted."""
    payload = {}
    payload.update(overrides)
    return payload


def make_schedule_payload(cutover_slot_id: str, **overrides) -> dict:
    payload = {"cutover_slot_id": cutover_slot_id}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Cutover slots
# ----------------------------------------------------------------------
def make_cutover_slot_payload(
    carrier_id: str,
    window_start: str = "2026-08-06T14:00:00.000Z",
    window_end: str = "2026-08-06T18:00:00.000Z",
    **overrides,
) -> dict:
    """A cutover window; both bounds are full ISO-8601 UTC instants."""
    payload = {
        "carrier_id": carrier_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Temporary bridges
# ----------------------------------------------------------------------
def make_temporary_bridge_payload(port_request_id: str, reservation_id: str, **overrides) -> dict:
    payload = {"port_request_id": port_request_id, "reservation_id": reservation_id}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Devices
# ----------------------------------------------------------------------
def make_device_payload(
    account_id: str,
    mac_address: str = "AABBCC003001",
    device_type: str = "BASE_STATION",
    **overrides,
) -> dict:
    payload = {
        "account_id": account_id,
        "mac_address": mac_address,
        "device_type": device_type,
    }
    payload.update(overrides)
    return payload


def make_nomadic_device_payload(
    account_id: str, mac_address: str = "AABBCC003001", **overrides
) -> dict:
    """A device flagged as legitimately mobile between dispatchable locations."""
    rest = dict(overrides)
    rest.pop("nomadic", None)
    return make_device_payload(account_id, mac_address, nomadic=True, **rest)


def make_number_holding_device_payload(
    account_id: str,
    assigned_number_id: str,
    mac_address: str = "AABBCC003001",
    **overrides,
) -> dict:
    """A device that takes a phone number at registration time."""
    rest = dict(overrides)
    rest.pop("assigned_number_id", None)
    return make_device_payload(
        account_id, mac_address, assigned_number_id=assigned_number_id, **rest
    )


def make_network_report_payload(
    reported_state_code: str = "CA", reported_postal_code: str = "94105", **overrides
) -> dict:
    payload = {
        "reported_state_code": reported_state_code,
        "reported_postal_code": reported_postal_code,
    }
    payload.update(overrides)
    return payload


def make_call_attempt_payload(
    destination_e164: str = "+14155559001",
    destination_country_code: str = "1",
    requested_duration_seconds: int = 300,
    **overrides,
) -> dict:
    """A dial request.

    `destination_country_code` must be a prefix of `destination_e164` once the
    leading plus sign is discarded, so the two are always chosen together.
    """
    payload = {
        "destination_e164": destination_e164,
        "destination_country_code": destination_country_code,
        "requested_duration_seconds": requested_duration_seconds,
    }
    payload.update(overrides)
    return payload


def make_calling_restriction_payload(action: str = "BLOCK_INTL", **overrides) -> dict:
    """A restriction action; the optional `note` is never persisted."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# E911 registrations
# ----------------------------------------------------------------------
def make_e911_registration_payload(
    device_id: str,
    jurisdiction_id: str,
    address_line1: str = "500 Market Street",
    city: str = "Oakland",
    state_code: str = "CA",
    postal_code: str = "94105",
    **overrides,
) -> dict:
    """A dispatchable location. `unit` is optional and defaults to "" server-side."""
    payload = {
        "device_id": device_id,
        "jurisdiction_id": jurisdiction_id,
        "address_line1": address_line1,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
    }
    payload.update(overrides)
    return payload


def make_verify_payload(outcome: str = "VERIFIED", **overrides) -> dict:
    """A validator outcome: mandatory `outcome`, optional `rejection_note`."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def make_reject_registration_payload(
    rejection_note: str = "no such civic address", **overrides
) -> dict:
    """A REJECTED verification outcome carrying the validator's note."""
    rest = dict(overrides)
    rest.pop("outcome", None)
    rest.pop("rejection_note", None)
    return make_verify_payload("REJECTED", rejection_note=rejection_note, **rest)


# ----------------------------------------------------------------------
# Fee assessments and remittance
# ----------------------------------------------------------------------
def make_fee_assessment_payload(
    account_id: str, jurisdiction_id: str, period_month: str = "2026-08", **overrides
) -> dict:
    payload = {
        "account_id": account_id,
        "jurisdiction_id": jurisdiction_id,
        "period_month": period_month,
    }
    payload.update(overrides)
    return payload


def make_void_payload(**overrides) -> dict:
    """A void body; `void_note` is optional and not persisted."""
    payload = {}
    payload.update(overrides)
    return payload


def make_remittance_run_payload(period_month: str = "2026-08", **overrides) -> dict:
    payload = {"period_month": period_month}
    payload.update(overrides)
    return payload
