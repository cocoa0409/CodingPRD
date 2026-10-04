"""Licensing and appointment sequencing: prerequisite registration ladders,
interval semantics and the policy-activation compliance gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_registration,
    get_success_data,
    new_advisor,
    new_appointment,
    new_license,
    new_office,
    new_registration,
    lc_headers,
    md_headers,
    any_headers,
    set_clock,
    validate_error,
    validate_success,
)


def test_prerequisite_registration_must_reach_active_first():
    """PRD §3.5: "Attempting to activate a registration before its prerequisite
    has reached `ACTIVE` is refused with `ERR_PREREQUISITE_REGISTRATION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/securities_activation_gated_by_prerequisite_registration
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Kai Sequence")

    series_6 = new_registration(advisor["id"], registration_type="SERIES_6",
                                crd_number="CRD-9006", activate=False)
    series_65 = new_registration(advisor["id"], registration_type="SERIES_65",
                                 crd_number="CRD-9065",
                                 prerequisite_registration_id=series_6["id"], activate=False)

    refused = api_client.activate_securities_registration(series_65["id"], lc_headers)
    validate_error(refused, ApiErrorId.ERR_PREREQUISITE_REGISTRATION_NOT_ACTIVE.value)

    still_pending = get_success_data(api_client.get_securities_registration(series_65["id"], any_headers))
    assert still_pending["status"] == "PENDING"


def test_flipping_the_prerequisite_flips_the_dependent_activation():
    """PRD §3.5: "A registration whose `prerequisite_registration_id` is set may
    reach `ACTIVE` only when that referenced registration's `status` is itself
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/securities_activation_gated_by_prerequisite_registration
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Kai Flip")

    series_6 = new_registration(advisor["id"], registration_type="SERIES_6",
                                crd_number="CRD-9106", activate=False)
    series_65 = new_registration(advisor["id"], registration_type="SERIES_65",
                                 crd_number="CRD-9165",
                                 prerequisite_registration_id=series_6["id"], activate=False)

    refused = api_client.activate_securities_registration(series_65["id"], lc_headers)
    validate_error(refused, ApiErrorId.ERR_PREREQUISITE_REGISTRATION_NOT_ACTIVE.value)

    activated_prereq = activate_registration(series_6["id"])
    assert activated_prereq["status"] == "ACTIVE"

    activated_dependent = activate_registration(series_65["id"])
    assert activated_dependent["status"] == "ACTIVE"
    assert activated_dependent["prerequisite_registration_id"] == series_6["id"]


def test_securities_activation_also_drives_the_prerequisite_dag_case_for_series_sixty_five():
    """PRD §3.5: "`SERIES_63` and `SERIES_65` require an already-active
    prerequisite registration and are refused until it exists."

    Design: Difficulty/non_linear_state_machine/licensing_parallel_dimensions_and_registration_dag
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Jordan Parallel")

    # A licence recorded but never activated stays PENDING, so the assertion
    # below observes that the registration ladder writes only the securities
    # dimension (§3.5: the four dimensions evolve independently).
    new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-5001",
                activate=False)
    series_6 = new_registration(advisor["id"], registration_type="SERIES_6",
                                crd_number="CRD-6006", activate=False)
    series_65 = new_registration(advisor["id"], registration_type="SERIES_65",
                                 crd_number="CRD-6065",
                                 prerequisite_registration_id=series_6["id"], activate=False)

    refused = api_client.activate_securities_registration(series_65["id"], lc_headers)
    validate_error(refused, ApiErrorId.ERR_PREREQUISITE_REGISTRATION_NOT_ACTIVE.value)

    activate_registration(series_6["id"])
    activate_registration(series_65["id"])

    refreshed = get_success_data(api_client.get_advisor(advisor["id"], any_headers))
    assert refreshed["securities_registration_status"] == "ACTIVE"
    assert refreshed["insurance_license_status"] == "PENDING", \
        "the licence dimension is untouched by the registration ladder"

    dependents = validate_success(api_client.list_registration_dependents(series_6["id"], any_headers))
    dependents = dependents if isinstance(dependents, list) else dependents.get("data", [])
    assert len(dependents) == 1
    assert dependents[0]["registration_type"] == "SERIES_65"


def test_a_licence_boundary_instant_is_not_an_overlap():
    """PRD §2.8: "A `ProductLicense` interval is also half-open,
    `[effective_date, expires_at)`. A new licence for the same advisor and the
    same `product_line` must not overlap an existing licence interval; an
    overlap is refused with `ERR_LICENSE_INTERVAL_OVERLAP`. A shared boundary
    instant is *not* an overlap for licences."

    Design: Difficulty/resource_temporal_overlap/product_licence_half_open_interval_no_overlap_at_boundary
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Mira Interval")

    first = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-1001",
                        effective_date="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
                        activate=False)

    adjacent = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-1002",
                           effective_date="2027-01-01T00:00:00Z", expires_at="2028-01-01T00:00:00Z",
                           activate=False)
    assert adjacent["status"] == "PENDING"

    overlapping = api_client.create_product_license({
        "advisor_id": advisor["id"],
        "product_line": "LIFE",
        "license_number": "WI-LIFE-1003",
        "effective_date": "2026-12-31T23:59:59Z",
        "expires_at": "2027-06-01T00:00:00Z",
        "appointment_required": True,
    }, lc_headers)
    validate_error(overlapping, ApiErrorId.ERR_LICENSE_INTERVAL_OVERLAP.value)

    rows = validate_success(api_client.list_advisor_product_licenses(
        advisor["id"], any_headers, {"product_line": "LIFE"}))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    assert len(rows) == 2, "the overlapping licence must not have been created"

    unchanged = get_success_data(api_client.get_product_license(first["id"], any_headers))
    assert unchanged["expires_at"].startswith("2027-01-01")


def test_a_registration_boundary_instant_is_an_overlap():
    """PRD §2.8: "A `SecuritiesRegistration` interval is closed at both ends,
    `[effective_date, expires_at]`. A new registration for the same advisor and
    the same `registration_type` must not share *any* instant with an existing
    registration interval; an overlap, including an overlap consisting of a
    single shared boundary instant, is refused with
    `ERR_REGISTRATION_INTERVAL_OVERLAP`. A shared boundary instant *is* an
    overlap for registrations."

    Design: Difficulty/resource_temporal_overlap/securities_registration_closed_interval_overlap_at_boundary
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Nico Closed")

    first = new_registration(advisor["id"], registration_type="SERIES_6",
                             crd_number="CRD-A002",
                             effective_date="2026-01-01T00:00:00Z",
                             expires_at="2027-01-01T00:00:00Z", activate=False)

    overlapping = api_client.create_securities_registration({
        "advisor_id": advisor["id"],
        "registration_type": "SERIES_6",
        "crd_number": "CRD-A003",
        "effective_date": "2027-01-01T00:00:00Z",
        "expires_at": "2028-01-01T00:00:00Z",
    }, lc_headers)
    validate_error(overlapping, ApiErrorId.ERR_REGISTRATION_INTERVAL_OVERLAP.value)

    # The identical dates are allowed for a DIFFERENT registration_type.
    other_type = validate_success(api_client.create_securities_registration({
        "advisor_id": advisor["id"],
        "registration_type": "SERIES_7",
        "crd_number": "CRD-A007",
        "effective_date": "2027-01-01T00:00:00Z",
        "expires_at": "2028-01-01T00:00:00Z",
    }, lc_headers), 201)
    assert other_type["status"] == "PENDING"

    rows = validate_success(api_client.list_advisor_securities_registrations(advisor["id"], any_headers))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    assert len(rows) == 2

    unchanged = get_success_data(api_client.get_securities_registration(first["id"], any_headers))
    assert unchanged["status"] == "PENDING"


def test_policy_activation_reports_the_appointment_gate_for_life_business():
    """PRD §3.6: "Activating an `ISSUED` policy requires that the writing
    advisor's `insurance_license_status` be `ACTIVE`, that the advisor's
    `appointment_status` be `APPROVED`, and that the advisor's `contract_status`
    not be `TERMINATED`."

    Design: Difficulty/cross_entity_state_dependency/policy_activation_gated_by_advisor_licensing_dimensions
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Lena Gate")

    license_row = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-9002")
    registration = new_registration(advisor["id"], registration_type="SERIES_6",
                                    crd_number="CRD-9002")

    life_policy = validate_success(api_client.create_policy({
        "policy_number": "NM-9001", "writing_advisor_id": advisor["id"],
        "carrier_name": "Northwestern Mutual", "product_line": "LIFE",
        "annual_premium_cents": 510000, "issue_date": "2026-02-01T00:00:00Z",
        "is_advanced_commission": True,
    }, md_headers), 201)

    refused = api_client.activate_policy(life_policy["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_APPOINTMENT_NOT_APPROVED.value)

    new_appointment(advisor["id"], license_row["id"])
    activated = validate_success(api_client.activate_policy(life_policy["id"], md_headers))

    assert activated["status"] == "ACTIVE"
    assert activated["months_inforce"] == 0


def test_annuity_business_additionally_requires_an_active_registration():
    """PRD §3.6: "For `ANNUITY` business specifically, the writing advisor's
    `securities_registration_status` must additionally be `ACTIVE`, because a
    variable annuity is a dual-registered product."

    Design: Difficulty/cross_entity_state_dependency/policy_activation_gated_by_advisor_licensing_dimensions
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Lena Annuity")

    license_row = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-9102")
    new_registration(advisor["id"], registration_type="SERIES_6", crd_number="CRD-9102")
    new_appointment(advisor["id"], license_row["id"])

    annuity = validate_success(api_client.create_policy({
        "policy_number": "NM-9002", "writing_advisor_id": advisor["id"],
        "carrier_name": "Northwestern Mutual", "product_line": "ANNUITY",
        "annual_premium_cents": 510000, "issue_date": "2026-02-01T00:00:00Z",
        "is_advanced_commission": True,
    }, md_headers), 201)

    activated = validate_success(api_client.activate_policy(annuity["id"], md_headers))
    assert activated["status"] == "ACTIVE"

    refreshed = get_success_data(api_client.get_advisor(advisor["id"], any_headers))
    assert refreshed["insurance_license_status"] == "ACTIVE"
    assert refreshed["securities_registration_status"] == "ACTIVE"
    assert refreshed["appointment_status"] == "APPROVED"

def test_an_inactive_licence_cannot_be_activated_but_a_lapsed_one_can_be_renewed():
    """PRD §3.5: "Activation is permitted only while the licence is `PENDING`
    and the clock is strictly before its `expires_at`; a licence whose
    `expires_at` the clock has already reached is refused with
    `ERR_LICENSE_NOT_ACTIVE`."
    PRD §3.5: "A lapsed licence is restorable by a `LicensingCoordinator` who
    supplies a fresh `expires_at` strictly after the clock."

    Design: Difficulty/non_linear_state_machine/licensing_parallel_dimensions_and_registration_dag
    """
    set_clock("2026-09-01T00:00:00Z")
    office = new_office()
    advisor = new_advisor(office["id"], name="Jordan Stale")

    fresh = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-5301",
                        effective_date="2026-01-01T00:00:00Z",
                        expires_at="2026-12-31T00:00:00Z", activate=True)
    assert fresh["status"] == "ACTIVE"

    # Advance the clock past the expiry: the licence lapses on read.
    set_clock("2027-03-01T00:00:00Z")
    lapsed = get_success_data(api_client.get_product_license(fresh["id"], any_headers))
    assert lapsed["status"] == "LAPSED"

    renewed = validate_success(api_client.renew_product_license(
        fresh["id"], "2028-12-31T00:00:00Z", lc_headers))
    assert renewed["status"] == "ACTIVE"
    assert renewed["expires_at"].startswith("2028-12-31")

    refreshed = get_success_data(api_client.get_advisor(advisor["id"], any_headers))
    assert refreshed["insurance_license_status"] == "ACTIVE"


def test_a_licence_registered_after_its_expiry_cannot_be_activated():
    """PRD §3.5: "Activation is permitted only while the licence is `PENDING`
    and the clock is strictly before its `expires_at`; a licence whose
    `expires_at` the clock has already reached is refused with
    `ERR_LICENSE_NOT_ACTIVE`."

    Design: Difficulty/non_linear_state_machine/licensing_parallel_dimensions_and_registration_dag
    """
    set_clock("2026-09-01T00:00:00Z")
    office = new_office()
    advisor = new_advisor(office["id"], name="Jordan Overdue")

    stale = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-5401",
                        effective_date="2026-01-01T00:00:00Z",
                        expires_at="2026-02-01T00:00:00Z", activate=False)
    assert stale["status"] == "PENDING"

    refused = api_client.activate_product_license(stale["id"], lc_headers)
    validate_error(refused, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)

    unchanged = get_success_data(api_client.get_product_license(stale["id"], any_headers))
    assert unchanged["status"] == "PENDING"


def test_a_boundary_adjacent_licence_is_left_untouched_by_a_refused_overlap():
    """PRD §2.8: "A new licence for the same advisor and the same `product_line`
    must not overlap an existing licence interval; an overlap is refused with
    `ERR_LICENSE_INTERVAL_OVERLAP`. A shared boundary instant is *not* an
    overlap for licences."

    Design: Difficulty/resource_temporal_overlap/product_licence_half_open_interval_no_overlap_at_boundary
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Mira Unchanged")

    first = new_license(advisor["id"], product_line="LIFE", license_number="WI-LIFE-1101",
                        effective_date="2026-01-01T00:00:00Z",
                        expires_at="2027-01-01T00:00:00Z", activate=False)

    overlapping = api_client.create_product_license({
        "advisor_id": advisor["id"],
        "product_line": "LIFE",
        "license_number": "WI-LIFE-1102",
        "effective_date": "2026-06-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
    }, lc_headers)
    validate_error(overlapping, ApiErrorId.ERR_LICENSE_INTERVAL_OVERLAP.value)

    unchanged = get_success_data(api_client.get_product_license(first["id"], any_headers))
    assert unchanged["expires_at"].startswith("2027-01-01")
    assert unchanged["status"] == "PENDING"


def test_dependencies_are_scoped_per_registration_type_not_per_advisor():
    """PRD §2.8: "A new registration for the same advisor and the same
    `registration_type` must not share *any* instant with an existing
    registration interval."

    Design: Difficulty/resource_temporal_overlap/securities_registration_closed_interval_overlap_at_boundary
    """
    set_clock()
    office = new_office()
    advisor = new_advisor(office["id"], name="Nico Scoped")

    first = new_registration(advisor["id"], registration_type="SERIES_6",
                             crd_number="CRD-S002",
                             effective_date="2026-01-01T00:00:00Z",
                             expires_at="2027-01-01T00:00:00Z", activate=False)
    other = new_registration(advisor["id"], registration_type="SERIES_63",
                             crd_number="CRD-S063",
                             effective_date="2026-06-01T00:00:00Z",
                             expires_at="2026-12-01T00:00:00Z", activate=False)

    assert first["status"] == "PENDING"
    assert other["status"] == "PENDING"
    assert other["registration_type"] == "SERIES_63"

    # A same-type registration inside the SERIES_6 window is still refused.
    overlapping = api_client.create_securities_registration({
        "advisor_id": advisor["id"],
        "registration_type": "SERIES_6",
        "crd_number": "CRD-S006",
        "effective_date": "2026-06-01T00:00:00Z",
        "expires_at": "2026-12-01T00:00:00Z",
    }, lc_headers)
    validate_error(overlapping, ApiErrorId.ERR_REGISTRATION_INTERVAL_OVERLAP.value)

    rows = validate_success(api_client.list_advisor_securities_registrations(advisor["id"], any_headers))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    assert len(rows) == 2
