"""Membership, the logical clock, and exhibition sale windows: computed expiry
and lapse, member pricing with half-up rounding, presale/public window gates,
and member self-service ownership (PRD §3.2, §2.4, §2.1)."""

from test_helpers import (
    MEMBER_PRICE_WORKED,
    ApiErrorId,
    create_exhibition,
    create_member,
    create_museum,
    create_trust_fund,
    get_fund,
    get_member,
    make_member_headers,
    make_public_headers,
    open_sale,
    purchase_ticket,
    reset_clock,
    set_clock,
    setup_exhibition_on_sale,
    validate_error,
)


def test_member_expires_on_computed_and_lapse_boundary(api):
    """PRD §3.2: "The server computes `expires_on` as the join date plus the term in calendar months, and derives `member_status` on every read and every member-linked purchase: the member is `ACTIVE` when the current logical date is on or before `expires_on`, and `LAPSED` from the day after."

    Design: Corner/entities/member_expires_on_computed_and_lapse_boundary
    """
    reset_clock()
    member = create_member(
        full_name="Charter Member", email="charter@example.org", membership_term_months=12
    )
    assert member["expires_on"] == "2027-09-01", (
        f"2026-09-01 plus 12 calendar months must be 2027-09-01, got {member['expires_on']}"
    )
    assert member["member_status"] == "ACTIVE"
    # The boundary is inclusive: on expires_on itself the member is still ACTIVE.
    set_clock("2027-09-01T00:00:00Z")
    on_expiry = get_member(member["id"])
    assert on_expiry["expires_on"] == "2027-09-01"
    assert on_expiry["member_status"] == "ACTIVE"
    set_clock("2027-09-02T00:00:00Z")
    day_after = get_member(member["id"])
    assert day_after["member_status"] == "LAPSED"


def test_clock_default_is_startup_default(api):
    """PRD §2.4: "At startup — before any clock-setting call — the logical clock reads exactly 2026-09-01T00:00:00Z."
    PRD §3.2: "The server computes `expires_on` as the join date plus the term in calendar months"

    Design: Corner/entities/clock_default_is_startup_default
    """
    # Deliberately no set-clock call anywhere in this test: the server has just
    # started, so the startup default (not the wall clock) drives the join date.
    member = create_member(
        full_name="Default Clock Member", email="default@example.org", membership_term_months=1
    )
    assert member["expires_on"] == "2026-10-01", (
        f"join at the 2026-09-01 startup default plus 1 month must be 2026-10-01, "
        f"got {member['expires_on']}"
    )
    read_back = get_member(member["id"])
    assert read_back["expires_on"] == "2026-10-01"
    assert read_back["member_status"] == "ACTIVE"


def test_member_discount_rounding_half_up(api):
    """PRD §3.2: "When a `member_id` is present and the member is `ACTIVE`, the unit price is the exhibition's `fee_cents` reduced by a member discount of twenty percent, rounded half up to whole cents per single ticket: a fee of 2,500 cents prices at 2,000, a fee of 2,499 prices at 1,999, and a fee of 2,501 prices at 2,001. Otherwise the full `fee_cents` applies."
    PRD §3.2: "A successful purchase lands in `PURCHASED` status and credits the revenue fund's `receipts_cents` by the `price_paid_cents`."

    Design: Corner/calculations/member_discount_rounding_half_up
    """
    reset_clock()
    member = create_member(full_name="Discounter", email="disc@example.org", membership_term_months=12)
    built = setup_exhibition_on_sale(
        fee_cents=2499, daily_ticket_quota=10, advance_clock_to="2026-09-10T00:00:00Z"
    )
    exhibition = built["exhibition"]
    member_ticket = purchase_ticket(
        exhibition["id"], member=member, buyer_name="Member Buyer", visit_date="2026-09-20"
    )
    assert member_ticket["price_paid_cents"] == MEMBER_PRICE_WORKED[2499] == 1999, (
        "round_half_up(2499 * 0.80) = round_half_up(1999.2) = 1999"
    )
    public_ticket = purchase_ticket(
        exhibition["id"], buyer_name="Public Buyer", visit_date="2026-09-20"
    )
    assert public_ticket["price_paid_cents"] == 2499
    fund = get_fund(built["fund"]["id"])
    assert fund["receipts_cents"] == 1999 + 2499


def test_presale_member_success_and_public_denial(api):
    """PRD §3.2: "From `member_presale_opens_at` until strictly before `public_sale_opens_at`, only a purchase naming an `ACTIVE` member succeeds; a non-member purchase in that window fails with `ERR_PRESALE_MEMBER_ONLY`, and at exactly `public_sale_opens_at` a non-member purchase succeeds."

    Design: Corner/calculations/presale_member_success_and_public_denial
    """
    reset_clock()
    member = create_member(full_name="Early Member", email="early@example.org", membership_term_months=12)
    built = setup_exhibition_on_sale(fee_cents=2500, daily_ticket_quota=10)
    exhibition = built["exhibition"]
    # Inside the member presale window: presale open 2026-09-05, public 2026-09-10.
    set_clock("2026-09-07T12:00:00Z")
    member_ticket = purchase_ticket(
        exhibition["id"], member=member, buyer_name="Member Presale Buyer", visit_date="2026-09-20"
    )
    assert member_ticket["status"] == "PURCHASED"
    assert member_ticket["price_paid_cents"] == MEMBER_PRICE_WORKED[2500] == 2000
    resp = api.purchase_ticket(
        exhibition["id"],
        {"buyer_name": "Public Too Early", "visit_date": "2026-09-20"},
        headers=make_public_headers("visitor-q"),
    )
    validate_error(resp, ApiErrorId.ERR_PRESALE_MEMBER_ONLY)


def test_public_sale_boundary_exact_open(api):
    """PRD §3.2: "The sale windows are half-open at their opening instants."
    PRD §3.2: "From `member_presale_opens_at` until strictly before `public_sale_opens_at`, only a purchase naming an `ACTIVE` member succeeds; a non-member purchase in that window fails with `ERR_PRESALE_MEMBER_ONLY`, and at exactly `public_sale_opens_at` a non-member purchase succeeds."

    Design: Difficulty/boundary_precision_check/public_sale_boundary_exact_open
    """
    reset_clock()
    built = setup_exhibition_on_sale(
        fee_cents=1000,
        daily_ticket_quota=5,
        member_presale_opens_at="2026-09-10T00:00:00Z",
        public_sale_opens_at="2026-09-15T00:00:00Z",
    )
    exhibition = built["exhibition"]
    # One second before the public open instant: still the member-only window.
    set_clock("2026-09-14T23:59:59Z")
    resp = api.purchase_ticket(
        exhibition["id"],
        {"buyer_name": "Early Bird", "visit_date": "2026-09-20"},
        headers=make_public_headers("visitor-e"),
    )
    validate_error(resp, ApiErrorId.ERR_PRESALE_MEMBER_ONLY)
    # Exactly at the public open instant the non-member purchase succeeds (>=).
    set_clock("2026-09-15T00:00:00Z")
    ticket = purchase_ticket(
        exhibition["id"], buyer_user_id="visitor-f", buyer_name="On The Dot", visit_date="2026-09-20"
    )
    assert ticket["status"] == "PURCHASED"
    assert ticket["price_paid_cents"] == 1000, "full public price without a member"


def test_sale_not_open_before_presale_and_in_draft(api):
    """PRD §3.2: "Before `member_presale_opens_at`, every purchase fails with `ERR_SALE_NOT_OPEN` — as does any purchase against an exhibition that is not in `ON_SALE`."

    Design: Corner/errors/sale_not_open_before_presale_and_in_draft
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=1000000)
    museum = create_museum()
    exh_x = create_exhibition(museum["id"], fund["id"], title="Too Early Show", fee_cents=1000, daily_ticket_quota=5)
    open_sale(exh_x["id"])
    exh_y = create_exhibition(museum["id"], fund["id"], title="Draft Only Show", fee_cents=1000, daily_ticket_quota=5)
    member = create_member(full_name="Keen Member", email="keen@example.org", membership_term_months=12)
    # Before the 2026-09-05 presale open: even an ACTIVE member is turned away.
    set_clock("2026-09-04T00:00:00Z")
    resp_early = api.purchase_ticket(
        exh_x["id"],
        {"buyer_name": "Keen Member", "visit_date": "2026-09-20", "member_id": member["id"]},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp_early, ApiErrorId.ERR_SALE_NOT_OPEN)
    # Well past the public open, but exhibition Y is still DRAFT.
    set_clock("2026-09-15T00:00:00Z")
    resp_draft = api.purchase_ticket(
        exh_y["id"],
        {"buyer_name": "Draft Buyer", "visit_date": "2026-09-20"},
        headers=make_public_headers("visitor-db"),
    )
    validate_error(resp_draft, ApiErrorId.ERR_SALE_NOT_OPEN)


def test_lapsed_member_purchase_rejected(api):
    """PRD §3.2: "A purchase that names a member whose `member_status` has become `LAPSED` fails with `ERR_MEMBER_LAPSED`, whether it sought presale access or member pricing."

    Design: Corner/errors/lapsed_member_purchase_rejected
    """
    # Member joins at the startup-default clock 2026-09-01, term 1 month.
    member = create_member(full_name="Short Term Member", email="short@example.org", membership_term_months=1)
    assert member["expires_on"] == "2026-10-01"
    built = setup_exhibition_on_sale(fee_cents=2500, daily_ticket_quota=5)
    # One day past expiry the member is LAPSED; the public window is long open.
    set_clock("2026-10-02T00:00:00Z")
    resp = api.purchase_ticket(
        built["exhibition"]["id"],
        {"buyer_name": "Short Term Member", "visit_date": "2026-10-20", "member_id": member["id"]},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_LAPSED)
    assert get_fund(built["fund"]["id"])["receipts_cents"] == 0, (
        "a rejected purchase must post no receipt"
    )


def test_member_must_act_as_self_for_member_price(api):
    """PRD §3.2: "when the caller's role is `Member`, the `member_id` must equal the caller's `X-User-ID`."
    PRD §2.1: "a `Member` caller may purchase only with a `member_id` equal to their own `X-User-ID`"

    Design: Corner/rbac/member_must_act_as_self_for_member_price
    """
    reset_clock()
    built = setup_exhibition_on_sale(
        fee_cents=2500, daily_ticket_quota=5, advance_clock_to="2026-09-10T00:00:00Z"
    )
    m1 = create_member(full_name="Member One", email="m1@example.org", membership_term_months=12)
    m2 = create_member(full_name="Member Two", email="m2@example.org", membership_term_months=12)
    # Caller is member M1 but attaches member_id M2: ownership violation.
    resp = api.purchase_ticket(
        built["exhibition"]["id"],
        {"buyer_name": "Member One", "visit_date": "2026-09-20", "member_id": m2["id"]},
        headers=make_member_headers(m1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_fund(built["fund"]["id"])["receipts_cents"] == 0, (
        "a rejected purchase must post no receipt"
    )
