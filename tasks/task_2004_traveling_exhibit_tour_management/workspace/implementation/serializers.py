"""Explicit per-entity serializers — output carries exactly the fields the
entity model declares (input + system + computed). Window timestamps echo
back the exact strings supplied at creation.
"""

_COMMON = ("id", "created_at", "updated_at", "version")

TOUR_FIELDS = ("title", "exhibit_code", "crate_count", "declared_value_cents",
               "refurbishment_gap_days", "status", "total_billed_cents",
               "total_collected_cents", "total_waived_cents") + _COMMON

VENUE_FIELDS = ("name", "city", "climate_controlled", "max_gallery_sqm",
                "local_sponsorship_cap_cents") + _COMMON

STOP_FIELDS = ("tour_id", "venue_id", "seq", "install_start", "open_date",
               "close_date", "teardown_end", "projected_attendance",
               "actual_attendance", "status", "supervision_required") + _COMMON

CONTRACT_FIELDS = ("tour_stop_id", "base_fee_cents", "sponsorship_credit_cents",
                   "status", "provisional_fee_cents", "final_fee_cents",
                   "amount_paid_cents") + _COMMON

CRATE_FIELDS = ("tour_id", "crate_label", "contents_value_cents",
                "location_status", "current_stop_id", "condition_score") + _COMMON

SHIPMENT_FIELDS = ("tour_id", "origin_stop_id", "destination_stop_id",
                   "depart_at", "arrive_at", "carrier_name", "status",
                   "crate_ids") + _COMMON

REPORT_FIELDS = ("shipment_id", "crate_id", "inspector_name", "phase",
                 "surface_score", "structural_score", "seal_intact", "status",
                 "composite_score") + _COMMON

CLAIM_FIELDS = ("shipment_id", "condition_report_id", "claimed_amount_cents",
                "line_items", "status", "assessed_payout_cents") + _COMMON

KIT_FIELDS = ("tour_stop_id", "language_count", "sponsor_logo_slots",
              "press_release_sent", "status", "production_cost_cents") + _COMMON

CERT_FIELDS = ("tour_id", "tour_stop_id", "insurer_name", "coverage_cents",
               "effective_from", "effective_to", "status") + _COMMON


def _pick(resource, fields):
    return {f: resource.get(f) for f in fields}


def tour_out(r):
    return _pick(r, TOUR_FIELDS)


def venue_out(r):
    return _pick(r, VENUE_FIELDS)


def stop_out(r):
    return _pick(r, STOP_FIELDS)


def contract_out(r):
    return _pick(r, CONTRACT_FIELDS)


def crate_out(r):
    return _pick(r, CRATE_FIELDS)


def shipment_out(r):
    return _pick(r, SHIPMENT_FIELDS)


def report_out(r):
    return _pick(r, REPORT_FIELDS)


def claim_out(r):
    return _pick(r, CLAIM_FIELDS)


def kit_out(r):
    return _pick(r, KIT_FIELDS)


def cert_out(r):
    return _pick(r, CERT_FIELDS)
