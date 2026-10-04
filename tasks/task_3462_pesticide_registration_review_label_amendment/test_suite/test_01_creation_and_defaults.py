"""Creation, defaults, and system-field stamping for reference data, products,
applications, amendments, and the registration-number sequence (PRD §3.1–§3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_active_ingredient,
    assert_application,
    assert_iso_instant_equal,
    assert_label_amendment,
    assert_product,
    create_active_ingredient,
    create_application,
    create_product,
    create_registered_product,
    file_method_change_amendment,
    get_product_version,
    list_product_use_sites,
    make_amendment_payload,
    make_application_payload,
    make_method_change_payload,
    make_non_food_use_site_object,
    make_product_payload,
    make_use_site_object,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]


def test_active_ingredient_create_echoes_fields_and_stamps_system_fields(api):
    """PRD §3.1: "An active ingredient is recorded with its public `common_name`
    (for example, chlorpyrifos), a `cas_number` that must be unique across all
    active-ingredient rows, an acute `tox_category` of `I`, `II`, `III`, or `IV`,
    a chronic `reference_dose_mg_kg_day` strictly greater than zero, and an
    `aquatic_lc50_ppm` strictly greater than zero."
    PRD §4: "Operations that create a new resource return `201 Created`"
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource."
    PRD §2.5: "Timestamps the workflows stamp — `submitted_at`, `decided_at`,
    `assessed_at`, `granted_at`, `effective_at`, and their kin — always read from
    the logical clock of §2.4."

    Design: Corner/entities/active_ingredient_create_echoes_fields_and_stamps_system_fields
    """
    resp = api_client.create_active_ingredient(
        {
            "common_name": "nominex",
            "cas_number": "100-00-1",
            "tox_category": "III",
            "reference_dose_mg_kg_day": 0.05,
            "aquatic_lc50_ppm": 100.0,
        },
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert resp.json()["meta"]["api_request_id"]
    assert resp.json()["meta"]["api_request_timestamp"]
    assert_active_ingredient(data)
    assert data["common_name"] == "nominex"
    assert data["cas_number"] == "100-00-1"
    assert data["tox_category"] == "III"
    assert data["reference_dose_mg_kg_day"] == 0.05
    assert data["aquatic_lc50_ppm"] == 100.0
    assert data["version"] == 1


def test_product_create_defaults_and_owner_stamping(api):
    """PRD §3.1: "Creation stamps the representative's `X-User-ID` as the
    product's `registrant_ref`, sets `status` to `UNREGISTERED`, leaves
    `classification` at its default of `GENERAL_USE`, and leaves both
    `signal_word` and `epa_registration_number` null"
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource."

    Design: Corner/entities/product_create_defaults_and_owner_stamping
    """
    ai = create_active_ingredient()
    resp = api_client.create_product(
        make_product_payload(ai["id"], product_name="Nominex G",
                             formulation_type="GRANULAR"),
        REGISTRANT,
    )
    product = validate_success(resp, 201)
    assert_product(product)
    assert product["status"] == "UNREGISTERED"
    assert product["classification"] == "GENERAL_USE"
    assert product["signal_word"] is None
    assert product["epa_registration_number"] is None
    assert product["registrant_ref"] == "reg-alice"
    assert product["version"] == 1


def test_application_create_mints_proposed_use_sites_and_defaults(api):
    """PRD §3.2: "Creating the application — which is born in `DRAFT` — mints one
    use-site row per array element, each in `PROPOSED` status with `origin`
    `INITIAL_APPLICATION` and its `product_id` pointing at the label owner."
    PRD §3.2: "An application is born with `deficiency_count` zero"
    PRD §3.2: "A successful first submit stamps `submitted_at` from the logical
    clock, computes `review_due_at` as the submission instant plus the statutory
    review timeline for the use pattern"

    Design: Corner/entities/application_create_mints_proposed_use_sites_and_defaults
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"], product_name="Nominex G")
    sites = [
        make_non_food_use_site_object(),
        make_use_site_object(site_code="ORNAMENTAL", pest_code="APHID",
                             max_application_rate_lbs_acre=0.5,
                             max_applications_per_season=4,
                             preharvest_interval_days=0,
                             restricted_entry_interval_hours=12),
    ]
    resp = api_client.create_application(
        make_application_payload(product["id"], "NON_FOOD_USE",
                                 proposed_use_sites=sites),
        REGISTRANT,
    )
    application = validate_success(resp, 201)
    assert_application(application)
    assert application["status"] == "DRAFT"
    assert application["deficiency_count"] == 0
    assert application["review_due_at"] is None
    assert application["submitted_at"] is None

    rows = list_product_use_sites(product["id"], status="PROPOSED")
    assert len(rows) == 2, f"expected 2 PROPOSED use sites, got {len(rows)}"
    by_code = {row["site_code"]: row for row in rows}
    assert set(by_code) == {"TURF", "ORNAMENTAL"}
    for row in rows:
        assert row["origin"] == "INITIAL_APPLICATION"
        assert row["product_id"] == product["id"]
    assert by_code["TURF"]["max_application_rate_lbs_acre"] == 1.0
    assert by_code["ORNAMENTAL"]["max_application_rate_lbs_acre"] == 0.5


def test_registration_number_minted_sequentially_across_products(api):
    """PRD §3.4: "its `epa_registration_number` is minted as the literal prefix
    `EPA-RR-` followed by a zero-padded six-digit sequence equal to one more than
    the count of previously approved applications, so the very first approval in
    the system mints `EPA-RR-000001`"
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource."

    Design: Corner/entities/registration_number_minted_sequentially_across_products
    """
    ctx1 = create_registered_product(product_overrides={"product_name": "Nominex G"})
    ctx2 = create_registered_product(product_overrides={"product_name": "Nominex WP"})
    assert ctx1["product"]["epa_registration_number"] == "EPA-RR-000001"
    assert ctx2["product"]["epa_registration_number"] == "EPA-RR-000002"
    assert ctx1["product"]["status"] == "REGISTERED"
    assert ctx2["product"]["status"] == "REGISTERED"
    # One mutation at creation, one at the approval cascade.
    assert ctx1["product"]["version"] == 2
    assert ctx2["product"]["version"] == 2


def test_amendment_create_computes_review_due_and_priia_category(api):
    """PRD §3.5: "The base is 365 days for a `NEW_USE`, 180 days for a
    `RATE_CHANGE`, and 91 days for a `METHOD_CHANGE`."
    PRD §3.5: "The amendment's `review_due_at` is its `submitted_at` plus the
    total days, and its `priia_category` is the amendment-type string, suffixed
    `-EXPEDITED` exactly when the halving applied."
    PRD §3.5: "Every successful filing advances the product's `version` by one,
    stamps `registrant_ref` and `submitted_at`, and births the amendment in
    `SUBMITTED` with `decided_at` still null."

    Design: Corner/entities/amendment_create_computes_review_due_and_priia_category
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    set_clock("2026-09-05T00:00:00Z")
    site_id = ctx["use_sites"][0]["id"]
    amendment = file_method_change_amendment(
        product_id, site_id, new_method="AERIAL",
        registrant_headers=REGISTRANT,
        expected_product_version=get_product_version(product_id))
    assert_label_amendment(amendment)
    assert_iso_instant_equal(amendment["submitted_at"], "2026-09-05T00:00:00Z",
                             "submitted_at")
    # 91-day base, no adders, no halving.
    assert_iso_instant_equal(amendment["review_due_at"], "2026-12-05T00:00:00Z",
                             "review_due_at")
    assert amendment["priia_category"] == "METHOD_CHANGE"
    assert amendment["status"] == "SUBMITTED"
    assert amendment["decided_at"] is None


def test_product_create_unknown_field_returns_invalid_request(api):
    """PRD §2.8: "3. **Request schema** — required fields present, types correct,
    enum members inside their declared sets, unknown keys rejected, and every
    conditional-requiredness rule honored:"
    PRD §2.8: "Any failure is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/product_create_unknown_field_returns_invalid_request
    """
    ai = create_active_ingredient()
    payload = make_product_payload(ai["id"], product_name="Nominex G")
    payload["status"] = "REGISTERED"  # system-managed field smuggled by client
    resp = api_client.create_product(payload, REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_products(REVIEWER))
    assert meta["total_count"] == 0, "no Product row may persist after a 400"


def test_product_create_missing_product_name_returns_invalid_request(api):
    """PRD §2.8: "3. **Request schema** — required fields present, types correct,
    enum members inside their declared sets, unknown keys rejected, and every
    conditional-requiredness rule honored:"
    PRD §2.8: "Any failure is `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "a `RegistrantRepresentative` creates a product shell by supplying a
    `product_name`, the `active_ingredient_id` of the product's single active
    ingredient, and a `formulation_type`"

    Design: Corner/entities/product_create_missing_product_name_returns_invalid_request
    """
    ai = create_active_ingredient()
    payload = make_product_payload(ai["id"])
    del payload["product_name"]
    resp = api_client.create_product(payload, REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_create_invalid_formulation_enum_returns_invalid_request(api):
    """PRD §3.1: "a `formulation_type` of `EMULSIFIABLE_CONCENTRATE`, `GRANULAR`,
    `WETTABLE_POWDER`, `READY_TO_USE`, or `SEED_TREATMENT`"
    PRD §2.8: "3. **Request schema** — required fields present, types correct,
    enum members inside their declared sets, unknown keys rejected, and every
    conditional-requiredness rule honored:"
    PRD §2.8: "Any failure is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/product_create_invalid_formulation_enum_returns_invalid_request
    """
    ai = create_active_ingredient()
    payload = make_product_payload(ai["id"], product_name="Nominex G",
                                   formulation_type="AEROSOL")
    resp = api_client.create_product(payload, REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
