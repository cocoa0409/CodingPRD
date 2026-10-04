"""Normalization: unit conversion, rounding order and revenue aggregation."""
from test_helpers import (
    create_filing,
    extract,
    get_filing,
    get_org,
    list_fields,
    make_admin_headers,
    make_verifier_headers,
    normalize,
    scenario_cascade,
    scenario_riverbend,
    set_clock,
    validate_paginated,
    validate_success,
    void_filing,
)


def test_extract_field_applies_the_usd_thousands_unit_multiplier(api):
    """PRD §3.5: "the `raw_value` is read as a decimal and multiplied by the unit
    multiplier belonging to its `raw_format` — 100 for `USD_WHOLE`, 100000 for
    `USD_THOUSANDS`, 100000000 for `USD_MILLIONS`, and 100 for `PLAIN_INTEGER` —
    and the product is rounded half up to a whole number of cents and stored in
    `normalized_value_cents`."

    Design: Corner/calculations/extract_field_applies_the_usd_thousands_unit_multiplier
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "12.5", "raw_format": "USD_THOUSANDS",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "12.5", "raw_format": "USD_MILLIONS",
         "is_revenue_component": True},
        {"line_code": "CONTRIB", "raw_value": "12.5", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])
    normalized = validate_success(
        api.normalize_filing(filing["id"], make_verifier_headers()), 200)

    fields = {f["line_code"]: f for f in list_fields(filing["id"])}
    assert fields["TOTREV"]["normalized_value_cents"] == 1250000
    assert fields["PROGREV"]["normalized_value_cents"] == 1250000000
    assert fields["CONTRIB"]["normalized_value_cents"] == 1250
    assert normalized["total_revenue_cents"] == 1251251250
    assert normalized["extraction_confidence_pct"] == 92.0, (
        "mean of 92.0 (USD_THOUSANDS), 85.0 (USD_MILLIONS) and 99.0 (USD_WHOLE)"
    )


def test_extract_field_rounds_half_up_away_from_zero_at_an_exact_half_cent(api):
    """PRD §2.8: "The single rounding primitive used throughout the system is
    round half up: an exact one-half fraction rounds away from zero. Rounding is
    never deferred."

    Design: Corner/calculations/extract_field_rounds_half_up_away_from_zero_at_an_exact_half_cent
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "0.125", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "0.135", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])
    normalized = validate_success(
        api.normalize_filing(filing["id"], make_verifier_headers()), 200)

    fields = {f["line_code"]: f for f in list_fields(filing["id"])}
    assert fields["TOTREV"]["normalized_value_cents"] == 13, "12.5 cents rounds half up"
    assert fields["PROGREV"]["normalized_value_cents"] == 14, "13.5 cents rounds half up"
    assert normalized["total_revenue_cents"] == 27
    assert normalized["total_revenue_cents"] != 26, (
        "the sum-then-round shortcut is not the stored value"
    )


def test_filing_revenue_excludes_pending_and_conflict_lines(api):
    """PRD §3.5: "Fields sitting in `PENDING` or `CONFLICT` are excluded from the
    set entirely."
    PRD §3.5: "a field whose `line_code` is duplicated by another field of the same
    filing moves to `CONFLICT` instead: a duplicate line code is an ambiguity the
    system will not silently resolve, so the conflicting fields keep a null
    `normalized_value_cents` and are excluded from the revenue total."

    Design: Corner/calculations/filing_revenue_excludes_pending_and_conflict_lines
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "1000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "500.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "700.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])
    normalized = validate_success(
        api.normalize_filing(filing["id"], make_verifier_headers()), 200)

    assert normalized["total_revenue_cents"] == 100000, "only the unique TOTREV line counts"
    assert normalized["extracted_field_count"] == 3

    fields = list_fields(filing["id"])
    progrev = [f for f in fields if f["line_code"] == "PROGREV"]
    assert len(progrev) == 2
    assert all(f["normalization_status"] == "CONFLICT" for f in progrev)
    assert all(f.get("normalized_value_cents") is None for f in progrev)


def test_organization_total_revenue_ignores_superseded_and_non_normalized_filings(api):
    """PRD §3.5: "The included filings are those whose `organization_id` matches,
    whose `status` is exactly `NORMALIZED`, and whose `superseded_by_revision_number`
    is null; the organization's `total_revenue_cents` is the exact integer sum of
    those filings' `total_revenue_cents`, and its `latest_filing_tax_year` is the
    greatest `tax_year` among them, or null when the set is empty."

    Design: Corner/calculations/organization_total_revenue_ignores_superseded_and_non_normalized_filings
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"], tax_year=2025)
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(filing["id"])

    extra = create_filing(org["id"], form_type="FORM_990_EZ", tax_year=2024,
                          coverage_start="2024-01-01T00:00:00Z",
                          coverage_end="2024-12-31T00:00:00Z", source="ORG_UPLOAD")

    after = get_org(org["id"])
    assert after["total_revenue_cents"] == 100000, (
        "the RECEIVED 2024 filing contributes nothing to the aggregate"
    )
    assert after["latest_filing_tax_year"] == 2025

    extra_read = get_filing(extra["id"])
    assert extra_read["status"] == "RECEIVED"
    assert extra_read["total_revenue_cents"] == 0


def test_normalize_cascade_is_visible_in_the_same_response(api):
    """PRD §2.11: "Reconciliation is immediate, not eventually consistent: the
    response to the request that triggered a change already reflects the
    recomputed values."

    Design: Corner/consistency_model/normalize_cascade_is_visible_in_the_same_response
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"], tax_year=2025)
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "1234.005", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "5678.005", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])

    resp = api.normalize_filing(filing["id"], make_verifier_headers())
    normalized = validate_success(resp, 200)
    assert normalized["status"] == "NORMALIZED"
    assert normalized["total_revenue_cents"] == 691202, (
        "the normalize response already carries the recomputed filing total"
    )

    after = get_org(org["id"])
    assert after["total_revenue_cents"] == 691202, "no delay or retry is needed"
    assert after["latest_filing_tax_year"] == 2025


# ---------------------------------------------------------------------------
# Pinned per-field rounding order (difficulty instance)
# ---------------------------------------------------------------------------

def test_filing_revenue_rounds_each_field_before_the_integer_sum(api):
    """PRD §3.5: "First, every `ExtractedField` of the filing whose
    `is_revenue_component` is true and whose `normalization_status` is `NORMALIZED`
    or `CORRECTED` has its `normalized_value_cents` computed by the per-field
    conversion above. Second, `total_revenue_cents` is the exact integer sum of
    those per-field values, with no second rounding."
    PRD §2.8: "Adding the two raw dollar figures first and rounding once at the
    end would produce 691201, and that result is wrong."

    Design: Difficulty/combinatorial_formula/filing_revenue_rounds_each_field_before_the_integer_sum
    """
    set_clock()
    org, filing = scenario_riverbend()

    read = get_filing(filing["id"])
    assert read["total_revenue_cents"] == 691202
    assert read["total_revenue_cents"] != 691201
    assert read["status"] == "NORMALIZED"
    assert read["extracted_field_count"] == 2
    assert read["extraction_confidence_pct"] == 99.0
    assert read["is_verified"] is True
    assert get_org(org["id"])["total_revenue_cents"] == 691202


def test_filing_revenue_per_field_values_are_rounded_individually(api):
    """PRD §2.8: "A filing with one revenue line whose `raw_value` is `1234.005`
    and `raw_format` is `USD_WHOLE` contributes 123401 cents, and a second line
    whose `raw_value` is `5678.005` and `raw_format` is also `USD_WHOLE`
    contributes 567801 cents; the filing's `total_revenue_cents` is 691202."

    Design: Difficulty/combinatorial_formula/filing_revenue_rounds_each_field_before_the_integer_sum
    """
    set_clock()
    org, filing = scenario_riverbend()

    fields = {f["line_code"]: f for f in list_fields(filing["id"])}
    assert fields["TOTREV"]["normalized_value_cents"] == 123401
    assert fields["PROGREV"]["normalized_value_cents"] == 567801
    assert fields["TOTREV"]["normalization_status"] == "NORMALIZED"
    assert fields["PROGREV"]["normalization_status"] == "NORMALIZED"


# ---------------------------------------------------------------------------
# Conserved organization revenue across supersede and void (difficulty instance)
# ---------------------------------------------------------------------------

def test_organization_revenue_is_restored_when_the_superseding_revision_is_voided(api):
    """PRD §3.5: "Voiding a revision that had superseded an earlier one is more
    interesting: if the voided filing's `revision_number` equals another filing's
    `superseded_by_revision_number`, that earlier filing is restored — its `status`
    returns to the exact value recorded in its `pre_supersede_status`, and both
    `superseded_by_revision_number` and `pre_supersede_status` are cleared back to null."

    Design: Difficulty/compensating_invariant/organization_revenue_conserved_across_filing_supersede_and_void
    """
    set_clock()
    org = scenario_cascade()
    original = create_filing(org["id"], tax_year=2025)
    extract(original["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                              "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(original["id"])
    before = get_org(org["id"])
    assert before["total_revenue_cents"] == 100000

    revision_two = create_filing(org["id"], tax_year=2025, source="ORG_UPLOAD")
    assert revision_two["revision_number"] == 2

    superseded = get_filing(original["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["pre_supersede_status"] == "NORMALIZED"
    assert get_org(org["id"])["total_revenue_cents"] == 0, (
        "the superseded revision drops out of the roll-up"
    )

    void_filing(revision_two["id"])

    restored = get_filing(original["id"])
    assert restored["status"] == "NORMALIZED"
    assert restored.get("superseded_by_revision_number") is None
    assert get_org(org["id"])["total_revenue_cents"] == 100000


def test_organization_revenue_survives_the_supersede_and_void_cycle_with_zero_drift(api):
    """PRD §3.5: "The organization's `total_revenue_cents` is recomputed over the
    non-superseded filings, which now include the restored revision."
    PRD §3.5: "The filing's `version` and the organization's `version` are each
    incremented by 1."

    Design: Difficulty/compensating_invariant/organization_revenue_conserved_across_filing_supersede_and_void
    """
    set_clock()
    org = scenario_cascade()
    original = create_filing(org["id"], tax_year=2025)
    extract(original["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                              "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    normalize(original["id"])
    revenue_before = get_org(org["id"])["total_revenue_cents"]

    revision_two = create_filing(org["id"], tax_year=2025, source="ORG_UPLOAD")
    voided = validate_success(
        api.void_filing(revision_two["id"], make_admin_headers()), 200)
    assert voided["revision_number"] == 2
    assert voided["status"] == "VOIDED"

    rows, meta = validate_paginated(
        api.list_organization_filings(org["id"], make_admin_headers()))
    normalized_rows = [r for r in rows if r["status"] == "NORMALIZED"]
    assert len(normalized_rows) == 1
    assert get_org(org["id"])["total_revenue_cents"] == revenue_before == 100000


def test_duplicate_line_code_normalizes_to_conflict_and_leaves_revenue_unchanged(api):
    """PRD §3.5: "a field whose `line_code` is duplicated by another field of the
    same filing moves to `CONFLICT` instead: a duplicate line code is an ambiguity
    the system will not silently resolve, so the conflicting fields keep a null
    `normalized_value_cents` and are excluded from the revenue total."
    PRD §3.5: "`is_verified` becomes true exactly when the filing's
    `extraction_confidence_pct` is at least 90.0, its `extracted_field_count` is at
    least 1, and no `ExtractedField` of the filing has `normalization_status`
    `CONFLICT`; otherwise it is false."

    Design: Corner/state_machines/duplicate_line_code_normalizes_to_conflict_and_leaves_revenue_unchanged
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "1000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "TOTREV", "raw_value": "2000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])

    normalized = validate_success(
        api.normalize_filing(filing["id"], make_verifier_headers()), 200)
    assert normalized["status"] == "NORMALIZED"
    assert normalized["is_verified"] is False, (
        "a CONFLICT line blocks the filing's verification flag"
    )
    assert normalized["total_revenue_cents"] == 0, "both CONFLICT lines are excluded"

    fields = list_fields(filing["id"])
    assert len(fields) == 2
    assert all(f["normalization_status"] == "CONFLICT" for f in fields)
    assert all(f.get("normalized_value_cents") is None for f in fields)
