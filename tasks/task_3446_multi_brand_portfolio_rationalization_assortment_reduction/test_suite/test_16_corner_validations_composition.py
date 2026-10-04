"""Corner queue: composition and eligibility validation claims — negotiation
brand_terms shape and channel-conflict guard, divestiture core-brand and
signing-window checks, and qualification-run payload sanity.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_brand_term,
    create_combined_negotiation_payload,
    create_divestiture_payload,
    create_qualification_run_payload,
    create_retailer,
    create_sign_spa_payload,
    make_plant_director_headers,
    setup_divestiture_proposed,
    setup_transfer_planned,
    validate_error,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]


def test_negotiation_single_brand_returns_not_combined():
    """PRD §3.6: "`brand_terms` holds between 2 and 5 entries — fewer or more
    is rejected with `ERR_NOT_COMBINED` (HTTP 422)".

    Design: Corner/validations/negotiation_single_brand_returns_not_combined
    """
    retailer = create_retailer(risk_rating="LOW")
    brand = create_brand()
    resp = api_client.create_combined_negotiation(
        create_combined_negotiation_payload(
            retailer["id"], [create_brand_term(brand["id"], 100, 90)]
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_COMBINED)


def test_negotiation_with_under_review_brand_returns_brand_not_negotiable():
    """PRD §3.6: "Every referenced brand must currently be `ACTIVE`: including
    a brand that is `UNDER_REVIEW`, `DIVESTING`, `DIVESTED`, or `EXITED` trips
    the channel-conflict guard and is rejected with `ERR_BRAND_NOT_NEGOTIABLE`
    (HTTP 422)."

    Design: Corner/validations/negotiation_with_under_review_brand_returns_brand_not_negotiable
    """
    retailer = create_retailer(risk_rating="MEDIUM")
    brand_active = create_brand(core_flag=True)
    brand_under_review, _ = setup_divestiture_proposed()  # open divestiture
    assert brand_under_review["core_flag"] is False
    terms = [create_brand_term(brand_active["id"], 100, 90),
             create_brand_term(brand_under_review["id"], 60, 50)]
    resp = api_client.create_combined_negotiation(
        create_combined_negotiation_payload(retailer["id"], terms), PM
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_NOT_NEGOTIABLE)


def test_divestiture_on_core_brand_returns_brand_core():
    """PRD §3.5: "The target brand must be non-core: proposing a divestiture
    for a brand whose `core_flag` is true is rejected with `ERR_BRAND_CORE`
    (HTTP 422)."

    Design: Corner/validations/divestiture_on_core_brand_returns_brand_core
    """
    brand = create_brand(core_flag=True)
    resp = api_client.create_divestiture(
        create_divestiture_payload(brand["id"]), PM
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_CORE)


def test_close_date_outside_tsa_window_returns_error():
    """PRD §3.5: "the window must be coherent: `tsa_start_date` strictly before
    `tsa_end_date`, with the divestiture's `expected_close_date` lying within
    the closed interval from `tsa_start_date` to `tsa_end_date` inclusive. A
    violation is rejected with `ERR_CLOSE_DATE_OUTSIDE_TSA` (HTTP 422)."

    Design: Corner/validations/close_date_outside_tsa_window_returns_error
    """
    # expected_close 2026-10-01 precedes the offered TSA start 2026-11-01.
    _, divestiture = setup_divestiture_proposed(
        divestiture_overrides={"expected_close_date": "2026-10-01T00:00:00Z"}
    )
    resp = api_client.sign_divestiture_spa(
        divestiture["id"],
        create_sign_spa_payload(tsa_start_date="2026-11-01T00:00:00Z",
                                tsa_end_date="2027-11-01T00:00:00Z"),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_CLOSE_DATE_OUTSIDE_TSA)
    tsas, _ = validate_paginated(
        api_client.list_tsas(PM, params={"divestiture_id": divestiture["id"]})
    )
    assert tsas == [], "a rejected sign-spa must create no TSA"
    after = validate_ok(api_client.get_divestiture(divestiture["id"], PM))
    assert after["divestiture_status"] == "PROPOSED"


def test_run_rejects_exceeding_produced_returns_invalid_run():
    """PRD §3.4: "Each run supplies a `run_date` (the logical date the trial
    ran), `units_produced` (at least 1), and `units_rejected` (zero or greater
    and never more than `units_produced`, else `ERR_INVALID_RUN`, HTTP 422)."

    Design: Corner/validations/run_rejects_exceeding_produced_returns_invalid_run
    """
    _, _, target_plant, _, transfer = setup_transfer_planned()
    resp = api_client.record_qualification_run(
        transfer["id"],
        create_qualification_run_payload(units_produced=100, units_rejected=101),
        make_plant_director_headers(target_plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_RUN)
    runs, _ = validate_paginated(
        api_client.list_qualification_runs(transfer["id"], PM)
    )
    assert runs == [], "an invalid run must not be recorded"
