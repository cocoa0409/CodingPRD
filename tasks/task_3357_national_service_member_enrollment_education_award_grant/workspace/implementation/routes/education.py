from flask import Blueprint, request

import auth
import clock
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("education", __name__)

READ_ROLES = ["CNCSProgramOfficer", "TrustAdministrator", "Member"]


def _load_award_or_404(educationAwardId):
    award = db.store.education_awards.get(educationAwardId)
    if award is None:
        raise ApiError(
            "ERR_EDUCATION_AWARD_NOT_FOUND", 404, "Education award not found"
        )
    return award


@bp.route("/education-awards", methods=["GET"])
def list_education_awards():
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    items = list(db.store.education_awards.values())
    if role == "Member":
        items = [a for a in items if a["member_id"] == uid]
    # Lazy EXPIRED evaluation on read happens before filtering.
    for award in items:
        domain.maybe_expire_education_award(award)
    member_id = request.args.get("member_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/education-awards/<educationAwardId>", methods=["GET"])
def get_education_award(educationAwardId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    award = _load_award_or_404(educationAwardId)
    auth.check_member_ownership(uid, role, award["member_id"])
    domain.maybe_expire_education_award(award)
    return util.ok(serialize(award), 200)


@bp.route("/education-awards/<educationAwardId>/uses", methods=["POST"])
def create_use(educationAwardId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["Member"])
    award = db.store.education_awards.get(educationAwardId)
    if award is not None:
        auth.check_member_ownership(uid, role, award["member_id"])
    if award is None:
        raise ApiError(
            "ERR_EDUCATION_AWARD_NOT_FOUND", 404, "Education award not found"
        )
    body = util.body_json()
    use_type = body.get("use_type")
    amount = body.get("amount_cents")
    institution_title_iv = body.get("institution_title_iv")
    expected_version = body.get("expected_education_award_version")
    if use_type not in C.USE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "use_type is invalid")
    if not util.is_int(amount) or amount <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "amount_cents must be an integer greater than zero"
        )
    if not util.is_int(expected_version):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "expected_education_award_version is required",
        )
    # Tier 11: the STORED status at request start must be ISSUED/PARTIALLY_USED.
    if award["status"] not in ("ISSUED", "PARTIALLY_USED"):
        raise ApiError(
            "ERR_EDUCATION_AWARD_NOT_USABLE",
            409,
            "Education award is not usable",
        )
    # Tier 14: OCC on the education award.
    if expected_version != award["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_education_award_version does not match the award",
        )
    # Tier 22: TUITION uses require a Title IV institution.
    if use_type == "TUITION" and institution_title_iv is not True:
        raise ApiError(
            "ERR_INSTITUTION_NOT_ELIGIBLE",
            422,
            "TUITION uses require institution_title_iv == true",
        )
    # Tier 24: use deadline (equality allowed); failure flips the award EXPIRED.
    deadline = clock.parse_datetime(award["use_deadline_at"])
    if clock.now() > deadline:
        award["status"] = "EXPIRED"
        raise ApiError(
            "ERR_AWARD_USE_DEADLINE_PASSED",
            422,
            "The education award use deadline has passed",
        )
    # Tier 38: balance gate at creation.
    if amount > award["remaining_balance_cents"]:
        raise ApiError(
            "ERR_INSUFFICIENT_AWARD_BALANCE",
            422,
            "Use amount exceeds the award's remaining balance",
        )
    use = db.new_entity(
        {
            "id": util.new_id(),
            "education_award_id": educationAwardId,
            "use_type": use_type,
            "amount_cents": amount,
            "institution_title_iv": institution_title_iv,
            "decision_note": None,
            "status": "PENDING_APPROVAL",
        }
    )
    db.store.uses[use["id"]] = use
    domain.touch(award)  # use creation bumps the education award's version
    return util.ok(serialize(use), 201)


@bp.route("/education-awards/<educationAwardId>/uses", methods=["GET"])
def list_uses(educationAwardId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    award = _load_award_or_404(educationAwardId)
    auth.check_member_ownership(uid, role, award["member_id"])
    domain.maybe_expire_education_award(award)
    items = [u for u in db.store.uses.values() if u["education_award_id"] == educationAwardId]
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/education-award-uses/<useId>/decide", methods=["POST"])
def decide_use(useId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["TrustAdministrator"])
    use = db.store.uses.get(useId)
    if use is None:
        raise ApiError("ERR_USE_NOT_FOUND", 404, "Education award use not found")
    body = util.body_json()
    decision = body.get("decision")
    note = body.get("note")
    if decision not in C.USE_DECISIONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "decision must be APPROVE or DENY")
    if note is not None and not util.is_str(note):
        raise ApiError("ERR_INVALID_REQUEST", 400, "note must be a string")
    if use["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_USE_NOT_PENDING", 409, "Use is not PENDING_APPROVAL")
    award = db.store.education_awards.get(use["education_award_id"])
    if decision == "APPROVE":
        # Balance is re-validated at decide time.
        if award["remaining_balance_cents"] < use["amount_cents"]:
            raise ApiError(
                "ERR_INSUFFICIENT_AWARD_BALANCE",
                422,
                "The award's remaining balance no longer covers the use amount",
            )
        award["remaining_balance_cents"] -= use["amount_cents"]
        domain.recompute_award_status_after_balance_change(award)
        domain.touch(award)
        use["status"] = "APPROVED"
    else:
        use["status"] = "DENIED"
    use["decision_note"] = note
    domain.touch(use)
    return util.ok(serialize(use), 200)


@bp.route("/education-award-uses/<useId>/rescind", methods=["POST"])
def rescind_use(useId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["TrustAdministrator"])
    use = db.store.uses.get(useId)
    if use is None:
        raise ApiError("ERR_USE_NOT_FOUND", 404, "Education award use not found")
    body = util.body_json()
    if not util.is_str(body.get("reason")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "reason is required")
    if use["status"] != "APPROVED":
        raise ApiError("ERR_USE_NOT_PENDING", 409, "Use is not APPROVED")
    award = db.store.education_awards.get(use["education_award_id"])
    award["remaining_balance_cents"] += use["amount_cents"]
    domain.recompute_award_status_after_balance_change(award)
    domain.touch(award)
    use["status"] = "RESCINDED"
    domain.touch(use)
    return util.ok(serialize(use), 200)
