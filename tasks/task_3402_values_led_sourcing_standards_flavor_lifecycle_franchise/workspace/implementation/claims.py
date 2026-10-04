"""Sourcing claim substantiation, publication, and challenge (PRD 3.5).

Substantiation supersedes the current claim state from UNCLAIMED, CHALLENGED
or RETRACTED, computes both coverage bases, and carries the OCC field
expected_flavor_version (staleness checked after citation existence, before
any state evaluation). Publication applies four gates in order: flavor
lifecycle, verified coverage threshold, certification status, scope.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from auth import authenticate, authorize
from db import STORE, public, touch
from envelope import ok
from errors import fail
from flavors import get_flavor
from validate import CLAIM_TYPES, get_body, req_enum, req_int, req_str_list

bp = Blueprint("claims", __name__)

CLAIM_COVERAGE_THRESHOLD = {
    "FAIR_TRADE_SOURCING": 95,
    "ORGANIC_INGREDIENTS": 100,
    "NON_GMO": 90,
    "CLIMATE_POSITIVE": 100,
}

SUBSTANTIABLE_FROM = ("UNCLAIMED", "CHALLENGED", "RETRACTED")


def _mean_2dp(values):
    total = Decimal("0")
    for v in values:
        total += Decimal(str(v))
    mean = total / Decimal(len(values))
    return float(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@bp.post("/flavors/<fid>/substantiate-claim")
def substantiate_claim(fid):
    _, role = authenticate()
    authorize(role, ("FlavorManager",))
    flavor = get_flavor(fid)
    body = get_body()
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    cert_ids = req_str_list(body, "certification_ids")
    expected = req_int(body, "expected_flavor_version")
    certs = []
    for cid in cert_ids:
        c = STORE["certifications"].get(cid)
        if c is None:
            fail("ERR_CERTIFICATION_NOT_FOUND",
                 "Cited certification id does not exist")
        certs.append(c)
    if expected != flavor["version"]:
        fail("ERR_STALE_VERSION",
             "expected_flavor_version does not match the flavor's current "
             "version")
    if flavor["claim_status"] not in SUBSTANTIABLE_FROM:
        fail("ERR_INVALID_STATE",
             "A claim in %s cannot be substantiated" % flavor["claim_status"])
    declared = _mean_2dp([c["declared_coverage_pct"] for c in certs])
    verified_vals = [c["verified_coverage_pct"] for c in certs
                     if c["status"] == "VERIFIED"]
    verified = _mean_2dp(verified_vals) if verified_vals else 0
    flavor["claim_type"] = claim_type
    flavor["claim_certification_ids"] = cert_ids
    flavor["claim_coverage_declared_pct"] = declared
    flavor["claim_coverage_verified_pct"] = verified
    flavor["claim_status"] = "SUBSTANTIATED"
    touch(flavor)
    return ok(public(flavor))


@bp.post("/flavors/<fid>/publish-claim")
def publish_claim(fid):
    _, role = authenticate()
    authorize(role, ("FlavorManager",))
    flavor = get_flavor(fid)
    if flavor["claim_status"] != "SUBSTANTIATED":
        fail("ERR_INVALID_STATE",
             "Only a SUBSTANTIATED claim can be published")
    # Gate 1: lifecycle state.
    if flavor["status"] not in ("LIMITED_RUN", "CORE_LINE"):
        fail("ERR_FLAVOR_NOT_PUBLISHABLE",
             "Claim publish requires flavor status LIMITED_RUN or CORE_LINE")
    # Gate 2: verified coverage meets the claim-type threshold (inclusive).
    threshold = CLAIM_COVERAGE_THRESHOLD.get(flavor["claim_type"])
    verified = flavor["claim_coverage_verified_pct"]
    if (threshold is None
            or Decimal(str(verified)) < Decimal(threshold)):
        fail("ERR_CLAIM_COVERAGE_INSUFFICIENT",
             "Verified coverage is below the claim type threshold")
    certs = [STORE["certifications"].get(cid)
             for cid in flavor["claim_certification_ids"]]
    # Gate 3: every cited certification is VERIFIED.
    if any(c is None or c["status"] != "VERIFIED" for c in certs):
        fail("ERR_CERT_NOT_VERIFIED",
             "Every cited certification must be in VERIFIED status")
    # Gate 4: base-type scope rule.
    if flavor["base_type"] == "DAIRY":
        scope_ok = any(c["ingredient_scope"] in ("DAIRY", "WHOLE_COMPANY")
                       for c in certs)
    else:
        scope_ok = any(c["ingredient_scope"] != "DAIRY" for c in certs)
    if not scope_ok:
        fail("ERR_CERT_SCOPE_MISMATCH",
             "Cited certifications do not satisfy the base-type scope rule")
    flavor["claim_status"] = "PUBLISHED"
    touch(flavor)
    return ok(public(flavor))


@bp.post("/flavors/<fid>/challenge-claim")
def challenge_claim(fid):
    _, role = authenticate()
    authorize(role, ("IndependentBoardMember",))
    flavor = get_flavor(fid)
    if flavor["claim_status"] not in ("SUBSTANTIATED", "PUBLISHED"):
        fail("ERR_INVALID_STATE",
             "Only a SUBSTANTIATED or PUBLISHED claim can be challenged")
    flavor["claim_status"] = "CHALLENGED"
    touch(flavor)
    return ok(public(flavor))
