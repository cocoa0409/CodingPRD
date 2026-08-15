"""Business logic: calculations, state machine helpers, cascades.

All monetary arithmetic uses integer minor units and round-half-up rounding
applied exactly at the steps designated by the PRD.
"""

import hashlib
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import STORE, today, today_str, now_iso, touch, create_entity, parse_date
from errors import ApiError, ERR_FX_RATE_MISSING

ACCESSORIAL_CODES = {"LIFTGATE", "RESIDENTIAL", "INSIDE_DELIVERY", "DETENTION", "STORAGE"}
CHARGE_CODES = ACCESSORIAL_CODES | {"BASE_FREIGHT", "FUEL_SURCHARGE", "OTHER"}

FUZZY_AMOUNT_TOLERANCE_BP = 50
FUZZY_DATE_WINDOW_DAYS = 7

TIER1_THRESHOLD_MINOR = 1000000
TIER1_BP = 150
TIER2_THRESHOLD_MINOR = 5000000
TIER2_BP = 250

DUE_WINDOW_DAYS = 7
MAX_ROUNDS = 3

ACTIVE_EXCEPTION_STATES = {"OPEN", "CARRIER_NOTIFIED", "CARRIER_RESPONDED", "ESCALATED"}


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) to whole units, via Decimal."""
    num = Decimal(str(numerator))
    den = Decimal(str(denominator))
    return int((num / den).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_value(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# FX conversion
# ---------------------------------------------------------------------------

def find_fx_rate(client_id, from_currency, to_currency, as_of_date):
    """Latest FxRate with effective_date <= as_of; tie-break latest created_at."""
    if from_currency == to_currency:
        return None  # identity conversion, no record needed
    candidates = [
        r for r in STORE.fx_rates.values()
        if r["client_id"] == client_id
        and r["from_currency"] == from_currency
        and r["to_currency"] == to_currency
        and r["effective_date"] <= as_of_date
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["effective_date"], r["created_at"], r["_seq"]),
                    reverse=True)
    return candidates[0]


def has_fx_path(client_id, from_currency, to_currency, as_of_date):
    if from_currency == to_currency:
        return True
    return find_fx_rate(client_id, from_currency, to_currency, as_of_date) is not None


def convert_amount(amount_minor, client_id, from_currency, to_currency, as_of_date,
                   raise_on_missing=True):
    """Convert an integer minor-unit amount at the as-of FX rate."""
    if from_currency == to_currency:
        return amount_minor
    rate = find_fx_rate(client_id, from_currency, to_currency, as_of_date)
    if rate is None:
        if raise_on_missing:
            raise ApiError(ERR_FX_RATE_MISSING, 409,
                           "No FX rate path exists for the required conversion")
        return amount_minor
    return round_half_up_div(amount_minor * rate["rate_ppm"], 1000000)


def compute_home_total(invoice, client, approved_amount_minor):
    """Invoice home total: convert each line's approved share first (per-line
    rounding), THEN sum. Share is proportional to rated_amount_minor (billed
    amounts as weights when rated_total_minor == 0)."""
    lines = invoice_lines(invoice["id"])
    invoice_date = invoice["invoice_date"]
    from_ccy = invoice["currency"]
    to_ccy = client["home_currency"]
    if from_ccy == to_ccy:
        rate_ppm = 1000000
    else:
        rate = find_fx_rate(client["id"], from_ccy, to_ccy, invoice_date)
        if rate is None:
            raise ApiError(ERR_FX_RATE_MISSING, 409,
                           "No FX rate path exists for home currency conversion")
        rate_ppm = rate["rate_ppm"]
    rated_total = invoice["rated_total_minor"]
    total = 0
    if rated_total > 0:
        for line in lines:
            # round_half_up(approved * rated_i * rate_ppm / (rated_total * 1e6))
            num = approved_amount_minor * line["rated_amount_minor"] * rate_ppm
            den = rated_total * 1000000
            total += round_half_up_div(num, den)
    else:
        billed_total = invoice["billed_total_minor"]
        den = max(billed_total, 1) * 1000000
        for line in lines:
            num = approved_amount_minor * line["billed_amount_minor"] * rate_ppm
            total += round_half_up_div(num, den)
    return total


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def invoice_lines(invoice_id):
    rows = [l for l in STORE.lines.values() if l["invoice_id"] == invoice_id]
    return db.sort_default(rows)


def invoice_exceptions(invoice_id):
    rows = [e for e in STORE.exceptions.values() if e["invoice_id"] == invoice_id]
    return db.sort_default(rows)


def run_items_of(run_id):
    rows = [i for i in STORE.run_items.values() if i["payment_run_id"] == run_id]
    return db.sort_default(rows)


# ---------------------------------------------------------------------------
# Contract selection and line rating
# ---------------------------------------------------------------------------

def select_contract(carrier_id, as_of_date):
    """Carrier's ACTIVE/SUPERSEDED contracts whose half-open window contains
    as_of_date; latest activated_at, tie-break latest created_at."""
    candidates = [
        c for c in STORE.contracts.values()
        if c["carrier_id"] == carrier_id
        and c["status"] in ("ACTIVE", "SUPERSEDED")
        and c["effective_from"] <= as_of_date < c["effective_to"]
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (c["activated_at"] or "", c["created_at"], c["_seq"]),
        reverse=True,
    )
    return candidates[0]


def match_lane(contract, shipment):
    if contract is None or shipment is None:
        return None
    for lane in contract.get("lanes") or []:
        if (lane.get("origin_country") == shipment["origin_country"]
                and lane.get("dest_country") == shipment["dest_country"]
                and lane.get("mode") == shipment["mode"]):
            return lane
    return None


def _rate_base_freight(lane, weight_kg):
    breaks = lane.get("weight_breaks") or []
    tier = None
    for wb in breaks:
        if wb.get("min_kg") <= weight_kg:
            tier = wb  # ascending order: keep the last qualifying tier
        else:
            break
    if tier is None:
        base = 0
    else:
        base = round_half_up_value(
            Decimal(str(tier.get("rate_per_kg_minor"))) * Decimal(str(weight_kg))
        )
    minimum = lane.get("minimum_charge_minor", 0)
    return max(base, minimum)


def rate_invoice(invoice, policy="SHIP_DATE", forced_contract=None):
    """Run line_rating on an invoice. Returns True when rated, False when the
    NO_CONTRACT path applies (caller performs the exception transition).

    forced_contract: used by the supersede cascade to rate against the newly
    ACTIVE contract directly.
    """
    shipment = STORE.shipments.get(invoice.get("shipment_id")) if invoice.get("shipment_id") else None
    if forced_contract is not None:
        contract = forced_contract
    else:
        if policy == "INVOICE_DATE":
            as_of = invoice["invoice_date"]
        else:  # SHIP_DATE default
            as_of = shipment["ship_date"] if shipment else invoice["invoice_date"]
        contract = select_contract(invoice["carrier_id"], as_of)
    if contract is None:
        return False

    lines = invoice_lines(invoice["id"])
    needs_lane = any(l["charge_code"] != "OTHER" for l in lines)
    lane = match_lane(contract, shipment) if shipment else None
    if needs_lane and lane is None:
        return False

    base_rated = None
    for line in lines:
        if line["charge_code"] == "BASE_FREIGHT":
            base_rated = _rate_base_freight(lane, shipment["actual_weight_kg"])
            break
    if base_rated is None:
        base_rated = 0

    rated_total = 0
    for line in lines:
        code = line["charge_code"]
        invalid = False
        if code == "BASE_FREIGHT":
            rated = _rate_base_freight(lane, shipment["actual_weight_kg"])
        elif code == "FUEL_SURCHARGE":
            fuel_bp = lane.get("fuel_surcharge_pct_bp", 0)
            rated = round_half_up_div(base_rated * fuel_bp, 10000)
        elif code in ACCESSORIAL_CODES:
            offered = None
            for acc in (lane.get("accessorials") or []):
                if acc.get("code") == code:
                    offered = acc
                    break
            rendered = shipment.get("accessorials_rendered") or []
            if offered is None or code not in rendered:
                rated = 0
                invalid = True
            else:
                cap = round_half_up_div(base_rated * offered.get("cap_pct_bp", 0), 10000)
                rated = min(offered.get("flat_minor", 0), cap)
        else:  # OTHER: uncontested
            rated = line["billed_amount_minor"]
        if line.get("rated_amount_minor") != rated or line.get("_invalid_accessorial") != invalid:
            line["rated_amount_minor"] = rated
            line["_invalid_accessorial"] = invalid
            line["variance_minor"] = line["billed_amount_minor"] - rated
            touch(line)
        rated_total += rated

    invoice["rated_total_minor"] = rated_total
    invoice["variance_minor"] = invoice["billed_total_minor"] - rated_total
    invoice["variance_pct_bp"] = (
        abs(invoice["variance_minor"]) * 10000
    ) // max(rated_total, 1)
    invoice["rated_contract_id"] = contract["id"]
    return True


def open_exception(invoice, code, disputed_amount_minor):
    queue = "AUDIT_TEAM" if code in ("NO_CONTRACT", "DUPLICATE_FUZZY") else "CARRIER"
    exc = create_entity(STORE.exceptions, {
        "invoice_id": invoice["id"],
        "client_id": invoice["client_id"],
        "code": code,
        "disputed_amount_minor": disputed_amount_minor,
        "resolution_credit_minor": 0,
        "routed_queue": queue,
        "round_count": 0,
        "opened_date": today_str(),
        "status": "OPEN",
    })
    return exc


def no_contract_transition(invoice):
    """CAPTURED/EXCEPTION -> EXCEPTION with a NO_CONTRACT exception."""
    invoice["audit_status"] = "EXCEPTION"
    touch(invoice)
    open_exception(invoice, "NO_CONTRACT", invoice["billed_total_minor"])


# ---------------------------------------------------------------------------
# Duplicate detection (capture) and exception routing (finalize)
# ---------------------------------------------------------------------------

def detect_fuzzy_duplicate(invoice):
    for other in STORE.invoices.values():
        if other["id"] == invoice["id"]:
            continue
        if other["audit_status"] == "VOIDED":
            continue
        if other["client_id"] != invoice["client_id"]:
            continue
        if other["carrier_id"] != invoice["carrier_id"]:
            continue
        amount_ok = (
            abs(other["billed_total_minor"] - invoice["billed_total_minor"]) * 10000
            <= FUZZY_AMOUNT_TOLERANCE_BP * max(invoice["billed_total_minor"], 1)
        )
        days = abs((parse_date(invoice["invoice_date"])
                    - parse_date(other["invoice_date"])).days)
        if amount_ok and days <= FUZZY_DATE_WINDOW_DAYS:
            return "FUZZY"
    return "NONE"


def finalize_invoice(invoice, client):
    """exception_routing: RATED -> CLEARED or RATED -> EXCEPTION.

    On CLEARED: approved amount, home_total (invoice-date FX), due_date.
    """
    resolved = [e for e in invoice_exceptions(invoice["id"])
                if e["status"] in ("RESOLVED_ACCEPTED", "RESOLVED_CONCEDED")]
    carrier = STORE.carriers.get(invoice["carrier_id"])

    if resolved:
        approved = invoice["approved_amount_minor"]
    else:
        if invoice["duplicate_flag"] == "FUZZY":
            invoice["audit_status"] = "EXCEPTION"
            touch(invoice)
            open_exception(invoice, "DUPLICATE_FUZZY", invoice["billed_total_minor"])
            return
        invalid_lines = [l for l in invoice_lines(invoice["id"])
                         if l.get("_invalid_accessorial")]
        if invalid_lines:
            disputed = sum(l["billed_amount_minor"] for l in invalid_lines)
            invoice["audit_status"] = "EXCEPTION"
            touch(invoice)
            open_exception(invoice, "INVALID_ACCESSORIAL", disputed)
            return
        if (abs(invoice["variance_minor"]) > client["audit_tolerance_minor"]
                or invoice["variance_pct_bp"] > client["audit_tolerance_pct_bp"]):
            invoice["audit_status"] = "EXCEPTION"
            touch(invoice)
            open_exception(invoice, "RATE_MISMATCH",
                           max(invoice["variance_minor"], 0))
            return
        approved = invoice["billed_total_minor"] - max(invoice["variance_minor"], 0)

    # CLEARED path: stamp the money facts. Compute before mutating so an FX
    # failure (ERR_FX_RATE_MISSING) leaves the invoice untouched in RATED.
    home_total = compute_home_total(invoice, client, approved)
    terms = carrier["payment_terms_days"] if carrier else 0
    invoice["audit_status"] = "CLEARED"
    invoice["approved_amount_minor"] = approved
    invoice["home_total_minor"] = home_total
    invoice["due_date"] = db.add_days(invoice["invoice_date"], terms)
    touch(invoice)


def apply_resolution(exception, outcome, credit_minor=None):
    """Pin the invoice payable amount per the resolution outcome; also sets the
    terminal exception status. Computes before mutating so an FX failure
    leaves prior state intact."""
    invoice = STORE.invoices[exception["invoice_id"]]
    client = STORE.clients[invoice["client_id"]]
    if outcome == "ACCEPT":
        credit = exception["disputed_amount_minor"]
        approved = invoice["rated_total_minor"]
    else:  # CONCEDE
        credit = credit_minor
        approved = invoice["billed_amount_minor"] - credit_minor
    home_total = compute_home_total(invoice, client, approved)
    exception["resolution_credit_minor"] = credit
    exception["status"] = ("RESOLVED_ACCEPTED" if outcome == "ACCEPT"
                           else "RESOLVED_CONCEDED")
    invoice["approved_amount_minor"] = approved
    invoice["home_total_minor"] = home_total
    touch(invoice)
    touch(exception)


# ---------------------------------------------------------------------------
# Cost allocation split
# ---------------------------------------------------------------------------

def replace_allocations(line, allocation_inputs):
    invoice = STORE.invoices[line["invoice_id"]]
    if invoice["rated_total_minor"] > 0:
        line_amount = line["rated_amount_minor"]
    else:
        line_amount = line["billed_amount_minor"]

    # Replace-set semantics: delete prior rows, recompute from scratch.
    for aid in [a["id"] for a in STORE.allocations.values()
                if a["invoice_line_id"] == line["id"]]:
        del STORE.allocations[aid]

    rows = []
    for entry in allocation_inputs:
        pct = entry["percentage_bp"]
        allocated = round_half_up_div(line_amount * pct, 10000)
        row = create_entity(STORE.allocations, {
            "invoice_line_id": line["id"],
            "gl_account_id": entry["gl_account_id"],
            "percentage_bp": pct,
            "allocated_minor": allocated,
        })
        rows.append(row)

    delta = line_amount - sum(r["allocated_minor"] for r in rows)
    if rows and delta != 0:
        def remainder_key(row):
            gl = STORE.gl_accounts.get(row["gl_account_id"])
            code = gl["code"] if gl else ""
            return (-row["percentage_bp"], code, row["created_at"], row["_seq"])
        target = sorted(rows, key=remainder_key)[0]
        target["allocated_minor"] += delta
        touch(target)
    touch(line)
    return rows


# ---------------------------------------------------------------------------
# Payment run composition, discount tiers, and cascades
# ---------------------------------------------------------------------------

def invoice_in_open_run(invoice_id):
    """True when the invoice is already an item of a DRAFT/LOCKED/RELEASED run."""
    for item in STORE.run_items.values():
        if item["invoice_id"] != invoice_id:
            continue
        run = STORE.runs.get(item["payment_run_id"])
        if run and run["status"] in ("DRAFT", "LOCKED", "RELEASED"):
            return True
    return False


def add_run_item(run, invoice, touch_run=True):
    scheduled = convert_amount(
        invoice["approved_amount_minor"], run["client_id"],
        invoice["currency"], run["currency"], run["run_date"],
        raise_on_missing=True,
    )
    item = create_entity(STORE.run_items, {
        "payment_run_id": run["id"],
        "invoice_id": invoice["id"],
        "scheduled_amount_minor": scheduled,
        "discount_minor": 0,
        "status": "SCHEDULED",
    })
    if touch_run:
        touch(run)
    return item


def auto_fill_run(run):
    """run_item_selection: eligibility filter, then due_date ASC ranking."""
    today_d = today()
    run_date_d = parse_date(run["run_date"])
    window_end = run_date_d + timedelta(days=DUE_WINDOW_DAYS)
    eligible = []
    for inv in STORE.invoices.values():
        if inv["client_id"] != run["client_id"]:
            continue
        if inv["audit_status"] != "CLEARED" or inv["payment_status"] != "UNPAID":
            continue
        carrier = STORE.carriers.get(inv["carrier_id"])
        if carrier is None or carrier["status"] != "ACTIVE":
            continue
        if run.get("country_scope") and carrier["country"] != run["country_scope"]:
            continue
        due = parse_date(inv["due_date"]) if inv.get("due_date") else None
        if due is None or due > window_end:
            continue
        if not has_fx_path(run["client_id"], inv["currency"], run["currency"],
                           run["run_date"]):
            continue
        if invoice_in_open_run(inv["id"]):
            continue
        eligible.append(inv)
    eligible.sort(key=lambda i: (i["due_date"], i["created_at"], i["_seq"]))
    for inv in eligible:
        add_run_item(run, inv, touch_run=False)
    # One composition step: the run version increments by exactly one.
    touch(run)
    return eligible


def lock_run(run, acting_user_id):
    items = run_items_of(run["id"])
    gross = sum(i["scheduled_amount_minor"] for i in items)
    if gross >= TIER2_THRESHOLD_MINOR:
        tier_bp = TIER2_BP
    elif gross >= TIER1_THRESHOLD_MINOR:
        tier_bp = TIER1_BP
    else:
        tier_bp = 0
    discount_total = 0
    for item in items:
        discount = round_half_up_div(item["scheduled_amount_minor"] * tier_bp, 10000)
        item["discount_minor"] = discount
        touch(item)
        discount_total += discount
    run["gross_total_minor"] = gross
    run["discount_total_minor"] = discount_total
    run["total_minor"] = gross - discount_total
    run["locked_by_user_id"] = acting_user_id
    run["status"] = "LOCKED"
    touch(run)


def release_run(run):
    for item in run_items_of(run["id"]):
        item["status"] = "RELEASED"
        touch(item)
        invoice = STORE.invoices[item["invoice_id"]]
        invoice["scheduled_minor"] += item["scheduled_amount_minor"]
        if invoice["payment_status"] == "UNPAID":
            invoice["payment_status"] = "SCHEDULED"
        touch(invoice)
    # One remittance advice per distinct carrier among the items.
    by_carrier = {}
    for item in run_items_of(run["id"]):
        invoice = STORE.invoices[item["invoice_id"]]
        entry = by_carrier.setdefault(invoice["carrier_id"], {"total": 0, "count": 0})
        entry["total"] += item["scheduled_amount_minor"] - item["discount_minor"]
        entry["count"] += 1
    for carrier_id, agg in by_carrier.items():
        create_entity(STORE.advices, {
            "payment_run_id": run["id"],
            "carrier_id": carrier_id,
            "total_minor": agg["total"],
            "item_count": agg["count"],
            "status": "GENERATED",
        })
    run["status"] = "RELEASED"
    touch(run)


def settle_run(run):
    for item in run_items_of(run["id"]):
        item["status"] = "PAID"
        touch(item)
        invoice = STORE.invoices[item["invoice_id"]]
        paid = item["scheduled_amount_minor"] - item["discount_minor"]
        invoice["paid_minor"] += paid
        invoice["payment_status"] = "PAID" if item["discount_minor"] == 0 else "SHORT_PAID"
        touch(invoice)
        shipment = STORE.shipments.get(invoice.get("shipment_id")) if invoice.get("shipment_id") else None
        if shipment is not None and shipment["status"] == "INVOICED":
            shipment["status"] = "CLOSED"
            touch(shipment)
    for advice in [a for a in STORE.advices.values()
                   if a["payment_run_id"] == run["id"]]:
        if advice["status"] == "GENERATED":
            advice["status"] = "SENT"
            touch(advice)
    run["status"] = "SETTLED"
    touch(run)


def delete_run_items(run):
    for iid in [i["id"] for i in STORE.run_items.values()
                if i["payment_run_id"] == run["id"]]:
        del STORE.run_items[iid]


# ---------------------------------------------------------------------------
# Contract activation cascade
# ---------------------------------------------------------------------------

def windows_overlap(a_from, a_to, b_from, b_to):
    return a_from < b_to and b_from < a_to


def lanes_intersect(lanes_a, lanes_b):
    keys_a = {(l.get("origin_country"), l.get("dest_country"), l.get("mode"))
              for l in (lanes_a or [])}
    keys_b = {(l.get("origin_country"), l.get("dest_country"), l.get("mode"))
              for l in (lanes_b or [])}
    return bool(keys_a & keys_b)


def check_contract_overlap(contract):
    """ERR_CONTRACT_WINDOW_OVERLAP when an intersecting ACTIVE contract exists
    on the same carrier and is not the declared supersedes target."""
    for other in STORE.contracts.values():
        if other["id"] == contract["id"]:
            continue
        if other["carrier_id"] != contract["carrier_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if contract.get("supersedes_contract_id") == other["id"]:
            continue
        if not windows_overlap(contract["effective_from"], contract["effective_to"],
                               other["effective_from"], other["effective_to"]):
            continue
        if lanes_intersect(contract.get("lanes"), other.get("lanes")):
            return other
    return None


def check_weight_breaks(contract):
    for lane in (contract.get("lanes") or []):
        breaks = lane.get("weight_breaks") or []
        mins = [wb.get("min_kg") for wb in breaks]
        for prev, cur in zip(mins, mins[1:]):
            if not (prev < cur):
                return False
    return True


def supersede_cascade(new_contract, client):
    """Hops 1-3: supersede the named contract, re-rate affected invoices,
    auto-resolve RATE_MISMATCH exceptions now within tolerance."""
    target_id = new_contract.get("supersedes_contract_id")
    if not target_id:
        return
    target = STORE.contracts.get(target_id)
    if target is None or target["status"] != "ACTIVE":
        return
    target["status"] = "SUPERSEDED"
    touch(target)

    rerated_invoices = []
    for invoice in STORE.invoices.values():
        if invoice.get("rated_contract_id") != target_id:
            continue
        if invoice["audit_status"] not in ("RATED", "EXCEPTION"):
            continue
        if rate_invoice(invoice, forced_contract=new_contract):
            touch(invoice)
            rerated_invoices.append(invoice)

    for invoice in rerated_invoices:
        within = (
            abs(invoice["variance_minor"]) <= client["audit_tolerance_minor"]
            and invoice["variance_pct_bp"] <= client["audit_tolerance_pct_bp"]
        )
        if not within:
            continue
        for exc in invoice_exceptions(invoice["id"]):
            if exc["status"] in ("OPEN", "CARRIER_NOTIFIED", "CARRIER_RESPONDED") \
                    and exc["code"] == "RATE_MISMATCH":
                exc["status"] = "RESOLVED_ACCEPTED"
                exc["resolution_credit_minor"] = exc["disputed_amount_minor"]
                touch(exc)
                invoice["approved_amount_minor"] = invoice["rated_total_minor"]
                try:
                    invoice["home_total_minor"] = compute_home_total(
                        invoice, client, invoice["approved_amount_minor"])
                except ApiError:
                    pass
                touch(invoice)


# ---------------------------------------------------------------------------
# Savings rollup
# ---------------------------------------------------------------------------

def savings_rollup(client):
    cid = client["id"]
    home = client["home_currency"]
    avoided = 0
    for inv in STORE.invoices.values():
        if inv["client_id"] != cid:
            continue
        if inv["payment_status"] not in ("PAID", "SHORT_PAID"):
            continue
        over = max(inv["billed_total_minor"] - inv["approved_amount_minor"], 0)
        avoided += convert_amount(over, cid, inv["currency"], home,
                                  inv["invoice_date"], raise_on_missing=False)
    recovered = 0
    for claim in STORE.claims.values():
        if claim["client_id"] != cid or claim["status"] != "COLLECTED":
            continue
        inv = STORE.invoices.get(claim["invoice_id"])
        inv_ccy = inv["currency"] if inv else home
        inv_date = inv["invoice_date"] if inv else today_str()
        recovered += convert_amount(claim["recovered_minor"], cid, inv_ccy, home,
                                    inv_date, raise_on_missing=False)
    outstanding = 0
    for inv in STORE.invoices.values():
        if inv["client_id"] != cid:
            continue
        if inv["audit_status"] != "CLEARED":
            continue
        if inv["payment_status"] not in ("UNPAID", "SCHEDULED"):
            continue
        due_amount = inv["approved_amount_minor"] - inv["paid_minor"]
        outstanding += convert_amount(due_amount, cid, inv["currency"], home,
                                      inv["invoice_date"], raise_on_missing=False)
    return {
        "savings_realized_minor": avoided + recovered,
        "avoided_overcharge_minor": avoided,
        "recovered_minor": recovered,
        "outstanding_liability_minor": outstanding,
        "currency": home,
    }


def compute_export(invoice_rows):
    ordered = sorted(invoice_rows,
                     key=lambda i: (i["created_at"], i["invoice_number"], i["_seq"]))
    joined = ",".join(i["invoice_number"] for i in ordered)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return len(ordered), "sha256:" + digest
