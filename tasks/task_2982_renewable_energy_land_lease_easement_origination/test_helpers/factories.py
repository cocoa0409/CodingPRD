"""
Request-payload builders for the Renewable Land Origination API test suite.

Every builder assembles a complete, valid payload and then applies the caller's
overrides as a final dictionary update. Overrides are never accepted as named
parameters alongside the same key in the base dictionary, so a caller can
restate any field — including one the base already sets — without colliding.

Money is always an int count of cents, acreage and rates are always numbers, and
every instant literal is a full ISO-8601 UTC instant rather than a bare date,
because the API distinguishes the two.
"""

from typing import Any, Dict

from .constants import CAPROCK_COUNTY_FIPS

Payload = Dict[str, Any]


def _merge(base: Payload, overrides: Payload) -> Payload:
    """Apply overrides last so any base key can be restated or removed."""
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel meaning "leave this key out of the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Landowners ───────────────────────────────────────

def landowner_payload(**overrides: Any) -> Payload:
    """A registrable landowner."""
    base = {
        "legal_name": "Caprock Wind Holdings LLC",
        "entity_type": "LLC",
        "mailing_state": "TX",
        "contact_email": "land@caprockwind.example",
        "w9_on_file": True,
    }
    return _merge(base, overrides)


def landowner_patch_payload(**overrides: Any) -> Payload:
    """A payables-flag patch."""
    base: Payload = {}
    return _merge(base, overrides)


# ─── Setback rules ────────────────────────────────────

def setback_rule_payload(**overrides: Any) -> Payload:
    """A publishable jurisdiction ordinance."""
    base = {
        "jurisdiction_code": CAPROCK_COUNTY_FIPS,
        "rule_type": "PROPERTY_LINE",
        "setback_feet": 150,
        "encumbrance_rate_per_acre": 0.06,
        "consent_waivable": True,
    }
    return _merge(base, overrides)


def caprock_property_line_rule(**overrides: Any) -> Payload:
    """The Caprock property-line ordinance."""
    return setback_rule_payload(
        **_merge(
            {
                "jurisdiction_code": CAPROCK_COUNTY_FIPS,
                "rule_type": "PROPERTY_LINE",
                "setback_feet": 150,
                "encumbrance_rate_per_acre": 0.06,
                "consent_waivable": True,
            },
            overrides,
        )
    )


def caprock_occupied_dwelling_rule(**overrides: Any) -> Payload:
    """The Caprock occupied-dwelling ordinance."""
    return setback_rule_payload(
        **_merge(
            {
                "jurisdiction_code": CAPROCK_COUNTY_FIPS,
                "rule_type": "OCCUPIED_DWELLING",
                "setback_feet": 500,
                "encumbrance_rate_per_acre": 0.10,
                "consent_waivable": True,
            },
            overrides,
        )
    )


def caprock_public_road_rule(**overrides: Any) -> Payload:
    """The Caprock public-road ordinance, which no consent can waive."""
    return setback_rule_payload(
        **_merge(
            {
                "jurisdiction_code": CAPROCK_COUNTY_FIPS,
                "rule_type": "PUBLIC_ROAD",
                "setback_feet": 100,
                "encumbrance_rate_per_acre": 0.04,
                "consent_waivable": False,
            },
            overrides,
        )
    )


# ─── Parcels ──────────────────────────────────────────

def parcel_payload(landowner_id: str, **overrides: Any) -> Payload:
    """
    A registrable parcel.

    The default is the canonical Caprock tract: 125.00 gross acres in county
    48453 with a grade-B title, a slope inside the zero-exclusion tier and
    agricultural zoning.
    """
    base = {
        "apn": "R-1188-004",
        "county_fips": CAPROCK_COUNTY_FIPS,
        "landowner_id": landowner_id,
        "gross_acres": 125.00,
        "interconnection_distance_km": 3.50,
        "resource_capacity_factor": 0.38,
        "slope_pct": 4.0,
        "title_condition_grade": "B",
        "zoning_code": "AG2",
    }
    return _merge(base, overrides)


# ─── Neighbor consents ────────────────────────────────

def neighbor_consent_payload(
    parcel_id: str, setback_rule_id: str, **overrides: Any
) -> Payload:
    """A consent request against one waivable ordinance."""
    base = {
        "parcel_id": parcel_id,
        "setback_rule_id": setback_rule_id,
        "neighbor_name": "H. Alvarado",
        "consent_expiry_days": 60,
    }
    return _merge(base, overrides)


# ─── Title curative items ─────────────────────────────

def curative_item_payload(parcel_id: str, **overrides: Any) -> Payload:
    """A raisable title defect."""
    base = {
        "parcel_id": parcel_id,
        "item_type": "MINERAL_SEVERANCE",
        "severity": "BLOCKING",
        "curative_cost_cents": 450000,
    }
    return _merge(base, overrides)


def clear_curative_payload(**overrides: Any) -> Payload:
    """A resolution payload for clearing a defect."""
    base: Payload = {}
    return _merge(base, overrides)


def waive_curative_payload(**overrides: Any) -> Payload:
    """A resolution payload for waiving a defect."""
    base = {"waiver_note": "title indemnity accepted by counsel of record"}
    return _merge(base, overrides)


# ─── Option agreements ────────────────────────────────

def option_payload(
    parcel_id: str, landowner_id: str, expected_parcel_version: int, **overrides: Any
) -> Payload:
    """
    A draft option on a qualified parcel.

    The default is the per-acre structure, whose royalty rate is zero because no
    royalty applies to it.
    """
    base = {
        "parcel_id": parcel_id,
        "landowner_id": landowner_id,
        "expected_parcel_version": expected_parcel_version,
        "option_term_days": 365,
        "option_fee_per_acre_cents": 2500,
        "extension_count_allowed": 1,
        "extension_fee_per_acre_cents": 3000,
        "rent_structure_type": "PER_ACRE",
        "base_rent_per_acre_cents": 118000,
        "royalty_rate_bps": 0,
        "escalator_pct_bps": 200,
        "escalator_mode": "SIMPLE",
    }
    return _merge(base, overrides)


def royalty_hybrid_option_payload(
    parcel_id: str, landowner_id: str, expected_parcel_version: int, **overrides: Any
) -> Payload:
    """A draft option on the royalty-hybrid structure."""
    return option_payload(
        parcel_id,
        landowner_id,
        expected_parcel_version,
        **_merge(
            {
                "rent_structure_type": "ROYALTY_HYBRID",
                "base_rent_per_acre_cents": 120000,
                "royalty_rate_bps": 350,
                "escalator_pct_bps": 200,
                "escalator_mode": "COMPOUND",
                "extension_count_allowed": 2,
            },
            overrides,
        ),
    )


def counter_payload(**overrides: Any) -> Payload:
    """A landowner counter over the counterable terms."""
    base = {"option_fee_per_acre_cents": 2600}
    return _merge(base, overrides)


def revise_payload(**overrides: Any) -> Payload:
    """A developer revision over the revisable terms."""
    base = {"base_rent_per_acre_cents": 121000}
    return _merge(base, overrides)


def exercise_payload(
    exercise_notice_reference: str = "NOL-2982-0001", **overrides: Any
) -> Payload:
    """An exercise notice, which carries exactly one field."""
    base = {"exercise_notice_reference": exercise_notice_reference}
    return _merge(base, overrides)


def withdraw_payload(**overrides: Any) -> Payload:
    """A withdrawal, which always carries the reason recorded on the instrument."""
    base = {
        "withdraw_reason": "interconnection queue position lost; releasing the parcel",
        "refund_extension_fees": False,
    }
    return _merge(base, overrides)


# ─── Corridors and crossings ──────────────────────────

def corridor_payload(**overrides: Any) -> Payload:
    """A planned transmission corridor."""
    base = {
        "route_name": "Bluestem 345kV Collector",
        "total_length_m": 5000,
        "voltage_class": "COLLECTION_34_5KV",
        "buffer_m": 50,
    }
    return _merge(base, overrides)


def crossing_payload(corridor_id: str, parcel_id: str, **overrides: Any) -> Payload:
    """A proposed crossing over one station range and one occupancy window."""
    base = {
        "corridor_id": corridor_id,
        "parcel_id": parcel_id,
        "crossing_kind": "COLLECTION_LINE",
        "station_start_m": 1000,
        "station_end_m": 1500,
        "occupancy_window_start": "2026-09-01T00:00:00Z",
        "occupancy_window_end": "2026-10-01T00:00:00Z",
    }
    return _merge(base, overrides)


# ─── Site-access bookings ─────────────────────────────

def booking_payload(parcel_id: str, **overrides: Any) -> Payload:
    """A site-access booking for a single crew."""
    base = {
        "parcel_id": parcel_id,
        "purpose": "TITLE_SURVEY",
        "window_start": "2026-08-10T08:00:00Z",
        "window_end": "2026-08-10T16:00:00Z",
        "crew_count": 1,
    }
    return _merge(base, overrides)


def cancel_booking_payload(**overrides: Any) -> Payload:
    """A booking cancellation."""
    base: Payload = {}
    return _merge(base, overrides)


# ─── Lease actions ────────────────────────────────────

def post_security_payload(amount_cents: int, **overrides: Any) -> Payload:
    """A security posting of an exact number of cents."""
    base = {"amount_cents": amount_cents}
    return _merge(base, overrides)


def record_memo_payload(**overrides: Any) -> Payload:
    """A recording payload carrying the county instrument number."""
    base = {"recording_instrument_no": "2026-0044821"}
    return _merge(base, overrides)


# ─── Rent invoices ────────────────────────────────────

def invoice_payload(
    expected_lease_agreement_version: int,
    period_year: int = 1,
    production_mwh: float = 90000,
    **overrides: Any,
) -> Payload:
    """A draft rent invoice for one period year."""
    base = {
        "expected_lease_agreement_version": expected_lease_agreement_version,
        "period_year": period_year,
        "production_mwh": production_mwh,
    }
    return _merge(base, overrides)


def pay_invoice_payload(paid_amount_cents: int, **overrides: Any) -> Payload:
    """A payment of an exact number of cents against an issued invoice."""
    base = {"paid_amount_cents": paid_amount_cents}
    return _merge(base, overrides)


def void_invoice_payload(**overrides: Any) -> Payload:
    """A void carrying its reason."""
    base = {"void_reason": "re-raised after the memorandum was recorded"}
    return _merge(base, overrides)


# ─── Parcel shapes reused across scenarios ────────────

def rescreen_payload(screen_mode: str = "FIELD_VERIFIED", **overrides: Any) -> Payload:
    """
    A rescreen request naming the variant to use.

    Re-screening takes no expected-version input: only two writes in the whole
    API carry a parent version, and this is not one of them.
    """
    base = {"screen_mode": screen_mode}
    return _merge(base, overrides)


def clock_payload(current_utc: str, **overrides: Any) -> Payload:
    """A logical-clock advance."""
    base = {"current_utc": current_utc}
    return _merge(base, overrides)


def projection_params(
    period_year: int = 1, production_mwh: float = 90000, **overrides: Any
) -> Payload:
    """Query inputs for the non-persisting rent projection."""
    base = {"period_year": period_year, "production_mwh": production_mwh}
    return _merge(base, overrides)


__all__ = [
    "OMIT",
    "landowner_payload",
    "landowner_patch_payload",
    "setback_rule_payload",
    "caprock_property_line_rule",
    "caprock_occupied_dwelling_rule",
    "caprock_public_road_rule",
    "parcel_payload",
    "neighbor_consent_payload",
    "curative_item_payload",
    "clear_curative_payload",
    "waive_curative_payload",
    "option_payload",
    "royalty_hybrid_option_payload",
    "counter_payload",
    "revise_payload",
    "exercise_payload",
    "withdraw_payload",
    "corridor_payload",
    "crossing_payload",
    "booking_payload",
    "cancel_booking_payload",
    "post_security_payload",
    "record_memo_payload",
    "invoice_payload",
    "pay_invoice_payload",
    "void_invoice_payload",
    "rescreen_payload",
    "clock_payload",
    "projection_params",
]
