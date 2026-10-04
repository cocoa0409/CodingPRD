"""RebateCertificate routes: redemption, reissue, fraud holds (PRD 3.6)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (CONTRACTOR, CUSTOMER, FINANCE_ADMIN, FRAUD_ANALYST,
                        GUEST_SERVICE, STORE_ADMIN, authenticate, get_body,
                        query_param, req_id, req_int,
                        require_account_ownership)
from response import object_response
from routes.common import paginated
from serialize import certificate_out, ledger_entry_out
from services import core, lookup, temporal

bp = Blueprint("certificates", __name__)

READ_ROLES = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]
CERT_READ = READ_ROLES + [CUSTOMER, CONTRACTOR]
TERMINAL_STATUSES = {"FULLY_REDEEMED", "VOIDED", "REISSUED"}


@bp.route("/stores/<store_id>/certificates", methods=["GET"])
def list_certificates(store_id):
    authenticate(READ_ROLES)
    lookup.store(store_id)
    account_id = query_param("account_id")
    status = query_param("status")
    records = [c for c in db.ordered(db.certificates)
               if c["store_id"] == store_id]
    if account_id is not None:
        records = [c for c in records if c["account_id"] == account_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    return paginated(records, certificate_out)


@bp.route("/stores/<store_id>/certificates/<certificate_id>", methods=["GET"])
def get_certificate(store_id, certificate_id):
    caller = authenticate(CERT_READ)
    lookup.store(store_id)
    cert = lookup.certificate_in_store(store_id, certificate_id)
    require_account_ownership(caller, cert["account_id"])
    return object_response(certificate_out(cert))


@bp.route("/stores/<store_id>/certificates/<certificate_id>/redeem",
          methods=["POST"])
def redeem_certificate(store_id, certificate_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    cert = lookup.certificate_in_store(store_id, certificate_id)
    body = get_body()
    receipt_id = req_id(body, "receipt_id")
    amount_cents = req_int(body, "amount_cents", minimum=1)

    # Body-referenced receipt: missing reference is 404.
    receipt = lookup.receipt(receipt_id)

    # Redemption checks in the order pinned by PRD 3.6.
    if cert["status"] not in ("ACTIVE", "PARTIALLY_REDEEMED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ACTIVE or PARTIALLY_REDEEMED certificate may "
                       "be redeemed")

    account = lookup.account(cert["account_id"])
    if account["status"] == "FROZEN":
        raise ApiError("ERR_ACCOUNT_FROZEN",
                       "A FROZEN account blocks redemption")

    if cert["fraud_hold"] == "HELD":
        raise ApiError("ERR_CERTIFICATE_HELD",
                       "A held certificate may not be redeemed")

    expires_at = temporal.parse_timestamp_iso(cert["expires_at"])
    if db.clock_now() >= expires_at:
        raise ApiError("ERR_CERTIFICATE_EXPIRED",
                       "The certificate expired at %s" % cert["expires_at"])

    # Store + account scoping of the redeeming receipt.
    if receipt["store_id"] != cert["store_id"] \
            or receipt["account_id"] != cert["account_id"]:
        raise ApiError("ERR_CERTIFICATE_WRONG_STORE",
                       "The certificate is redeemable only at its issuing "
                       "store against the holder's own receipts")

    # The redemption bar: certificates may never pay for further
    # rebate-eligible purchases.
    for line in core.receipt_lines_of(receipt["id"]):
        if core.match_program_item(receipt["store_id"], line["sku"],
                                   receipt) is not None:
            raise ApiError(
                "ERR_CERTIFICATE_REBATE_PURCHASE_BARRED",
                "The redeeming receipt contains a rebate-eligible line; "
                "certificates may not pay for further rebate-eligible "
                "purchases")

    if amount_cents > cert["remaining_balance_cents"]:
        raise ApiError("ERR_REDEMPTION_EXCEEDS_BALANCE",
                       "amount_cents exceeds remaining_balance_cents")

    cert["remaining_balance_cents"] -= amount_cents
    if cert["remaining_balance_cents"] == 0:
        cert["status"] = "FULLY_REDEEMED"
    else:
        cert["status"] = "PARTIALLY_REDEEMED"
    db.touch(cert)

    core.post_ledger(store, account["id"], cert["id"], "REDEMPTION",
                     -amount_cents, "redemption against receipt %s"
                     % receipt["id"])

    core.recompute_account(account)
    core.recompute_store(store)
    return object_response(certificate_out(cert))


@bp.route("/stores/<store_id>/certificates/<certificate_id>/reissue",
          methods=["POST"])
def reissue_certificate(store_id, certificate_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    cert = lookup.certificate_in_store(store_id, certificate_id)
    get_body()

    if cert["status"] != "EXPIRED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an EXPIRED certificate may be reissued")

    if db.clock_now() >= temporal.reissue_deadline(cert):
        raise ApiError("ERR_REISSUE_WINDOW_CLOSED",
                       "The 30-day reissue grace window has closed")

    account = lookup.account(cert["account_id"])
    for flag in core.account_flags(account["id"]):
        if flag["status"] == "CONFIRMED":
            raise ApiError("ERR_ACCOUNT_FRAUD_CONFIRMED",
                           "A CONFIRMED fraud flag blocks certificate "
                           "reissue")

    if cert["fraud_hold"] == "HELD":
        raise ApiError("ERR_CERTIFICATE_HELD",
                       "A held certificate may not be reissued")

    issued_at = db.clock_now()
    amount = cert["remaining_balance_cents"]

    new_cert = db.base_record()
    new_cert.update({
        "store_id": store_id,
        "account_id": account["id"],
        "submission_id": None,
        "issued_amount_cents": amount,
        "remaining_balance_cents": amount,
        "status": "ACTIVE",
        "fraud_hold": "NONE",
        "issued_at": db.logical_timestamp(),
        "expires_at": _iso(temporal.expiry_instant(store, issued_at)),
        "reissued_from_id": cert["id"],
    })
    db.certificates[new_cert["id"]] = new_cert

    cert["remaining_balance_cents"] = 0
    cert["status"] = "REISSUED"
    db.touch(cert)

    core.post_ledger(store, account["id"], new_cert["id"], "REISSUE_CREDIT",
                     amount, "reissue of certificate %s" % cert["id"])

    core.recompute_account(account)
    core.recompute_store(store)
    return object_response(certificate_out(new_cert))


def _iso(dt):
    from response import iso_timestamp
    return iso_timestamp(dt)


@bp.route("/stores/<store_id>/certificates/<certificate_id>/hold",
          methods=["POST"])
def hold_certificate(store_id, certificate_id):
    authenticate([FRAUD_ANALYST])
    lookup.store(store_id)
    cert = lookup.certificate_in_store(store_id, certificate_id)
    get_body()
    if cert["status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "A terminal certificate cannot be held")
    cert["fraud_hold"] = "HELD"
    db.touch(cert)
    return object_response(certificate_out(cert))


@bp.route("/stores/<store_id>/certificates/<certificate_id>/release",
          methods=["POST"])
def release_certificate(store_id, certificate_id):
    authenticate([FRAUD_ANALYST])
    lookup.store(store_id)
    cert = lookup.certificate_in_store(store_id, certificate_id)
    get_body()
    if cert["status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "A terminal certificate cannot be released")
    cert["fraud_hold"] = "RELEASED"
    db.touch(cert)
    return object_response(certificate_out(cert))


# ---------------------------------------------------------------------------
# Flat canonical reads + FK reverse reachability
# ---------------------------------------------------------------------------
@bp.route("/certificates", methods=["GET"])
def list_all_certificates():
    authenticate(READ_ROLES)
    store_id = query_param("store_id")
    account_id = query_param("account_id")
    status = query_param("status")
    submission_id = query_param("submission_id")
    reissued_from_id = query_param("reissued_from_id")
    records = db.ordered(db.certificates)
    if store_id is not None:
        records = [c for c in records if c["store_id"] == store_id]
    if account_id is not None:
        records = [c for c in records if c["account_id"] == account_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    if submission_id is not None:
        records = [c for c in records if c["submission_id"] == submission_id]
    if reissued_from_id is not None:
        records = [c for c in records
                   if c["reissued_from_id"] == reissued_from_id]
    return paginated(records, certificate_out)


@bp.route("/certificates/<certificate_id>", methods=["GET"])
def get_certificate_flat(certificate_id):
    caller = authenticate(CERT_READ)
    cert = lookup.certificate(certificate_id)
    require_account_ownership(caller, cert["account_id"])
    return object_response(certificate_out(cert))


@bp.route("/certificates/<certificate_id>/ledger-entries", methods=["GET"])
def certificate_ledger_entries(certificate_id):
    authenticate(READ_ROLES)
    cert = lookup.certificate(certificate_id)
    entries = [e for e in db.ordered(db.ledger_entries)
               if e["certificate_id"] == cert["id"]]
    return paginated(entries, ledger_entry_out)


@bp.route("/certificates/<certificate_id>/reissues", methods=["GET"])
def certificate_reissues(certificate_id):
    authenticate(READ_ROLES)
    cert = lookup.certificate(certificate_id)
    records = [c for c in db.ordered(db.certificates)
               if c["reissued_from_id"] == cert["id"]]
    return paginated(records, certificate_out)
