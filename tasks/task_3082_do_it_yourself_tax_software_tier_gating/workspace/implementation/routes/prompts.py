"""UpgradePrompt endpoints: list, acknowledge, decline."""
from flask import Blueprint

from core import (
    ApiError,
    TIER_RANK,
    check_ownership,
    db,
    endpoint,
    expected_version,
    body,
    dump,
    paginate,
    respond_object,
    touch,
)
import svc

bp = Blueprint("prompts", __name__)


def _own(return_id):
    ret = svc.get_return(return_id)
    acct = db.accounts[ret["account_id"]]
    check_ownership(acct)
    return ret, acct


@bp.get("/tax/returns/<return_id>/upgrade-prompts")
@endpoint("Taxpayer")
def list_prompts(return_id):
    ret, _acct = _own(return_id)
    return paginate(svc.prompts_of(ret))


@bp.post("/tax/returns/<return_id>/upgrade-prompts/<prompt_id>/acknowledge")
@endpoint("Taxpayer")
def acknowledge_prompt(return_id, prompt_id):
    ret, acct = _own(return_id)
    prompt = svc.get_prompt_on_return(ret, prompt_id)
    payload = body()
    svc.require_account_active(acct)
    svc.require_return_editable(ret)  # ERR_RETURN_NOT_EDITABLE
    if prompt["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Prompt is not PENDING.")
    expected_version(payload, ret)
    prompt["status"] = "ACKNOWLEDGED"
    prompt["acknowledged"] = True
    touch(prompt)
    ret["current_tier"] = prompt["to_tier"]
    svc.recompute_prompt_flag(ret)
    svc.recompute_fees(ret)
    touch(ret)
    return respond_object(dump(prompt))


@bp.post("/tax/returns/<return_id>/upgrade-prompts/<prompt_id>/decline")
@endpoint("Taxpayer")
def decline_prompt(return_id, prompt_id):
    ret, acct = _own(return_id)
    prompt = svc.get_prompt_on_return(ret, prompt_id)
    payload = body()
    svc.require_account_active(acct)
    svc.require_return_editable(ret)  # ERR_RETURN_NOT_EDITABLE
    if prompt["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Prompt is not PENDING.")
    expected_version(payload, ret)
    from_rank = TIER_RANK[prompt["from_tier"]]
    # Imported carryforward forms must be removed explicitly first.
    for f in svc.active_forms_of(ret):
        if f["source"] == "IMPORTED":
            spec = db.form_specs[f["form_code"]]
            if TIER_RANK[spec["minimum_tier"]] > from_rank:
                raise ApiError(
                    "ERR_DOWNGRADE_WOULD_LEAVE_GAP",
                    "ACTIVE IMPORTED carryforward forms still require a tier above from_tier.",
                )
    # Sweep ACTIVE MANUAL forms outranking from_tier to REMOVED.
    for f in svc.active_forms_of(ret):
        if f["source"] == "MANUAL":
            spec = db.form_specs[f["form_code"]]
            if TIER_RANK[spec["minimum_tier"]] > from_rank:
                f["status"] = "REMOVED"
                touch(f)
    prompt["status"] = "DECLINED_DOWNGRADED"
    touch(prompt)
    svc.recompute_classification(ret, acct)
    svc.recompute_refund(ret)
    svc.recompute_prompt_flag(ret)
    touch(ret)
    return respond_object(dump(prompt))
