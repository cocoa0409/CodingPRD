"""OperatorDelayLedger listings (PRD 3.9): per-operator and per-program views."""

from flask import Blueprint

from constants import ROLES
from serialize import serialize_ledger
from storage import DB
from util import paginate
from validation import auth_context, get_operator, get_tmi, require_roles

bp = Blueprint("ledgers", __name__)


@bp.route("/atfm/operators/<operator_id>/delay-ledgers", methods=["GET"])
def list_operator_ledgers(operator_id):
    auth_context()
    require_roles(*ROLES)
    operator = get_operator(operator_id)
    rows = [l for l in DB["ledgers"].values() if l["operator_id"] == operator["id"]]
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return paginate([serialize_ledger(l) for l in rows])


@bp.route("/atfm/tmis/<tmi_id>/delay-ledgers", methods=["GET"])
def list_tmi_ledgers(tmi_id):
    auth_context()
    require_roles(*ROLES)
    tmi = get_tmi(tmi_id)
    rows = [l for l in DB["ledgers"].values() if l["tmi_id"] == tmi["id"]]
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return paginate([serialize_ledger(l) for l in rows])
