"""System engine: logical-clock sweeps, LSI accrual, lottery allocation, housing."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from helpers import parse_dt, add_months, months_between, round_half_up, touch

NO_SHOW_GRACE_HOURS = 24


# ---------- LSI accrual ----------

def lsi_accrual(contract, project, n):
    """Accrued LSI cents at contract month offset n. Rounds each month-step half-up."""
    A = project["authorized_cost_cents"]
    T = contract["term_months"]
    m0 = project.get("in_service_month_offset") or 0
    n = max(0, min(n, T))
    if n <= m0:
        return 0
    if contract["lsi_annual_schedule_type"] == "LINEAR":
        return _round_steps_linear(A, T, m0, n)
    return _round_steps_declining(A, T, m0, n)


def _round_steps_linear(A, T, m0, n):
    per_month = Decimal(A) / Decimal(T)
    step = int(per_month.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return step * (n - m0)


def _phase_bounds(T):
    """Phase windows as (start_month_excl, end_month_incl) in 1-based month indices."""
    p1 = round_half_up(Decimal(T) * Decimal("0.5"))
    p2 = round_half_up(Decimal(T) * Decimal("0.4"))
    p3 = T - p1 - p2
    return [(0, p1), (p1, p1 + p2), (p1 + p2, p1 + p2 + p3)]


def _round_steps_declining(A, T, m0, n):
    rates = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
    bounds = _phase_bounds(T)
    total = 0
    for rate, (lo, hi) in zip(rates, bounds):
        window = hi - lo
        if window <= 0:
            continue
        per_month = (Decimal(A) * rate) / Decimal(window)
        step = int(per_month.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        # months strictly after m0 within (lo, hi] and <= n (1-based months 1..n)
        count = max(0, min(n, hi) - max(m0, lo))
        total += step * count
    return total


def current_offset(contract):
    return months_between(parse_dt(contract["start_date"]), store.clock)


def project_out(project):
    """Serialize a capital project with live-accrued LSI."""
    contract = store.contracts[project["contract_id"]]
    out = {k: v for k, v in project.items() if not k.startswith("_")}
    if project["status"] == "EXPENDED":
        out["accrued_lsi_cents"] = project.get("accrued_lsi_cents", 0)
    elif project.get("in_service_month_offset") is not None and project["status"] in ("COMPLETED", "APPROVED"):
        out["accrued_lsi_cents"] = lsi_accrual(contract, project, current_offset(contract))
    else:
        out["accrued_lsi_cents"] = project.get("accrued_lsi_cents", 0)
    return out


# ---------- Inventory / lottery ----------

def _nights_of(res):
    ci = parse_dt(res["check_in_date"])
    co = parse_dt(res["check_out_date"])
    return res["nights"]


def allocated_on_night(season_id, room_class_id, night_start, exclude_id=None):
    """Count CONFIRMED reservations covering the night [night_start, +1day)."""
    night_end = night_start + timedelta(days=1)
    count = 0
    for r in store.reservations.values():
        if r["season_id"] != season_id or r["room_class_id"] != room_class_id:
            continue
        if r["status"] != "CONFIRMED" or r["id"] == exclude_id:
            continue
        ci, co = parse_dt(r["check_in_date"]), parse_dt(r["check_out_date"])
        if ci < night_end and co > night_start:
            count += 1
    return count


def reservation_fits(res, room_class):
    ci, co = parse_dt(res["check_in_date"]), parse_dt(res["check_out_date"])
    night = ci
    while night < co:
        if allocated_on_night(res["season_id"], res["room_class_id"], night, exclude_id=res["id"]) >= room_class["total_rooms"]:
            return False
        night += timedelta(days=1)
    return True


def _res_sort_key(r):
    return (r["_seq"], r["guest_ref"])


def run_allocation(season_id):
    """Lottery run at window close: confirm fitting REQUESTED reservations oldest-first."""
    season = store.seasons[season_id]
    candidates = [
        r for r in store.reservations.values()
        if r["season_id"] == season_id and r["status"] == "REQUESTED"
    ]
    for res in sorted(candidates, key=_res_sort_key):
        rc = store.room_classes.get(res["room_class_id"])
        if rc and reservation_fits(res, rc):
            res["status"] = "CONFIRMED"
            touch(res)


def try_immediate_allocate(res):
    """After window close: allocate immediately if it fits."""
    rc = store.room_classes.get(res["room_class_id"])
    if rc and reservation_fits(res, rc):
        res["status"] = "CONFIRMED"
        touch(res)


def promote_waitlist(season_id):
    """After a cancellation releases inventory: promote longest-waiting fitting request."""
    season = store.seasons[season_id]
    candidates = [
        r for r in store.reservations.values()
        if r["season_id"] == season_id and r["status"] == "REQUESTED"
    ]
    for res in sorted(candidates, key=_res_sort_key):
        rc = store.room_classes.get(res["room_class_id"])
        if rc and reservation_fits(res, rc):
            res["status"] = "CONFIRMED"
            touch(res)
            return


# ---------- Housing ----------

def unit_occupied_beds(unit_id, season_id):
    return sum(
        1 for h in store.hires.values()
        if h["housing_unit_id"] == unit_id and h["season_id"] == season_id
        and h["status"] in ("HIRED", "ARRIVED")
    )


# ---------- Logical clock sweep ----------

def advance_clock(new_dt):
    store.clock = new_dt
    _sweep_seasons_open()
    _sweep_lottery_windows()
    _sweep_no_shows()
    _sweep_seasons_close()
    _sweep_filing_expiry()
    _sweep_contract_expiry()
    _sweep_study_staleness()


def _sweep_seasons_open():
    for s in store.seasons.values():
        if s["status"] == "PLANNED" and store.clock >= parse_dt(s["open_date"]):
            s["status"] = "OPEN"
            touch(s)


def _sweep_lottery_windows():
    for s in store.seasons.values():
        close_at = parse_dt(s["lottery_open_date"]) + timedelta(hours=s["lottery_window_hours"])
        if store.clock >= close_at and not s.get("_lottery_ran"):
            s["_lottery_ran"] = True
            run_allocation(s["id"])


def _sweep_no_shows():
    for r in store.reservations.values():
        if r["status"] == "CONFIRMED" and not r.get("_checked_in"):
            ci = parse_dt(r["check_in_date"])
            if store.clock > ci + timedelta(hours=NO_SHOW_GRACE_HOURS):
                r["status"] = "NO_SHOW"
                r["cancellation_fee_cents"] = r["deposit_cents"]
                touch(r)
    for h in store.hires.values():
        if h["status"] == "HIRED":
            arr = parse_dt(h["arrival_date"])
            if store.clock > arr + timedelta(hours=NO_SHOW_GRACE_HOURS):
                h["status"] = "NO_SHOW"
                touch(h)
                v = store.vouchers.get(h.get("transport_voucher_id") or "")
                if v and v["status"] == "BOOKED":
                    v["status"] = "VOID"
                    touch(v)


def _sweep_seasons_close():
    for s in store.seasons.values():
        if s["status"] == "OPEN" and store.clock >= parse_dt(s["close_date"]):
            s["status"] = "CLOSED"
            touch(s)
            close_dt = parse_dt(s["close_date"])
            for r in store.reservations.values():
                if r["season_id"] == s["id"] and r["status"] == "CONFIRMED":
                    if parse_dt(r["check_out_date"]) <= close_dt:
                        r["status"] = "FULFILLED"
                    else:
                        r["status"] = "NO_SHOW"
                        r["cancellation_fee_cents"] = r["deposit_cents"]
                    touch(r)


def _sweep_filing_expiry():
    for f in store.filings.values():
        if f["status"] == "APPROVED":
            season = store.seasons.get(f["season_id"])
            if season and store.clock >= parse_dt(season["close_date"]):
                f["status"] = "EXPIRED"
                touch(f)


def _sweep_contract_expiry():
    for c in store.contracts.values():
        if c["status"] == "ACTIVE" and store.clock >= parse_dt(c["end_date"]):
            c["status"] = "EXPIRED"
            touch(c)
            for s in store.seasons.values():
                if s["contract_id"] == c["id"] and s["status"] != "RECONCILED":
                    if s["status"] != "CLOSED":
                        s["status"] = "CLOSED"
                        touch(s)
            for sl in store.service_lines.values():
                if sl["contract_id"] == c["id"] and sl["status"] != "SUSPENDED":
                    sl["status"] = "SUSPENDED"
                    touch(sl)


def _sweep_study_staleness():
    for st in store.studies.values():
        if st["status"] == "REGISTERED" and store.clock > parse_dt(st["valid_through"]):
            st["status"] = "STALE"
            touch(st)
