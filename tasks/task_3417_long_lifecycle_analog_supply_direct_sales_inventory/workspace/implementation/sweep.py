# Logical-clock sweep (PRD 2.5): fires every clock-gated transition whose
# threshold instant is at or before the new clock value, in dependency order.
import constants as C
from derive import announced_notice_for_part
from store import store
from timeutil import add_years


def run_sweep():
    now = store.now()

    # Parts: EOL_ANNOUNCED -> LAST_TIME_BUY -> DISCONTINUED (a single clock set
    # may carry a part through both); reaching DISCONTINUED completes the
    # linked ANNOUNCED notice.
    for part in store.parts.values():
        if part["lifecycle_status"] not in ("EOL_ANNOUNCED", "LAST_TIME_BUY"):
            continue
        notice = announced_notice_for_part(part["id"])
        if notice is None:
            continue
        if part["lifecycle_status"] == "EOL_ANNOUNCED" and now >= notice["last_order_date"]:
            part["lifecycle_status"] = "LAST_TIME_BUY"
            store.touch(part)
        if part["lifecycle_status"] == "LAST_TIME_BUY" and now >= notice["last_ship_date"]:
            part["lifecycle_status"] = "DISCONTINUED"
            store.touch(part)
            notice["status"] = "COMPLETED"
            store.touch(notice)

    # Design wins: ACTIVE -> COMPLETED once the clock reaches start_date + 4 years.
    for win in store.design_wins.values():
        if win["status"] == "ACTIVE" and now >= add_years(win["start_date"], C.TAIL_YEARS):
            win["status"] = "COMPLETED"
            store.touch(win)

    # CapacityPool.status and DesignWin recognized-revenue fields are derived
    # from the clock at read time, so they need no stored transition here.
