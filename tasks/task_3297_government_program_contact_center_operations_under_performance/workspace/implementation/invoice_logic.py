"""Invoice preparation, recompute, and cure-period reconciliation."""

from datetime import timedelta

import db
from calculations import (binding_service_level, compute_line_withholding,
                          gross_cents_for, is_compliant, measured_abandon,
                          measured_asa, measured_qa_avg, staffing_actual,
                          staffing_target_for)
from clock import iso_now, now, parse_iso, period_end
from errors import ApiError
from models import make_cure_period, make_invoice_line, touch

CURE_WINDOW_HOURS = 72


def _line_program_code(line):
    sl = db.service_levels.get(line["service_level_id"])
    return sl["program_code"] if sl else None


def _distinct_program_metric_pairs(contract_id, period):
    """Binding service levels at period end, one per (program_code, metric)."""
    pend = period_end(period)
    pairs = {}
    for sl in db.service_levels.values():
        if sl["contract_id"] != contract_id:
            continue
        if sl["status"] not in ("EFFECTIVE", "SUPERSEDED", "ARCHIVED"):
            continue
        if parse_iso(sl["effective_from"]) > pend:
            continue
        pairs.setdefault((sl["program_code"], sl["metric"]), None)
    out = []
    for (program, metric) in pairs.keys():
        binding = binding_service_level(contract_id, program, metric, pend)
        if binding is not None:
            out.append(binding)
    return out


def _contract_cumulative_gross_through(contract_id, period):
    """Sum of gross_cents of invoices of this contract with period <= given period (chronological string order)."""
    total = 0
    for inv in db.invoices.values():
        if inv["contract_id"] != contract_id:
            continue
        if inv["period"] > period:
            continue
        g = inv.get("gross_cents")
        if g is None:
            continue
        total += int(g)
    return total


def _contract_withheld_cum_before(contract_id, period, exclude_invoice_id):
    """Sum of withheld_cents across invoices of this contract with period strictly before given period."""
    total = 0
    for inv in db.invoices.values():
        if inv["contract_id"] != contract_id:
            continue
        if inv["id"] == exclude_invoice_id:
            continue
        if inv["period"] >= period:
            continue
        w = inv.get("withheld_cents")
        if w is None:
            continue
        total += int(w)
    return total


def _measure_line(line, contract, period):
    sl = db.service_levels[line["service_level_id"]]
    program = sl["program_code"]
    metric = sl["metric"]
    if metric == "ASA":
        line["measured_value"] = measured_asa(contract["id"], program, period)
    elif metric == "ABANDON":
        line["measured_value"] = measured_abandon(contract["id"], program, period)
    elif metric == "QA_AVG":
        line["measured_value"] = measured_qa_avg(contract["id"], program, period)
    pend = period_end(period)
    line["staffing_actual"] = staffing_actual(program, pend)
    line["staffing_target"] = staffing_target_for(contract["id"], program, pend)
    line["compliant"] = is_compliant(metric, line["measured_value"], sl["target"],
                                     line["staffing_actual"], line["staffing_target"])


def _has_completed_cure_period(service_level_id):
    for cp in db.cure_periods.values():
        line = db.invoice_lines.get(cp["invoice_line_id"])
        if line is None:
            continue
        if line["service_level_id"] != service_level_id:
            continue
        if cp["status"] in ("REMEDIED", "FORFEIT"):
            return True
    return False


def prepare_invoice(invoice, preparer_user_id):
    contract = db.contracts[invoice["contract_id"]]
    period = invoice["period"]
    # Remove any existing lines (in case re-prepare) and their PENDING cure periods.
    existing_lines = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]]
    for line in existing_lines:
        for cp in list(db.cure_periods.values()):
            if cp["invoice_line_id"] == line["id"] and cp["status"] == "PENDING":
                del db.cure_periods[cp["id"]]
        del db.invoice_lines[line["id"]]

    invoice["preparer_user_id"] = preparer_user_id
    invoice["gross_cents"] = gross_cents_for(contract, period)
    gross = invoice["gross_cents"]

    bindings = _distinct_program_metric_pairs(contract["id"], period)
    auto_review = False
    for sl in bindings:
        line = make_invoice_line(invoice["id"], sl["id"], sl["metric"])
        db.invoice_lines[line["id"]] = line
        _measure_line(line, contract, period)
        if not line["compliant"]:
            cumulative_gross_through = _contract_cumulative_gross_through(contract["id"], period)
            withheld_before = _contract_withheld_cum_before(contract["id"], period, invoice["id"])
            line["withheld_cents"] = compute_line_withholding(
                line, sl, contract, gross, cumulative_gross_through, withheld_before)
            n = now()
            cp = make_cure_period(line["id"], iso_now(),
                                  (n + timedelta(hours=CURE_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%S.") + f"{(n + timedelta(hours=CURE_WINDOW_HOURS)).microsecond // 1000:03d}Z",
                                  sl["remedy_fee_cents"])
            db.cure_periods[cp["id"]] = cp
        else:
            line["withheld_cents"] = 0
        if _has_completed_cure_period(sl["id"]):
            auto_review = True

    invoice["withheld_cents"] = sum(int(l["withheld_cents"]) for l in db.invoice_lines.values()
                                    if l["invoice_id"] == invoice["id"])
    invoice["net_cents"] = int(gross) - int(invoice["withheld_cents"])
    invoice["auto_review"] = auto_review
    touch(invoice)
    # Resync contract.withheld_cents_cum
    contract["withheld_cents_cum"] = sum(int(inv.get("withheld_cents") or 0)
                                         for inv in db.invoices.values()
                                         if inv["contract_id"] == contract["id"])
    return invoice


def recompute_invoice(invoice):
    contract = db.contracts[invoice["contract_id"]]
    period = invoice["period"]
    invoice["gross_cents"] = gross_cents_for(contract, period)
    gross = invoice["gross_cents"]
    auto_review = False
    lines = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]]
    for line in lines:
        sl = db.service_levels[line["service_level_id"]]
        _measure_line(line, contract, period)
        # A remedy payment cures the breach permanently: the line keeps its
        # released (zero) withholding across recomputes and no new cure
        # period opens for it.
        cured = any(cp["invoice_line_id"] == line["id"] and cp["status"] == "REMEDIED"
                    for cp in db.cure_periods.values())
        if not line["compliant"] and not cured:
            cumulative_gross_through = _contract_cumulative_gross_through(contract["id"], period)
            withheld_before = _contract_withheld_cum_before(contract["id"], period, invoice["id"])
            line["withheld_cents"] = compute_line_withholding(
                line, sl, contract, gross, cumulative_gross_through, withheld_before)
            # Ensure a PENDING cure period exists for this line.
            existing_pending = [cp for cp in db.cure_periods.values()
                                if cp["invoice_line_id"] == line["id"] and cp["status"] == "PENDING"]
            if not existing_pending:
                n = now()
                cp = make_cure_period(line["id"], iso_now(),
                                      (n + timedelta(hours=CURE_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%S.") + f"{(n + timedelta(hours=CURE_WINDOW_HOURS)).microsecond // 1000:03d}Z",
                                      sl["remedy_fee_cents"])
                db.cure_periods[cp["id"]] = cp
        else:
            line["withheld_cents"] = 0
            # Remove PENDING cure periods for now-compliant lines.
            for cp in list(db.cure_periods.values()):
                if cp["invoice_line_id"] == line["id"] and cp["status"] == "PENDING":
                    del db.cure_periods[cp["id"]]
        if _has_completed_cure_period(sl["id"]):
            auto_review = True
        touch(line)

    invoice["withheld_cents"] = sum(int(l["withheld_cents"]) for l in db.invoice_lines.values()
                                    if l["invoice_id"] == invoice["id"])
    invoice["net_cents"] = int(gross) - int(invoice["withheld_cents"])
    invoice["auto_review"] = auto_review
    touch(invoice)
    contract["withheld_cents_cum"] = sum(int(inv.get("withheld_cents") or 0)
                                         for inv in db.invoices.values()
                                         if inv["contract_id"] == contract["id"])
    return invoice


def pay_cure_remedy(cure_period):
    if cure_period["status"] != "PENDING":
        raise ApiError("ERR_CURE_WINDOW_CLOSED", "Cure period is not PENDING", 409)
    n = now()
    if parse_iso(cure_period["deadline"]) < n:
        raise ApiError("ERR_CURE_WINDOW_CLOSED", "Cure window has closed", 409)
    cure_period["status"] = "REMEDIED"
    touch(cure_period)
    line = db.invoice_lines.get(cure_period["invoice_line_id"])
    if line is None:
        return cure_period
    released = int(line["withheld_cents"] or 0)
    line["withheld_cents"] = 0
    touch(line)
    invoice = db.invoices.get(line["invoice_id"])
    if invoice is not None:
        invoice["withheld_cents"] = sum(int(l["withheld_cents"]) for l in db.invoice_lines.values()
                                        if l["invoice_id"] == invoice["id"])
        invoice["net_cents"] = int(invoice.get("gross_cents") or 0) - int(invoice["withheld_cents"])
        touch(invoice)
        contract = db.contracts.get(invoice["contract_id"])
        if contract is not None:
            contract["withheld_cents_cum"] = int(contract.get("withheld_cents_cum", 0)) - released
            contract["cure_periods_used"] = int(contract.get("cure_periods_used", 0)) + 1
    return cure_period
