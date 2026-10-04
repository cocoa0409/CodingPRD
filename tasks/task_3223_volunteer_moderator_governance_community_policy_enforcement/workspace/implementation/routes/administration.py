"""Platform administration routes (§3.4, §3.5, §3.6, §3.7, §3.8)."""

from flask import Blueprint, request

import db
import response as R
from errors import fail
from middleware import require_roles
from services import community as community_svc
from services import content
from services import appeals as appeal_svc
from services import protests as protest_svc

bp = Blueprint("administration", __name__)


# --------------------------------------------------------------------------
# Account-wide enforcement (§3.4)
# --------------------------------------------------------------------------
@bp.post("/api/community-administration/account-sanctions")
def account_wide_sanction():
    require_roles("PlatformAdmin")
    data = R.body(request)
    R.as_str(data, "account_id")
    R.as_str(data, "community_id")
    R.as_enum(data, "decision_outcome", content.DECISION_OUTCOMES)
    sanction = content.account_wide_sanction(data, None)
    return R.ok(R.to_json(sanction), status=201)


@bp.post("/api/community-administration/sanction-reinstatements")
def sanction_reinstatement():
    require_roles("PlatformAdmin")
    data = R.body(request)
    sanction_id = R.as_str(data, "sanction_id")
    sanction = db.find("AccountSanction", sanction_id)
    if sanction is None:
        fail("ERR_SANCTION_NOT_FOUND")
    # §2.6 ranks the sanction-reinstatement conflict above state eligibility,
    # so a target that is already ACTIVE (or whose issuing community is past
    # RESTRICTED) reports the conflict code rather than the state error.
    community = community_svc.fetch(sanction["community_id"])
    if (sanction["status"] == "ACTIVE" or community is None
            or community["state"] not in ("ACTIVE", "RESTRICTED")):
        fail("ERR_ACTIVE_SANCTION_CONFLICT")
    sanction = content.reinstate_sanction(sanction)
    return R.ok(R.to_json(sanction))


# --------------------------------------------------------------------------
# Appeals governance (§3.6)
# --------------------------------------------------------------------------
@bp.post("/api/community-administration/appeal-referrals")
def appeal_referral():
    require_roles("PlatformAdmin")
    data = R.body(request)
    appeal_id = R.as_str(data, "appeal_id")
    appeal = db.find("Appeal", appeal_id)
    if appeal is None:
        fail("ERR_NOT_FOUND")
    appeal = appeal_svc.refer_appeal(appeal, data.get("note"))
    return R.ok(R.to_json(appeal))


# --------------------------------------------------------------------------
# Brigading governance (§3.5)
# --------------------------------------------------------------------------
@bp.post("/api/community-administration/brigade-escalations")
def brigade_escalation():
    require_roles("PlatformAdmin")
    data = R.body(request)
    cluster_id = R.as_str(data, "cluster_id")
    cluster = db.find("BrigadingCluster", cluster_id)
    if cluster is None:
        fail("ERR_NOT_FOUND")
    cluster = content.escalate_cluster(cluster, data.get("sanction_ladder"))
    return R.ok(R.to_json(cluster))


@bp.post("/api/community-administration/brigade-revivals")
def brigade_revival():
    require_roles("PlatformAdmin")
    data = R.body(request)
    cluster_id = R.as_str(data, "cluster_id")
    cluster = db.find("BrigadingCluster", cluster_id)
    if cluster is None:
        fail("ERR_NOT_FOUND")
    cluster = content.revive_cluster(cluster)
    return R.ok(R.to_json(cluster))


# --------------------------------------------------------------------------
# Decision audit chain (§3.4)
# --------------------------------------------------------------------------
@bp.post("/api/community-administration/decision-audits")
def decision_audit():
    require_roles("PlatformAdmin")
    data = R.body(request)
    decision_id = R.as_str(data, "decision_id")
    decision = db.find("ContentDecision", decision_id)
    if decision is None:
        fail("ERR_NOT_FOUND")
    decision = content.audit_decision(decision)
    return R.ok(R.to_json(decision))


@bp.post("/api/community-administration/decision-revisions")
def decision_revision():
    require_roles("PlatformAdmin")
    data = R.body(request)
    decision_id = R.as_str(data, "decision_id")
    decision = db.find("ContentDecision", decision_id)
    if decision is None:
        fail("ERR_NOT_FOUND")
    decision = content.revise_decision(decision)
    return R.ok(R.to_json(decision))


@bp.post("/api/community-administration/decision-reaudits")
def decision_reaudit():
    require_roles("PlatformAdmin")
    data = R.body(request)
    decision_id = R.as_str(data, "decision_id")
    decision = db.find("ContentDecision", decision_id)
    if decision is None:
        fail("ERR_NOT_FOUND")
    decision = content.reaudit_decision(decision)
    return R.ok(R.to_json(decision))


# --------------------------------------------------------------------------
# Posture and platform response (§3.8)
# --------------------------------------------------------------------------
@bp.post("/api/community-administration/policy-advisories")
def policy_advisory():
    require_roles("PlatformAdmin")
    data = R.body(request)
    community_id = R.as_str(data, "community_id")
    community = community_svc.policy_advisory(community_id)
    return R.ok(R.to_json(community))


@bp.post("/api/community-administration/regulation-cadences")
def regulation_cadence():
    require_roles("PlatformAdmin")
    data = R.body(request)
    community_id = R.as_str(data, "community_id")
    community = community_svc.regulation_cadence(community_id)
    return R.ok(R.to_json(community))


@bp.post("/api/community-administration/institution-negotiations")
def institution_negotiation():
    require_roles("PlatformAdmin")
    data = R.body(request)
    community_id = R.as_str(data, "community_id")
    community = community_svc.institution_negotiation(community_id)
    return R.ok(R.to_json(community))


@bp.post("/api/community-administration/archivals")
def archival():
    require_roles("PlatformAdmin")
    data = R.body(request)
    community_id = R.as_str(data, "community_id")
    community = community_svc.archive(community_id)
    return R.ok(R.to_json(community))