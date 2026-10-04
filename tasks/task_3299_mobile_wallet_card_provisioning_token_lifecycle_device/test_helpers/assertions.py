"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    ArtifactStatus,
    AuthorizationStatus,
    CardAccountStatus,
    CardProduct,
    CardholderStatus,
    DisputeReason,
    DisputeStatus,
    IssuerStatus,
    SecurityPosture,
    SessionStatus,
    TokenStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_cardholder(data: dict):
    _assert_common(data, "Cardholder")
    assert data["status"] in [s.value for s in CardholderStatus]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_device(data: dict):
    _assert_common(data, "Device")
    assert isinstance(data["device_serial"], str) and data["device_serial"]
    assert isinstance(data["passcode_enabled"], bool)
    assert isinstance(data["biometric_enabled"], bool)
    assert isinstance(data["is_lost"], bool)
    assert data["security_posture"] in [s.value for s in SecurityPosture]
    assert isinstance(data["active_token_count"], int)
    assert "default_card_id" in data


def assert_issuer(data: dict):
    _assert_common(data, "Issuer")
    assert data["status"] in [s.value for s in IssuerStatus]
    assert isinstance(data["issuer_name"], str) and data["issuer_name"]


def assert_agreement(data: dict):
    _assert_common(data, "IssuerAgreement")
    assert data["status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["fee_bps"], int)
    assert isinstance(data["fee_cap_cents"], int)
    assert isinstance(data["fee_floor_cents"], int)


def assert_card_account(data: dict):
    _assert_common(data, "CardAccount")
    assert data["status"] in [s.value for s in CardAccountStatus]
    assert data["card_product"] in [s.value for s in CardProduct]
    assert "reissue_of_account_id" in data


def assert_card_artifact(data: dict):
    _assert_common(data, "CardArtifact")
    assert data["status"] in [s.value for s in ArtifactStatus]
    assert isinstance(data["pan_last4"], str)


def assert_provisioning_session(data: dict):
    _assert_common(data, "ProvisioningSession")
    assert data["status"] in [s.value for s in SessionStatus]
    assert isinstance(data["verification_attempt_count"], int)
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_payment_token(data: dict):
    _assert_common(data, "PaymentToken")
    assert data["status"] in [s.value for s in TokenStatus]
    assert isinstance(data["device_account_number"], str)
    for counter in (
        "auth_attempt_count",
        "approved_auth_count",
        "decline_count",
        "consecutive_decline_count",
        "suspension_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert "last_decline_reason" in data
    assert "deactivated_reason" in data


def assert_authorization(data: dict):
    _assert_common(data, "Authorization")
    assert data["status"] in [s.value for s in AuthorizationStatus]
    assert isinstance(data["amount_cents"], int)
    assert "declined_reason" in data


def assert_dispute(data: dict):
    _assert_common(data, "Dispute")
    assert data["status"] in [s.value for s in DisputeStatus]
    assert data["reason"] in [s.value for s in DisputeReason]
    assert isinstance(data["amount_cents"], int)
    assert is_valid_uuid(data.get("card_account_id", ""))


def assert_merchant_program(data: dict):
    _assert_common(data, "MerchantProgram")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["max_auth_amount_cents"], int)


def assert_enrollment(data: dict):
    _assert_common(data, "MerchantCardProgram")
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_transit_operator(data: dict):
    _assert_common(data, "TransitOperator")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["flat_fare_cents"], int)
    assert isinstance(data["express_cap_cents"], int)


def assert_transit_allowlist_entry(data: dict):
    # Append-only: id + created_at only, NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "TransitAllowlist must not carry updated_at"
    assert "version" not in data, "TransitAllowlist must not carry version"
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_token_event(data: dict):
    # Append-only: id + created_at only, NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "TokenEvent must not carry updated_at"
    assert "version" not in data, "TokenEvent must not carry version"
    assert data["event_type"] in (
        "PROVISIONING",
        "ACTIVATION",
        "AUTHORIZATION_APPROVED",
        "AUTHORIZATION_DECLINED",
        "SUSPENSION",
        "RESUMPTION",
        "DEACTIVATION",
        "DEVICE_BINDING_LOST",
    )


def assert_posture(device: dict, expected: str):
    """Domain invariant: posture derives from is_lost/passcode_enabled only."""
    if device["is_lost"]:
        derived = "LOST"
    elif not device["passcode_enabled"]:
        derived = "DEGRADED"
    else:
        derived = "HEALTHY"
    assert device["security_posture"] == expected == derived, (
        f"posture {device['security_posture']} != expected {expected} "
        f"(derived {derived})"
    )
