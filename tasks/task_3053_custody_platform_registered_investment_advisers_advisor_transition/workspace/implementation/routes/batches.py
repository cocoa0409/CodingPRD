"""Bulk onboarding batches: materialise ACCOUNTS, TRANSFERS, LOTS or EVIDENCE
rows, with idempotent dispatch by natural key (PRD §3.3)."""

from core import constants as C
from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE
from domain.cascade import apply_posture
from domain.guards import firm_active_guard
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import load, load_firm, params


def register(api):

    @api.route("/ria/onboarding-batches", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_batch():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        firm_active_guard(firm)
        items = data.get("items")
        if not isinstance(items, list):
            items = []
        row = create("OnboardingBatch",
                     firm_id=firm.get("id"),
                     batch_kind=need(data, "batch_kind"),
                     batch_status="CREATED",
                     chunk_size=data.get("chunk_size"),
                     requested_item_count=len(items),
                     dispatched_item_count=0,
                     skipped_duplicate_count=0,
                     _items=items)
        return ok(serialize(row), 201)

    @api.route("/ria/onboarding-batches/<batch_id>", methods=["PUT"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def dispatch_batch(batch_id):
        batch = load("OnboardingBatch", batch_id)
        data = body()
        check_if_match(batch, data)
        firm = load_firm(batch.get("firm_id"))
        firm_active_guard(firm)
        if batch.get("batch_status") == "COMPLETED":
            # PRD §3.3: dispatch is idempotent by design, so a repeated dispatch
            # skips rows whose natural key already exists rather than being
            # refused — the counts it reports stay stable across retries.
            return ok(serialize(batch), 200)
        if "chunk_size" in data and data.get("chunk_size") is not None:
            batch["chunk_size"] = int(data["chunk_size"])
        items = batch.get("_items") or []
        items = items[:int(batch.get("chunk_size"))] if batch.get("chunk_size") else items
        _check_dispatchable(batch, firm, items)
        dispatched, skipped = _materialise(batch, firm, items)
        batch["dispatched_item_count"] = int(batch.get("dispatched_item_count") or 0) + dispatched
        batch["skipped_duplicate_count"] = skipped
        batch["batch_status"] = "COMPLETED"
        touch(batch)
        return ok(serialize(batch), 200)

    @api.route("/ria/onboarding-batches/<batch_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_batch(batch_id):
        return ok(serialize(load("OnboardingBatch", batch_id)), 200)

    @api.route("/ria/firms/<firm_id>/onboarding-batches", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_batches(firm_id):
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("OnboardingBatch", {"firm_id": firm_id, "batch_kind": p.get("batch_kind")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)


def _check_dispatchable(batch, firm, items):
    kind = batch.get("batch_kind")
    if kind == "ACCOUNTS":
        for item in items:
            household = STORE.get("Household", item.get("household_id"))
            if household is None or household.get("household_status") == "CLOSED":
                fail("ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE")
    elif kind == "TRANSFERS":
        for item in items:
            account = STORE.get("HouseholdAccount", item.get("receiving_account_id"))
            if account is None or account.get("account_status") not in ("OPEN", "FROZEN"):
                fail("ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE")
    elif kind == "LOTS":
        for item in items:
            if STORE.get("AssetTransfer", item.get("transfer_id")) is None:
                fail("ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE")
    elif kind == "EVIDENCE":
        if not STORE.find("CustodyRulesEvidence", firm_id=firm.get("id")):
            fail("ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE")
    else:
        fail("ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE")


def _materialise(batch, firm, items):
    dispatched = 0
    skipped = 0
    kind = batch.get("batch_kind")
    for item in items:
        if kind == "ACCOUNTS":
            number = item.get("account_number")
            existing = None
            for candidate in STORE.find("HouseholdAccount", firm_id=firm.get("id")):
                if candidate.get("account_number") == number and candidate.get("account_status") != "CLOSED":
                    existing = candidate
                    break
            if existing is not None:
                skipped += 1
                continue
            account_type = item.get("account_type")
            create("HouseholdAccount",
                   household_id=item.get("household_id"),
                   firm_id=firm.get("id"),
                   account_number=number,
                   account_type=account_type,
                   account_status="PENDING",
                   market_value_cents=0,
                   account_fee_basis_cents=0,
                   billable=account_type in C.BILLABLE_ACCOUNT_TYPES,
                   householding_consent=item.get("householding_consent", "NONE"),
                   last_listed_cents=None,
                   last_listed_at=None,
                   model_portfolio_id=None,
                   billed_period_count=0)
            dispatched += 1
        elif kind == "TRANSFERS":
            deliverer = item.get("delivering_firm_name")
            method = item.get("method")
            account_id = item.get("receiving_account_id")
            existing = None
            for candidate in STORE.find("AssetTransfer", receiving_account_id=account_id):
                if candidate.get("delivering_firm_name") == deliverer and candidate.get("method") == method:
                    existing = candidate
                    break
            if existing is not None:
                skipped += 1
                continue
            transfer = create("AssetTransfer",
                              receiving_account_id=account_id,
                              firm_id=firm.get("id"),
                              transfer_status="REQUESTED",
                              delivering_firm_name=deliverer,
                              method=method,
                              sent_basis_confidence=None,
                              carryover_cents=0,
                              cost_basis_complete=False,
                              rejected_reason_code=None,
                              credited_at=None,
                              submitted_at=None)
            for lot in item.get("lots") or []:
                create("TransferLot",
                       transfer_id=transfer.get("id"),
                       symbol=lot.get("symbol"),
                       quantity_micros=int(lot.get("quantity_micros") or 0),
                       sent_cost_basis_cents=lot.get("sent_cost_basis_cents"),
                       lot_inventory_date=lot.get("lot_inventory_date"),
                       valuation_price_micros=int(lot.get("valuation_price_micros") or 0),
                       basis_appraisal_cents=None,
                       suspected_double_basis=False,
                       basis_confidence_grade=None,
                       lot_status="PENDING")
            dispatched += 1
        elif kind == "LOTS":
            transfer_id = item.get("transfer_id")
            symbol = item.get("symbol")
            existing = None
            for candidate in STORE.find("TransferLot", transfer_id=transfer_id):
                if candidate.get("symbol") == symbol:
                    existing = candidate
                    break
            if existing is not None:
                skipped += 1
                continue
            create("TransferLot",
                   transfer_id=transfer_id,
                   symbol=symbol,
                   quantity_micros=int(item.get("quantity_micros") or 0),
                   sent_cost_basis_cents=item.get("sent_cost_basis_cents"),
                   lot_inventory_date=item.get("lot_inventory_date"),
                   valuation_price_micros=int(item.get("valuation_price_micros") or 0),
                   basis_appraisal_cents=None,
                   suspected_double_basis=False,
                   basis_confidence_grade=None,
                   lot_status="PENDING")
            dispatched += 1
        elif kind == "EVIDENCE":
            code = item.get("requirement_code")
            existing = None
            for candidate in STORE.find("CustodyRulesEvidence", firm_id=firm.get("id")):
                if candidate.get("requirement_code") == code:
                    existing = candidate
                    break
            if existing is not None:
                skipped += 1
                continue
            create("CustodyRulesEvidence",
                   firm_id=firm.get("id"),
                   requirement_code=code,
                   requirement_status="PENDING",
                   critical=bool(item.get("critical")),
                   drafted_by_user_id=None,
                   accepted_by_user_id=None,
                   evidence_document_hash=None,
                   submitted_at=None,
                   evidence_round_number=0)
            dispatched += 1
        else:
            fail("ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE")
    if kind == "EVIDENCE":
        apply_posture(firm)
    return dispatched, skipped