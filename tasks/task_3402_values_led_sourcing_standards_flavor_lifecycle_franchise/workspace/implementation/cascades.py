"""Cross-aggregate cascade side effects (PRD 3.1/3.2/3.4/3.5).

Capacity pools are derived from live statuses, so 'releasing' a reservation
is simply the status transition itself; no separate pool bookkeeping exists.
"""
from db import STORE, touch


def _flavors_citing(cert_ids):
    ids = set(cert_ids)
    for f in STORE["flavors"].values():
        if any(cid in ids for cid in f["claim_certification_ids"]):
            yield f


def challenge_claims_citing(cert_ids):
    """Certification revocation: citing claims SUBSTANTIATED|PUBLISHED -> CHALLENGED."""
    for f in _flavors_citing(cert_ids):
        if f["claim_status"] in ("SUBSTANTIATED", "PUBLISHED"):
            f["claim_status"] = "CHALLENGED"
            touch(f)


def retract_claims_citing(cert_ids):
    """Certification expiry: citing claims PUBLISHED -> RETRACTED (depth-2 clock cascade)."""
    for f in _flavors_citing(cert_ids):
        if f["claim_status"] == "PUBLISHED":
            f["claim_status"] = "RETRACTED"
            touch(f)


def audit_fail_cascade(supplier):
    """Depth-3 audit-fail cascade (PRD 3.2): certifications revoked, citing
    claims challenged, ACTIVE commitments lapsed. The caller sets the
    supplier's own status and bumps its version."""
    sid = supplier["id"]
    revoked = []
    for c in STORE["certifications"].values():
        if c["supplier_id"] == sid and c["status"] in ("PENDING", "VERIFIED"):
            c["status"] = "REVOKED"
            touch(c)
            revoked.append(c["id"])
    if revoked:
        challenge_claims_citing(revoked)
    for cm in STORE["commitments"].values():
        if cm["supplier_id"] == sid and cm["status"] == "ACTIVE":
            cm["status"] = "LAPSED"
            touch(cm)


def retire_cascade(flavor):
    """Flavor retirement cascade (PRD 3.4): open orders containing the flavor
    are cancelled (an ALLOCATED order's pints are released by the status
    change), PLANNED/CONFIRMED slots of the flavor are cancelled, and a
    PUBLISHED claim retracts. The caller sets status/retired_at and bumps the
    flavor's version once."""
    fid = flavor["id"]
    for o in STORE["orders"].values():
        if o["status"] in ("PLACED", "CONFIRMED", "ALLOCATED") and any(
                line["flavor_id"] == fid for line in o["lines"]):
            o["status"] = "CANCELLED"
            touch(o)
    for s in STORE["slots"].values():
        if s["flavor_id"] == fid and s["status"] in ("PLANNED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)
    if flavor["claim_status"] == "PUBLISHED":
        flavor["claim_status"] = "RETRACTED"
