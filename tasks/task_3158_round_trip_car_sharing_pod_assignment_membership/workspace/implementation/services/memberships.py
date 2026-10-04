"""Membership lifecycle: creation, suspension, freezing, thawing and closing.

Traces PRD §3.3 (tiers and the occupancy fee), §3.4 (suspension, freezing,
thawing, closing and the residual release) and §2.6 (the conserved ledger).
"""

from db import STORE, ordered, paginate
from errors import fail
from services import lookup
from services.calculations import membership_billing_cents, residual_release_cents

TIERS = ("STANDARD", "PLUS", "PREMIUM", "FROZEN")
ENTITLEMENT_TIERS = ("STANDARD", "PLUS", "PREMIUM")
TIER_RANK = {"PREMIUM": 3, "PLUS": 2, "STANDARD": 1, "FROZEN": 1}

RESERVATION_GATES = ("HELD", "CONFIRMED", "IN_USE", "OVERDUE")


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def derive_billing():
    return membership_billing_cents()


def create(data, fields):
    """POST /car-share/memberships (UniversityAccountAdmin) — PRD §3.3."""
    account_id = fields.field(data, "account_id", "string", default=None)
    member_id = fields.field(data, "member_id", "string", required=True)
    department_code = fields.field(data, "department_code", "string", default=None)
    tier = fields.field(data, "tier", "string", required=True, enum=TIERS)
    primary_flag = fields.field(data, "primary_flag", "boolean", required=True)

    if account_id is not None:
        lookup.account(account_id)
    member = lookup.member(member_id)
    # A membership is the carrier of booking rights (PRD §3.3), so creation
    # carries the same screening gate the booking paths do: PRD §3.1 states that
    # a REFERRED or FAILED outcome "blocks the operation" and §2.12 places
    # ERR_SCREENING_NOT_CLEAR below the invalid-transition guard.
    if member.get("screen_result") in ("REFERRED", "FAILED"):
        fail("ERR_SCREENING_NOT_CLEAR",
             "A REFERRED or FAILED screening outcome blocks membership creation.")

    if primary_flag and _has_active_primary(member_id):
        fail("ERR_DUPLICATE_PRIMARY_MEMBERSHIP",
             "The member already holds an ACTIVE primary membership.")

    row = STORE.create(
        STORE.memberships,
        account_id=account_id,
        member_id=member_id,
        department_code=department_code if department_code is not None else "UNSPONSORED",
        tier=tier,
        primary_flag=primary_flag,
        status="ACTIVE",
        status_before_freeze="NONE",
        membership_billing_cents=derive_billing(),
        residual_released_cents=0,
    )
    STORE.touch(member)
    return row


def _has_active_primary(member_id, exclude_id=None):
    for m in STORE.memberships.values():
        if m["id"] == exclude_id:
            continue
        if m.get("member_id") == member_id and m.get("status") == "ACTIVE" and m.get("primary_flag"):
            return True
    return False


def active_memberships(member_id):
    return [m for m in ordered(STORE.memberships.values())
            if m.get("member_id") == member_id and m.get("status") == "ACTIVE"]


def has_active(member_id):
    return bool(active_memberships(member_id))


def has_frozen(member_id):
    return any(m.get("member_id") == member_id and m.get("status") == "FROZEN"
               for m in STORE.memberships.values())


def list_memberships(member_id=None, account_id=None, status=None, limit=10, offset=0):
    rows = ordered(STORE.memberships.values())
    if member_id:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if account_id:
        rows = [r for r in rows if r.get("account_id") == account_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, limit, offset)


def get(membership_id):
    return lookup.membership(membership_id)


def suspend(membership_id):
    """POST /car-share/memberships/{id}/suspend (PodOperator) — PRD §3.4."""
    m = lookup.membership(membership_id)
    if m["status"] != "ACTIVE" or not m.get("primary_flag"):
        fail("ERR_INVALID_STATE",
             "Only an ACTIVE primary membership may be suspended.")
    m["status"] = "SUSPENDED"
    STORE.bump(m)
    return m


def reinstate(membership_id):
    """POST /car-share/memberships/{id}/reinstate (PodOperator) — PRD §3.4."""
    m = lookup.membership(membership_id)
    if m["status"] == "SUSPENDED":
        m["status"] = "ACTIVE"
        STORE.bump(m)
        return m
    if m["status"] == "CLOSED":
        member = lookup.member(m["member_id"])
        if member.get("application_status") != "APPROVED":
            fail("ERR_INVALID_STATE",
                 "A CLOSED membership may only be reopened for an APPROVED member.")
        if _has_active_primary(m["member_id"], exclude_id=m["id"]) or has_active(m["member_id"]):
            fail("ERR_INVALID_STATE",
                 "The member already holds an ACTIVE membership.")
        m["status"] = "ACTIVE"
        STORE.bump(m)
        return m
    fail("ERR_INVALID_STATE",
         "A membership in %s admits no reinstate edge." % m["status"])


def _frozen_memberships(member_id):
    return [m for m in STORE.memberships.values()
            if m.get("member_id") == member_id and m.get("status") == "FROZEN"]


def thaw(membership_id):
    """POST /car-share/memberships/{id}/thaw (PodOperator) — PRD §3.4."""
    m = lookup.membership(membership_id)
    if m["status"] == "ACTIVE":
        fail("ERR_ALREADY_TERMINAL", "The membership is already in its thawed posture.")
    if m["status"] != "FROZEN":
        fail("ERR_INVALID_STATE", "Only a FROZEN membership may be thawed.")

    incident_id = m.get("froze_for_incident")
    if not incident_id:
        fail("ERR_INVALID_STATE", "No freeze-causing incident is recorded on this membership.")
    incident = STORE.incidents.get(incident_id)
    if incident is None or incident.get("status") != "CLOSED":
        fail("ERR_INVALID_STATE", "The incident that caused the freeze has not reached CLOSED.")

    preserved = m.get("status_before_freeze")
    if preserved not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "The preserved pre-freeze status admits no thaw.")

    if preserved == "ACTIVE":
        pool = [e for e in ordered(STORE.tier_entitlements.values())
                if e.get("membership_id") == m["id"] and e.get("restore_status") == "PENDING"]
        if pool:
            chosen = pool[0]
            m["tier"] = chosen["tier"]
            chosen["restore_status"] = "CONSUMED"
            chosen["consumed_at"] = STORE.now_iso()
            STORE.bump(chosen)
        else:
            m["tier"] = "STANDARD"

    m["status"] = preserved
    m["status_before_freeze"] = "NONE"
    STORE.bump(m)
    return m


def close(membership_id):
    """POST /car-share/memberships/{id}/close (UniversityAccountAdmin) — PRD §3.4."""
    m = lookup.membership(membership_id)

    if int(m.get("residual_released_cents") or 0) != 0:
        fail("ERR_ALREADY_RELEASED",
             "The wallet residual for this membership has already been released.")

    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "Only an ACTIVE or SUSPENDED membership may be closed.")

    for r in STORE.reservations.values():
        if r.get("member_id") != m["member_id"]:
            continue
        if r.get("status") in RESERVATION_GATES:
            fail("ERR_INVALID_STATE",
                 "The member still holds an open reservation.")

    member = lookup.member(m["member_id"])
    if m.get("status") == "ACTIVE" and m.get("primary_flag"):
        others = [o for o in STORE.memberships.values()
                  if o.get("member_id") == m["member_id"] and o.get("status") == "ACTIVE"
                  and o.get("primary_flag") and o["id"] != m["id"]]
        if others:
            fail("ERR_DUPLICATE_PRIMARY_MEMBERSHIP",
                 "Closing this membership would leave a second ACTIVE primary.")

    released = residual_release_cents(int(m.get("membership_billing_cents") or 0))
    m["status"] = "CLOSED"
    m["residual_released_cents"] = int(m.get("residual_released_cents") or 0) + released
    STORE.bump(m)

    member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) + released
    STORE.bump(member)
    return m


# ---- tier-restore entitlements ---------------------------------------------
def create_entitlement(membership_id, data, fields):
    """POST /car-share/memberships/{id}/tier-restore-entitlements — PRD §3.4."""
    m = lookup.membership(membership_id)
    tier = fields.field(data, "tier", "string", required=True, enum=ENTITLEMENT_TIERS)
    reason = fields.field(data, "reason", "string", required=True)

    row = STORE.create(
        STORE.tier_entitlements,
        membership_id=m["id"],
        tier=tier,
        reason=reason,
        restore_status="PENDING",
        consumed_at=None,
    )
    STORE.bump(m)
    return row


def list_entitlements(membership_id=None, restore_status=None, limit=10, offset=0):
    rows = ordered(STORE.tier_entitlements.values())
    if membership_id:
        rows = [r for r in rows if r.get("membership_id") == membership_id]
    if restore_status:
        rows = [r for r in rows if r.get("restore_status") == restore_status]
    return paginate(rows, limit, offset)


def entitlements_for_member(member_id):
    ids = {m["id"] for m in STORE.memberships.values() if m.get("member_id") == member_id}
    return ordered([e for e in STORE.tier_entitlements.values()
                    if e.get("membership_id") in ids])


# ---- C3 tier selector -------------------------------------------------------
def insurance_tier_for(member_id):
    """Pinned selector (PRD §3.13): ACTIVE memberships, highest tier rank wins,
    ties broken by earliest created_at; Member.id and Membership.id never
    participate. A FROZEN tier reads as the preserved base tier."""
    rows = [m for m in STORE.memberships.values()
            if m.get("member_id") == member_id and m.get("status") == "ACTIVE"]
    if not rows:
        return None
    rows.sort(key=lambda m: (-TIER_RANK.get(m.get("tier"), 1), m.get("created_at", ""), m.get("_seq", 0)))
    tier = rows[0].get("tier")
    if tier == "FROZEN":
        return "STANDARD"
    return tier


# ---- freeze cascade (PRD §3.4) ---------------------------------------------
def freeze_memberships(member_id, incident_id=None):
    """Move every ACTIVE/SUSPENDED membership of the member to FROZEN."""
    frozen = []
    for m in ordered(STORE.memberships.values()):
        if m.get("member_id") != member_id:
            continue
        if m.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        m["status_before_freeze"] = m["status"]
        m["status"] = "FROZEN"
        m["tier"] = "FROZEN"
        if incident_id is not None:
            m["froze_for_incident"] = incident_id
        STORE.bump(m)
        frozen.append(m)
    return frozen


def thaw_frozen_memberships(member_id):
    """Return every FROZEN membership of the member to its preserved status."""
    thawed = []
    for m in ordered(STORE.memberships.values()):
        if m.get("member_id") != member_id or m.get("status") != "FROZEN":
            continue
        preserved = m.get("status_before_freeze")
        m["status"] = preserved if preserved in ("ACTIVE", "SUSPENDED") else "ACTIVE"
        m["status_before_freeze"] = "NONE"
        STORE.bump(m)
        thawed.append(m)
    return thawed