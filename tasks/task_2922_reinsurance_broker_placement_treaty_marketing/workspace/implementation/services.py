"""Derived-field reconciliation and the cascade engine (PRD 2.9, 3.5-3.9).

Three rules from PRD 2.9 govern everything here: cascades are immediate and
complete within the request; every entity whose state or derived fields a cascade
mutates has its updated_at refreshed and its version incremented by one; and a
compound status is always re-derived from recomputed totals, never assumed.
"""
from decimal import Decimal

import calc
import db
import enums
from errors import fail
from util import Q4, dec, pct4

ZERO4 = Decimal("0.0000")
FULL = Decimal("100.0000")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_cedent(cedent_id):
    row = db.cedents.get(cedent_id)
    if row is None:
        fail("ERR_CEDENT_NOT_FOUND", "cedent %s does not exist" % cedent_id)
    return row


def get_reinsurer(reinsurer_id):
    row = db.reinsurers.get(reinsurer_id)
    if row is None:
        fail("ERR_REINSURER_NOT_FOUND", "reinsurer %s does not exist" % reinsurer_id)
    return row


def get_program(program_id):
    row = db.programs.get(program_id)
    if row is None:
        fail("ERR_PROGRAM_NOT_FOUND", "program %s does not exist" % program_id)
    return row


def get_prior_program(program_id):
    row = db.programs.get(program_id)
    if row is None:
        fail("ERR_PRIOR_PROGRAM_NOT_FOUND",
             "prior program %s does not exist" % program_id)
    return row


def get_submission(submission_id):
    row = db.exposure_submissions.get(submission_id)
    if row is None:
        fail("ERR_EXPOSURE_SUBMISSION_NOT_FOUND",
             "exposure submission %s does not exist" % submission_id)
    return row


def get_layer(layer_id):
    row = db.layers.get(layer_id)
    if row is None:
        fail("ERR_LAYER_NOT_FOUND", "layer %s does not exist" % layer_id)
    return row


def get_market_submission(market_submission_id):
    row = db.market_submissions.get(market_submission_id)
    if row is None:
        fail("ERR_MARKET_SUBMISSION_NOT_FOUND",
             "market submission %s does not exist" % market_submission_id)
    return row


def get_quote(quote_id):
    row = db.quotes.get(quote_id)
    if row is None:
        fail("ERR_QUOTE_NOT_FOUND", "quote %s does not exist" % quote_id)
    return row


def get_signing_line(signing_line_id):
    row = db.signing_lines.get(signing_line_id)
    if row is None:
        fail("ERR_SIGNING_LINE_NOT_FOUND",
             "signing line %s does not exist" % signing_line_id)
    return row


def get_disclosure(disclosure_id):
    row = db.brokerage_disclosures.get(disclosure_id)
    if row is None:
        fail("ERR_DISCLOSURE_NOT_FOUND",
             "brokerage disclosure %s does not exist" % disclosure_id)
    return row


def get_transaction(transaction_id):
    row = db.fiduciary_transactions.get(transaction_id)
    if row is None:
        fail("ERR_TRANSACTION_NOT_FOUND",
             "fiduciary transaction %s does not exist" % transaction_id)
    return row


def get_advocacy(claim_advocacy_id):
    row = db.claim_advocacies.get(claim_advocacy_id)
    if row is None:
        fail("ERR_CLAIM_ADVOCACY_NOT_FOUND",
             "claim advocacy %s does not exist" % claim_advocacy_id)
    return row


def get_dispute(dispute_id):
    row = db.cession_disputes.get(dispute_id)
    if row is None:
        fail("ERR_CESSION_DISPUTE_NOT_FOUND",
             "cession dispute %s does not exist" % dispute_id)
    return row


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def program_of_layer(layer):
    return db.programs[layer["program_id"]]


def layer_of_line(line):
    return db.layers[line["layer_id"]]


def program_of_line(line):
    return program_of_layer(db.layers[line["layer_id"]])


def program_of_advocacy(advocacy):
    return program_of_layer(db.layers[advocacy["layer_id"]])


def layers_of_program(program_id):
    return [r for r in db.ordered(db.layers) if r["program_id"] == program_id]


def lines_of_layer(layer_id):
    return [r for r in db.ordered(db.signing_lines) if r["layer_id"] == layer_id]


def lines_of_program(program_id):
    ids = {l["id"] for l in layers_of_program(program_id)}
    return [r for r in db.ordered(db.signing_lines) if r["layer_id"] in ids]


def submissions_of_layer(layer_id):
    return [r for r in db.ordered(db.market_submissions) if r["layer_id"] == layer_id]


def quotes_of_layer(layer_id):
    return [r for r in db.ordered(db.quotes) if r["layer_id"] == layer_id]


def advocacies_of_layer(layer_id):
    return [r for r in db.ordered(db.claim_advocacies) if r["layer_id"] == layer_id]


def disputes_of_advocacy(advocacy_id):
    return [r for r in db.ordered(db.cession_disputes)
            if r["claim_advocacy_id"] == advocacy_id]


def transactions_of_program(program_id):
    return [r for r in db.ordered(db.fiduciary_transactions)
            if r["program_id"] == program_id]


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------

def recompute_layer_totals(layer):
    """PRD 3.5: the written and signed totals over the layer's live lines."""
    written = ZERO4
    signed = ZERO4
    for line in lines_of_layer(layer["id"]):
        if line["status"] not in enums.LIVE_LINE_STATUSES:
            continue
        written += dec(line["written_line_pct"])
        if line["signed_line_pct"] is not None:
            signed += dec(line["signed_line_pct"])
    changed = (
        pct4(written) != dec(layer["written_line_total_pct"])
        or pct4(signed) != dec(layer["signed_line_total_pct"])
    )
    layer["written_line_total_pct"] = pct4(written)
    layer["signed_line_total_pct"] = pct4(signed)
    return changed


def derive_layer_status_forward(layer):
    """A total in (0,100) is PARTIALLY_PLACED, exactly 100 FULLY_PLACED,
    above 100 OVERSUBSCRIBED (PRD 3.5, second hop of the firm-order cascade)."""
    total = dec(layer["written_line_total_pct"])
    if total > FULL:
        return "OVERSUBSCRIBED"
    if total == FULL:
        return "FULLY_PLACED"
    if total > ZERO4:
        return "PARTIALLY_PLACED"
    return layer["status"]


def recompute_reinsurer_capacity(reinsurer_id):
    """PRD 3.5: the unwindowed committed total over the market's live lines."""
    market = db.reinsurers.get(reinsurer_id)
    if market is None:
        return
    committed = 0
    for line in db.ordered(db.signing_lines):
        if line["reinsurer_id"] != reinsurer_id:
            continue
        if line["status"] not in enums.LIVE_LINE_STATUSES:
            continue
        layer = db.layers[line["layer_id"]]
        committed += calc.line_capacity_minor(layer["limit_minor"],
                                             line["effective_line_pct"])
    available = market["capacity_limit_minor"] - committed
    if (market["committed_capacity_minor"] != committed
            or market["available_capacity_minor"] != available):
        market["committed_capacity_minor"] = committed
        market["available_capacity_minor"] = available
        db.touch(market)


def windowed_committed_capacity(reinsurer_id, target_program):
    """PRD 3.5: only lines whose own program is contemporaneous count.

    The window runs from thirty days before the target program's inception_date
    to thirty days after its expiry_date and is closed at both ends.
    """
    from util import add_days
    start = add_days(target_program["inception_date"], -calc.CAPACITY_WINDOW_DAYS)
    end = add_days(target_program["expiry_date"], calc.CAPACITY_WINDOW_DAYS)
    total = 0
    for line in db.ordered(db.signing_lines):
        if line["reinsurer_id"] != reinsurer_id:
            continue
        if line["status"] not in enums.LIVE_LINE_STATUSES:
            continue
        layer = db.layers[line["layer_id"]]
        program = db.programs[layer["program_id"]]
        inception = program["inception_date"]
        if inception < start or inception > end:
            continue
        total += calc.line_capacity_minor(layer["limit_minor"],
                                         line["effective_line_pct"])
    return total


def recompute_cedent_aggregates(cedent_id):
    """PRD 3.8: both cedent aggregates read the ledger across all its programs."""
    cedent = db.cedents.get(cedent_id)
    if cedent is None:
        return
    program_ids = {p["id"] for p in db.programs.values()
                   if p["cedent_id"] == cedent_id}
    receipts = 0
    outstanding = 0
    for txn in db.ordered(db.fiduciary_transactions):
        if txn["program_id"] not in program_ids:
            continue
        if txn["txn_type"] == "CEDENT_RECEIPT" and txn["status"] == "SETTLED":
            receipts += txn["amount_minor"]
        if (txn["txn_type"] == "REINSTATEMENT_PREMIUM"
                and txn["status"] in ("PENDING", "APPROVED")):
            outstanding += txn["amount_minor"]
    if (cedent["settled_receipts_minor"] != receipts
            or cedent["outstanding_reinstatement_premium_minor"] != outstanding):
        cedent["settled_receipts_minor"] = receipts
        cedent["outstanding_reinstatement_premium_minor"] = outstanding
        db.touch(cedent)


def recompute_program_balance(program):
    """PRD 3.8: an append-only projection over SETTLED and REVERSED rows."""
    balance = 0
    for txn in transactions_of_program(program["id"]):
        if txn["status"] not in ("SETTLED", "REVERSED"):
            continue
        if txn["txn_type"] in enums.INFLOW_TYPES:
            balance += txn["amount_minor"]
        else:
            balance -= txn["amount_minor"]
    changed = program["fiduciary_holding_minor"] != balance
    program["fiduciary_holding_minor"] = balance
    return changed


def recompute_advocacy_figures(advocacy):
    """PRD 3.9: the dispute overlay and the collectible remainder."""
    disputed = 0
    for dispute in disputes_of_advocacy(advocacy["id"]):
        status = dispute["status"]
        if status in ("RAISED", "UPHELD"):
            disputed += dispute["disputed_minor"]
        elif status == "SETTLED_PARTIAL":
            disputed += dispute["disputed_minor"] - dispute["settled_minor"]
    collectible = advocacy["ceded_claim_minor"] - disputed
    if collectible < 0:
        collectible = 0
    changed = (advocacy["disputed_minor"] != disputed
               or advocacy["collectible_minor"] != collectible)
    advocacy["disputed_minor"] = disputed
    advocacy["collectible_minor"] = collectible
    return changed


def recompute_advocacy_collected(advocacy):
    """PRD 3.9: collections booked against the file's signing lines, counted
    from the moment they are booked (PENDING, APPROVED or SETTLED)."""
    line_ids = {l["id"] for l in lines_of_layer(advocacy["layer_id"])}
    collected = 0
    for txn in db.ordered(db.fiduciary_transactions):
        if txn["txn_type"] != "CLAIM_COLLECTION":
            continue
        if txn["signing_line_id"] not in line_ids:
            continue
        if txn["status"] not in ("PENDING", "APPROVED", "SETTLED"):
            continue
        collected += txn["amount_minor"]
    changed = advocacy["collected_minor"] != collected
    advocacy["collected_minor"] = collected
    return changed


def recompute_layer_incurred(layer):
    """PRD 3.9: only RESOLVED and COLLECTED files enter incurred experience."""
    total = 0
    for advocacy in advocacies_of_layer(layer["id"]):
        if advocacy["status"] in ("RESOLVED", "COLLECTED"):
            total += advocacy["ceded_claim_minor"]
    changed = layer["incurred_ceded_minor"] != total
    layer["incurred_ceded_minor"] = total
    return changed


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def clear_market_on_program(program):
    """Fourth hop of the firm-order cascade, and part of a withdrawal.

    Every quote on the program's layers still in QUOTED, COUNTERED or REQUOTED
    lapses, and every submission still in SENT or QUOTED closes.
    """
    layer_ids = {l["id"] for l in layers_of_program(program["id"])}
    for quote in db.ordered(db.quotes):
        if quote["layer_id"] in layer_ids and quote["status"] in (
                "QUOTED", "COUNTERED", "REQUOTED"):
            quote["status"] = "LAPSED"
            db.touch(quote)
    for submission in db.ordered(db.market_submissions):
        if submission["layer_id"] in layer_ids and submission["status"] in (
                "SENT", "QUOTED"):
            submission["status"] = "CLOSED"
            db.touch(submission)


def promote_program_to_firm_order(program):
    """Third hop: every non-LAPSED layer is FULLY_PLACED or OVERSUBSCRIBED."""
    if program["placement_status"] != "IN_MARKET":
        return False
    layers = layers_of_program(program["id"])
    considered = [l for l in layers if l["status"] != "LAPSED"]
    if not considered:
        return False
    for layer in considered:
        if layer["status"] not in ("FULLY_PLACED", "OVERSUBSCRIBED"):
            return False
    program["placement_status"] = "FIRM_ORDER"
    db.touch(program)
    clear_market_on_program(program)
    return True


def revert_program_from_firm_order(program):
    """Third hop of the release cascade: a layer back in the market pulls the
    program back to IN_MARKET.  Lapsed quotes are never revived."""
    if program["placement_status"] != "FIRM_ORDER":
        return False
    for layer in layers_of_program(program["id"]):
        if layer["status"] in ("IN_MARKET", "PARTIALLY_PLACED"):
            program["placement_status"] = "IN_MARKET"
            db.touch(program)
            return True
    return False


def firm_order_cascade(layer, quote, accepted_line_pct, program):
    """The four-hop firm-order cascade of PRD 3.5."""
    line = db.base_row()
    line.update({
        "layer_id": layer["id"],
        "quote_id": quote["id"],
        "reinsurer_id": quote["reinsurer_id"],
        "written_line_pct": pct4(accepted_line_pct),
        "signed_line_pct": None,
        "effective_line_pct": pct4(accepted_line_pct),
        "committed_capacity_minor": calc.line_capacity_minor(
            layer["limit_minor"], accepted_line_pct),
        "status": "PROVISIONAL",
        "release_reason": None,
    })
    db.signing_lines[line["id"]] = line

    quote["accepted_line_pct"] = pct4(accepted_line_pct)
    quote["status"] = "FIRM_ORDER"
    db.touch(quote)

    recompute_layer_totals(layer)
    layer["status"] = derive_layer_status_forward(layer)
    db.touch(layer)

    promote_program_to_firm_order(program)
    recompute_reinsurer_capacity(quote["reinsurer_id"])
    return line


def release_line_cascade(line, reason, lapse_quote=True):
    """Reverse chain shared by broker release, sign-down zeroing, the security
    cascade and program withdrawal."""
    line["status"] = "RELEASED"
    line["release_reason"] = reason
    db.touch(line)
    if lapse_quote:
        quote = db.quotes.get(line["quote_id"])
        if quote is not None and quote["status"] == "FIRM_ORDER":
            quote["status"] = "LAPSED"
            db.touch(quote)


def revert_layer_after_release(layer):
    """Second hop of the release cascade (PRD 3.5).

    The sign-down is emphatically not recomputed: surviving SIGNED lines keep
    the signed percentages they were allocated.
    """
    recompute_layer_totals(layer)
    written = dec(layer["written_line_total_pct"])
    signed = dec(layer["signed_line_total_pct"])
    status = layer["status"]
    if status == "FULLY_PLACED":
        if written < FULL:
            layer["status"] = "PARTIALLY_PLACED"
    elif status == "OVERSUBSCRIBED":
        if written < FULL:
            layer["status"] = "PARTIALLY_PLACED"
        elif written == FULL:
            layer["status"] = "FULLY_PLACED"
    elif status == "SIGNED_DOWN":
        if signed < FULL:
            layer["status"] = "PARTIALLY_PLACED"
    db.touch(layer)


def security_suspension_cascade(market):
    """PRD 3.5: the reverse chain across every program the market sits on.

    Lines on layers that are already BOUND are untouched -- suspension is
    prospective and a bound contract is a contract.
    """
    touched_layers = {}
    for line in db.ordered(db.signing_lines):
        if line["reinsurer_id"] != market["id"]:
            continue
        if line["status"] not in ("PROVISIONAL", "SIGNED"):
            continue
        layer = db.layers[line["layer_id"]]
        if layer["status"] == "BOUND":
            continue
        release_line_cascade(line, "SECURITY_FAILURE", lapse_quote=False)
        touched_layers[layer["id"]] = layer

    touched_programs = {}
    for layer in touched_layers.values():
        recompute_layer_totals(layer)
        if layer["status"] in ("FULLY_PLACED", "OVERSUBSCRIBED"):
            layer["status"] = "PARTIALLY_PLACED"
        db.touch(layer)
        program = program_of_layer(layer)
        touched_programs[program["id"]] = program

    for program in touched_programs.values():
        if program["placement_status"] == "FIRM_ORDER":
            program["placement_status"] = "IN_MARKET"
            db.touch(program)

    for quote in db.ordered(db.quotes):
        if quote["reinsurer_id"] == market["id"] and quote["status"] == "FIRM_ORDER":
            quote["status"] = "LAPSED"
            db.touch(quote)

    recompute_reinsurer_capacity(market["id"])


def withdraw_program_cascade(program):
    """PRD 3.1: the larger cascade run from IN_MARKET or FIRM_ORDER."""
    layers = layers_of_program(program["id"])
    affected = []
    for layer in layers:
        if layer["status"] == "BOUND":
            continue
        if layer["status"] != "LAPSED":
            layer["status"] = "LAPSED"
            db.touch(layer)
        affected.append(layer)

    affected_ids = {l["id"] for l in affected}
    markets = set()
    for line in db.ordered(db.signing_lines):
        if line["layer_id"] not in affected_ids:
            continue
        if line["status"] in ("PROVISIONAL", "SIGNED"):
            line["status"] = "RELEASED"
            line["release_reason"] = "PROGRAM_WITHDRAWN"
            db.touch(line)
            markets.add(line["reinsurer_id"])

    for quote in db.ordered(db.quotes):
        if quote["layer_id"] in affected_ids and quote["status"] in (
                "QUOTED", "COUNTERED", "REQUOTED", "FIRM_ORDER"):
            quote["status"] = "LAPSED"
            db.touch(quote)

    for submission in db.ordered(db.market_submissions):
        if submission["layer_id"] in affected_ids and submission["status"] in (
                "SENT", "QUOTED"):
            submission["status"] = "CLOSED"
            db.touch(submission)

    for market_id in sorted(markets):
        recompute_reinsurer_capacity(market_id)


def sign_down_layer(layer, program):
    """PRD 3.6: the two-stage floor-and-residue waterfall."""
    provisional = [l for l in lines_of_layer(layer["id"])
                   if l["status"] == "PROVISIONAL"]
    entries = []
    for line in provisional:
        quote = db.quotes.get(line["quote_id"])
        market = db.reinsurers.get(line["reinsurer_id"])
        entries.append({
            "id": line["id"],
            "written": dec(line["written_line_pct"]),
            "is_lead": bool(quote["is_lead"]) if quote else False,
            "reinsurer_name": market["name"] if market else "",
            "created_at": line["created_at"],
            "seq": line["_seq"],
        })

    shares = calc.signing_down_allocation(entries, program["signdown_method"])

    markets = set()
    for line in provisional:
        share = shares.get(line["id"], ZERO4)
        line["signed_line_pct"] = pct4(share)
        line["effective_line_pct"] = pct4(share)
        line["committed_capacity_minor"] = calc.line_capacity_minor(
            layer["limit_minor"], share)
        if pct4(share) == ZERO4:
            line["status"] = "RELEASED"
            line["release_reason"] = "SIGNDOWN_ZEROED"
            line["committed_capacity_minor"] = 0
            quote = db.quotes.get(line["quote_id"])
            if quote is not None and quote["status"] == "FIRM_ORDER":
                quote["status"] = "LAPSED"
                db.touch(quote)
        else:
            line["status"] = "SIGNED"
        db.touch(line)
        markets.add(line["reinsurer_id"])

    recompute_layer_totals(layer)
    layer["signed_line_total_pct"] = FULL
    layer["status"] = "SIGNED_DOWN"
    db.touch(layer)

    for market_id in markets:
        recompute_reinsurer_capacity(market_id)


def bind_program(program):
    """PRD 3.6: binding converts the whole file and pins the money."""
    layers = layers_of_program(program["id"])
    bound_layers = [l for l in layers if l["status"] in ("FULLY_PLACED", "SIGNED_DOWN")]
    bound_ids = {l["id"] for l in bound_layers}
    markets = set()

    for layer in bound_layers:
        layer["status"] = "BOUND"

    for line in db.ordered(db.signing_lines):
        if line["layer_id"] not in bound_ids:
            continue
        if line["status"] == "PROVISIONAL":
            line["signed_line_pct"] = pct4(line["written_line_pct"])
            line["effective_line_pct"] = pct4(line["written_line_pct"])
            line["committed_capacity_minor"] = calc.line_capacity_minor(
                db.layers[line["layer_id"]]["limit_minor"], line["signed_line_pct"])
            line["status"] = "BOUND"
            db.touch(line)
            markets.add(line["reinsurer_id"])
        elif line["status"] == "SIGNED":
            line["status"] = "BOUND"
            db.touch(line)
            markets.add(line["reinsurer_id"])

    for quote in db.ordered(db.quotes):
        if quote["layer_id"] in bound_ids and quote["status"] == "FIRM_ORDER":
            quote["status"] = "BOUND"
            db.touch(quote)

    # Provisional ceding commission, quota-share only.
    for layer in bound_layers:
        recompute_layer_totals(layer)
        if layer["layer_type"] == "QUOTA_SHARE":
            layer["provisional_ceding_commission_minor"] = \
                calc.provisional_ceding_commission(
                    layer["quoted_gross_premium_minor"],
                    layer["ceding_commission_pct"])
        db.touch(layer)

    # Brokerage and net remittance over BOUND lines of BOUND layers.
    contributing = []
    for line in db.ordered(db.signing_lines):
        if line["layer_id"] not in bound_ids or line["status"] != "BOUND":
            continue
        layer = db.layers[line["layer_id"]]
        contributing.append((layer["quoted_gross_premium_minor"],
                             line["signed_line_pct"]))
    brokerage, net = calc.brokerage_and_net_remittance(
        contributing, program["brokerage_pct"])
    gross = sum(l["quoted_gross_premium_minor"] for l in bound_layers)

    program["gross_written_premium_minor"] = gross
    program["brokerage_earned_minor"] = brokerage
    program["net_remittance_minor"] = net
    program["rounding_residue_minor"] = gross - (brokerage + net)
    program["placement_status"] = "BOUND"
    db.touch(program)

    for market_id in markets:
        recompute_reinsurer_capacity(market_id)


def settle_program(program):
    """PRD 3.9: the accounting close reconciles the ceding commission."""
    for layer in layers_of_program(program["id"]):
        if layer["status"] != "BOUND":
            continue
        recompute_layer_incurred(layer)
        layer["loss_ratio_pct"] = calc.loss_ratio_pct(
            layer["incurred_ceded_minor"], layer["quoted_gross_premium_minor"])
        if layer["layer_type"] == "QUOTA_SHARE":
            final_pct = calc.final_ceding_commission_pct(
                layer["ceding_commission_pct"], layer["loss_ratio_pct"])
            final_amount = calc.final_ceding_commission(
                layer["quoted_gross_premium_minor"], final_pct)
            provisional = layer["provisional_ceding_commission_minor"] or 0
            layer["final_ceding_commission_minor"] = final_amount
            layer["ceding_commission_delta_minor"] = final_amount - provisional
        db.touch(layer)

    program["placement_status"] = "SETTLED"
    db.touch(program)


def breach_contract_certainty(program):
    """PRD 3.7: the breach freezes outbound money but not inbound receipts."""
    program["documentation_status"] = "CERTAINTY_BREACHED"
    db.touch(program)
    for txn in transactions_of_program(program["id"]):
        if txn["txn_type"] not in ("REINSURER_REMITTANCE", "REINSTATEMENT_PREMIUM"):
            continue
        if txn["status"] not in ("PENDING", "APPROVED"):
            continue
        txn["status"] = "HELD"
        txn["hold_reason"] = "CONTRACT_CERTAINTY_BREACHED"
        db.touch(txn)
    recompute_cedent_aggregates(program["cedent_id"])


def release_held_transactions(program):
    """PRD 3.7: an AGREED_WORDING filing releases every HELD movement, which
    must then be re-approved from scratch."""
    for txn in transactions_of_program(program["id"]):
        if txn["status"] != "HELD":
            continue
        txn["status"] = "PENDING"
        txn["hold_reason"] = None
        txn["approved_by_user_id"] = None
        db.touch(txn)
    recompute_cedent_aggregates(program["cedent_id"])


def new_transaction(program, txn_type, amount_minor, created_by_user_id,
                    signing_line_id=None, status="PENDING", value_date=None,
                    reverses_transaction_id=None):
    row = db.base_row()
    row.update({
        "program_id": program["id"],
        "signing_line_id": signing_line_id,
        "reverses_transaction_id": reverses_transaction_id,
        "txn_type": txn_type,
        "amount_minor": amount_minor,
        "created_by_user_id": created_by_user_id,
        "approved_by_user_id": None,
        "value_date": value_date,
        "hold_reason": None,
        "status": status,
    })
    db.fiduciary_transactions[row["id"]] = row
    return row


def collected_cascade(advocacy, program, actor_user_id):
    """PRD 3.9: the three-hop cascade that closes a fully collected file."""
    layer = db.layers[advocacy["layer_id"]]
    ceded = advocacy["ceded_claim_minor"]
    previous_used = layer["reinstatements_used"]
    new_eroded, new_used, reinstated = calc.erosion_after_collection(layer, ceded)
    layer["limit_eroded_minor"] = new_eroded
    layer["reinstatements_used"] = new_used

    triggered = new_used > previous_used
    advocacy["reinstatement_triggered"] = triggered
    advocacy["status"] = "COLLECTED"

    if triggered:
        premium = calc.reinstatement_premium_minor(layer, reinstated)
        if premium > 0:
            new_transaction(program, "REINSTATEMENT_PREMIUM", premium,
                            actor_user_id)

    recompute_layer_incurred(layer)
    db.touch(layer)
    recompute_cedent_aggregates(program["cedent_id"])


# ---------------------------------------------------------------------------
# Layer structure and pricing (PRD 3.3), shared by create and restructure
# ---------------------------------------------------------------------------

def check_layer_structure(layer):
    """Priority 52 then priority 53."""
    if layer["layer_type"] == "QUOTA_SHARE":
        coherent = (
            layer["attachment_minor"] == 0
            and dec(layer["cession_pct"]) > 0
            and dec(layer["base_rate_pct"]) == dec(layer["cession_pct"])
        )
    else:
        coherent = (
            layer["attachment_minor"] > 0
            and dec(layer["cession_pct"]) == 0
            and dec(layer["ceding_commission_pct"]) == 0
        )
    if not coherent:
        fail("ERR_LAYER_STRUCTURE_INVALID",
             "the layer's structure is incoherent with its layer_type")
    if layer["sublimit_minor"] > layer["limit_minor"]:
        fail("ERR_SUBLIMIT_EXCEEDS_LIMIT",
             "sublimit_minor may not exceed limit_minor")


def apply_technical_premium(layer):
    """PRD 3.3: recomputed on create and on every restructure, then frozen."""
    _provisional, _discount, quoted = calc.layer_technical_premium(
        layer["subject_premium_base_minor"],
        layer["base_rate_pct"],
        layer["reinstatements_total"],
    )
    layer["quoted_gross_premium_minor"] = quoted
    return quoted


def bound_limit_minor(program_id):
    """The total limit_minor of a program's BOUND layers (PRD 3.9)."""
    total = 0
    for layer in layers_of_program(program_id):
        if layer["status"] == "BOUND":
            total += layer["limit_minor"]
    return total
