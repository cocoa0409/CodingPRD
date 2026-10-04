"""Commission ledger, corrections and carrier reconciliation
(PRD 2.8, 3.8)."""

from decimal import Decimal

import calculations as calc
import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

READ_ROLES = ("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "Any")
ENTRY_TYPES = ("INITIAL", "RENEWAL", "CHARGEBACK", "ADJUSTMENT", "REVERSAL")


def register(app):
    @app.post("/commission-ledger-entries")
    @requires("DirectorOfSales")
    def post_ledger_entry():
        payload = middleware.body()
        enrollment = middleware.resolve("Enrollment",
                                        middleware.require_field(payload, "enrollment_id"))
        reconciliation = middleware.resolve("CarrierReconciliation",
                                            middleware.require_field(payload, "carrier_reconciliation_id"))
        entry_type = middleware.require_field(payload, "entry_type", str)
        if entry_type not in ENTRY_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "entry_type is not a recognized classification.")
        period_month = middleware.require_field(payload, "period_month", str)
        row = core.post_entry(enrollment, entry_type=entry_type, period_month=period_month,
                              memo=middleware.optional(payload, "memo"),
                              reconciliation_id=reconciliation["id"])
        core.recompute_reconciliation(reconciliation)
        core.recompute_balance(db.agencies.get(enrollment["agency_id"]))
        return response.ok(serializers.serialize("CommissionLedgerEntry", row), status=201)

    @app.get("/commission-ledger-entries")
    @requires(*READ_ROLES)
    def list_ledger_entries():
        rows = list(db.ledger_entries.values())
        for arg, field in (("enrollment_id", "enrollment_id"),
                           ("carrier_reconciliation_id", "carrier_reconciliation_id"),
                           ("entry_type", "entry_type"), ("status", "status"),
                           ("period_month", "period_month")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CommissionLedgerEntry", page), limit, offset, total)

    @app.get("/commission-ledger-entries/<entry_id>")
    @requires(*READ_ROLES)
    def get_ledger_entry(entry_id):
        row = middleware.resolve("CommissionLedgerEntry", entry_id)
        return response.ok(serializers.serialize("CommissionLedgerEntry", row))

    @app.post("/commission-ledger-entries/<entry_id>/finalize")
    @requires("DirectorOfSales")
    def finalize_entry(entry_id):
        row = middleware.resolve("CommissionLedgerEntry", entry_id)
        if row["status"] != "PROVISIONAL":
            raise ApiError("ERR_LEDGER_ENTRY_NOT_PROVISIONAL", "The entry is not PROVISIONAL.")
        enrollment = db.enrollments.get(row["enrollment_id"])
        if row["entry_type"] in ("INITIAL", "RENEWAL") \
                and enrollment["disenrollment_status"] != "ENROLLED":
            raise ApiError("ERR_ENROLLMENT_NOT_ENROLLED",
                           "The enrollment's membership has ended.")

        plan = db.plans.get(enrollment["plan_id"])
        carrier = db.carriers.get(enrollment["carrier_id"])
        if row["entry_type"] == "INITIAL":
            final_amount = calc.annual_initial(plan, carrier)
        elif row["entry_type"] == "RENEWAL":
            final_amount = calc.annual_renewal(plan, carrier)
        elif row["entry_type"] == "ADJUSTMENT":
            final_amount = row["amount_cents"]
        else:
            final_amount = row["amount_cents"]

        row["status"] = "FINALIZED"
        row["amount_cents"] = calc.r2(final_amount)
        core.touch(row)
        core.refresh_period(row["carrier_id"], row["period_month"])
        agency = db.agencies.get(enrollment["agency_id"])
        core.recompute_balance(agency)
        core.recompute_loss_ratio(agency)
        return response.ok(serializers.serialize("CommissionLedgerEntry", row))

    @app.post("/commission-ledger-entries/<entry_id>/reverse")
    @requires("DirectorOfSales")
    def reverse_entry(entry_id):
        row = middleware.resolve("CommissionLedgerEntry", entry_id)
        if row["status"] not in ("PROVISIONAL", "FINALIZED"):
            raise ApiError("ERR_LEDGER_ENTRY_NOT_REVERSIBLE", "The entry is already REVERSED.")

        enrollment = db.enrollments.get(row["enrollment_id"])
        agency = db.agencies.get(enrollment["agency_id"])
        row["_balance_before_reversal"] = calc.dec(agency["commission_balance_cents"])
        row["_ledger_count_at_reversal"] = len(
            [e for e in db.ledger_entries.values()
             if db.enrollments.get(e["enrollment_id"], {}).get("agency_id") == agency["id"]])
        row["_reversal_side_effect_cents"] = Decimal("0.00")

        row["status"] = "REVERSED"
        core.touch(row)
        core.recompute_balance(agency)
        core.refresh_period(row["carrier_id"], row["period_month"])
        core.recompute_loss_ratio(agency)

        if enrollment["submission_status"] == "EFFECTUATED" \
                and enrollment["disenrollment_status"] == "ENROLLED":
            adjustment = core.post_entry(
                enrollment, entry_type="ADJUSTMENT",
                period_month=row["period_month"],
                reconciliation_id=row.get("carrier_reconciliation_id"))
            row["_reversal_side_effect_cents"] = calc.dec(adjustment["amount_cents"])
            core.recompute_balance(agency)
            core.refresh_period(row["carrier_id"], row["period_month"])

        core.recompute_posture(agency)
        return response.ok(serializers.serialize("CommissionLedgerEntry", row))

    @app.post("/commission-ledger-entries/<entry_id>/reinstate")
    @requires("DirectorOfSales")
    def reinstate_entry(entry_id):
        row = middleware.resolve("CommissionLedgerEntry", entry_id)
        if row["status"] != "REVERSED":
            raise ApiError("ERR_LEDGER_ENTRY_NOT_REVERSED", "The entry is not REVERSED.")
        enrollment = db.enrollments.get(row["enrollment_id"])
        agency = db.agencies.get(enrollment["agency_id"])
        middleware.gate_posture(agency)

        _check_invariant(row, agency, "PROVISIONAL")
        row["status"] = "PROVISIONAL"
        core.touch(row)
        core.recompute_balance(agency)
        core.refresh_period(row["carrier_id"], row["period_month"])
        return response.ok(serializers.serialize("CommissionLedgerEntry", row))

    @app.post("/commission-ledger-entries/<entry_id>/reinstate-finalized")
    @requires("DirectorOfSales")
    def reinstate_finalized(entry_id):
        row = middleware.resolve("CommissionLedgerEntry", entry_id)
        if row["status"] != "REVERSED":
            raise ApiError("ERR_LEDGER_ENTRY_NOT_REVERSED", "The entry is not REVERSED.")
        enrollment = db.enrollments.get(row["enrollment_id"])
        agency = db.agencies.get(enrollment["agency_id"])
        middleware.gate_posture(agency)
        if enrollment["disenrollment_status"] != "ENROLLED":
            raise ApiError("ERR_ENROLLMENT_NOT_ENROLLED",
                           "The enrollment's membership has ended.")

        _check_invariant(row, agency, "FINALIZED")
        row["status"] = "FINALIZED"
        core.touch(row)
        core.recompute_balance(agency)
        core.refresh_period(row["carrier_id"], row["period_month"])
        return response.ok(serializers.serialize("CommissionLedgerEntry", row))

    # -- Corrections ---------------------------------------------------------
    @app.post("/corrections")
    @requires("DirectorOfSales")
    def post_correction():
        payload = middleware.body()
        enrollment = middleware.resolve("Enrollment",
                                        middleware.require_field(payload, "enrollment_id"))
        reconciliation = middleware.resolve("CarrierReconciliation",
                                            middleware.require_field(payload, "carrier_reconciliation_id"))
        amount_cents = calc.dec(middleware.require_field(payload, "amount_cents"))
        period_month = middleware.require_field(payload, "period_month", str)
        if reconciliation["carrier_id"] != enrollment["carrier_id"] \
                or reconciliation["period_month"] != period_month \
                or reconciliation["status"] != "OPEN":
            raise ApiError("ERR_NO_OPEN_RECONCILIATION",
                           "No OPEN reconciliation names this carrier and period.")
        row = core.post_entry(enrollment, entry_type="ADJUSTMENT", amount_cents=amount_cents,
                              period_month=period_month,
                              memo=middleware.optional(payload, "memo"),
                              reconciliation_id=reconciliation["id"])
        core.recompute_reconciliation(reconciliation)
        core.recompute_balance(db.agencies.get(enrollment["agency_id"]))
        return response.ok(serializers.serialize("CommissionLedgerEntry", row), status=201)

    @app.get("/corrections")
    @requires(*READ_ROLES)
    def list_corrections():
        rows = [row for row in db.ledger_entries.values() if row["entry_type"] == "ADJUSTMENT"]
        for arg, field in (("enrollment_id", "enrollment_id"),
                           ("carrier_reconciliation_id", "carrier_reconciliation_id"),
                           ("period_month", "period_month")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CommissionLedgerEntry", page), limit, offset, total)

    # -- Carrier reconciliation ---------------------------------------------
    @app.post("/carrier-reconciliations")
    @requires("DirectorOfSales")
    def open_reconciliation():
        payload = middleware.body()
        carrier = middleware.resolve("Carrier", middleware.require_field(payload, "carrier_id"))
        variant = middleware.require_field(payload, "internal_total_variant", str)
        if variant not in ("PROVISIONAL", "FINAL"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "internal_total_variant must be PROVISIONAL or FINAL.")
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "carrier_id": carrier["id"],
            "period_month": middleware.require_field(payload, "period_month", str),
            "carrier_reported_total_cents": (
                None if payload.get("carrier_reported_total_cents") is None
                else middleware.as_int(payload["carrier_reported_total_cents"],
                                       "carrier_reported_total_cents")),
            "internal_total_variant": variant,
            "status": "OPEN",
        }
        db.reconciliations[row["id"]] = row
        core.recompute_reconciliation(row)
        return response.ok(serializers.serialize("CarrierReconciliation", row), status=201)

    @app.get("/carrier-reconciliations")
    @requires(*READ_ROLES)
    def list_reconciliations():
        rows = list(db.reconciliations.values())
        for arg, field in (("carrier_id", "carrier_id"), ("period_month", "period_month"),
                           ("status", "status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CarrierReconciliation", page), limit, offset, total)

    @app.get("/carrier-reconciliations/<rec_id>")
    @requires(*READ_ROLES)
    def get_reconciliation(rec_id):
        row = middleware.resolve("CarrierReconciliation", rec_id)
        return response.ok(serializers.serialize("CarrierReconciliation", row))

    @app.post("/carrier-reconciliations/<rec_id>/reconcile")
    @requires("DirectorOfSales")
    def reconcile(rec_id):
        row = middleware.resolve("CarrierReconciliation", rec_id)
        if row["status"] != "OPEN":
            raise ApiError("ERR_RECONCILIATION_NOT_OPEN", "The period is not OPEN.")
        core.recompute_reconciliation(row)
        if calc.dec(row["variance_cents"]) != 0:
            raise ApiError("ERR_RECONCILIATION_VARIANCE_NONZERO",
                           "Reconciliation requires a zero variance.")
        row["status"] = "RECONCILED"
        core.touch(row)
        _finalize_period_entries(row)
        agency = _agency_for_carrier(row["carrier_id"])
        if agency is not None:
            core.recompute_balance(agency)
            core.recompute_loss_ratio(agency)
        return response.ok(serializers.serialize("CarrierReconciliation", row))

    @app.post("/carrier-reconciliations/<rec_id>/dispute")
    @requires("DirectorOfSales")
    def dispute(rec_id):
        row = middleware.resolve("CarrierReconciliation", rec_id)
        if row["status"] != "OPEN":
            raise ApiError("ERR_RECONCILIATION_NOT_OPEN", "The period is not OPEN.")
        core.recompute_reconciliation(row)
        if calc.dec(row["variance_cents"]) == 0:
            raise ApiError("ERR_RECONCILIATION_VARIANCE_ZERO",
                           "A zero variance period cannot be disputed.")
        row["status"] = "DISPUTED"
        core.touch(row)
        _finalize_period_entries(row)
        agency = _agency_for_carrier(row["carrier_id"])
        if agency is not None:
            core.recompute_balance(agency)
            core.recompute_loss_ratio(agency)
        return response.ok(serializers.serialize("CarrierReconciliation", row))

    @app.post("/carrier-reconciliations/<rec_id>/reopen")
    @requires("DirectorOfSales")
    def reopen(rec_id):
        row = middleware.resolve("CarrierReconciliation", rec_id)
        if row["status"] != "DISPUTED":
            raise ApiError("ERR_RECONCILIATION_NOT_DISPUTED", "The period is not DISPUTED.")
        core.recompute_reconciliation(row)
        if calc.dec(row["variance_cents"]) == 0:
            raise ApiError("ERR_RECONCILIATION_VARIANCE_ZERO",
                           "A zero variance period cannot be reopened as disputed.")
        row["status"] = "OPEN"
        core.touch(row)
        core.recompute_reconciliation(row)
        return response.ok(serializers.serialize("CarrierReconciliation", row))

    @app.post("/carrier-reconciliations/<rec_id>/level-recognize")
    @requires("DirectorOfSales")
    def level_recognize(rec_id):
        row = middleware.resolve("CarrierReconciliation", rec_id)
        if row["status"] != "OPEN":
            raise ApiError("ERR_RECONCILIATION_NOT_OPEN", "The period is not OPEN.")
        if row.get("carrier_reported_total_cents") is not None:
            raise ApiError("ERR_CARRIER_REPORTED_TOTAL_PRESENT",
                           "A carrier-reported total is already present for this period.")
        final_variant = dict(row)
        final_variant["internal_total_variant"] = "FINAL"
        core.recompute_reconciliation(final_variant)
        row["carrier_reported_total_cents"] = int(final_variant["internal_total_cents"])
        row["status"] = "RECONCILED"
        core.touch(row)
        _finalize_period_entries(row)
        core.recompute_reconciliation(row)
        agency = _agency_for_carrier(row["carrier_id"])
        if agency is not None:
            core.recompute_loss_ratio(agency)
        return response.ok(serializers.serialize("CarrierReconciliation", row))


def _finalize_period_entries(rec):
    for entry in core.lock_entries_for(rec):
        if entry["status"] == "PROVISIONAL":
            entry["status"] = "FINALIZED"
            core.touch(entry)


def _agency_for_carrier(carrier_id):
    for enrollment in db.enrollments.values():
        if enrollment["carrier_id"] == carrier_id:
            return db.agencies.get(enrollment["agency_id"])
    return None


def _check_invariant(row, agency, target_status):
    """A reverse-then-reinstate pair must restore the pre-reversal balance."""
    snapshot = row.get("_balance_before_reversal")
    if snapshot is None:
        return
    original_count = row.get("_ledger_count_at_reversal")
    current_count = len([e for e in db.ledger_entries.values()
                         if db.enrollments.get(e["enrollment_id"], {}).get("agency_id") == agency["id"]])
    if original_count is None or current_count != original_count:
        return
    previous = row["status"]
    row["status"] = target_status
    core.recompute_balance(agency)
    restored = calc.dec(agency["commission_balance_cents"])
    row["status"] = previous
    core.recompute_balance(agency)
    expected = calc.dec(snapshot) + calc.dec(row.get("_reversal_side_effect_cents") or 0)
    if restored != expected:
        raise ApiError("ERR_COMMISSION_LEDGER_INVARIANT_VIOLATION",
                       "The compensating pair would not restore the pre-reversal balance.")