"""braided_cost_allocation, delivery_unit_cost and duplication_disallowance."""

import clock
import db
from common import cents
from errors import ApiError
from services import posture

RANKED_BASES = ("DIRECT_ONLY", "HEADCOUNT")
CHRONO_BASES = ("TIME_AND_EFFORT", "SQUARE_FOOTAGE")


def governing_basis(delivery):
    """The basis the governing funder mandates, recorded on the governing grant:
    DIRECT_ONLY and HEADCOUNT pin the ranked_priority order, TIME_AND_EFFORT and
    SQUARE_FOOTAGE pin the chronological_period order."""
    grant = db.get("grants", delivery.get("grant_id"))
    return (grant or {}).get("cost_allocation_basis")


def candidate_grants(delivery):
    """Every grant that is either the enrollment's grant or the authorization's
    grant, restricted to OPEN or THROTTLED posture."""
    auth = db.get("service_authorizations", delivery.get("service_authorization_id"))
    enrollment = db.get("enrollments", auth.get("enrollment_id")) if auth else None
    ids = []
    if enrollment is not None:
        ids.append(enrollment.get("grant_id"))
    if auth is not None:
        ids.append(auth.get("grant_id"))
    out = []
    seen = set()
    for grant_id in ids:
        if grant_id is None or grant_id in seen:
            continue
        seen.add(grant_id)
        grant = db.get("grants", grant_id)
        if grant is None:
            continue
        if grant.get("status") in ("OPEN", "THROTTLED"):
            out.append(grant)
    return out


def pinned_order(grants, basis):
    """The order is pinned once, before any line is written."""
    if basis in RANKED_BASES:
        return sorted(
            grants,
            key=lambda g: (g.get("allocation_rank", 0), g["created_at"], g["_seq"]),
        )
    return sorted(grants, key=lambda g: (g["period_start"], g["created_at"], g["_seq"]))


def braid(delivery):
    """Run the waterfall and rewrite the delivery's PROVISIONAL lines.

    Nothing is persisted unless the whole pass completes with residual == 0.
    """
    total_cost = delivery.get("units_delivered", 0) * delivery.get("unit_rate_cents", 0)
    basis = governing_basis(delivery)
    order = pinned_order(candidate_grants(delivery), basis)
    label = "RANKED_PRIORITY" if basis in RANKED_BASES else "CHRONOLOGICAL_PERIOD"

    planned = []
    residual = total_cost
    for index, grant in enumerate(order, start=1):
        capacity = (
            grant.get("total_award_cents", 0)
            - grant.get("expended_cents", 0)
            - grant.get("obligated_cents", 0)
        )
        take = min(capacity, residual)
        if take < 1:
            take = 0
        admin = cents(take * grant.get("admin_rate_pct", 0))
        planned.append({"grant": grant, "take": take, "admin": admin, "rank": index})
        residual -= take

    if residual > 0:
        raise ApiError(
            "ERR_ALLOCATION_EXCEEDS_AWARD",
            "The combined remaining capacity of the candidate grants is below "
            "the delivery's total cost.",
        )

    for line in db.rows("cost_allocations"):
        if line.get("service_delivery_id") != delivery["id"]:
            continue
        if line.get("status") == "PROVISIONAL":
            del db.store["cost_allocations"][line["id"]]

    created = []
    for item in planned:
        row = db.create("cost_allocations", {
            "service_delivery_id": delivery["id"],
            "grant_id": item["grant"]["id"],
            "allocation_rank": item["rank"],
            "allocated_amount_cents": item["take"],
            "admin_amount_cents": item["admin"],
            "allocation_basis": label,
            "disallowed_cents": 0,
            "status": "PROVISIONAL",
        })
        created.append(row)

    for item in planned:
        grant = item["grant"]
        grant["obligated_cents"] = grant.get("obligated_cents", 0) + item["take"] + item["admin"]
    for grant in {item["grant"]["id"]: item["grant"] for item in planned}.values():
        posture.recompute(grant)
    return created


def delivery_totals(delivery):
    allocated = 0
    admin = 0
    for line in db.rows("cost_allocations"):
        if line.get("service_delivery_id") != delivery["id"]:
            continue
        if line.get("status") not in ("PROVISIONAL", "COMMITTED"):
            continue
        allocated += line.get("allocated_amount_cents", 0)
        admin += line.get("admin_amount_cents", 0)
    return allocated, admin


def peer_rows(delivery):
    """Same client, same logical-clock day, same service_code, DOCUMENTED or BILLED."""
    auth = db.get("service_authorizations", delivery.get("service_authorization_id"))
    if auth is None:
        return []
    code = auth.get("service_code")
    day = clock.clock_day(delivery["service_date"])
    peers = []
    for other in db.rows("service_deliveries"):
        if other.get("client_id") != delivery.get("client_id"):
            continue
        if other.get("status") not in ("DOCUMENTED", "BILLED"):
            continue
        other_auth = db.get("service_authorizations", other.get("service_authorization_id"))
        if other_auth is None or other_auth.get("service_code") != code:
            continue
        if clock.clock_day(other["service_date"]) != day:
            continue
        peers.append(other)
    return sorted(peers, key=lambda d: (d["created_at"], d.get("sequence_no", 0)))


def _row_total(delivery):
    return delivery.get("allocated_total_cents", 0) + delivery.get("admin_total_cents", 0)


def _disallowed_rows(delivery, variant):
    peers = peer_rows(delivery)
    if not peers:
        return []
    if variant == "lowest_cost_first":
        cheapest = min(_row_total(p) for p in peers)
        allowed = [p for p in peers if _row_total(p) == cheapest]
    else:
        allowed = [peers[0]]
    allowed_ids = {p["id"] for p in allowed}
    return [p for p in peers if p["id"] not in allowed_ids]


def disallowance(delivery, variant="first_by_creation"):
    """The disallowed amount carried by this delivery: its own braided total
    when it is a disallowed row of its day, otherwise zero."""
    rows = _disallowed_rows(delivery, variant)
    if any(row["id"] == delivery["id"] for row in rows):
        return _row_total(delivery)
    return 0


def alternate_disallowance(delivery):
    return disallowance(delivery, variant="lowest_cost_first")
