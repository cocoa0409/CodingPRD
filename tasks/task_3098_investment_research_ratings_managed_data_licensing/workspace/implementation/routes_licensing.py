"""Licensing-domain routes: licensees, license agreements, seat entitlements,
license audits, and index definitions."""
from flask import Blueprint, request

import errors
from db import store, _parse_iso
from middleware import require_roles, body, req_str, opt_str, req_int, req_enum
from response import success_object, success_list, parse_pagination, paginate
import services as S

bp = Blueprint("licensing", __name__)

LIC = ("LicenseAdmin",)
LIC_READ = ("LicenseAdmin", "ResearchOps", "ComplianceOfficer")
INDEX_READ = ("LicenseAdmin", "ResearchOps", "Analyst", "ComplianceOfficer")


def _parse_date(value, field):
    try:
        _parse_iso(value)
    except Exception:
        raise errors.validation(f"Invalid date for {field}: {value}")
    return value


def _windows_overlap(a_from, a_to, b_from, b_to):
    if a_to is not None and a_to <= b_from:
        return False
    if b_to is not None and b_to <= a_from:
        return False
    return True


# ===========================================================================
# Licensees
# ===========================================================================

@bp.post("/research/licensees")
def create_licensee():
    require_roles("LicenseAdmin")
    data = body()
    name = req_str(data, "licensee_name")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update({"licensee_name": name, "licensee_status": "ACTIVE", "arrears_cents": 0})
    store.licensees[rec["id"]] = rec
    return success_object(S.licensee_view(rec), 201)


@bp.get("/research/licensees/<lid>")
def get_licensee(lid):
    require_roles(*LIC_READ)
    return success_object(S.licensee_view(S.get_licensee(lid)))


@bp.get("/research/licensees/<lid>/agreements")
def list_licensee_agreements(lid):
    require_roles(*LIC_READ)
    S.get_licensee(lid)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.agreements.values() if a["licensee_id"] == lid]
    if request.args.get("agreement_status") is not None:
        items = [a for a in items if a["agreement_status"] == request.args["agreement_status"]]
    if request.args.get("tier") is not None:
        items = [a for a in items if a["tier"] == request.args["tier"]]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    return success_list([S.agreement_view(a) for a in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/licensees/<lid>/notices")
def list_licensee_notices(lid):
    require_roles("LicenseAdmin", "ResearchOps", "ComplianceOfficer")
    S.get_licensee(lid)
    limit, offset = parse_pagination(request.args)
    items = [n for n in store.client_notices.values() if n["licensee_id"] == lid]
    items.sort(key=lambda n: n["created_at"])
    total = len(items)
    return success_list([S.notice_view(n) for n in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/licensees/<lid>/reinstate")
def reinstate_licensee(lid):
    require_roles("LicenseAdmin")
    licensee = S.get_licensee(lid)
    if licensee["licensee_status"] != "SUSPENDED":
        raise errors.invalid_state("Licensee must be SUSPENDED to reinstate")
    if licensee["arrears_cents"] != 0:
        raise errors.arrears_outstanding()
    licensee["licensee_status"] = "ACTIVE"
    S.touch(licensee)
    return success_object(S.licensee_view(licensee))


@bp.post("/research/licensees/<lid>/terminate")
def terminate_licensee(lid):
    require_roles("LicenseAdmin")
    licensee = S.get_licensee(lid)
    if licensee["licensee_status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Licensee must be ACTIVE or SUSPENDED to terminate")
    for ag in store.agreements.values():
        if ag["licensee_id"] == lid and ag["agreement_status"] == "ACTIVE":
            raise errors.invalid_state("No ACTIVE agreements may remain when terminating a licensee")
    licensee["licensee_status"] = "TERMINATED"
    S.touch(licensee)
    for ag in store.agreements.values():
        if ag["licensee_id"] == lid and ag["agreement_status"] in ("DRAFT", "SUSPENDED"):
            ag["agreement_status"] = "TERMINATED"
            S.touch(ag)
    return success_object(S.licensee_view(licensee))


# ===========================================================================
# License agreements
# ===========================================================================

@bp.post("/research/license-agreements")
def create_agreement():
    require_roles("LicenseAdmin")
    data = body()
    licensee_id = data.get("licensee_id")
    tier = data.get("tier")
    seat_limit = data.get("seat_limit")
    effective_from = data.get("effective_from")
    effective_to = data.get("effective_to")
    base_fee_cents = data.get("base_fee_cents")
    if licensee_id is None or not isinstance(licensee_id, str):
        raise errors.validation("Missing or invalid required field: licensee_id")
    if tier not in ("DISPLAY", "REDISTRIBUTION", "DERIVED_WORKS"):
        raise errors.validation("Invalid tier")
    if seat_limit is None or isinstance(seat_limit, bool) or not isinstance(seat_limit, int):
        raise errors.validation("Missing or invalid required field: seat_limit")
    if seat_limit <= 0:
        raise errors.validation("seat_limit must be > 0")
    if effective_from is None or not isinstance(effective_from, str):
        raise errors.validation("Missing or invalid required field: effective_from")
    if effective_to is not None and not isinstance(effective_to, str):
        raise errors.validation("effective_to must be a string or null")
    if base_fee_cents is None or isinstance(base_fee_cents, bool) or not isinstance(base_fee_cents, int):
        raise errors.validation("Missing or invalid required field: base_fee_cents")
    _parse_date(effective_from, "effective_from")
    if effective_to is not None:
        _parse_date(effective_to, "effective_to")
    # Body FK existence (priority 4).
    if licensee_id not in store.licensees:
        raise errors.reference_not_found(f"Licensee not found: {licensee_id}")
    # Window ordering (priority 9).
    if effective_to is not None and effective_to <= effective_from:
        raise errors.temporal_overlap("effective_to must be later than effective_from")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "licensee_id": licensee_id,
            "tier": tier,
            "seat_limit": seat_limit,
            "seats_in_use": 0,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "agreement_status": "DRAFT",
            "base_fee_cents": base_fee_cents,
            "audit_count": 0,
        }
    )
    store.agreements[rec["id"]] = rec
    return success_object(S.agreement_view(rec), 201)


@bp.post("/research/license-agreements/fee-quote")
def fee_quote():
    require_roles("LicenseAdmin", "ResearchOps")
    data = body()
    tier = data.get("tier")
    seat_limit = data.get("seat_limit")
    base_fee_cents = data.get("base_fee_cents")
    if tier not in ("DISPLAY", "REDISTRIBUTION", "DERIVED_WORKS"):
        raise errors.validation("Invalid tier")
    if seat_limit is None or isinstance(seat_limit, bool) or not isinstance(seat_limit, int):
        raise errors.validation("Missing or invalid required field: seat_limit")
    if seat_limit <= 0:
        raise errors.validation("seat_limit must be > 0")
    if base_fee_cents is None or isinstance(base_fee_cents, bool) or not isinstance(base_fee_cents, int):
        raise errors.validation("Missing or invalid required field: base_fee_cents")
    return success_object({"total_fee_cents": S.fee_quote(tier, seat_limit, base_fee_cents)})


@bp.get("/research/license-agreements/<aid>")
def get_agreement(aid):
    require_roles(*LIC_READ)
    return success_object(S.agreement_view(S.get_agreement(aid)))


@bp.get("/research/license-agreements/<aid>/seats")
def list_agreement_seats(aid):
    require_roles(*LIC_READ)
    S.get_agreement(aid)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.seats.values() if s["agreement_id"] == aid]
    if request.args.get("seat_status") is not None:
        items = [s for s in items if s["seat_status"] == request.args["seat_status"]]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    return success_list([S.seat_view(s) for s in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/license-agreements/<aid>/audits")
def list_agreement_audits(aid):
    require_roles("LicenseAdmin", "ComplianceOfficer")
    S.get_agreement(aid)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.audits.values() if a["agreement_id"] == aid]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    return success_list([S.audit_view(a) for a in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/license-agreements/<aid>/activate")
def activate_agreement(aid):
    require_roles("LicenseAdmin")
    ag = S.get_agreement(aid)
    if ag["agreement_status"] not in ("DRAFT", "SUSPENDED"):
        raise errors.invalid_state("Agreement must be DRAFT or SUSPENDED to activate")
    licensee = store.licensees.get(ag["licensee_id"])
    if licensee is None or licensee["licensee_status"] != "ACTIVE":
        raise errors.invalid_state("Licensee must be ACTIVE to activate an agreement")
    if ag["agreement_status"] == "DRAFT":
        # Same-licensee same-tier ACTIVE window non-overlap (priority 9).
        for other in store.agreements.values():
            if (
                other["id"] != aid
                and other["licensee_id"] == ag["licensee_id"]
                and other["tier"] == ag["tier"]
                and other["agreement_status"] == "ACTIVE"
                and _windows_overlap(
                    ag["effective_from"], ag["effective_to"],
                    other["effective_from"], other["effective_to"],
                )
            ):
                raise errors.temporal_overlap("Overlapping ACTIVE window for the same licensee and tier")
    ag["agreement_status"] = "ACTIVE"
    S.touch(ag)
    return success_object(S.agreement_view(ag))


@bp.post("/research/license-agreements/<aid>/suspend")
def suspend_agreement(aid):
    require_roles("LicenseAdmin")
    ag = S.get_agreement(aid)
    if ag["agreement_status"] != "ACTIVE":
        raise errors.invalid_state("Agreement must be ACTIVE to suspend")
    ag["agreement_status"] = "SUSPENDED"
    S.touch(ag)
    return success_object(S.agreement_view(ag))


@bp.post("/research/license-agreements/<aid>/terminate")
def terminate_agreement(aid):
    require_roles("LicenseAdmin")
    ag = S.get_agreement(aid)
    if ag["agreement_status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Agreement must be DRAFT, ACTIVE, or SUSPENDED to terminate")
    if ag["seats_in_use"] != 0:
        raise errors.seats_still_active()
    ag["agreement_status"] = "TERMINATED"
    S.touch(ag)
    # Linked LIVE indices move to SUSPENDED.
    for idx in store.indices.values():
        if idx["licensed_agreement_id"] == aid and idx["index_status"] == "LIVE":
            idx["index_status"] = "SUSPENDED"
            S.touch(idx)
    return success_object(S.agreement_view(ag))


@bp.post("/research/license-agreements/<aid>/seats")
def grant_seat(aid):
    require_roles("LicenseAdmin")
    ag = S.get_agreement(aid)
    data = body()
    workstation_user_id = data.get("workstation_user_id")
    expected_version = data.get("expected_agreement_version")
    if workstation_user_id is None or not isinstance(workstation_user_id, str):
        raise errors.validation("Missing or invalid required field: workstation_user_id")
    if expected_version is None or isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.validation("Missing or invalid required field: expected_agreement_version")
    if expected_version != ag["version"]:
        raise errors.stale_version("expected_agreement_version does not match the agreement's current version")
    # Uniqueness: ACTIVE seat per workstation_user_id within the agreement.
    if any(
        s["agreement_id"] == aid
        and s["workstation_user_id"] == workstation_user_id
        and s["seat_status"] == "ACTIVE"
        for s in store.seats.values()
    ):
        raise errors.uniqueness("An ACTIVE seat already exists for this workstation_user_id")
    licensee = store.licensees.get(ag["licensee_id"])
    if (
        ag["seats_in_use"] >= ag["seat_limit"]
        or ag["agreement_status"] != "ACTIVE"
        or licensee is None
        or licensee["licensee_status"] != "ACTIVE"
    ):
        raise errors.seat_limit()
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "agreement_id": aid,
            "workstation_user_id": workstation_user_id,
            "seat_status": "ACTIVE",
            "entitled_data_scope": ag["tier"],
        }
    )
    store.seats[rec["id"]] = rec
    ag["seats_in_use"] += 1
    S.touch(ag)
    return success_object(S.seat_view(rec), 201)


# ===========================================================================
# Seat entitlements
# ===========================================================================

@bp.post("/research/seat-entitlements/<sid>/revoke")
def revoke_seat(sid):
    require_roles("LicenseAdmin")
    seat = S.get_seat(sid)
    if seat["seat_status"] != "ACTIVE":
        raise errors.invalid_state("Seat must be ACTIVE to revoke")
    seat["seat_status"] = "REVOKED"
    S.touch(seat)
    ag = store.agreements.get(seat["agreement_id"])
    if ag is not None:
        ag["seats_in_use"] -= 1
        S.touch(ag)
    return success_object(S.seat_view(seat))


# ===========================================================================
# License audits
# ===========================================================================

@bp.post("/research/license-audits")
def open_audit():
    require_roles("LicenseAdmin")
    data = body()
    agreement_id = data.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str):
        raise errors.validation("Missing or invalid required field: agreement_id")
    if agreement_id not in store.agreements:
        raise errors.reference_not_found(f"LicenseAgreement not found: {agreement_id}")
    ag = store.agreements[agreement_id]
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "agreement_id": agreement_id,
            "audit_status": "OPEN",
            "unlicensed_uses_found": 0,
            "penalty_cents": 0,
        }
    )
    store.audits[rec["id"]] = rec
    ag["audit_count"] += 1
    S.touch(ag)
    return success_object(S.audit_view(rec), 201)


@bp.post("/research/license-audits/<aid>/file-findings")
def file_findings(aid):
    require_roles("LicenseAdmin")
    audit = S.get_audit(aid)
    data = body()
    uses = data.get("unlicensed_uses_found")
    if uses is None or isinstance(uses, bool) or not isinstance(uses, int) or uses < 0:
        raise errors.validation("unlicensed_uses_found must be a non-negative integer")
    if audit["audit_status"] != "OPEN":
        raise errors.invalid_state("Audit must be OPEN to file findings")
    audit["unlicensed_uses_found"] = uses
    audit["audit_status"] = "FINDINGS_FILED"
    S.touch(audit)
    return success_object(S.audit_view(audit))


@bp.post("/research/license-audits/<aid>/close")
def close_audit(aid):
    require_roles("LicenseAdmin")
    audit = S.get_audit(aid)
    data = body()
    outcome = data.get("outcome")
    if outcome is None or outcome not in ("NO_ACTION", "PENALTY"):
        raise errors.validation("Invalid outcome")
    if audit["audit_status"] != "FINDINGS_FILED":
        raise errors.invalid_state("Audit must be FINDINGS_FILED to close")
    ag = store.agreements.get(audit["agreement_id"])
    if outcome == "PENALTY":
        if audit["unlicensed_uses_found"] <= 0:
            raise errors.audit_outcome_invalid()
        penalty = S.audit_penalty(ag, audit["unlicensed_uses_found"])
        audit["penalty_cents"] = penalty
        audit["audit_status"] = "CLOSED_WITH_PENALTY"
        S.touch(audit)
        # Cascade: arrears, then licensee suspension when arrears > 0.
        licensee = store.licensees.get(ag["licensee_id"]) if ag is not None else None
        if licensee is not None:
            licensee["arrears_cents"] += penalty
            if licensee["arrears_cents"] > 0 and licensee["licensee_status"] == "ACTIVE":
                licensee["licensee_status"] = "SUSPENDED"
                # Revoke every ACTIVE seat under this licensee's agreements.
                for other_ag in store.agreements.values():
                    if other_ag["licensee_id"] != licensee["id"]:
                        continue
                    revoked_any = False
                    for seat in store.seats.values():
                        if (
                            seat["agreement_id"] == other_ag["id"]
                            and seat["seat_status"] == "ACTIVE"
                        ):
                            seat["seat_status"] = "REVOKED"
                            S.touch(seat)
                            revoked_any = True
                    other_ag["seats_in_use"] = 0
                    if revoked_any:
                        S.touch(other_ag)
            S.touch(licensee)
    else:
        audit["penalty_cents"] = 0
        audit["audit_status"] = "CLOSED_NO_ACTION"
        S.touch(audit)
    return success_object(S.audit_view(audit))


# ===========================================================================
# Indices
# ===========================================================================

@bp.post("/research/indices")
def create_index():
    require_roles("LicenseAdmin")
    data = body()
    index_code = data.get("index_code")
    methodology_id = data.get("methodology_id")
    max_constituents = data.get("max_constituents")
    cap = data.get("single_constituent_cap_bp")
    if index_code is None or not isinstance(index_code, str) or index_code == "":
        raise errors.validation("Missing or invalid required field: index_code")
    if methodology_id is None or not isinstance(methodology_id, str):
        raise errors.validation("Missing or invalid required field: methodology_id")
    if max_constituents is None or isinstance(max_constituents, bool) or not isinstance(max_constituents, int):
        raise errors.validation("Missing or invalid required field: max_constituents")
    if max_constituents <= 0:
        raise errors.validation("max_constituents must be > 0")
    if cap is None or isinstance(cap, bool) or not isinstance(cap, int):
        raise errors.validation("Missing or invalid required field: single_constituent_cap_bp")
    if methodology_id not in store.methodologies:
        raise errors.reference_not_found(f"Methodology not found: {methodology_id}")
    if any(i["index_code"] == index_code for i in store.indices.values()):
        raise errors.uniqueness(f"Index code already exists: {index_code}")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "index_code": index_code,
            "methodology_id": methodology_id,
            "max_constituents": max_constituents,
            "single_constituent_cap_bp": cap,
            "index_status": "DRAFT",
            "licensed_agreement_id": None,
        }
    )
    store.indices[rec["id"]] = rec
    return success_object(S.index_view(rec), 201)


@bp.get("/research/indices/<iid>")
def get_index(iid):
    require_roles(*INDEX_READ)
    return success_object(S.index_view(S.get_index(iid)))


@bp.get("/research/indices")
def list_indices():
    require_roles(*INDEX_READ)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.indices.values(), key=lambda i: i["created_at"])
    if request.args.get("methodology_id") is not None:
        items = [i for i in items if i["methodology_id"] == request.args["methodology_id"]]
    if request.args.get("licensed_agreement_id") is not None:
        items = [i for i in items if i["licensed_agreement_id"] == request.args["licensed_agreement_id"]]
    if request.args.get("index_status") is not None:
        items = [i for i in items if i["index_status"] == request.args["index_status"]]
    total = len(items)
    return success_list([S.index_view(i) for i in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/indices/<iid>/constituents")
def list_index_constituents(iid):
    require_roles(*INDEX_READ)
    S.get_index(iid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.constituents.values() if c["index_id"] == iid]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    return success_list([S.constituent_view(c) for c in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/indices/<iid>/link-license")
def link_license(iid):
    require_roles("LicenseAdmin")
    idx = S.get_index(iid)
    data = body()
    agreement_id = data.get("licensed_agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str):
        raise errors.validation("Missing or invalid required field: licensed_agreement_id")
    if agreement_id not in store.agreements:
        raise errors.reference_not_found(f"LicenseAgreement not found: {agreement_id}")
    ag = store.agreements[agreement_id]
    licensee = store.licensees.get(ag["licensee_id"])
    if (
        ag["agreement_status"] != "ACTIVE"
        or ag["tier"] != "DERIVED_WORKS"
        or licensee is None
        or licensee["licensee_status"] != "ACTIVE"
    ):
        raise errors.license_tier_insufficient()
    idx["licensed_agreement_id"] = agreement_id
    S.touch(idx)
    return success_object(S.index_view(idx))


@bp.post("/research/indices/<iid>/constituents")
def add_constituent(iid):
    require_roles("LicenseAdmin")
    idx = S.get_index(iid)
    data = body()
    fund_id = data.get("fund_id")
    target_weight_bp = data.get("target_weight_bp")
    if fund_id is None or not isinstance(fund_id, str):
        raise errors.validation("Missing or invalid required field: fund_id")
    if target_weight_bp is None or isinstance(target_weight_bp, bool) or not isinstance(target_weight_bp, int):
        raise errors.validation("Missing or invalid required field: target_weight_bp")
    if fund_id not in store.funds:
        raise errors.reference_not_found(f"Fund not found: {fund_id}")
    fund = store.funds[fund_id]
    existing = [c for c in store.constituents.values() if c["index_id"] == iid]
    if len(existing) >= idx["max_constituents"]:
        raise errors.index_not_licensable("Constituent count exceeds max_constituents")
    has_published = any(
        r["fund_id"] == fund_id
        and r["methodology_id"] == idx["methodology_id"]
        and r["rating_status"] == "PUBLISHED"
        for r in store.ratings.values()
    )
    if fund["fund_status"] != "ACTIVE" or not has_published:
        raise errors.invalid_state(
            "Constituent fund must be ACTIVE with a PUBLISHED rating under the index methodology"
        )
    rec = S.ledger_new({"id": S.new_id()})
    rec.update(
        {
            "index_id": iid,
            "fund_id": fund_id,
            "target_weight_bp": target_weight_bp,
            "final_weight_bp": None,
        }
    )
    store.constituents[rec["id"]] = rec
    return success_object(S.constituent_view(rec), 201)


@bp.post("/research/indices/<iid>/launch")
def launch_index(iid):
    require_roles("LicenseAdmin")
    idx = S.get_index(iid)
    if idx["index_status"] not in ("DRAFT", "SUSPENDED"):
        raise errors.invalid_state("Index must be DRAFT or SUSPENDED to launch")
    # Licensing preconditions (priority 12): a missing agreement link is an
    # unmet launch precondition (ERR_INDEX_NOT_LICENSABLE); a linked agreement
    # with the wrong tier or status is a tier failure (ERR_LICENSE_TIER_INSUFFICIENT).
    if not idx["licensed_agreement_id"]:
        raise errors.index_not_licensable("No licensing agreement is linked to this index")
    ag = store.agreements.get(idx["licensed_agreement_id"])
    if ag is None:
        raise errors.index_not_licensable("Linked licensing agreement does not exist")
    licensee = store.licensees.get(ag["licensee_id"])
    if (
        ag["agreement_status"] != "ACTIVE"
        or ag["tier"] != "DERIVED_WORKS"
        or licensee is None
        or licensee["licensee_status"] != "ACTIVE"
    ):
        raise errors.license_tier_insufficient()
    meth = store.methodologies.get(idx["methodology_id"])
    if meth is None or meth["methodology_status"] != "EFFECTIVE":
        raise errors.methodology_not_effective()
    count = sum(1 for c in store.constituents.values() if c["index_id"] == iid)
    if count < 1 or count > idx["max_constituents"]:
        raise errors.index_not_licensable("Constituent count must be >= 1 and <= max_constituents")
    idx["index_status"] = "LIVE"
    S.touch(idx)
    S.index_rebalance(idx)
    return success_object(S.index_view(idx))


@bp.post("/research/indices/<iid>/suspend")
def suspend_index(iid):
    require_roles("LicenseAdmin")
    idx = S.get_index(iid)
    if idx["index_status"] != "LIVE":
        raise errors.invalid_state("Index must be LIVE to suspend")
    idx["index_status"] = "SUSPENDED"
    S.touch(idx)
    return success_object(S.index_view(idx))


@bp.post("/research/indices/<iid>/retire")
def retire_index(iid):
    require_roles("LicenseAdmin")
    idx = S.get_index(iid)
    if idx["index_status"] not in ("DRAFT", "SUSPENDED"):
        raise errors.invalid_state("Index must not be LIVE to retire (suspend it first)")
    idx["index_status"] = "RETIRED"
    S.touch(idx)
    return success_object(S.index_view(idx))


@bp.post("/research/indices/<iid>/rebalance")
def rebalance_index(iid):
    require_roles("LicenseAdmin")
    idx = S.get_index(iid)
    if idx["index_status"] != "LIVE":
        raise errors.invalid_state("Index must be LIVE to rebalance")
    rows = S.index_rebalance(idx)
    rows = sorted(rows, key=lambda c: c["created_at"])
    return success_list([S.constituent_view(c) for c in rows], len(rows), 0, len(rows))
