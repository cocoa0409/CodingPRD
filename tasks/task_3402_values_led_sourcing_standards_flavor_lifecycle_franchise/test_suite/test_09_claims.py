"""Claim substantiation: coverage bases, OCC, machine guard (PRD §3.5, §2.7)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    make_supplier, create_approved_supplier, make_certification,
    make_verified_certification,
    make_flavor, make_limited_run_flavor, get_flavor_version,
    substantiate_claim,
    make_independent_board_member_headers,
)

FM = TEST_USERS["flavor_manager_headers"]
SM = TEST_USERS["sourcing_manager_headers"]



def test_claim_coverage_declared_vs_verified_diverge(api):
    """PRD §3.5: "`claim_coverage_declared_pct` is the supplier-reported basis — the mean of `declared_coverage_pct` over all cited certifications regardless of their status — rounded half-up to two decimal places."
    PRD §3.5: "`claim_coverage_verified_pct` is the verification basis — the mean of `verified_coverage_pct` over the cited certifications whose status is `VERIFIED`, and 0 when none of the cited certifications is verified — rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/claim_coverage_declared_vs_verified_diverge
    """
    supplier = create_approved_supplier(name="Green Dairy Co")
    c1 = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                     scope="DAIRY", declared=100, verified=90,
                                     certificate_number="FT-D1")
    c2 = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                     scope="COCOA", declared=90, verified=80,
                                     certificate_number="FT-C1")
    flavor = make_limited_run_flavor(name="Fudge Duet", chunk_load_pct=5,
                                     swirl_load_pct=5, pint_price_cents=199)
    resp = api.substantiate_claim(
        flavor["id"],
        {"claim_type": "FAIR_TRADE_SOURCING",
         "certification_ids": [c1["id"], c2["id"]],
         "expected_flavor_version": get_flavor_version(flavor["id"])}, FM)
    data = validate_success(resp)
    assert data["claim_status"] == "SUBSTANTIATED"
    assert data["claim_coverage_declared_pct"] == 95.0   # mean(100, 90)
    assert data["claim_coverage_verified_pct"] == 85.0   # mean(90, 80)
    assert data["claim_coverage_declared_pct"] - data["claim_coverage_verified_pct"] == 10.0


def test_claim_coverage_bases_persist_on_read(api):
    """PRD §3.5: "`claim_coverage_declared_pct` is the supplier-reported basis — the mean of `declared_coverage_pct` over all cited certifications regardless of their status — rounded half-up to two decimal places."
    PRD §3.5: "`claim_coverage_verified_pct` is the verification basis — the mean of `verified_coverage_pct` over the cited certifications whose status is `VERIFIED`, and 0 when none of the cited certifications is verified — rounded half-up to two decimal places."
    PRD §3.5: "On success the write sets `claim_type` and
    `claim_certification_ids`, computes both coverage bases, moves
    `claim_status` to `SUBSTANTIATED`, and bumps the flavor's `version`".

    Design: Difficulty/dual_variant_calc/claim_coverage_declared_vs_verified_diverge
    """
    supplier = create_approved_supplier(name="Persist Dairy")
    c1 = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                     scope="DAIRY", declared=100, verified=90,
                                     certificate_number="FT-D2")
    c2 = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                     scope="COCOA", declared=90, verified=80,
                                     certificate_number="FT-C2")
    flavor = make_limited_run_flavor(name="Fudge Echo")
    before = get_flavor_version(flavor["id"])
    written = substantiate_claim(flavor["id"], [c1["id"], c2["id"]])
    assert written["version"] == before + 1, "substantiation bumps Flavor.version"
    assert written["claim_type"] == "FAIR_TRADE_SOURCING"
    assert sorted(written["claim_certification_ids"]) == sorted([c1["id"], c2["id"]])

    read = get_success_data(api.get_flavor(flavor["id"], FM))
    assert read["claim_coverage_declared_pct"] == 95.0
    assert read["claim_coverage_verified_pct"] == 85.0


def test_claim_coverage_verified_empty_set_zero(api):
    """PRD §3.5: "`claim_coverage_declared_pct` is the supplier-reported basis — the mean of `declared_coverage_pct` over all cited certifications regardless of their status — rounded half-up to two decimal places."
    PRD §3.5: "`claim_coverage_verified_pct` is the verification basis — the mean of `verified_coverage_pct` over the cited certifications whose status is `VERIFIED`, and 0 when none of the cited certifications is verified — rounded half-up to two decimal places."

    Design: Corner/calculations/claim_coverage_verified_empty_set_zero
    """
    supplier = make_supplier(name="Pending Cert Dairy")
    cert = make_certification(supplier["id"], declared=100,
                              certificate_number="FT-PD")  # stays PENDING
    flavor = make_limited_run_flavor(name="Unverified Ube")
    data = substantiate_claim(flavor["id"], [cert["id"]])
    assert data["claim_coverage_declared_pct"] == 100.0
    assert data["claim_coverage_verified_pct"] == 0, \
        "no VERIFIED certs in the cited set -> verified basis is 0"


def test_claim_resubstantiate_from_substantiated_rejected(api):
    """PRD §3.5: "Substantiation is defined from `UNCLAIMED`, from `CHALLENGED`,
    and from `RETRACTED`, and in each case it supersedes whatever claim state
    the flavor currently holds."
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/claim_resubstantiate_from_substantiated_rejected
    """
    supplier = create_approved_supplier(name="Layer Dairy")
    cert = make_verified_certification(supplier["id"], declared=95, verified=95,
                                       certificate_number="FT-L1")
    flavor = make_limited_run_flavor(name="Layer Cake")
    substantiate_claim(flavor["id"], [cert["id"]])

    # Fresh OCC version: only the machine guard can reject this call.
    resp = api.substantiate_claim(
        flavor["id"],
        {"claim_type": "NON_GMO",
         "certification_ids": [cert["id"]],
         "expected_flavor_version": get_flavor_version(flavor["id"])}, FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_occ_claim_stale_version_rejected(api):
    """PRD §2.7: "`POST /creamery/flavors/{id}/substantiate-claim` requires `expected_flavor_version`, carrying the client's last observed `version` of the Flavor." PRD §2.7: "A mismatch with the flavor's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_claim_stale_version_rejected
    """
    supplier = create_approved_supplier(name="OCC Claim Dairy")
    cert = make_verified_certification(supplier["id"], declared=95, verified=95,
                                       certificate_number="FT-OCC")
    flavor = make_limited_run_flavor(name="OCC Fudge")
    stale_v = get_flavor_version(flavor["id"])
    substantiate_claim(flavor["id"], [cert["id"]])       # bump 1
    validate_success(api.challenge_claim(
        flavor["id"], make_independent_board_member_headers("board-1")))  # bump 2

    # Replaying the captured version must fail even though CHALLENGED ->
    # SUBSTANTIATED is a legal machine transition.
    resp = api.substantiate_claim(
        flavor["id"],
        {"claim_type": "FAIR_TRADE_SOURCING",
         "certification_ids": [cert["id"]],
         "expected_flavor_version": stale_v}, FM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
