"""Government registration, member registration, and the pinned annual-dues
computation (PRD §3.2, §2.2, §2.4, §2.5).
"""

from test_helpers import (
    ApiErrorId,
    DUES_LARGE_PLAIN_CENTS,
    DUES_MEDIUM_INDEPENDENT_CENTS,
    DUES_MEDIUM_PLAIN_CENTS,
    DUES_SMALL_INDEPENDENT_CENTS,
    PLATFORM_ADMIN,
    assert_government,
    assert_member,
    create_member,
    government_payload,
    member_payload,
    set_logical_clock,
    validate_success,
)


def test_government_create_returns_defaults_and_envelope(api):
    """PRD §3.2: "The government's `lifetime_award_count` starts at zero and is
    advanced only by the award decision fork of §3.6."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.4: "All time-dependent behavior in the system reads a single logical
    clock maintained by the server — never the host's wall-clock time."

    Design: Corner/entities/government_create_returns_defaults_and_envelope
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")

    resp = api.create_government(
        government_payload(
            legal_name="City of Example",
            gov_type="CITY",
            population_band="MEDIUM",
            state_code="OH",
        ),
        headers=PLATFORM_ADMIN,
    )
    body = resp.json()
    data = validate_success(resp, 201)
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")

    assert_government(data)
    assert data["lifetime_award_count"] == 0
    # created_at is stamped from the logical clock (2026-09-15), not wall time.
    assert data["created_at"].startswith("2026-09-15T00:00:00"), (
        "created_at must record the logical-clock instant of creation, "
        "got {0!r}".format(data["created_at"])
    )


def test_member_create_dues_input_ignored(api):
    """PRD §3.2: "The server computes `annual_dues_cents` at creation; any
    client-supplied value for it is ignored."

    Design: Corner/entities/member_create_dues_input_ignored
    """
    set_logical_clock(api)

    resp = api.create_member(
        member_payload(
            full_name="Mid Plain",
            government_size_band="MEDIUM",
            independent_finance_officer=False,
            annual_dues_cents=999999,
        ),
        headers=PLATFORM_ADMIN,
    )
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["annual_dues_cents"] == DUES_MEDIUM_PLAIN_CENTS, (
        "client-supplied 999999 must be ignored; MEDIUM non-independent dues "
        "are 28500 by the pinned formula"
    )


def test_member_dues_pinned_evaluation_order(api):
    """PRD §3.2: "The dues computation follows a pinned evaluation order so
    that the discount tier cannot feed back on itself: first the band base —
    15,000 cents for `SMALL`, 30,000 cents for `MEDIUM`, 60,000 cents for
    `LARGE`; second, an affiliation fee of 5,000 cents added when
    `independent_finance_officer` is true, and zero otherwise; third, the
    pre-discount total formed as the band base plus the affiliation fee;
    fourth, the discount tier keyed on that pre-discount total — ten percent
    when the pre-discount total is at least 60,000 cents, five percent when it
    is at least 30,000 cents but below 60,000, and no discount below 30,000;
    fifth and finally, the dues are the pre-discount total reduced by the
    discount percentage, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/member_dues_pinned_evaluation_order
    """
    set_logical_clock(api)

    small_indy = create_member(
        api, full_name="Small Indy", government_size_band="SMALL",
        independent_finance_officer=True,
    )
    mid_plain = create_member(
        api, full_name="Mid Plain", government_size_band="MEDIUM",
        independent_finance_officer=False,
    )
    large_plain = create_member(
        api, full_name="Large Plain", government_size_band="LARGE",
        independent_finance_officer=False,
    )
    mid_indy = create_member(
        api, full_name="Mid Indy", government_size_band="MEDIUM",
        independent_finance_officer=True,
    )

    # 15000 + 5000 = 20000 pre-discount; below the 30000 tier, no discount.
    assert small_indy["annual_dues_cents"] == DUES_SMALL_INDEPENDENT_CENTS
    # Exactly 30000 -> the >= boundary fires the 5% tier: 30000 * 0.95.
    assert mid_plain["annual_dues_cents"] == DUES_MEDIUM_PLAIN_CENTS
    # Exactly 60000 -> the 10% tier: 60000 * 0.90.
    assert large_plain["annual_dues_cents"] == DUES_LARGE_PLAIN_CENTS
    # 35000 pre-discount -> 5% keyed on the PRE-discount total: 33250.
    assert mid_indy["annual_dues_cents"] == DUES_MEDIUM_INDEPENDENT_CENTS


def test_dues_medium_independent_hits_low_tier(api):
    """PRD §3.2: "fourth, the discount tier keyed on that pre-discount total —
    ten percent when the pre-discount total is at least 60,000 cents, five
    percent when it is at least 30,000 cents but below 60,000, and no discount
    below 30,000; fifth and finally, the dues are the pre-discount total
    reduced by the discount percentage, rounded half-up to whole cents."

    Design: Corner/calculations/dues_medium_independent_hits_low_tier
    """
    set_logical_clock(api)

    member = create_member(
        api, full_name="Mid Indy", government_size_band="MEDIUM",
        independent_finance_officer=True,
    )
    # 30000 base + 5000 fee = 35000 pre-discount; 35000 >= 30000 -> 5% off.
    assert member["annual_dues_cents"] == DUES_MEDIUM_INDEPENDENT_CENTS == 33250
