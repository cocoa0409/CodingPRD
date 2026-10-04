"""Cost-lot pass-through recalculation on transfer-order post (§3.6)."""
from store import DB, to_ms
from svc_common import recompute_lots


def suspend_pass_through(offering_id):
    """An OPEN transfer order suspends pass-through for the whole offering."""
    offering = DB.offerings.get(offering_id)
    if offering is None:
        return 0
    offering["updated_at"] = to_ms(DB.now())
    offering["version"] = int(offering["version"]) + 1
    return recompute_lots(offering)