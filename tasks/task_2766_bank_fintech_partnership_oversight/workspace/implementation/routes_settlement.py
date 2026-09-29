"""Settlement batches, reconciliation, variance, funding, clawback and the ledger."""
from flask import Blueprint, g

import calc
import cascade
import respond
import schema
import serialize
import store
from authz import auth, scope_partner_id, scope_rows
from errors import fail

bp = Blueprint("settlement", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")
POSITIVE_TYPES = ("END_USER_CREDIT", "RESERVE_FUND", "CLAWBACK")
NEGATIVE_TYPES = ("END_USER_DEBIT", "RESERVE_RELEASE", "FEE")
FBO_ONLY = ("END_USER_CREDIT", "END_USER_DEBIT")
RESERVE_ONLY = ("RESERVE_FUND", "RESERVE_RELEASE")


def _write_entry(partner_id, account, entry_type, amount, effective_at, memo="",
                 batch_id=None, reversal_of=None):
    record = {
        "partner_id": partner_id,
        "custody_account_id": account["id"],
        "settlement_batch_id": batch_id,
        "entry_type": entry_type,
        "amount_cents": int(amount),
        "effective_at": effective_at,
        "sequence_no": store.next_sequence_no(account["id"]),
        "memo": memo,
        "reversal_of_entry_id": reversal_of,
    }
    store.insert("ledger_entries", record, common_fields=False)
    return record


# --------------------------------------------------------------------------- #
# Settlement batches
# --------------------------------------------------------------------------- #
@bp.post("/oversight/settlement-batches")
@auth("FintechPartner", "ProgramOfficer")
def create_batch():
    data = schema.body()
    partner = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    if partner is not None:                                          # rank 12
        scope_partner_id(partner["id"])
    schema.req_str(data, "partner_id")                               # rank 18
    window_start = schema.req_dt(data, "window_start")
    window_end = schema.req_dt(data, "window_end")
    gross = schema.req_int(data, "gross_settlement_cents", 0)
    interchange = schema.req_int(data, "interchange_cents", 0)
    returns = schema.req_int(data, "returns_cents", 0)
    reported = schema.req_int(data, "partner_reported_net_cents")
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    if window_end <= window_start:                                   # rank 60
        fail("ERR_INVALID_INTERVAL", "window_end must be after window_start")
    for other in store.rows("settlement_batches"):                   # rank 62
        if other["partner_id"] != partner["id"]:
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            fail("ERR_SETTLEMENT_WINDOW_OVERLAP", "settlement windows intersect")
    record = {
        "partner_id": partner["id"],
        "window_start": window_start,
        "window_end": window_end,
        "gross_settlement_cents": gross,
        "interchange_cents": interchange,
        "returns_cents": returns,
        "partner_reported_net_cents": reported,
        "bank_reported_net_cents": None,
        "variance_cents": 0,
        "variance_adjustment_cents": 0,
        "settlement_base_cents": 0,
        "bank_fee_bps_applied": 0,
        "bank_fee_cents": 0,
        "reserve_funding_cents": 0,
        "net_to_partner_cents": 0,
        "shortfall_carry_cents": 0,
        "reconciliation_status": "UNRECONCILED",
        "funding_status": "UNFUNDED",
        "funded_at": None,
        "funding_reference": None,
        "clawback_reason": None,
        "_funding_entry_ids": [],
    }
    store.insert("settlement_batches", record)
    return respond.ok(serialize.settlement_batch(record), 201)


@bp.get("/oversight/settlement-batches")
@auth(*READ_ROLES)
def list_batches():
    rows = store.rows("settlement_batches")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    recon = schema.filter_enum("reconciliation_status", schema.RECON_STATUSES)
    if recon is not None:
        rows = [r for r in rows if r["reconciliation_status"] == recon]
    funding = schema.filter_enum("funding_status", schema.FUNDING_STATUSES)
    if funding is not None:
        rows = [r for r in rows if r["funding_status"] == funding]
    return respond.paginate(scope_rows(rows), serialize.settlement_batch)


@bp.get("/oversight/settlement-batches/<bid>")
@auth(*READ_ROLES)
def read_batch(bid):
    batch = store.must("settlement_batches", bid)
    scope_partner_id(batch["partner_id"])
    return respond.ok(serialize.settlement_batch(batch))


@bp.post("/oversight/settlement-batches/<bid>/reconcile")
@auth("InternalAudit", "ProgramOfficer")
def reconcile_batch(bid):
    batch = store.must("settlement_batches", bid)                    # rank 8
    data = schema.body()
    reported = schema.req_int(data, "bank_reported_net_cents")       # rank 18
    if batch["reconciliation_status"] != "UNRECONCILED":             # rank 34
        fail("ERR_BATCH_NOT_UNRECONCILED", "batch is not UNRECONCILED")
    partner = store.get("partners", batch["partner_id"])
    batch["bank_reported_net_cents"] = reported
    batch["variance_cents"] = reported - int(batch["partner_reported_net_cents"])
    if batch["variance_cents"] == 0:
        batch["reconciliation_status"] = "MATCHED"
        cascade.refresh_unreconciled_variance(partner)
    else:
        batch["reconciliation_status"] = "VARIANCE_OPEN"
        cascade.refresh_unreconciled_variance(partner)
        cascade.refresh_posture(partner)
        cascade.freeze_custody_if_frozen(partner)
    store.touch(batch)
    store.touch(partner)
    return respond.ok(serialize.settlement_batch(batch))


@bp.post("/oversight/settlement-batches/<bid>/clear-variance")
@auth("InternalAudit")
def clear_variance(bid):
    batch = store.must("settlement_batches", bid)                    # rank 8
    data = schema.body()
    adjustment = schema.req_int(data, "variance_adjustment_cents")   # rank 18
    schema.req_str(data, "root_cause_note", 1)
    if batch["reconciliation_status"] != "VARIANCE_OPEN":            # rank 34
        fail("ERR_BATCH_NO_OPEN_VARIANCE", "batch has no open variance")
    if int(batch["partner_reported_net_cents"]) + adjustment != \
            int(batch["bank_reported_net_cents"]):                   # rank 75
        fail("ERR_VARIANCE_NOT_EXPLAINED", "adjustment does not close the variance")
    partner = store.get("partners", batch["partner_id"])
    batch["variance_adjustment_cents"] = adjustment
    batch["settlement_base_cents"] = (int(batch["gross_settlement_cents"])
                                      + int(batch["interchange_cents"])
                                      - int(batch["returns_cents"]) + adjustment)
    batch["reconciliation_status"] = "VARIANCE_CLEARED"
    cascade.refresh_unreconciled_variance(partner)
    if batch["funding_status"] == "FUNDED":
        reserve = calc.account_of(partner["id"], "RESERVE")
        if reserve is not None:
            _write_entry(partner["id"], reserve, "VARIANCE_ADJUSTMENT", adjustment,
                         store.clock(), "", batch["id"])
            cascade.refresh_balance(reserve)
    cascade.money_cascade(partner)
    store.touch(batch)
    store.touch(partner)
    return respond.ok(serialize.settlement_batch(batch))


@bp.post("/oversight/settlement-batches/<bid>/fund")
@auth("ProgramOfficer")
def fund_batch(bid):
    batch = store.must("settlement_batches", bid)                    # rank 8
    data = schema.body()
    reference = schema.req_str(data, "funding_reference", 1)         # rank 18
    if batch["funding_status"] != "UNFUNDED":                        # rank 34
        fail("ERR_BATCH_ALREADY_FUNDED", "batch is not UNFUNDED")
    if batch["reconciliation_status"] == "UNRECONCILED":             # rank 36
        fail("ERR_BATCH_NOT_RECONCILED", "batch is not reconciled")
    partner = store.get("partners", batch["partner_id"])
    if partner["status"] != "LIVE":                                  # rank 38
        fail("ERR_PARTNER_NOT_LIVE", "partner is not LIVE")
    fbo = calc.account_of(partner["id"], "FBO_END_USER")
    reserve = calc.account_of(partner["id"], "RESERVE")
    if reserve is None or reserve["status"] != "ACTIVE":             # rank 46
        fail("ERR_CUSTODY_ACCOUNT_NOT_ACTIVE", "reserve account is not ACTIVE")
    agreement = calc.governing_agreement(partner["id"])
    reserve_bps = int(agreement["reserve_requirement_bps"]) if agreement else 0
    money = calc.settlement_money(batch, reserve_bps)
    if fbo is None or int(fbo["balance_cents"]) - money["settlement_base_cents"] < 0:
        fail("ERR_CUSTODY_INSUFFICIENT_FUNDS", "funding would overdraw custody")  # rank 80
    if int(partner["reserve_shortfall_cents"]) != 0:                 # rank 86
        fail("ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING", "reserve shortfall blocks funding")
    for key, value in money.items():
        batch[key] = value
    now = store.clock()
    leg_ids = []
    leg_ids.append(_write_entry(partner["id"], fbo, "END_USER_DEBIT",
                                -money["settlement_base_cents"], now, "",
                                batch["id"])["id"])
    leg_ids.append(_write_entry(
        partner["id"], reserve, "RESERVE_FUND",
        money["reserve_funding_cents"] + money["shortfall_carry_cents"], now, "",
        batch["id"])["id"])
    if money["bank_fee_cents"] > 0:
        leg_ids.append(_write_entry(partner["id"], reserve, "FEE",
                                    -money["bank_fee_cents"], now, "", batch["id"])["id"])
    batch["_funding_entry_ids"] = leg_ids
    partner["cumulative_paid_out_cents"] = (int(partner["cumulative_paid_out_cents"])
                                            + money["net_to_partner_cents"])
    partner["cumulative_bank_fee_cents"] = (int(partner["cumulative_bank_fee_cents"])
                                            + money["bank_fee_cents"])
    cascade.refresh_balance(fbo)
    cascade.refresh_balance(reserve)
    cascade.money_cascade(partner)
    batch["funding_status"] = "FUNDED"
    batch["funded_at"] = now
    batch["funding_reference"] = reference
    store.touch(batch)
    store.touch(partner)
    return respond.ok(serialize.settlement_batch(batch))


@bp.post("/oversight/settlement-batches/<bid>/clawback")
@auth("ProgramOfficer")
def clawback_batch(bid):
    batch = store.must("settlement_batches", bid)                    # rank 8
    data = schema.body()
    reason = schema.req_enum(data, "clawback_reason", schema.CLAWBACK_REASONS)  # rank 18
    if batch["funding_status"] != "FUNDED":                          # rank 34
        fail("ERR_BATCH_NOT_FUNDED", "batch is not FUNDED")
    partner = store.get("partners", batch["partner_id"])
    if partner["status"] not in ("LIVE", "WIND_DOWN"):               # rank 38
        fail("ERR_PARTNER_NOT_LIVE", "partner is not LIVE or WIND_DOWN")
    now = store.clock()
    for entry_id in list(batch.get("_funding_entry_ids") or []):
        original = store.get("ledger_entries", entry_id)
        if original is None:
            continue
        account = store.get("custody_accounts", original["custody_account_id"])
        _write_entry(partner["id"], account, "CLAWBACK", -int(original["amount_cents"]),
                     now, "", batch["id"], original["id"])
    partner["cumulative_paid_out_cents"] = (int(partner["cumulative_paid_out_cents"])
                                            - int(batch["net_to_partner_cents"]))
    partner["cumulative_bank_fee_cents"] = (int(partner["cumulative_bank_fee_cents"])
                                            - int(batch["bank_fee_cents"]))
    for account_type in ("FBO_END_USER", "RESERVE"):
        account = calc.account_of(partner["id"], account_type)
        if account is not None:
            cascade.refresh_balance(account)
    cascade.money_cascade(partner)
    batch["funding_status"] = "CLAWED_BACK"
    batch["clawback_reason"] = reason
    store.touch(batch)
    store.touch(partner)
    return respond.ok(serialize.settlement_batch(batch))


# --------------------------------------------------------------------------- #
# Ledger entries
# --------------------------------------------------------------------------- #
@bp.post("/oversight/ledger-entries")
@auth("ProgramOfficer", "FintechPartner")
def create_entry():
    data = schema.body()
    partner = None
    account = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    if data.get("custody_account_id") is not None:
        account = store.must("custody_accounts", data["custody_account_id"])
    if partner is not None:                                          # rank 12
        scope_partner_id(partner["id"])
    schema.req_str(data, "partner_id")                               # rank 18
    schema.req_str(data, "custody_account_id")
    entry_type = schema.req_enum(data, "entry_type", schema.ENTRY_TYPES)
    amount = schema.req_int(data, "amount_cents")
    effective_at = schema.req_dt(data, "effective_at")
    expected = schema.req_int(data, "expected_custody_account_version")
    memo = schema.opt_str(data, "memo", "")
    if account["partner_id"] != partner["id"]:                       # rank 24
        fail("ERR_CUSTODY_PARTNER_MISMATCH", "custody account belongs to another partner")
    if expected != int(account["version"]):                          # rank 29
        fail("ERR_STALE_CUSTODY_ACCOUNT_VERSION", "custody account version is stale")
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    if entry_type == "END_USER_CREDIT" and partner["status"] != "LIVE":  # rank 38
        fail("ERR_PARTNER_NOT_LIVE", "partner is not LIVE")
    if account["status"] != "ACTIVE":                                 # rank 46
        fail("ERR_CUSTODY_ACCOUNT_NOT_ACTIVE", "custody account is not ACTIVE")
    if entry_type == "END_USER_CREDIT" and \
            partner["oversight_posture"] == "FROZEN":                 # rank 52
        fail("ERR_POSTURE_BLOCKS_INFLOW", "posture FROZEN blocks end-user inflow")
    bad_sign = (
        (entry_type in POSITIVE_TYPES and amount <= 0)
        or (entry_type in NEGATIVE_TYPES and amount >= 0)
        or amount == 0
        or (entry_type in FBO_ONLY and account["account_type"] != "FBO_END_USER")
        or (entry_type in RESERVE_ONLY and account["account_type"] != "RESERVE")
    )
    if bad_sign:                                                     # rank 73
        fail("ERR_LEDGER_SIGN_MISMATCH", "sign or account discipline violated")
    open_cycle = None
    for cycle in store.rows("cycles"):
        if cycle["status"] != "OPEN":
            continue
        if cycle["period_start"] <= effective_at < cycle["period_end"]:
            open_cycle = cycle
            break
    if open_cycle is None:                                           # rank 74
        fail("ERR_NO_OPEN_CYCLE", "effective_at falls in no OPEN cycle period")
    resulting = int(account["balance_cents"]) + amount
    if resulting < 0:                                                # rank 80
        fail("ERR_CUSTODY_INSUFFICIENT_FUNDS", "custody account would go negative")
    if entry_type == "END_USER_CREDIT":
        agreement = calc.governing_agreement(partner["id"])
        if agreement is not None:
            if resulting > int(agreement["max_end_user_balance_cents"]):   # rank 82
                fail("ERR_END_USER_BALANCE_CAP_EXCEEDED", "end-user balance cap exceeded")
            numerator, denominator, _ = calc.concentration_parts(partner)
            ratio = calc.concentration_ratio(numerator + amount, denominator + amount)
            if ratio >= float(agreement["concentration_cap_pct"]):    # rank 84
                fail("ERR_CONCENTRATION_CAP_BREACH", "concentration cap breached")
    record = _write_entry(partner["id"], account, entry_type, amount, effective_at, memo)
    cascade.refresh_balance(account)
    cascade.money_cascade(partner)
    store.touch(partner)
    return respond.ok(serialize.ledger_entry(record), 201)


@bp.get("/oversight/ledger-entries")
@auth(*READ_ROLES)
def list_entries():
    rows = list(store.DB["ledger_entries"].values())
    rows.sort(key=lambda r: (r["custody_account_id"], r["sequence_no"]))
    account_id = schema.filter_str("custody_account_id")
    if account_id is not None:
        rows = [r for r in rows if r["custody_account_id"] == account_id]
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    batch_id = schema.filter_str("settlement_batch_id")
    if batch_id is not None:
        rows = [r for r in rows if r["settlement_batch_id"] == batch_id]
    reversal_of = schema.filter_str("reversal_of_entry_id")
    if reversal_of is not None:
        rows = [r for r in rows if r["reversal_of_entry_id"] == reversal_of]
    entry_type = schema.filter_enum("entry_type", schema.ENTRY_TYPES)
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return respond.paginate(scope_rows(rows), serialize.ledger_entry)


@bp.get("/oversight/ledger-entries/<eid>")
@auth(*READ_ROLES)
def read_entry(eid):
    entry = store.must("ledger_entries", eid)
    scope_partner_id(entry["partner_id"])
    return respond.ok(serialize.ledger_entry(entry))
