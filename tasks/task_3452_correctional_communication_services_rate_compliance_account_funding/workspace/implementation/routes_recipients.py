"""RecipientNumber endpoints: register/get/list, verify (which doubles as the
unblock path), request-block, and attorney-privilege decisions."""

from flask import Blueprint

from core import (ALL_ROLES, DB, auth, body, err, list_response, new_entity,
                  new_verification_code, ok_obj, opt_str, pub, req_enum,
                  req_field, req_str, touch, apply_filters)

bp = Blueprint("recipients", __name__)

RELATIONSHIP_TYPES = ("FAMILY", "FRIEND", "ATTORNEY", "LEGAL_AID", "OTHER")
PRIVILEGE_AUTO = ("ATTORNEY", "LEGAL_AID")


def recipient_or_404(recipient_id):
    recipient = DB.recipients.get(recipient_id)
    if recipient is None:
        err("ERR_RECIPIENT_NUMBER_NOT_FOUND", 404,
            "RecipientNumber %s does not exist" % recipient_id)
    return recipient


@bp.post("/comm-services/recipient-numbers")
def create_recipient():
    user_id, role = auth(["AccountHolder", "FacilityStaff"])
    data = body()
    account_id = req_str(data, "account_id")
    # Tier 3 ownership: an AccountHolder registers numbers on their own
    # account's contact list only.
    if role == "AccountHolder" and user_id != account_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only register numbers on their own account")
    e164_number = req_str(data, "e164_number")
    label = req_str(data, "label")
    relationship_type = req_enum(data, "relationship_type", RELATIONSHIP_TYPES)
    if account_id not in DB.accounts:
        err("ERR_ACCOUNT_NOT_FOUND", 404,
            "Account %s does not exist" % account_id)
    for other in DB.recipients.values():
        if (other["account_id"] == account_id
                and other["e164_number"] == e164_number):
            err("ERR_INVALID_REQUEST", 400,
                "e164_number %s is already on this account's contact list"
                % e164_number)
    entity = new_entity()
    entity.update({
        "account_id": account_id,
        "e164_number": e164_number,
        "label": label,
        "relationship_type": relationship_type,
        "verification_status": "VERIFICATION_SENT",
        "verification_code": new_verification_code(),
        "consent_to_recording": False,
        "block_status": "NOT_BLOCKED",
        "block_reason": None,
        # ATTORNEY/LEGAL_AID auto-enter PRIVILEGE_REQUESTED at creation.
        "privilege_status": ("PRIVILEGE_REQUESTED"
                             if relationship_type in PRIVILEGE_AUTO else "NONE"),
        "privilege_decision_note": None,
    })
    DB.recipients[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/recipient-numbers/<recipient_id>")
def get_recipient(recipient_id):
    auth(ALL_ROLES)
    return ok_obj(pub(recipient_or_404(recipient_id)))


@bp.get("/comm-services/recipient-numbers")
def list_recipients():
    auth(ALL_ROLES)
    items = apply_filters(DB.recipients.values(),
                          ["account_id", "verification_status",
                           "block_status", "privilege_status"])
    return list_response(items, pub)


@bp.post("/comm-services/recipient-numbers/<recipient_id>/verify")
def verify_recipient(recipient_id):
    user_id, role = auth(["RecipientParty"])
    # Tier 3 ownership: a RecipientParty's X-User-ID is the number's id.
    if user_id != recipient_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "RecipientParty may only verify their own number record")
    data = body()
    code = req_field(data, "verification_code")
    recipient = recipient_or_404(recipient_id)
    if code != recipient["verification_code"]:
        err("ERR_VERIFICATION_CODE_INVALID", 422,
            "Verification code does not match")
    if data.get("consent_to_recording") is not True:
        err("ERR_CONSENT_REQUIRED", 422,
            "Recording consent must be affirmatively true")
    if recipient["block_status"] == "BLOCKED":
        # The same call doubles as the unblock path: fresh consent lifts the
        # block and clears the recorded reason.
        recipient["block_status"] = "NOT_BLOCKED"
        recipient["block_reason"] = None
        recipient["consent_to_recording"] = True
        touch(recipient)
        return ok_obj(pub(recipient))
    if recipient["verification_status"] != "VERIFICATION_SENT":
        err("ERR_INVALID_STATE", 409,
            "Number is already verified and not blocked")
    recipient["verification_status"] = "VERIFIED"
    recipient["consent_to_recording"] = True
    touch(recipient)
    return ok_obj(pub(recipient))


@bp.post("/comm-services/recipient-numbers/<recipient_id>/request-block")
def request_block(recipient_id):
    user_id, role = auth(["RecipientParty"])
    if user_id != recipient_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "RecipientParty may only block their own number record")
    data = body()
    reason = opt_str(data, "reason")
    recipient = recipient_or_404(recipient_id)
    if recipient["verification_status"] != "VERIFIED":
        err("ERR_INVALID_STATE", 409,
            "Only a verified recipient can demand a block")
    if recipient["block_status"] != "NOT_BLOCKED":
        err("ERR_INVALID_STATE", 409, "Number is already BLOCKED")
    recipient["block_status"] = "BLOCKED"
    recipient["block_reason"] = reason
    touch(recipient)
    return ok_obj(pub(recipient))


@bp.post("/comm-services/recipient-numbers/<recipient_id>/privilege-decision")
def privilege_decision(recipient_id):
    auth(["ComplianceOfficer"])
    data = body()
    decision = req_enum(data, "decision", ("VERIFY", "REVOKE"))
    note = opt_str(data, "note")
    recipient = recipient_or_404(recipient_id)
    current = recipient["privilege_status"]
    if decision == "VERIFY":
        if current != "PRIVILEGE_REQUESTED":
            err("ERR_INVALID_STATE", 409,
                "VERIFY requires privilege_status PRIVILEGE_REQUESTED")
        recipient["privilege_status"] = "PRIVILEGED"
    else:  # REVOKE
        if current not in ("PRIVILEGE_REQUESTED", "PRIVILEGED"):
            err("ERR_INVALID_STATE", 409,
                "REVOKE requires privilege_status PRIVILEGE_REQUESTED or "
                "PRIVILEGED")
        recipient["privilege_status"] = "REVOKED"
    recipient["privilege_decision_note"] = note
    touch(recipient)
    return ok_obj(pub(recipient))
