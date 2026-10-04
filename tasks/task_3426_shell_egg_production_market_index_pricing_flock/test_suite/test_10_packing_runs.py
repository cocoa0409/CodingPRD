"""Grading and packing: the largest-remainder carton assortment, bucket and
LAYING-flock guards, the quarantine gate, OCC on the complex version, and
the verify transition.
"""

from test_helpers import (
    ADMIN,
    HEALTH,
    PLANNER,
    PLANT,
    api_client,
    assert_cases_reconcile,
    assert_packing_run,
    confirm_disease_event,
    create_and_place_flock,
    create_complex,
    create_disease_event,
    create_house,
    create_packing_run_payload,
    read_complex,
    read_flock,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def _setup_grading_central(api):
    """Two LAYING flocks (20000 @ age 20, 30000 @ age 25) plus one run-ops
    week: the conventional bucket holds 24791 dozen.  Returns
    (complex, complex_version)."""
    set_clock("2026-08-25T00:00:00Z")
    complex_ = create_complex(name="Grading Central", region_code="SOUTHEAST")
    house_a = create_house(complex_["id"], house_code="HA", capacity_hens=50_000)
    house_b = create_house(complex_["id"], house_code="HB", capacity_hens=50_000)
    create_and_place_flock(
        house_a["id"], flock_code="FA",
        placement_date="2026-04-07T00:00:00Z", placed_hen_count=20_000,
    )
    create_and_place_flock(
        house_b["id"], flock_code="FB",
        placement_date="2026-03-03T00:00:00Z", placed_hen_count=30_000,
    )
    set_clock("2026-09-01T00:00:00Z")
    complex_after = run_ops(complex_["id"])
    assert complex_after["ungraded_conventional_dozen"] == 24_791, (
        "setup bucket "
        f"{complex_after['ungraded_conventional_dozen']} != 24791"
    )
    return complex_, complex_after["version"]


def test_packing_distribution_largest_remainder_rounding(api):
    """Case counts floor per size class first; the 3-case remainder goes to
    the largest fractional parts (SMALL .959, PEEWEE .735, JUMBO .656).

    PRD §3.9: "The run's `total_cases` is the whole-case floor of
    `dozen_input` divided by thirty dozen per case; raw cases per size are
    `total_cases` times the blended share, and rounding proceeds **per size
    class first, then reconciles** — each size's raw figure is floored to
    whole cases, and the remaining cases are distributed one each to the
    sizes with the largest fractional parts, ties broken in declaration order
    `JUMBO`, `EXTRA_LARGE`, `LARGE`, `MEDIUM`, `SMALL`, `PEEWEE`."

    Design: Difficulty/combinatorial_formula/packing_distribution_largest_remainder_rounding
    """
    complex_, version = _setup_grading_central(api)

    run = validate_success(
        api.create_packing_run(
            complex_["id"],
            create_packing_run_payload(
                "CONVENTIONAL", 2_970, "2026-09-01T00:00:00Z", version
            ),
            PLANT,
        ),
        201,
    )
    assert_packing_run(run)
    assert run["status"] == "PACKED"
    assert run["total_cases"] == 99  # floor(2970 / 30)
    assert run["cases_by_size"] == {
        "JUMBO": 6,
        "EXTRA_LARGE": 19,
        "LARGE": 40,
        "MEDIUM": 22,
        "SMALL": 9,
        "PEEWEE": 3,
    }
    assert_cases_reconcile(run)


def test_packing_run_consumes_the_ungraded_bucket(api):
    """The bucket decrements by dozen_input in the same request.

    PRD §3.9: "On success the bucket decrements by `dozen_input`, the run is
    born `PACKED`, and the complex's `version` increments."

    Design: Difficulty/combinatorial_formula/packing_distribution_largest_remainder_rounding
    """
    complex_, version = _setup_grading_central(api)
    validate_success(
        api.create_packing_run(
            complex_["id"],
            create_packing_run_payload(
                "CONVENTIONAL", 2_970, "2026-09-01T00:00:00Z", version
            ),
            PLANT,
        ),
        201,
    )
    complex_after = read_complex(complex_["id"])
    assert complex_after["ungraded_conventional_dozen"] == 21_821  # 24791-2970
    assert complex_after["version"] == version + 1


def test_packing_beyond_ungraded_bucket_rejected(api):
    """dozen_input greater than the program bucket is 422 and consumes
    nothing.

    PRD §3.9: "the program's ungraded bucket must hold at least
    `dozen_input` (else `ERR_INSUFFICIENT_UNGRADED_INVENTORY`)".

    Design: Corner/validations/packing_beyond_ungraded_bucket_rejected
    """
    set_clock("2026-08-25T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-07T00:00:00Z",
        placed_hen_count=20_000,
    )
    set_clock("2026-09-01T00:00:00Z")
    complex_mid = run_ops(complex_["id"])
    assert complex_mid["ungraded_conventional_dozen"] == 9_916

    response = api.create_packing_run(
        complex_["id"],
        create_packing_run_payload(
            "CONVENTIONAL", 20_000, "2026-09-01T00:00:00Z",
            complex_mid["version"],
        ),
        PLANT,
    )
    validate_error(response, ERR.ERR_INSUFFICIENT_UNGRADED_INVENTORY)
    assert read_complex(complex_["id"])["ungraded_conventional_dozen"] == 9_916
    rows, meta = validate_paginated(api.list_packing_runs(complex_["id"], PLANT))
    assert rows == [] and meta["total_count"] == 0


def test_packing_without_laying_flock_for_program_rejected(api):
    """A stocked bucket does not substitute for a LAYING flock: with the only
    flock in MOLT the size distribution is undefined.

    PRD §3.9: "at least one `LAYING` flock of that program must exist in the
    complex to define the size distribution (else
    `ERR_NO_LAYING_FLOCK_FOR_PROGRAM`)".

    Design: Corner/validations/packing_without_laying_flock_for_program_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )
    assert flock["status"] == "LAYING" and flock["age_weeks"] == 18

    set_clock("2027-04-13T00:00:00Z")  # 32 weeks: accrual, flock reaches 50
    complex_mid = run_ops(complex_["id"])
    assert complex_mid["ungraded_conventional_dozen"] > 0
    molted = validate_success(api.molt_flock(flock["id"], PLANNER))
    assert molted["status"] == "MOLT"

    version = read_complex(complex_["id"])["version"]
    response = api.create_packing_run(
        complex_["id"],
        create_packing_run_payload(
            "CONVENTIONAL", 100, "2027-04-13T00:00:00Z", version
        ),
        PLANT,
    )
    validate_error(response, ERR.ERR_NO_LAYING_FLOCK_FOR_PROGRAM)
    assert (
        read_complex(complex_["id"])["ungraded_conventional_dozen"]
        == complex_mid["ungraded_conventional_dozen"]
    )


def _setup_quarantined_gradeworks(api):
    """A complex with a stocked conventional bucket whose disease event is
    CONFIRMED (posture QUARANTINE).  Returns (complex, version)."""
    set_clock("2026-08-25T00:00:00Z")
    complex_ = create_complex(name="Gradeworks", region_code="SOUTHWEST")
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-07T00:00:00Z",
        placed_hen_count=20_000,
    )
    set_clock("2026-09-01T00:00:00Z")
    run_ops(complex_["id"])
    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    complex_after = read_complex(complex_["id"])
    assert complex_after["biosecurity_posture"] == "QUARANTINE"
    assert complex_after["ungraded_conventional_dozen"] == 9_916
    return complex_, complex_after["version"]


def test_packing_rejected_while_complex_quarantined(api):
    """A valid OCC version, stocked bucket and LAYING flock do not rescue a
    packing run under QUARANTINE.

    PRD §2.7: "`QUARANTINE` is a hard gate on two operations — flock
    placement and packing-run creation both fail with
    `ERR_COMPLEX_QUARANTINED`".

    Design: Difficulty/cross_entity_state_dependency/packing_rejected_while_complex_quarantined
    """
    complex_, version = _setup_quarantined_gradeworks(api)

    response = api.create_packing_run(
        complex_["id"],
        create_packing_run_payload(
            "CONVENTIONAL", 3_000, "2026-09-01T00:00:00Z", version
        ),
        PLANT,
    )
    validate_error(response, ERR.ERR_COMPLEX_QUARANTINED)


def test_packing_rejected_while_quarantined_consumes_nothing(api):
    """The quarantine rejection creates no run and leaves the bucket intact.

    PRD §2.7: "`QUARANTINE` is a hard gate on two operations — flock
    placement and packing-run creation both fail with
    `ERR_COMPLEX_QUARANTINED` — while order allocation treats a quarantined
    complex more gently".
    PRD §3.9: "On success the bucket decrements by `dozen_input`" — and on
    this failure there is no success, so no decrement.

    Design: Difficulty/cross_entity_state_dependency/packing_rejected_while_complex_quarantined
    """
    complex_, version = _setup_quarantined_gradeworks(api)
    validate_error(
        api.create_packing_run(
            complex_["id"],
            create_packing_run_payload(
                "CONVENTIONAL", 3_000, "2026-09-01T00:00:00Z", version
            ),
            PLANT,
        ),
        ERR.ERR_COMPLEX_QUARANTINED,
    )
    assert read_complex(complex_["id"])["ungraded_conventional_dozen"] == 9_916
    rows, meta = validate_paginated(api.list_packing_runs(complex_["id"], PLANT))
    assert rows == [] and meta["total_count"] == 0


def test_packing_run_verify_transitions_to_verified(api):
    """PACKED -> VERIFIED on the first verify; the second is a state error
    because VERIFIED is terminal.

    PRD §3.9: "a `PlantManager` verifies a `PACKED` run (from any other state
    it is `ERR_INVALID_STATE`), moving it to `VERIFIED` and bumping its
    `version`. `VERIFIED` is terminal."

    Design: Corner/endpoints/packing_run_verify_transitions_to_verified
    """
    set_clock("2026-08-25T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-07T00:00:00Z",
        placed_hen_count=20_000,
    )
    set_clock("2026-09-01T00:00:00Z")
    complex_mid = run_ops(complex_["id"])

    run = validate_success(
        api.create_packing_run(
            complex_["id"],
            create_packing_run_payload(
                "CONVENTIONAL", 300, "2026-09-01T00:00:00Z",
                complex_mid["version"],
            ),
            PLANT,
        ),
        201,
    )
    assert run["status"] == "PACKED"
    assert run["total_cases"] == 10  # floor(300 / 30)
    assert_cases_reconcile(run)

    verified = validate_success(api.verify_packing_run(run["id"], PLANT))
    assert verified["status"] == "VERIFIED"
    assert verified["version"] == run["version"] + 1

    validate_error(api.verify_packing_run(run["id"], PLANT), ERR.ERR_INVALID_STATE)


def test_stale_complex_version_returns_412(api):
    """OCC on the complex version: the first packing run consumes inventory
    and bumps the version; replaying the pre-first version is stale.

    PRD §2.10: "`POST /api/complexes/{id}/packing-runs` — the request body
    must carry `expected_complex_version` equal to the complex's current
    `version`. Creating a packing run consumes ungraded inventory and bumps
    the complex's `version`, so a second create carrying the pre-first-create
    version is stale. A mismatch is rejected with `ERR_STALE_COMPLEX_VERSION`
    (HTTP 412)."

    Design: Corner/complexity_layers/stale_complex_version_returns_412
    """
    set_clock("2026-08-25T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-07T00:00:00Z",
        placed_hen_count=20_000,
    )
    set_clock("2026-09-01T00:00:00Z")
    run_ops(complex_["id"])
    version = read_complex(complex_["id"])["version"]

    validate_success(
        api.create_packing_run(
            complex_["id"],
            create_packing_run_payload(
                "CONVENTIONAL", 100, "2026-09-01T00:00:00Z", version
            ),
            PLANT,
        ),
        201,
    )
    response = api.create_packing_run(
        complex_["id"],
        create_packing_run_payload(
            "CONVENTIONAL", 100, "2026-09-01T00:00:00Z", version
        ),
        PLANT,
    )
    validate_error(response, ERR.ERR_STALE_COMPLEX_VERSION)

    # Exactly one 100-dozen consumption from the 9916-dozen bucket.
    assert read_complex(complex_["id"])["ungraded_conventional_dozen"] == 9_816
    rows, meta = validate_paginated(api.list_packing_runs(complex_["id"], PLANT))
    assert meta["total_count"] == 1 and len(rows) == 1

