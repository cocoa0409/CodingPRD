"""Routes: open negotiations, IDR, appeals, feed batches, invoices, reports."""
from datetime import timedelta
from flask import request

import db
import errors
import util
import calendar as cal
import pricing
from middleware import require_roles
from response import success_object, success_list
import repricing_service as rs
from routes_claims import _settle_claim, _get_claim_or_404


def register(app):

    # --- open negotiations -----------------------------------------------------
    @app.route("/open-negotiations", methods=["POST"])
    def create_open_negotiation():
        require_roles("PayerRep", "ProviderRep")
        b = util.body()
        claim_id = util.req_str(b, "claim_id")
        initiated_by = util.req_enum(b, "initiated_by", {"PAYER", "PROVIDER"})
        c = db.claims.get(claim_id)
        if c is None:
            raise errors.not_found("Claim not found")
        now = db.now()
        expires = cal.add_business_days(now, 30)
        o = {
            "id": util.new_id(),
            "claim_id": claim_id,
            "initiated_by": initiated_by,
            "initiated_at": db.fmt(now),
            "_initiated_at_dt": now,
            "expires_at": db.fmt(expires),
            "_expires_at_dt": expires,
            "status": "ACTIVE",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.open_negotiations[o["id"]] = o
        return success_object(util.ser_open_negotiation(o), 201)

    @app.route("/open-negotiations/<oid>", methods=["GET"])
    def get_open_negotiation(oid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "IdrEntity")
        o = db.open_negotiations.get(oid)
        if o is None:
            raise errors.not_found("OpenNegotiation not found")
        return success_object(util.ser_open_negotiation(o))

    @app.route("/open-negotiations", methods=["GET"])
    def list_open_negotiations():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "IdrEntity")
        limit, offset = util.paginate_args()
        items = list(db.open_negotiations.values())
        cid = request.args.get("claim_id")
        st = request.args.get("status")
        if cid is not None:
            items = [o for o in items if o["claim_id"] == cid]
        if st is not None:
            items = [o for o in items if o["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_open_negotiation(o) for o in page],
                            limit, offset, total)

    @app.route("/open-negotiations/<oid>/agree", methods=["POST"])
    def agree_open_negotiation(oid):
        require_roles("PayerRep", "ProviderRep")
        o = db.open_negotiations.get(oid)
        if o is None:
            raise errors.not_found("OpenNegotiation not found")
        if o["status"] != "ACTIVE":
            raise errors.invalid_state("OpenNegotiation is not ACTIVE")
        b = util.body()
        amount = util.req_int(b, "agreed_amount_cents")
        claim = db.claims.get(o["claim_id"])
        billed = claim["billed_amount_cents"] if claim else 0
        if amount <= 0 or amount > billed:
            raise errors.offer_out_of_range()
        o["status"] = "AGREED"
        util.touch(o)
        if claim is not None:
            _settle_claim(claim, amount, extra_snapshot={
                "open_negotiation_id": o["id"],
            })
        return success_object(util.ser_open_negotiation(o))

    # --- IDR submissions --------------------------------------------------------
    @app.route("/idr-submissions", methods=["POST"])
    def create_idr():
        require_roles("PayerRep", "ProviderRep")
        b = util.body()
        claim_id = util.req_str(b, "claim_id")
        on_id = util.req_str(b, "open_negotiation_id")
        payer_offer = util.req_int(b, "payer_offer_cents")
        provider_offer = util.req_int(b, "provider_offer_cents")
        claim = db.claims.get(claim_id)
        if claim is None:
            raise errors.not_found("Claim not found")
        on = db.open_negotiations.get(on_id)
        if on is None:
            raise errors.not_found("OpenNegotiation not found")
        now = db.now()
        # temporal window: submission forbidden strictly before expires_at
        if now < on["_expires_at_dt"] or on["status"] != "EXPIRED":
            raise errors.open_negotiation_active()
        # QPA computation
        primary = None
        lines = rs.non_void_lines(claim_id)
        if lines:
            primary = lines[0]
        rates = []
        if primary is not None:
            for det in db.repricing_determinations.values():
                if det["methodology"] != "CONTRACTED_NETWORK":
                    continue
                snap = det.get("input_snapshot") or {}
                ag_id = snap.get("agreement_id") or det.get("agreement_id")
                if not ag_id:
                    continue
                ag = db.network_agreements.get(ag_id)
                if ag is None or ag["status"] != "ACTIVE":
                    continue
                for lsnap in snap.get("lines", []):
                    if lsnap.get("procedure_code") != primary["procedure_code"]:
                        continue
                    if lsnap.get("region_code") != primary["region_code"]:
                        continue
                    unit = lsnap.get("unit_charge_cents")
                    if unit is None:
                        continue
                    rate = pricing.round_half_up_cents(
                        unit * (1 - ag["discount_percent"]))
                    rates.append(rate)
        if not rates:
            raise errors.qpa_unavailable()
        rates.sort()
        n = len(rates)
        if n % 2 == 1:
            qpa = rates[n // 2]
        else:
            qpa = rates[n // 2 - 1]
        sub = {
            "id": util.new_id(),
            "claim_id": claim_id,
            "open_negotiation_id": on_id,
            "payer_offer_cents": payer_offer,
            "provider_offer_cents": provider_offer,
            "qpa_cents": qpa,
            "submitted_at": db.fmt(now),
            "_submitted_at_dt": now,
            "status": "SUBMITTED",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.idr_submissions[sub["id"]] = sub
        on["status"] = "SUPERSEDED_BY_IDR"
        util.touch(on)
        return success_object(util.ser_idr(sub), 201)

    @app.route("/idr-submissions/<iid>", methods=["GET"])
    def get_idr(iid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "IdrEntity")
        s = db.idr_submissions.get(iid)
        if s is None:
            raise errors.not_found("IdrSubmission not found")
        return success_object(util.ser_idr(s))

    @app.route("/idr-submissions", methods=["GET"])
    def list_idr():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "IdrEntity")
        limit, offset = util.paginate_args()
        items = list(db.idr_submissions.values())
        cid = request.args.get("claim_id")
        oid = request.args.get("open_negotiation_id")
        st = request.args.get("status")
        if cid is not None:
            items = [s for s in items if s["claim_id"] == cid]
        if oid is not None:
            items = [s for s in items if s["open_negotiation_id"] == oid]
        if st is not None:
            items = [s for s in items if s["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_idr(s) for s in page], limit, offset, total)

    @app.route("/idr-submissions/<iid>/decide", methods=["POST"])
    def decide_idr(iid):
        require_roles("IdrEntity")
        s = db.idr_submissions.get(iid)
        if s is None:
            raise errors.not_found("IdrSubmission not found")
        if s["status"] != "SUBMITTED":
            raise errors.invalid_state("IdrSubmission is not SUBMITTED")
        b = util.body()
        winner = util.req_enum(b, "winner", {"PAYER", "PROVIDER"})
        winning = util.req_int(b, "winning_amount_cents")
        if winner == "PAYER":
            if winning != s["payer_offer_cents"]:
                raise errors.idr_amount_mismatch()
            s["status"] = "DECIDED_PAYER"
        else:
            if winning != s["provider_offer_cents"]:
                raise errors.idr_amount_mismatch()
            s["status"] = "DECIDED_PROVIDER"
        util.touch(s)
        claim = db.claims.get(s["claim_id"])
        if claim is not None:
            _settle_claim(claim, winning, extra_snapshot={
                "idr_submission_id": s["id"],
            })
        return success_object(util.ser_idr(s))

    @app.route("/idr-submissions/<iid>/dismiss", methods=["POST"])
    def dismiss_idr(iid):
        require_roles("IdrEntity")
        s = db.idr_submissions.get(iid)
        if s is None:
            raise errors.not_found("IdrSubmission not found")
        if s["status"] != "SUBMITTED":
            raise errors.invalid_state("IdrSubmission is not SUBMITTED")
        s["status"] = "DISMISSED"
        util.touch(s)
        return success_object(util.ser_idr(s))

    # --- appeals ------------------------------------------------------------------
    @app.route("/claims/<cid>/appeals", methods=["POST"])
    def create_appeal(cid):
        require_roles("ProviderRep")
        c = _get_claim_or_404(cid)
        b = util.body()
        det_id = util.req_str(b, "determination_id")
        reason = util.req_str(b, "appeal_reason")
        det = db.repricing_determinations.get(det_id)
        if det is None:
            raise errors.not_found("RepricingDetermination not found")
        now = db.now()
        deadline = det["_created_at_dt"] + timedelta(days=45)
        if now > deadline:
            raise errors.appeal_window_closed()
        ap = {
            "id": util.new_id(),
            "claim_id": cid,
            "determination_id": det_id,
            "appeal_reason": reason,
            "appeal_window_deadline": db.fmt(deadline),
            "_appeal_window_deadline_dt": deadline,
            "status": "SUBMITTED",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.provider_appeals[ap["id"]] = ap
        return success_object(util.ser_appeal(ap), 201)

    @app.route("/appeals/<aid>", methods=["GET"])
    def get_appeal(aid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        ap = db.provider_appeals.get(aid)
        if ap is None:
            raise errors.not_found("ProviderAppeal not found")
        return success_object(util.ser_appeal(ap))

    @app.route("/appeals", methods=["GET"])
    def list_appeals():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        limit, offset = util.paginate_args()
        items = list(db.provider_appeals.values())
        cid = request.args.get("claim_id")
        did = request.args.get("determination_id")
        st = request.args.get("status")
        if cid is not None:
            items = [a for a in items if a["claim_id"] == cid]
        if did is not None:
            items = [a for a in items if a["determination_id"] == did]
        if st is not None:
            items = [a for a in items if a["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_appeal(a) for a in page], limit, offset, total)

    @app.route("/appeals/<aid>/start-review", methods=["POST"])
    def start_review(aid):
        require_roles("PayerRep")
        ap = db.provider_appeals.get(aid)
        if ap is None:
            raise errors.not_found("ProviderAppeal not found")
        if ap["status"] != "SUBMITTED":
            raise errors.invalid_state("Appeal is not SUBMITTED")
        ap["status"] = "UNDER_REVIEW"
        util.touch(ap)
        return success_object(util.ser_appeal(ap))

    @app.route("/appeals/<aid>/resolve", methods=["POST"])
    def resolve_appeal(aid):
        require_roles("PayerRep")
        ap = db.provider_appeals.get(aid)
        if ap is None:
            raise errors.not_found("ProviderAppeal not found")
        if ap["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Appeal is not UNDER_REVIEW")
        b = util.body()
        outcome = util.req_enum(b, "outcome", {"UPHELD", "ADJUSTED", "DENIED"})
        if outcome == "UPHELD":
            ap["status"] = "RE_REVIEWED_UPHELD"
            util.touch(ap)
        elif outcome == "DENIED":
            ap["status"] = "DENIED"
            util.touch(ap)
        else:
            amount = util.req_int(b, "adjusted_amount_cents")
            claim = db.claims.get(ap["claim_id"])
            billed = claim["billed_amount_cents"] if claim else 0
            if amount <= 0 or amount > billed:
                raise errors.offer_out_of_range()
            ap["status"] = "RE_REVIEWED_ADJUSTED"
            util.touch(ap)
            if claim is not None:
                appealed_det = db.repricing_determinations.get(ap["determination_id"])
                methodology = appealed_det["methodology"] if appealed_det else "NEGOTIATED"
                rs._settle_claim_to(claim, amount)
                # new determination supersedes current ACTIVE
                prior = None
                for d in db.repricing_determinations.values():
                    if d["claim_id"] == claim["id"] and d["status"] == "ACTIVE":
                        prior = d
                        break
                det = rs._new_determination(
                    claim["id"], methodology,
                    appealed_det["policy_id"] if appealed_det else None,
                    appealed_det["agreement_id"] if appealed_det else None,
                    prior["id"] if prior else None,
                    {
                        "methodology": methodology,
                        "appeal_id": ap["id"],
                        "adjusted_amount_cents": amount,
                    },
                    [{
                        "step": "appeal_adjustment",
                        "adjusted_amount_cents": amount,
                    }],
                    None)
                if prior is not None:
                    prior["status"] = "SUPERSEDED"
                    util.touch(prior)
                util.touch(claim)
        return success_object(util.ser_appeal(ap))

    # --- feed batches -------------------------------------------------------------
    TURNAROUND = {"CLAIM_INTAKE": 4, "REMITTANCE": 24, "ELIGIBILITY": 24}

    @app.route("/feed-batches", methods=["POST"])
    def create_feed_batch():
        require_roles("FeedOperator")
        b = util.body()
        payer_client_id = util.req_str(b, "payer_client_id")
        feed_type = util.req_enum(b, "feed_type",
                                  {"CLAIM_INTAKE", "REMITTANCE", "ELIGIBILITY"})
        record_count = util.req_int(b, "record_count")
        if payer_client_id not in db.payer_clients:
            raise errors.not_found("PayerClient not found")
        now = db.now()
        hours = TURNAROUND[feed_type]
        due = cal.add_business_hours(now, hours)
        f = {
            "id": util.new_id(),
            "payer_client_id": payer_client_id,
            "feed_type": feed_type,
            "record_count": record_count,
            "received_at": db.fmt(now),
            "_received_at_dt": now,
            "sla_due_at": db.fmt(due),
            "_sla_due_at_dt": due,
            "processed_at": None,
            "_processed_at_dt": None,
            "sla_met": None,
            "status": "RECEIVED",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.claim_feed_batches[f["id"]] = f
        return success_object(util.ser_feed_batch(f), 201)

    @app.route("/feed-batches/<fid>", methods=["GET"])
    def get_feed_batch(fid):
        require_roles("OpsAdmin", "PayerAdmin", "FeedOperator")
        f = db.claim_feed_batches.get(fid)
        if f is None:
            raise errors.not_found("ClaimFeedBatch not found")
        return success_object(util.ser_feed_batch(f))

    @app.route("/feed-batches", methods=["GET"])
    def list_feed_batches():
        require_roles("OpsAdmin", "PayerAdmin", "FeedOperator")
        limit, offset = util.paginate_args()
        items = list(db.claim_feed_batches.values())
        pcid = request.args.get("payer_client_id")
        ft = request.args.get("feed_type")
        st = request.args.get("status")
        sm = request.args.get("sla_met")
        if pcid is not None:
            items = [f for f in items if f["payer_client_id"] == pcid]
        if ft is not None:
            items = [f for f in items if f["feed_type"] == ft]
        if st is not None:
            items = [f for f in items if f["status"] == st]
        if sm is not None:
            want = sm.lower() in ("true", "1", "yes")
            items = [f for f in items if f["sla_met"] is want]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_feed_batch(f) for f in page],
                            limit, offset, total)

    @app.route("/feed-batches/<fid>/process", methods=["POST"])
    def process_feed_batch(fid):
        require_roles("FeedOperator")
        f = db.claim_feed_batches.get(fid)
        if f is None:
            raise errors.not_found("ClaimFeedBatch not found")
        if f["status"] != "RECEIVED":
            raise errors.invalid_state("ClaimFeedBatch is not RECEIVED")
        now = db.now()
        f["_processed_at_dt"] = now
        f["processed_at"] = db.fmt(now)
        f["sla_met"] = now <= f["_sla_due_at_dt"]
        f["status"] = "PROCESSED"
        util.touch(f)
        return success_object(util.ser_feed_batch(f))

    @app.route("/feed-batches/<fid>/fail", methods=["POST"])
    def fail_feed_batch(fid):
        require_roles("FeedOperator")
        f = db.claim_feed_batches.get(fid)
        if f is None:
            raise errors.not_found("ClaimFeedBatch not found")
        if f["status"] != "RECEIVED":
            raise errors.invalid_state("ClaimFeedBatch is not RECEIVED")
        f["status"] = "FAILED"
        util.touch(f)
        return success_object(util.ser_feed_batch(f))

    # --- fee invoices ----------------------------------------------------------------
    def _fiscal_guards(inv):
        """Validate claims FINALIZED and not already on another non-voided invoice."""
        claims = []
        for cid in inv["claim_ids"]:
            c = db.claims.get(cid)
            if c is None:
                raise errors.not_found("Claim not found")
            claims.append(c)
        for c in claims:
            if c["status"] != "FINALIZED":
                raise errors.claim_not_finalized()
        for other in db.fee_invoices.values():
            if other["id"] == inv["id"]:
                continue
            if other["status"] == "VOIDED":
                continue
            overlap = set(other["claim_ids"]) & set(inv["claim_ids"])
            if overlap:
                raise errors.claim_already_invoiced()
        return claims

    def _recompute_aggregate(payer_client_id):
        total = sum(f["gross_fee_cents"] for f in db.fee_invoices.values()
                    if f["payer_client_id"] == payer_client_id
                    and f["status"] != "VOIDED")
        for f in db.fee_invoices.values():
            if f["payer_client_id"] == payer_client_id and f["status"] != "VOIDED":
                f["aggregate_fee_cents"] = total

    @app.route("/fee-invoices", methods=["POST"])
    def create_invoice():
        require_roles("OpsAdmin")
        b = util.body()
        payer_client_id = util.req_str(b, "payer_client_id")
        claim_ids = b.get("claim_ids")
        if not isinstance(claim_ids, list) or not all(
                isinstance(x, str) for x in claim_ids):
            raise errors.invalid_request("claim_ids must be an array of strings")
        if payer_client_id not in db.payer_clients:
            raise errors.not_found("PayerClient not found")
        now = db.now()
        inv = {
            "id": util.new_id(),
            "payer_client_id": payer_client_id,
            "claim_ids": list(claim_ids),
            "gross_fee_cents": 0,
            "aggregate_fee_cents": 0,
            "transparency_report_id": None,
            "status": "DRAFT",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.fee_invoices[inv["id"]] = inv
        # fiscal guards also apply at creation
        _fiscal_guards(inv)
        return success_object(util.ser_fee_invoice(inv), 201)

    @app.route("/fee-invoices/<fid>", methods=["GET"])
    def get_invoice(fid):
        require_roles("OpsAdmin", "PayerAdmin")
        f = db.fee_invoices.get(fid)
        if f is None:
            raise errors.not_found("FeeInvoice not found")
        return success_object(util.ser_fee_invoice(f))

    @app.route("/fee-invoices", methods=["GET"])
    def list_invoices():
        require_roles("OpsAdmin", "PayerAdmin")
        limit, offset = util.paginate_args()
        items = list(db.fee_invoices.values())
        pcid = request.args.get("payer_client_id")
        st = request.args.get("status")
        trid = request.args.get("transparency_report_id")
        if pcid is not None:
            items = [f for f in items if f["payer_client_id"] == pcid]
        if st is not None:
            items = [f for f in items if f["status"] == st]
        if trid is not None:
            items = [f for f in items if f["transparency_report_id"] == trid]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_fee_invoice(f) for f in page],
                            limit, offset, total)

    @app.route("/fee-invoices/<fid>/issue", methods=["POST"])
    def issue_invoice(fid):
        require_roles("OpsAdmin")
        inv = db.fee_invoices.get(fid)
        if inv is None:
            raise errors.not_found("FeeInvoice not found")
        if inv["status"] != "DRAFT":
            raise errors.invalid_state("FeeInvoice is not DRAFT")
        claims = _fiscal_guards(inv)
        payer = db.payer_clients.get(inv["payer_client_id"])
        cap = payer["fee_cap_cents_per_claim"] if payer else 0
        gross = 0
        for c in claims:
            savings = c["savings_cents"] or 0
            gross += pricing.per_claim_fee(savings, cap)
        inv["gross_fee_cents"] = gross
        inv["status"] = "ISSUED"
        util.touch(inv)
        _recompute_aggregate(inv["payer_client_id"])
        # refresh own aggregate field after recompute
        return success_object(util.ser_fee_invoice(inv))

    @app.route("/fee-invoices/<fid>/void", methods=["POST"])
    def void_invoice(fid):
        require_roles("OpsAdmin")
        inv = db.fee_invoices.get(fid)
        if inv is None:
            raise errors.not_found("FeeInvoice not found")
        if inv["status"] != "ISSUED":
            raise errors.invalid_state("FeeInvoice is not ISSUED")
        inv["status"] = "VOIDED"
        util.touch(inv)
        _recompute_aggregate(inv["payer_client_id"])
        return success_object(util.ser_fee_invoice(inv))

    @app.route("/fee-invoices/<fid>/publish-transparency-report", methods=["POST"])
    def publish_report(fid):
        require_roles("OpsAdmin")
        inv = db.fee_invoices.get(fid)
        if inv is None:
            raise errors.not_found("FeeInvoice not found")
        payer = db.payer_clients.get(inv["payer_client_id"])
        enabled = payer["transparency_reporting_enabled"] if payer else False
        if not enabled or inv["status"] != "ISSUED":
            raise errors.transparency_not_enabled()
        claims = [db.claims.get(cid) for cid in inv["claim_ids"]]
        claims = [c for c in claims if c is not None]
        total_billed = sum(c["billed_amount_cents"] or 0 for c in claims)
        total_allowed = sum(c["allowed_amount_cents"] or 0 for c in claims)
        total_savings = sum(c["savings_cents"] or 0 for c in claims)
        now = db.now()
        t = {
            "id": util.new_id(),
            "fee_invoice_id": inv["id"],
            "total_billed_cents": total_billed,
            "total_allowed_cents": total_allowed,
            "total_savings_cents": total_savings,
            "total_fee_cents": inv["gross_fee_cents"],
            "status": "PUBLISHED",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.transparency_reports[t["id"]] = t
        inv["transparency_report_id"] = t["id"]
        util.touch(inv)
        return success_object(util.ser_transparency_report(t), 201)

    @app.route("/transparency-reports/<tid>", methods=["GET"])
    def get_report(tid):
        require_roles("OpsAdmin", "PayerAdmin")
        t = db.transparency_reports.get(tid)
        if t is None:
            raise errors.not_found("TransparencyReport not found")
        return success_object(util.ser_transparency_report(t))

    @app.route("/transparency-reports", methods=["GET"])
    def list_reports():
        require_roles("OpsAdmin", "PayerAdmin")
        limit, offset = util.paginate_args()
        items = list(db.transparency_reports.values())
        fid = request.args.get("fee_invoice_id")
        if fid is not None:
            items = [t for t in items if t["fee_invoice_id"] == fid]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_transparency_report(t) for t in page],
                            limit, offset, total)
