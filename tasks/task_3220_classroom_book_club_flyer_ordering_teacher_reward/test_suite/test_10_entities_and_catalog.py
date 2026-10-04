"""Entity creation and catalog constraints: defaults, uniqueness, and the
flyer pricing pin.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    add_offering,
    create_cycle,
    create_school,
    create_title,
    enroll_school,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def test_school_defaults_low_income_false_and_posture_normal(api):
    """An unflagged school starts low_income_program false and NORMAL.

    PRD: "At registration the school may also be flagged with
    `low_income_program`, a boolean defaulting to false, which marks enrollment
    in the low-income school program."
    PRD: "A school is `NORMAL` when it has a program enrollment in `ACTIVE`
    status — or when no enrollment has ever been created for it at all — and
    `RESTRICTED` while its enrollment is suspended."
    PRD: "Every persisted resource carries an `id` — a server-minted UUID with
    no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with
    three fractional digits. Every resource in this system additionally carries
    `updated_at` (same format, refreshed on every mutation) and `version`, an
    integer that starts at its initial value on creation and increments by
    exactly one on every mutation of that resource."

    Design: Corner/entities/create_school_minimal_defaults_low_income_false
    """
    created = validate_success(
        api.create_school({"name": "Default School", "address": "100 Default Rd"}, CLUB_ADMIN),
        201,
    )
    assert created["low_income_program"] is False
    assert created["posture"] == "NORMAL", "no enrollment has ever been created"
    assert created["version"] == 1, "the version starts at its initial value on creation"

    fetched = validate_success(api.get_school(created["id"], CLUB_ADMIN))
    assert fetched["low_income_program"] is False
    assert fetched["posture"] == "NORMAL"
    assert fetched["active_fair_id"] is None


def test_teacher_email_is_unique_across_all_teachers(api):
    """A duplicate email is rejected as a malformed field.

    PRD: "a login `email` (unique across all teachers — duplicates are rejected
    with `ERR_INVALID_REQUEST`)"
    PRD: "23. Field shape (`ERR_INVALID_REQUEST`) — quantity at least one,
    dates parse, enum members valid, `email` unique across all teachers, `isbn`
    unique across all titles."

    Design: Corner/entities/create_teacher_duplicate_email_rejected
    """
    school = create_school(api, name="Email School", low_income_program=False)
    validate_success(
        api.create_teacher(
            {
                "school_id": school["id"],
                "full_name": "First Teacher",
                "email": "duplicate@example.com",
                "grade_band": "K_2",
            },
            CLUB_ADMIN,
        ),
        201,
    )
    rejected = api.create_teacher(
        {
            "school_id": school["id"],
            "full_name": "Second Teacher",
            "email": "duplicate@example.com",
            "grade_band": "G6_8",
        },
        CLUB_ADMIN,
    )
    validate_error(rejected, "ERR_INVALID_REQUEST", 400)


def test_title_isbn_is_unique_across_the_catalog(api):
    """A duplicate ISBN is rejected as a malformed field.

    PRD: "its `isbn` (an ISBN-13 key, unique across all titles)"
    PRD: "23. Field shape (`ERR_INVALID_REQUEST`) — quantity at least one,
    dates parse, enum members valid, `email` unique across all teachers, `isbn`
    unique across all titles."

    Design: Corner/entities/create_title_duplicate_isbn_rejected
    """
    validate_success(
        api.create_title(
            {
                "isbn": "9781000000001",
                "name": "First ISBN Title",
                "format": "PAPERBACK",
                "grade_band": "K_2",
                "base_price_cents": 500,
                "points_cost": 5,
                "rights_holder": "Publisher One",
                "royalty_cap_cents": 10000,
            },
            CLUB_ADMIN,
        ),
        201,
    )
    rejected = api.create_title(
        {
            "isbn": "9781000000001",
            "name": "Second ISBN Title",
            "format": "CLUB_PAPERBACK",
            "grade_band": "G3_5",
            "base_price_cents": 900,
            "points_cost": 9,
            "rights_holder": "Publisher Two",
            "royalty_cap_cents": 10000,
        },
        CLUB_ADMIN,
    )
    validate_error(rejected, "ERR_INVALID_REQUEST", 400)


def test_club_paperback_price_is_floored_seventy_percent_of_list(api):
    """The pinned flyer price floors base*70/100; PAPERBACK passes through.

    PRD: "At the moment an offering is added, its `flyer_price_cents` is pinned
    once and never recomputed, even if the title's `base_price_cents` later
    changes. For a `CLUB_PAPERBACK` title the pinned price is the title's
    `base_price_cents` multiplied by 70 and divided by 100, floored to whole
    cents — the club edition is priced at 70% of list. For `PAPERBACK` (and any
    other offered format) the pinned price is simply the title's
    `base_price_cents`."

    Design: Corner/entities/computed_flyer_price_ignores_input_and_floor_rounds
    """
    school = create_school(api, name="Pricing School", low_income_program=False)
    enroll_school(api, school["id"])
    club_title = create_title(
        api, name="Club 999", format="CLUB_PAPERBACK", base_price_cents=999, points_cost=7
    )
    plain_title = create_title(
        api, name="Plain 999", format="PAPERBACK", base_price_cents=999, points_cost=7
    )
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    club_offering = add_offering(api, cycle["id"], club_title["id"])
    plain_offering = add_offering(api, cycle["id"], plain_title["id"])

    club_read = validate_success(api.get_offering(club_offering["id"], CLUB_ADMIN))
    plain_read = validate_success(api.get_offering(plain_offering["id"], CLUB_ADMIN))
    assert club_read["flyer_price_cents"] == 699, "floor(999 * 70 / 100) = 699"
    assert plain_read["flyer_price_cents"] == 999, "PAPERBACK pins the list price"
