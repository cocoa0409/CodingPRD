"""Methodology pinning: weight-sum gate, OCC stale-version precedence, factor
weight bounds, and the immutability freeze once fielding begins (PRD §2.6, §3.1)."""
from test_helpers import (
    ApiErrorId,
    add_brand,
    add_frame,
    create_methodology_payload,
    create_study,
    create_study_with_pinned_methodology,
    get_study,
    open_fielding,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

ML = TEST_USERS["methodology_lead_headers"]


def test_pin_weight_sum_mismatch_returns_422(api):
    """PRD §3.1: "Pinning is allowed only while the study is `DRAFT` or
    `DESIGN_LOCKED` (otherwise `ERR_METHODOLOGY_IMMUTABLE`), and only when the
    version's factors are non-empty, each within its `weight_bp` bounds
    (`ERR_FACTOR_WEIGHT_INVALID`), and summing to exactly 10000 basis points
    (`ERR_WEIGHT_SUM_MISMATCH`)."

    Design: Corner/validations/pin_weight_sum_mismatch_returns_422
    """
    study = create_study()
    bad_factors = [
        {"code": "QUAL", "name": "Quality & Reliability", "weight_bp": 6000, "ordinal": 1},
        {"code": "FEAT", "name": "Features & Controls", "weight_bp": 3000, "ordinal": 2},
    ]
    mv = validate_success(
        api.create_methodology_version(
            create_methodology_payload(study["id"], factors=bad_factors), ML
        ),
        expected_status=201,
    )
    resp = api.pin_methodology_version(mv["id"], {"expected_study_version": study["version"]}, ML)
    validate_error(resp, ApiErrorId.ERR_WEIGHT_SUM_MISMATCH)
    after = get_study(study["id"])
    assert after["status"] == "DRAFT" and after["version"] == 1
    assert after["active_methodology_id"] is None


def test_stale_version_beats_weight_mismatch(api):
    """PRD §2.6: "If that value does not equal the study's current `version`, the
    pin is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "When a request is malformed in more than one way, the server
    reports a single error, and the order in which checks run is fixed"
    (optimistic concurrency at item 4, domain constraints at item 8).

    Design: Corner/validations/stale_version_beats_weight_mismatch
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=3)
    study, mv1 = ctx["study"], ctx["mv"]
    stale_version = study["version"] - 1  # the pre-pin observation (1)
    bad_factors = [
        {"code": "QUAL", "name": "Quality & Reliability", "weight_bp": 6000, "ordinal": 1},
        {"code": "FEAT", "name": "Features & Controls", "weight_bp": 3000, "ordinal": 2},
    ]
    mv2 = validate_success(
        api.create_methodology_version(
            create_methodology_payload(study["id"], change_class="ADJUSTED", factors=bad_factors),
            ML,
        ),
        expected_status=201,
    )
    resp = api.pin_methodology_version(mv2["id"], {"expected_study_version": stale_version}, ML)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    mv2_after = validate_success(api.get_methodology_version(mv2["id"], ML))
    mv1_after = validate_success(api.get_methodology_version(mv1["id"], ML))
    assert mv2_after["status"] == "DRAFT"
    assert mv1_after["status"] == "PINNED"
    assert get_study(study["id"])["version"] == 2


def test_factor_weight_invalid_returns_422(api, methodology_lead_headers):
    """PRD §3.1: "a `weight_bp` weight in basis points that must be strictly
    greater than 0 and strictly less than 10000 ... A factor whose `weight_bp`
    falls outside its bounds fails the create with `ERR_FACTOR_WEIGHT_INVALID`"

    Design: Corner/errors/factor_weight_invalid_returns_422
    """
    study = create_study()
    bad_factors = [
        {"code": "QUAL", "name": "Quality & Reliability", "weight_bp": 0, "ordinal": 1},
        {"code": "FEAT", "name": "Features & Controls", "weight_bp": 10000, "ordinal": 2},
    ]
    resp = api.create_methodology_version(
        create_methodology_payload(study["id"], factors=bad_factors), methodology_lead_headers
    )
    validate_error(resp, ApiErrorId.ERR_FACTOR_WEIGHT_INVALID)
    versions = validate_success(
        api.list_study_methodology_versions(study["id"], methodology_lead_headers)
    )
    assert versions == [], "no methodology version may be created"


def test_methodology_create_after_fielding_returns_409(api, methodology_lead_headers):
    """PRD §3.1: "Methodology create is only permitted while the owning study is
    `DRAFT` or `DESIGN_LOCKED`; once fielding has begun or the study is terminal,
    the attempt fails with `ERR_METHODOLOGY_IMMUTABLE`."

    Design: Corner/errors/methodology_create_after_fielding_returns_409
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=1)
    sid = ctx["study"]["id"]
    brand = add_brand("BrandA")
    add_frame(sid, brand["id"])
    open_fielding(sid)

    resp = api.create_methodology_version(
        create_methodology_payload(sid, change_class="ADJUSTED", min_duration_seconds=200),
        methodology_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_METHODOLOGY_IMMUTABLE)
    versions = validate_success(
        api.list_study_methodology_versions(sid, methodology_lead_headers)
    )
    assert len(versions) == 1, "the frozen methodology surface admits no new version"
