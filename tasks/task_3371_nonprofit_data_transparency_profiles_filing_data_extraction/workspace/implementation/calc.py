"""Every calculation rule from SCAFFOLD 1.3 / PRD 3.

Pure functions over plain values: no store access, no request context.  All
money is integer cents; the single rounding primitive is round-half-up (an
exact .5 fraction rounds away from zero) and rounding is never deferred.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# --- rounding primitives -------------------------------------------------

def round_half_up(value, places):
    """Round a Decimal (or int/str) half up to ``places`` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def to_int(value):
    return int(round_half_up(value, 0))


# --- 1.3 extract_field_normalization ------------------------------------

UNIT_MULTIPLIER = {
    "USD_WHOLE": Decimal(100),
    "USD_THOUSANDS": Decimal(100000),
    "USD_MILLIONS": Decimal(100000000),
    "PLAIN_INTEGER": Decimal(100),
}

CONFIDENCE_BY_FORMAT = {
    "USD_WHOLE": Decimal("99.0"),
    "PLAIN_INTEGER": Decimal("99.0"),
    "USD_THOUSANDS": Decimal("92.0"),
    "USD_MILLIONS": Decimal("85.0"),
}

RAW_FORMATS = ("USD_WHOLE", "USD_THOUSANDS", "USD_MILLIONS", "PLAIN_INTEGER")


def parse_raw_decimal(raw_value):
    """The decimal a raw_value denotes, or None when it is unparseable."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return Decimal(str(raw_value))
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def normalize_cents(raw_value, raw_format):
    """round_half_up(decimal(raw_value) * UNIT_MULTIPLIER[raw_format], 0)."""
    amount = parse_raw_decimal(raw_value)
    if amount is None:
        return None
    multiplier = UNIT_MULTIPLIER.get(raw_format)
    if multiplier is None:
        return None
    return to_int(amount * multiplier)


def confidence_for(raw_format):
    return CONFIDENCE_BY_FORMAT.get(raw_format)


def mean_confidence(values):
    """Mean of the rows' confidence_pct values, to one decimal place."""
    if not values:
        return None
    total = Decimal(0)
    for value in values:
        total += value if isinstance(value, Decimal) else Decimal(str(value))
    return float(round_half_up(total / Decimal(len(values)), 1))


# --- 1.3 form_version_line_membership -----------------------------------

FORM_VERSION_LINE_MAP = {
    2019: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING"],
    2020: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING", "GOV_GRANTS"],
    2021: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING", "GOV_GRANTS"],
    2022: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING", "GOV_GRANTS", "NET_ASSETS"],
    2023: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING", "GOV_GRANTS", "NET_ASSETS"],
    2024: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING", "GOV_GRANTS", "NET_ASSETS", "CRYPTO_HOLDINGS"],
}

SUPPORTED_FORM_VERSION_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)

# --- 1.3 license_permitted_use_check ------------------------------------

PERMITTED_USES_BY_TIER = {
    "RESEARCHER": ("AGGREGATE_RESEARCH",),
    "FUNDER": ("AGGREGATE_RESEARCH", "GRANTMAKING_DUE_DILIGENCE"),
    "PLATFORM": (
        "AGGREGATE_RESEARCH",
        "GRANTMAKING_DUE_DILIGENCE",
        "PLATFORM_REDISTRIBUTION",
        "MARKETING_PROSPECTING",
    ),
}

PERMITTED_USES = (
    "AGGREGATE_RESEARCH",
    "GRANTMAKING_DUE_DILIGENCE",
    "PLATFORM_REDISTRIBUTION",
    "MARKETING_PROSPECTING",
)

TIERS = ("RESEARCHER", "FUNDER", "PLATFORM")

# --- 1.3 license_annual_fee_cents ---------------------------------------

TIER_BASE_FEE_CENTS = {"RESEARCHER": 500000, "FUNDER": 2500000, "PLATFORM": 10000000}
TIER_INCLUDED_RECORDS = {"RESEARCHER": 10000, "FUNDER": 100000, "PLATFORM": 1000000}
TIER_OVERAGE_RATE_CENTS = {"RESEARCHER": 5, "FUNDER": 2, "PLATFORM": 1}
QUOTA_HARD_CAP_MULTIPLIER = 4


def license_fee_cents(tier, overage_source_records):
    """base + max(0, records - included) * overage_rate (integer cents)."""
    included = TIER_INCLUDED_RECORDS[tier]
    overage = max(0, overage_source_records - included)
    return TIER_BASE_FEE_CENTS[tier] + overage * TIER_OVERAGE_RATE_CENTS[tier]


# --- 1.3 completeness ledger (PRD 3.2) ----------------------------------

DIMENSION_WEIGHTS = {
    "PROGRAMS": Decimal("0.15"),
    "FINANCES": Decimal("0.25"),
    "LEADERSHIP": Decimal("0.20"),
    "DEMOGRAPHICS": Decimal("0.15"),
    "MISSION": Decimal("0.10"),
    "GOVERNANCE": Decimal("0.15"),
}

DISCLOSURE_WEIGHTS = {
    "PROGRAMS": Decimal("0.15"),
    "FINANCES": Decimal("0.30"),
    "LEADERSHIP": Decimal("0.20"),
    "DEMOGRAPHICS": Decimal("0.15"),
    "MISSION": Decimal("0.10"),
    "GOVERNANCE": Decimal("0.10"),
}

ZERO = Decimal("0.0")
HALF = Decimal("0.5")
ONE = Decimal("1.0")


def _text_present(value):
    return isinstance(value, str) and value.strip() != ""


def mission_present(org):
    return _text_present(org.get("mission_statement"))


def ntee_present(org):
    return org.get("ntee_code") is not None and str(org.get("ntee_code")) != ""


def mission_dimension(org):
    mission = mission_present(org)
    ntee = ntee_present(org)
    if mission and ntee:
        return ONE
    if mission or ntee:
        return HALF
    return ZERO


def _active_programs(programs):
    return [p for p in programs if p.get("status") == "ACTIVE"]


def _active_leaders(leaders):
    return [l for l in leaders if l.get("status") == "ACTIVE"]


def provisional_dimensions(org, programs, filings, leaders, demographics):
    active_programs = _active_programs(programs)
    if not active_programs:
        programs_score = ZERO
    elif any(p.get("subject_code") is not None for p in active_programs):
        programs_score = ONE
    else:
        programs_score = HALF

    finances_rows = [f for f in filings if f.get("status") in ("NORMALIZED", "DISPUTED")]
    if not finances_rows:
        finances_score = ZERO
    elif any(f.get("status") == "NORMALIZED" and f.get("total_revenue_cents") is not None
             for f in finances_rows):
        finances_score = ONE
    else:
        finances_score = HALF

    active_leaders = _active_leaders(leaders)
    officers = [l for l in active_leaders if l.get("is_officer") is True]
    if not active_leaders:
        leadership_score = ZERO
    elif len(officers) >= 3:
        leadership_score = ONE
    elif len(officers) in (1, 2):
        leadership_score = HALF
    else:
        leadership_score = ZERO

    if not demographics:
        demographics_score = ZERO
    elif any(d.get("disclosure_level") == "PUBLIC" for d in demographics):
        demographics_score = ONE
    else:
        demographics_score = HALF

    if not officers:
        governance_score = ZERO
    else:
        independents = [l for l in officers if l.get("is_independent") is True]
        if len(independents) >= 3:
            governance_score = ONE
        elif len(independents) in (1, 2):
            governance_score = HALF
        else:
            governance_score = ZERO

    return {
        "PROGRAMS": programs_score,
        "FINANCES": finances_score,
        "LEADERSHIP": leadership_score,
        "DEMOGRAPHICS": demographics_score,
        "MISSION": mission_dimension(org),
        "GOVERNANCE": governance_score,
    }


def verified_dimensions(org, programs, filings, leaders, demographics):
    active_programs = _active_programs(programs)
    if not active_programs:
        programs_score = ZERO
    elif (all(p.get("is_verified") is True for p in active_programs)
          and any(p.get("subject_code") is not None for p in active_programs)):
        programs_score = ONE
    else:
        programs_score = HALF

    normalized = [f for f in filings if f.get("status") == "NORMALIZED"]
    finance_rows = [f for f in filings if f.get("status") in ("NORMALIZED", "DISPUTED")]
    if any(f.get("is_verified") is True for f in normalized):
        finances_score = ONE
    elif finance_rows:
        finances_score = HALF
    else:
        finances_score = ZERO

    active_leaders = _active_leaders(leaders)
    officers = [l for l in active_leaders if l.get("is_officer") is True]
    if len(officers) >= 3 and all(l.get("is_verified") is True for l in officers):
        leadership_score = ONE
    elif active_leaders:
        leadership_score = HALF
    else:
        leadership_score = ZERO

    if any(d.get("disclosure_level") == "PUBLIC" and d.get("is_verified") is True
           for d in demographics):
        demographics_score = ONE
    elif demographics:
        demographics_score = HALF
    else:
        demographics_score = ZERO

    mission = mission_present(org)
    ntee = ntee_present(org)
    if mission and ntee and org.get("ntee_code_verified") is True:
        mission_score = ONE
    elif mission or ntee:
        mission_score = HALF
    else:
        mission_score = ZERO

    independents = [l for l in officers if l.get("is_independent") is True]
    if len(independents) >= 3 and all(l.get("is_verified") is True for l in officers):
        governance_score = ONE
    elif officers:
        governance_score = HALF
    else:
        governance_score = ZERO

    return {
        "PROGRAMS": programs_score,
        "FINANCES": finances_score,
        "LEADERSHIP": leadership_score,
        "DEMOGRAPHICS": demographics_score,
        "MISSION": mission_score,
        "GOVERNANCE": governance_score,
    }


def _weighted(dimensions, weights):
    total = Decimal(0)
    for name, weight in weights.items():
        total += weight * dimensions[name]
    return total


def _clamp_score(value):
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


def provisional_completeness_score(org, programs, filings, leaders, demographics):
    dims = provisional_dimensions(org, programs, filings, leaders, demographics)
    return _clamp_score(to_int(_weighted(dims, DIMENSION_WEIGHTS) * 100))


def verified_completeness_score(org, programs, filings, leaders, demographics):
    dims = verified_dimensions(org, programs, filings, leaders, demographics)
    return _clamp_score(to_int(_weighted(dims, DIMENSION_WEIGHTS) * 100))


def published_completeness_score(org, provisional, verified):
    if org.get("verification_level") in ("DOCUMENT_VERIFIED", "INDEPENDENTLY_AUDITED"):
        return verified
    return provisional


# --- 1.3 disclosure_pct (PRD 3.2) ---------------------------------------

def disclosure_dimensions(org, programs, filings, leaders, demographics):
    active_programs = _active_programs(programs)
    if not active_programs:
        programs_score = ZERO
    elif any(p.get("disclosure_level") == "PUBLIC" for p in active_programs):
        programs_score = ONE
    else:
        programs_score = HALF

    if not filings:
        finances_score = ZERO
    elif any(f.get("status") == "NORMALIZED" for f in filings):
        finances_score = ONE
    else:
        finances_score = HALF

    active_leaders = _active_leaders(leaders)
    if not active_leaders:
        leadership_score = ZERO
    elif any(l.get("disclosure_level") == "PUBLIC" for l in active_leaders):
        leadership_score = ONE
    else:
        leadership_score = HALF

    if not demographics:
        demographics_score = ZERO
    elif any(d.get("disclosure_level") == "PUBLIC" for d in demographics):
        demographics_score = ONE
    else:
        demographics_score = HALF

    officers = [l for l in active_leaders if l.get("is_officer") is True]
    public_independents = [
        l for l in active_leaders
        if l.get("is_independent") is True and l.get("disclosure_level") == "PUBLIC"
    ]
    if public_independents:
        governance_score = ONE
    elif officers:
        governance_score = HALF
    else:
        governance_score = ZERO

    return {
        "PROGRAMS": programs_score,
        "FINANCES": finances_score,
        "LEADERSHIP": leadership_score,
        "DEMOGRAPHICS": demographics_score,
        "MISSION": mission_dimension(org),
        "GOVERNANCE": governance_score,
    }


def disclosure_pct(org, programs, filings, leaders, demographics):
    dims = disclosure_dimensions(org, programs, filings, leaders, demographics)
    return round_half_up(_weighted(dims, DISCLOSURE_WEIGHTS), 4)


# --- 1.3 seal_level_award (PRD 3.7) -------------------------------------

SEAL_RANK = {"BRONZE": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 4}
RANK_SEAL = {1: "BRONZE", 2: "SILVER", 3: "GOLD", 4: "PLATINUM"}

SEAL_DISCLOSURE_FLOOR = {
    "BRONZE": Decimal("0.50"),
    "SILVER": Decimal("0.50"),
    "GOLD": Decimal("0.75"),
    "PLATINUM": Decimal("0.90"),
}

SEAL_TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 60
SEAL_LEVELS = ("BRONZE", "SILVER", "GOLD", "PLATINUM")


def verified_filing_count(org, filings):
    latest = org.get("latest_filing_tax_year")
    if latest is None:
        return 0
    count = 0
    for filing in filings:
        if filing.get("status") != "NORMALIZED":
            continue
        if filing.get("is_verified") is not True:
            continue
        tax_year = filing.get("tax_year")
        if tax_year is None:
            continue
        if tax_year >= latest - 2:
            count += 1
    return count


def leadership_verified_pct(leaders):
    """round_half_up(verified / active, 4); None when there are no ACTIVE rows."""
    active = _active_leaders(leaders)
    if not active:
        return None
    verified = [l for l in active if l.get("is_verified") is True]
    return round_half_up(Decimal(len(verified)) / Decimal(len(active)), 4)


def seal_level_award(org, filings, leaders):
    """The awarded level, or None when the 0.50 disclosure floor is not met."""
    pct = Decimal(str(org.get("disclosure_pct") or 0))
    if pct < Decimal("0.50"):
        return None

    filing_count = verified_filing_count(org, filings)
    if pct >= Decimal("0.90") and filing_count >= 2:
        base_level = "PLATINUM"
    elif pct >= Decimal("0.75") and filing_count >= 1:
        base_level = "GOLD"
    else:
        base_level = "SILVER"

    level_rank = org.get("verification_level")
    if level_rank == "SELF_REPORTED":
        cap_level = "BRONZE"
    elif level_rank == "DOCUMENT_VERIFIED":
        cap_level = "GOLD"
    else:
        cap_level = "PLATINUM"

    level = RANK_SEAL[min(SEAL_RANK[base_level], SEAL_RANK[cap_level])]

    verified_pct = leadership_verified_pct(leaders)
    if verified_pct is not None and verified_pct < Decimal("0.50"):
        if SEAL_RANK[level] > SEAL_RANK["SILVER"]:
            level = "SILVER"
    return level


# --- 1.3 seal_renewal_fee_cents (PRD 3.7) -------------------------------

SEAL_BASE_FEE_CENTS = {"BRONZE": 0, "SILVER": 25000, "GOLD": 75000, "PLATINUM": 200000}
LATE_PCT = {0: Decimal("0.00"), 1: Decimal("0.10"), 2: Decimal("0.25"), 3: Decimal("0.50")}


def late_tier(days_late):
    if days_late <= 0:
        return 0
    if days_late <= 30:
        return 1
    if days_late <= 90:
        return 2
    return 3


def seal_renewal_fee_cents(level, days_late):
    base_fee = SEAL_BASE_FEE_CENTS[level]
    tier = late_tier(days_late)
    late_fee = to_int(Decimal(base_fee) * LATE_PCT[tier])
    return base_fee + late_fee, tier


# --- 1.3 grant_recipient_match_score (PRD 3.9) --------------------------

NAME_SUFFIXES = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "LLC", "LTD",
    "FOUNDATION", "FUND", "TRUST", "ASSOCIATION", "SOCIETY",
}

EIN_MATCH_POINTS = 60
NAME_EXACT_POINTS = 30
NAME_PREFIX_POINTS = 18
NAME_PREFIX_CHARS = 12
SUBJECT_MATCH_POINTS = 10
MATCHED_MIN_SCORE = 70
AMBIGUOUS_MIN_SCORE = 40


def normalize_name(value):
    if not isinstance(value, str):
        return ""
    upper = value.upper()
    cleaned = []
    for char in upper:
        if ("A" <= char <= "Z") or ("0" <= char <= "9"):
            cleaned.append(char)
        else:
            cleaned.append(" ")
    tokens = "".join(cleaned).split()
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    while tokens and tokens[-1] in NAME_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def grant_match_score(grant, recipient_org):
    score = 0
    if recipient_org is None:
        return 0
    recipient_ein = grant.get("recipient_ein")
    if recipient_ein is not None and recipient_ein == recipient_org.get("ein"):
        score += EIN_MATCH_POINTS
    left = normalize_name(grant.get("recipient_name_raw"))
    right = normalize_name(recipient_org.get("legal_name"))
    if left != "" and left == right:
        score += NAME_EXACT_POINTS
    elif (len(left) >= NAME_PREFIX_CHARS and len(right) >= NAME_PREFIX_CHARS
          and left[:NAME_PREFIX_CHARS] == right[:NAME_PREFIX_CHARS]):
        score += NAME_PREFIX_POINTS
    subject_code = grant.get("subject_code")
    if subject_code is not None and subject_code == recipient_org.get("ntee_code"):
        score += SUBJECT_MATCH_POINTS
    return min(100, score)


def grant_match_status(score):
    if score >= MATCHED_MIN_SCORE:
        return "MATCHED"
    if score >= AMBIGUOUS_MIN_SCORE:
        return "AMBIGUOUS"
    return "UNMATCHED"


# --- 1.3 prospect_match_score (PRD 3.9) ---------------------------------

GEO_MATCH_POINTS = 25
PROSPECT_SUBJECT_POINTS = 35
SIZE_BAND_POINTS = 20
HISTORY_POINTS = 20


def mean_grant_amount_cents(grants):
    amounts = [g.get("amount_cents") for g in grants if g.get("amount_cents") is not None]
    if not amounts:
        return Decimal(0)
    return Decimal(sum(amounts)) / Decimal(len(amounts))


def prospect_score(candidate, funder, mean_amount, recorded_grants, subject_code):
    score = 0
    if candidate.get("state_code") is not None and candidate.get("state_code") == funder.get("state_code"):
        score += GEO_MATCH_POINTS
    if subject_code is not None and candidate.get("ntee_code") == subject_code:
        score += PROSPECT_SUBJECT_POINTS
    band_low = to_int(mean_amount * Decimal("0.5"))
    band_high = to_int(mean_amount * Decimal("2.0"))
    revenue = candidate.get("total_revenue_cents") or 0
    if band_low <= revenue <= band_high:
        score += SIZE_BAND_POINTS
    if recorded_grants:
        score += HISTORY_POINTS
    return min(100, score)


def historical_giving_cents(grants):
    return sum(g.get("amount_cents") or 0 for g in grants)
