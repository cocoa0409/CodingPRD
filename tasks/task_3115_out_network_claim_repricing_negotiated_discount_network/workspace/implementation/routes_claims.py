"""Routes: claims, lines, reprice, determinations, negotiations, settlements."""
from flask import request

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list
import repricing_service as rs


CLAIM_TYPES = {"PROFESSIONAL", "FACILITY", "ANCILLARY", "EMERGENCY"}
NETWORK_STATUSES = {"IN_NETWORK", "OUT_OF_NETWORK", "EMERGENCY_OON"}


def _get_claim_or_404(cid):
    c = db.claims.get(cid)
    if c is None:
        raise errors.not_found("Claim not found")
    return c


def _settle_claim(claim, amount_cents, extra_snapshot=None):
    """Re-price claim to amount, supersede determination, move to SETTLED."""
    rs._settle_claim_to(claim, amount_cents)
    claim["methodology_used"] = "NEGOTIATED"
    rs.create_negotiated_determination(claim, extra_snapshot=extra_snapshot)
    if claim["status"] == "PRICED":
        claim["status"] = "SETTLED"
    util.touch(claim)


def register(app):

    # --- claims --------------------------------------------------------------
    @app.route("/claims", methods=["POST"])
    def create_claim():
        user_id, role = require_roles("PayerRep")
        b = util.body()
        payer_client_id = util.req_str(b, "payer_client_id")
        provider_id = util.req_str(b, "provider_id")
        ref = util.req_str(b, "external_claim_ref")
        claim_type = util.req_enum(b, "claim_type", CLAIM_TYPES)
        network_status = util.req_enum(b, "network_status", NETWORK_STATUSES)
        service_date = util.req_datetime(b, "service_date")
        prc = util.req_int(b, "patient_responsibility_cents")
        nsa = util.opt_bool(b, "nsa_flag")
        payer = db.payer_clients.get(payer_client_id)
        if payer is None:
            raise errors.not_found("PayerClient not found")
        if provider_id not in db.providers:
            raise errors.not_found("Provider not found")
        if payer["status"] != "ACTIVE":
            raise errors.payer_suspended()
        for c in db.claims.values():
            if c["payer_client_id"] == payer_client_id and \
                    c["external_claim_ref"] == ref:
                raise errors.duplicate_claim_ref()
        now = db.now()
        c = {
            "id": util.new_id(),
            "payer_client_id": payer_client_id,
            "provider_id": provider_id,
            "external_claim_ref": ref,
            "claim_type": claim_type,
            "network_status": network_status,
            "service_date": db.fmt(service_date),
            "_service_date_dt": service_date,
            "billed_amount_cents": 0,
            "patient_responsibility_cents": prc,
            "nsa_flag": nsa if nsa is not None else False,
            "methodology_used": None,
            "allowed_amount_cents": None,
            "payer_liability_cents": None,
            "savings_cents": None,
            "rbp_amount_cents": None,
            "status": "RECEIVED",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.claims[c["id"]] = c
        return success_object(util.ser_claim(c), 201)

    @app.route("/claims/<cid>", methods=["GET"])
    def get_claim(cid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "NetworkAdmin", "IdrEntity")
        c = _get_claim_or_404(cid)
        return success_object(util.ser_claim(c))

    @app.route("/claims", methods=["GET"])
    def list_claims():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        limit, offset = util.paginate_args()
        items = list(db.claims.values())
        pcid = request.args.get("payer_client_id")
        prid = request.args.get("provider_id")
        st = request.args.get("status")
        ns = request.args.get("network_status")
        if pcid is not None:
            items = [c for c in items if c["payer_client_id"] == pcid]
        if prid is not None:
            items = [c for c in items if c["provider_id"] == prid]
        if st is not None:
            items = [c for c in items if c["status"] == st]
        if ns is not None:
            items = [c for c in items if c["network_status"] == ns]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_claim(c) for c in page], limit, offset, total)

    @app.route("/claims/<cid>/lines", methods=["POST"])
    def add_line(cid):
        user_id, role = require_roles("PayerRep")
        c = _get_claim_or_404(cid)
        payer = db.payer_clients.get(c["payer_client_id"])
        if payer is not None and payer["status"] != "ACTIVE":
            raise errors.payer_suspended()
        if c["status"] not in ("RECEIVED", "PENDING_LINES"):
            raise errors.invalid_state("Claim state does not permit adding lines")
        b = util.body()
        procedure_code = util.req_str(b, "procedure_code")
        quantity_units = util.req_int(b, "quantity_units")
        unit_charge_cents = util.req_int(b, "unit_charge_cents")
        region_code = util.req_str(b, "region_code")
        if quantity_units < 1:
            raise errors.invalid_request("quantity_units must be >= 1")
        if unit_charge_cents <= 0:
            raise errors.invalid_request("unit_charge_cents must be > 0")
        now = db.now()
        line = {
            "id": util.new_id(),
            "claim_id": cid,
            "procedure_code": procedure_code,
            "quantity_units": quantity_units,
            "unit_charge_cents": unit_charge_cents,
            "region_code": region_code,
            "allowed_amount_cents": None,
            "status": "PENDING",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.claim_lines[line["id"]] = line
        rs.recompute_billed(c)
        if c["status"] == "RECEIVED":
            c["status"] = "PENDING_LINES"
        util.touch(c)
        return success_object(util.ser_claim_line(line), 201)

    @app.route("/claims/<cid>/lines", methods=["GET"])
    def list_lines(cid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        _get_claim_or_404(cid)
        limit, offset = util.paginate_args()
        items = [l for l in db.claim_lines.values() if l["claim_id"] == cid]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_claim_line(l) for l in page],
                            limit, offset, total)

    @app.route("/claims/<cid>/reprice", methods=["POST"])
    def reprice(cid):
        user_id, role = require_roles("PayerRep")
        c = _get_claim_or_404(cid)
        payer = db.payer_clients.get(c["payer_client_id"])
        if payer is not None and payer["status"] != "ACTIVE":
            raise errors.payer_suspended()
        if c["status"] != "PENDING_LINES":
            raise errors.invalid_state("Claim is not PENDING_LINES")
        b = util.body()
        notes = util.opt_str(b, "defensibility_notes")
        # Business validations first (pure, no mutation)...
        plan = rs._plan_reprice(c)
        # ...then OCC (last priority)...
        expected = b.get("expected_claim_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise errors.invalid_request("Invalid expected_claim_version")
            if expected != c["version"]:
                raise errors.stale_version()
        # ...then commit.
        det = rs._commit_reprice(c, plan, notes)
        return success_object(util.ser_determination(det))

    @app.route("/claims/<cid>/determinations", methods=["GET"])
    def list_claim_determinations(cid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        _get_claim_or_404(cid)
        limit, offset = util.paginate_args()
        items = [d for d in db.repricing_determinations.values()
                 if d["claim_id"] == cid]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_determination(d) for d in page],
                            limit, offset, total)

    @app.route("/repricing-determinations/<did>", methods=["GET"])
    def get_determination(did):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        d = db.repricing_determinations.get(did)
        if d is None:
            raise errors.not_found("RepricingDetermination not found")
        return success_object(util.ser_determination(d))

    @app.route("/repricing-determinations", methods=["GET"])
    def list_determinations():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        limit, offset = util.paginate_args()
        items = list(db.repricing_determinations.values())
        pid = request.args.get("policy_id")
        aid = request.args.get("agreement_id")
        sid = request.args.get("supersedes_determination_id")
        st = request.args.get("status")
        if pid is not None:
            items = [d for d in items if d["policy_id"] == pid]
        if aid is not None:
            items = [d for d in items if d["agreement_id"] == aid]
        if sid is not None:
            items = [d for d in items if d["supersedes_determination_id"] == sid]
        if st is not None:
            items = [d for d in items if d["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_determination(d) for d in page],
                            limit, offset, total)

    @app.route("/claims/<cid>/finalize", methods=["POST"])
    def finalize_claim(cid):
        require_roles("PayerRep")
        c = _get_claim_or_404(cid)
        if c["status"] not in ("PRICED", "SETTLED"):
            raise errors.invalid_state("Claim is not PRICED or SETTLED")
        for ap in db.provider_appeals.values():
            if ap["claim_id"] == cid and ap["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                raise errors.appeal_in_progress()
        c["status"] = "FINALIZED"
        util.touch(c)
        return success_object(util.ser_claim(c))

    # --- negotiation cases ----------------------------------------------------
    NONTERMINAL_CASE = ("OPEN", "OFFER_PENDING", "COUNTERED", "ACCEPTED")

    @app.route("/negotiation-cases", methods=["POST"])
    def create_case():
        user_id, role = require_roles("PayerRep", "ProviderRep")
        b = util.body()
        claim_id = util.req_str(b, "claim_id")
        c = db.claims.get(claim_id)
        if c is None:
            raise errors.not_found("Claim not found")
        if c["status"] not in ("PRICED", "PENDING_LINES"):
            raise errors.invalid_state(
                "Claim must be PRICED or PENDING_LINES to open a negotiation")
        for n in db.negotiation_cases.values():
            if n["claim_id"] == claim_id and n["status"] in NONTERMINAL_CASE:
                raise errors.case_already_open()
        now = db.now()
        n = {
            "id": util.new_id(),
            "claim_id": claim_id,
            "opened_by_role": role,
            "round_count": 0,
            "current_offer_cents": None,
            "status": "OPEN",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.negotiation_cases[n["id"]] = n
        return success_object(util.ser_negotiation_case(n), 201)

    @app.route("/negotiation-cases/<nid>", methods=["GET"])
    def get_case(nid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        n = db.negotiation_cases.get(nid)
        if n is None:
            raise errors.not_found("NegotiationCase not found")
        return success_object(util.ser_negotiation_case(n))

    @app.route("/negotiation-cases", methods=["GET"])
    def list_cases():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        limit, offset = util.paginate_args()
        items = list(db.negotiation_cases.values())
        cid = request.args.get("claim_id")
        st = request.args.get("status")
        if cid is not None:
            items = [n for n in items if n["claim_id"] == cid]
        if st is not None:
            items = [n for n in items if n["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_negotiation_case(n) for n in page],
                            limit, offset, total)

    def _get_case_or_404(nid):
        n = db.negotiation_cases.get(nid)
        if n is None:
            raise errors.not_found("NegotiationCase not found")
        return n

    @app.route("/negotiation-cases/<nid>/offer", methods=["POST"])
    def offer(nid):
        require_roles("PayerRep")
        n = _get_case_or_404(nid)
        if n["status"] not in ("OPEN", "COUNTERED"):
            raise errors.invalid_state("Case state does not permit an offer")
        b = util.body()
        offer_cents = util.req_int(b, "offer_cents")
        claim = db.claims.get(n["claim_id"])
        billed = claim["billed_amount_cents"] if claim else 0
        if offer_cents <= 0 or offer_cents > billed:
            raise errors.offer_out_of_range()
        # OCC last
        expected = b.get("expected_case_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise errors.invalid_request("Invalid expected_case_version")
            if expected != n["version"]:
                raise errors.stale_version()
        n["current_offer_cents"] = offer_cents
        n["status"] = "OFFER_PENDING"
        util.touch(n)
        return success_object(util.ser_negotiation_case(n))

    @app.route("/negotiation-cases/<nid>/counter", methods=["POST"])
    def counter(nid):
        require_roles("ProviderRep")
        n = _get_case_or_404(nid)
        if n["status"] != "OFFER_PENDING":
            raise errors.invalid_state("Case state does not permit a counter")
        b = util.body()
        counter_cents = util.req_int(b, "counter_cents")
        claim = db.claims.get(n["claim_id"])
        billed = claim["billed_amount_cents"] if claim else 0
        if counter_cents < (n["current_offer_cents"] or 0):
            raise errors.counter_below_offer()
        if counter_cents > billed:
            raise errors.offer_out_of_range()
        n["current_offer_cents"] = counter_cents
        n["round_count"] = n["round_count"] + 1
        if n["round_count"] >= 5:
            n["status"] = "EXPIRED"
        else:
            n["status"] = "COUNTERED"
        util.touch(n)
        return success_object(util.ser_negotiation_case(n))

    @app.route("/negotiation-cases/<nid>/accept", methods=["POST"])
    def accept(nid):
        user_id, role = require_roles("PayerRep", "ProviderRep")
        n = _get_case_or_404(nid)
        if n["status"] == "OFFER_PENDING":
            if role != "ProviderRep":
                raise errors.forbidden()
        elif n["status"] == "COUNTERED":
            if role != "PayerRep":
                raise errors.forbidden()
        else:
            raise errors.invalid_state("Case state does not permit acceptance")
        n["status"] = "ACCEPTED"
        util.touch(n)
        now = db.now()
        s = {
            "id": util.new_id(),
            "negotiation_case_id": n["id"],
            "claim_id": n["claim_id"],
            "settled_amount_cents": n["current_offer_cents"],
            "payer_signed_at": None,
            "provider_signed_at": None,
            "_payer_signed_at_dt": None,
            "_provider_signed_at_dt": None,
            "balance_billing_prohibited": True,
            "status": "PENDING_SIGNATURES",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.settlement_agreements[s["id"]] = s
        return success_object(util.ser_negotiation_case(n))

    @app.route("/negotiation-cases/<nid>/withdraw", methods=["POST"])
    def withdraw(nid):
        require_roles("PayerRep", "ProviderRep")
        n = _get_case_or_404(nid)
        if n["status"] not in ("OPEN", "OFFER_PENDING", "COUNTERED"):
            raise errors.invalid_state("Case state does not permit withdrawal")
        n["status"] = "WITHDRAWN"
        util.touch(n)
        return success_object(util.ser_negotiation_case(n))

    # --- settlement agreements -------------------------------------------------
    @app.route("/settlement-agreements/<sid>", methods=["GET"])
    def get_settlement(sid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        s = db.settlement_agreements.get(sid)
        if s is None:
            raise errors.not_found("SettlementAgreement not found")
        return success_object(util.ser_settlement(s))

    @app.route("/settlement-agreements", methods=["GET"])
    def list_settlements():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep")
        limit, offset = util.paginate_args()
        items = list(db.settlement_agreements.values())
        cid = request.args.get("claim_id")
        nid = request.args.get("negotiation_case_id")
        st = request.args.get("status")
        if cid is not None:
            items = [s for s in items if s["claim_id"] == cid]
        if nid is not None:
            items = [s for s in items if s["negotiation_case_id"] == nid]
        if st is not None:
            items = [s for s in items if s["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_settlement(s) for s in page],
                            limit, offset, total)

    @app.route("/settlement-agreements/<sid>/sign", methods=["POST"])
    def sign_settlement(sid):
        user_id, role = require_roles("PayerRep", "ProviderRep")
        s = db.settlement_agreements.get(sid)
        if s is None:
            raise errors.not_found("SettlementAgreement not found")
        if s["status"] != "PENDING_SIGNATURES":
            raise errors.invalid_state("Settlement is not PENDING_SIGNATURES")
        now = db.now()
        if role == "PayerRep":
            if s["_payer_signed_at_dt"] is not None:
                raise errors.already_signed()
            s["_payer_signed_at_dt"] = now
            s["payer_signed_at"] = db.fmt(now)
        else:
            if s["_provider_signed_at_dt"] is not None:
                raise errors.already_signed()
            s["_provider_signed_at_dt"] = now
            s["provider_signed_at"] = db.fmt(now)
        util.touch(s)
        # second signature executes
        if s["_payer_signed_at_dt"] is not None and \
                s["_provider_signed_at_dt"] is not None:
            claim = db.claims.get(s["claim_id"])
            if claim is not None and claim["status"] == "FINALIZED":
                raise errors.invalid_state("Claim already FINALIZED")
            s["status"] = "EXECUTED"
            s["balance_billing_prohibited"] = True
            util.touch(s)
            if claim is not None:
                _settle_claim(claim, s["settled_amount_cents"],
                              extra_snapshot={
                                  "settlement_agreement_id": s["id"],
                                  "negotiation_case_id": s["negotiation_case_id"],
                              })
            n = db.negotiation_cases.get(s["negotiation_case_id"])
            if n is not None and n["status"] == "ACCEPTED":
                n["status"] = "SETTLED"
                util.touch(n)
        return success_object(util.ser_settlement(s))

    @app.route("/settlement-agreements/<sid>/void", methods=["POST"])
    def void_settlement(sid):
        require_roles("PayerRep")
        s = db.settlement_agreements.get(sid)
        if s is None:
            raise errors.not_found("SettlementAgreement not found")
        if s["status"] != "PENDING_SIGNATURES":
            raise errors.invalid_state("Settlement is not PENDING_SIGNATURES")
        if s["_payer_signed_at_dt"] is not None or \
                s["_provider_signed_at_dt"] is not None:
            raise errors.already_signed()
        s["status"] = "VOIDED"
        util.touch(s)
        n = db.negotiation_cases.get(s["negotiation_case_id"])
        if n is not None and n["status"] == "ACCEPTED":
            n["status"] = "COUNTERED"
            util.touch(n)
        return success_object(util.ser_settlement(s))
