"""Routes: clock, payer clients, policies, providers, agreements, rate tables."""
from flask import request

import db
import errors
import util
import calendar as cal
from middleware import get_auth, require_roles
from response import success_object, success_list


ALL_ROLES = ("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
             "NetworkAdmin", "FeedOperator", "IdrEntity")


def register(app):

    # --- logical clock ------------------------------------------------------
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        require_roles("OpsAdmin", "FeedOperator")
        b = util.body()
        dt = util.req_datetime(b, "current_utc")
        db.set_now(dt)
        # side effect: expire open negotiations whose expires_at reached
        for on in db.open_negotiations.values():
            if on["status"] == "ACTIVE" and dt >= on["_expires_at_dt"]:
                on["status"] = "EXPIRED"
                util.touch(on)
        return success_object({"current_utc": db.fmt(dt)})

    # --- payer clients ------------------------------------------------------
    @app.route("/payer-clients", methods=["POST"])
    def create_payer():
        require_roles("OpsAdmin")
        b = util.body()
        name = util.req_str(b, "payer_name")
        fee_percent = util.req_num(b, "fee_percent")
        fee_cap = util.req_int(b, "fee_cap_cents_per_claim")
        min_inv = util.opt_int(b, "minimum_invoice_cents")
        trans = util.opt_bool(b, "transparency_reporting_enabled")
        now = db.now()
        p = {
            "id": util.new_id(),
            "payer_name": name,
            "status": "ACTIVE",
            "fee_percent": fee_percent,
            "fee_cap_cents_per_claim": fee_cap,
            "minimum_invoice_cents": min_inv if min_inv is not None else 0,
            "transparency_reporting_enabled": trans if trans is not None else False,
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.payer_clients[p["id"]] = p
        return success_object(util.ser_payer_client(p), 201)

    @app.route("/payer-clients/<pid>", methods=["GET"])
    def get_payer(pid):
        require_roles(*ALL_ROLES)
        p = db.payer_clients.get(pid)
        if p is None:
            raise errors.not_found("PayerClient not found")
        return success_object(util.ser_payer_client(p))

    @app.route("/payer-clients", methods=["GET"])
    def list_payers():
        require_roles("OpsAdmin", "PayerAdmin")
        limit, offset = util.paginate_args()
        items = list(db.payer_clients.values())
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_payer_client(p) for p in page],
                            limit, offset, total)

    @app.route("/payer-clients/<pid>/suspend", methods=["POST"])
    def suspend_payer(pid):
        require_roles("OpsAdmin")
        p = db.payer_clients.get(pid)
        if p is None:
            raise errors.not_found("PayerClient not found")
        if p["status"] != "ACTIVE":
            raise errors.invalid_state("PayerClient is not ACTIVE")
        p["status"] = "SUSPENDED"
        util.touch(p)
        return success_object(util.ser_payer_client(p))

    @app.route("/payer-clients/<pid>/reinstate", methods=["POST"])
    def reinstate_payer(pid):
        require_roles("OpsAdmin")
        p = db.payer_clients.get(pid)
        if p is None:
            raise errors.not_found("PayerClient not found")
        if p["status"] != "SUSPENDED":
            raise errors.invalid_state("PayerClient is not SUSPENDED")
        p["status"] = "ACTIVE"
        util.touch(p)
        return success_object(util.ser_payer_client(p))

    # --- repricing policies --------------------------------------------------
    @app.route("/repricing-policies", methods=["POST"])
    def create_policy():
        require_roles("PayerAdmin")
        b = util.body()
        payer_client_id = util.req_str(b, "payer_client_id")
        claim_type = util.req_enum(b, "claim_type",
                                   {"PROFESSIONAL", "FACILITY", "ANCILLARY", "EMERGENCY"})
        network_status = util.req_enum(
            b, "network_status",
            {"IN_NETWORK", "OUT_OF_NETWORK", "EMERGENCY_OON"})
        methodology = util.req_enum(
            b, "methodology",
            {"CONTRACTED_NETWORK", "REFERENCE_BASED", "PERCENT_OF_MEDICARE",
             "UCR", "NEGOTIATION_REQUIRED"})
        pct = util.opt_num(b, "percent_of_medicare")
        rbp = util.opt_num(b, "rbp_markup_percent")
        ucrp = util.opt_int(b, "ucr_percentile")
        priority = util.req_int(b, "priority")
        if payer_client_id not in db.payer_clients:
            raise errors.not_found("PayerClient not found")
        now = db.now()
        p = {
            "id": util.new_id(),
            "payer_client_id": payer_client_id,
            "claim_type": claim_type,
            "network_status": network_status,
            "methodology": methodology,
            "percent_of_medicare": pct,
            "rbp_markup_percent": rbp,
            "ucr_percentile": ucrp,
            "priority": priority,
            "status": "ACTIVE",
            "rounding_order": "PER_LINE_THEN_SUM",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.repricing_policies[p["id"]] = p
        return success_object(util.ser_policy(p), 201)

    @app.route("/repricing-policies/<pid>", methods=["GET"])
    def get_policy(pid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep")
        p = db.repricing_policies.get(pid)
        if p is None:
            raise errors.not_found("RepricingPolicy not found")
        return success_object(util.ser_policy(p))

    @app.route("/repricing-policies", methods=["GET"])
    def list_policies():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep")
        limit, offset = util.paginate_args()
        items = list(db.repricing_policies.values())
        pcid = request.args.get("payer_client_id")
        meth = request.args.get("methodology")
        st = request.args.get("status")
        if pcid is not None:
            items = [p for p in items if p["payer_client_id"] == pcid]
        if meth is not None:
            items = [p for p in items if p["methodology"] == meth]
        if st is not None:
            items = [p for p in items if p["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_policy(p) for p in page], limit, offset, total)

    @app.route("/repricing-policies/<pid>/retire", methods=["POST"])
    def retire_policy(pid):
        require_roles("PayerAdmin")
        p = db.repricing_policies.get(pid)
        if p is None:
            raise errors.not_found("RepricingPolicy not found")
        if p["status"] != "ACTIVE":
            raise errors.invalid_state("RepricingPolicy is not ACTIVE")
        p["status"] = "RETIRED"
        util.touch(p)
        return success_object(util.ser_policy(p))

    # --- providers -----------------------------------------------------------
    @app.route("/providers", methods=["POST"])
    def create_provider():
        require_roles("NetworkAdmin")
        b = util.body()
        npi = util.req_str(b, "npi")
        legal_name = util.req_str(b, "legal_name")
        tin = util.req_str(b, "tin")
        for pr in db.providers.values():
            if pr["npi"] == npi:
                raise errors.duplicate_npi()
        now = db.now()
        p = {
            "id": util.new_id(),
            "npi": npi,
            "legal_name": legal_name,
            "tin": tin,
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.providers[p["id"]] = p
        return success_object(util.ser_provider(p), 201)

    @app.route("/providers/<pid>", methods=["GET"])
    def get_provider(pid):
        require_roles(*ALL_ROLES)
        p = db.providers.get(pid)
        if p is None:
            raise errors.not_found("Provider not found")
        return success_object(util.ser_provider(p))

    @app.route("/providers", methods=["GET"])
    def list_providers():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "NetworkAdmin")
        limit, offset = util.paginate_args()
        items = list(db.providers.values())
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_provider(p) for p in page], limit, offset, total)

    # --- network agreements --------------------------------------------------
    @app.route("/network-agreements", methods=["POST"])
    def create_agreement():
        require_roles("NetworkAdmin")
        b = util.body()
        network_name = util.req_str(b, "network_name")
        provider_id = util.req_str(b, "provider_id")
        discount = util.req_num(b, "discount_percent")
        start = util.req_datetime(b, "effective_start")
        end = util.req_datetime(b, "effective_end")
        if provider_id not in db.providers:
            raise errors.not_found("Provider not found")
        if not (end > start):
            raise errors.invalid_request(
                "effective_end must be strictly after effective_start")
        # overlap detection: half-open [start, end) among ACTIVE/SUSPENDED
        for a in db.network_agreements.values():
            if a["provider_id"] != provider_id:
                continue
            if a["status"] not in ("ACTIVE", "SUSPENDED"):
                continue
            if start < a["_effective_end_dt"] and a["_effective_start_dt"] < end:
                raise errors.agreement_overlap()
        now = db.now()
        ag = {
            "id": util.new_id(),
            "network_name": network_name,
            "provider_id": provider_id,
            "discount_percent": discount,
            "effective_start": db.fmt(start),
            "effective_end": db.fmt(end),
            "_effective_start_dt": start,
            "_effective_end_dt": end,
            "balance_billing_prohibited": True,
            "status": "ACTIVE",
            "version": 1,
            "_seq": db.next_seq(),
            "_created_at_dt": now,
            "_updated_at_dt": now,
        }
        db.network_agreements[ag["id"]] = ag
        return success_object(util.ser_agreement(ag), 201)

    @app.route("/network-agreements/<aid>", methods=["GET"])
    def get_agreement(aid):
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "NetworkAdmin")
        a = db.network_agreements.get(aid)
        if a is None:
            raise errors.not_found("NetworkAgreement not found")
        return success_object(util.ser_agreement(a))

    @app.route("/network-agreements", methods=["GET"])
    def list_agreements():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "ProviderRep",
                      "NetworkAdmin")
        limit, offset = util.paginate_args()
        items = list(db.network_agreements.values())
        pid = request.args.get("provider_id")
        st = request.args.get("status")
        if pid is not None:
            items = [a for a in items if a["provider_id"] == pid]
        if st is not None:
            items = [a for a in items if a["status"] == st]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_agreement(a) for a in page], limit, offset, total)

    @app.route("/network-agreements/<aid>/suspend", methods=["POST"])
    def suspend_agreement(aid):
        require_roles("NetworkAdmin")
        a = db.network_agreements.get(aid)
        if a is None:
            raise errors.not_found("NetworkAgreement not found")
        if a["status"] != "ACTIVE":
            raise errors.invalid_state("NetworkAgreement is not ACTIVE")
        a["status"] = "SUSPENDED"
        util.touch(a)
        return success_object(util.ser_agreement(a))

    @app.route("/network-agreements/<aid>/reinstate", methods=["POST"])
    def reinstate_agreement(aid):
        require_roles("NetworkAdmin")
        a = db.network_agreements.get(aid)
        if a is None:
            raise errors.not_found("NetworkAgreement not found")
        if a["status"] != "SUSPENDED":
            raise errors.invalid_state("NetworkAgreement is not SUSPENDED")
        a["status"] = "ACTIVE"
        util.touch(a)
        return success_object(util.ser_agreement(a))

    @app.route("/network-agreements/<aid>/terminate", methods=["POST"])
    def terminate_agreement(aid):
        require_roles("NetworkAdmin")
        a = db.network_agreements.get(aid)
        if a is None:
            raise errors.not_found("NetworkAgreement not found")
        if a["status"] not in ("ACTIVE", "SUSPENDED"):
            raise errors.invalid_state("NetworkAgreement cannot be terminated")
        a["status"] = "TERMINATED"
        util.touch(a)
        return success_object(util.ser_agreement(a))

    # --- rate tables ---------------------------------------------------------
    @app.route("/medicare-fee-schedule", methods=["POST"])
    def create_medicare():
        require_roles("NetworkAdmin")
        b = util.body()
        procedure_code = util.req_str(b, "procedure_code")
        region_code = util.req_str(b, "region_code")
        base_rate_cents = util.req_int(b, "base_rate_cents")
        gaf = util.req_num(b, "geographic_adjustment_factor")
        effective_year = util.req_int(b, "effective_year")
        m = {
            "id": util.new_id(),
            "procedure_code": procedure_code,
            "region_code": region_code,
            "base_rate_cents": base_rate_cents,
            "geographic_adjustment_factor": gaf,
            "effective_year": effective_year,
            "_created_at_dt": db.now(),
        }
        db.medicare_fee_schedule[m["id"]] = m
        return success_object(util.ser_medicare(m), 201)

    @app.route("/medicare-fee-schedule", methods=["GET"])
    def list_medicare():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "NetworkAdmin")
        limit, offset = util.paginate_args()
        items = list(db.medicare_fee_schedule.values())
        pc = request.args.get("procedure_code")
        rc = request.args.get("region_code")
        if pc is not None:
            items = [m for m in items if m["procedure_code"] == pc]
        if rc is not None:
            items = [m for m in items if m["region_code"] == rc]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_medicare(m) for m in page], limit, offset, total)

    @app.route("/ucr-rates", methods=["POST"])
    def create_ucr():
        require_roles("NetworkAdmin")
        b = util.body()
        procedure_code = util.req_str(b, "procedure_code")
        region_code = util.req_str(b, "region_code")
        p50 = util.req_int(b, "percentile_50_cents")
        p80 = util.req_int(b, "percentile_80_cents")
        u = {
            "id": util.new_id(),
            "procedure_code": procedure_code,
            "region_code": region_code,
            "percentile_50_cents": p50,
            "percentile_80_cents": p80,
            "_created_at_dt": db.now(),
        }
        db.ucr_rates[u["id"]] = u
        return success_object(util.ser_ucr(u), 201)

    @app.route("/ucr-rates", methods=["GET"])
    def list_ucr():
        require_roles("OpsAdmin", "PayerAdmin", "PayerRep", "NetworkAdmin")
        limit, offset = util.paginate_args()
        items = list(db.ucr_rates.values())
        pc = request.args.get("procedure_code")
        rc = request.args.get("region_code")
        if pc is not None:
            items = [u for u in items if u["procedure_code"] == pc]
        if rc is not None:
            items = [u for u in items if u["region_code"] == rc]
        page, total = util.sort_and_page(items, limit, offset)
        return success_list([util.ser_ucr(u) for u in page], limit, offset, total)
