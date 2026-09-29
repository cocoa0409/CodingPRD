"""Request-payload builders for the presort bureau API.

Every builder returns a plain dict ready to be sent as a JSON body, with the
contract's own field names and its own types:

* money is an integer count of whole cents — ``1250``, never ``"1250"``;
* rates in basis points and per-piece rates in mills are integers too;
* piece counts and day counts are integers;
* a declared per-piece weight is a decimal number of ounces;
* every instant is a full ISO 8601 UTC value with exactly three fractional
  digits and a trailing ``Z``, because that is the only instant shape the
  contract serialises or accepts — a date-only string is not an instant.

Optional fields are omitted unless the caller passes them, so that a builder
can be used both to exercise a default and to override it.
"""

from typing import Dict, List, Optional

from test_helpers.constants import (
    DEFAULT_BILLING_TERMS,
)

# ─── Instant helpers ──────────────────────────────────────────────────────


def instant(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    millis: int = 0,
) -> str:
    """An ISO 8601 UTC instant with exactly three fractional digits."""
    return (
        f"{year:04d}-{month:02d}-{day:02d}"
        f"T{hour:02d}:{minute:02d}:{second:02d}.{millis:03d}Z"
    )


def august_2026(day: int, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """A convenience instant inside the month every fixture chain runs in."""
    return instant(2026, 8, day, hour, minute, second)


# The billing period covering the whole of the fixture month, as a closed
# interval: both endpoints belong to the period.
AUGUST_2026_START = instant(2026, 8, 1, 0, 0, 0)
AUGUST_2026_END = instant(2026, 8, 31, 23, 59, 59)
SEPTEMBER_2026_START = instant(2026, 9, 1, 0, 0, 0)
SEPTEMBER_2026_END = instant(2026, 9, 30, 23, 59, 59)

# An annual permit fee paid well past every fixture instant.
FEE_PAID_THROUGH_2027 = instant(2027, 1, 31, 23, 59, 59)


# ─── Clients ──────────────────────────────────────────────────────────────


def client_payload(
    name: str = "Acme Direct",
    client_code: str = "ACME",
    service_fee_rate_per_thousand_cents: int = 900,
    billing_terms: Optional[str] = None,
    commingle_opt_in: Optional[bool] = None,
) -> Dict:
    """A client registration. The fee rate is whole cents per thousand pieces."""
    payload: Dict = {
        "name": name,
        "client_code": client_code,
        "service_fee_rate_per_thousand_cents": service_fee_rate_per_thousand_cents,
    }
    if billing_terms is not None:
        payload["billing_terms"] = billing_terms
    if commingle_opt_in is not None:
        payload["commingle_opt_in"] = commingle_opt_in
    return payload


def client_status_payload(status: str, reason: Optional[str] = None) -> Dict:
    payload: Dict = {"status": status}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ─── Permit accounts ──────────────────────────────────────────────────────


def permit_account_payload(
    client_id: str,
    permit_number: str = "PI-100100",
    payment_method: str = "PERMIT_IMPRINT",
    annual_fee_paid_through_utc: str = FEE_PAID_THROUGH_2027,
) -> Dict:
    return {
        "client_id": client_id,
        "permit_number": permit_number,
        "payment_method": payment_method,
        "annual_fee_paid_through_utc": annual_fee_paid_through_utc,
    }


def funding_payload(
    amount_cents: int,
    expected_permit_account_version: int,
    reference: Optional[str] = None,
) -> Dict:
    """A deposit of whole cents guarded by the account's current version."""
    payload: Dict = {
        "amount_cents": amount_cents,
        "expected_permit_account_version": expected_permit_account_version,
    }
    if reference is not None:
        payload["reference"] = reference
    return payload


def permit_status_payload(status: str, reason: Optional[str] = None) -> Dict:
    payload: Dict = {"status": status}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ─── Mail jobs ────────────────────────────────────────────────────────────


def mail_job_payload(
    client_id: str,
    permit_account_id: str,
    mail_class: str = "MARKETING_MAIL",
    processing_category: str = "LETTERS",
    declared_piece_count: int = 1250,
    declared_weight_oz_per_piece: float = 1.2,
) -> Dict:
    return {
        "client_id": client_id,
        "permit_account_id": permit_account_id,
        "mail_class": mail_class,
        "processing_category": processing_category,
        "declared_piece_count": declared_piece_count,
        "declared_weight_oz_per_piece": declared_weight_oz_per_piece,
    }


def hygiene_run_payload(
    submitted_piece_count: int = 1250,
    cass_matched_count: int = 1235,
    ncoa_move_updated_count: int = 40,
    undeliverable_removed_count: int = 50,
    move_update_age_days: int = 30,
) -> Dict:
    """An address hygiene pass. Every count is a whole number of pieces and the
    move-update age is a whole number of days."""
    return {
        "submitted_piece_count": submitted_piece_count,
        "cass_matched_count": cass_matched_count,
        "ncoa_move_updated_count": ncoa_move_updated_count,
        "undeliverable_removed_count": undeliverable_removed_count,
        "move_update_age_days": move_update_age_days,
    }


def cancel_payload(reason: str = "client withdrew the mailing") -> Dict:
    return {"reason": reason}


# ─── Entry facilities ─────────────────────────────────────────────────────


def entry_facility_payload(
    facility_code: str = "SCF-021",
    facility_type: str = "SCF",
    zip3: str = "021",
    dock_capacity_pallets_per_slot: int = 12,
    drop_ship_discount_bp: int = 300,
    served_zip3_list: Optional[List[str]] = None,
) -> Dict:
    """An entry point. The drop-ship discount is in basis points."""
    return {
        "facility_code": facility_code,
        "facility_type": facility_type,
        "zip3": zip3,
        "dock_capacity_pallets_per_slot": dock_capacity_pallets_per_slot,
        "drop_ship_discount_bp": drop_ship_discount_bp,
        "served_zip3_list": (
            ["021", "022"] if served_zip3_list is None else served_zip3_list
        ),
    }


def facility_status_payload(status: str) -> Dict:
    return {"status": status}


# ─── Commingle batches ────────────────────────────────────────────────────


def commingle_batch_payload(
    entry_facility_id: str,
    mail_class: str = "MARKETING_MAIL",
    processing_category: str = "LETTERS",
) -> Dict:
    return {
        "mail_class": mail_class,
        "processing_category": processing_category,
        "entry_facility_id": entry_facility_id,
    }


def batch_member_payload(mail_job_id: str) -> Dict:
    return {"mail_job_id": mail_job_id}


def sort_container_payload(
    container_type: str = "TRAY",
    destination_zip3: str = "021",
    sort_level: str = "FIVE_DIGIT",
    piece_count: int = 1000,
) -> Dict:
    return {
        "container_type": container_type,
        "destination_zip3": destination_zip3,
        "sort_level": sort_level,
        "piece_count": piece_count,
    }


# ─── Drop shipments ───────────────────────────────────────────────────────


def drop_shipment_payload(
    commingle_batch_id: str,
    entry_facility_id: str,
    window_start_utc: str,
    window_end_utc: str,
    pallet_count: int = 2,
) -> Dict:
    """An appointment. Both window endpoints are full instants; the window is
    half-open, so the end instant is not part of the appointment."""
    return {
        "commingle_batch_id": commingle_batch_id,
        "entry_facility_id": entry_facility_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "pallet_count": pallet_count,
    }


# ─── Postage statements ───────────────────────────────────────────────────


def postage_statement_payload(
    commingle_batch_id: str, permit_account_id: str, expected_batch_version: int
) -> Dict:
    """A statement filing guarded by the batch's current version."""
    return {
        "commingle_batch_id": commingle_batch_id,
        "permit_account_id": permit_account_id,
        "expected_batch_version": expected_batch_version,
    }


def finding_payload(
    finding_type: str = "CONTAINER_NOT_QUALIFIED", affected_piece_count: int = 90
) -> Dict:
    return {
        "finding_type": finding_type,
        "affected_piece_count": affected_piece_count,
    }


def verify_payload(outcome: str = "ACCEPT") -> Dict:
    return {"outcome": outcome}


def void_payload(reason: str = "client pulled the job from the drop") -> Dict:
    return {"reason": reason}


# ─── Service-level records ────────────────────────────────────────────────


def delivery_scan_payload(actual_delivery_days: int, scanned_at_utc: str) -> Dict:
    """A delivery observation: a whole number of days and a full instant."""
    return {
        "actual_delivery_days": actual_delivery_days,
        "scanned_at_utc": scanned_at_utc,
    }


# ─── Invoices ─────────────────────────────────────────────────────────────


def invoice_payload(
    period_start_utc: str = AUGUST_2026_START,
    period_end_utc: str = AUGUST_2026_END,
) -> Dict:
    """A billing period as a closed interval of instants."""
    return {
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
    }


def payment_payload(amount_cents: int) -> Dict:
    """A payment of whole cents."""
    return {"amount_cents": amount_cents}


# ─── Named fixture payloads used by more than one chain ───────────────────

ACME_CLIENT = client_payload(
    name="Acme Direct", client_code="ACME", service_fee_rate_per_thousand_cents=900
)
BORE_CLIENT = client_payload(
    name="Borealis Mailers",
    client_code="BORE",
    service_fee_rate_per_thousand_cents=2200,
)
HOUSE_CLIENT = client_payload(
    name="Bureau House Account",
    client_code="PSBUREAU",
    service_fee_rate_per_thousand_cents=1,
    commingle_opt_in=False,
)

DEFAULT_BILLING_TERMS_VALUE = DEFAULT_BILLING_TERMS
