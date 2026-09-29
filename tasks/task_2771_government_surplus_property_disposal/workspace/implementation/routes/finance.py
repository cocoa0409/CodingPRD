"""Proceeds distribution and the agency proceeds ledger (PRD section 3.9)."""
import db as store
from db import db, by_created
from errors import ApiError
from middleware import (Fields, endpoint, list_params, plain_filters,
                        read_body)
from response import collection, created, ok
from services import calc, rollups
from services.enums import DISTRIBUTION_BASIS, DISTRIBUTION_STATUS
from services.serialize import view, views


def register(app):

    @app.route("/proceeds-distributions", methods=["POST"])
    @endpoint(["FinanceController"])
    def create_distribution(ctx):
        body = read_body()
        f = Fields(body)
        f.string("auction_lot_id", required=True, minlen=1)
        f.enum("basis", DISTRIBUTION_BASIS, required=True)
        f.integer("expected_auction_lot_version", required=True)
        f.done()
        lot = rollups.fetch(db.lots, f["auction_lot_id"], "ERR_AUCTION_LOT_NOT_FOUND")
        if f["expected_auction_lot_version"] != lot["version"]:
            raise ApiError("ERR_STALE_LOT_VERSION",
                           "expected_auction_lot_version does not match the lot's "
                           "current version")
        basis = f["basis"]
        invoice = rollups.live_invoice_of_lot(lot["id"])
        settled = lot["status"] in ("CLOSED_MET", "SETTLED")
        if basis == "ACCRUAL":
            available = settled
        else:
            available = (settled and invoice is not None
                         and invoice["status"] in ("PAID", "DEFAULTED"))
        if not available:
            raise ApiError("ERR_DISTRIBUTION_BASIS_UNAVAILABLE",
                           "the requested basis is not available for this lot")
        siblings = rollups.distributions_of_lot(lot["id"])
        for row in siblings:
            if row["status"] == "POSTED":
                raise ApiError("ERR_DISTRIBUTION_ALREADY_POSTED",
                               "a distribution for this lot has already been posted")
        asset = db.assets.get(lot["asset_id"])
        beneficiary_id = None
        if asset is not None:
            turn_in = db.turn_ins.get(asset["turn_in_id"])
            if turn_in is not None:
                beneficiary_id = turn_in["turning_in_agency_id"]
        if basis == "ACCRUAL":
            base = lot["high_bid_cents"]
        else:
            base = invoice["amount_paid_cents"]
        fee = calc.service_fee(base)
        recovery = calc.cost_recovery(asset["id"]) if asset is not None else 0
        net = calc.distribution_net(base, fee, recovery)
        # A newer draft supersedes any live one for the same lot.
        for row in siblings:
            if row["status"] == "CALCULATED":
                row["status"] = "SUPERSEDED"
                ctx.touch(row)
        dist = store.base_row()
        dist.update({
            "auction_lot_id": lot["id"],
            "beneficiary_agency_id": beneficiary_id,
            "basis": basis,
            "distributable_base_cents": base,
            "service_fee_cents": fee,
            "cost_recovery_cents": recovery,
            "net_to_agency_cents": net,
            "status": "CALCULATED",
            "posted_by_user_id": None,
            "posted_at": None,
            "reversal_reason": None,
        })
        db.distributions[dist["id"]] = dist
        # The calculation reads the lot, so the lot's version advances.
        ctx.touch(lot)
        return created(view("ProceedsDistribution", dist))

    @app.route("/proceeds-distributions/<dist_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "FinanceController", "AgencyOfficer"])
    def get_distribution(ctx, dist_id):
        dist = rollups.fetch(db.distributions, dist_id, "ERR_DISTRIBUTION_NOT_FOUND")
        return ok(view("ProceedsDistribution", dist))

    @app.route("/proceeds-distributions", methods=["GET"])
    @endpoint(["ProgramAdmin", "FinanceController", "AgencyOfficer"])
    def list_distributions(ctx):
        filters, limit, offset = list_params({"basis": DISTRIBUTION_BASIS,
                                              "status": DISTRIBUTION_STATUS})
        plain = plain_filters(["auction_lot_id", "beneficiary_agency_id"])
        rows = by_created(db.distributions.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("ProceedsDistribution", rows), limit, offset)

    @app.route("/proceeds-distributions/<dist_id>/post", methods=["POST"])
    @endpoint(["FinanceController"])
    def post_distribution(ctx, dist_id):
        dist = rollups.fetch(db.distributions, dist_id, "ERR_DISTRIBUTION_NOT_FOUND")
        lot = db.lots.get(dist["auction_lot_id"])
        # Segregation of duties is checked ahead of the state precondition.
        if lot is not None and lot["closed_by_user_id"] is not None \
                and lot["closed_by_user_id"] == ctx.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the officer who closed the lot may not post its "
                           "proceeds distribution")
        if dist["status"] != "CALCULATED":
            raise ApiError("ERR_INVALID_STATE",
                           "only a CALCULATED distribution may be posted")
        for row in rollups.distributions_of_lot(dist["auction_lot_id"]):
            if row["id"] != dist["id"] and row["status"] == "POSTED":
                raise ApiError("ERR_DISTRIBUTION_ALREADY_POSTED",
                               "a distribution for this lot has already been posted")
        dist["status"] = "POSTED"
        dist["posted_by_user_id"] = ctx.user_id
        dist["posted_at"] = store.iso(store.db.now)
        ctx.touch(dist)
        agency = db.agencies.get(dist["beneficiary_agency_id"])
        if agency is not None:
            rollups.recompute_agency_ledger(agency, ctx)
        return ok(view("ProceedsDistribution", dist))

    @app.route("/proceeds-distributions/<dist_id>/reverse", methods=["POST"])
    @endpoint(["FinanceController"])
    def reverse_distribution(ctx, dist_id):
        body = read_body()
        f = Fields(body)
        f.string("reversal_reason", required=True, minlen=1)
        f.done()
        dist = rollups.fetch(db.distributions, dist_id, "ERR_DISTRIBUTION_NOT_FOUND")
        if dist["status"] != "POSTED":
            raise ApiError("ERR_INVALID_STATE",
                           "only a POSTED distribution may be reversed")
        agency = db.agencies.get(dist["beneficiary_agency_id"])
        if agency is not None:
            remaining = (agency["proceeds_account_balance_cents"]
                         - dist["net_to_agency_cents"])
            if remaining < 0:
                raise ApiError("ERR_LEDGER_WOULD_GO_NEGATIVE",
                               "the reversal would overdraw the beneficiary's "
                               "proceeds ledger")
        dist["status"] = "REVERSED"
        dist["reversal_reason"] = f["reversal_reason"]
        ctx.touch(dist)
        if agency is not None:
            rollups.recompute_agency_ledger(agency, ctx)
        return ok(view("ProceedsDistribution", dist))
