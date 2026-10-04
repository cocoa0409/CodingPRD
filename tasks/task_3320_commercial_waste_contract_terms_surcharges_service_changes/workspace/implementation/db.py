import uuid
from datetime import datetime, timedelta, timezone

from util import D, dfloor, rhu, fmt_ts, add_months, months_ceil

INITIAL_CLOCK = datetime(2026, 9, 1, tzinfo=timezone.utc)

CREDIT_FILING_WINDOW_DAYS = 14
DISPUTE_WINDOW_DAYS = 30
ROFR_UNDERCUT_CENTS = 500

CLOCK = INITIAL_CLOCK


def now():
    return CLOCK


def set_clock(dt):
    global CLOCK
    CLOCK = dt


def _wall_counter():
    if not hasattr(_wall_counter, "c"):
        _wall_counter.c = 0
    _wall_counter.c += 1
    return _wall_counter.c


def logical_now_iso():
    return fmt_ts(now())


def _next_created_at():
    """Logical-clock ISO timestamp (PRD §2.4: all temporal rules evaluate
    against the single server-side logical clock); ties broken by _seq."""
    return fmt_ts(now())


class Rec:
    """Base record with common system fields."""

    def __init__(self, **fields):
        self.id = str(uuid.uuid4())
        self.created_at = _next_created_at()
        self.updated_at = self.created_at
        self.version = 1
        self._seq = _wall_counter()
        for k, v in fields.items():
            setattr(self, k, v)

    def touch(self):
        self.updated_at = _next_created_at()
        self.version += 1

    def common(self):
        return {"id": self.id, "created_at": self.created_at,
                "updated_at": self.updated_at, "version": self.version}


class LedgerRec:
    def __init__(self, **fields):
        self.id = str(uuid.uuid4())
        self.created_at = _next_created_at()
        self._seq = _wall_counter()
        for k, v in fields.items():
            setattr(self, k, v)


# ---------- in-memory stores ----------

customers = {}
contracts = {}
lines = {}
pickup_events = {}
surcharge_configs = {}
rate_notices = {}
service_changes = {}
competing_offers = {}
cancellations = {}
service_credits = {}
rolloff_orders = {}
ledger_entries = {}


# ---------- serializers ----------

def ser_customer(c):
    out = c.common()
    out.update({"legal_name": c.legal_name, "billing_email": c.billing_email,
                "credit_balance_cents": c.credit_balance_cents})
    return out


def ser_contract(c):
    out = c.common()
    out.update({
        "customer_id": c.customer_id,
        "start_date": fmt_ts(c.start_date),
        "term_months": c.term_months,
        "end_date": fmt_ts(c.end_date),
        "renewal_term_months": c.renewal_term_months,
        "cancellation_notice_days": c.cancellation_notice_days,
        "rofr_enabled": c.rofr_enabled,
        "rofr_window_days": c.rofr_window_days,
        "status": c.status,
        "current_term_index": c.current_term_index,
        "base_monthly_total_cents": c.base_monthly_total_cents,
    })
    return out


def ser_line(l):
    out = l.common()
    out.update({"contract_id": l.contract_id, "container_size": l.container_size,
                "frequency_per_week": l.frequency_per_week,
                "base_rate_cents": l.base_rate_cents})
    return out


def ser_pickup(e):
    out = e.common()
    out.update({
        "service_line_id": e.service_line_id,
        "occurred_date": e.occurred_date,
        "outcome": e.outcome,
        "photo_evidence_url": e.photo_evidence_url,
        "contamination_fee_cents": e.contamination_fee_cents,
        "overweight_fee_cents": e.overweight_fee_cents,
        "dispute_status": e.dispute_status,
        "appeal_count": e.appeal_count,
    })
    return out


def ser_surcharge(s):
    out = s.common()
    out.update({
        "fuel_mode": s.fuel_mode,
        "fuel_fixed_pct": s.fuel_fixed_pct,
        "fuel_index_base": s.fuel_index_base,
        "fuel_index_current": s.fuel_index_current,
        "environmental_pct": s.environmental_pct,
        "admin_pct": s.admin_pct,
        "contamination_fee_cents": s.contamination_fee_cents,
        "overweight_fee_cents": s.overweight_fee_cents,
        "credit_pct_of_base": s.credit_pct_of_base,
        "effective_from": fmt_ts(s.effective_from),
    })
    return out


def ser_notice(n):
    out = n.common()
    out.update({"contract_id": n.contract_id, "reason": n.reason,
                "pct_increase": n.pct_increase,
                "effective_date": fmt_ts(n.effective_date),
                "status": n.status})
    return out


def ser_service_change(r):
    out = r.common()
    out.update({
        "service_line_id": r.service_line_id,
        "new_container_size": r.new_container_size,
        "new_frequency_per_week": r.new_frequency_per_week,
        "effective_date": fmt_ts(r.effective_date),
        "old_rate_cents": r.old_rate_cents,
        "quoted_new_rate_cents": r.quoted_new_rate_cents,
        "final_applied_rate_cents": r.final_applied_rate_cents,
        "status": r.status,
    })
    return out


def ser_offer(o):
    out = o.common()
    out.update({"contract_id": o.contract_id,
                "competitor_monthly_cents": o.competitor_monthly_cents,
                "evidence_doc_url": o.evidence_doc_url,
                "status": o.status})
    return out


def ser_cancellation(r):
    out = r.common()
    out.update({
        "contract_id": r.contract_id,
        "requested_end_date": fmt_ts(r.requested_end_date),
        "timely": r.timely,
        "months_remaining": r.months_remaining,
        "ld_base_cents": r.ld_base_cents,
        "ld_total_cents": r.ld_total_cents,
        "ld_status": r.ld_status,
        "status": r.status,
    })
    return out


def ser_credit(cr):
    out = cr.common()
    out.update({"service_line_id": cr.service_line_id,
                "pickup_event_id": cr.pickup_event_id,
                "credit_cents": cr.credit_cents,
                "filed_at": cr.filed_at,
                "status": cr.status})
    return out


def ser_rolloff(o):
    out = o.common()
    out.update({
        "customer_id": o.customer_id,
        "container_size": o.container_size,
        "delivery_date": fmt_ts(o.delivery_date),
        "rental_days": o.rental_days,
        "included_tons": o.included_tons,
        "actual_tons": o.actual_tons,
        "delivery_fee_cents": o.delivery_fee_cents,
        "daily_rental_cents": o.daily_rental_cents,
        "overage_ton_cents": o.overage_ton_cents,
        "total_cents": o.total_cents,
        "status": o.status,
    })
    return out


def ser_ledger(le):
    return {
        "id": le.id,
        "created_at": le.created_at,
        "contract_id": le.contract_id,
        "effective_date": fmt_ts(le.effective_date),
        "old_base_monthly_cents": le.old_base_monthly_cents,
        "new_base_monthly_cents": le.new_base_monthly_cents,
        "source": le.source,
    }


# ---------- shared services ----------

def active_config_at(t):
    """Active SurchargeConfig at datetime t: max effective_from <= t."""
    best = None
    for cfg in surcharge_configs.values():
        if cfg.effective_from <= t and (best is None or cfg.effective_from > best.effective_from):
            best = cfg
    return best


def recompute_contract_base(c):
    total = sum(l.base_rate_cents for l in lines.values() if l.contract_id == c.id)
    c.base_monthly_total_cents = total
    return total


def recompute_customer_balance(cust):
    total = 0
    for c in contracts.values():
        if c.customer_id != cust.id:
            continue
        line_ids = {l.id for l in lines.values() if l.contract_id == c.id}
        for cr in service_credits.values():
            if cr.status == "ACTIVE" and cr.service_line_id in line_ids:
                total += cr.credit_cents
        for cx in cancellations.values():
            if cx.contract_id == c.id and cx.ld_status == "ASSESSED":
                total -= cx.ld_total_cents
    cust.credit_balance_cents = total


def write_ledger(contract_id, effective_date, old_base, new_base, source):
    le = LedgerRec(contract_id=contract_id, effective_date=effective_date,
                   old_base_monthly_cents=old_base, new_base_monthly_cents=new_base,
                   source=source)
    ledger_entries[le.id] = le
    return le


def fuel_pct(cfg):
    if cfg.fuel_mode == "FIXED":
        return D(cfg.fuel_fixed_pct)
    cur = D(cfg.fuel_index_current)
    base = D(cfg.fuel_index_base)
    diff = cur - base
    if diff <= 0:
        return D(0)
    return diff / base


def apply_rate_notice(n):
    c = contracts[n.contract_id]
    old_base = c.base_monthly_total_cents
    for l in lines.values():
        if l.contract_id != c.id:
            continue
        l.base_rate_cents = rhu(D(l.base_rate_cents) * (1 + D(n.pct_increase)))
        l.touch()
    new_base = recompute_contract_base(c)
    write_ledger(c.id, n.effective_date, old_base, new_base, "RATE_NOTICE")
    n.status = "APPLIED"
    n.touch()
    c.touch()


def run_sweeps():
    t = now()
    # 1. auto-renewal
    for c in list(contracts.values()):
        if c.status == "ACTIVE" and c.end_date <= t:
            c.end_date = add_months(c.end_date, c.renewal_term_months)
            c.current_term_index += 1
            c.touch()
    # 2. rate-notice application
    for n in sorted(rate_notices.values(), key=lambda x: x._seq):
        if n.status == "SCHEDULED" and n.effective_date <= t:
            apply_rate_notice(n)
    # 3. termination finalization
    for cx in list(cancellations.values()):
        if cx.status == "APPROVED":
            c = contracts[cx.contract_id]
            if c.status == "TERMINATION_PENDING" and cx.requested_end_date <= t:
                c.status = "TERMINATED"
                c.touch()
