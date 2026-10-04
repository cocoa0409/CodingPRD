"""Member lifecycle, authorized signers, and annual reports."""
from flask import Blueprint

from db import store, iso
from domain import (
    ASSIGN_OUT_STATES, MEMBER_TYPES, ORG_ID_TYPES, ROLE_SCOPES, base_record,
    compute_report_figures, err, find_member, find_signer, find_signer_under,
    finalize_termination, get_body, new_exception, opt_bool, opt_iso,
    paginate, parse_iso, req_enum, req_int, req_iso, req_str, sorted_items, touch,
)
from middleware import require_role
from response import success
from views import member_view, report_view, signer_view

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    body = get_body()
    require_role("RegistryAdmin")
    legal_name = req_str(body, "legal_name")
    org_id = req_str(body, "org_id")
    org_id_type = req_enum(body, "org_id_type", ORG_ID_TYPES)
    member_type = req_enum(body, "member_type", MEMBER_TYPES)
    if not (len(org_id) == 7 and org_id.isdigit()):
        raise err("ERR_INVALID_REQUEST", "org_id must be a string of exactly 7 digits")
    if any(m["org_id"] == org_id for m in store.members.values()):
        raise err("ERR_DUPLICATE_ORG_ID",
                  f"org_id {org_id} is already registered (including terminated members)")
    rec = base_record()
    rec.update({
        "legal_name": legal_name,
        "org_id": org_id,
        "org_id_type": org_id_type,
        "member_type": member_type,
        "termination_effective_date": None,
        "_term_dt": None,
        "status": "PENDING_ACTIVATION",
    })
    store.members[rec["id"]] = rec
    return success(member_view(rec), status=201)


@bp.get("/members")
def list_members():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    from flask import request
    items = sorted_items(store.members)
    status = request.args.get("status")
    mtype = request.args.get("member_type")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if mtype is not None:
        items = [m for m in items if m["member_type"] == mtype]
    page, meta = paginate(items)
    return success([member_view(m) for m in page], is_list=True, pagination=meta)


@bp.get("/members/<memberId>")
def get_member(memberId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    return success(member_view(find_member(memberId)))


def _has_active_signer(member_id):
    return any(s["member_id"] == member_id and s["status"] == "ACTIVE"
               for s in store.signers.values())


@bp.post("/members/<memberId>/activate")
def activate_member(memberId):
    get_body()
    require_role("RegistryAdmin")
    member = find_member(memberId)
    if member["status"] != "PENDING_ACTIVATION":
        raise err("ERR_MEMBER_NOT_ACTIVE",
                  "Only a PENDING_ACTIVATION member can be activated")
    if not _has_active_signer(memberId):
        raise err("ERR_NO_AUTHORIZED_SIGNER",
                  "Activation requires at least one ACTIVE authorized signer")
    member["status"] = "ACTIVE"
    touch(member)
    return success(member_view(member))


@bp.post("/members/<memberId>/suspend")
def suspend_member(memberId):
    get_body()
    require_role("RegistryAdmin")
    member = find_member(memberId)
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Only an ACTIVE member can be suspended")
    member["status"] = "SUSPENDED"
    touch(member)
    return success(member_view(member))


@bp.post("/members/<memberId>/reinstate")
def reinstate_member(memberId):
    get_body()
    require_role("RegistryAdmin")
    member = find_member(memberId)
    if member["status"] != "SUSPENDED":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Only a SUSPENDED member can be reinstated")
    if not _has_active_signer(memberId):
        raise err("ERR_NO_AUTHORIZED_SIGNER",
                  "Reinstatement requires at least one ACTIVE authorized signer")
    member["status"] = "ACTIVE"
    touch(member)
    return success(member_view(member))


@bp.post("/members/<memberId>/terminate")
def terminate_member(memberId):
    body = get_body()
    require_role("RegistryAdmin")
    member = find_member(memberId)
    effective_date = req_iso(body, "effective_date")
    expected_version = req_int(body, "expected_member_version")

    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE",
                  "Only an ACTIVE member can begin termination")
    # Clock discipline (tier 11): strictly past is refused; equal is immediate.
    if effective_date < store.clock:
        raise err("ERR_TERMINATION_DATE_PAST",
                  "effective_date lies strictly in the past relative to the logical clock")
    # Termination gates (tier 13).
    holds_rights = any(
        l["current_investor_id"] == memberId or l["current_servicer_id"] == memberId
        for l in store.loans.values()
    )
    if holds_rights:
        raise err("ERR_MEMBER_HOLDS_ACTIVE_RIGHTS",
                  "Member is current investor or servicer of at least one loan")
    if any(m["reported_by_member_id"] == memberId and m["status"] == "PENDING"
           for m in store.matches.values()):
        raise err("ERR_OPEN_TRANSFER_MATCHES",
                  "Member has PENDING transfer matches")
    # OCC last (tier 16).
    if expected_version != member["version"]:
        raise err("ERR_STALE_MEMBER_VERSION",
                  "expected_member_version does not match the member's current version")

    member["termination_effective_date"] = iso(effective_date)
    member["_term_dt"] = effective_date

    # Cascade hop 1: deactivate the member's own still-ACTIVE portfolio.
    flipped = [l for l in store.loans.values()
               if l["registering_member_id"] == memberId and l["status"] == "ACTIVE"]
    flipped.sort(key=lambda l: l["serial"])
    open_run = next((r for r in store.runs.values()
                     if r["member_id"] == memberId and r["status"] == "OPEN"), None)
    for loan in flipped:
        loan["status"] = "INACTIVE_TERMINATED"
        touch(loan)
        if open_run is not None:
            # Hop 2: a REGISTRY_ONLY exception per flipped loan on the open run.
            new_exception(open_run["id"], loan["id"], "REGISTRY_ONLY",
                          f"Loan {loan['min']} deactivated by member termination")
    # Hop 3: termination never auto-completes a run (no maybe_complete_run call).

    if effective_date <= store.clock:
        member["status"] = "TERMINATION_PENDING"
        finalize_termination(member)  # bumps version, revokes signers
    else:
        member["status"] = "TERMINATION_PENDING"
        touch(member)
    return success(member_view(member))


# ---------------- signers ----------------

def _windows_overlap(a_from, a_until, b_from, b_until):
    inf = None  # None effective_until means +inf
    a_end = a_until  # datetime or None
    b_end = b_until
    # [a_from, a_end) vs [b_from, b_end): overlap iff a_from < b_end and b_from < a_end
    cond1 = True if b_end is None else a_from < b_end
    cond2 = True if a_end is None else b_from < a_end
    return cond1 and cond2


@bp.post("/members/<memberId>/signers")
def create_signer(memberId):
    body = get_body()
    require_role("RegistryAdmin")
    find_member(memberId)
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    eff_from = req_iso(body, "effective_from")
    role_scope = req_enum(body, "role_scope", ROLE_SCOPES)
    eff_until = opt_iso(body, "effective_until")
    if eff_until is not None and eff_until <= eff_from:
        raise err("ERR_INVALID_SIGNER_WINDOW",
                  "effective_until must be strictly greater than effective_from")
    for s in store.signers.values():
        if s["member_id"] != memberId:
            continue
        s_from = parse_iso(s["effective_from"], "effective_from")
        s_until = parse_iso(s["effective_until"], "effective_until") \
            if s["effective_until"] else None
        if _windows_overlap(eff_from, eff_until, s_from, s_until):
            raise err("ERR_SIGNER_WINDOW_OVERLAP",
                      "Signer authority window overlaps an existing signer window")
    rec = base_record()
    rec.update({
        "member_id": memberId,
        "full_name": full_name,
        "email": email,
        "effective_from": iso(eff_from),
        "effective_until": iso(eff_until) if eff_until is not None else None,
        "role_scope": role_scope,
        "status": "ACTIVE",
    })
    store.signers[rec["id"]] = rec
    return success(signer_view(rec), status=201)


@bp.get("/members/<memberId>/signers")
def list_signers(memberId):
    require_role("RegistryAdmin", "QAAuditor")
    from flask import request
    find_member(memberId)
    items = [s for s in sorted_items(store.signers) if s["member_id"] == memberId]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success([signer_view(s) for s in page], is_list=True, pagination=meta)


@bp.get("/members/<memberId>/signers/<signerId>")
def get_signer_nested(memberId, signerId):
    require_role("RegistryAdmin", "QAAuditor")
    find_member(memberId)
    return success(signer_view(find_signer_under(memberId, signerId)))


@bp.get("/signers/<signerId>")
def get_signer_flat(signerId):
    require_role("RegistryAdmin", "QAAuditor")
    return success(signer_view(find_signer(signerId)))


@bp.get("/signers")
def list_signers_flat():
    require_role("RegistryAdmin", "QAAuditor")
    from flask import request
    items = sorted_items(store.signers)
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success([signer_view(s) for s in page], is_list=True, pagination=meta)


@bp.post("/members/<memberId>/signers/<signerId>/revoke")
def revoke_signer(memberId, signerId):
    get_body()
    require_role("RegistryAdmin")
    member = find_member(memberId)
    signer = find_signer_under(memberId, signerId)
    if signer["status"] != "ACTIVE":
        raise err("ERR_SIGNER_NOT_AUTHORIZED", "Only an ACTIVE signer can be revoked")
    if member["status"] == "ACTIVE":
        others = [s for s in store.signers.values()
                  if s["member_id"] == memberId and s["status"] == "ACTIVE"
                  and s["id"] != signerId]
        if not others:
            raise err("ERR_NO_AUTHORIZED_SIGNER",
                      "Revoking the last ACTIVE signer of an ACTIVE member is refused")
    signer["status"] = "REVOKED"
    touch(signer)
    return success(signer_view(signer))


# ---------------- annual reports ----------------

@bp.post("/members/<memberId>/annual-reports")
def create_annual_report(memberId):
    body = get_body()
    require_role("RegistryAdmin")
    find_member(memberId)
    report_year = req_int(body, "report_year")
    force = opt_bool(body, "force_regenerate", False)

    prior_final = next((r for r in store.reports.values()
                        if r["member_id"] == memberId
                        and r["report_year"] == report_year
                        and r["status"] == "FINAL"), None)
    if prior_final is not None and not force:
        raise err("ERR_DUPLICATE_ANNUAL_REPORT",
                  "A FINAL annual report already exists for this member and year")

    figures = compute_report_figures(memberId, report_year)
    if prior_final is not None:
        prior_final["status"] = "VOID"
        touch(prior_final)

    rec = base_record()
    rec.update({
        "member_id": memberId,
        "report_year": report_year,
        "status": "FINAL",
    })
    rec.update(figures)
    store.reports[rec["id"]] = rec
    return success(report_view(rec), status=201)
