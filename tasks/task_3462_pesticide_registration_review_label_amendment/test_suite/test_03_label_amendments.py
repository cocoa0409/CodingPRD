"""Label amendments: OCC-guarded filing, tiered review timelines, ESA bulletin
conflicts, approval side effects on the label, and terminal-state lockdown
(PRD §2.7, §3.5, §3.6).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_amendment,
    assert_iso_instant_equal,
    assert_label_amendment,
    create_bulletin,
    create_registered_product,
    file_method_change_amendment,
    file_new_use_amendment,
    file_rate_change_amendment,
    get_amendment,
    get_product_version,
    list_product_tolerances,
    list_product_use_sites,
    make_amendment_payload,
    make_method_change_payload,
    make_new_use_payload,
    make_rate_change_payload,
    set_clock,
    setup_cancelled_product,
    user_id_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]


def test_amendment_timeline_tiered_conditionals(api):
    """PRD §3.5: "The base is 365 days for a `NEW_USE`, 180 days for a
    `RATE_CHANGE`, and 91 days for a `METHOD_CHANGE`. Three adders accumulate onto
    the base: 90 days when the product's `classification` is `RESTRICTED_USE`; 180
    days when a `NEW_USE` payload includes `tolerance_ppm` (a new food use); and
    60 days when any endangered-species bulletin of the product is `IN_EFFECT`."
    PRD §3.5: "A `METHOD_CHANGE` filed with `expedited` true halves the
    accumulated total, rounding up to a whole number of days."
    PRD §2.7: "every successful amendment filing itself advances the product's
    `version` by one"

    Design: Difficulty/combinatorial_formula/amendment_timeline_tiered_conditionals
    """
    ctx = create_registered_product(use_pattern="FOOD_USE",
                                    final_classification="RESTRICTED_USE")
    product_id = ctx["product"]["id"]
    create_bulletin(product_id, REVIEWER, county_fips="06037",
                    restriction_code="SEASONAL_WINDOW", window_start_month=3,
                    window_end_month=8, consultation_reference="USFWS-BO-2026-114")
    set_clock("2026-09-05T00:00:00Z")

    pv1 = get_product_version(product_id)
    am_new_use = file_new_use_amendment(
        product_id, registrant_headers=REGISTRANT, commodity_code="SOYBEAN",
        tolerance_ppm=0.05, expected_product_version=pv1)
    assert_label_amendment(am_new_use)
    assert_iso_instant_equal(am_new_use["submitted_at"], "2026-09-05T00:00:00Z",
                             "submitted_at")
    # 365 base + 90 RUP + 180 new-food-use + 60 bulletin = 695 days.
    assert_iso_instant_equal(am_new_use["review_due_at"], "2028-07-31T00:00:00Z",
                             "review_due_at")
    assert am_new_use["priia_category"] == "NEW_USE"

    pv2 = get_product_version(product_id)
    assert pv2 == pv1 + 1, "each successful filing advances Product.version by 1"
    site_id = ctx["use_sites"][0]["id"]
    am_method = file_method_change_amendment(
        product_id, site_id, new_method="AERIAL", expedited=True,
        registrant_headers=REGISTRANT, expected_product_version=pv2)
    # (91 base + 90 RUP + 60 bulletin) = 241, expedited ceil(241/2) = 121 days.
    assert_iso_instant_equal(am_method["review_due_at"], "2027-01-04T00:00:00Z",
                             "review_due_at")
    assert am_method["priia_category"] == "METHOD_CHANGE-EXPEDITED"
    assert get_product_version(product_id) == pv2 + 1


def test_amendment_create_state_error_beats_rate_cap(api):
    """PRD §2.8: "The stages are evaluated in the order below, and a failure at
    any stage short-circuits all later stages"
    PRD §3.5: "Filing requires the product to be `REGISTERED` or `UNDER_REVIEW`: a
    `CANCELLED` product forbids the filing with `ERR_PRODUCT_TERMINAL`, and an
    `UNREGISTERED` or `SUSPENDED` product fails `ERR_PRODUCT_NOT_REGISTERED`."
    PRD §3.5: "a `NEW_USE` site rate or a `RATE_CHANGE` target rate above the cap
    is rejected with `ERR_RATE_EXCEEDS_SAFETY_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/amendment_create_state_error_beats_rate_cap
    """
    ctx = setup_cancelled_product(authorized_units=100, stocks_method="FIXED")
    product_id = ctx["product"]["id"]
    site_id = ctx["use_sites"][0]["id"]
    pv = get_product_version(product_id)
    resp = api_client.create_label_amendment(
        make_amendment_payload(product_id, "RATE_CHANGE",
                               make_rate_change_payload(site_id, 9.0), pv),
        REGISTRANT,
    )
    # The 409 state gate (stage 7) fires ahead of the 422 safety cap (stage 8)
    # even though 9.0 lbs/acre exceeds the 8.0 cap.
    validate_error(resp, ApiErrorId.ERR_PRODUCT_TERMINAL)
    assert get_product_version(product_id) == pv, (
        "a rejected filing must not advance Product.version")


def test_occ_correct_version_then_stale_version_sequence(api):
    """PRD §2.7: "The request body must carry `expected_product_version`, holding
    the `version` of the target product as the filing client last observed it; the
    field is not optional. If another writer has advanced the product's `version`
    since that observation, the two values differ and the filing is rejected with
    `ERR_STALE_PRODUCT_VERSION` (HTTP 412) — even when every state precondition on
    the product still holds."
    PRD §2.7: "every successful amendment filing itself advances the product's
    `version` by one, so a client holding a stale observation is necessarily
    filing against a label record that no longer matches its view."

    Design: Corner/cross_cutting_layers/occ_correct_version_then_stale_version_sequence
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    site_id = ctx["use_sites"][0]["id"]
    pv = get_product_version(product_id)

    first = file_method_change_amendment(
        product_id, site_id, new_method="AERIAL", registrant_headers=REGISTRANT,
        expected_product_version=pv)
    assert first["status"] == "SUBMITTED"
    assert get_product_version(product_id) == pv + 1

    # Replaying the same observed version is stale after the first filing.
    resp = api_client.create_label_amendment(
        make_amendment_payload(
            product_id, "METHOD_CHANGE",
            make_method_change_payload(site_id, "CHEMIGATION"), pv),
        REGISTRANT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PRODUCT_VERSION)
    assert get_product_version(product_id) == pv + 1
    _, meta = validate_paginated(
        api_client.list_label_amendments(REGISTRANT, params={"product_id": product_id}))
    assert meta["total_count"] == 1, "the stale filing must not persist a row"


def test_amendment_approval_new_use_materializes_use_site_and_tolerance(api):
    """PRD §3.5: "For `NEW_USE`, the system mints the payload's use site directly
    in `ACTIVE` with `origin` `AMENDMENT` — a documented exception to the usual
    rule that use sites are born `PROPOSED` — and when the payload carries
    `tolerance_ppm` it also mints a tolerance directly in `ESTABLISHED` with
    `origin` `AMENDMENT` and `established_at` stamped, again bypassing the usual
    `PROPOSED` birth."

    Design: Corner/state_machines/amendment_approval_new_use_materializes_use_site_and_tolerance
    """
    ctx = create_registered_product(use_pattern="FOOD_USE")
    product_id = ctx["product"]["id"]
    amendment = file_new_use_amendment(
        product_id, registrant_headers=REGISTRANT, commodity_code="SOYBEAN",
        tolerance_ppm=0.05)
    approved = approve_amendment(amendment["id"])
    assert approved["status"] == "APPROVED"

    sites = list_product_use_sites(product_id, status="ACTIVE")
    assert len(sites) == 2
    by_code = {s["site_code"]: s for s in sites}
    assert by_code["CORN"]["origin"] == "INITIAL_APPLICATION"
    assert by_code["SOYBEAN"]["origin"] == "AMENDMENT"
    assert by_code["SOYBEAN"]["max_application_rate_lbs_acre"] == 1.5

    tolerances = list_product_tolerances(product_id)
    assert len(tolerances) == 2
    by_commodity = {t["commodity_code"]: t for t in tolerances}
    assert by_commodity["CORN"]["status"] == "ESTABLISHED"
    assert by_commodity["CORN"]["origin"] == "INITIAL_APPLICATION"
    assert by_commodity["SOYBEAN"]["status"] == "ESTABLISHED"
    assert by_commodity["SOYBEAN"]["origin"] == "AMENDMENT"
    assert_iso_instant_equal(by_commodity["SOYBEAN"]["established_at"],
                             "2026-09-01T00:00:00Z", "tolerance.established_at")


def test_amendment_approval_rate_change_mutates_use_site_in_place(api):
    """PRD §3.5: "For `RATE_CHANGE`, the target use site's
    `max_application_rate_lbs_acre` is rewritten to
    `new_max_application_rate_lbs_acre`."

    Design: Corner/state_machines/amendment_approval_rate_change_mutates_use_site_in_place
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    site_id = ctx["use_sites"][0]["id"]
    amendment = file_rate_change_amendment(
        product_id, site_id, new_rate=3.0, registrant_headers=REGISTRANT)
    approved = approve_amendment(amendment["id"])
    assert approved["status"] == "APPROVED"

    sites = list_product_use_sites(product_id)
    assert len(sites) == 1, "a RATE_CHANGE rewrites in place; no new row appears"
    assert sites[0]["id"] == site_id
    assert sites[0]["max_application_rate_lbs_acre"] == 3.0
    assert sites[0]["status"] == "ACTIVE"


def test_amendment_withdraw_after_approval_returns_not_pending(api):
    """PRD §3.5: "The registrant may withdraw a `SUBMITTED` amendment with an
    optional `reason`; withdrawal from any other status is likewise
    `ERR_AMENDMENT_NOT_PENDING`."

    Design: Corner/state_machines/amendment_withdraw_after_approval_returns_not_pending
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    site_id = ctx["use_sites"][0]["id"]
    amendment = file_rate_change_amendment(
        product_id, site_id, new_rate=3.0, registrant_headers=REGISTRANT)
    approve_amendment(amendment["id"])

    resp = api_client.withdraw_label_amendment(amendment["id"], REGISTRANT, payload={})
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_PENDING)
    assert get_amendment(amendment["id"])["status"] == "APPROVED"
    # The approved label change stays applied.
    sites = list_product_use_sites(product_id)
    assert sites[0]["max_application_rate_lbs_acre"] == 3.0


def test_expedited_flag_on_new_use_returns_invalid_request(api):
    """PRD §3.5: "A `METHOD_CHANGE` payload carries `use_site_id`,
    `new_application_method`, and an optional `expedited` flag; setting
    `expedited` on any other amendment type is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/expedited_flag_on_new_use_returns_invalid_request
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    pv = get_product_version(product_id)
    resp = api_client.create_label_amendment(
        make_amendment_payload(product_id, "NEW_USE",
                               make_new_use_payload(expedited=True), pv),
        REGISTRANT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_amendment_use_site_of_other_product_returns_mismatch(api):
    """PRD §3.5: "A `use_site_id` that does not name a use site of the same
    product fails `ERR_USE_SITE_PRODUCT_MISMATCH` (HTTP 400)."

    Design: Corner/errors/amendment_use_site_of_other_product_returns_mismatch
    """
    ctx1 = create_registered_product(product_overrides={"product_name": "Nominex G"})
    ctx2 = create_registered_product(product_overrides={"product_name": "Nominex WP"})
    product_id = ctx1["product"]["id"]
    other_site_id = ctx2["use_sites"][0]["id"]
    pv = get_product_version(product_id)

    resp = api_client.create_label_amendment(
        make_amendment_payload(product_id, "RATE_CHANGE",
                               make_rate_change_payload(other_site_id, 2.0), pv),
        REGISTRANT,
    )
    validate_error(resp, ApiErrorId.ERR_USE_SITE_PRODUCT_MISMATCH)
    assert get_product_version(product_id) == pv
    _, meta = validate_paginated(
        api_client.list_label_amendments(REGISTRANT, params={"product_id": product_id}))
    assert meta["total_count"] == 0, "no amendment row may persist after a 400"


def test_esa_bulletin_blocks_conflicting_amendments(api):
    """PRD §3.6: "While a bulletin is `IN_EFFECT` it has two teeth, both felt at
    amendment filing time (§3.5): a `PROHIBITED` bulletin blocks `NEW_USE` filings
    on the product, and a `RATE_CAP` bulletin caps newly filed rates at its
    `rate_cap_lbs_acre` — violations fail `ERR_ESA_PROHIBITION_CONFLICT`"

    Design: Corner/validations/esa_bulletin_blocks_conflicting_amendments
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    site_id = ctx["use_sites"][0]["id"]
    create_bulletin(product_id, REVIEWER, county_fips="06037",
                    restriction_code="RATE_CAP", rate_cap_lbs_acre=1.0,
                    window_start_month=3, window_end_month=8,
                    consultation_reference="USFWS-BO-2026-130")
    create_bulletin(product_id, REVIEWER, county_fips="48101",
                    restriction_code="PROHIBITED", window_start_month=1,
                    window_end_month=12, consultation_reference="USFWS-BO-2026-131")

    pv = get_product_version(product_id)
    resp_over = api_client.create_label_amendment(
        make_amendment_payload(product_id, "RATE_CHANGE",
                               make_rate_change_payload(site_id, 2.0), pv),
        REGISTRANT,
    )
    validate_error(resp_over, ApiErrorId.ERR_ESA_PROHIBITION_CONFLICT)
    assert get_product_version(product_id) == pv

    # A rate exactly at the cap is allowed; only rates above it conflict.
    at_cap = file_rate_change_amendment(
        product_id, site_id, new_rate=1.0, registrant_headers=REGISTRANT,
        expected_product_version=pv)
    assert at_cap["status"] == "SUBMITTED"

    pv2 = get_product_version(product_id)
    assert pv2 == pv + 1
    resp_new_use = api_client.create_label_amendment(
        make_amendment_payload(product_id, "NEW_USE", make_new_use_payload(), pv2),
        REGISTRANT,
    )
    validate_error(resp_new_use, ApiErrorId.ERR_ESA_PROHIBITION_CONFLICT)
    assert get_product_version(product_id) == pv2
