"""Consistency claim: a four-hop cascade is readable the instant the write returns."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_acres_equals,
    assert_instant_equals,
    assert_page_meta,
    assert_status,
    assert_version_advanced,
    assert_version_is,
)
from test_helpers.fixtures import (
    client,
    parcels_page,
    publish_setback_rule,
    read_consent,
    read_landowner,
    read_parcel,
    register_landowner,
    register_parcel,
    request_consent,
)
from test_helpers.test_users import LAND_AGENT

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"


def _consent_awaiting_signature_on_a_hundred_acre_tract():
    """A quarter-acre-per-acre ordinance, a hundred acres, and an unsigned consent."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    rule = publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=500,
        encumbrance_rate_per_acre=0.2500,
        consent_waivable=True,
    )
    parcel = register_parcel(
        landowner_id,
        apn="R-9001-001",
        county_fips=CLEAN_COUNTY,
        gross_acres=100.00,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    assert_acres_equals(parcel["raw_setback_acres"], 25.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 75.00, "buildable_acres")
    assert_status(parcel, "SCREENING", "parcel")
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")
    consent = request_consent(
        parcel["id"], rule["id"], neighbor_name="H. Vaughn", consent_expiry_days=60
    )
    assert_status(consent, "REQUESTED", "consent")
    assert_acres_equals(consent["released_acres"], 0.00, "released_acres")
    return landowner_id, parcel, consent


def test_the_grant_response_already_carries_the_released_acreage():
    """
    The whole cascade runs inside the request that triggered it, so the grant's own
    response — not some later read — is where the twenty released acres first appear.

    PRD: "The grant then cascades in three hops, and the whole cascade completes inside
    the same request."

    Design: Corner/consistency_model/derived_totals_are_readable_immediately_after_the_write_returns
    """
    _landowner_id, _parcel, consent = _consent_awaiting_signature_on_a_hundred_acre_tract()

    response = client().grant_neighbor_consent(consent["id"], {}, LAND_AGENT)

    granted = validate_success(response, 200)
    assert_status(granted, "GRANTED", "consent")
    assert_acres_equals(granted["released_acres"], 20.00, "released_acres")
    assert_instant_equals(granted["granted_at"], "2026-08-01T00:00:00Z", "granted_at")


def test_the_next_read_already_shows_the_promotion_and_the_posture_sync():
    """
    No delay, no retry and no polling loop: the immediately following reads show the
    parcel's recomputed acreage and its promotion, the owner's advanced posture, and a
    filtered collection that already counts the parcel.

    PRD: "The API's central promise is that every derived number — a parcel's buildable
    acreage, its screening tier, an option's fee ledger, a lease's decommissioning
    security, an annual rent invoice — is computed by the server from pinned formulas
    rather than supplied by a client, and that every state change which invalidates one of
    those numbers recomputes it immediately and cascades the consequence to every
    dependent record in the same request."

    Design: Corner/consistency_model/derived_totals_are_readable_immediately_after_the_write_returns
    """
    landowner_id, parcel, consent = _consent_awaiting_signature_on_a_hundred_acre_tract()

    validate_success(
        client().grant_neighbor_consent(consent["id"], {}, LAND_AGENT), 200
    )

    after = read_parcel(parcel["id"])
    assert_acres_equals(after["consent_released_acres"], 20.00, "consent_released_acres")
    assert_acres_equals(
        after["setback_encumbered_acres"], 5.00, "setback_encumbered_acres"
    )
    assert_acres_equals(after["buildable_acres"], 95.00, "buildable_acres")
    assert_status(after, "QUALIFIED", "parcel")
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")
    _rows, meta = parcels_page(LAND_AGENT, status="QUALIFIED")
    assert_page_meta(meta, total_count=1)


def test_repeating_the_reads_returns_the_same_authoritative_state():
    """
    Every read is served from one authoritative state rather than from a replica that
    may still be catching up, so the cascade bumped each row exactly once and repeating
    either read changes nothing.

    PRD: "Both the consent and the parcel have their `version` incremented and their
    `updated_at` refreshed."

    Design: Corner/consistency_model/derived_totals_are_readable_immediately_after_the_write_returns
    """
    _landowner_id, parcel, consent = _consent_awaiting_signature_on_a_hundred_acre_tract()
    before = read_parcel(parcel["id"])

    validate_success(
        client().grant_neighbor_consent(consent["id"], {}, LAND_AGENT), 200
    )

    first_read = read_parcel(parcel["id"])
    # PRD 2.4 shows a cascade-driven parcel write landing "two or three higher",
    # so only the advance itself is pinned, not the size of the step.
    assert_version_advanced(before, first_read, "parcel")
    assert_version_is(read_consent(consent["id"]), consent["version"] + 1, "consent")
    assert read_parcel(parcel["id"]) == first_read, "a repeated read returned other data"
    assert read_consent(consent["id"]) == read_consent(consent["id"])
