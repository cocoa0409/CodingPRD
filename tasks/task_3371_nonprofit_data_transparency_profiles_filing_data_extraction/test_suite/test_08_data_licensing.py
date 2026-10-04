"""Data licensing: fees, terms, quota and the conserved usage counter."""
from test_helpers import (
    ApiErrorId,
    activate_license,
    create_license,
    create_org,
    get_license,
    get_org,
    list_usage,
    make_data_consumer_headers,
    make_verifier_headers,
    post_usage,
    scenario_dissolved_license_holder,
    scenario_license_holder,
    scenario_ridgeway,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    void_usage,
    CLOCK_2026_10_01,
    CLOCK_2027_09_01,
)


def test_license_platform_tier_pays_the_base_fee_below_its_included_records(api):
    """PRD §3.9: "Its `included_records` is derived from the tier — 10000 for
    `RESEARCHER`, 100000 for `FUNDER`, 1000000 for `PLATFORM` — and its
    `projected_annual_fee_cents` is quoted from the forecast".
    PRD §3.9: "`overage_flag` is true exactly when `records_accessed` exceeds
    `included_records`."

    Design: Corner/calculations/license_platform_tier_pays_the_base_fee_below_its_included_records
    """
    set_clock()
    org, license_ = scenario_license_holder(
        tier="PLATFORM", permitted_use="PLATFORM_REDISTRIBUTION",
        projected_annual_records=400000)

    post_usage(license_["id"], org["id"], record_count=250000,
               dataset_scope="GRANT_HISTORY", purpose_code="BULK_LOAD")

    read = get_license(license_["id"], org["id"])
    assert read["included_records"] == 1000000
    assert read["records_accessed"] == 250000
    assert read["overage_records"] == 0
    assert read["projected_annual_fee_cents"] == 10000000
    assert read["final_annual_fee_cents"] == 10000000
    assert read["overage_flag"] is False


def test_usage_event_beyond_the_quota_hard_cap_returns_quota_exceeded(api):
    """PRD §3.9: "a posting that would push `records_accessed` above
    `included_records` multiplied by 4 is refused with `ERR_QUOTA_EXCEEDED`
    (HTTP 402). That hard cap of four times the included allowance is a ceiling on
    consumption, not a pricing tier".

    Design: Corner/validations/usage_event_beyond_the_quota_hard_cap_returns_quota_exceeded
    """
    set_clock()
    org, license_ = scenario_license_holder()
    post_usage(license_["id"], org["id"], record_count=10000,
               purpose_code="FIRST_BATCH")

    at_cap = api.post_usage_event(
        license_["id"],
        {"dataset_scope": "FILING_FINANCIALS", "record_count": 30000,
         "purpose_code": "AT_CAP"},
        make_data_consumer_headers(org["id"]))
    validate_success(at_cap, 201)

    over_cap = api.post_usage_event(
        license_["id"],
        {"dataset_scope": "GRANT_HISTORY", "record_count": 1,
         "purpose_code": "ONE_OVER"},
        make_data_consumer_headers(org["id"]))
    assert over_cap.status_code == 402, (
        f"Expected 402, got {over_cap.status_code}: {over_cap.text}"
    )
    validate_error(over_cap, ApiErrorId.ERR_QUOTA_EXCEEDED.value)

    read = get_license(license_["id"], org["id"])
    assert read["records_accessed"] == 40000
    assert read["overage_records"] == 30000

    events = list_usage(license_["id"], org["id"])
    assert len(events) == 2, "the refused posting creates no usage event"


def test_usage_event_outside_the_license_term_returns_license_term_closed(api):
    """PRD §3.9: "a logical clock outside the license's `[term_start, term_end)`
    window is refused with `ERR_LICENSE_TERM_CLOSED` (HTTP 409)".
    PRD §3.9: "a `term_start` marking the first instant of the term inclusive".

    Design: Corner/validations/usage_event_outside_the_license_term_returns_license_term_closed
    """
    set_clock()
    org, license_ = scenario_license_holder(
        term_start="2026-10-01T00:00:00Z", term_end="2027-10-01T00:00:00Z")
    assert license_["status"] == "ACTIVE", "activation does not gate on the clock"

    early = api.post_usage_event(
        license_["id"],
        {"dataset_scope": "GRANT_HISTORY", "record_count": 500,
         "purpose_code": "EARLY_READ"},
        make_data_consumer_headers(org["id"]))
    assert early.status_code == 409, f"Expected 409, got {early.status_code}: {early.text}"
    validate_error(early, ApiErrorId.ERR_LICENSE_TERM_CLOSED.value)
    assert get_license(license_["id"], org["id"])["records_accessed"] == 0

    set_clock(CLOCK_2026_10_01)
    opened = api.post_usage_event(
        license_["id"],
        {"dataset_scope": "GRANT_HISTORY", "record_count": 500,
         "purpose_code": "OPENING_READ"},
        make_data_consumer_headers(org["id"]))
    validate_success(opened, 201)
    assert get_license(license_["id"], org["id"])["records_accessed"] == 500


def test_license_expires_automatically_when_the_logical_clock_passes_term_end(api):
    """PRD §3.9: "A license expires automatically when the logical clock reaches
    `term_end`, and also when the licensee organization finalizes a `MERGE` or a
    `DISSOLUTION` identity case; in both cases the licensee organization's
    `active_license_count` is recomputed."

    Design: Corner/state_machines/license_expires_automatically_when_the_logical_clock_passes_term_end
    """
    set_clock()
    org, license_ = scenario_license_holder()
    assert get_org(org["id"])["active_license_count"] == 1

    set_clock(CLOCK_2027_09_01)

    assert get_license(license_["id"], org["id"])["status"] == "EXPIRED"
    assert get_org(org["id"])["active_license_count"] == 0

    rows, _ = validate_paginated(
        api.list_licenses(org["id"], make_verifier_headers()))
    assert [r for r in rows if r["status"] == "ACTIVE"] == []


def test_data_consumer_cannot_activate_another_organizations_license(api):
    """PRD §2.1: "When `X-User-Role` is `DataConsumer`, `X-User-ID` is likewise the
    `id` of the acting `Organization` — the funder, researcher or platform that
    holds or is requesting the license".
    PRD §2.1: "an `OrganizationUser` acting on a resource that does not belong to
    its own organization is refused with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/roles/data_consumer_cannot_activate_another_organizations_license
    """
    set_clock()
    org, license_ = scenario_license_holder(activate=False)
    other = create_org("Prairie Food Bank", "900100201", state_code="IL")

    resp = api.activate_license(license_["id"], make_data_consumer_headers(other["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    assert get_license(license_["id"], org["id"])["status"] == "DRAFT"
    assert get_org(org["id"])["active_license_count"] == 0


# ---------------------------------------------------------------------------
# Projected vs final fee variants (difficulty instance)
# ---------------------------------------------------------------------------

def test_projected_and_final_license_fees_diverge_for_the_same_license(api):
    """PRD §3.9: "A `RESEARCHER` license forecasting 50000 records therefore quotes
    700000 cents: a 500000-cent base plus 40000 overage records at 5 cents each."
    PRD §3.9: "The `RESEARCHER` license that quoted 700000 cents from a 50000-record
    forecast reports 510000 cents once its posted events total 12000 records
    actually read — a 500000-cent base plus 2000 overage records at 5 cents each."

    Design: Difficulty/dual_variant_calc/license_fee_projected_variant_diverges_from_final_variant
    """
    set_clock()
    org, license_ = scenario_license_holder(projected_annual_records=50000)
    post_usage(license_["id"], org["id"], record_count=12000,
               dataset_scope="ORGANIZATION_PROFILES", purpose_code="PILOT_SCAN")

    read = get_license(license_["id"], org["id"])
    assert read["included_records"] == 10000
    assert read["projected_annual_fee_cents"] == 700000
    assert read["final_annual_fee_cents"] == 510000
    assert read["projected_annual_fee_cents"] != read["final_annual_fee_cents"]
    assert read["records_accessed"] == 12000
    assert read["overage_records"] == 2000
    assert read["overage_flag"] is True


def test_projected_license_fee_is_quoted_before_any_usage_is_posted(api):
    """PRD §3.9: "The license opens in `DRAFT` status with `records_accessed` 0,
    `overage_records` 0 and `overage_flag` false."
    PRD §3.9: "Its `included_records` is derived from the tier — 10000 for
    `RESEARCHER`, 100000 for `FUNDER`, 1000000 for `PLATFORM` — and its
    `projected_annual_fee_cents` is quoted from the forecast".

    Design: Difficulty/dual_variant_calc/license_fee_projected_variant_diverges_from_final_variant
    """
    set_clock()
    org, license_ = scenario_license_holder(projected_annual_records=50000,
                                            activate=False)
    assert license_["status"] == "DRAFT"
    assert license_["records_accessed"] == 0
    assert license_["overage_records"] == 0
    assert license_["overage_flag"] is False
    assert license_["projected_annual_fee_cents"] == 700000, (
        "the quote is available from the forecast alone, before any usage"
    )
    assert license_["final_annual_fee_cents"] == 500000, (
        "with no POSTED events the read-time fee is the bare tier base"
    )

    activated = activate_license(license_["id"], org["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["projected_annual_fee_cents"] == 700000


# ---------------------------------------------------------------------------
# Half-open license terms (difficulty instance)
# ---------------------------------------------------------------------------

def test_license_term_starting_exactly_at_the_prior_term_end_is_not_an_overlap(api):
    """PRD §3.9: "an adjacent term whose `term_start` exactly equals the prior
    term's `term_end` is *not* an overlap, because the intervals are half-open."

    Design: Difficulty/resource_temporal_overlap/license_half_open_terms_allow_adjacent_renewal_but_reject_overlap
    """
    set_clock()
    org, first = scenario_license_holder(
        term_start="2026-09-01T00:00:00Z", term_end="2027-09-01T00:00:00Z")
    assert first["status"] == "ACTIVE"

    successor = create_license(org["id"], tier="RESEARCHER",
                               term_start="2027-09-01T00:00:00Z",
                               term_end="2028-09-01T00:00:00Z",
                               projected_annual_records=12000)
    activated = activate_license(successor["id"], org["id"])
    assert activated["status"] == "ACTIVE", (
        "the adjacent half-open term does not overlap its predecessor"
    )

    rows, _ = validate_paginated(
        api.list_licenses(org["id"], make_verifier_headers()))
    assert len([r for r in rows if r["status"] == "ACTIVE"]) == 2


def test_license_term_starting_one_day_earlier_does_overlap_and_is_rejected(api):
    """PRD §3.9: "The half-open term `[term_start, term_end)` must not overlap an
    existing non-`EXPIRED` license of the same tier held by the same licensee; an
    overlap is refused with `ERR_LICENSE_TERM_OVERLAP` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/license_half_open_terms_allow_adjacent_renewal_but_reject_overlap
    """
    set_clock()
    org, first = scenario_license_holder(
        term_start="2026-09-01T00:00:00Z", term_end="2027-09-01T00:00:00Z")
    successor = create_license(org["id"], tier="RESEARCHER",
                               term_start="2027-09-01T00:00:00Z",
                               term_end="2028-09-01T00:00:00Z",
                               projected_annual_records=12000)
    activate_license(successor["id"], org["id"])

    overlapping = create_license(org["id"], tier="RESEARCHER",
                                 term_start="2027-08-31T00:00:00Z",
                                 term_end="2028-08-31T00:00:00Z",
                                 projected_annual_records=12000)
    resp = api.activate_license(overlapping["id"], make_data_consumer_headers(org["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_OVERLAP.value)

    assert get_license(overlapping["id"], org["id"])["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Conserved usage counter (difficulty instance)
# ---------------------------------------------------------------------------

def test_voiding_a_usage_event_returns_exactly_its_records_to_the_license(api):
    """PRD §3.9: "`records_accessed` is a conserved quantity: it equals the sum of
    `record_count` over the license's `POSTED` usage events and nothing else, which
    is what makes voiding meaningful."
    PRD §3.9: "A `PlatformAdmin` may void a posted event by naming its `event_id`
    within the owning license, which moves that event to `VOIDED`, subtracts its
    `record_count` from `records_accessed`, recomputes `overage_records`,
    `overage_flag` and `final_annual_fee_cents`".

    Design: Difficulty/compensating_invariant/license_records_accessed_conserved_across_usage_void
    """
    set_clock()
    org, license_ = scenario_license_holder()
    post_usage(license_["id"], org["id"], record_count=4000, purpose_code="COHORT_A")
    post_usage(license_["id"], org["id"], record_count=5000, purpose_code="COHORT_B")
    third = post_usage(license_["id"], org["id"], record_count=6000,
                       dataset_scope="GRANT_HISTORY", purpose_code="COHORT_C")

    before = get_license(license_["id"], org["id"])
    assert before["records_accessed"] == 15000
    assert before["overage_records"] == 5000
    assert before["final_annual_fee_cents"] == 525000

    voided = void_usage(license_["id"], third["id"])
    assert voided["status"] == "VOIDED"

    after = get_license(license_["id"], org["id"])
    assert after["records_accessed"] == 9000
    assert after["records_accessed"] != 15000
    assert after["overage_records"] == 0
    assert after["overage_flag"] is False
    assert after["final_annual_fee_cents"] == 500000


def test_records_accessed_equals_the_sum_of_the_surviving_posted_events(api):
    """PRD §3.9: "`records_accessed` is a conserved quantity: it equals the sum of
    `record_count` over the license's `POSTED` usage events and nothing else".
    PRD §3.9: "`overage_flag` is true exactly when `records_accessed` exceeds
    `included_records`."

    Design: Difficulty/compensating_invariant/license_records_accessed_conserved_across_usage_void
    """
    set_clock()
    org, license_ = scenario_license_holder()
    events = [post_usage(license_["id"], org["id"], record_count=count,
                         purpose_code=f"COHORT_{count}")
              for count in (4000, 5000, 6000)]
    void_usage(license_["id"], events[2]["id"])

    listed = list_usage(license_["id"], org["id"])
    posted = [e for e in listed if e["status"] == "POSTED"]
    assert len(posted) == 2
    assert sum(e["record_count"] for e in posted) == 9000

    read = get_license(license_["id"], org["id"])
    assert read["records_accessed"] == sum(e["record_count"] for e in posted)
    assert read["records_accessed"] == 4000 + 5000
    assert read["overage_flag"] is False


# ---------------------------------------------------------------------------
# Safety gate outranking the permitted-use referential check (difficulty instance)
# ---------------------------------------------------------------------------

def test_license_activation_refuses_a_dissolved_licensee_before_the_permitted_use_check(api):
    """PRD §3.9: "The licensee organization must be `ACTIVE`, or the request is
    refused with `ERR_ORG_NOT_IN_GOOD_STANDING` (HTTP 403)."
    PRD §2.10: "Business safety gates come next ... These yield
    `ERR_SEGREGATION_OF_DUTIES`, `ERR_VERIFICATION_STEP_INVALID`,
    `ERR_PROFILE_INCOMPLETE` and `ERR_ORG_NOT_IN_GOOD_STANDING` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/license_activation_prefers_safety_over_permitted_use_referential
    """
    set_clock()
    org, license_ = scenario_dissolved_license_holder()
    assert org["profile_status"] == "DISSOLVED"

    resp = api.activate_license(license_["id"], make_data_consumer_headers(org["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_ORG_NOT_IN_GOOD_STANDING.value)
    assert err["error_id"] != "ERR_PERMITTED_USE_NOT_IN_TIER", (
        "the safety gate outranks the reference-data membership check"
    )

    assert get_license(license_["id"], org["id"])["status"] == "DRAFT"
    assert get_org(org["id"])["active_license_count"] == 0


def test_license_activation_reports_the_permitted_use_error_for_an_active_licensee(api):
    """PRD §3.9: "The `permitted_use` must be a member of the tier's permitted set
    as tabulated in §2.7, or the request is refused with
    `ERR_PERMITTED_USE_NOT_IN_TIER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/license_activation_prefers_safety_over_permitted_use_referential
    """
    set_clock()
    org, license_ = scenario_ridgeway()
    assert org["profile_status"] == "ACTIVE"

    resp = api.activate_license(license_["id"], make_data_consumer_headers(org["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_PERMITTED_USE_NOT_IN_TIER.value)

    assert get_license(license_["id"], org["id"])["status"] == "DRAFT"
