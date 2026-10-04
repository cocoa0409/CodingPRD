"""Registration fee: nested rounding order is pinned - gross first, assistance second."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    assert_cents,
    make_member_headers,
)
from test_helpers import fixtures


def test_reciprocity_visitor_fee_rounds_the_gross_once(api):
    """A reciprocity visitor on an odd base fee pays round-half-up of the gross
    product, applied exactly once.

    PRD §3.5: "The fee is computed in two pinned rounding steps, never rounding
    multipliers. First the gross: `HOME_MEMBER` and `ASSOCIATION_MEMBER`
    registrants pay the program's `base_fee_cents` unchanged; a
    `RECIPROCITY_VISITOR` pays the base fee multiplied by 1.25, rounded half-up
    to integer cents; a `NON_MEMBER` pays the base fee multiplied by the
    program's `non_member_multiplier`, rounded half-up. Then, when the
    registrant holds an `ACTIVE` or `ON_HOLD` membership at the session's
    branch, the `fee_charged_cents` is the gross multiplied by one minus that
    membership's `assistance_pct`, rounded half-up again; without such a
    membership the fee is simply the gross."
    PRD §3.8: "The visitor's member record carries `visiting_association_name`,
    which the fee engine reads to classify them as `RECIPROCITY_VISITOR` and to
    apply the 1.25 surcharge described in §3.5."

    Design: Difficulty/combinatorial_formula/registration_fee_nested_rounding_order_pinned
    """
    world = fixtures.setup_session_scenario(
        api, base_fee_cents=4_999, member_priority_days=0
    )
    visitor = fixtures.create_member(
        api,
        world["branch"]["id"],
        full_name="Visitor Vic",
        email="vic@x.com",
        birth_date="1988-08-08",
        visiting_association_name="OtherTown YMCA",
    )

    registration = get_success_data(
        api.create_registration(
            {
                "session_id": world["session"]["id"],
                "member_id": visitor["id"],
                "participant_name": "Visitor Vic",
                "participant_birth_date": "1988-08-08",
            },
            make_member_headers(visitor["id"]),
        )
    )
    assert registration["registrant_class"] == "RECIPROCITY_VISITOR"
    # round_half_up(4999 * 1.25) = round_half_up(6248.75) = 6249.
    assert_cents(registration["fee_charged_cents"], 6_249, "registration.fee_charged_cents")
    assert registration["status"] == "REGISTERED"


def test_nested_rounding_discount_applies_to_the_already_rounded_gross(api):
    """The assistance discount rounds a second time against the rounded gross,
    never against the unrounded product.

    PRD §3.5: "Then, when the registrant holds an `ACTIVE` or `ON_HOLD`
    membership at the session's branch, the `fee_charged_cents` is the gross
    multiplied by one minus that membership's `assistance_pct`, rounded half-up
    again; without such a membership the fee is simply the gross."
    PRD §3.5: "a `NON_MEMBER` pays the base fee multiplied by the program's
    `non_member_multiplier`, rounded half-up"

    Design: Difficulty/combinatorial_formula/registration_fee_nested_rounding_order_pinned
    """
    # Base fee 2001 with multiplier 1.5: gross = round_half_up(3001.5) = 3002.
    world = fixtures.setup_session_scenario(
        api,
        base_fee_cents=2_001,
        member_priority_days=0,
        non_member_multiplier=1.5,
    )
    walkin = fixtures.create_member(
        api, world["branch"]["id"], full_name="Walkin Will", email="w@x.com", birth_date="1992-02-02"
    )
    registration = get_success_data(
        api.create_registration(
            {
                "session_id": world["session"]["id"],
                "member_id": walkin["id"],
                "participant_name": "Walkin Will",
                "participant_birth_date": "1992-02-02",
            },
            make_member_headers(walkin["id"]),
        )
    )
    assert registration["registrant_class"] == "NON_MEMBER"
    # 2001 * 1.5 = 3001.5, rounded half-up exactly once -> 3002.
    assert_cents(registration["fee_charged_cents"], 3_002, "registration.fee_charged_cents")
