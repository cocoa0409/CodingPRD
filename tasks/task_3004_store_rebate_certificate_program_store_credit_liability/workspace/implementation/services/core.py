"""Core business logic: award calculation, derived balances/liability,
ledger posting, program-item matching, fraud screening, and the
guest-service reversal cascade.

Every rule implemented here traces to SCAFFOLD.yaml `calculations` /
`state_machines` and PRD.md section 3 prose.  PRD wins on any disagreement.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError
from response import iso_timestamp
from services import temporal

# Rebate-certificate redeemable lifecycle states (store liability composition,
# PRD 3.7 gross variant).
LIABILITY_CERT_STATUSES = {"ACTIVE", "PARTIALLY_REDEEMED", "EXPIRED"}

# States that contribute to an account's spendable balance (PRD 3.3).
BALANCE_CERT_STATUSES = {"ACTIVE", "PARTIALLY_REDEEMED"}

TIER1_THRESHOLD_CENTS = 500000
TIER2_THRESHOLD_CENTS = 2000000
PRO_RATE = Decimal("0.02")
PRO_PLUS_RATE = Decimal("0.05")


def dec(value):
    """Exact Decimal for a caller-supplied numeric (never via float)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to whole cents, round-half-up (PRD 2.5)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def store_certificates(store_id):
    return [c for c in db.ordered(db.certificates) if c["store_id"] == store_id]


def account_certificates(account_id):
    return [c for c in db.ordered(db.certificates) if c["account_id"] == account_id]


def store_submissions(store_id):
    return [s for s in db.ordered(db.submissions) if s["store_id"] == store_id]


def account_submissions(account_id):
    return [s for s in db.ordered(db.submissions) if s["account_id"] == account_id]


def receipt_submissions(receipt_id):
    return [s for s in db.ordered(db.submissions) if s["receipt_id"] == receipt_id]


def submission_lines_of(submission_id):
    return [sl for sl in db.ordered(db.submission_lines)
            if sl["submission_id"] == submission_id]


def receipt_lines_of(receipt_id):
    lines = [rl for rl in db.ordered(db.receipt_lines)
             if rl["receipt_id"] == receipt_id]
    lines.sort(key=lambda l: l["line_number"])
    return lines


def account_receipts(account_id):
    return [r for r in db.ordered(db.receipts) if r["account_id"] == account_id]


def account_flags(account_id):
    return [f for f in db.ordered(db.flags) if f["account_id"] == account_id]


def program_items_of(program_id):
    return [pi for pi in db.ordered(db.program_items)
            if pi["program_id"] == program_id]


# ---------------------------------------------------------------------------
# Derived figures: account balances (PRD 3.3) and store liability (PRD 3.7)
# ---------------------------------------------------------------------------
def _settled_submission_ids():
    """Submissions already settled by an issued certificate.  An APPROVED
    submission with a certificate contributes to the certificate-backed
    liability/balance legs, never again to the pending-award leg — the
    pinned evaluation order of credit_account_balance (pending decremented
    before balance incremented) means the two legs never double-count."""
    return {c["submission_id"] for c in db.certificates.values()
            if c.get("submission_id")}


def _pending_submissions(submissions):
    settled = _settled_submission_ids()
    return [s for s in submissions
            if s["status"] == "APPROVED" and s["id"] not in settled]


def recompute_account(account):
    """credit_account_balance calculation.  credit_balance_cents sums
    remaining balances of ACTIVE/PARTIALLY_REDEEMED certificates;
    pending_award_cents sums award_cents of APPROVED submissions whose
    certificate has not yet been issued."""
    balance = sum(c["remaining_balance_cents"]
                  for c in account_certificates(account["id"])
                  if c["status"] in BALANCE_CERT_STATUSES)
    pending = sum(s["award_cents"] or 0
                  for s in _pending_submissions(
                      account_submissions(account["id"])))
    account["credit_balance_cents"] = balance
    account["pending_award_cents"] = pending
    db.touch(account)


def recompute_store(store):
    """store_credit_liability calculation, both variants maintained on every
    mutation.  Gross = redeemable-state certificate remainder + awards of
    APPROVED submissions not yet settled by a certificate; net =
    round_half_up(gross * (1 - breakage_rate))."""
    gross = sum(c["remaining_balance_cents"]
                for c in store_certificates(store["id"])
                if c["status"] in LIABILITY_CERT_STATUSES)
    gross += sum(s["award_cents"] or 0
                 for s in _pending_submissions(store_submissions(store["id"])))
    store["outstanding_liability_cents"] = gross
    rate = dec(store["expected_breakage_rate"])
    store["net_liability_cents"] = round_half_up(
        Decimal(gross) * (Decimal(1) - rate))
    db.touch(store)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def post_ledger(store, account_id, certificate_id, entry_type, amount_cents,
                note):
    entry = db.base_record(versioned=False)
    entry.update({
        "store_id": store["id"],
        "account_id": account_id,
        "certificate_id": certificate_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "liability_epoch": store["liability_epoch"],
        "created_note": note,
    })
    db.ledger_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Program-item matching (rebate_award step 1)
# ---------------------------------------------------------------------------
def match_program_item(store_id, sku, purchase_at):
    """The store-scoped ProgramItem whose sku matches and whose program's
    advertised week contains purchase_at.  Greatest rebate_pct wins; ties
    break by ProgramItem created_at ASC.  Programs of other stores are
    never visible.  None -> None."""
    if isinstance(purchase_at, dict):
        purchase_dt = temporal.purchase_dt(purchase_at)
    else:
        purchase_dt = temporal.parse_timestamp_iso(purchase_at)
    candidates = []
    for item in db.ordered(db.program_items):
        if item["store_id"] != store_id or item["sku"] != sku:
            continue
        program = db.programs.get(item["program_id"])
        if program is None:
            continue
        if temporal.week_contains(program, purchase_dt):
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda i: (-dec(i["rebate_pct"]), db.sort_key(i)))
    return candidates[0]


# ---------------------------------------------------------------------------
# Rebate award calculation (calculation rebate_award; PRD 3.5)
# ---------------------------------------------------------------------------
def compute_award(store, receipt, variant):
    """Per-line award, line_number ASC, per-line round-half-up before
    summation (pinned rounding order).  Returns (total_cents, line_results).

    variant == "provisional":  returns invisible (returned_quantity = 0),
                               min_quantity check skipped.
    variant == "adjudicated":  net_qty subtracts current returned_quantity,
                               min_quantity enforced.
    """
    provisional = (variant == "provisional")
    total = 0
    results = []
    for line in receipt_lines_of(receipt["id"]):
        item = match_program_item(store["id"], line["sku"], receipt)
        reason = None
        program_item_id = None
        base = 0
        awarded = 0

        if item is None:
            reason = "NO_PROGRAM_ITEM"
        else:
            program_item_id = item["id"]
            line_total = line["quantity"] * line["unit_price_cents"]
            if line["category"] in item["excluded_categories"]:
                reason = "EXCLUDED_CATEGORY"
            else:
                net_qty = (line["quantity"] if provisional
                           else line["quantity"] - line["returned_quantity"])
                if not provisional and net_qty < item["min_quantity"]:
                    reason = "BELOW_MIN_QUANTITY"
                elif line["certificate_tendered_cents"] >= line_total:
                    reason = "FULLY_CERTIFICATE_TENDERED"
                else:
                    gross_base = net_qty * line["unit_price_cents"]
                    base = max(gross_base - line["certificate_tendered_cents"], 0)
                    raw = Decimal(base) * dec(item["rebate_pct"])
                    cap = item["per_receipt_cap_cents"]
                    if cap is not None and raw > Decimal(cap):
                        raw = Decimal(cap)
                    awarded = round_half_up(raw)

        results.append({
            "receipt_line_id": line["id"],
            "program_item_id": program_item_id,
            "eligible_base_cents": base,
            "awarded_cents": awarded,
            "exclusion_reason": reason,
        })
        total += awarded
    return total, results


def write_submission_lines(submission, line_results):
    """Replace the submission's SubmissionLine rows with fresh computed ones
    (used on create and on each resubmit recomputation)."""
    for sl in [sl for sl in db.submission_lines.values()
               if sl["submission_id"] == submission["id"]]:
        del db.submission_lines[sl["id"]]
    for res in line_results:
        sl = db.base_record(versioned=False)
        sl.update({
            "submission_id": submission["id"],
            "store_id": submission["store_id"],
            "receipt_line_id": res["receipt_line_id"],
            "program_item_id": res["program_item_id"],
            "eligible_base_cents": res["eligible_base_cents"],
            "awarded_cents": res["awarded_cents"],
            "exclusion_reason": res["exclusion_reason"],
        })
        db.submission_lines[sl["id"]] = sl


# ---------------------------------------------------------------------------
# Fraud screening (calculation fraud_screening; PRD 3.4 / 3.9)
# ---------------------------------------------------------------------------
def _new_flag(store_id, account_id, flag_type, receipt_ids, detail):
    flag = db.base_record()
    flag.update({
        "store_id": store_id,
        "account_id": account_id,
        "flag_type": flag_type,
        "status": "OPEN",
        "receipt_ids": receipt_ids,
        "detail": detail,
    })
    db.flags[flag["id"]] = flag
    return flag


def split_scan(store, receipt):
    """SPLIT_TRANSACTION scan at receipt creation.  Candidate receipts are
    the account's other receipts at the same store with purchase_at in the
    half-open window (new.purchase_at - split_txn_window_hours,
    new.purchase_at]; when the cluster (candidates + the new receipt) reaches
    split_txn_min_receipts and at least two receipts share a SKU, an OPEN
    flag is raised.  The sale is never blocked."""
    window = timedelta(hours=store["split_txn_window_hours"])
    purchase_dt = temporal.purchase_dt(receipt)
    left_edge = purchase_dt - window

    cluster = [receipt]
    for other in db.receipts.values():
        if other["id"] == receipt["id"]:
            continue
        if other["store_id"] != receipt["store_id"]:
            continue
        if other["account_id"] != receipt["account_id"]:
            continue
        other_dt = temporal.purchase_dt(other)
        if left_edge < other_dt <= purchase_dt:
            cluster.append(other)

    if len(cluster) < store["split_txn_min_receipts"]:
        return None

    # At least two receipts of the cluster must share at least one SKU.
    skus_by_receipt = {
        r["id"]: {l["sku"] for l in receipt_lines_of(r["id"])}
        for r in cluster
    }
    ids = [r["id"] for r in cluster]
    shared = False
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if skus_by_receipt[ids[i]] & skus_by_receipt[ids[j]]:
                shared = True
                break
        if shared:
            break
    if not shared:
        return None

    cluster.sort(key=db.sort_key)
    numbers = [r["receipt_number"] for r in cluster]
    detail = ("Split-transaction cluster: %d receipts at store %s within the "
              "half-open window (%s, %s]; receipt numbers %s"
              % (len(cluster), store["store_code"],
                 iso_timestamp(left_edge), iso_timestamp(purchase_dt),
                 ", ".join(str(n) for n in numbers)))
    return _new_flag(store["id"], receipt["account_id"], "SPLIT_TRANSACTION",
                     [r["id"] for r in cluster], detail)


def duplicate_scan(store, receipt):
    """DUPLICATE_RECEIPT scan at submission creation: a non-REVERSED
    submission already exists for this receipt -> raise
    ERR_DUPLICATE_RECEIPT_SUBMISSION and record an OPEN flag listing the
    implicated receipt."""
    for sub in receipt_submissions(receipt["id"]):
        if sub["status"] != "REVERSED":
            detail = ("Duplicate rebate submission for receipt %s "
                      "(receipt_number %s); prior submission %s"
                      % (receipt["id"], receipt["receipt_number"], sub["id"]))
            _new_flag(store["id"], receipt["account_id"],
                      "DUPLICATE_RECEIPT", [receipt["id"]], detail)
            raise ApiError("ERR_DUPLICATE_RECEIPT_SUBMISSION",
                           "A non-REVERSED submission already exists for "
                           "this receipt")


# ---------------------------------------------------------------------------
# Guest-service reversal cascade (PRD 3.8)
# ---------------------------------------------------------------------------
def submission_eligible_line_ids(submission):
    """Receipt-line ids that contributed a positive eligible base to the
    submission (drives the reversal-cascade trigger)."""
    return {sl["receipt_line_id"]
            for sl in submission_lines_of(submission["id"])
            if sl["eligible_base_cents"] > 0}


def process_return_cascade(store, ret_record, receipt, touched_line_ids):
    """Fire the APPROVED -> REVERSED cascade when the return touched at
    least one line that fed an APPROVED submission on this receipt.

    Settles four levels in the same request: submission REVERSED, settling
    certificate VOIDED (pre-void remainder kept on the row but excluded by
    status), REVERSAL_DEBIT posted for the certificate's remaining balance
    (already-redeemed value is NOT clawed back), account and store figures
    recomputed.  lifetime_rebate_cents is never decremented.
    """
    reversal_entry_ids = []
    for sub in receipt_submissions(receipt["id"]):
        if sub["status"] != "APPROVED":
            continue
        if not (submission_eligible_line_ids(sub) & set(touched_line_ids)):
            continue

        sub["status"] = "REVERSED"
        sub["rejection_reason"] = None
        db.touch(sub)

        certs = [c for c in account_certificates(sub["account_id"])
                 if c["submission_id"] == sub["id"]
                 and c["status"] in ("ACTIVE", "PARTIALLY_REDEEMED")]
        for cert in certs:
            amount = cert["remaining_balance_cents"]
            cert["status"] = "VOIDED"
            db.touch(cert)
            entry = post_ledger(store, sub["account_id"], cert["id"],
                                "REVERSAL_DEBIT", -amount,
                                "return %s" % ret_record["id"])
            reversal_entry_ids.append(entry["id"])

        account = db.accounts.get(sub["account_id"])
        if account is not None:
            recompute_account(account)
        recompute_store(store)
    return reversal_entry_ids


# ---------------------------------------------------------------------------
# Contractor summary (calculation contractor_aggregation; PRD 3.3)
# ---------------------------------------------------------------------------
def contractor_summary(account):
    """Per-job net-of-reversal award totals plus the account-level volume
    bonus (average rate, single round-half-up; tier boundary inclusive
    upward)."""
    jobs = [j for j in db.ordered(db.jobs)
            if j["contractor_account_id"] == account["id"]]
    job_rows = []
    account_total = 0
    for job in jobs:
        job_receipt_ids = {r["id"] for r in db.receipts.values()
                           if r.get("job_purchase_id") == job["id"]}
        awarded = 0
        reversed_ = 0
        for sub in db.submissions.values():
            if sub["receipt_id"] not in job_receipt_ids:
                continue
            # REVERSED submissions were once APPROVED: they contribute to
            # both legs of the net-of-reversal figure (PRD 3.3: the job's
            # awarded total is the sum over APPROVED submissions, minus the
            # award_cents of REVERSED submissions on those same receipts).
            if sub["status"] in ("APPROVED", "REVERSED"):
                awarded += sub["award_cents"] or 0
            if sub["status"] == "REVERSED":
                reversed_ += sub["award_cents"] or 0
        net = awarded - reversed_
        account_total += net
        job_rows.append({
            "job_id": job["id"],
            "job_reference": job["job_reference"],
            "status": job["status"],
            "job_awarded_cents": net,
        })

    if account_total >= TIER2_THRESHOLD_CENTS:
        tier = "PRO_PLUS"
        bonus = round_half_up(Decimal(account_total) * PRO_PLUS_RATE)
    elif account_total >= TIER1_THRESHOLD_CENTS:
        tier = "PRO"
        bonus = round_half_up(Decimal(account_total) * PRO_RATE)
    else:
        tier = "NONE"
        bonus = 0

    return {
        "account_job_total_cents": account_total,
        "bonus_tier": tier,
        "bonus_cents": bonus,
        "jobs": job_rows,
    }
