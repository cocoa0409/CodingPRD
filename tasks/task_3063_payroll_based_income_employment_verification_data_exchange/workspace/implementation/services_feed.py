"""Employer freeze lifecycle, layouts and payroll feed batches."""
import clock
import calculations
import models
import store
from errors import ApiError
from domain import MAX_BATCH_RECORD_COUNT


# ------------------------------------------------------------------ employer

def refresh_employer(employer):
    calculations.refresh_employer_feed_status(employer)
    return employer


def freeze_employer(employer, reason_code):
    state = employer.get("freeze_state")
    if state == "ACTIVE":
        raise ApiError("ERR_ACTIVE_FREEZE_BLOCK")
    if state == "NONE":
        employer["freeze_state"] = "REQUESTED"
        employer["freeze_reason_code"] = reason_code
        employer["freeze_requested_at"] = clock.now()
        store.touch(employer)
        return employer
    if state == "REQUESTED":
        observed = employer["version"]
        employer["freeze_state"] = "ACTIVE"
        for record in store.all_rows("employment_records"):
            if record.get("employer_id") != employer["id"]:
                continue
            if record.get("currency_state") in ("CURRENT", "STALE"):
                record["currency_state"] = "FROZEN"
                record["frozen_by_employer_version"] = observed
                store.touch(record)
        _decline_requests_for_freeze(employer)
        _retire_layouts_on_freeze(employer)
        store.touch(employer)
        return employer
    if state in ("RELEASED", "LAPSED"):
        # "lapsed and released employers can be frozen again, returning
        # freeze_state to NONE" (PRD §2.7) — a fresh filing re-enters NONE.
        employer["freeze_state"] = "NONE"
        employer["freeze_reason_code"] = None
        employer["freeze_requested_at"] = None
        store.touch(employer)
        return employer
    raise ApiError("ERR_INVALID_STATE")


def _retire_layouts_on_freeze(employer):
    """Withdrawal leaves the contributor unable to produce verifiable data, so the
    layouts it had declared stop being usable; a released employer's layouts are
    re-declared DRAFT (PRD §2.7)."""
    for layout in store.all_rows("record_layouts"):
        if layout.get("employer_id") != employer["id"]:
            continue
        if layout.get("status") in ("DRAFT", "VERIFIED"):
            layout["status"] = "SUPERSEDED"
            layout["verified_at"] = None
            store.touch(layout)


def _revive_layouts_after_thaw(employer):
    for layout in store.all_rows("record_layouts"):
        if layout.get("employer_id") != employer["id"]:
            continue
        if layout.get("status") == "SUPERSEDED":
            layout["status"] = "DRAFT"
            store.touch(layout)


def _decline_requests_for_freeze(employer):
    for request in store.all_rows("verification_requests"):
        if request.get("request_state") not in ("PERMITTED", "VALIDATED"):
            continue
        if request.get("current_employer_id") == employer["id"]:
            decline_request(request, "EMPLOYER_FROZEN")
            continue
        if any(record.get("employer_id") == employer["id"]
               and record.get("covered_worker_id") == request.get("covered_worker_id")
               for record in store.all_rows("employment_records")):
            decline_request(request, "EMPLOYER_FROZEN")


def decline_request(request, reason):
    request["request_state"] = "DECLINED"
    request["decline_reason"] = reason
    request["fee_charged_cents"] = 0
    _invalidate_attestations(request["id"])
    store.touch(request)
    return request


def _invalidate_attestations(request_id):
    for attestation in store.all_rows("verification_attestations"):
        if attestation.get("verification_request_id") != request_id:
            continue
        if attestation.get("attestation_state") == "SIGNED":
            attestation["attestation_state"] = "INVALIDATED"
            store.touch(attestation)


def unfreeze_employer(employer, outcome):
    state = employer.get("freeze_state")
    if outcome == "RELEASE":
        if state != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        if employer.get("freeze_reason_code") == "REGULATORY_HOLD":
            raise ApiError("ERR_REGULATORY_HOLD_IRRELEASABLE")
        employer["freeze_state"] = "RELEASED"
        _thaw_records(employer)
        _revive_layouts_after_thaw(employer)
        store.touch(employer)
        return employer
    if outcome == "LAPSE":
        if state == "ACTIVE":
            # A REGULATORY_HOLD freeze cannot be released; lapse is governed by
            # the same hold and is refused while the hold stands (PRD §2.7).
            if employer.get("freeze_reason_code") == "REGULATORY_HOLD":
                raise ApiError("ERR_REGULATORY_HOLD_IRRELEASABLE")
            if employer.get("dispute_open_count") or 0:
                raise ApiError("ERR_INVALID_STATE")
            for request in store.all_rows("verification_requests"):
                if (request.get("current_employer_id") == employer["id"]
                        and request.get("request_state") == "PERMITTED"):
                    raise ApiError("ERR_INVALID_STATE")
            employer["freeze_state"] = "LAPSED"
            employer["freeze_reason_code"] = None
            employer["freeze_requested_at"] = None
            _thaw_records(employer)
            _revive_layouts_after_thaw(employer)
            store.touch(employer)
            return employer
        if state in ("RELEASED", "LAPSED"):
            employer["freeze_state"] = "NONE"
            store.touch(employer)
            return employer
        raise ApiError("ERR_INVALID_STATE")
    raise ApiError("ERR_INVALID_STATE")


def _thaw_records(employer):
    for record in store.all_rows("employment_records"):
        if record.get("employer_id") != employer["id"]:
            continue
        if record.get("currency_state") == "FROZEN":
            record["currency_state"] = "STALE"
            record["frozen_by_employer_version"] = None
            store.touch(record)


# ------------------------------------------------------------------ layouts

def predecessor_layout(employer_id, layout_version):
    candidates = [
        layout for layout in store.all_rows("record_layouts")
        if layout.get("employer_id") == employer_id
        and (layout.get("layout_version") or 0) < layout_version
    ]
    if not candidates:
        return None
    best_version = max(layout["layout_version"] for layout in candidates)
    top = [layout for layout in candidates if layout["layout_version"] == best_version]
    top.sort(key=lambda layout: layout.get("created_at"))
    return top[0]


def register_layout(layout):
    predecessor = predecessor_layout(layout["employer_id"], layout["layout_version"])
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        store.touch(predecessor)
    return layout


def revise_layout(layout, column_map, fiscal_year_start_month):
    status = layout.get("status")
    if status == "SUPERSEDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status == "VERIFIED":
        for batch in store.all_rows("payroll_feed_batches"):
            if (batch.get("record_layout_id") == layout["id"]
                    and batch.get("validation_state") == "RECEIVED"):
                raise ApiError("ERR_INVALID_STATE")
        layout["status"] = "DRAFT"
        layout["verified_at"] = None
    layout["column_map"] = column_map
    if fiscal_year_start_month is not None:
        layout["fiscal_year_start_month"] = fiscal_year_start_month
    count, missing = models.layout_diagnostics(column_map)
    layout["validation_error_count"] = count
    layout["missing_canonical_fields"] = missing
    store.touch(layout)
    return layout


def verify_layout(layout):
    if layout.get("status") == "SUPERSEDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if layout.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if (layout.get("validation_error_count") or 0) != 0:
        raise ApiError("ERR_LAYOUT_MAPPING_INCOMPLETE")
    layout["status"] = "VERIFIED"
    layout["verified_at"] = clock.now()
    store.touch(layout)
    return layout


# ------------------------------------------------------------------ batches

def declare_records(batch, rejected_entries):
    if batch.get("validation_state") == "REJECTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if batch.get("validation_state") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    rejected = int(rejected_entries or 0)
    batch["rejected_record_count"] = rejected
    batch["accepted_record_count"] = (batch.get("record_count") or 0) - rejected
    store.touch(batch)
    return batch


def reject_batch(batch):
    if batch.get("validation_state") == "VALIDATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if batch.get("validation_state") == "REJECTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    batch["validation_state"] = "REJECTED"
    for record in store.all_rows("employment_records"):
        if record.get("payroll_feed_batch_id") == batch["id"]:
            record["currency_state"] = "FROZEN"
            store.touch(record)
    store.touch(batch)
    return batch


def validate_batch(batch, employer):
    if batch.get("validation_state") in ("VALIDATED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if batch.get("validation_state") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    layout = store.get("record_layouts", batch.get("record_layout_id"))
    if layout is None or layout.get("status") != "VERIFIED":
        raise ApiError("ERR_BATCH_LAYOUT_NOT_VERIFIED")
    if (batch.get("rejected_record_count") or 0) != 0:
        raise ApiError("ERR_INVALID_STATE")
    if (batch.get("record_count") or 0) > MAX_BATCH_RECORD_COUNT:
        raise ApiError("ERR_BATCH_RECORD_COUNT_EXCEEDED")
    last = employer.get("last_feed_received_date")
    end = batch.get("pay_period_end_date")
    if last is not None and end is not None and not (end > last):
        raise ApiError("ERR_FEED_NOT_MONOTONIC")

    batch["validation_state"] = "VALIDATED"
    if last is None or (end is not None and end > last):
        employer["last_feed_received_date"] = end

    attached = [r for r in store.all_rows("employment_records")
                if r.get("payroll_feed_batch_id") == batch["id"]]
    gross = 0
    for record in attached:
        record["record_state"] = "VERIFIED"
        record["currency_state"] = "CURRENT"
        calculations.recompute_record(record, employer)
        gross += record.get("annualized_income_cents") or 0
        store.touch(record)
    batch["gross_amount_cents"] = gross

    _refresh_employer_records_currency(employer)

    employer["total_records_contributed"] = (
        (employer.get("total_records_contributed") or 0) + (batch.get("accepted_record_count") or 0)
    )
    _accrue_for_batch(batch, employer)
    store.touch(employer)
    store.touch(batch)
    return batch


def _refresh_employer_records_currency(employer):
    status = calculations.refresh_employer_feed_status(employer)
    if status in ("DELAYED", "STALLED"):
        for record in store.all_rows("employment_records"):
            if record.get("employer_id") != employer["id"]:
                continue
            if record.get("currency_state") == "CURRENT":
                record["currency_state"] = "STALE"
                store.touch(record)
    elif status == "CURRENT":
        for record in store.all_rows("employment_records"):
            if record.get("employer_id") != employer["id"]:
                continue
            if record.get("currency_state") == "STALE":
                record["currency_state"] = "CURRENT"
                store.touch(record)


def _accrue_for_batch(batch, employer):
    count = batch.get("record_count") or 0
    unit, gross = calculations.contributor_rate(count)
    accrual = models.new_compensation_accrual({
        "employer_id": employer["id"],
        "pay_period_end_date": batch.get("pay_period_end_date"),
        "transaction_ref": "batch:%s" % batch["id"],
        "records_count": count,
    })
    accrual["unit_rate_cents"] = unit
    accrual["gross_accrued_cents"] = gross
    store.insert("compensation_accruals", accrual)
    return accrual