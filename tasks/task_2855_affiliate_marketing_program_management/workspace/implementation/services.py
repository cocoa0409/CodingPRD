"""Shared business services: derived-field recomputation, the suspension and
termination cascades, the validation sweep, the tax-expiry refresh and the
payout line / batch recomputation (PRD 2.11, 3.6-3.9).
"""

from datetime import timedelta

import calc
from common import (db, fail, new_row, now_dt, now_iso, ordered, parse_instant,
                    touch)


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def links_of(affiliate_id):
    return [r for r in ordered(db.links) if r["affiliate_id"] == affiliate_id]


def cases_of(affiliate_id):
    return [r for r in ordered(db.cases) if r["affiliate_id"] == affiliate_id]


def tax_docs_of(affiliate_id):
    return [r for r in ordered(db.tax_documents)
            if r["affiliate_id"] == affiliate_id]


def lines_of_affiliate(affiliate_id):
    return [r for r in ordered(db.lines) if r["affiliate_id"] == affiliate_id]


def lines_of_batch(batch_id):
    return [r for r in ordered(db.lines) if r["payout_batch_id"] == batch_id]


def entries_of_batch(batch_id):
    return [r for r in ordered(db.ledger) if r["payout_batch_id"] == batch_id]


def children_of(affiliate_id):
    return [r for r in ordered(db.affiliates)
            if r["parent_affiliate_id"] == affiliate_id]


def latest_tax_doc(affiliate_id):
    docs = tax_docs_of(affiliate_id)
    if not docs:
        return None
    return docs[-1]


# ---------------------------------------------------------------------------
# Derived affiliate fields
# ---------------------------------------------------------------------------

def recompute_incrementality(affiliate):
    score, tier = calc.incrementality(
        affiliate["partner_type"],
        affiliate["attributed_conversion_count"],
        affiliate["new_customer_attributed_count"],
        affiliate["coupon_assisted_conversion_count"],
    )
    affiliate["incrementality_score_bps"] = score
    affiliate["incrementality_tier"] = tier


def recompute_fraud(affiliate):
    """Recompute both fraud scores and the open-case counter, then apply the
    automatic fraud suspension when the point-in-time score reaches the
    threshold and the partner is still ACTIVE."""
    cases = cases_of(affiliate["id"])
    point = calc.point_in_time_fraud_score(cases)
    affiliate["fraud_risk_score"] = point
    affiliate["fraud_risk_score_trailing"] = calc.trailing_fraud_score(
        cases, now_dt(), parse_instant)
    affiliate["open_violation_case_count"] = len(
        [c for c in cases if c["state"] in calc.OPEN_CASE_STATES])
    touch(affiliate)
    if (affiliate["status"] == "ACTIVE"
            and point >= calc.FRAUD_SUSPENSION_THRESHOLD):
        suspend_cascade(affiliate, "FRAUD_SCORE_BREACH")


# ---------------------------------------------------------------------------
# Cascades (PRD 2.11)
# ---------------------------------------------------------------------------

def disable_link(link, reason):
    link["status"] = "DISABLED"
    link["disabled_reason"] = reason
    touch(link)


def suspend_cascade(affiliate, cause):
    """Ordered hops: the partner itself, then its ACTIVE sub-affiliates, then
    for each newly suspended partner its ACTIVE links and INCLUDED payout
    lines on DRAFT/VALIDATED batches, then the touched batch payable totals.
    Parent propagation never re-evaluates a child's own fraud score."""
    newly = []
    affiliate["status"] = "SUSPENDED"
    affiliate["suspension_cause"] = cause
    touch(affiliate)
    newly.append(affiliate)

    for child in children_of(affiliate["id"]):
        if child["status"] == "ACTIVE":
            child["status"] = "SUSPENDED"
            child["suspension_cause"] = "PARENT_SUSPENSION"
            touch(child)
            newly.append(child)

    touched_batches = []
    for partner in newly:
        for link in links_of(partner["id"]):
            if link["status"] == "ACTIVE":
                disable_link(link, "AFFILIATE_SUSPENDED")
        for line in lines_of_affiliate(partner["id"]):
            batch = db.batches.get(line["payout_batch_id"])
            if (line["state"] == "INCLUDED" and batch is not None
                    and batch["state"] in ("DRAFT", "VALIDATED")):
                line["state"] = "HELD_FRAUD"
                line["hold_reason"] = "AFFILIATE_SUSPENDED"
                touch(line)
                if batch["id"] not in [b["id"] for b in touched_batches]:
                    touched_batches.append(batch)

    for batch in touched_batches:
        recompute_batch_totals(batch, payable_only=True)


def terminate_affiliate(affiliate, disable_reason):
    affiliate["status"] = "TERMINATED"
    touch(affiliate)
    for link in links_of(affiliate["id"]):
        if link["status"] == "ACTIVE":
            disable_link(link, disable_reason)


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------

def validation_sweep():
    """Promotes PENDING_VALIDATION orders whose 30-day hold has elapsed.
    Runs at the start of payout-batch generation.  Inclusive boundary."""
    now = now_dt()
    for conv in ordered(db.conversions):
        if (conv["validation_status"] == "PENDING_VALIDATION"
                and conv["attribution_status"] in ("AFFILIATE_ATTRIBUTED",
                                                   "CREDIT_REDUCED")):
            placed = parse_instant(conv["placed_at"])
            if placed is not None and placed + timedelta(
                    days=calc.VALIDATION_HOLD_DAYS) <= now:
                conv["validation_status"] = "VALIDATED"
                touch(conv)


def tax_expiry_plan():
    now = now_dt()
    plan = []
    for doc in ordered(db.tax_documents):
        if doc["status"] == "VALID":
            expires = parse_instant(doc["expires_on"])
            if expires is not None and expires <= now:
                plan.append(doc)
    return plan


def apply_tax_expiry(plan):
    for doc in plan:
        doc["status"] = "EXPIRED"
        touch(doc)
        mirror_tax_status(doc)


def mirror_tax_status(doc):
    """The partner mirror only follows the partner's most recent document."""
    latest = latest_tax_doc(doc["affiliate_id"])
    if latest is not None and latest["id"] == doc["id"]:
        affiliate = db.affiliates.get(doc["affiliate_id"])
        if affiliate is not None:
            affiliate["tax_document_status"] = doc["status"]
            touch(affiliate)


def tax_refresh():
    apply_tax_expiry(tax_expiry_plan())


# ---------------------------------------------------------------------------
# Payout line / batch recomputation
# ---------------------------------------------------------------------------

def withholding_bps_for(affiliate_id, expired_doc_ids=None):
    latest = latest_tax_doc(affiliate_id)
    if latest is not None and latest["status"] == "VALID":
        if not expired_doc_ids or latest["id"] not in expired_doc_ids:
            return latest["treaty_withholding_bps"]
    return calc.DEFAULT_BACKUP_WITHHOLDING_BPS


def compute_line_values(batch, affiliate_id, expired_doc_ids=None):
    network = db.networks[batch["network_id"]]
    entries = [e for e in entries_of_batch(batch["id"])
               if e["affiliate_id"] == affiliate_id]
    gross = sum(e["amount_cents"] for e in entries
                if e["entry_type"] == "ACCRUAL")
    clawback = abs(sum(e["amount_cents"] for e in entries
                       if e["entry_type"] in ("REVERSAL", "CLAWBACK",
                                              "ADJUSTMENT")))
    net_before_fees = gross - clawback
    conversion_ids = set()
    for e in entries:
        if e["entry_type"] == "ACCRUAL" and e["conversion_id"]:
            conversion_ids.add(e["conversion_id"])
    conversion_count = len(conversion_ids)
    fee = calc.network_fee_cents(net_before_fees, network["fee_bps"],
                                network["flat_fee_cents"], conversion_count)
    base = net_before_fees - fee
    bps = withholding_bps_for(affiliate_id, expired_doc_ids)
    withheld = calc.withholding_cents(base, bps)
    return {
        "gross_cents": gross,
        "clawback_cents": clawback,
        "net_before_fees_cents": net_before_fees,
        "conversion_count": conversion_count,
        "network_fee_cents": fee,
        "withholding_bps": bps,
        "withholding_cents": withheld,
        "net_cents": base - withheld,
    }


MONEY_KEYS = ("gross_cents", "clawback_cents", "net_before_fees_cents",
              "conversion_count", "network_fee_cents", "withholding_bps",
              "withholding_cents", "net_cents")


def apply_line_values(line, values):
    changed = False
    for key in MONEY_KEYS:
        if line.get(key) != values[key]:
            line[key] = values[key]
            changed = True
    return changed


def recompute_batch_totals(batch, payable_only=False, force_touch=True):
    lines = lines_of_batch(batch["id"])
    gross = clawback = fee = withheld = net = 0
    for line in lines:
        if line["state"] != "VOIDED":
            gross += line["gross_cents"]
            clawback += line["clawback_cents"]
        if line["state"] in ("INCLUDED", "PAID"):
            fee += line["network_fee_cents"]
            withheld += line["withholding_cents"]
            net += line["net_cents"]
    if not payable_only:
        batch["gross_commission_cents"] = gross
        batch["clawback_cents"] = clawback
    batch["network_fee_cents"] = fee
    batch["withholding_cents"] = withheld
    batch["net_payable_cents"] = net
    if force_touch:
        touch(batch)


def unstamp_entries(batch_id, affiliate_id=None):
    for entry in entries_of_batch(batch_id):
        if affiliate_id is None or entry["affiliate_id"] == affiliate_id:
            entry["payout_batch_id"] = None


# ---------------------------------------------------------------------------
# Existence lookups (rules 3-12 of the global precedence order)
# ---------------------------------------------------------------------------

def _find(collection, key, error_id):
    if not isinstance(key, str):
        fail(error_id)
    row = collection.get(key)
    if row is None:
        fail(error_id)
    return row


def find_affiliate(key):
    return _find(db.affiliates, key, "ERR_AFFILIATE_NOT_FOUND")


def find_application(key):
    return _find(db.applications, key, "ERR_APPLICATION_NOT_FOUND")


def find_policy(key):
    return _find(db.policies, key, "ERR_POLICY_NOT_FOUND")


def find_link(key):
    return _find(db.links, key, "ERR_TRACKING_LINK_NOT_FOUND")


def find_conversion(key):
    return _find(db.conversions, key, "ERR_CONVERSION_NOT_FOUND")


def find_case(key):
    return _find(db.cases, key, "ERR_CASE_NOT_FOUND")


def find_batch(key):
    return _find(db.batches, key, "ERR_BATCH_NOT_FOUND")


def find_line(key):
    return _find(db.lines, key, "ERR_LINE_NOT_FOUND")


def find_network(key):
    return _find(db.networks, key, "ERR_NETWORK_NOT_FOUND")


def find_tax_document(key):
    return _find(db.tax_documents, key, "ERR_TAX_DOCUMENT_NOT_FOUND")


def find_scan(key):
    return _find(db.scans, key, "ERR_CASE_NOT_FOUND")


def applications_of(affiliate_id):
    return [r for r in ordered(db.applications)
            if r["affiliate_id"] == affiliate_id]


def clicks_of_link(link_id):
    return [r for r in ordered(db.clicks) if r["tracking_link_id"] == link_id]


def decisions_of_conversion(conversion_id):
    return [r for r in ordered(db.decisions)
            if r["conversion_id"] == conversion_id]


def ledger_of_conversion(conversion_id):
    return [r for r in ordered(db.ledger)
            if r["conversion_id"] == conversion_id]


def scans_of(affiliate_id, engine=None):
    return [r for r in ordered(db.scans)
            if r["affiliate_id"] == affiliate_id
            and (engine is None or r["engine"] == engine)]


# ---------------------------------------------------------------------------
# Attribution candidate set (PRD 3.5 step one / step two)
# ---------------------------------------------------------------------------

def click_match_mode(click, link, conv):
    """DEVICE_EXACT, HOUSEHOLD_GRAPH or None."""
    if click.get("device_id") is not None and click["device_id"] == conv.get(
            "device_id"):
        return "DEVICE_EXACT"
    if (link.get("device_graph_enabled")
            and click.get("household_id") is not None
            and conv.get("household_id") is not None
            and click["household_id"] == conv["household_id"]):
        return "HOUSEHOLD_GRAPH"
    return None


def in_cookie_window(click_occurred, placed, cookie_window_days):
    if click_occurred is None or placed is None:
        return False
    if click_occurred < placed - timedelta(days=cookie_window_days):
        return False
    return click_occurred < placed


def eligible_clicks(conv):
    """Every click that qualifies as an attribution candidate for this order,
    as a list of (click, link, device_match_mode) triples."""
    placed = parse_instant(conv["placed_at"])
    out = []
    for click in ordered(db.clicks):
        if click["click_type"] != "ORGANIC_CLICK":
            continue
        link = db.links.get(click["tracking_link_id"])
        if link is None or link["status"] != "ACTIVE":
            continue
        if not in_cookie_window(parse_instant(click["occurred_at"]), placed,
                                link["cookie_window_days"]):
            continue
        mode = click_match_mode(click, link, conv)
        if mode is None:
            continue
        out.append((click, link, mode))
    return out


def rank_candidates(candidates):
    """occurred_at DESC, then created_at DESC.  The id is never a tie-break."""
    return sorted(
        candidates,
        key=lambda e: (parse_instant(e[0]["occurred_at"]),
                       parse_instant(e[0]["created_at"])),
        reverse=True)


# ---------------------------------------------------------------------------
# Ledger appends and single-line recomputation
# ---------------------------------------------------------------------------

def append_entry(affiliate, entry_type, amount_cents, conversion_id=None,
                 payout_batch_id=None, memo="", affect_accrued=True):
    """Append an immutable ledger entry.  Every append except a SETTLEMENT
    moves the partner's unreserved pool by the signed amount."""
    row = new_row(
        mutable=False, affiliate_id=affiliate["id"],
        conversion_id=conversion_id, payout_batch_id=payout_batch_id,
        entry_type=entry_type, amount_cents=amount_cents, memo=memo,
    )
    db.ledger[row["id"]] = row
    if affect_accrued:
        affiliate["accrued_balance_cents"] += amount_cents
    return row


def accrual_entry_of(conversion_id):
    for entry in ledger_of_conversion(conversion_id):
        if entry["entry_type"] == "ACCRUAL":
            return entry
    return None


def line_for(batch_id, affiliate_id):
    for line in lines_of_batch(batch_id):
        if line["affiliate_id"] == affiliate_id:
            return line
    return None


def recompute_line(line, batch, apply_minimum=True):
    """Recompute one line from its stamped entries, apply the minimum-payout
    hold when it now falls short, then recompute the batch totals."""
    values = compute_line_values(batch, line["affiliate_id"])
    changed = apply_line_values(line, values)
    if (apply_minimum and line["state"] == "INCLUDED"
            and not line.get("minimum_waived")
            and line["net_cents"] < calc.MIN_PAYOUT_CENTS):
        line["state"] = "HELD_BELOW_MINIMUM"
        line["hold_reason"] = "BELOW_MINIMUM_PAYOUT"
        changed = True
    if changed:
        touch(line)
    recompute_batch_totals(batch)


def prospective_tax_status(affiliate, expired_doc_ids):
    """The partner's mirrored tax status as it will stand once the pending
    expiry plan has been applied."""
    if affiliate is None:
        return "NONE"
    latest = latest_tax_doc(affiliate["id"])
    if latest is not None and latest["id"] in (expired_doc_ids or ()):
        return "EXPIRED"
    return affiliate["tax_document_status"]
