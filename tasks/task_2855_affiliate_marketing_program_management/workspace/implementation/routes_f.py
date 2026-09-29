"""Routes: ledger reads, payout batch generation / reconciliation / approval /
payment / voiding, payout lines and the test-only logical clock
(PRD 3.6 and 3.9)."""

import calc
import serializers as S
import services as SV
from common import (
    ALL_STAFF, ApiError, ROLE_COMPLIANCE, ROLE_FIN_ANALYST,
    ROLE_FIN_CONTROLLER, ROLE_INGESTOR, ROLE_PARTNER, ROLE_PARTNER_MANAGER,
    ROLE_PROGRAM_ADMIN, authorize, body, check_sod, clock, db, fail, fmt_dt, g,
    get_instant, get_int, get_str, new_row, ordered, opt_raw, paginate,
    parse_instant, query_filter, respond, touch,
)

FINANCE_READ = [ROLE_PROGRAM_ADMIN, ROLE_FIN_ANALYST, ROLE_FIN_CONTROLLER]


def register(app):

    # -- Commission ledger --------------------------------------------------

    @app.get("/commission-ledger-entries/<eid>")
    def get_ledger_entry(eid):
        authorize(FINANCE_READ)
        row = db.ledger.get(eid)
        if row is None:
            raise ApiError("ERR_LEDGER_ENTRY_NOT_FOUND",
                           "no such commission ledger entry", 404)
        return respond(S.ledger_out(row))

    @app.get("/commission-ledger-entries")
    def list_ledger_entries():
        role = authorize(FINANCE_READ + [ROLE_PARTNER])[1]
        rows = ordered(db.ledger)
        if role == ROLE_PARTNER:
            rows = [r for r in rows if r["affiliate_id"] == g.user_id]
        rows = query_filter(rows, "affiliate_id")
        rows = query_filter(rows, "conversion_id")
        rows = query_filter(rows, "payout_batch_id")
        rows = query_filter(rows, "entry_type")
        return paginate(rows, S.ledger_out)

    # -- Payout batches -----------------------------------------------------

    @app.post("/payout-batches")
    def generate_batch():
        authorize([ROLE_FIN_ANALYST])
        payload = body()
        raw_network = opt_raw(payload, "network_id")
        network = None
        if raw_network is not None:
            network = SV.find_network(raw_network)
        if network is None:
            fail("ERR_INVALID_REQUEST", "network_id is required")
        period_start = get_instant(payload, "period_start")
        period_end = get_instant(payload, "period_end")

        SV.validation_sweep()
        SV.tax_refresh()

        claimed = []
        for entry in ordered(db.ledger):
            if entry["payout_batch_id"] is not None:
                continue
            if not entry["conversion_id"]:
                continue
            conv = db.conversions.get(entry["conversion_id"])
            if conv is None:
                continue
            if conv["validation_status"] not in ("VALIDATED", "CLAWED_BACK"):
                continue
            placed = parse_instant(conv["placed_at"])
            if placed is None or placed < period_start or placed >= period_end:
                continue
            claimed.append(entry)
        if not claimed:
            fail("ERR_NO_ELIGIBLE_PAYOUT_LINES",
                 "no unstamped ledger entry qualifies for this period")

        batch = new_row(
            network_id=network["id"], period_start=fmt_dt(period_start),
            period_end=fmt_dt(period_end), state="DRAFT", line_count=0,
            gross_commission_cents=0, clawback_cents=0, network_fee_cents=0,
            withholding_cents=0, net_payable_cents=0,
            statement_gross_cents=None, statement_fee_cents=None,
            network_fee_variance_cents=None, network_fee_variance_bps=None,
            reconciliation_status="PENDING", prepared_by_user_id=g.user_id,
            approved_by_user_id=None, payment_reference=None, void_reason=None,
        )
        db.batches[batch["id"]] = batch
        partner_ids = []
        for entry in claimed:
            entry["payout_batch_id"] = batch["id"]
            if entry["affiliate_id"] not in partner_ids:
                partner_ids.append(entry["affiliate_id"])
        for affiliate_id in partner_ids:
            values = SV.compute_line_values(batch, affiliate_id)
            line = new_row(
                payout_batch_id=batch["id"], affiliate_id=affiliate_id,
                state="INCLUDED", hold_reason=None, released_by_user_id=None,
                **values)
            if line["net_cents"] < calc.MIN_PAYOUT_CENTS:
                line["state"] = "HELD_BELOW_MINIMUM"
                line["hold_reason"] = "BELOW_MINIMUM_PAYOUT"
            db.lines[line["id"]] = line
        batch["line_count"] = len(partner_ids)
        SV.recompute_batch_totals(batch)
        return respond(S.batch_out(batch), 201)

    @app.get("/payout-batches/<bid>")
    def get_batch(bid):
        authorize(FINANCE_READ)
        return respond(S.batch_out(SV.find_batch(bid)))

    @app.get("/payout-batches")
    def list_batches():
        authorize(FINANCE_READ)
        rows = ordered(db.batches)
        rows = query_filter(rows, "network_id")
        rows = query_filter(rows, "state")
        rows = query_filter(rows, "reconciliation_status")
        return paginate(rows, S.batch_out)

    @app.post("/payout-batches/<bid>/validate")
    def validate_batch(bid):
        authorize([ROLE_FIN_ANALYST])
        batch = SV.find_batch(bid)
        payload = body()
        statement_gross = get_int(payload, "statement_gross_cents", min_v=0)
        statement_fee = get_int(payload, "statement_fee_cents", min_v=0)
        if batch["state"] in ("PAID", "VOIDED"):
            fail("ERR_BATCH_TERMINAL", "the batch is terminal")
        if batch["state"] != "DRAFT":
            fail("ERR_BATCH_NOT_VALIDATED", "only a DRAFT batch may be validated")

        # Everything below is computed as a plan first: a failed reconciliation
        # must leave the batch, its lines and the tax documents untouched.
        expiring = SV.tax_expiry_plan()
        expired_ids = set(d["id"] for d in expiring)
        plan = []
        gross = clawback = fee = withheld = net = 0
        for line in SV.lines_of_batch(batch["id"]):
            if line["state"] == "VOIDED":
                continue
            values = SV.compute_line_values(batch, line["affiliate_id"],
                                            expired_ids)
            state, hold = line["state"], line["hold_reason"]
            if state == "INCLUDED":
                affiliate = db.affiliates.get(line["affiliate_id"])
                tax_status = SV.prospective_tax_status(affiliate, expired_ids)
                if tax_status != "VALID":
                    state, hold = "HELD_TAX_DOC", "TAX_DOCUMENT_NOT_VALID"
                elif affiliate is None or affiliate["status"] != "ACTIVE":
                    state, hold = "HELD_FRAUD", "AFFILIATE_SUSPENDED"
                elif (values["net_cents"] < calc.MIN_PAYOUT_CENTS
                        and not line.get("minimum_waived")):
                    state, hold = "HELD_BELOW_MINIMUM", "BELOW_MINIMUM_PAYOUT"
            plan.append((line, values, state, hold))
            gross += values["gross_cents"]
            clawback += values["clawback_cents"]
            if state in ("INCLUDED", "PAID"):
                fee += values["network_fee_cents"]
                withheld += values["withholding_cents"]
                net += values["net_cents"]
        if statement_gross != gross:
            fail("ERR_NETWORK_FEE_VARIANCE",
                 "statement_gross_cents does not match the computed gross")
        variance, variance_bps, status = calc.fee_variance(statement_fee, fee)
        if status is None:
            fail("ERR_NETWORK_FEE_VARIANCE",
                 "the network fee variance exceeds the accepted tolerance")

        SV.apply_tax_expiry(expiring)
        for line, values, state, hold in plan:
            changed = SV.apply_line_values(line, values)
            if line["state"] != state or line["hold_reason"] != hold:
                line["state"] = state
                line["hold_reason"] = hold
                changed = True
            if changed:
                touch(line)
        batch["gross_commission_cents"] = gross
        batch["clawback_cents"] = clawback
        batch["network_fee_cents"] = fee
        batch["withholding_cents"] = withheld
        batch["net_payable_cents"] = net
        batch["statement_gross_cents"] = statement_gross
        batch["statement_fee_cents"] = statement_fee
        batch["network_fee_variance_cents"] = variance
        batch["network_fee_variance_bps"] = variance_bps
        batch["reconciliation_status"] = status
        batch["state"] = "VALIDATED"
        touch(batch)
        return respond(S.batch_out(batch))

    @app.post("/payout-batches/<bid>/approve")
    def approve_batch(bid):
        authorize([ROLE_FIN_CONTROLLER])
        batch = SV.find_batch(bid)
        payload = body()
        expected = get_int(payload, "expected_batch_version")
        check_sod(batch["prepared_by_user_id"],
                  "the preparer of the batch may not approve it")
        if batch["state"] in ("PAID", "VOIDED"):
            fail("ERR_BATCH_TERMINAL", "the batch is terminal")
        if batch["state"] != "VALIDATED":
            fail("ERR_BATCH_NOT_VALIDATED",
                 "only a VALIDATED batch may be approved")
        if expected != batch["version"]:
            fail("ERR_STALE_BATCH_VERSION",
                 "expected_batch_version does not match the batch version")
        if batch["net_payable_cents"] > calc.APPROVAL_LIMIT_CENTS:
            fail("ERR_APPROVAL_LIMIT_EXCEEDED",
                 "the batch exceeds the single-approval ceiling")
        for line in SV.lines_of_batch(batch["id"]):
            if line["state"] != "INCLUDED":
                continue
            affiliate = db.affiliates.get(line["affiliate_id"])
            if affiliate is None:
                continue
            amount = line["net_before_fees_cents"]
            affiliate["accrued_balance_cents"] -= amount
            affiliate["reserved_balance_cents"] += amount
            touch(affiliate)
        batch["state"] = "APPROVED"
        batch["approved_by_user_id"] = g.user_id
        touch(batch)
        return respond(S.batch_out(batch))

    @app.post("/payout-batches/<bid>/pay")
    def pay_batch(bid):
        authorize([ROLE_FIN_CONTROLLER])
        batch = SV.find_batch(bid)
        payload = body()
        reference = get_str(payload, "payment_reference", min_len=1, max_len=120)
        if batch["state"] in ("PAID", "VOIDED"):
            fail("ERR_BATCH_TERMINAL", "the batch is terminal")
        if batch["state"] != "APPROVED":
            fail("ERR_BATCH_NOT_VALIDATED", "only an APPROVED batch may be paid")
        for line in SV.lines_of_batch(batch["id"]):
            affiliate = db.affiliates.get(line["affiliate_id"])
            if line["state"] == "INCLUDED":
                line["state"] = "PAID"
                touch(line)
                if affiliate is not None:
                    SV.append_entry(
                        affiliate, "SETTLEMENT",
                        -line["net_before_fees_cents"],
                        payout_batch_id=batch["id"],
                        memo="payout settled for batch %s" % batch["id"],
                        affect_accrued=False)
                    affiliate["reserved_balance_cents"] -= \
                        line["net_before_fees_cents"]
                    affiliate["lifetime_paid_cents"] += line["net_cents"]
                    touch(affiliate)
            elif line["state"] in ("HELD_TAX_DOC", "HELD_FRAUD",
                                   "HELD_BELOW_MINIMUM"):
                SV.unstamp_entries(batch["id"], line["affiliate_id"])
        batch["state"] = "PAID"
        batch["payment_reference"] = reference
        touch(batch)
        return respond(S.batch_out(batch))

    @app.post("/payout-batches/<bid>/void")
    def void_batch(bid):
        authorize([ROLE_FIN_CONTROLLER])
        batch = SV.find_batch(bid)
        payload = body()
        reason = get_str(payload, "reason", min_len=1)
        if batch["state"] in ("PAID", "VOIDED"):
            fail("ERR_BATCH_TERMINAL", "the batch is terminal")
        was_approved = batch["state"] == "APPROVED"
        for line in SV.lines_of_batch(batch["id"]):
            if was_approved and line["state"] == "INCLUDED":
                affiliate = db.affiliates.get(line["affiliate_id"])
                if affiliate is not None:
                    amount = line["net_before_fees_cents"]
                    affiliate["reserved_balance_cents"] -= amount
                    affiliate["accrued_balance_cents"] += amount
                    touch(affiliate)
            if line["state"] != "VOIDED":
                line["state"] = "VOIDED"
                touch(line)
        SV.unstamp_entries(batch["id"])
        batch["state"] = "VOIDED"
        batch["void_reason"] = reason
        touch(batch)
        return respond(S.batch_out(batch))

    # -- Payout lines -------------------------------------------------------

    @app.get("/payout-lines/<lid>")
    def get_line(lid):
        authorize(FINANCE_READ + [ROLE_PARTNER])
        return respond(S.line_out(SV.find_line(lid)))

    @app.get("/payout-lines")
    def list_lines():
        role = authorize(FINANCE_READ + [ROLE_PARTNER])[1]
        rows = ordered(db.lines)
        if role == ROLE_PARTNER:
            rows = [r for r in rows if r["affiliate_id"] == g.user_id]
        rows = query_filter(rows, "payout_batch_id")
        rows = query_filter(rows, "affiliate_id")
        rows = query_filter(rows, "state")
        return paginate(rows, S.line_out)

    @app.post("/payout-lines/<lid>/release-hold")
    def release_hold(lid):
        authorize([ROLE_FIN_CONTROLLER])
        line = SV.find_line(lid)
        payload = body()
        get_str(payload, "reason", min_len=1)
        batch = db.batches.get(line["payout_batch_id"])
        held = ("HELD_TAX_DOC", "HELD_FRAUD", "HELD_BELOW_MINIMUM")
        if line["state"] not in held or batch is None \
                or batch["state"] not in ("DRAFT", "VALIDATED"):
            fail("ERR_LINE_NOT_HELD",
                 "only a held line on a DRAFT or VALIDATED batch is releasable")
        if line["state"] == "HELD_FRAUD":
            fail("ERR_FRAUD_HOLD_NOT_CLEARABLE",
                 "a fraud hold is not releasable through this channel")
        latest = SV.latest_tax_doc(line["affiliate_id"])
        valid = False
        if latest is not None and latest["status"] == "VALID":
            expires = parse_instant(latest["expires_on"])
            valid = expires is not None and expires > SV.now_dt()
        if not valid:
            fail("ERR_TAX_DOCUMENT_INVALID",
                 "releasing a hold requires a currently valid tax document")
        if line["state"] == "HELD_BELOW_MINIMUM":
            line["minimum_waived"] = True
        line["state"] = "INCLUDED"
        line["hold_reason"] = None
        line["released_by_user_id"] = g.user_id
        SV.apply_line_values(
            line, SV.compute_line_values(batch, line["affiliate_id"]))
        touch(line)
        SV.recompute_batch_totals(batch)
        return respond(S.line_out(line))

    # -- Test-only logical clock -------------------------------------------

    @app.post("/_clock/set_current_utc")
    def set_clock():
        authorize(ALL_STAFF + [ROLE_INGESTOR])
        payload = body()
        target = get_instant(payload, "to_iso8601")
        clock.current = target
        return respond({"current_utc": fmt_dt(target)})
