"""Aid packages: the dual EFC variants, the pinned composition waterfall and
its rounding order, the verification gate on finalization, the
finalize/revise loop with OCC, and the balance invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_aid_package,
    assert_aid_package_balances,
    create_college,
    create_community_partner,
    create_counselor,
    create_income_verification,
    decide_verification,
    expect_error,
    expect_success,
    get_aid_package,
    make_college_officer_headers,
    make_counselor_headers,
    revise_aid_package_payload,
    setup_finalized_package,
    setup_matched,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def _officer(ctx):
    return make_college_officer_headers(ctx["college"]["id"])


def _file_and_decide(ctx, decision="VERIFY", **verification_overrides):
    """Counselor files the verification; an unrelated partner decides it."""
    counselor = create_counselor()
    partner = create_community_partner()
    verification = create_income_verification(
        ctx["application"]["id"],
        make_counselor_headers(counselor["id"]),
        **verification_overrides,
    )
    decided = decide_verification(verification["id"], partner["id"], decision)
    return counselor, partner, decided


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/efc_provisional_vs_verified_same_application
# ---------------------------------------------------------------------------

def test_provisional_variant_amounts_at_creation(api):
    """PRD §3.7: "The `PROVISIONAL` variant works from the application's
    self-reported figures: an allowance of $24,000 — 2,400,000 cents — plus
    $6,000 (600,000 cents) per household member is subtracted from
    `household_income_cents`, the excess is multiplied by 0.20, the product is
    rounded half-up to a whole cent, and the result is floored at zero so the
    contribution never goes negative."
    PRD §3.5: "Second, the match auto-creates its aid package: `PROVISIONAL`
    status, `guaranteed_full_need` true, `coa_cents` copied from the college's
    current figure, and all amounts computed under the provisional
    contribution variant and the composition waterfall of §3.7 — ..."

    Design: Difficulty/dual_variant_calc/efc_provisional_vs_verified_same_application
    """
    ctx = setup_matched()
    package = ctx["aid_package"]
    assert_aid_package(package)
    assert package["aid_variant"] == "PROVISIONAL"
    assert package["status"] == "PROVISIONAL"
    # allowance 2,400,000 + 4*600,000 == 4,800,000; (6,500,000 - 4,800,000) * 0.20
    assert package["efc_cents"] == 340000
    assert package["need_cents"] == 7660000       # 8,000,000 - 340,000
    assert package["work_study_cents"] == 300000  # 10% of need is above the cap
    assert package["loan_cents"] == 0             # NO_LOAN college
    assert package["grant_cents"] == 7360000      # 7,660,000 - 300,000
    assert_aid_package_balances(package)


def test_finalize_with_verified_decision_switches_to_verified_variant(api):
    """PRD §3.7: "The `VERIFIED` variant works from the latest verification
    record decided `VERIFIED`: first an asset add-back — 12% of
    `verified_assets_cents`, rounded half-up to a whole cent before any
    further arithmetic, a pinned rounding order — then an allowance of $20,000
    (2,000,000 cents) plus $5,500 (550,000 cents) per verified household
    member. The verified contribution is `verified_income_cents` plus the
    add-back minus the allowance, the difference multiplied by 0.22, rounded
    half-up to a whole cent, and again floored at zero."
    PRD §3.7: "A `VERIFIED` decision recomputes every amount under the
    `VERIFIED` contribution variant and flips `aid_variant` to `VERIFIED`; a
    `WAIVED` decision keeps the provisional amounts and leaves `aid_variant`
    at `PROVISIONAL`."

    Design: Difficulty/dual_variant_calc/efc_provisional_vs_verified_same_application
    """
    ctx = setup_matched()
    assert ctx["aid_package"]["efc_cents"] == 340000  # provisional baseline
    _file_and_decide(ctx, "VERIFY")
    resp = api.finalize_aid_package(ctx["aid_package"]["id"], _officer(ctx))
    package = expect_success(resp, 200)
    assert package["status"] == "FINALIZED"
    assert package["aid_variant"] == "VERIFIED"
    # add-back 500,000*0.12 == 60,000; allowance 2,000,000 + 4*550,000 ==
    # 4,200,000; (6,200,000 + 60,000 - 4,200,000) * 0.22 == 453,200
    assert package["efc_cents"] == 453200
    assert package["need_cents"] == 7546800   # 8,000,000 - 453,200
    assert package["work_study_cents"] == 300000
    assert package["loan_cents"] == 0
    assert package["grant_cents"] == 7246800  # 7,546,800 - 300,000
    assert package["efc_cents"] != 340000, (
        "the two variants deliberately diverge for the same family (PRD §3.7)"
    )
    assert_aid_package_balances(package)


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/aid_composition_per_component_rounding
# ---------------------------------------------------------------------------

def _setup_fractional_need_package():
    """coa 1,000,005 with efc 0: need 1,000,005, so ten percent of need is
    the fractional 100,000.5 — the pinned rounding order decides the split."""
    return setup_matched(
        college_overrides={"coa_cents": 1000005},
        app_overrides={"household_income_cents": 1000000},
    )


def test_work_study_rounded_half_up_before_cap(api):
    """PRD §3.7: "`work_study_cents` is the lesser of the $3,000 work-study
    cap and ten percent of need rounded half-up to a whole cent."
    PRD §2.6: "Where a computation produces a fractional cent, the result is
    rounded half-up to the nearest whole cent, and the rounding points are
    pinned per calculation: the asset add-back in the verified contribution
    formula is rounded before the rate multiplication, and each aid component
    is rounded individually before its cap is applied — the server never sums
    first and rounds later."

    Design: Difficulty/combinatorial_formula/aid_composition_per_component_rounding
    """
    ctx = _setup_fractional_need_package()
    package = ctx["aid_package"]
    assert package["efc_cents"] == 0, (
        "income 1,000,000 is below the provisional allowance 4,800,000"
    )
    assert package["need_cents"] == 1000005
    assert package["work_study_cents"] == 100001, (
        "round_half_up(1,000,005 * 0.10) == round_half_up(100,000.5) == 100,001"
    )


def test_grant_absorbs_the_unrounded_remainder(api):
    """PRD §3.7: "`grant_cents` is whatever remains — need minus work-study
    minus loan — and is never rounded, so it absorbs any residual cents."
    PRD §3.7: "`loan_cents` is exactly zero at a `NO_LOAN` college; ..."
    PRD §3.7: "The package always balances: work-study plus loan plus grant
    plus the expected family contribution equals `coa_cents` exactly."

    Design: Difficulty/combinatorial_formula/aid_composition_per_component_rounding
    """
    ctx = _setup_fractional_need_package()
    package = ctx["aid_package"]
    assert package["loan_cents"] == 0
    assert package["grant_cents"] == 900004, (
        "unrounded remainder 1,000,005 - 100,001 - 0 == 900,004 (a "
        "sum-then-round order would wrongly report 900,005)"
    )
    assert_aid_package_balances(package)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/finalize_blocked_until_verification_decided
# ---------------------------------------------------------------------------

def test_finalize_blocked_while_verification_pending(api):
    """PRD §3.7: "Finalization also requires a decided verification: the
    application's latest decided income verification must carry the outcome
    `VERIFIED` or `WAIVED`, failing which the request is rejected with
    `ERR_VERIFICATION_REQUIRED`."
    PRD §3.6: "The record starts `PENDING`, and the filer's identity lands in
    exactly one of two slots: ..."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_until_verification_decided
    """
    ctx = setup_matched()
    counselor = create_counselor()
    create_community_partner()
    create_income_verification(
        ctx["application"]["id"], make_counselor_headers(counselor["id"])
    )
    resp = api.finalize_aid_package(ctx["aid_package"]["id"], _officer(ctx))
    expect_error(resp, ApiErrorId.ERR_VERIFICATION_REQUIRED)
    package = get_aid_package(ctx["aid_package"]["id"])
    assert package["status"] == "PROVISIONAL", (
        "a PENDING verification leaves the finalize gate closed"
    )


def test_finalize_opens_once_verification_is_verified(api):
    """PRD §3.7: "A `CollegeOfficer` of the owning college finalizes a package
    that is `PROVISIONAL` or `REVISED`; finalizing from any other status is
    `ERR_INVALID_STATE`. Finalization also requires a decided verification:
    the application's latest decided income verification must carry the
    outcome `VERIFIED` or `WAIVED`, failing which the request is rejected with
    `ERR_VERIFICATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_until_verification_decided
    """
    ctx = setup_matched()
    _file_and_decide(ctx, "VERIFY")
    resp = api.finalize_aid_package(ctx["aid_package"]["id"], _officer(ctx))
    package = expect_success(resp, 200)
    assert package["status"] == "FINALIZED"
    assert package["aid_variant"] == "VERIFIED"
    assert package["efc_cents"] == 453200


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/aid_package_finalize_revise_finalize_cycle
# ---------------------------------------------------------------------------

def test_revise_recomputes_amounts_under_current_variant(api):
    """PRD §3.7: "A finalized package can be revised by the owning college's
    officer. The request must carry `expected_aid_package_version` matching
    the package's current `version`; a mismatch means a prior finalize or
    revise has already advanced the version since the caller last read the
    package, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
    per §2.8. An optional `coa_cents` in the payload replaces the stored cost
    of attendance; all amounts are then recomputed under the package's current
    `aid_variant`, the status moves `FINALIZED` → `REVISED`, and the `version`
    increments by 1."

    Design: Difficulty/non_linear_state_machine/aid_package_finalize_revise_finalize_cycle
    """
    ctx = setup_finalized_package()
    version = ctx["aid_package_version"]
    payload = revise_aid_package_payload(
        expected_aid_package_version=version, coa_cents=8100000
    )
    resp = api.revise_aid_package(ctx["aid_package"]["id"], payload, _officer(ctx))
    package = expect_success(resp, 200, payload)
    assert package["status"] == "REVISED"
    assert package["coa_cents"] == 8100000
    assert package["aid_variant"] == "VERIFIED", (
        "revision recomputes under the package's current variant"
    )
    assert package["efc_cents"] == 453200, "revision changed coa only"
    assert package["need_cents"] == 7646800   # 8,100,000 - 453,200
    assert package["work_study_cents"] == 300000
    assert package["grant_cents"] == 7346800  # 7,646,800 - 300,000
    assert package["version"] == version + 1
    assert_aid_package_balances(package)


def test_revised_package_finalizes_back_to_completed_loop(api):
    """PRD §3.7: "A `CollegeOfficer` of the owning college finalizes a package
    that is `PROVISIONAL` or `REVISED`; finalizing from any other status is
    `ERR_INVALID_STATE`."
    PRD §3.7: "Either way the package lands `FINALIZED` and its `version`
    increments by 1."

    Design: Difficulty/non_linear_state_machine/aid_package_finalize_revise_finalize_cycle
    """
    ctx = setup_finalized_package()
    payload = revise_aid_package_payload(
        expected_aid_package_version=ctx["aid_package_version"],
        coa_cents=8100000,
    )
    expect_success(
        api.revise_aid_package(ctx["aid_package"]["id"], payload, _officer(ctx)),
        200,
        payload,
    )
    resp = api.finalize_aid_package(ctx["aid_package"]["id"], _officer(ctx))
    package = expect_success(resp, 200)
    assert package["status"] == "FINALIZED", (
        "REVISED -> FINALIZED is a declared transition, completing "
        "FINALIZED -> REVISED -> FINALIZED"
    )
    assert package["aid_variant"] == "VERIFIED"
    assert package["efc_cents"] == 453200
    assert package["grant_cents"] == 7346800
    assert_aid_package_balances(package)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/full_need_coverage_survives_revise_pair
# ---------------------------------------------------------------------------

def test_full_need_balance_after_revise_up(api):
    """PRD §3.7: "The package always balances: work-study plus loan plus grant
    plus the expected family contribution equals `coa_cents` exactly."

    Design: Difficulty/compensating_invariant/full_need_coverage_survives_revise_pair
    """
    ctx = setup_finalized_package()
    payload = revise_aid_package_payload(
        expected_aid_package_version=ctx["aid_package_version"],
        coa_cents=8100000,
    )
    resp = api.revise_aid_package(ctx["aid_package"]["id"], payload, _officer(ctx))
    package = expect_success(resp, 200, payload)
    assert package["grant_cents"] == 7346800
    total = (
        package["grant_cents"]
        + package["loan_cents"]
        + package["work_study_cents"]
        + package["efc_cents"]
    )
    assert total == package["coa_cents"] == 8100000, (
        "7,346,800 + 0 + 300,000 + 453,200 == 8,100,000 == the new coa"
    )


def test_compensating_revise_pair_returns_grant_without_drift(api):
    """PRD §3.7: "The package always balances: work-study plus loan plus grant
    plus the expected family contribution equals `coa_cents` exactly."
    PRD §3.7: "An optional `coa_cents` in the payload replaces the stored cost
    of attendance; all amounts are then recomputed under the package's current
    `aid_variant`, the status moves `FINALIZED` → `REVISED`, and the `version`
    increments by 1."

    Design: Difficulty/compensating_invariant/full_need_coverage_survives_revise_pair
    """
    ctx = setup_finalized_package()
    package_id = ctx["aid_package"]["id"]
    officer = _officer(ctx)
    up = revise_aid_package_payload(
        expected_aid_package_version=ctx["aid_package_version"],
        coa_cents=8100000,
    )
    expect_success(api.revise_aid_package(package_id, up, officer), 200, up)
    refinalized = expect_success(
        api.finalize_aid_package(package_id, officer), 200
    )
    down = revise_aid_package_payload(
        expected_aid_package_version=refinalized["version"],
        coa_cents=8000000,
    )
    expect_success(api.revise_aid_package(package_id, down, officer), 200, down)
    resp = api.finalize_aid_package(package_id, officer)
    package = expect_success(resp, 200)
    assert package["status"] == "FINALIZED"
    assert package["coa_cents"] == 8000000
    assert package["grant_cents"] == 7246800, (
        "the compensating revise back down returns grant to exactly the "
        "pre-revision figure — zero drift"
    )
    assert package["loan_cents"] == 0
    assert package["work_study_cents"] == 300000
    assert package["efc_cents"] == 453200
    assert_aid_package_balances(package)


# ---------------------------------------------------------------------------
# Corner: exact-cent EFC rounding, WAIVED variant retention, revise OCC,
# college-officer ownership
# ---------------------------------------------------------------------------

def test_efc_exact_cent_rounding(api):
    """PRD §2.6: "Where a computation produces a fractional cent, the result
    is rounded half-up to the nearest whole cent, and the rounding points are
    pinned per calculation: the asset add-back in the verified contribution
    formula is rounded before the rate multiplication, and each aid component
    is rounded individually before its cap is applied — the server never sums
    first and rounds later. The grant component of an aid package is the one
    deliberate exception to rounding: it is the unrounded remainder that
    absorbs residual cents so that every package balances exactly, as §3.7
    specifies."
    PRD §3.7: "The package always balances: work-study plus loan plus grant
    plus the expected family contribution equals `coa_cents` exactly."

    Design: Corner/calculations/efc_exact_cent_rounding
    """
    ctx = setup_matched(
        app_overrides={"household_income_cents": 4800005}
    )
    package = ctx["aid_package"]
    assert package["efc_cents"] == 1, (
        "(4,800,005 - 4,800,000) * 0.20 == 1.0 cent, rounded half-up to 1"
    )
    assert package["need_cents"] == 7999999
    assert package["work_study_cents"] == 300000, (
        "10% of need rounds to 800,000, so the $3,000 cap binds"
    )
    assert package["grant_cents"] == 7699999
    assert_aid_package_balances(package)


def test_finalize_with_waived_verification_keeps_provisional_variant(api):
    """PRD §3.7: "The two acceptable outcomes diverge in effect. A `VERIFIED`
    decision recomputes every amount under the `VERIFIED` contribution variant
    and flips `aid_variant` to `VERIFIED`; a `WAIVED` decision keeps the
    provisional amounts and leaves `aid_variant` at `PROVISIONAL`."
    PRD §3.6: "A `WAIVE` decision skips the arithmetic entirely and lands in
    `WAIVED` under the same segregation rule."

    Design: Corner/calculations/finalize_with_waived_verification_keeps_provisional_variant
    """
    ctx = setup_matched()
    _counselor, _partner, decided = _file_and_decide(ctx, "WAIVE")
    assert decided["outcome"] == "WAIVED"
    resp = api.finalize_aid_package(ctx["aid_package"]["id"], _officer(ctx))
    package = expect_success(resp, 200)
    assert package["status"] == "FINALIZED"
    assert package["aid_variant"] == "PROVISIONAL"
    assert package["efc_cents"] == 340000
    assert package["grant_cents"] == 7360000
    assert_aid_package_balances(package)


def test_revise_stale_version_returns_stale_version(api):
    """PRD §2.8: "Revising a finalized aid package requires the request to
    carry `expected_aid_package_version`, the caller's last observed `version`
    of the package. If the package's current `version` has advanced since the
    caller last read it — because a prior finalize or revise already
    recomputed the amounts — the request is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/revise_stale_version_returns_stale_version
    """
    ctx = setup_finalized_package()
    package_id = ctx["aid_package"]["id"]
    officer = _officer(ctx)
    first_version = ctx["aid_package_version"]
    up = revise_aid_package_payload(
        expected_aid_package_version=first_version, coa_cents=8100000
    )
    expect_success(api.revise_aid_package(package_id, up, officer), 200, up)
    expect_success(api.finalize_aid_package(package_id, officer), 200)
    stale = revise_aid_package_payload(
        expected_aid_package_version=first_version, coa_cents=8200000
    )
    resp = api.revise_aid_package(package_id, stale, officer)
    expect_error(resp, ApiErrorId.ERR_STALE_VERSION, stale)
    package = get_aid_package(package_id)
    assert package["status"] == "FINALIZED"
    assert package["coa_cents"] == 8100000, (
        "the stale revise is rejected wholesale; the finalized figures stand"
    )


def test_college_officer_cannot_finalize_other_colleges_package(api):
    """PRD §2.1: "When `X-User-Role` is `CollegeOfficer`, `X-User-ID` is the
    `id` of the PartnerCollege the officer serves; ownership checks on
    college-scoped resources — aid packages, matches, outcome records,
    regular-decision authority — compare the resource's `college_id` to
    `X-User-ID`."
    PRD §2.1: "A request whose role is not among an endpoint's authorized
    roles, or that fails the entity-backed ownership rule attached to that
    role, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/college_officer_cannot_finalize_other_colleges_package
    """
    ctx = setup_matched()
    other_college = create_college(aid_policy="MINIMAL_LOAN", coa_cents=7000000)
    resp = api.finalize_aid_package(
        ctx["aid_package"]["id"],
        make_college_officer_headers(other_college["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    package = get_aid_package(ctx["aid_package"]["id"])
    assert package["status"] == "PROVISIONAL"

