"""PayerContract endpoints per PRD §3.1, §2.8."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_input, ERR_CONTRACT_NOT_FOUND,
                    ERR_PROGRAM_NOT_FOUND, ERR_PAYMENT_MODEL_MISMATCH)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.resources import base_fields
from services.validation import (get_json_body, require_string, require_enum,
                                 optional_int, optional_number)

bp = Blueprint("contracts", __name__)

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "PerformanceAnalyst"]
PAYMENT_MODELS = {"CAPITATED", "SHARED_SAVINGS"}


@bp.route("/payer-contracts", methods=["POST"])
def create_contract():
    require_roles(["ContractAdministrator"])
    body = get_json_body()
    care_program_id = require_string(body, "care_program_id")
    payer_name = require_string(body, "payer_name")
    effective = require_string(body, "contract_effective_date")
    expiration = require_string(body, "contract_expiration_date")
    payment_model = require_enum(body, "payment_model", PAYMENT_MODELS)

    # Existence: body-supplied FK (validation ladder rung 4)
    program = db.care_programs.get(care_program_id)
    if program is None:
        raise err_not_found(ERR_PROGRAM_NOT_FOUND, "CareProgram")

    pmpm = optional_int(body, "pmpm_rate_cents")
    baseline = optional_int(body, "shared_savings_baseline_pmpm_cents")
    split_pct = optional_number(body, "shared_savings_split_pct")
    withhold_pct = optional_number(body, "quality_withhold_pct", 0.10)
    threshold = optional_number(body, "min_performance_threshold", 0.80)

    # Payment-model consistency (§2.8, validation ladder rung 15)
    if payment_model == "CAPITATED" and pmpm is None:
        raise err_input(ERR_PAYMENT_MODEL_MISMATCH,
                        "CAPITATED contract requires pmpm_rate_cents")
    if payment_model == "SHARED_SAVINGS" and (baseline is None or split_pct is None):
        raise err_input(ERR_PAYMENT_MODEL_MISMATCH,
                        "SHARED_SAVINGS contract requires "
                        "shared_savings_baseline_pmpm_cents and shared_savings_split_pct")

    c = base_fields()
    c.update({
        "care_program_id": care_program_id,
        "payer_name": payer_name,
        "contract_effective_date": effective,
        "contract_expiration_date": expiration,
        "payment_model": payment_model,
        "pmpm_rate_cents": pmpm,
        "shared_savings_baseline_pmpm_cents": baseline,
        "shared_savings_split_pct": split_pct,
        "quality_withhold_pct": withhold_pct,
        "min_performance_threshold": threshold,
    })
    db.payer_contracts[c["id"]] = c
    return success_object(serializers.payer_contract(c), status=201)


@bp.route("/payer-contracts", methods=["GET"])
def list_contracts():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.payer_contracts.values())
    cp = request.args.get("care_program_id")
    if cp:
        items = [c for c in items if c.get("care_program_id") == cp]
    pm = request.args.get("payment_model")
    if pm:
        items = [c for c in items if c.get("payment_model") == pm]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.payer_contract(c) for c in page],
                        limit, offset, total)


@bp.route("/payer-contracts/<contractId>", methods=["GET"])
def get_contract(contractId):
    require_roles(READ_ROLES)
    c = db.payer_contracts.get(contractId)
    if c is None:
        raise err_not_found(ERR_CONTRACT_NOT_FOUND, "PayerContract")
    return success_object(serializers.payer_contract(c))
