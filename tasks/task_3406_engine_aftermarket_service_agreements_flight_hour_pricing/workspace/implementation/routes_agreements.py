"""ServiceAgreement lifecycle: draft, activate, renegotiate, amend (OCC),
enroll; plus agreement reads and nested statement/snapshot lists."""
from decimal import Decimal

from flask import Blueprint

from authz import current_caller, require_roles
from calc import recompute_engine_removal
from envelope import paginate, pagination_params, success
from errors import api_err
from serialize import agreement_json, engine_json, snapshot_json, statement_json
from storage import DB, new_id, next_seq, now, touch
from validate import (
    as_datetime,
    as_enum,
    as_int,
    as_number,
    as_str,
    as_str_list,
    body,
    opt_field,
    req_field,
)

bp = Blueprint("agreements", __name__)

SOURCING_CLASSES = {"NEW", "REPAIRED", "USM"}


def get_agreement_or_404(agreement_id):
    agreement = DB["agreements"].get(agreement_id)
    if agreement is None:
        raise api_err("ERR_AGREEMENT_NOT_FOUND", "agreement does not exist")
    return agreement


def _validate_terms(data, partial):
    """Validate agreement commercial terms. When partial is True, only fields
    present in the payload are validated (amend); otherwise all are required.
    Returns a dict of validated values keyed by field name."""
    out = {}

    def present(name):
        return name in data and data[name] is not None

    def need(name):
        if partial:
            return present(name)
        return True

    if need("contract_ref"):
        out["contract_ref"] = as_str(req_field(data, "contract_ref"), "contract_ref")
    if need("base_rate_per_fh_usd"):
        rate = as_number(req_field(data, "base_rate_per_fh_usd"), "base_rate_per_fh_usd")
        if rate <= 0:
            raise api_err("ERR_INVALID_REQUEST", "base_rate_per_fh_usd must be > 0")
        out["base_rate_per_fh_usd"] = rate
    if need("escalation_pct"):
        esc = as_number(req_field(data, "escalation_pct"), "escalation_pct")
        if esc < 0:
            raise api_err("ERR_INVALID_REQUEST", "escalation_pct must be >= 0")
        out["escalation_pct"] = esc
    if need("escalation_anchor_date"):
        out["escalation_anchor_date"] = as_datetime(
            req_field(data, "escalation_anchor_date"), "escalation_anchor_date")
    if need("start_date"):
        out["start_date"] = as_datetime(req_field(data, "start_date"), "start_date")
    if need("end_date"):
        out["end_date"] = as_datetime(req_field(data, "end_date"), "end_date")
    if need("allowed_sourcing_classes"):
        classes = as_str_list(
            req_field(data, "allowed_sourcing_classes"), "allowed_sourcing_classes")
        if len(classes) == 0:
            raise api_err("ERR_INVALID_REQUEST", "allowed_sourcing_classes must be non-empty")
        for c in classes:
            if c not in SOURCING_CLASSES:
                raise api_err(
                    "ERR_INVALID_REQUEST",
                    "allowed_sourcing_classes entries must be in NEW/REPAIRED/USM")
        out["allowed_sourcing_classes"] = classes
    if need("max_workscope_cost_usd"):
        cap = as_number(req_field(data, "max_workscope_cost_usd"), "max_workscope_cost_usd")
        if cap <= 0:
            raise api_err("ERR_INVALID_REQUEST", "max_workscope_cost_usd must be > 0")
        out["max_workscope_cost_usd"] = cap
    return out


@bp.route("/api/agreements", methods=["POST"])
def create_agreement():
    require_roles("ContractManager")
    data = body()
    terms = _validate_terms(data, partial=False)
    if any(a["contract_ref"] == terms["contract_ref"] for a in DB["agreements"].values()):
        raise api_err("ERR_DUPLICATE_RESOURCE", "contract_ref already registered")
    ts = now()
    agreement = {
        "id": new_id(),
        "contract_ref": terms["contract_ref"],
        "base_rate_per_fh_usd": terms["base_rate_per_fh_usd"],
        "escalation_pct": terms["escalation_pct"],
        "escalation_anchor_date": terms["escalation_anchor_date"],
        "start_date": terms["start_date"],
        "end_date": terms["end_date"],
        "allowed_sourcing_classes": terms["allowed_sourcing_classes"],
        "max_workscope_cost_usd": terms["max_workscope_cost_usd"],
        "status": "DRAFT",
        "billed_to_date_usd": Decimal(0),
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["agreements"][agreement["id"]] = agreement
    return success(agreement_json(agreement), 201)


@bp.route("/api/agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    require_roles("ContractManager")
    agreement = get_agreement_or_404(agreement_id)
    clock = now()
    if agreement["status"] != "DRAFT" or not (
            agreement["start_date"] <= clock < agreement["end_date"]):
        raise api_err(
            "ERR_INVALID_STATE",
            "activation requires DRAFT and the logical clock inside the contract term")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return success(agreement_json(agreement), 200)


@bp.route("/api/agreements/<agreement_id>/open-renegotiation", methods=["POST"])
def open_renegotiation(agreement_id):
    require_roles("ContractManager")
    agreement = get_agreement_or_404(agreement_id)
    if agreement["status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE", "renegotiation can only open from ACTIVE")
    agreement["status"] = "RENEGOTIATION"
    touch(agreement)
    return success(agreement_json(agreement), 200)


@bp.route("/api/agreements/<agreement_id>/amend", methods=["POST"])
def amend_agreement(agreement_id):
    require_roles("ContractManager")
    agreement = get_agreement_or_404(agreement_id)
    data = body()
    expected = as_int(req_field(data, "expected_agreement_version"),
                      "expected_agreement_version")
    terms = _validate_terms(data, partial=True)
    terms.pop("contract_ref", None)  # contract_ref is not amendable
    terms.pop("start_date", None)    # start_date is not amendable
    if agreement["status"] != "RENEGOTIATION":
        raise api_err("ERR_AGREEMENT_NOT_IN_RENEGOTIATION",
                      "amend requires the agreement in RENEGOTIATION")
    if expected != agreement["version"]:
        raise api_err("ERR_STALE_VERSION", "agreement version has advanced")
    for key, value in terms.items():
        agreement[key] = value
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return success(agreement_json(agreement), 200)


@bp.route("/api/agreements/<agreement_id>/enroll", methods=["POST"])
def enroll_engine(agreement_id):
    require_roles("ContractManager")
    agreement = get_agreement_or_404(agreement_id)
    data = body()
    engine_id = as_str(req_field(data, "engine_id"), "engine_id")
    hours = as_number(req_field(data, "assumed_annual_hours"), "assumed_annual_hours")
    if hours <= 0:
        raise api_err("ERR_INVALID_REQUEST", "assumed_annual_hours must be > 0")
    acpm = as_int(req_field(data, "assumed_cycles_per_month"), "assumed_cycles_per_month")
    if acpm <= 0:
        raise api_err("ERR_INVALID_REQUEST", "assumed_cycles_per_month must be a positive integer")
    engine = DB["engines"].get(engine_id)
    if engine is None:
        raise api_err("ERR_ENGINE_NOT_FOUND", "engine does not exist")
    if agreement["status"] != "ACTIVE":
        raise api_err("ERR_AGREEMENT_NOT_ACTIVE", "enrollment requires an ACTIVE agreement")
    if engine["agreement_id"] is not None:
        raise api_err("ERR_ENGINE_ALREADY_ENROLLED", "engine already belongs to an agreement")
    if engine["status"] != "IN_SERVICE":
        raise api_err("ERR_ENGINE_IN_SHOP", "engine is not IN_SERVICE")
    engine["agreement_id"] = agreement["id"]
    engine["assumed_annual_hours"] = hours
    engine["assumed_cycles_per_month"] = acpm
    engine["enrolled_at"] = now()
    recompute_engine_removal(engine)
    touch(engine)
    return success(engine_json(engine), 200)


@bp.route("/api/agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    current_caller()
    return success(agreement_json(get_agreement_or_404(agreement_id)), 200)


@bp.route("/api/agreements/<agreement_id>/billing-statements", methods=["GET"])
def list_agreement_statements(agreement_id):
    current_caller()
    get_agreement_or_404(agreement_id)
    limit, offset = pagination_params()
    statements = sorted(
        (s for s in DB["statements"].values() if s["agreement_id"] == agreement_id),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    page, meta = paginate(statements, limit, offset)
    return success([statement_json(s) for s in page], 200, meta)


@bp.route("/api/agreements/<agreement_id>/recognition-snapshots", methods=["GET"])
def list_agreement_snapshots(agreement_id):
    current_caller()
    get_agreement_or_404(agreement_id)
    limit, offset = pagination_params()
    snaps = sorted(
        (s for s in DB["snapshots"].values() if s["agreement_id"] == agreement_id),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    page, meta = paginate(snaps, limit, offset)
    return success([snapshot_json(s) for s in page], 200, meta)
