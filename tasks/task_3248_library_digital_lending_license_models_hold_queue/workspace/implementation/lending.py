"""Lending engine: promotion cascade, checkout/return/expire, epoch sweep, auto-purchase."""
from datetime import timedelta
from db import stores
from timeutil import CLOCK, fmt_ts, round_half_up
from engine import (
    new_id, now, touch_common, write_event, select_license, effective_copies,
    holds_queue, recompute_waits_for_title, discounted_cpc_charge, recompute_fund,
    fund_covering, sync_patron_counters, consortium_of_title,
)
from errors import err, ERR_NO_LICENSE_AVAILABLE, ERR_LICENSE_BALANCE_DEPLETED


def _reserve_for_ready(hold, license_id):
    lic = stores["licenses"][license_id]
    lic["_reserved"] += 1
    hold["_reserved_license_id"] = license_id


def _release_ready_reservation(hold):
    lid = hold.pop("_reserved_license_id", None)
    if lid:
        lic = stores["licenses"].get(lid)
        if lic is not None and lic["_reserved"] > 0:
            lic["_reserved"] -= 1
    return lid


def run_promotion(title_id, collect=None):
    """Promote eligible PLACED holds to READY while lendable copies exist.
    Returns count. If collect (a list) is given, promoted hold ids are appended."""
    promoted = 0
    title = stores["titles"].get(title_id)
    if title is None:
        return 0
    while True:
        lic = _find_promotable_license(title)
        if lic is None:
            break
        cand = _next_eligible_hold(title, lic)
        if cand is None:
            break
        _promote(cand, lic)
        promoted += 1
        if collect is not None:
            collect.append(cand["id"])
        if _EPOCH_COLLECT is not None:
            _EPOCH_COLLECT.append(cand["id"])
    if promoted:
        recompute_waits_for_title(title_id)
    return promoted


# When an epoch is in progress, every promotion — however it was triggered
# (return-path expiry, ready-hold lapse, fulfillment, auto-purchase) — is
# counted in the epoch's holds_promoted counter.
_EPOCH_COLLECT = None


def _reset_epoch_collect():
    global _EPOCH_COLLECT
    _EPOCH_COLLECT = None


def _find_promotable_license(title):
    """An ACTIVE license with capacity that can host a reserved/loaned copy."""
    cands = []
    for lic in stores["licenses"].values():
        if lic["title_id"] != title["id"] or lic["status"] != "ACTIVE":
            continue
        model = lic["model"]
        if model == "OCOU":
            if lic["copies_on_loan"] + lic["_reserved"] < lic["copies_total"]:
                cands.append(lic)
        elif model == "METERED_CIRC":
            if lic["circs_consumed"] < lic["circs_total"]:
                cands.append(lic)
        elif model == "METERED_TIME":
            exp = lic.get("expires_at_dt")
            if exp is not None and exp > now():
                cands.append(lic)
        elif model == "COST_PER_CIRC":
            cands.append(lic)
        # SIMULTANEOUS_USE never queues -> excluded
    if not cands:
        return None
    order = {"OCOU": 0, "METERED_TIME": 1, "METERED_CIRC": 2, "COST_PER_CIRC": 3}
    cands.sort(key=lambda l: (order[l["model"]], l["created_at"], l["_seq"]))
    return cands[0]


def _next_eligible_hold(title, lic):
    cands = []
    for h in stores["holds"].values():
        if h["title_id"] != title["id"] or h["status"] != "PLACED":
            continue
        if h["library_id"] == lic["library_id"] or title["sharing_scope"] == "CONSORTIUM":
            cands.append(h)
    if not cands:
        return None
    cands.sort(key=lambda h: (h["placed_at"], h["created_at"], h["_seq"]))
    return cands[0]


def _promote(hold, lic):
    lib = stores["libraries"][hold["library_id"]]
    hold["status"] = "READY"
    hold["ready_since"] = fmt_ts(now())
    hold["ready_until"] = fmt_ts(now() + timedelta(hours=lib["pickup_window_hours"]))
    hold["_ready_until_dt"] = now() + timedelta(hours=lib["pickup_window_hours"])
    if lic["model"] == "OCOU":
        _reserve_for_ready(hold, lic["id"])
    else:
        hold["_reserved_license_id"] = lic["id"]
    touch_common(hold)
    write_event(hold["library_id"], hold["title_id"], hold["patron_id"], None,
                hold["id"], lic["id"], "HOLD_READY")


def perform_checkout(patron, title, library, lic, hold=None, is_skip=False):
    """Create an ACTIVE loan on the chosen license. Assumes all gates passed."""
    consortium = consortium_of_title(title)
    loan_days = library["skip_the_line_loan_days"] if is_skip else library["loan_period_days"]
    due = now() + timedelta(days=loan_days)
    if lic["model"] in ("METERED_TIME", "SIMULTANEOUS_USE"):
        exp = lic.get("expires_at_dt")
        if exp is not None and due > exp:
            due = exp
    charge = 0
    if lic["model"] == "COST_PER_CIRC":
        charge = discounted_cpc_charge(title)
        if lic["balance_cents"] < charge:
            raise err(ERR_LICENSE_BALANCE_DEPLETED, "CPC license balance cannot cover the charge")
        lic["balance_cents"] -= charge
        fund = fund_covering(patron["library_id"], now())
        if fund is not None:
            recompute_fund(fund)
    # claim path: promotion earmarked an OCOU copy; converting earmark -> loan
    if hold is not None and lic["model"] == "OCOU" and lic.get("_reserved", 0) > 0:
        lic["_reserved"] -= 1
    if lic["model"] == "OCOU":
        lic["copies_on_loan"] += 1
    elif lic["model"] == "METERED_CIRC":
        lic["circs_consumed"] += 1
    loan = {
        "id": new_id(),
        "license_id": lic["id"],
        "patron_id": patron["id"],
        "hold_id": hold["id"] if hold else None,
        "is_skip_the_line": bool(is_skip),
        "checkout_at": fmt_ts(now()),
        "due_at": fmt_ts(due),
        "returned_at": None,
        "renewals_used": 0,
        "circ_price_charged_cents": charge,
        "status": "ACTIVE",
        "_seq": None,
    }
    touch_common(loan, created=True)
    loan["_seq"] = len(stores["loans"])
    stores["loans"][loan["id"]] = loan
    write_event(patron["library_id"], title["id"], patron["id"], loan["id"],
                hold["id"] if hold else None, lic["id"], "CHECKOUT", charge)
    sync_patron_counters(patron["id"])
    return loan


def do_return(loan):
    """ACTIVE -> RETURNED with metering unwind + promotion cascade."""
    lic = stores["licenses"][loan["license_id"]]
    loan["status"] = "RETURNED"
    loan["returned_at"] = fmt_ts(now())
    freed = False
    if lic["model"] == "OCOU":
        lic["copies_on_loan"] = max(0, lic["copies_on_loan"] - 1)
        freed = True
    elif lic["model"] == "METERED_CIRC":
        checkout_dt = loan["_checkout_dt"]
        if now() < checkout_dt + timedelta(hours=2) and lic["circs_consumed"] > 0:
            lic["circs_consumed"] -= 1
        freed = True
    elif lic["model"] in ("METERED_TIME", "SIMULTANEOUS_USE"):
        freed = lic["status"] == "ACTIVE" and lic.get("expires_at_dt") is not None \
            and lic["expires_at_dt"] > now()
    elif lic["model"] == "COST_PER_CIRC":
        freed = lic["status"] == "ACTIVE" and lic["balance_cents"] is not None \
            and lic["balance_cents"] >= discounted_cpc_charge(
                stores["titles"][lic["title_id"]])
    touch_common(loan)
    sync_patron_counters(loan["patron_id"])
    write_event(loan["_library_id"], loan["_title_id"], loan["patron_id"], loan["id"],
                loan.get("hold_id"), lic["id"], "RETURN")
    if freed:
        run_promotion(loan["_title_id"])


def do_expire_loan(loan):
    lic = stores["licenses"][loan["license_id"]]
    loan["status"] = "EXPIRED"
    freed = False
    if lic["model"] == "OCOU":
        lic["copies_on_loan"] = max(0, lic["copies_on_loan"] - 1)
        freed = True
    elif lic["model"] == "METERED_CIRC":
        freed = True
    elif lic["model"] in ("METERED_TIME", "SIMULTANEOUS_USE"):
        freed = lic["status"] == "ACTIVE" and lic.get("expires_at_dt") is not None \
            and lic["expires_at_dt"] > now()
    elif lic["model"] == "COST_PER_CIRC":
        freed = lic["status"] == "ACTIVE" and lic["balance_cents"] is not None \
            and lic["balance_cents"] >= discounted_cpc_charge(
                stores["titles"][lic["title_id"]])
    touch_common(loan)
    sync_patron_counters(loan["patron_id"])
    write_event(loan["_library_id"], loan["_title_id"], loan["patron_id"], loan["id"],
                loan.get("hold_id"), lic["id"], "LOAN_EXPIRED")
    if freed:
        run_promotion(loan["_title_id"])


def do_expire_ready_hold(hold):
    lic_id = _release_ready_reservation(hold)
    hold["status"] = "EXPIRED"
    touch_common(hold)
    sync_patron_counters(hold["patron_id"])
    write_event(hold["library_id"], hold["title_id"], hold["patron_id"], None,
                hold["id"], lic_id, "HOLD_EXPIRED")
    run_promotion(hold["title_id"])


def fulfill_order(order, invoiced_cost, consortium_admin_op=False):
    """Create the license, move the fund ledger, write PURCHASE, promote. Returns license."""
    fund = stores["funds"][order["budget_fund_id"]]
    title = stores["titles"][order["title_id"]]
    model = order["model"]
    lic = {
        "id": new_id(),
        "title_id": title["id"],
        "library_id": order["library_id"],
        "acquisition_order_id": order["id"],
        "model": model,
        "copies_total": order["copies"] if model == "OCOU" else 1,
        "copies_on_loan": 0,
        "activated_at": fmt_ts(now()),
        "expires_at": None,
        "circs_total": None,
        "circs_consumed": None,
        "balance_cents": None,
        "status": "ACTIVE",
        "_reserved": 0,
    }
    if model == "METERED_TIME":
        lic["expires_at"] = fmt_ts(now() + timedelta(days=title["metered_time_days"]))
    elif model == "SIMULTANEOUS_USE":
        lic["expires_at"] = fmt_ts(now() + timedelta(days=title["simultaneous_use_days"]))
    elif model == "METERED_CIRC":
        lic["circs_total"] = title["metered_circ_count"]
        lic["circs_consumed"] = 0
    elif model == "COST_PER_CIRC":
        lic["balance_cents"] = order.get("prepaid_balance_cents")
    touch_common(lic, created=True)
    lic["_seq"] = len(stores["licenses"])
    exp_dt = None
    from timeutil import parse_iso
    if lic["expires_at"]:
        exp_dt = parse_iso(lic["expires_at"])
    lic["expires_at_dt"] = exp_dt
    stores["licenses"][lic["id"]] = lic

    order["status"] = "FULFILLED"
    order["invoiced_cost_cents"] = invoiced_cost
    touch_common(order)
    touch_common(fund)
    recompute_fund(fund)
    write_event(order["library_id"], title["id"], None, None, None, lic["id"],
                "PURCHASE", invoiced_cost)
    run_promotion(title["id"])
    return lic


# ---------------------------------------------------------------- epoch

def run_epoch():
    res = {"expired_loans": 0, "expired_holds": 0, "expired_licenses": 0,
           "exhausted_licenses": 0, "expired_patrons": 0,
           "auto_orders_created": 0, "holds_promoted": 0}
    ts = now()
    epoch_promoted = []
    global _EPOCH_COLLECT
    _EPOCH_COLLECT = epoch_promoted

    # (1) expire due loans
    for loan in list(stores["loans"].values()):
        if loan["status"] == "ACTIVE" and loan["_due_dt"] <= ts:
            do_expire_loan(loan)
            res["expired_loans"] += 1

    # (2) expire READY holds past pickup window
    for hold in list(stores["holds"].values()):
        if hold["status"] == "READY" and hold["_ready_until_dt"] is not None and hold["_ready_until_dt"] <= ts:
            do_expire_ready_hold(hold)
            res["expired_holds"] += 1

    # (3) expire metered licenses past term
    for lic in list(stores["licenses"].values()):
        if lic["status"] == "ACTIVE" and lic["model"] in ("METERED_TIME", "SIMULTANEOUS_USE"):
            exp = lic.get("expires_at_dt")
            if exp is not None and exp <= ts:
                lic["status"] = "EXPIRED"
                touch_common(lic)
                res["expired_licenses"] += 1

    # (4) expire patron cards
    for patron in list(stores["patrons"].values()):
        if patron["status"] in ("ACTIVE", "SUSPENDED") and patron["_card_expires_dt"] <= ts:
            patron["status"] = "EXPIRED"
            touch_common(patron)
            res["expired_patrons"] += 1
            for hold in list(stores["holds"].values()):
                if hold["patron_id"] != patron["id"]:
                    continue
                if hold["status"] in ("PLACED", "SUSPENDED"):
                    hold["status"] = "CANCELLED"
                    touch_common(hold)
                    sync_patron_counters(patron["id"])
                elif hold["status"] == "READY":
                    do_expire_ready_hold(hold)

    # (5) deplete licenses -> EXHAUSTED
    for lic in list(stores["licenses"].values()):
        if lic["status"] != "ACTIVE":
            continue
        if lic["model"] == "METERED_CIRC" and lic["circs_consumed"] >= lic["circs_total"]:
            lic["status"] = "EXHAUSTED"
            touch_common(lic)
            res["exhausted_licenses"] += 1
        elif lic["model"] == "COST_PER_CIRC":
            title = stores["titles"].get(lic["title_id"])
            if title is not None and lic["balance_cents"] is not None \
                    and lic["balance_cents"] < discounted_cpc_charge(title):
                lic["status"] = "EXHAUSTED"
                touch_common(lic)
                res["exhausted_licenses"] += 1

    # (6) auto-purchase sweep
    res["auto_orders_created"] = _auto_purchase_sweep()

    # (7) promotion sweep
    for title in list(stores["titles"].values()):
        run_promotion(title["id"], collect=epoch_promoted)
    res["holds_promoted"] = len(epoch_promoted)
    _reset_epoch_collect()
    return res


def _auto_purchase_sweep():
    created = 0
    ts = now()
    for lib in list(stores["libraries"].values()):
        if not lib.get("auto_purchase_enabled") or lib["status"] != "ACTIVE":
            continue
        consortium = stores["consortiums"].get(lib["consortium_id"])
        if consortium is None or consortium["status"] != "ACTIVE":
            continue
        # titles with PLACED/SUSPENDED holds at this library
        title_ids = {h["title_id"] for h in stores["holds"].values()
                     if h["library_id"] == lib["id"] and h["status"] in ("PLACED", "SUSPENDED")}
        for tid in sorted(title_ids):
            title = stores["titles"].get(tid)
            if title is None:
                continue
            holds_count = sum(1 for h in stores["holds"].values()
                              if h["library_id"] == lib["id"] and h["title_id"] == tid
                              and h["status"] in ("PLACED", "SUSPENDED"))
            C = max(effective_copies(title, lib["id"]), 1)
            if holds_count / C < lib["holds_per_copy_ratio"]:
                continue
            # pessimistic wait of the newest such hold
            q = [h for h in holds_queue(tid) if h["library_id"] == lib["id"]]
            if not q:
                continue
            newest = q[-1]
            # 1-based queue position of the newest hold (matches compute_waits)
            pos = sum(1 for h in holds_queue(tid)
                      if h["library_id"] == lib["id"]
                      and (h["placed_at"], h["created_at"], h["_seq"])
                      <= (newest["placed_at"], newest["created_at"], newest["_seq"]))
            pess_cycles = -(-pos // C)  # ceil
            pessimistic = pess_cycles * (
                lib["loan_period_days"] + lib["max_renewals"] * lib["renewal_period_days"])
            if pessimistic <= lib["wait_target_days"]:
                continue
            import math
            # Top-up sizing: the holds backlog holds_count divided by
            # holds_per_copy_ratio, rounded up, minus the current C. When the
            # fire conditions hold the sweep buys at least one copy — the
            # pinned ratio boundary ("holds exactly at the ratio do trigger")
            # pre-empts the zero-or-negative skip, which exists to suppress
            # top-ups on titles whose queue no longer needs them.
            needed = math.ceil(holds_count / lib["holds_per_copy_ratio"]) - C
            if needed < 1:
                needed = 1
            price = title["price_ocou_cents"]
            if price <= 0:
                continue
            copies = needed
            if copies * price > lib["auto_purchase_max_cents"]:
                copies = lib["auto_purchase_max_cents"] // price
            if copies <= 0:
                continue
            estimated = copies * price
            fund = fund_covering(lib["id"], ts)
            if fund is None:
                continue
            recompute_fund(fund)
            if estimated > fund["available_committed_cents"]:
                continue
            # create-and-fulfill commits the estimate first so concurrent titles
            # in the same sweep see the shrink in available_committed_cents
            fund["committed_cents"] += estimated
            order = {
                "id": new_id(),
                "library_id": lib["id"],
                "budget_fund_id": fund["id"],
                "title_id": tid,
                "model": "OCOU",
                "copies": copies,
                "prepaid_balance_cents": None,
                "estimated_cost_cents": estimated,
                "invoiced_cost_cents": None,
                "origin": "AUTO_RATIO",
                "status": "APPROVED",
            }
            touch_common(order, created=True)
            order["_seq"] = len(stores["orders"])
            stores["orders"][order["id"]] = order
            touch_common(fund)
            recompute_fund(fund)
            fulfill_order(order, estimated, consortium_admin_op=True)
            created += 1
    return created
