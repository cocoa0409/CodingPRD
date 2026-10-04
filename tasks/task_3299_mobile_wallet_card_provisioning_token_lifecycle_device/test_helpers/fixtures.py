"""Composite setup helpers. Every fixture builds preconditions from scratch via
PRD-declared endpoints (the server is restarted before every test, so each test
starts against an empty database)."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_START, GOOD_CODE_1, GOOD_CODE_2
from .factories import (
    create_agreement_payload,
    create_authorization_payload,
    create_card_account_payload,
    create_card_artifact_payload,
    create_cardholder_payload,
    create_device_payload,
    create_issuer_payload,
    create_provisioning_session_payload,
)
from .test_users import (
    TEST_USERS,
    make_cardholder_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["issuer_operator_headers"]
DESK = TEST_USERS["customer_service_headers"]


def reset_clock(api: ApiClient, at: str = CLOCK_START):
    """Pin the logical clock. Startup default is already 2026-09-01T00:00:00Z;
    we set it explicitly so tests never depend on wall-clock or prior state."""
    resp = api.set_clock(at, None)
    get_success_data(resp)


def setup_cardholder(api: ApiClient, email: str = "ada@example.com",
                     name: str = "Ada Byers", phone: str = "+15550001001") -> dict:
    resp = api.create_cardholder(
        create_cardholder_payload(legal_name=name, email=email, phone=phone), None
    )
    return get_success_data(resp)


def setup_issuer_active(api: ApiClient, *, fee_bps: int = 150, fee_cap_cents: int = 500,
                        fee_floor_cents: int = 0, express_supported: bool = True,
                        issuer_name: str = "Meridian Bank") -> tuple:
    """Issuer + agreement, both ACTIVE. Returns (issuer, agreement)."""
    issuer = get_success_data(
        api.create_issuer(create_issuer_payload(issuer_name=issuer_name), ADMIN)
    )
    agreement = get_success_data(
        api.create_agreement(
            create_agreement_payload(
                issuer["id"],
                fee_bps=fee_bps,
                fee_cap_cents=fee_cap_cents,
                fee_floor_cents=fee_floor_cents,
                express_transit_supported=express_supported,
            ),
            ADMIN,
        )
    )
    get_success_data(api.activate_agreement(agreement["id"], ADMIN))
    issuer = get_success_data(api.activate_issuer(issuer["id"], ADMIN))
    return issuer, agreement


def setup_device(api: ApiClient, cardholder: dict, *, serial: str = "SN-001",
                 secure: bool = True, biometric: bool = True) -> dict:
    """Device owned by the cardholder; secure=True enables passcode (+ biometric)."""
    ch_headers = make_cardholder_headers(cardholder["id"])
    device = get_success_data(
        api.create_device(
            create_device_payload(cardholder["id"], device_serial=serial), ch_headers
        )
    )
    if secure:
        device = get_success_data(
            api.set_device_security(
                device["id"],
                {"passcode_enabled": True, "biometric_enabled": biometric},
                ch_headers,
            )
        )
    return device


def setup_account_and_artifact(api: ApiClient, cardholder: dict, issuer: dict,
                               *, card_product: str = "TRANSIT",
                               pan_last4: str = "4242") -> tuple:
    account = get_success_data(
        api.create_card_account(
            create_card_account_payload(
                cardholder["id"], issuer["id"], card_product=card_product,
                fpan_last4=pan_last4,
            ),
            OPERATOR,
        )
    )
    artifact = get_success_data(
        api.create_card_artifact(
            create_card_artifact_payload(account["id"], pan_last4=pan_last4), OPERATOR
        )
    )
    return account, artifact


def open_session(api: ApiClient, device: dict, artifact: dict, cardholder: dict,
                 *, idem_key: str = "prov-1") -> dict:
    ch_headers = make_cardholder_headers(cardholder["id"])
    return get_success_data(
        api.create_provisioning_session(
            device["id"],
            create_provisioning_session_payload(artifact["id"], idempotency_key=idem_key),
            ch_headers,
        )
    )


def verify_session_twice(api: ApiClient, device: dict, session: dict,
                         cardholder: dict) -> dict:
    """Two successful challenges move the session to VERIFIED. Returns the
    session after the second verify (with current version)."""
    ch_headers = make_cardholder_headers(cardholder["id"])
    get_success_data(
        api.verify_session(
            device["id"], session["id"],
            {"method": "OTP_TEXT", "code": GOOD_CODE_1}, ch_headers,
        )
    )
    get_success_data(
        api.verify_session(
            device["id"], session["id"],
            {"method": "ISSUER_APP", "code": GOOD_CODE_2}, ch_headers,
        )
    )
    return get_success_data(api.get_provisioning_session(session["id"]))


def tokenize(api: ApiClient, device: dict, session: dict, cardholder: dict,
             *, express: bool = False) -> dict:
    """Tokenize a VERIFIED session with its current version. Returns the token."""
    ch_headers = make_cardholder_headers(cardholder["id"])
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    payload = {"expected_session_version": fresh["version"]}
    if express:
        payload["express_transit_enabled"] = True
    return get_success_data(
        api.tokenize_session(device["id"], session["id"], payload, ch_headers)
    )


def setup_provisioned_token(api: ApiClient, *, fee_bps: int = 150,
                            fee_cap_cents: int = 500, fee_floor_cents: int = 0,
                            express_supported: bool = True,
                            card_product: str = "TRANSIT",
                            express_token: bool = False,
                            secure: bool = True) -> dict:
    """Full happy-path chain: clock pinned, cardholder, ACTIVE issuer with
    ACTIVE agreement, HEALTHY device, OPEN account, artifact, verified session,
    ACTIVE token. Returns a namespace dict with every entity."""
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, agreement = setup_issuer_active(
        api, fee_bps=fee_bps, fee_cap_cents=fee_cap_cents,
        fee_floor_cents=fee_floor_cents, express_supported=express_supported,
    )
    device = setup_device(api, ch, secure=secure)
    account, artifact = setup_account_and_artifact(
        api, ch, issuer, card_product=card_product
    )
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    token = tokenize(api, device, session, ch, express=express_token)
    return {
        "cardholder": ch,
        "issuer": issuer,
        "agreement": agreement,
        "device": device,
        "account": account,
        "artifact": artifact,
        "session": session,
        "token": token,
    }


def provision_second_token(api: ApiClient, ns: dict, *, pan_last4: str = "5555",
                           idem_key: str = "prov-2", express: bool = False) -> dict:
    """Provision a second token on the same device/account via a new artifact
    and a new session. Returns the new token; mutates ns with art2/session2."""
    artifact2 = get_success_data(
        api.create_card_artifact(
            create_card_artifact_payload(ns["account"]["id"], pan_last4=pan_last4,
                                         expiry="0931"),
            OPERATOR,
        )
    )
    session2 = open_session(api, ns["device"], artifact2, ns["cardholder"],
                            idem_key=idem_key)
    session2 = verify_session_twice(api, ns["device"], session2, ns["cardholder"])
    token2 = tokenize(api, ns["device"], session2, ns["cardholder"], express=express)
    ns["artifact2"] = artifact2
    ns["session2"] = session2
    ns["token2"] = token2
    return token2


def authorize(api: ApiClient, token: dict, *, amount_cents: int = 1000,
              cryptogram: str = "cgm-1", merchant_id: str = "m-1",
              merchant_category: str = "GENERAL", biometric_verified: bool = True,
              express_mode: bool = False, transit_operator_id=None):
    """Raw authorize call — returns the Response (success or error)."""
    payload = create_authorization_payload(
        cryptogram=cryptogram,
        amount_cents=amount_cents,
        merchant_id=merchant_id,
        merchant_category=merchant_category,
        biometric_verified=biometric_verified,
        express_mode=express_mode,
    )
    if transit_operator_id is not None:
        payload["transit_operator_id"] = transit_operator_id
    return api.authorize(token["id"], payload, OPERATOR)


def approved_authorization(api: ApiClient, token: dict, *, amount_cents: int = 1000,
                           cryptogram: str = "cgm-ok", merchant_id: str = "m-1") -> dict:
    resp = authorize(api, token, amount_cents=amount_cents, cryptogram=cryptogram,
                     merchant_id=merchant_id)
    return get_success_data(resp)


def setup_token_with_approved_auth(api: ApiClient, *, amount_cents: int = 10000,
                                   cryptogram: str = "cgm-ok", **kwargs) -> dict:
    """Standard provisioned token plus one APPROVED authorization."""
    ns = setup_provisioned_token(api, **kwargs)
    auth = approved_authorization(api, ns["token"], amount_cents=amount_cents,
                                  cryptogram=cryptogram)
    ns["authorization"] = auth
    return ns
