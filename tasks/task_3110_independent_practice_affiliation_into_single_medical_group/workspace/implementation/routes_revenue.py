"""Routes: collection batches and distribution statements."""

from flask import Blueprint, request

from db import store
from errors import (
    err_dup_batch,
    err_dup_statement,
    err_invalid,
    err_no_effective,
    err_not_found,
    err_practice_not_affiliated,
    err_sod,
    err_stale,
    err_transition,
    err_unsettled,
)
from middleware import get_context, require_roles
from response import created, new_entity, ok, paginate, parse_pagination, touch
from services import (
    compute_final,
    compute_hold_carry,
    compute_provisional,
    get_executed_agreement,
    period_batches,
    practice_has_effective_enrollment,
)
from validate import body_json, require_int, require_period, require_str

bp = Blueprint("revenue", __name__)


# ---------------------------------------------------------------------------
# CollectionBatch
# ---------------------------------------------------------------------------

@bp.route("/api/collection-batches", methods=["POST"])
def create_batch():
    require_roles("DistributionAccountant")
    data = body_json()
    practice_id = require_str(data, "practice_id")
    payer_contract_id = require_str(data, "payer_contract_id")
    period = require_period(data, "period")
    posted_amount_cents = require_int(data, "posted_amount_cents")
    if posted_amount_cents <= 0:
        raise err_invalid("posted_amount_cents must be > 0")
    practice = store.practices.get(practice_id)
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    contract = store.payer_contracts.get(payer_contract_id)
    if contract is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    if practice["status"] not in ("AFFILIATED", "DEPARTING"):
        raise err_practice_not_affiliated()
    for b in store.batches.values():
        if (
            b["practice_id"] == practice_id
            and b["payer_contract_id"] == payer_contract_id
            and b["period"] == period
        ):
            raise err_dup_batch()
    if not practice_has_effective_enrollment(practice_id, payer_contract_id):
        raise err_no_effective()
    b = new_entity()
    b.update(
        practice_id=practice_id,
        payer_contract_id=payer_contract_id,
        period=period,
        posted_amount_cents=posted_amount_cents,
        denial_amount_cents=0,
        settled_amount_cents=None,
        adjustment_total_cents=0,
        net_settled_cents=None,
        settled_by_user_id=None,
        status="POSTED",
    )
    store.batches[b["id"]] = b
    return created(b)


@bp.route("/api/collection-batches", methods=["GET"])
def list_batches():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.batches.values())
    pid = request.args.get("practice_id")
    if pid is not None:
        items = [b for b in items if b["practice_id"] == pid]
    cid = request.args.get("payer_contract_id")
    if cid is not None:
        items = [b for b in items if b["payer_contract_id"] == cid]
    per = request.args.get("period")
    if per is not None:
        items = [b for b in items if b["period"] == per]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/collection-batches/<bid>", methods=["GET"])
def get_batch(bid):
    get_context()
    b = store.batches.get(bid)
    if b is None:
        raise err_not_found("BATCH", "Collection batch not found")
    return ok(b)


@bp.route("/api/collection-batches/<bid>/settle", methods=["POST"])
def settle_batch(bid):
    user_id, _role = require_roles("DistributionAccountant")
    data = body_json()
    if "denial_amount_cents" not in data:
        raise err_invalid("denial_amount_cents is required")
    denial = require_int(data, "denial_amount_cents")
    b = store.batches.get(bid)
    if b is None:
        raise err_not_found("BATCH", "Collection batch not found")
    if b["status"] != "POSTED":
        raise err_transition("Batch is not POSTED")
    if denial < 0 or denial > b["posted_amount_cents"]:
        raise err_invalid("denial_amount_cents must be in [0, posted_amount_cents]")
    b["status"] = "SETTLED"
    b["denial_amount_cents"] = denial
    b["settled_amount_cents"] = b["posted_amount_cents"] - denial
    b["net_settled_cents"] = b["settled_amount_cents"] + b["adjustment_total_cents"]
    b["settled_by_user_id"] = user_id
    touch(b)
    return ok(b)


@bp.route("/api/collection-batches/<bid>/adjust", methods=["POST"])
def adjust_batch(bid):
    require_roles("DistributionAccountant")
    data = body_json()
    if "adjustment_cents" not in data:
        raise err_invalid("adjustment_cents is required")
    delta = require_int(data, "adjustment_cents")
    b = store.batches.get(bid)
    if b is None:
        raise err_not_found("BATCH", "Collection batch not found")
    if b["status"] not in ("SETTLED", "ADJUSTED"):
        raise err_transition("Batch must be SETTLED or ADJUSTED")
    if delta == 0:
        raise err_invalid("adjustment_cents must be non-zero")
    b["adjustment_total_cents"] += delta
    b["net_settled_cents"] = b["settled_amount_cents"] + b["adjustment_total_cents"]
    b["status"] = "ADJUSTED"
    touch(b)
    return ok(b)


# ---------------------------------------------------------------------------
# DistributionStatement
# ---------------------------------------------------------------------------

def _group_of_practice(practice):
    return store.medical_groups.get(practice["medical_group_id"])


@bp.route("/api/distribution-statements", methods=["POST"])
def create_statement():
    require_roles("DistributionAccountant")
    data = body_json()
    practice_id = require_str(data, "practice_id")
    period = require_period(data, "period")
    practice = store.practices.get(practice_id)
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] not in ("AFFILIATED", "DEPARTING"):
        raise err_practice_not_affiliated()
    for s in store.statements.values():
        if s["practice_id"] == practice_id and s["period"] == period:
            raise err_dup_statement()
    group = _group_of_practice(practice)
    agreement = get_executed_agreement(practice_id)
    gross, fee, net = compute_provisional(group, agreement, practice_id, period)
    s = new_entity()
    s.update(
        practice_id=practice_id,
        period=period,
        status="PROVISIONAL_ISSUED",
        provisional_gross_cents=gross,
        provisional_fee_cents=fee,
        provisional_net_cents=net,
        gross_collections_cents=None,
        shared_services_fee_cents=None,
        net_distribution_cents=None,
        carried_forward_in_cents=None,
        payable_total_cents=None,
        payout_cents=None,
        carried_forward_out_cents=None,
        finalized_by_user_id=None,
    )
    store.statements[s["id"]] = s
    return created(s)


@bp.route("/api/distribution-statements", methods=["GET"])
def list_statements():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.statements.values())
    pid = request.args.get("practice_id")
    if pid is not None:
        items = [s for s in items if s["practice_id"] == pid]
    per = request.args.get("period")
    if per is not None:
        items = [s for s in items if s["period"] == per]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/distribution-statements/<sid>", methods=["GET"])
def get_statement(sid):
    get_context()
    s = store.statements.get(sid)
    if s is None:
        raise err_not_found("STATEMENT", "Statement not found")
    return ok(s)


def _recompute_final_fields(s):
    practice = store.practices.get(s["practice_id"])
    group = _group_of_practice(practice)
    agreement = get_executed_agreement(s["practice_id"])
    gross, fee, net = compute_final(group, agreement, s["practice_id"], s["period"])
    carried_in, payable_total, payout, carry_out = compute_hold_carry(
        group, s["practice_id"], s["period"], net
    )
    s["gross_collections_cents"] = gross
    s["shared_services_fee_cents"] = fee
    s["net_distribution_cents"] = net
    s["carried_forward_in_cents"] = carried_in
    s["payable_total_cents"] = payable_total
    s["payout_cents"] = payout
    s["carried_forward_out_cents"] = carry_out


@bp.route("/api/distribution-statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    user_id, _role = require_roles("GroupFinancialController")
    s = store.statements.get(sid)
    if s is None:
        raise err_not_found("STATEMENT", "Statement not found")
    if s["status"] != "PROVISIONAL_ISSUED":
        raise err_transition("Statement is not PROVISIONAL_ISSUED")
    practice = store.practices.get(s["practice_id"])
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] not in ("AFFILIATED", "DEPARTING"):
        raise err_practice_not_affiliated()
    batches = period_batches(s["practice_id"], s["period"])
    for b in batches:
        if b["status"] == "POSTED":
            raise err_unsettled()
    for b in batches:
        if b["settled_by_user_id"] is not None and b["settled_by_user_id"] == user_id:
            raise err_sod()
    _recompute_final_fields(s)
    s["status"] = "FINAL_ISSUED"
    s["finalized_by_user_id"] = user_id
    touch(s)
    return ok(s)


@bp.route("/api/distribution-statements/<sid>/amend", methods=["POST"])
def amend_statement(sid):
    require_roles("GroupFinancialController")
    data = body_json()
    if "expected_statement_version" not in data:
        raise err_invalid("expected_statement_version is required")
    expected = require_int(data, "expected_statement_version")
    s = store.statements.get(sid)
    if s is None:
        raise err_not_found("STATEMENT", "Statement not found")
    if expected != s["version"]:
        raise err_stale()
    if s["status"] not in ("FINAL_ISSUED", "REISSUED", "AMENDED"):
        raise err_transition("Statement must be FINAL_ISSUED, REISSUED, or AMENDED")
    _recompute_final_fields(s)
    s["status"] = "AMENDED"
    touch(s)
    return ok(s)


@bp.route("/api/distribution-statements/<sid>/reissue", methods=["POST"])
def reissue_statement(sid):
    require_roles("GroupFinancialController")
    s = store.statements.get(sid)
    if s is None:
        raise err_not_found("STATEMENT", "Statement not found")
    if s["status"] != "AMENDED":
        raise err_transition("Statement is not AMENDED")
    s["status"] = "REISSUED"
    touch(s)
    return ok(s)
