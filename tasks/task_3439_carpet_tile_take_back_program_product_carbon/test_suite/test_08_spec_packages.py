"""Specification packages (PRD §3.8): issuance gates, the per-pair
package_version sequence with supersede, collection-scoped optimistic
concurrency, and the depth-3 publish cascade (PRD §2.9 cascade A).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_report,
    clear_report,
    create_claim,
    create_collection,
    create_released_batch,
    create_report,
    create_spec_package_payload,
    create_target,
    get_collection_version,
    issue_package,
    publish_report,
    set_clock,
    setup_collection_with_batch,
    setup_published_claim,
    setup_published_report,
    submit_report,
    validate_error,
    validate_success,
)

SECOND_MIX_50 = [
    (100, 0.40, "POST_CONSUMER_TILE", "NETCO"),
    (100, 2.10, "VIRGIN", "POLYCO"),
]


def _published_gate_collection():
    """Collection GAT with the canonical released batch and a PUBLISHED
    CRADLE_TO_GATE report."""
    set_clock()
    built = setup_collection_with_batch(
        collection_overrides={
            "name": "Gatehouse",
            "pattern_code": "GAT",
            "lifecycle_boundary": "CRADLE_TO_GATE",
            "claim_intent": "NONE",
        }
    )
    rep = setup_published_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")
    return built["collection"], rep


def _published_claim_and_package():
    """Collection CIR (GRAVE): PUBLISHED report REP-1 (lifecycle 6.750),
    PUBLISHED CARBON_NEGATIVE claim CL-1 (volume 100, required 1175.0 fully
    retired), and ISSUED package PKG-1 referencing both."""
    set_clock()
    col = create_collection(claim_intent="NONE")
    create_released_batch(col["id"])
    rep1 = setup_published_report(col["id"], boundary="CRADLE_TO_GRAVE")
    tgt = create_target()
    cl1 = setup_published_claim(
        col["id"],
        rep1["id"],
        claim_type="CARBON_NEGATIVE",
        claimed_volume_m2=100,
        boundary="CRADLE_TO_GRAVE",
        manufacturing_target_id=tgt["id"],
    )
    pkg1 = issue_package(col["id"], rep1["id"], claim_id=cl1["id"])
    return col, rep1, cl1, pkg1


def _publish_overlapping_second_report(col):
    """Release DL-105 (50 m2, produced 2026-09-20, embodied 6.000) and publish
    REP-2 over [2026-09-15, 2026-10-15), which overlaps REP-1's period."""
    create_released_batch(
        col["id"],
        mix=SECOND_MIX_50,
        dye_lot_code="DL-105",
        production_date="2026-09-20T00:00:00Z",
        produced_m2=50,
        mfg_intensity_kgco2e_per_m2=1.0,
        delta_e=0.6,
    )
    rep2 = create_report(
        col["id"],
        period_start="2026-09-15T00:00:00Z",
        period_end="2026-10-15T00:00:00Z",
        boundary="CRADLE_TO_GRAVE",
    )
    rep2 = submit_report(rep2)
    rep2 = assign_report(rep2)
    rep2 = clear_report(rep2)
    return publish_report(rep2)


def test_publish_supersedes_overlapping_published_report(api, admin_headers):
    """PRD §2.9 (cascade A): "Link 1: every other `PUBLISHED` report of the
    same collection whose half-open period overlaps the newly published
    report's period moves to `SUPERSEDED`."
    PRD §3.6: "The input set is every batch of the report's collection whose
    `production_date` falls inside the half-open period and whose status is
    `RELEASED` or `EXHAUSTED`."

    Design: Difficulty/transitive_cascade/publish_supersedes_report_retires_claim_revokes_package
    """
    col, rep1, _cl1, _pkg1 = _published_claim_and_package()
    rep2 = _publish_overlapping_second_report(col)
    assert rep2["status"] == "PUBLISHED"
    # Only DL-105's 2026-09-20 production date lies in [09-15, 10-15).
    assert rep2["operational_kgco2e_per_m2"] == pytest.approx(6.000, abs=1e-9)
    rep1_after = validate_success(api.get_pcf_report(rep1["id"], admin_headers))
    assert rep1_after["status"] == "SUPERSEDED"


def test_retired_claim_revokes_package(api, admin_headers):
    """PRD §2.9 (cascade A): "Link 2: every carbon claim in `PUBLISHED` whose
    `report_id` references a report superseded in link 1 moves to `RETIRED`.
    Link 3: every specification package in `ISSUED` whose `claim_id` references
    a claim retired in link 2 moves to `REVOKED`."

    Design: Difficulty/transitive_cascade/publish_supersedes_report_retires_claim_revokes_package
    """
    col, rep1, cl1, pkg1 = _published_claim_and_package()
    _publish_overlapping_second_report(col)
    claim = validate_success(api.get_carbon_claim(cl1["id"], admin_headers))
    assert claim["status"] == "RETIRED"
    package = validate_success(api.get_spec_package(pkg1["id"], admin_headers))
    assert package["status"] == "REVOKED"
    # The package is revoked, not rewritten.
    assert package["package_version"] == 1
    assert package["report_id"] == rep1["id"]
    assert package["claim_id"] == cl1["id"]


def test_package_version_increments_and_prior_is_superseded(api, admin_headers):
    """PRD §3.8: "Issuing a package for a firm-and-collection pair that already
    has an `ISSUED` package supersedes it: the older package moves to
    `SUPERSEDED`, and the new package's `package_version` continues the pair's
    issuance sequence — a per-(`architect_firm`, `collection_id`) counter that
    starts at 1 for the first package of the pair."

    Design: Corner/entities/package_version_increments_and_prior_is_superseded
    """
    col, rep = _published_gate_collection()
    pkg1 = issue_package(col["id"], rep["id"], architect_firm="FIRM-A")
    assert pkg1["package_version"] == 1
    pkg2 = issue_package(col["id"], rep["id"], architect_firm="FIRM-A")
    assert pkg2["status"] == "ISSUED"
    assert pkg2["package_version"] == 2, "next in the FIRM-A x collection sequence"
    pkg3 = issue_package(col["id"], rep["id"], architect_firm="FIRM-B")
    assert pkg3["status"] == "ISSUED"
    assert pkg3["package_version"] == 1, "FIRM-B starts its own sequence"
    pkg1_after = validate_success(api.get_spec_package(pkg1["id"], admin_headers))
    assert pkg1_after["status"] == "SUPERSEDED"
    assert pkg1_after["package_version"] == 1


def test_package_create_with_unpublished_claim_returns_422(api, specifier_headers):
    """PRD §3.8: "A `claim_id` may be included to bind a carbon claim into the
    package; when present it too must be `PUBLISHED`, otherwise
    `ERR_CLAIM_NOT_PUBLISHED` (HTTP 422)."

    Design: Corner/validations/package_create_with_unpublished_claim_returns_422
    """
    col, rep = _published_gate_collection()
    claim = create_claim(
        col["id"],
        rep["id"],
        claim_type="CARBON_NEUTRAL",
        claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )
    assert claim["status"] == "DRAFT"
    payload = create_spec_package_payload(
        col["id"],
        rep["id"],
        get_collection_version(col["id"]),
        claim_id=claim["id"],
    )
    resp = api.create_spec_package(payload, specifier_headers)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PUBLISHED)


def test_package_create_with_unpublished_report_returns_422(api, specifier_headers):
    """PRD §3.8: "Issuance names the `architect_firm`, the `collection_id`, and
    the `report_id` of a footprint report that must be `PUBLISHED` at issuance
    — otherwise `ERR_REPORT_NOT_PUBLISHED` (HTTP 422)."

    Design: Corner/validations/package_create_with_unpublished_report_returns_422
    """
    set_clock()
    built = setup_collection_with_batch(
        collection_overrides={
            "name": "Gatehouse",
            "pattern_code": "GAT",
            "lifecycle_boundary": "CRADLE_TO_GATE",
            "claim_intent": "NONE",
        }
    )
    rep = create_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")
    rep = submit_report(rep)
    rep = assign_report(rep)
    rep = clear_report(rep)  # VERIFIED — verification is not publication
    payload = create_spec_package_payload(
        built["collection"]["id"],
        rep["id"],
        get_collection_version(built["collection"]["id"]),
    )
    resp = api.create_spec_package(payload, specifier_headers)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_PUBLISHED)


def test_occ_package_create_stale_version_returns_412(
    api, admin_headers, specifier_headers
):
    """PRD §2.7: "Opening a footprint report and issuing a specification
    package each require the request body to carry
    `expected_collection_version`, holding the version of the target product
    collection the client last observed."
    PRD §2.7: "If the value presented does not match the parent's current
    `version` — because another writer's create has advanced that version
    since the client last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), protecting the client from, for example,
    superseding a package it has never seen or drafting a report over a draft
    it did not know had been replaced."

    Design: Corner/cross_cutting_layers/occ_package_create_stale_version_returns_412
    """
    col, rep = _published_gate_collection()
    captured = get_collection_version(col["id"])
    pkg_a = issue_package(
        col["id"], rep["id"],
        expected_collection_version=captured, architect_firm="FIRM-A",
    )
    assert pkg_a["package_version"] == 1
    # PKG-A's issuance advanced the collection version past the captured one.
    payload = create_spec_package_payload(
        col["id"], rep["id"], captured, architect_firm="FIRM-B"
    )
    validate_error(
        api.create_spec_package(payload, specifier_headers),
        ApiErrorId.ERR_STALE_VERSION,
    )
    pkg_b = issue_package(col["id"], rep["id"], architect_firm="FIRM-B")
    assert pkg_b["status"] == "ISSUED"
    assert pkg_b["package_version"] == 1, "FIRM-B has its own sequence"
    pkg_a_after = validate_success(api.get_spec_package(pkg_a["id"], admin_headers))
    assert pkg_a_after["status"] == "ISSUED", "different firm pair — no supersede"
    assert pkg_a_after["package_version"] == 1
