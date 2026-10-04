"""Verification attempt lifecycle: expiry sweep, wrong-code exhaustion,
cooldown and frequency-cap throttles, owner gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_listing,
    create_verification_attempt_payload,
    make_business_owner_headers,
    make_contributor,
    make_listing,
    make_region,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _wrong_code(minted: str, candidate: str) -> str:
    return "999999" if minted != "999999" else "000000"


def test_attempt_creation_rejected_on_unclaimed_listing(api):
    """PRD §3.3: "The owner of a listing in `CLAIM_PENDING` or
    `REVERIFY_REQUIRED` may request a verification attempt, choosing a
    `method` of `POSTCARD`, `PHONE`, `VIDEO`, or `RECORDS`."
    PRD §3.3: "The listing must still be verifiable — `CLAIM_PENDING` or
    `REVERIFY_REQUIRED`, else `ERR_LISTING_NOT_VERIFIABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/verification_requires_claim_pending_listing_pair
    """
    region = make_region(name="R13")
    contributor = make_contributor(region["id"], display_name="C15", email="c15@x.com")
    listing = make_listing(region["id"], name="Garage Thirteen")
    assert listing["status"] == "UNCLAIMED"

    resp = api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"],
                                            method="POSTCARD"),
        make_business_owner_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_VERIFIABLE)


def test_attempt_creation_admitted_on_claim_pending(api):
    """PRD §3.3: "The owner of a listing in `CLAIM_PENDING` or
    `REVERIFY_REQUIRED` may request a verification attempt, choosing a
    `method` of `POSTCARD`, `PHONE`, `VIDEO`, or `RECORDS`."
    PRD §3.3: "An attempt begins `ISSUED` with `attempts_used` at 0 against a
    `max_attempts` budget of 3, and `failure_reason` null."

    Design: Difficulty/cross_entity_state_dependency/verification_requires_claim_pending_listing_pair
    """
    region = make_region(name="R13b")
    owner = make_contributor(region["id"], display_name="C15b", email="c15b@x.com")
    listing = make_listing(region["id"], name="Garage Thirteen B")
    listing = claim_listing(listing, owner["id"])
    assert listing["status"] == "CLAIM_PENDING"

    resp = api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"],
                                            method="POSTCARD"),
        make_business_owner_headers(owner["id"]),
    )
    attempt = validate_success(resp, expected_status=201)
    assert attempt["status"] == "ISSUED"
    assert attempt["attempts_used"] == 0
    assert attempt["max_attempts"] == 3


def test_verification_attempt_expiry_via_sweep(api):
    """PRD §3.3: "Separately, an administrator-run sweep expires attempts:
    every `ISSUED` attempt whose `expires_at` is at or before the logical
    clock moves to `EXPIRED`, and the sweep reports an `expired_count`."
    PRD §3.3: "The server mints a six-digit `code` returned at creation for
    the postcard and phone flows, stamps `issued_at` from the logical clock,
    and sets `expires_at` exactly fourteen days after issuance."

    Design: Corner/state_machines/verification_attempt_expiry_via_sweep
    """
    region = make_region(name="RExp")
    owner = make_contributor(region["id"], display_name="OwnE", email="own2@x.com")
    listing = make_listing(region["id"], name="Expiring Biz")
    claim_listing(listing, owner["id"])
    attempt = validate_success(api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"],
                                            method="POSTCARD"),
        make_business_owner_headers(owner["id"]),
    ), expected_status=201)

    set_clock("2026-09-16T00:00:00Z")
    sweep = validate_success(api.sweep_verification_expired(ADMIN))
    assert sweep["expired_count"] == 1, (
        f"one attempt must expire, got {sweep['expired_count']}"
    )
    read = validate_success(api.get_verification_attempt(attempt["id"], ADMIN))
    assert read["status"] == "EXPIRED"


def test_wrong_code_exhaustion_fails_attempt(api):
    """PRD §3.3: "An attempt begins `ISSUED` with `attempts_used` at 0 against
    a `max_attempts` budget of 3, and `failure_reason` null."
    PRD §3.3: "A wrong code either leaves the attempt in `CODE_SUBMITTED`
    while budget remains, or — when the submission consumes the last attempt —
    fails it with `failure_reason` `WRONG_CODE`."
    PRD §2.6: "State admissibility comes next — for example, resolving a
    ticket is only admissible on a `CLAIMED` ticket, submitting a code only on
    an `ISSUED` or `CODE_SUBMITTED` attempt, an appeal only on an `OPEN` case,
    scheduling only on a `PLANNED` task, and validating only on a `PROPOSED`
    routing update — with violations returning `ERR_INVALID_STATE`."

    Design: Corner/state_machines/wrong_code_exhaustion_fails_attempt
    """
    region = make_region(name="RWrong")
    owner = make_contributor(region["id"], display_name="OwnW", email="own3@x.com")
    listing = make_listing(region["id"], name="Retry Biz")
    claim_listing(listing, owner["id"])
    attempt = validate_success(api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"], method="PHONE"),
        make_business_owner_headers(owner["id"]),
    ), expected_status=201)
    owner_headers = make_business_owner_headers(owner["id"])

    wrongs = [_wrong_code(attempt["code"], c) for c in ("000000", "111111", "222222")]
    # Guarantee the three wrong candidates differ from the minted code and
    # from each other.
    candidates = []
    pool = [c for c in ("000000", "111111", "222222", "333333") if c != attempt["code"]]
    candidates = pool[:3]
    last = None
    for code in candidates:
        last = api.submit_verification_code(attempt["id"], {"code": code},
                                            owner_headers)
    final = validate_success(last)
    assert final["status"] == "FAILED", (
        f"third wrong code consumes the budget, got {final['status']}"
    )
    assert final["failure_reason"] == "WRONG_CODE"

    resp = api.submit_verification_code(
        attempt["id"], {"code": attempt["code"]}, owner_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_verification_cooldown_boundary_72h(api):
    """PRD §3.3: "First, a cooldown: if the listing's most recent `FAILED`
    attempt was updated less than 72 hours ago, the request is rejected with
    `ERR_VERIFICATION_COOLDOWN` (HTTP 409); the boundary is strict, so exactly
    72 hours after the failure a new attempt is allowed."

    Design: Corner/calculations/verification_cooldown_boundary_72h
    """
    region = make_region(name="RCool")
    owner = make_contributor(region["id"], display_name="OwnC", email="own7@x.com")
    listing = make_listing(region["id"], name="Cool Biz")
    set_clock("2026-09-01T00:00:00Z")
    claim_listing(listing, owner["id"])
    attempt = validate_success(api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"], method="PHONE"),
        make_business_owner_headers(owner["id"]),
    ), expected_status=201)
    owner_headers = make_business_owner_headers(owner["id"])
    set_clock("2026-09-01T01:00:00Z")
    pool = [c for c in ("000000", "111111", "222222", "333333") if c != attempt["code"]]
    for code in pool[:3]:
        api.submit_verification_code(attempt["id"], {"code": code}, owner_headers)
    failed = validate_success(api.get_verification_attempt(attempt["id"], ADMIN))
    assert failed["status"] == "FAILED"

    # 71 hours after the failure: still inside the cooldown.
    set_clock("2026-09-04T00:00:00Z")
    resp = api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"], method="VIDEO"),
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_COOLDOWN)

    # Exactly 72 hours after the failure: allowed (strict < comparison).
    set_clock("2026-09-04T01:00:00Z")
    resp = api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"], method="VIDEO"),
        owner_headers,
    )
    fresh = validate_success(resp, expected_status=201)
    assert fresh["status"] == "ISSUED"


def test_sixth_attempt_within_30_days_rejected(api):
    """PRD §3.3: "Second, a frequency cap: if the listing already has five
    attempts created within the trailing thirty days (inclusive), a sixth is
    rejected with `ERR_TOO_MANY_ATTEMPTS` (HTTP 409)."
    PRD §3.3: "An owner may cancel an `ISSUED` attempt outright, moving it to
    `CANCELLED`."

    Design: Corner/errors/error_too_many_attempts
    """
    region = make_region(name="RMany")
    owner = make_contributor(region["id"], display_name="OwnM", email="own8@x.com")
    listing = make_listing(region["id"], name="Attempt Biz")
    claim_listing(listing, owner["id"])
    owner_headers = make_business_owner_headers(owner["id"])

    for _ in range(5):
        attempt = validate_success(api.create_verification_attempt(
            create_verification_attempt_payload(listing_id=listing["id"],
                                                method="POSTCARD"),
            owner_headers,
        ), expected_status=201)
        validate_success(api.cancel_verification_attempt(attempt["id"],
                                                         owner_headers))

    resp = api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"],
                                            method="POSTCARD"),
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TOO_MANY_ATTEMPTS)


def test_submit_code_by_non_owner_rejected(api):
    """PRD §3.3: "The actor must be the listing's owner — anyone else is
    refused with `ERR_NOT_LISTING_OWNER` (HTTP 403)."

    Design: Corner/validations/flag_limit_and_non_owner_submit_code
    """
    region = make_region(name="ROwner")
    owner = make_contributor(region["id"], display_name="CO", email="co@x.com")
    other = make_contributor(region["id"], display_name="R1", email="r1@x.com")
    listing = make_listing(region["id"], name="Owner Biz")
    claim_listing(listing, owner["id"])
    attempt = validate_success(api.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing["id"], method="PHONE"),
        make_business_owner_headers(owner["id"]),
    ), expected_status=201)

    resp = api.submit_verification_code(
        attempt["id"], {"code": attempt["code"]},
        make_business_owner_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_LISTING_OWNER)
