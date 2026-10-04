# =============================================================================
# Generic helpers: path resolution, list responses, row factories
# =============================================================================
import db
from errors import not_found
from response import paginate, success_list


def resolve(table, rid, error_id, label):
    row = table.get(rid)
    if row is None:
        raise not_found(error_id, f"{label} {rid} does not exist")
    return row


def resolve_device(device_id):
    return resolve(db.devices, device_id, "ERR_DEVICE_NOT_FOUND", "Device")


def resolve_issuer(issuer_id):
    return resolve(db.issuers, issuer_id, "ERR_ISSUER_NOT_FOUND", "Issuer")


def resolve_agreement(agreement_id):
    return resolve(db.issuer_agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND", "IssuerAgreement")


def resolve_card_account(account_id):
    return resolve(db.card_accounts, account_id, "ERR_CARD_ACCOUNT_NOT_FOUND", "CardAccount")


def resolve_token(token_id):
    return resolve(db.payment_tokens, token_id, "ERR_TOKEN_NOT_FOUND", "PaymentToken")


def resolve_authorization(auth_id):
    return resolve(db.authorizations, auth_id, "ERR_AUTHORIZATION_NOT_FOUND", "Authorization")


def resolve_dispute(dispute_id):
    return resolve(db.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND", "Dispute")


def resolve_program(program_id):
    return resolve(db.merchant_programs, program_id, "ERR_PROGRAM_NOT_FOUND", "MerchantProgram")


def resolve_operator(operator_id):
    return resolve(db.transit_operators, operator_id, "ERR_OPERATOR_NOT_FOUND", "TransitOperator")


def resolve_cardholder(cardholder_id):
    return resolve(db.cardholders, cardholder_id, "ERR_NOT_FOUND", "Cardholder")


def resolve_session(session_id):
    return resolve(db.provisioning_sessions, session_id, "ERR_NOT_FOUND", "ProvisioningSession")


def resolve_artifact(artifact_id):
    return resolve(db.card_artifacts, artifact_id, "ERR_NOT_FOUND", "CardArtifact")


def resolve_enrollment(enrollment_id):
    return resolve(db.merchant_card_programs, enrollment_id, "ERR_NOT_FOUND", "MerchantCardProgram")


def resolve_allowlist_entry(entry_id):
    return resolve(db.transit_allowlist, entry_id, "ERR_NOT_FOUND", "TransitAllowlist")


def check_child(parent, child, fk, error_id, label):
    """Nested ownership: child must belong to the parent in the URL path."""
    if child.get(fk) != parent["id"]:
        raise not_found(error_id, f"{label} does not belong to the parent resource")


def public(row):
    """Strip server-internal fields before serializing."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def list_response(rows, filters=None):
    """Apply optional exact-match filters, sort by created_at asc, paginate."""
    items = list(rows)
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [r for r in items if str(r.get(field)) == str(value)]
    items.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
    page, total = paginate(items)
    return success_list([public(r) for r in page], total)


def new_common_row(fields):
    now = db.get_clock()
    row = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row
