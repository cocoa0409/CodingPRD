"""Licensing arithmetic: royalty schedules, fee gate, scope derivation,
territory characteristics, delivery activation mode and education credits.

Sources: PRD.md 3.9, 3.10 and SCAFFOLD.yaml `license_royalty_schedule`,
`license_territory_scope_derivation`, `education_credit_conversion`,
`assistant_interpretation_entitlement`.
"""

from money import Decimal, as_float, cents, dec, round_half_away, round_half_up
import store

MIN_SALES_UNITS = 4
BAND1_RATE = Decimal("0.90")
BAND2_FIXED = Decimal("450000")
BAND2_RATE = Decimal("0.55")
BAND3_FIXED = Decimal("2475000")
BAND3_RATE = Decimal("0.25")

PAYER_TIER_RATES = {
    "TIER_1": Decimal("0.75"),
    "TIER_2": Decimal("1.15"),
    "TIER_3": Decimal("1.50"),
}

ANCILLARY_PUBLICATION_CODES = []


# --- royalty schedule ------------------------------------------------------

def royalty_fee(license_record):
    """Two schedules, selected by the presence of `payer_revenue_tier`.

    When the tier is absent the three-band schedule applies and
    `vendor_worldwide` does not change the fee.  When `payer_revenue_tier` is
    present the revenue-tier schedule replaces the band schedule entirely and
    `vendor_worldwide` is ignored.
    """
    tier = license_record.get("payer_revenue_tier")
    if tier:
        rate = PAYER_TIER_RATES.get(tier)
        base = dec(license_record.get("base_fee_cents"))
        if rate is None:
            return as_float(round_half_up(base, 2))
        return as_float(round_half_up(rate * base, 2))

    units = dec(license_record.get("sales_unit_count"))
    if units <= Decimal("500000"):
        return int(cents(units * BAND1_RATE))
    if units <= Decimal("5000000"):
        return int(cents(BAND2_FIXED + (units - Decimal("500000")) * BAND2_RATE))
    return int(cents(
        BAND2_FIXED + BAND3_FIXED + (units - Decimal("5000000")) * BAND3_RATE
    ))


def recompute_royalty(license_record):
    license_record["royalty_fee_cents"] = royalty_fee(license_record)
    return license_record["royalty_fee_cents"]


def recompute_fee_gate(license_record):
    """At least 4 units yields PASS; below 4 yields BELOW_MINIMUM."""
    units = dec(license_record.get("sales_unit_count"))
    license_record["fee_threshold_gate_status"] = (
        "PASS" if units >= Decimal(MIN_SALES_UNITS) else "BELOW_MINIMUM"
    )
    return license_record["fee_threshold_gate_status"]


# --- scope derivation ------------------------------------------------------

def scope_score(license_record):
    score = 0
    if license_record.get("agreement_status") == "ACTIVE":
        score += 1
    territory_id = license_record.get("territory_id")
    if territory_id:
        territory = store.territories.get(territory_id)
        if territory is not None and bool(territory.get("can_license")):
            score += 1
    if license_record.get("licensee_type") == "VENDOR" and bool(
        license_record.get("vendor_worldwide")
    ):
        score += 1
    return score


def scope_for_score(license_record, score):
    if score == 0:
        return "INTERNAL_ONLY"
    if bool(license_record.get("vendor_worldwide")):
        return "WORLDWIDE"
    return "US_ONLY"


def recompute_scope(license_record, frozen=False):
    """Recompute `distribution_scope` from the score and store it.

    Suspension recomputes the scope and then freezes it at its last value;
    termination forces INTERNAL_ONLY regardless of score.
    """
    score = scope_score(license_record)
    new_scope = scope_for_score(license_record, score)
    if frozen:
        current = license_record.get("distribution_scope")
        if current is not None:
            new_scope = current
    license_record["distribution_scope"] = new_scope
    return new_scope


def recompute_scope_internal_only(license_record):
    license_record["distribution_scope"] = "INTERNAL_ONLY"
    return "INTERNAL_ONLY"


def recompute_ancillary(license_record):
    license_record["ancillary_publication_codes"] = list(ANCILLARY_PUBLICATION_CODES)
    return license_record["ancillary_publication_codes"]


# --- territory characteristics --------------------------------------------

def territory_characteristics(territory):
    """Derive `can_license`, `distribution_channel`, `site_exception`,
    `transaction_set_required` and `activation_details` from method and EDI
    payer-network membership (PRD.md 3.9)."""
    method = territory.get("method")
    on_edi = bool(territory.get("edi_payer_network"))

    can_license = method == "SITE"
    if method == "SITE":
        channel = "SITE"
    elif on_edi:
        channel = "EDI"
    else:
        channel = "PRINT_AND_ELECTRONIC"

    site_exception = method == "SITE"
    transaction_set_required = channel == "EDI"

    if site_exception:
        activation_details = {
            "electronic_format_required": False,
            "media_required": False,
        }
    else:
        activation_details = {
            "electronic_format_required": True,
            "media_required": True,
        }

    territory["can_license"] = can_license
    territory["distribution_channel"] = channel
    territory["site_exception"] = site_exception
    territory["transaction_set_required"] = transaction_set_required
    territory["activation_details"] = activation_details
    return territory


# --- delivery --------------------------------------------------------------

def activation_mode(channel, format_params):
    """`SITE`, `MEDIA` or `ELECTRONIC`, derived from the channel and the format
    parameters (PRD.md 3.10)."""
    format_params = format_params or {}
    if channel == "SITE":
        return "SITE"
    if format_params.get("media"):
        return "MEDIA"
    if format_params.get("electronic_format") or channel == "EDI":
        return "ELECTRONIC"
    return "ELECTRONIC"


def metadatschema_requires_qualifier(territory):
    """A version qualifier is required by the 2026.1 or later metadata schema."""
    if territory is None:
        return True
    version = territory.get("metadata_schema_version")
    if version is None:
        return True
    try:
        major, minor = str(version).split(".")
        return (int(major), int(minor)) >= (2026, 1)
    except (ValueError, AttributeError):
        return True


# --- education -------------------------------------------------------------

def education_credits(clock_hours):
    """Clock hours over two, rounded to one decimal place, half away from zero.

    At or below 1 clock hour the credit is 0.5 regardless of the division; at
    6 or more the derived credit carries through unadjusted; in all cases the
    derived credit is capped at 2.0.  Neither `assistant_targeted` nor the
    licence is consulted.
    """
    hours = dec(clock_hours)
    derived = round_half_away(hours / Decimal(2), 1)
    if hours <= Decimal(1):
        derived = Decimal("0.5")
    if derived > Decimal("2.0"):
        derived = Decimal("2.0")
    awarded = round_half_away(derived, 1)
    return as_float(awarded), as_float(round_half_up(awarded, 0))


# --- interpretation entitlement -------------------------------------------

def interpretation_entitlement(license_record):
    """Entitled when the requesting licence is ACTIVE, and also when it is an
    EDUCATOR licence in any non-terminated status.  Not entitled when the class
    is PROVIDER, and not entitled when the licence is TERMINATED."""
    if license_record is None:
        return "NOT_ENTITLED"
    status = license_record.get("agreement_status")
    licensee_type = license_record.get("licensee_type")

    if status == "TERMINATED":
        return "NOT_ENTITLED"
    if licensee_type == "PROVIDER":
        return "NOT_ENTITLED"
    if status == "ACTIVE":
        return "ENTITLED"
    if licensee_type == "EDUCATOR" and status != "TERMINATED":
        return "ENTITLED"
    return "NOT_ENTITLED"