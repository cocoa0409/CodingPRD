"""Valuation methods: guide tool, certified appraisal, auction composite,
OCC on vehicle, and valuation lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_appraisal_payload,
    create_guide_tool_valuation,
    create_member,
    create_published_guide,
    create_valuation_payload,
    create_vehicle,
    get_vehicle,
    make_appraiser_headers,
    make_underwriter_headers,
    post_auction_comp,
    propose_and_approve,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def _member_and_vehicle(vin):
    member, m_headers = create_member()
    vehicle = create_vehicle(member, vin=vin)
    return member, m_headers, vehicle


def test_guide_tool_computed_value_base_times_condition(api):
    """PRD §3.5: "The computed value is the entry's `base_value_cents`
    multiplied by the condition multiplier for the vehicle's `condition_grade`
    — 1.25 for `EXCELLENT`, 1.00 for `GOOD`, 0.75 for `FAIR`, 0.50 for
    `PROJECT` — rounded half-up to whole cents."

    Design: Corner/calculations/guide_tool_condition_multiplier_applied
    """
    member, m_headers = create_member()
    vehicle = create_vehicle(member, vin="VIN109", condition_grade="EXCELLENT")
    create_published_guide(base_value_cents=3_200_000)
    valuation = create_guide_tool_valuation(vehicle["id"], 4_000_000)
    assert valuation["computed_value_cents"] == 4_000_000, (
        f"3200000 x 1.25 must compute 4000000, got {valuation['computed_value_cents']}"
    )


def test_dual_variant_guide_tool_value(api):
    """PRD §3.5: "Under the guide-tool method, the valuation pins the
    currently `PUBLISHED` guide as its `guide_id` and looks up the guide entry
    matching the vehicle's class, make, and model year within the entry's
    inclusive year range."
    PRD §3.5: "The computed value is the entry's `base_value_cents` multiplied
    by the condition multiplier for the vehicle's `condition_grade` — 1.25 for
    `EXCELLENT`, 1.00 for `GOOD`, 0.75 for `FAIR`, 0.50 for `PROJECT` — rounded
    half-up to whole cents."

    Design: Difficulty/dual_variant_calc/agreed_value_guide_vs_appraisal_divergence
    """
    member, m_headers, vehicle = _member_and_vehicle("VIN001")
    create_published_guide(base_value_cents=3_000_000)
    valuation = create_guide_tool_valuation(vehicle["id"], 3_000_000)
    assert valuation["computed_value_cents"] == 3_000_000, (
        f"GUIDE_TOOL on a GOOD vehicle over a 3000000 base must compute "
        f"3000000, got {valuation['computed_value_cents']}"
    )


def test_dual_variant_certified_appraisal_value_diverges(api):
    """PRD §3.5: "The computed value is then exactly the linked appraisal's
    `appraised_value_cents`."
    PRD §3.5: "How `computed_value_cents` is derived depends on the method,
    and for the same vehicle the guide-tool and certified-appraisal variants
    generally produce different numbers — this dual-variant split is
    deliberate."

    Design: Difficulty/dual_variant_calc/agreed_value_guide_vs_appraisal_divergence
    """
    member, m_headers, vehicle = _member_and_vehicle("VIN001D")
    create_published_guide(base_value_cents=3_000_000)
    guide_valuation = create_guide_tool_valuation(vehicle["id"], 3_000_000)
    assert guide_valuation["computed_value_cents"] == 3_000_000

    appraiser_headers = make_appraiser_headers("appraiser-1")
    appraisal = validate_success(
        api.submit_appraisal(
            vehicle["id"],
            create_appraisal_payload(appraised_value_cents=3_500_000),
            appraiser_headers,
        ),
        expected_status=201,
    )
    certified = validate_success(
        api.certify_appraisal(appraisal["id"], {"decision": "CERTIFY"},
                              make_underwriter_headers("uw-1"))
    )
    assert certified["status"] == "CERTIFIED"

    fresh = get_vehicle(vehicle["id"])
    appraisal_valuation = validate_success(
        api.create_valuation(
            vehicle["id"],
            create_valuation_payload(
                method="CERTIFIED_APPRAISAL",
                appraisal_id=appraisal["id"],
                proposed_agreed_value_cents=3_500_000,
                expected_vehicle_version=fresh["version"],
            ),
            UW,
        ),
        expected_status=201,
    )
    assert appraisal_valuation["computed_value_cents"] == 3_500_000, (
        "CERTIFIED_APPRAISAL computed value must equal the linked appraisal"
    )
    assert appraisal_valuation["computed_value_cents"] != guide_valuation["computed_value_cents"], (
        "Same vehicle, different methods must produce different computed values"
    )


def test_auction_composite_trimmed_mean(api):
    """PRD §3.5: "Otherwise the selector takes up to the five most recent
    comparables, ordered by sale date descending and then record creation
    descending; when at least four comparables are in play, one occurrence of
    the highest sale price and one occurrence of the lowest are dropped, and
    the computed value is the mean of the remaining sale prices, rounded
    half-up to whole cents."

    Design: Corner/calculations/auction_composite_trimmed_mean
    """
    member, m_headers, vehicle = _member_and_vehicle("VIN107")
    post_auction_comp(2_800_000, "2026-03-01T00:00:00Z", year=1970, source_name="A")
    post_auction_comp(3_000_000, "2026-04-01T00:00:00Z", year=1969, source_name="B")
    post_auction_comp(3_100_000, "2026-05-01T00:00:00Z", year=1971, source_name="C")
    post_auction_comp(3_200_000, "2026-06-01T00:00:00Z", year=1970, source_name="D")
    fresh = get_vehicle(vehicle["id"])
    resp = api.create_valuation(
        vehicle["id"],
        create_valuation_payload(
            method="AUCTION_COMPOSITE",
            proposed_agreed_value_cents=3_050_000,
            expected_vehicle_version=fresh["version"],
        ),
        UW,
    )
    data = validate_success(resp, expected_status=201)
    assert data["computed_value_cents"] == 3_050_000, (
        f"trim min 2800000 and max 3200000, mean(3000000, 3100000) == 3050000; "
        f"got {data['computed_value_cents']}"
    )


def test_occ_stale_vehicle_version_on_valuation_create(api):
    """PRD §2.7: "Creating a valuation for a vehicle requires the request to
    carry `expected_vehicle_version`, the client-observed `version` of the
    target `Vehicle`. If another writer has advanced the vehicle's version
    since the client last read it — for example, an approval that superseded
    the prior current valuation and bumped the vehicle's version — the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client
    from layering a new valuation onto a vehicle state it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_vehicle_version_on_valuation_create
    """
    member, m_headers, vehicle = _member_and_vehicle("VIN160")
    create_published_guide(base_value_cents=3_000_000)
    stale_version = vehicle["version"]
    # First valuation succeeds and bumps the vehicle version.
    create_guide_tool_valuation(vehicle["id"], 3_000_000)
    # Second create carrying the pre-first-create version must be rejected.
    resp = api.create_valuation(
        vehicle["id"],
        create_valuation_payload(
            method="GUIDE_TOOL",
            proposed_agreed_value_cents=3_100_000,
            expected_vehicle_version=stale_version,
        ),
        UW,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_vehicle_version_retry_with_fresh_version_succeeds(api):
    """PRD §2.7: "If another writer has advanced the vehicle's version since
    the client last read it — for example, an approval that superseded the
    prior current valuation and bumped the vehicle's version — the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
    layering a new valuation onto a vehicle state it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_vehicle_version_on_valuation_create
    """
    member, m_headers, vehicle = _member_and_vehicle("VIN160R")
    create_published_guide(base_value_cents=3_000_000)
    stale_version = vehicle["version"]
    create_guide_tool_valuation(vehicle["id"], 3_000_000)
    resp = api.create_valuation(
        vehicle["id"],
        create_valuation_payload(
            method="GUIDE_TOOL",
            proposed_agreed_value_cents=3_100_000,
            expected_vehicle_version=stale_version,
        ),
        UW,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    fresh = get_vehicle(vehicle["id"])
    retry = api.create_valuation(
        vehicle["id"],
        create_valuation_payload(
            method="GUIDE_TOOL",
            proposed_agreed_value_cents=3_100_000,
            expected_vehicle_version=fresh["version"],
        ),
        UW,
    )
    validate_success(retry, expected_status=201)
