"""Derived fields and response serialisers."""

from decimal import Decimal

import calc
import store
from store import DB


# ---------------------------------------------------------------------------
# traversal helpers
# ---------------------------------------------------------------------------

def rows(collection):
    return list(DB[collection].values())


def batch_of_run(run):
    return DB["batches"].get(run.get("batch_id"))


def beer_of_run(run):
    batch = batch_of_run(run)
    if batch is None:
        return None
    return DB["beers"].get(batch.get("beer_id"))


def runs_of_batch(batch_id):
    return store.ordered([r for r in rows("runs") if r.get("batch_id") == batch_id])


def completed_runs_of_batch(batch_id):
    return [r for r in runs_of_batch(batch_id) if r.get("state") == "COMPLETED"]


def orders_citing_run(run_id, states):
    result = []
    for order in rows("orders"):
        if order.get("state") not in states:
            continue
        for line in order.get("allocation_lines") or []:
            if line.get("packaging_run_id") == run_id:
                result.append((order, line))
    return result


# ---------------------------------------------------------------------------
# brewery
# ---------------------------------------------------------------------------

def notice_active():
    brewery = DB["brewery"]
    return brewery is not None and brewery.get("notice_status") == "ACTIVE"


def filed_reports():
    return [r for r in rows("reports") if r.get("state") == "FILED"]


def taproom_bbl_ytd():
    brewery = DB["brewery"]
    total = Decimal(brewery.get("carry_in_taproom_bbl") or 0)
    for report in filed_reports():
        total += Decimal(report.get("taproom_bbl") or 0)
    return calc.bbl(total)


def distribution_bbl_ytd():
    brewery = DB["brewery"]
    total = Decimal(brewery.get("carry_in_distribution_bbl") or 0)
    for report in filed_reports():
        total += Decimal(report.get("distribution_bbl") or 0)
    return calc.bbl(total)


def franchise_locked_state_codes():
    codes = set()
    for appointment in rows("appointments"):
        if appointment.get("state") not in ("ACTIVE", "TERMINATION_REQUESTED"):
            continue
        licence = DB["licenses"].get(appointment.get("state_license_id"))
        if licence is not None:
            codes.add(licence.get("state_code"))
    return sorted(codes)


def serialize_brewery(brewery):
    taproom = taproom_bbl_ytd()
    distribution = distribution_bbl_ytd()
    return {
        "id": brewery["id"],
        "legal_name": brewery["legal_name"],
        "home_state_code": brewery["home_state_code"],
        "ttb_brewers_notice_number": brewery["ttb_brewers_notice_number"],
        "notice_status": brewery["notice_status"],
        "notice_effective_utc": brewery.get("notice_effective_utc"),
        "suspension_reason": brewery.get("suspension_reason"),
        "carry_in_taproom_bbl": calc.bbl(brewery.get("carry_in_taproom_bbl") or 0),
        "carry_in_distribution_bbl": calc.bbl(brewery.get("carry_in_distribution_bbl") or 0),
        "taproom_bbl_ytd": taproom,
        "distribution_bbl_ytd": distribution,
        "total_bbl_ytd": calc.bbl(taproom + distribution),
        "franchise_locked_state_codes": franchise_locked_state_codes(),
        "created_at": brewery["created_at"],
        "updated_at": brewery["updated_at"],
        "version": brewery["version"],
    }


# ---------------------------------------------------------------------------
# beer
# ---------------------------------------------------------------------------

def formula_ok(beer):
    return beer.get("registration_state") in ("FORMULA_APPROVED", "FORMULA_EXEMPT")


def taproom_sellable(beer):
    return bool(notice_active() and formula_ok(beer))


def distribution_sellable(beer):
    return bool(notice_active() and formula_ok(beer)
                and beer.get("label_state") == "COLA_APPROVED")


def serialize_beer(beer):
    return {
        "id": beer["id"],
        "name": beer["name"],
        "style": beer["style"],
        "abv_pct": beer["abv_pct"],
        "requires_formula": beer["requires_formula"],
        "price_per_bbl_cents": beer["price_per_bbl_cents"],
        "registration_state": beer["registration_state"],
        "label_state": beer["label_state"],
        "cola_id": beer.get("cola_id"),
        "label_fields": beer.get("label_fields"),
        "taproom_sellable": taproom_sellable(beer),
        "distribution_sellable": distribution_sellable(beer),
        "created_at": beer["created_at"],
        "updated_at": beer["updated_at"],
        "version": beer["version"],
    }


# ---------------------------------------------------------------------------
# tank
# ---------------------------------------------------------------------------

def serialize_tank(tank):
    return {
        "id": tank["id"],
        "code": tank["code"],
        "tank_type": tank["tank_type"],
        "capacity_bbl": calc.bbl2(tank["capacity_bbl"]),
        "status": tank["status"],
        "last_cip_utc": tank.get("last_cip_utc"),
        "cip_cycle_count": tank["cip_cycle_count"],
        "occupying_batch_id": tank.get("occupying_batch_id"),
        "created_at": tank["created_at"],
        "updated_at": tank["updated_at"],
        "version": tank["version"],
    }


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------

def packaged_bbl(batch):
    total = Decimal("0")
    for run in completed_runs_of_batch(batch["id"]):
        total += Decimal(run.get("bbl_removed") or 0)
    return calc.bbl(total)


def yield_figure(batch):
    if batch.get("actual_yield_bbl") is not None:
        return Decimal(batch["actual_yield_bbl"])
    return Decimal(batch["planned_volume_bbl"])


def remaining_bbl(batch):
    return calc.bbl(yield_figure(batch) - packaged_bbl(batch))


def serialize_batch(batch):
    return {
        "id": batch["id"],
        "beer_id": batch["beer_id"],
        "tank_id": batch["tank_id"],
        "batch_code": batch["batch_code"],
        "planned_volume_bbl": calc.bbl2(batch["planned_volume_bbl"]),
        "brew_start_utc": store.fmt_dt(batch["brew_start_utc"]),
        "brew_end_utc": store.fmt_dt(batch["brew_end_utc"]),
        "loss_basis": batch["loss_basis"],
        "state": batch["state"],
        "actual_yield_bbl": (calc.bbl(batch["actual_yield_bbl"])
                             if batch.get("actual_yield_bbl") is not None else None),
        "packaged_bbl": packaged_bbl(batch),
        "remaining_bbl": remaining_bbl(batch),
        "total_loss_bbl": (calc.bbl(batch["total_loss_bbl"])
                           if batch.get("total_loss_bbl") is not None else None),
        "dumped_reason": batch.get("dumped_reason"),
        "created_at": batch["created_at"],
        "updated_at": batch["updated_at"],
        "version": batch["version"],
    }


# ---------------------------------------------------------------------------
# packaging run
# ---------------------------------------------------------------------------

def run_allocated_bbl(run):
    total = Decimal("0")
    for _order, line in orders_citing_run(run["id"], ("ALLOCATED",)):
        total += Decimal(line.get("bbl") or 0)
    return calc.bbl(total)


def run_shipped_bbl(run):
    total = Decimal("0")
    for _order, line in orders_citing_run(run["id"], ("SHIPPED",)):
        total += Decimal(line.get("bbl") or 0)
    return calc.bbl(total)


def run_available_bbl(run):
    return calc.bbl(Decimal(run.get("bbl_removed") or 0)
                    - run_allocated_bbl(run) - run_shipped_bbl(run))


def kegs_outstanding_count(run):
    count = 0
    for keg in rows("kegs"):
        if keg.get("packaging_run_id") == run["id"] and keg.get("state") in (
                "FILLED", "TAPPED", "DEPLOYED"):
            count += 1
    return count


def serialize_run(run):
    return {
        "id": run["id"],
        "batch_id": run["batch_id"],
        "run_code": run["run_code"],
        "package_type": run["package_type"],
        "destination": run["destination"],
        "units_planned": run["units_planned"],
        "units_produced": run.get("units_produced"),
        "bbl_removed": calc.bbl(run.get("bbl_removed") or 0),
        "removed_at_utc": run.get("removed_at_utc"),
        "state": run["state"],
        "allocated_bbl": run_allocated_bbl(run),
        "shipped_bbl": run_shipped_bbl(run),
        "available_bbl": run_available_bbl(run),
        "kegs_filled_count": run.get("kegs_filled_count") or 0,
        "kegs_outstanding_count": kegs_outstanding_count(run),
        "reconciliation_state": run["reconciliation_state"],
        "keg_shrinkage_oz": (calc.oz(run["keg_shrinkage_oz"])
                             if run.get("keg_shrinkage_oz") is not None else None),
        "loss_share_bbl": (calc.bbl(run["loss_share_bbl"])
                           if run.get("loss_share_bbl") is not None else None),
        "certified_by_user_id": run.get("certified_by_user_id"),
        "voided_at_utc": run.get("voided_at_utc"),
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "version": run["version"],
    }


# ---------------------------------------------------------------------------
# keg asset
# ---------------------------------------------------------------------------

def keg_remaining_oz(keg):
    return calc.oz(Decimal(keg.get("filled_volume_oz") or 0)
                   - Decimal(keg.get("poured_volume_oz") or 0))


def serialize_keg(keg):
    return {
        "id": keg["id"],
        "keg_serial": keg["keg_serial"],
        "size_bbl": keg["size_bbl"],
        "packaging_run_id": keg.get("packaging_run_id"),
        "filled_beer_id": keg.get("filled_beer_id"),
        "state": keg["state"],
        "filled_volume_oz": calc.oz(keg.get("filled_volume_oz") or 0),
        "remaining_volume_oz": keg_remaining_oz(keg),
        "poured_volume_oz": calc.oz(keg.get("poured_volume_oz") or 0),
        "returned_volume_oz": (calc.oz(keg["returned_volume_oz"])
                               if keg.get("returned_volume_oz") is not None else None),
        "depletion_variance_oz": (calc.oz(keg["depletion_variance_oz"])
                                  if keg.get("depletion_variance_oz") is not None else None),
        "shrinkage_flagged": bool(keg.get("shrinkage_flagged")),
        "cycle_count": keg.get("cycle_count") or 0,
        "last_cleaned_utc": keg.get("last_cleaned_utc"),
        "tapped_at_utc": keg.get("tapped_at_utc"),
        "deployment_channel": keg.get("deployment_channel"),
        "created_at": keg["created_at"],
        "updated_at": keg["updated_at"],
        "version": keg["version"],
    }


# ---------------------------------------------------------------------------
# taproom pour
# ---------------------------------------------------------------------------

def serialize_pour(pour):
    return {
        "id": pour["id"],
        "keg_asset_id": pour["keg_asset_id"],
        "container_type": pour["container_type"],
        "volume_oz": calc.oz(pour["volume_oz"]),
        "price_cents": pour["price_cents"],
        "poured_at_utc": pour["poured_at_utc"],
        "poured_by_user_id": pour["poured_by_user_id"],
        "container_sanitized": pour.get("container_sanitized"),
        "sanitizer_ppm": pour.get("sanitizer_ppm"),
        "contact_time_seconds": pour.get("contact_time_seconds"),
        "sanitation_verdict": pour["sanitation_verdict"],
        "attested_by_user_id": pour.get("attested_by_user_id"),
        "label_fields": pour.get("label_fields"),
        "created_at": pour["created_at"],
    }


# ---------------------------------------------------------------------------
# state licence
# ---------------------------------------------------------------------------

def barrels_shipped_ytd(licence):
    total = Decimal(licence.get("carry_in_barrels_ytd") or 0)
    for order in rows("orders"):
        if (order.get("state") == "SHIPPED"
                and order.get("state_license_id") == licence["id"]):
            total += Decimal(order.get("allocated_bbl") or 0)
    return calc.bbl(total)


def active_appointment_count(licence):
    count = 0
    for appointment in rows("appointments"):
        if (appointment.get("state_license_id") == licence["id"]
                and appointment.get("state") in ("ACTIVE", "TERMINATION_REQUESTED")):
            count += 1
    return count


def serialize_license(licence):
    return {
        "id": licence["id"],
        "state_code": licence["state_code"],
        "license_type": licence["license_type"],
        "annual_barrel_cap": calc.bbl2(licence["annual_barrel_cap"]),
        "franchise_state": bool(licence["franchise_state"]),
        "termination_notice_days": licence["termination_notice_days"],
        "effective_from_utc": store.fmt_dt(licence["effective_from_utc"]),
        "expires_at_utc": store.fmt_dt(licence["expires_at_utc"]),
        "status": licence["status"],
        "carry_in_barrels_ytd": calc.bbl(licence.get("carry_in_barrels_ytd") or 0),
        "barrels_shipped_ytd": barrels_shipped_ytd(licence),
        "active_appointment_count": active_appointment_count(licence),
        "created_at": licence["created_at"],
        "updated_at": licence["updated_at"],
        "version": licence["version"],
    }


# ---------------------------------------------------------------------------
# distributor appointment
# ---------------------------------------------------------------------------

def brand_scope(appointment):
    return "SINGLE_BRAND" if appointment.get("appointed_beer_id") else "ALL_BRANDS"


def appointment_covers_beer(appointment, beer_id):
    if brand_scope(appointment) == "ALL_BRANDS":
        return True
    return appointment.get("appointed_beer_id") == beer_id


def live_appointment_for(state_license_id, beer_id):
    for appointment in store.ordered(rows("appointments")):
        if appointment.get("state_license_id") != state_license_id:
            continue
        if appointment.get("state") not in ("ACTIVE", "TERMINATION_REQUESTED"):
            continue
        if appointment_covers_beer(appointment, beer_id):
            return appointment
    return None


def serialize_appointment(appointment):
    return {
        "id": appointment["id"],
        "state_license_id": appointment["state_license_id"],
        "appointed_beer_id": appointment.get("appointed_beer_id"),
        "distributor_name": appointment["distributor_name"],
        "brand_scope": brand_scope(appointment),
        "state": appointment["state"],
        "proposed_by_user_id": appointment.get("proposed_by_user_id"),
        "approved_by_user_id": appointment.get("approved_by_user_id"),
        "activated_at_utc": appointment.get("activated_at_utc"),
        "termination_requested_at_utc": appointment.get("termination_requested_at_utc"),
        "termination_effective_utc": appointment.get("termination_effective_utc"),
        "good_cause_code": appointment.get("good_cause_code"),
        "terminated_at_utc": appointment.get("terminated_at_utc"),
        "created_at": appointment["created_at"],
        "updated_at": appointment["updated_at"],
        "version": appointment["version"],
    }


# ---------------------------------------------------------------------------
# distribution order
# ---------------------------------------------------------------------------

def serialize_order(order):
    lines = []
    for line in order.get("allocation_lines") or []:
        lines.append({
            "packaging_run_id": line["packaging_run_id"],
            "bbl": calc.bbl(line["bbl"]),
        })
    return {
        "id": order["id"],
        "beer_id": order["beer_id"],
        "state_license_id": order["state_license_id"],
        "appointment_id": order.get("appointment_id"),
        "order_code": order["order_code"],
        "bbl_requested": calc.bbl2(order["bbl_requested"]),
        "ship_to_state_code": order["ship_to_state_code"],
        "distance_miles": order["distance_miles"],
        "requested_ship_utc": store.fmt_dt(order["requested_ship_utc"]),
        "channel": order["channel"],
        "product_cents": order["product_cents"],
        "freight_cents": order["freight_cents"],
        "franchise_fee_cents": order["franchise_fee_cents"],
        "landed_cost_cents": order["landed_cost_cents"],
        "state": order["state"],
        "allocated_bbl": calc.bbl(order.get("allocated_bbl") or 0),
        "allocation_lines": lines,
        "rejection_reason": order.get("rejection_reason"),
        "cancel_reason": order.get("cancel_reason"),
        "shipped_at_utc": order.get("shipped_at_utc"),
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
        "version": order["version"],
    }


# ---------------------------------------------------------------------------
# excise report
# ---------------------------------------------------------------------------

def serialize_report(report):
    return {
        "id": report["id"],
        "period_start_utc": store.fmt_dt(report["period_start_utc"]),
        "period_end_utc": store.fmt_dt(report["period_end_utc"]),
        "taproom_basis": report["taproom_basis"],
        "amends_report_id": report.get("amends_report_id"),
        "taproom_bbl": calc.bbl(report["taproom_bbl"]),
        "distribution_bbl": calc.bbl(report["distribution_bbl"]),
        "total_taxable_bbl": calc.bbl(report["total_taxable_bbl"]),
        "ytd_bbl_before_period": calc.bbl(report["ytd_bbl_before_period"]),
        "federal_tax_cents": report["federal_tax_cents"],
        "state_tax_cents": report["state_tax_cents"],
        "total_tax_due_cents": report["total_tax_due_cents"],
        "state": report["state"],
        "prepared_by_user_id": report.get("prepared_by_user_id"),
        "filed_by_user_id": report.get("filed_by_user_id"),
        "filed_at_utc": report.get("filed_at_utc"),
        "created_at": report["created_at"],
        "updated_at": report["updated_at"],
        "version": report["version"],
    }


# ---------------------------------------------------------------------------
# event permit
# ---------------------------------------------------------------------------

def serialize_permit(permit):
    return {
        "id": permit["id"],
        "featured_beer_id": permit["featured_beer_id"],
        "event_name": permit["event_name"],
        "permit_type": permit["permit_type"],
        "venue_state_code": permit["venue_state_code"],
        "event_start_utc": store.fmt_dt(permit["event_start_utc"]),
        "event_end_utc": store.fmt_dt(permit["event_end_utc"]),
        "requested_bbl": calc.bbl2(permit["requested_bbl"]),
        "state": permit["state"],
        "info_request_note": permit.get("info_request_note"),
        "submission_count": permit.get("submission_count") or 0,
        "decided_at_utc": permit.get("decided_at_utc"),
        "denial_reason": permit.get("denial_reason"),
        "created_at": permit["created_at"],
        "updated_at": permit["updated_at"],
        "version": permit["version"],
    }
