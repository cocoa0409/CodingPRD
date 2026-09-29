"""Domain assertions for the Pressure Vessel Fabrication API test suite.

Everything here is an assertion helper or an independent recomputation of a PRD
formula. The recomputations exist so that a test can state the expected number in
the PRD's own arithmetic instead of a hand-transcribed literal.
"""

from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    APPEND_ONLY_AUDIT_FIELDS,
    CATEGORY_B_FULL_RT_THICKNESS_THRESHOLD,
    HYDROSTATIC_MEDIUM_TEMP_MARGIN_F,
    HYDROSTATIC_PRESSURE_FACTOR,
    JOINT_EFFICIENCY_BY_EXTENT,
    MIN_SOAK_MINUTES,
    PNEUMATIC_MEDIUM_TEMP_MARGIN_F,
    PNEUMATIC_PRESSURE_FACTOR,
    SECTION_ORDER,
    SECTION_WEIGHTS,
    SOAK_MINUTES_PER_INCH,
    TEST_TYPE_HYDROSTATIC,
    UT_CROSSOVER_THICKNESS,
    VARIANT_CIRCUMFERENTIAL,
    VARIANT_LONGITUDINAL,
)


# --- rounding (§2.6: "Every rounding step in this system is round half up") ---
def round_half_up(value, places):
    """Round ``value`` to ``places`` decimals, midpoints away from zero."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_scale(actual, places, field_name="value"):
    """Assert a returned number carries no more than ``places`` decimals."""
    assert actual is not None, "{0} should be populated".format(field_name)
    rendered = Decimal(str(actual))
    exponent = -rendered.as_tuple().exponent
    assert exponent <= places, "{0} carries {1} decimals, PRD declares {2}: {3}".format(
        field_name, exponent, places, actual
    )


def assert_number_equals(actual, expected, places, field_name="value"):
    """Assert two numbers agree once both are read at the field's own scale."""
    assert actual is not None, "{0} should be populated".format(field_name)
    left = Decimal(str(actual)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    right = Decimal(str(expected)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    assert left == right, "{0}: expected {1}, got {2}".format(field_name, expected, actual)


# --- §2.2 envelope -----------------------------------------------------------
def assert_envelope_meta(response):
    """Assert the §2.2 meta contract on any response body."""
    body = response.json()
    assert "meta" in body, "response carries no meta object"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_: {0}".format(meta["api_request_id"])
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        "api_request_timestamp is not an ISO 8601 UTC timestamp: {0}".format(
            meta.get("api_request_timestamp")
        )
    )
    assert_three_fractional_digits(meta["api_request_timestamp"], "api_request_timestamp")
    return meta


def assert_response_type(response, expected):
    body = response.json()
    assert body.get("response_type") == expected, "expected response_type {0}, got {1}".format(
        expected, body.get("response_type")
    )


def assert_error_envelope(response, expected_error_id):
    """Assert the §2.2 error envelope shape and its error_id."""
    assert_envelope_meta(response)
    body = response.json()
    assert body.get("response_type") == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta must carry only api_request_id and api_request_timestamp: {0}".format(
            sorted(body["meta"].keys())
        )
    )
    data = body["data"]
    assert data.get("error_id") == expected_error_id
    assert isinstance(data.get("message"), str) and data["message"], "message must be non-empty"


# --- §2.4 identity and audit fields -----------------------------------------
def assert_three_fractional_digits(timestamp, field_name="timestamp"):
    """Assert an ISO 8601 UTC timestamp carries exactly three fractional digits."""
    assert isinstance(timestamp, str), "{0} must be a string".format(field_name)
    assert timestamp.endswith("Z"), "{0} must be a UTC instant: {1}".format(field_name, timestamp)
    stem = timestamp[:-1]
    assert "." in stem, "{0} carries no fractional digits: {1}".format(field_name, timestamp)
    fraction = stem.split(".")[1]
    assert len(fraction) == 3, "{0} carries {1} fractional digits, PRD declares 3: {2}".format(
        field_name, len(fraction), timestamp
    )


def assert_full_audit_fields(record, expected_version=None):
    """Assert the §2.4 full identity set: id, created_at, updated_at and version."""
    assert is_valid_uuid(record.get("id")), "id is not a UUID: {0}".format(record.get("id"))
    assert_three_fractional_digits(record.get("created_at"), "created_at")
    assert_three_fractional_digits(record.get("updated_at"), "updated_at")
    assert isinstance(record.get("version"), int), "version must be an integer"
    assert record["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert record["version"] == expected_version, "expected version {0}, got {1}".format(
            expected_version, record["version"]
        )


def assert_append_only_audit_fields(record):
    """Assert the §2.4 exception set carried by `Personnel`: id and created_at only."""
    assert is_valid_uuid(record.get("id")), "id is not a UUID: {0}".format(record.get("id"))
    assert_three_fractional_digits(record.get("created_at"), "created_at")
    assert "updated_at" not in record, "this record must expose no updated_at field"
    assert "version" not in record, "this record must expose no version field"
    for field in APPEND_ONLY_AUDIT_FIELDS:
        assert field in record


def assert_created_at_unchanged(before, after):
    """§2.4: created_at is "fixed at creation and never rewritten"."""
    assert canonical_instant(before["created_at"]) == canonical_instant(after["created_at"]), (
        "created_at was rewritten"
    )


def assert_version_advanced(before, after, by=1):
    assert after["version"] == before["version"] + by, (
        "expected version {0} -> {1}, got {2}".format(
            before["version"], before["version"] + by, after["version"]
        )
    )


def assert_updated_at_advanced(before, after):
    assert canonical_instant(after["updated_at"]) >= canonical_instant(before["updated_at"]), (
        "updated_at moved backwards"
    )


# --- §2.3 pagination ---------------------------------------------------------
def assert_pagination_meta(response, limit, offset, total_count, has_more):
    meta = assert_envelope_meta(response)
    assert meta.get("limit") == limit, "expected limit {0}, got {1}".format(limit, meta.get("limit"))
    assert meta.get("offset") == offset
    assert meta.get("total_count") == total_count, "expected total_count {0}, got {1}".format(
        total_count, meta.get("total_count")
    )
    assert meta.get("has_more") is has_more
    return meta


def assert_sorted_by_created_at(records):
    """§2.3 default order: `created_at` ascending."""
    stamps = [canonical_instant(record["created_at"]) for record in records]
    assert stamps == sorted(stamps), "records are not sorted by created_at ascending"


# --- §3.3 wall sizing --------------------------------------------------------
def circumferential_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency):
    """§3.3 circumferential-stress variant, unrounded."""
    pressure = Decimal(str(mawp_psi))
    radius = Decimal(str(inside_radius_in))
    stress = Decimal(str(allowable_stress_psi))
    joint = Decimal(str(efficiency))
    return pressure * radius / (stress * joint - Decimal("0.6") * pressure)


def longitudinal_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency):
    """§3.3 longitudinal-stress variant, unrounded."""
    pressure = Decimal(str(mawp_psi))
    radius = Decimal(str(inside_radius_in))
    stress = Decimal(str(allowable_stress_psi))
    joint = Decimal(str(efficiency))
    return pressure * radius / (Decimal(2) * stress * joint + Decimal("0.4") * pressure)


def expected_thickness_pair(mawp_psi, inside_radius_in, allowable_stress_psi, rt_extent_declared):
    """Both reported thickness variants, each rounded half up to four decimals."""
    efficiency = JOINT_EFFICIENCY_BY_EXTENT[rt_extent_declared]
    circ = circumferential_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency)
    longi = longitudinal_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency)
    return round_half_up(circ, 4), round_half_up(longi, 4)


def expected_governing_variant(mawp_psi, inside_radius_in, allowable_stress_psi, rt_extent_declared):
    """§3.3: CIRCUMFERENTIAL when the unrounded circumferential value wins ties."""
    efficiency = JOINT_EFFICIENCY_BY_EXTENT[rt_extent_declared]
    circ = circumferential_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency)
    longi = longitudinal_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency)
    return VARIANT_CIRCUMFERENTIAL if circ >= longi else VARIANT_LONGITUDINAL


def expected_required_thickness(
    mawp_psi, inside_radius_in, allowable_stress_psi, rt_extent_declared, corrosion_allowance_in
):
    """§3.3: the greater unrounded variant plus the allowance, rounded once."""
    efficiency = JOINT_EFFICIENCY_BY_EXTENT[rt_extent_declared]
    circ = circumferential_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency)
    longi = longitudinal_thickness_raw(mawp_psi, inside_radius_in, allowable_stress_psi, efficiency)
    governing = circ if circ >= longi else longi
    return round_half_up(governing + Decimal(str(corrosion_allowance_in)), 4)


# --- §3.6 coverage resolution ------------------------------------------------
def expected_volumetric_method(thickness_in, joint_type):
    """§3.6: UT on heavy butt joints, RT in every other case."""
    if Decimal(str(thickness_in)) >= Decimal(str(UT_CROSSOVER_THICKNESS)) and joint_type == "BUTT":
        return "UT"
    return "RT"


def expected_category_b_coverage(rt_extent_declared, thickness_in):
    """§3.6 Category B clause, read at three decimal places."""
    if rt_extent_declared == "FULL":
        thick = Decimal(str(thickness_in)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        threshold = Decimal(str(CATEGORY_B_FULL_RT_THICKNESS_THRESHOLD))
        return 100 if thick >= threshold else 25
    if rt_extent_declared == "SPOT":
        return 25
    return 0


# --- §3.8 soak demand and test parameters ------------------------------------
def expected_required_soak_minutes(governing_thickness_in):
    """§3.8: the larger of 15 minutes and 60 minutes per inch, rounded first."""
    product = Decimal(str(governing_thickness_in)) * Decimal(SOAK_MINUTES_PER_INCH)
    rounded = int(product.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return max(MIN_SOAK_MINUTES, rounded)


def expected_test_pressure(mawp_psi, stress_ratio, test_type):
    """§3.8: 1.3 x MAWP x stress ratio hydrostatic, 1.1 x pneumatic, at 1 decimal."""
    factor = (
        HYDROSTATIC_PRESSURE_FACTOR if test_type == TEST_TYPE_HYDROSTATIC else PNEUMATIC_PRESSURE_FACTOR
    )
    raw = Decimal(str(factor)) * Decimal(str(mawp_psi)) * Decimal(str(stress_ratio))
    return round_half_up(raw, 1)


def expected_min_medium_temp(mdmt_f, test_type):
    """§3.8: mdmt plus 30 hydrostatic, plus 60 pneumatic."""
    margin = (
        HYDROSTATIC_MEDIUM_TEMP_MARGIN_F
        if test_type == TEST_TYPE_HYDROSTATIC
        else PNEUMATIC_MEDIUM_TEMP_MARGIN_F
    )
    return float(Decimal(str(mdmt_f)) + Decimal(margin))


# --- §3.9 completeness scoring -----------------------------------------------
def expected_section_points(section, numerator, denominator):
    """§3.9: weight x fraction, rounded half up to two decimals per section."""
    fraction = Decimal(1) if denominator == 0 else Decimal(numerator) / Decimal(denominator)
    return round_half_up(Decimal(SECTION_WEIGHTS[section]) * fraction, 2)


def expected_completeness_score(fractions):
    """§3.9: the sum of the already-rounded section points, rounded once more."""
    total = Decimal(0)
    for section in SECTION_ORDER:
        numerator, denominator = fractions[section]
        total += Decimal(str(expected_section_points(section, numerator, denominator)))
    return round_half_up(total, 2)


def expected_missing_items(fractions, open_nonconformance, stamping_authorized):
    """§3.9: the section names below full marks, then the two shop-level literals."""
    items = []
    for section in SECTION_ORDER:
        numerator, denominator = fractions[section]
        fraction = Decimal(1) if denominator == 0 else Decimal(numerator) / Decimal(denominator)
        if fraction < Decimal(1):
            items.append(section)
    if open_nonconformance:
        items.append("OPEN_NONCONFORMANCE")
    if not stamping_authorized:
        items.append("CERTIFICATE_NOT_AUTHORIZED")
    return items


# --- §3.5 weld completion ----------------------------------------------------
def expected_weld_completion_pct(numerator, denominator):
    """§3.6: 0.00 on an empty map, otherwise the percentage at two decimals."""
    if denominator == 0:
        return 0.00
    return round_half_up(Decimal(100) * Decimal(numerator) / Decimal(denominator), 2)
