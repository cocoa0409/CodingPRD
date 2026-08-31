"""Credentials and the equipment cabinet."""
from __future__ import annotations

from flask import Blueprint

from calc import (KIT_TYPES, apply_issuance_terms, apply_renewal_terms,
                  compute_settlement, core_active_count, credential_of,
                  recompute_readiness, recompute_trainee_tallies,
                  refresh_refresher_hours, renewal_tier_and_requirement,
                  select_asset)
from cascade import (refresh_program, revoke_credential, suspend_credential)
from errors import ApiError
from store import new_row, sorted_rows, store, touch
from util import D
from web import (body, f_enum, f_id, f_int, f_str, ok_row, paginate, q_enum,
                 q_str, require, require_any, resolve)

bp = Blueprint("credentials", __name__)

CREDENTIAL_STATUS = ("ACTIVE", "GRACE", "EXPIRED", "SUSPENDED", "REVOKED")
ASSET_STATUS = ("IN_STOCK", "ISSUED", "RETIRED", "LOST")
ISSUANCE_STATUS = ("ISSUED", "RETURNED", "LOST_WRITTEN_OFF")


# ==========================================================================
# Credential
# ==========================================================================
def _core_complete(trainee):
    recompute_trainee_tallies(trainee)
    if int(trainee["passed_core_count"]) != core_active_count():
        return False
    for c in store.module_completions.values():
        if c["trainee_id"] == trainee["id"] and c["status"] == "SKILLS_PENDING":
            return False
    return True


@bp.post("/credentials")
def mint_credential():
    user_id, role = require("ProgramCoordinator")
    data = body()
    trainee_id = f_id(data, "trainee_id")
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    cohort = store.cohorts.get(trainee["cohort_id"])

    if cohort is None or cohort["status"] != "GRADUATION_REVIEW":
        raise ApiError("ERR_COHORT_NOT_IN_REVIEW",
                       "The trainee's cohort is not in GRADUATION_REVIEW.")
    if cohort.get("graduation_reviewer_user_id") is not None and \
            user_id == cohort["graduation_reviewer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The graduation reviewer may not mint this cohort's credentials.")
    if not _core_complete(trainee):
        raise ApiError("ERR_CORE_MODULES_INCOMPLETE",
                       "The trainee has not completed every core active module.")
    if trainee["enrollment_status"] != "GRADUATED" or credential_of(trainee_id) is not None:
        raise ApiError("ERR_CREDENTIAL_ALREADY_ISSUED",
                       "A credential may only be minted once, for a GRADUATED trainee.")

    cohort_trainee_ids = set(t["id"] for t in store.trainees.values()
                             if t.get("cohort_id") == cohort["id"])
    sequence = sum(1 for c in store.credentials.values()
                   if c["trainee_id"] in cohort_trainee_ids) + 1
    row = new_row(
        "Credential",
        trainee_id=trainee_id,
        credential_number="%s-%04d" % (cohort["cohort_code"], sequence),
        issued_on=store.now_iso(),
        term_start_on=store.now_iso(),
        expires_on=None,
        grace_ends_on=None,
        reinstatement_count=0,
        renewal_tier=None,
        required_refresher_hours=None,
        refresher_hours_in_term=0.0,
        issued_by_user_id=user_id,
        status="ACTIVE",
    )
    apply_issuance_terms(row)
    store.credentials[row["id"]] = row
    trainee["currency_status"] = "CURRENT"
    touch(trainee)
    return ok_row(row, 201)


@bp.get("/credentials")
def list_credentials():
    require_any()
    trainee_id = q_str("trainee_id")
    status = q_enum("status", CREDENTIAL_STATUS)
    rows = []
    for c in store.credentials.values():
        if trainee_id is not None and c["trainee_id"] != trainee_id:
            continue
        if status is not None and c["status"] != status:
            continue
        rows.append(c)
    return paginate(rows)


@bp.get("/credentials/<credential_id>")
def read_credential(credential_id):
    require_any()
    cred = resolve(store.credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")
    return ok_row(cred)


@bp.post("/credentials/<credential_id>/status")
def credential_status(credential_id):
    require("ProgramCoordinator")
    cred = resolve(store.credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")
    data = body()
    action = f_enum(data, "action", ("RENEW", "SUSPEND", "REINSTATE", "REVOKE"))
    trainee = store.trainees.get(cred["trainee_id"])

    # The refresher ledger is refreshed from primary evidence before any
    # action is evaluated (PRD 3.6).
    refresh_refresher_hours(cred)

    current = cred["status"]
    if action == "RENEW":
        if current not in ("ACTIVE", "GRACE", "EXPIRED"):
            raise ApiError("ERR_INVALID_STATE",
                           "A credential in %s cannot be renewed." % current)
        if trainee is None or trainee["enrollment_status"] != "GRADUATED":
            raise ApiError("ERR_INVALID_STATE",
                           "Renewal requires a GRADUATED trainee.")
        tier, required = renewal_tier_and_requirement(cred)
        hours = D(cred.get("refresher_hours_in_term") or 0)
        if hours < required:
            raise ApiError("ERR_REFRESHER_HOURS_INSUFFICIENT",
                           "Refresher hours in term are below the requirement.")
        apply_renewal_terms(cred, tier, required)
        cred["status"] = "ACTIVE"
        touch(cred)
        if current == "GRACE" and trainee["currency_status"] == "LAPSING":
            trainee["currency_status"] = "CURRENT"
        elif current == "EXPIRED" and trainee["currency_status"] == "LAPSED":
            trainee["currency_status"] = "CURRENT"
        recompute_readiness(trainee)
        touch(trainee)
    elif action == "SUSPEND":
        if current != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an ACTIVE credential can be suspended.")
        suspend_credential(cred, trainee)
    elif action == "REINSTATE":
        if current != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a SUSPENDED credential can be reinstated.")
        if trainee is None or trainee["enrollment_status"] != "GRADUATED":
            raise ApiError("ERR_INVALID_STATE",
                           "Reinstatement requires a GRADUATED trainee.")
        recompute_trainee_tallies(trainee)
        if int(trainee["passed_core_count"]) != core_active_count():
            raise ApiError("ERR_INVALID_STATE",
                           "Reinstatement requires every core active module passed.")
        cred["status"] = "ACTIVE"
        cred["term_start_on"] = store.now_iso()
        touch(cred)
        if trainee["currency_status"] == "LAPSED":
            trainee["currency_status"] = "CURRENT"
        recompute_readiness(trainee)
        touch(trainee)
    else:  # REVOKE
        if current == "REVOKED":
            raise ApiError("ERR_INVALID_STATE", "The credential is already REVOKED.")
        revoke_credential(cred, trainee)
    return ok_row(cred)


# ==========================================================================
# EquipmentAsset
# ==========================================================================
@bp.post("/equipment-assets")
def create_asset():
    require("LogisticsOfficer")
    data = body()
    program_id = f_id(data, "program_id")
    asset_tag = f_str(data, "asset_tag")
    kit_type = f_enum(data, "kit_type", KIT_TYPES)
    unit_value = f_int(data, "unit_value_cents", min_val=1)
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    for a in store.equipment_assets.values():
        if a["asset_tag"] == asset_tag:
            raise ApiError("ERR_DUPLICATE_GLOBAL_KEY", "asset_tag is already used.")
    row = new_row(
        "EquipmentAsset",
        program_id=program_id,
        asset_tag=asset_tag,
        kit_type=kit_type,
        unit_value_cents=unit_value,
        issue_count=0,
        condition="NEW",
        status="IN_STOCK",
    )
    store.equipment_assets[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/equipment-assets")
def list_assets():
    require_any()
    program_id = q_str("program_id")
    kit_type = q_enum("kit_type", KIT_TYPES)
    status = q_enum("status", ASSET_STATUS)
    rows = []
    for a in store.equipment_assets.values():
        if program_id is not None and a["program_id"] != program_id:
            continue
        if kit_type is not None and a["kit_type"] != kit_type:
            continue
        if status is not None and a["status"] != status:
            continue
        rows.append(a)
    return paginate(rows)


@bp.get("/equipment-assets/<asset_id>")
def read_asset(asset_id):
    require_any()
    asset = resolve(store.equipment_assets, asset_id, "ERR_EQUIPMENT_ASSET_NOT_FOUND")
    return ok_row(asset)


# ==========================================================================
# EquipmentIssuance
# ==========================================================================
@bp.post("/equipment-issuances")
def create_issuance():
    user_id, role = require("LogisticsOfficer")
    data = body()
    trainee_id = f_id(data, "trainee_id")
    kit_type = f_enum(data, "kit_type", KIT_TYPES)
    expected = f_int(data, "expected_program_version")
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    program = store.programs.get(trainee["program_id"])
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")

    # 10 — optimistic concurrency on the program ledger
    if expected != int(program["version"]):
        raise ApiError("ERR_STALE_PROGRAM_VERSION",
                       "expected_program_version does not match the program's version.")
    # 26 — the volunteer must hold a live credential
    cred = credential_of(trainee_id)
    if cred is None or cred["status"] not in ("ACTIVE", "GRACE"):
        raise ApiError("ERR_CREDENTIAL_NOT_ACTIVE",
                       "The trainee does not hold a live credential.")
    # 70 — the selector's candidate pool must be non-empty
    asset = select_asset(program["id"], kit_type)
    if asset is None:
        raise ApiError("ERR_NO_ASSET_AVAILABLE",
                       "No asset of that kit type is available.")
    # 71 — at most one outstanding issuance per kit type
    for iss in store.equipment_issuances.values():
        if iss["trainee_id"] == trainee_id and iss["kit_type"] == kit_type \
                and iss["status"] == "ISSUED":
            raise ApiError("ERR_TRAINEE_ALREADY_ISSUED_KIT",
                           "The trainee already holds a kit of that type.")
    # 80 — the fiscal ceiling, evaluated last of all
    committed = int(program["equipment_committed_cents"])
    if committed + int(asset["unit_value_cents"]) > int(program["equipment_budget_cents"]):
        raise ApiError("ERR_EQUIPMENT_BUDGET_EXCEEDED",
                       "The equipment budget ceiling would be exceeded.")

    row = new_row(
        "EquipmentIssuance",
        trainee_id=trainee_id,
        asset_id=asset["id"],
        kit_type=kit_type,
        issued_on=store.now_iso(),
        returned_on=None,
        lost_reported_on=None,
        months_held=None,
        residual_pct=None,
        settlement_cents=0,
        settlement_variant=None,
        issued_by_user_id=user_id,
        status="ISSUED",
    )
    store.equipment_issuances[row["id"]] = row
    asset["status"] = "ISSUED"
    asset["issue_count"] = int(asset["issue_count"]) + 1
    touch(asset)
    refresh_program(program)
    return ok_row(row, 201)


@bp.get("/equipment-issuances")
def list_issuances():
    require_any()
    trainee_id = q_str("trainee_id")
    asset_id = q_str("asset_id")
    status = q_enum("status", ISSUANCE_STATUS)
    rows = []
    for i in store.equipment_issuances.values():
        if trainee_id is not None and i["trainee_id"] != trainee_id:
            continue
        if asset_id is not None and i["asset_id"] != asset_id:
            continue
        if status is not None and i["status"] != status:
            continue
        rows.append(i)
    return paginate(rows)


@bp.get("/equipment-issuances/<issuance_id>")
def read_issuance(issuance_id):
    require_any()
    iss = resolve(store.equipment_issuances, issuance_id, "ERR_ISSUANCE_NOT_FOUND")
    return ok_row(iss)


@bp.post("/equipment-issuances/<issuance_id>/return")
def return_issuance(issuance_id):
    require("LogisticsOfficer")
    iss = resolve(store.equipment_issuances, issuance_id, "ERR_ISSUANCE_NOT_FOUND")
    data = body()
    condition = f_enum(data, "condition", ("SERVICEABLE", "DAMAGED"))
    if iss["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED kit can be returned.")
    asset = store.equipment_assets.get(iss["asset_id"])
    iss["status"] = "RETURNED"
    iss["returned_on"] = store.now_iso()
    touch(iss)
    if asset is not None:
        asset["condition"] = condition
        asset["status"] = "IN_STOCK" if condition == "SERVICEABLE" else "RETIRED"
        touch(asset)
    trainee = store.trainees.get(iss["trainee_id"])
    program = store.programs.get(trainee["program_id"]) if trainee else None
    refresh_program(program)
    return ok_row(iss)


@bp.post("/equipment-issuances/<issuance_id>/report-lost")
def report_lost(issuance_id):
    require("LogisticsOfficer")
    iss = resolve(store.equipment_issuances, issuance_id, "ERR_ISSUANCE_NOT_FOUND")
    data = body()
    f_str(data, "note", required=False, default=None)
    if iss["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED kit can be written off.")
    asset = store.equipment_assets.get(iss["asset_id"])
    trainee = store.trainees.get(iss["trainee_id"])
    cred = credential_of(iss["trainee_id"])
    iss["status"] = "LOST_WRITTEN_OFF"
    iss["lost_reported_on"] = store.now_iso()
    compute_settlement(iss, asset, cred)
    touch(iss)
    if asset is not None:
        asset["status"] = "LOST"
        asset["condition"] = "WRITTEN_OFF"
        touch(asset)
    if trainee is not None:
        recompute_trainee_tallies(trainee)
        touch(trainee)
        refresh_program(store.programs.get(trainee["program_id"]))
    return ok_row(iss)
