"""Small-government funds: FLAT_CAP vs PRO_RATA grant variants, the exact
pool-drain boundary, OCC on the fund version, allocation-state precedence,
the allocate/rescind conservation invariant, and application eligibility
gates (PRD §3.9, §2.10, §2.6).
"""

from test_helpers import (
    ApiErrorId,
    AWARDS_DIRECTOR,
    PLATFORM_ADMIN,
    allocate_application,
    allocate_payload,
    assert_fund_money_invariant,
    create_fund,
    create_small_government,
    get_fund,
    rescind_application,
    scholarship_application_payload,
    set_logical_clock,
    setup_fund_with_applications,
    make_government_contact_headers,
    create_government,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scholarship_flat_cap_vs_pro_rata(api):
    """PRD §3.9: "Under `FLAT_CAP`, the grant is the smallest of the
    application's `requested_cents`, the fund's `per_applicant_cap_cents`, and
    the fund's `remaining_cents` — a first-come waterfall that permits partial
    grants when the cap or the pool runs short. Under `PRO_RATA`, the system
    first totals `requested_cents` across all of the fund's applications still
    in `PENDING`, including the one being allocated; the grant is then the
    smallest of the per-applicant cap, the fund's `remaining_cents` scaled by
    this application's share of that total and rounded half-up to whole cents,
    and the remaining balance itself, so an oversubscribed pool yields a
    strictly smaller grant than the same fund data would under the flat cap."

    Design: Difficulty/dual_variant_calc/scholarship_flat_cap_vs_pro_rata
    """
    flat = setup_fund_with_applications(
        api, pool_total_cents=100000, per_applicant_cap_cents=200000,
        allocation_policy="FLAT_CAP", requested_amounts=(100000,),
    )
    pro_rata = setup_fund_with_applications(
        api, pool_total_cents=100000, per_applicant_cap_cents=200000,
        allocation_policy="PRO_RATA", requested_amounts=(100000, 100000),
    )
    app_flat = flat["applications"][0]
    app_pr_1, app_pr_2 = pro_rata["applications"]

    granted_flat = allocate_application(api, app_flat["id"], flat["fund"]["id"])
    granted_pr = allocate_application(
        api, app_pr_1["id"], pro_rata["fund"]["id"]
    )

    # FLAT_CAP: min(100000 requested, 200000 cap, 100000 remaining).
    assert granted_flat["granted_cents"] == 100000
    assert granted_flat["status"] == "GRANTED"
    # PRO_RATA: min(200000 cap, round(100000 * 100000/200000) = 50000, 100000).
    assert granted_pr["granted_cents"] == 50000
    assert granted_pr["status"] == "GRANTED"
    assert granted_flat["granted_cents"] - granted_pr["granted_cents"] == 50000, (
        "identical pool/cap/request diverge by exactly the pro-rata scaling"
    )

    untouched = validate_success(
        api.get_scholarship_application(app_pr_2["id"], headers=AWARDS_DIRECTOR)
    )
    assert untouched["status"] == "PENDING"
    assert untouched["granted_cents"] == 0


def test_allocate_exact_pool_drain_boundary(api):
    """PRD §3.9: "the fund's `remaining_cents` must still be positive, else
    `ERR_POOL_EXHAUSTED`."
    PRD §3.9: "`ALLOCATING` while `remaining_cents` is positive, `EXHAUSTED`
    exactly when it reaches zero, flipping in either direction as grants and
    rescissions move the balance."

    Design: Difficulty/boundary_precision_check/allocate_exact_pool_drain_boundary
    """
    bundle = setup_fund_with_applications(
        api, pool_total_cents=120000, per_applicant_cap_cents=200000,
        allocation_policy="FLAT_CAP", requested_amounts=(120000, 10000),
    )
    fund = bundle["fund"]
    app_full, app_rest = bundle["applications"]

    # A request exactly equal to the pool drains it to zero and succeeds: the
    # guard is remaining > 0, checked before the grant.
    drained = allocate_application(api, app_full["id"], fund["id"])
    assert drained["granted_cents"] == 120000
    assert drained["status"] == "GRANTED"

    exhausted = get_fund(api, fund["id"])
    assert exhausted["remaining_cents"] == 0
    assert exhausted["status"] == "EXHAUSTED"

    blocked = api.allocate_scholarship_application(
        app_rest["id"],
        allocate_payload(exhausted["version"]),
        headers=AWARDS_DIRECTOR,
    )
    validate_error(blocked, ApiErrorId.ERR_POOL_EXHAUSTED)
    stays = validate_success(
        api.get_scholarship_application(app_rest["id"], headers=AWARDS_DIRECTOR)
    )
    assert stays["status"] == "PENDING"


def test_allocate_state_error_beats_fiscal_error(api):
    """PRD §2.6: "A single request can fail several rules at once, so the
    system evaluates checks in a fixed order and reports the first failure
    encountered."  State gates (rule 6, including "the two
    optimistic-concurrency version checks") precede fiscal checks (rule 11:
    "a scholarship fund must still hold unallocated funds at grant time, else
    `ERR_POOL_EXHAUSTED`").
    PRD §3.9: "The application must be `PENDING`, else
    `ERR_APPLICATION_STATE_INVALID`"

    Design: Difficulty/priority_pair_validation_conflict/allocate_state_error_beats_fiscal_error
    """
    bundle = setup_fund_with_applications(
        api, pool_total_cents=100000, per_applicant_cap_cents=100000,
        allocation_policy="FLAT_CAP", requested_amounts=(100000,),
    )
    fund = bundle["fund"]
    application = bundle["applications"][0]
    allocate_application(api, application["id"], fund["id"])

    # The application is GRANTED and the fund is drained: both the state gate
    # and the fiscal gate fail.  The OCC version is kept current so only this
    # pair is in play, and the state error must win.
    current = get_fund(api, fund["id"])
    assert current["remaining_cents"] == 0
    resp = api.allocate_scholarship_application(
        application["id"],
        allocate_payload(current["version"]),
        headers=AWARDS_DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_INVALID)


def test_scholarship_allocate_rescind_conserves_pool_money(api):
    """PRD §3.9: "Rescission is the compensating action, also the
    `AwardsDirector`'s. Lawful only from `GRANTED`, else
    `ERR_APPLICATION_STATE_INVALID`, it moves the application to the terminal
    `RESCINDED` state, adds its `granted_cents` back into the fund's
    `remaining_cents`, and recomputes the fund's `status` — which returns to
    `ALLOCATING` as soon as the balance is positive again."
    PRD §3.9: "Allocation stores the result in `granted_cents`, moves the
    application from `PENDING` to `GRANTED`, subtracts the grant from the
    fund's `remaining_cents`, recomputes the fund's derived `status` —
    `EXHAUSTED` exactly when the remainder is zero — and increments the
    `version` of both the application and the fund."

    Design: Difficulty/compensating_invariant/scholarship_allocate_rescind_conserves_pool_money
    """
    bundle = setup_fund_with_applications(
        api, pool_total_cents=80000, per_applicant_cap_cents=80000,
        allocation_policy="FLAT_CAP", program_label="TECHNICAL_ASSISTANCE",
        requested_amounts=(60000, 80000),
    )
    fund = bundle["fund"]
    app_1, app_2 = bundle["applications"]

    granted_1 = allocate_application(api, app_1["id"], fund["id"])
    assert granted_1["granted_cents"] == 60000
    mid = get_fund(api, fund["id"])
    assert mid["remaining_cents"] == 20000
    assert mid["status"] == "ALLOCATING"
    assert_fund_money_invariant(mid, 60000)

    rescinded = rescind_application(api, app_1["id"])
    assert rescinded["status"] == "RESCINDED"
    restored = get_fund(api, fund["id"])
    assert restored["remaining_cents"] == 80000
    assert restored["status"] == "ALLOCATING", (
        "the recredit returns the fund to ALLOCATING; EXHAUSTED comes only "
        "after the follow-up grant"
    )

    # The recredit is exact: the second application can draw the full pool.
    granted_2 = allocate_application(api, app_2["id"], fund["id"])
    assert granted_2["granted_cents"] == 80000
    assert granted_2["status"] == "GRANTED"
    final = get_fund(api, fund["id"])
    assert final["remaining_cents"] == 0
    assert final["status"] == "EXHAUSTED"
    assert_fund_money_invariant(final, 80000)


def test_scholarship_allocate_stale_version_occ(api):
    """PRD §2.10: "Granting a scholarship application requires the request to
    carry `expected_fund_version`, holding the caller's last observed
    `version` of the parent scholarship fund. If the fund's current `version`
    no longer matches — because a prior allocation or rescission has advanced
    it — the request is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412),
    since the caller's view of the remaining pool is stale and the grant must
    be re-issued against the version actually observed."

    Design: Corner/cross_cutting_layers/scholarship_allocate_stale_version_occ
    """
    bundle = setup_fund_with_applications(
        api, pool_total_cents=100000, per_applicant_cap_cents=100000,
        allocation_policy="FLAT_CAP", requested_amounts=(40000, 40000),
    )
    fund = bundle["fund"]
    app_1, app_2 = bundle["applications"]
    stale_version = fund["version"]

    first = allocate_application(
        api, app_1["id"], fund["id"], expected_fund_version=stale_version
    )
    assert first["granted_cents"] == 40000

    stale = api.allocate_scholarship_application(
        app_2["id"], allocate_payload(stale_version), headers=AWARDS_DIRECTOR
    )
    validate_error(stale, ApiErrorId.ERR_STALE_FUND_VERSION)

    current_version = get_fund(api, fund["id"])["version"]
    retried = allocate_application(
        api, app_2["id"], fund["id"], expected_fund_version=current_version
    )
    assert retried["granted_cents"] == 40000
    assert retried["status"] == "GRANTED"

    after = get_fund(api, fund["id"])
    assert after["remaining_cents"] == 20000, (
        "both grants debited exactly once"
    )


def test_non_small_government_scholarship_rejected(api):
    """PRD §3.9: "The government's `population_band` must be `SMALL`, else
    `ERR_GOVERNMENT_NOT_SMALL`."
    PRD §3.2: "a `population_band` of `SMALL`, `MEDIUM`, or `LARGE` — where
    `SMALL` means a population under 10,000 and is what drives scholarship
    eligibility"

    Design: Corner/validations/non_small_government_scholarship_rejected
    """
    set_logical_clock(api)
    fund = create_fund(api)
    government = create_government(api, population_band="MEDIUM")

    resp = api.create_scholarship_application(
        scholarship_application_payload(
            fund["id"], government["id"],
            purpose="CONFERENCE_SCHOLARSHIP", requested_cents=10000,
        ),
        headers=make_government_contact_headers(government["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GOVERNMENT_NOT_SMALL)

    rows, meta = validate_paginated(
        api.list_scholarship_applications(
            headers=PLATFORM_ADMIN, params={"government_id": government["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []


def test_purpose_program_mismatch_rejected(api):
    """PRD §3.9: "And the purpose must match the fund's program: a `purpose`
    of `CONFERENCE_SCHOLARSHIP` belongs to a fund labeled `SCHOLARSHIP`, and a
    `purpose` of `TECHNICAL_ASSISTANCE` belongs to a fund labeled
    `TECHNICAL_ASSISTANCE`, with any cross pairing rejected as
    `ERR_PURPOSE_PROGRAM_MISMATCH`."

    Design: Corner/validations/purpose_program_mismatch_rejected
    """
    set_logical_clock(api)
    fund = create_fund(api)  # SCHOLARSHIP fund
    government = create_small_government(api)

    resp = api.create_scholarship_application(
        scholarship_application_payload(
            fund["id"], government["id"],
            purpose="TECHNICAL_ASSISTANCE", requested_cents=10000,
        ),
        headers=make_government_contact_headers(government["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PURPOSE_PROGRAM_MISMATCH)
