"""Time-driven transitions, re-evaluated whenever the logical clock advances."""
from datetime import timedelta

import clock
import util
from db import db


def sweep_all():
    """Apply every time-driven transition against the current logical time."""
    now = clock.now()
    _expire_promo_codes(now)
    _expire_replay_assets(now)
    _expire_holds(now)
    _lapse_grace(now)
    _complete_campaigns(now)
    _expire_properties(now)


def _expire_promo_codes(now):
    for pc in db.promo_codes.values():
        if pc["code_status"] == "ISSUED" and now >= pc["expires_at"]:
            pc["code_status"] = "EXPIRED"
            util.touch(pc)


def _expire_replay_assets(now):
    for ra in db.replay_assets.values():
        if ra["status"] == "AVAILABLE" and now >= ra["expires_at"]:
            ra["status"] = "EXPIRED"
            util.touch(ra)


def _expire_holds(now):
    for res in db.capacity_reservations.values():
        if res["status"] == "HELD" and now >= res["hold_expires_at"]:
            res["status"] = "EXPIRED"
            util.touch(res)
            pool = db.capacity_pools.get(res["pool_id"])
            if pool is not None:
                pool["committed_units"] = pool.get("committed_units", 0) - res["units"]
                util.touch(pool)


def _lapse_grace(now):
    for viewer in db.viewers.values():
        if viewer["subscription_status"] == "GRACE":
            entered = viewer.get("grace_entered_at")
            if entered is not None and now >= entered + timedelta(hours=72):
                viewer["subscription_status"] = "SUSPENDED"
                util.touch(viewer)
                for ent in db.entitlements.values():
                    if ent["viewer_id"] == viewer["id"] and ent["active"]:
                        ent["active"] = False


def _complete_campaigns(now):
    for camp in db.ad_campaigns.values():
        if camp["campaign_status"] == "BOOKED" and now > camp["flight_end"]:
            camp["campaign_status"] = "COMPLETED"
            util.touch(camp)


def _expire_properties(now):
    from services.window import cancel_window
    for prop in db.properties.values():
        if prop["status"] in ("NEGOTIATION", "ACTIVE", "SUSPENDED") and now >= prop["term_end"]:
            if prop["status"] == "NEGOTIATION":
                continue
            prop["status"] = "EXPIRED"
            util.touch(prop)
            for win in list(db.windows.values()):
                if win["property_id"] == prop["id"] and win["status"] == "SCHEDULED":
                    cancel_window(win)
