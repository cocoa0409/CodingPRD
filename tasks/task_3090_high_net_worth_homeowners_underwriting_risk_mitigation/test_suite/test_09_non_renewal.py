"""Non-renewal: the notice-period arithmetic, ground actionability and the effect path."""
from test_helpers import (
    add_approved_appraisal,
    add_verified_mitigation,
    api_client,
    assert_non_renewal_notice,
    create_agency,
    create_enrollment,
    create_non_renewal_notice,
    create_property,
    create_zone,
    get_success_data,
    reload_property,
    reset_clock,
    run_posture_eval,
    setup_attached_enrollment,
    submit_enrollment,
    validate_error,
    validate_success,
)


def _critical_book(uw, zone_code="ZCRIT", agency_code="AGCRIT", coverage_cents=150_000_000):
    """Two equal-exposure dwellings in one zone, the first bound, book CRITICAL.

    The first enrollment is approved and bound before the second joins the active
    population, because the two dwelling book re-derives its zone to CRITICAL and
    a CRITICAL zone freezes attachment (PRD §2.10).  `required_notice_days` is
    read from the zone band at issue time, so the book must already stand when
    the notice is raised (PRD §3.9).
    """
    zone = create_zone(zone_code=zone_code)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"], dwelling_cost_cents=100_000_000)
    add_verified_mitigation(prop["id"], band_awarded="CLEARED")
    run_posture_eval(prop["id"])

    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=coverage_cents)
    submit_enrollment(enroll["id"], agency["id"])
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], uw), 200)
    attached = validate_success(api_client.attach_enrollment(
        approved["id"], reload_property(prop["id"])["version"], uw), 200)

    sibling = create_property(zone["id"], agency["id"], address_line="2 Critical Rd")
    add_approved_appraisal(sibling["id"], dwelling_cost_cents=100_000_000)
    run_posture_eval(sibling["id"])
    sibling = reload_property(sibling["id"])
    second = create_enrollment(sibling["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=coverage_cents)
    submit_enrollment(second["id"], agency["id"])

    checked = validate_success(
        api_client.check_concentration(zone["id"], uw), 200)
    assert checked["concentration_band"] == "CRITICAL"
    return zone, agency, reload_property(prop["id"]), attached


def test_a_notice_period_at_or_below_the_required_days_is_insufficient(
        api, underwriter_headers):
    """PRD 3.9: "The notice period must be strictly longer than the required period —
    a notice whose effective date falls exactly on the seal instant is insufficient, so
    equality fails"
    PRD 3.9: "A notice failing the notice-period test or the 60-day age test is refused
    with `ERR_NOTICE_PERIOD_INSUFFICIENT`"

    Design: Difficulty/combinatorial_formula/notice_period_nested_rounding_and_strict_boundary_modes
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZE1", agency_code="AG4", coverage_cents=150_000_000,
        dwelling_cost_cents=100_000_000, mitigation_band=None)
    reset_clock("2026-10-01T00:00:00Z")

    # 16 whole days, exclusive of the 2026-10-01 issue date and inclusive of
    # the 2026-10-17 effective date.
    notice = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2026-10-17T00:00:00Z")
    assert notice["notice_period_days"] == 16
    assert notice["required_notice_days"] == 45

    res = api_client.issue_non_renewal_notice(notice["id"], underwriter_headers)
    validate_error(res, "ERR_NOTICE_PERIOD_INSUFFICIENT", expected_status=422)

    still = get_success_data(api_client.list_enrollment_notices(
        enroll["id"], underwriter_headers))[0]
    assert still["status"] == "PENDING"
    assert still["issued_on"] is None


def test_a_notice_period_strictly_above_the_required_days_is_sufficient(
        api, underwriter_headers):
    """PRD 3.9: "The notice period must be strictly longer than the required period —
    a notice whose effective date falls exactly on the seal instant is insufficient, so
    equality fails; the seal instant itself is the issue date advanced by the required
    number of days."

    Design: Difficulty/combinatorial_formula/notice_period_nested_rounding_and_strict_boundary_modes
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZE1S", agency_code="AG4S", coverage_cents=150_000_000,
        dwelling_cost_cents=100_000_000, mitigation_band=None)
    # The gate auto-imposes a DEFENSIBLE_SPACE requirement (the zone is EXTREME
    # and inside the WUI with nothing cleared); once the advance below crosses its
    # due date the requirement lapses, so the band is FAILED and the
    # MITIGATION_FAILURE ground is actionable (PRD §3.5, §3.3).
    reset_clock("2026-11-02T00:00:00Z")
    assert reload_property(prop["id"])["mitigation_band"] == "FAILED"

    # 93 whole days clears the 45-day NORMAL band and the 60-day minimum age
    # (the policy was bound 2026-09-01, 62 days before the filing date).
    notice = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2027-02-03T00:00:00Z")
    assert notice["notice_period_days"] == 93

    issued = validate_success(
        api_client.issue_non_renewal_notice(notice["id"], underwriter_headers), 200)
    assert issued["status"] == "ISSUED"
    assert issued["issued_on"]

    # The notice period is counted exclusively of the issue date, so an effective
    # date exactly 45 days out sits on the seal instant and fails.
    exact = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2026-12-17T00:00:00Z")
    assert exact["notice_period_days"] == 45
    res = api_client.issue_non_renewal_notice(exact["id"], underwriter_headers)
    validate_error(res, "ERR_NOTICE_PERIOD_INSUFFICIENT", expected_status=422)


def test_the_required_period_is_reread_from_the_zone_band(api, underwriter_headers):
    """PRD 3.9: "`required_notice_days`, read from the zone's band at issue time — 90
    days when the zone band is `CRITICAL`, 60 when it is `ELEVATED`, and 45 otherwise"
    PRD 3.9: "The notice is born `PENDING` and immediately computes two fields"

    Design: Difficulty/combinatorial_formula/notice_period_nested_rounding_and_strict_boundary_modes
    """
    zone, agency, prop, enroll = _critical_book(underwriter_headers, zone_code="ZCRIT", agency_code="AGCRIT")
    reset_clock("2026-10-01T00:00:00Z")

    # 61 whole days would clear the 60-day ELEVATED band but not the 90-day
    # CRITICAL band the zone now carries.
    notice = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2026-12-01T00:00:00Z")
    assert notice["notice_period_days"] == 61
    assert notice["required_notice_days"] == 90
    res = api_client.issue_non_renewal_notice(notice["id"], underwriter_headers)
    validate_error(res, "ERR_NOTICE_PERIOD_INSUFFICIENT", expected_status=422)


def test_an_unactionable_mitigation_failure_ground_is_refused(
        api, underwriter_headers):
    """PRD 3.9: "a `MITIGATION_FAILURE` ground is refused unless the property's
    `mitigation_band` is `FAILED`, an `APPRAISAL_LAPSE` ground is refused unless no
    approved appraisal remains current, and a `CONCENTRATION_REVIEW` ground is refused
    unless the zone band is `CRITICAL` — all three refusals carrying
    `ERR_GROUND_NOT_ACTIONABLE`."

    Design: Difficulty/priority_pair_validation_conflict/notice_period_insufficient_outranks_ground_not_actionable
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZK1", agency_code="AG10", coverage_cents=150_000_000,
        dwelling_cost_cents=100_000_000, mitigation_band=None,
        zone_kwargs={"wildland_urban_interface_band": "OUTSIDE_WUI",
                     "exposure_band": "ELEVATED", "sustained_wind_mph": 35})
    # The dwelling carries no mitigation at all: the zone sits outside the WUI, so
    # the gate auto-imposes nothing and the band stays UNVERIFIED rather than
    # lapsing to the FAILED that would make the ground actionable (PRD §3.5).
    assert prop["mitigation_band"] == "UNVERIFIED"
    # The policy must first clear the 60-day minimum age, or the age test would
    # pre-empt the ground test that this case is about.
    reset_clock("2026-11-02T00:00:00Z")
    assert reload_property(prop["id"])["mitigation_band"] == "UNVERIFIED"

    notice = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2027-01-02T00:00:00Z")
    res = api_client.issue_non_renewal_notice(notice["id"], underwriter_headers)
    validate_error(res, "ERR_GROUND_NOT_ACTIONABLE", expected_status=422)


def test_a_concentration_review_ground_needs_a_critical_zone(
        api, underwriter_headers):
    """PRD 3.9: "a `CONCENTRATION_REVIEW` ground is refused unless the zone band is
    `CRITICAL`"

    Design: Corner/errors/every_error_code_is_reachable_from_a_declared_endpoint
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZGRND", agency_code="AGGRND", coverage_cents=150_000_000,
        dwelling_cost_cents=100_000_000, mitigation_band=None,
        zone_kwargs={"wildland_urban_interface_band": "OUTSIDE_WUI",
                     "exposure_band": "ELEVATED", "sustained_wind_mph": 35})
    reset_clock("2026-11-02T00:00:00Z")

    # A single ACTIVE enrollment leaves the zone band NORMAL, not CRITICAL.
    notice = create_non_renewal_notice(
        enroll["id"], ground="CONCENTRATION_REVIEW", effective_on="2027-02-01T00:00:00Z")
    res = api_client.issue_non_renewal_notice(notice["id"], underwriter_headers)
    validate_error(res, "ERR_GROUND_NOT_ACTIONABLE", expected_status=422)


def test_issuance_requires_a_minimum_policy_age(api, underwriter_headers):
    """PRD 3.9: "The policy must be old enough: the enrollment's `bound_at` must be at
    least 60 days before the issue date."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZAGE", agency_code="AGAGE", coverage_cents=150_000_000,
        dwelling_cost_cents=100_000_000, mitigation_band=None)
    reset_clock("2026-10-01T00:00:00Z")

    notice = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2026-12-15T00:00:00Z")
    # The period is generous (75 days), but the policy is only about a month old.
    assert notice["notice_period_days"] == 75
    res = api_client.issue_non_renewal_notice(notice["id"], underwriter_headers)
    validate_error(res, "ERR_NOTICE_PERIOD_INSUFFICIENT", expected_status=422)


def test_issuing_a_concentration_review_activates_the_property_ground(
        api, underwriter_headers):
    """PRD 3.9: "Issuance stamps `issued_on`, computes `seal_at` as the issue date
    advanced by the required number of days, and sets the property's
    `non_renewal_ground_activated` flag to true when the ground is
    `CONCENTRATION_REVIEW`."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    zone, agency, prop, enroll = _critical_book(underwriter_headers, zone_code="ZACT", agency_code="AGACT")

    # A CRITICAL zone with a CONCENTRATION_REVIEW ground is delay-exempt, so only
    # the 60-day minimum policy age is enforced; the bind is 62 days before the
    # issue date.
    reset_clock("2026-11-02T00:00:00Z")
    notice = create_non_renewal_notice(
        enroll["id"], ground="CONCENTRATION_REVIEW", effective_on="2027-02-01T00:00:00Z")
    assert notice["required_notice_days"] == 90

    issued = validate_success(
        api_client.issue_non_renewal_notice(notice["id"], underwriter_headers), 200)
    assert issued["status"] == "ISSUED"
    assert_non_renewal_notice(issued)
    assert reload_property(prop["id"])["non_renewal_ground_activated"] is True


def test_rescinding_a_notice_clears_the_activated_ground(api, underwriter_headers):
    """PRD 3.9: "Rescission is available while the notice is `PENDING` or `ISSUED` and
    while the clock has not yet passed `effective_on`; it moves the notice to
    `RESCINDED` and resets the property's `non_renewal_ground_activated` flag to false."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    zone, agency, prop, enroll = _critical_book(underwriter_headers, zone_code="ZRESC", agency_code="AGRESC")
    reset_clock("2026-11-02T00:00:00Z")

    notice = create_non_renewal_notice(
        enroll["id"], ground="CONCENTRATION_REVIEW", effective_on="2027-02-01T00:00:00Z")
    validate_success(api_client.issue_non_renewal_notice(notice["id"], underwriter_headers), 200)

    rescinded = validate_success(
        api_client.rescind_non_renewal_notice(notice["id"], underwriter_headers), 200)
    assert rescinded["status"] == "RESCINDED"
    assert reload_property(prop["id"])["non_renewal_ground_activated"] is False


def test_the_temporal_defect_outranks_the_fiscal_defect(api, underwriter_headers):
    """PRD 2.11: "mitigation lapse and notice period (priorities 10-11), then the
    aggregate scheduled-value cap and the coverage-ceiling and coverage-floor checks
    (priorities 12-14), then ground actionability, valuation staleness and the
    appraisal-document referential checks (priorities 15-18), then agency activity and
    enrollment-bound status (priorities 19-20), and finally the slot-conflict,
    dispatch-capacity, branch-capital, deductible and endorsement-compatibility checks
    (priorities 21-25)."
    PRD 2.11: "A caller that supplies a request failing two rules will therefore see the
    lower-numbered rule's error, not whichever check the implementation happened to run
    first."

    Design: Difficulty/priority_pair_validation_conflict/notice_period_insufficient_outranks_ground_not_actionable
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZK1B", agency_code="AG10B", coverage_cents=150_000_000,
        dwelling_cost_cents=100_000_000, mitigation_band=None,
        zone_kwargs={"wildland_urban_interface_band": "OUTSIDE_WUI",
                     "exposure_band": "ELEVATED", "sustained_wind_mph": 35})
    assert reload_property(prop["id"])["mitigation_band"] == "UNVERIFIED"
    reset_clock("2026-11-02T00:00:00Z")

    # A 16-day period fails priority 10 AND the UNVERIFIED ground fails priority 15;
    # the lower-numbered rule is what the caller sees.
    deficient = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2026-11-18T00:00:00Z")
    assert deficient["notice_period_days"] == 16
    res = api_client.issue_non_renewal_notice(deficient["id"], underwriter_headers)
    validate_error(res, "ERR_NOTICE_PERIOD_INSUFFICIENT", expected_status=422)
    assert res.json()["data"]["error_id"] != "ERR_GROUND_NOT_ACTIONABLE"

    # Once the period clears priority 10, the unactionable ground is what surfaces.
    sufficient = create_non_renewal_notice(
        enroll["id"], ground="MITIGATION_FAILURE", effective_on="2027-02-01T00:00:00Z")
    assert sufficient["notice_period_days"] == 91
    res2 = api_client.issue_non_renewal_notice(sufficient["id"], underwriter_headers)
    validate_error(res2, "ERR_GROUND_NOT_ACTIONABLE", expected_status=422)
