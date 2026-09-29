"""Optimistic concurrency on the determination create, and the immediacy of every
derived field.

These two properties are the cross-cutting spine of the API. The only two writes that
carry an expected version are guarded above every state and business rule, so a
version invalidated by an unrelated rename is reported as staleness rather than as a
conflict; and nothing in this API converges later — the recomputed load, the posture
ladder and `open_notice_count` are all readable on the very next call.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STALE_PRODUCT_VERSION
from test_helpers.assertions import (
    assert_exposure,
    assert_instant,
    assert_load,
    assert_margin,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    DECISION_WARNING_REQUIRED,
    DEFAULT_CLOCK,
    DETERMINATION_DRAFT,
    METHOD_MODELED,
    NOTICE_DISMISSED,
    NOTICE_RECEIVED,
    NOTICE_UNDER_EVALUATION,
    POSTURE_ENFORCEMENT_HOLD,
    POSTURE_EXPOSURE_UNKNOWN,
    POSTURE_WARNING_REQUIRED,
    RESULT_AT_OR_ABOVE,
    ROUTE_ORAL,
)
from test_helpers.fixtures import (
    add_component,
    make_assessment,
    make_benzene,
    make_final_assessment,
    make_notice,
    make_product,
    make_supplied_material,
    read_product,
    set_clock,
)
from test_helpers.test_users import (
    LABELING_SPECIALIST,
    LS_1,
    REGISTRY_ADMIN,
    REGULATORY_COUNSEL,
)


SERVED_AT = "2026-07-01T00:00:00Z"
EARLIEST_VIOLATION = "2026-05-01T00:00:00Z"
CURE_DEADLINE = "2026-08-30T00:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _determination_payload(bundle, expected_product_version):
    """The one body the OCC tests replay verbatim on both sides of the version."""
    return f.determination_payload(
        bundle["product"]["id"],
        bundle["assessment"]["id"],
        DECISION_WARNING_REQUIRED,
        expected_product_version,
    )


def _create_determination(api, bundle, expected_product_version):
    return api.create_determination(
        _determination_payload(bundle, expected_product_version), LABELING_SPECIALIST
    )


def _determination_count(api, product_id):
    _, meta = validate_paginated(
        api.list_determinations(LABELING_SPECIALIST, f.page(product_id=product_id))
    )
    return meta["total_count"]


def _version(api, product_id):
    return read_product(api, product_id)["version"]


def _rename(api, product_id, product_name):
    return api.patch_product(
        product_id, {"product_name": product_name}, REGISTRY_ADMIN
    )


def _move_notice(api, notice_id, action, **fields):
    return get_success_data(
        api.notice_transition(
            notice_id, f.action_payload(action, **fields), REGULATORY_COUNSEL
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def occ(api, clocked):
    """SKU-OCC with one ACTIVE component of RM-OCC and a FINAL assessment.

    800.0 ppm x 0.25 g x 0.5 x 1.00 x 1.0 gives 100.000 ug/day, comfortably above
    Benzene's 6.4 ug/day NSRL, so a WARNING_REQUIRED determination is legitimate.
    """
    benzene = make_benzene(api)
    supplied = make_supplied_material(api, benzene["id"], 800.0, material_code="RM-OCC")
    product = make_product(
        api, "SKU-OCC", product_name="Concurrency Widget", annual_units=100
    )
    add_component(api, product["id"], supplied["material"]["id"], 0.25, 0.5)
    assessment = make_final_assessment(
        api, product["id"], benzene["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
    )
    return {
        "chemical": benzene,
        "material": supplied["material"],
        "product": product,
        "assessment": assessment,
        "stale_version": _version(api, product["id"]),
    }


@pytest.fixture
def immediate(api, clocked):
    """SKU-CM with nothing attached yet, beside a VERIFIED RM-CM at 800.0 ppm.

    Every derived field is therefore at its initial value, and each trigger below
    moves exactly one of them.
    """
    benzene = make_benzene(api)
    supplied = make_supplied_material(api, benzene["id"], 800.0, material_code="RM-CM")
    product = make_product(
        api, "SKU-CM", product_name="Immediate Widget", annual_units=100
    )
    return {
        "chemical": benzene,
        "material": supplied["material"],
        "product": product,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1 — the expected version, on both sides of the same number
# ─────────────────────────────────────────────────────────────────────────────


class TestStaleExpectedProductVersion:
    """A rename that touches no determination still invalidates the client's version."""

    def test_a_rename_bumps_the_product_version(self, api, occ):
        """The PATCH is an ordinary configuration update, and it is what makes the
        observed version stale.

        PRD: "The update increments the product's `version` by 1."
        PRD: "Update the configuration fields that drive warning content: `product_name`, `product_category`, `occupancy_type`, `distribution_channels`, `label_area_sq_in` and `annual_units`; neither state dimension is writable and a discontinued product is immutable. | RegistryAdmin |"

        Design: Corner/cross_cutting_complexity_layers/cc_stale_expected_product_version_rejected_then_fresh_version_accepted
        """
        renamed = get_success_data(
            _rename(api, occ["product"]["id"], "Concurrency Widget Mk II")
        )

        assert renamed["product_name"] == "Concurrency Widget Mk II"
        assert renamed["version"] == occ["stale_version"] + 1

    def test_the_stale_version_is_refused_with_412(self, api, occ):
        """The determination create carrying the pre-rename version is rejected, and the
        rejection persists nothing and bumps nothing.

        PRD: "If that value does not equal the product's current `version` — because any other writer has advanced it in the meantime — the create is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)"
        PRD: "First `expected_product_version` against the product's current `version` on determination create → `ERR_STALE_PRODUCT_VERSION`;"

        Design: Corner/cross_cutting_complexity_layers/cc_stale_expected_product_version_rejected_then_fresh_version_accepted
        """
        get_success_data(_rename(api, occ["product"]["id"], "Concurrency Widget Mk II"))

        response = _create_determination(api, occ, occ["stale_version"])

        validate_error(response, ERR_STALE_PRODUCT_VERSION, 412)
        assert _determination_count(api, occ["product"]["id"]) == 0
        assert _version(api, occ["product"]["id"]) == occ["stale_version"] + 1

    def test_the_re_read_version_is_accepted(self, api, occ):
        """The identical body succeeds once the client re-reads the version the rename
        produced.

        PRD: "Creating a warning determination requires a non-optional `expected_product_version` field in the request body, carrying the `version` of the target `Product` as the client last read it."
        PRD: "The create stamps `prepared_by_user_id` from the acting `X-User-ID`, sets `status` to `DRAFT`, and increments the product's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/cc_stale_expected_product_version_rejected_then_fresh_version_accepted
        """
        get_success_data(_rename(api, occ["product"]["id"], "Concurrency Widget Mk II"))
        validate_error(
            _create_determination(api, occ, occ["stale_version"]),
            ERR_STALE_PRODUCT_VERSION,
            412,
        )

        fresh = _version(api, occ["product"]["id"])
        assert fresh == occ["stale_version"] + 1

        determination = get_success_data(_create_determination(api, occ, fresh), 201)

        assert_status(determination, DETERMINATION_DRAFT)
        assert determination["decision"] == DECISION_WARNING_REQUIRED
        assert determination["prepared_by_user_id"] == LS_1

    def test_the_accepted_create_bumps_the_parent_so_a_replay_is_stale(self, api, occ):
        """A successful determination create is itself a write on the product, so
        replaying the accepted body fails the same check.

        PRD: "The create stamps `prepared_by_user_id` from the acting `X-User-ID`, sets `status` to `DRAFT`, and increments the product's `version` by 1."
        PRD: "If that value does not equal the product's current `version` — because any other writer has advanced it in the meantime — the create is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/cc_stale_expected_product_version_rejected_then_fresh_version_accepted
        """
        get_success_data(_rename(api, occ["product"]["id"], "Concurrency Widget Mk II"))
        fresh = _version(api, occ["product"]["id"])
        get_success_data(_create_determination(api, occ, fresh), 201)

        assert _version(api, occ["product"]["id"]) == fresh + 1

        replay = _create_determination(api, occ, fresh)

        validate_error(replay, ERR_STALE_PRODUCT_VERSION, 412)


# ─────────────────────────────────────────────────────────────────────────────
# 2 — nothing converges later
# ─────────────────────────────────────────────────────────────────────────────


class TestImmediateVisibilityOfDerivedState:
    """Posture and counters are stable on their first observation after each write."""

    def test_a_fresh_product_reads_its_initial_derived_state(self, api, immediate):
        """Before any child exists the counters are zero and the posture is the initial
        one.

        PRD: "A newly created product has `lifecycle_state` set to `DEVELOPMENT`, `compliance_posture` set to `EXPOSURE_UNKNOWN`, and every derived counter — `open_notice_count`, `accrued_penalty_cents` and `total_listed_chemical_load_ug` — set to 0."
        PRD: "The initial posture of a newly created product is `EXPOSURE_UNKNOWN`."

        Design: Corner/consistency_model/consistency_immediate_visibility_of_posture_and_counters_after_every_write
        """
        product = read_product(api, immediate["product"]["id"])

        assert_load(product["total_listed_chemical_load_ug"], 0.0)
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)
        assert product["open_notice_count"] == 0
        assert product["accrued_penalty_cents"] == 0

    def test_the_load_is_visible_on_the_first_read_after_the_component_create(
        self, api, immediate
    ):
        """800.0 ppm x 0.25 g is 200.000 ug on the next read, with no assessment FINAL
        yet so the posture stays at clause 2.

        PRD: "For each such chemical-and-component pair the server evaluates the modelled effective concentration of that chemical in that component's material — the roll-up described in Section 3.5, always under the modelled variant regardless of any assessment — multiplies it by that component's `quantity_grams_per_unit`, and rounds the product half up to three decimal places."
        PRD: "The load is recomputed on every mutation that can change an active component's material, quantity or concentration: component creation"
        PRD: "2. **`EXPOSURE_UNKNOWN`** — clause 1 does not apply, and either the product has zero components in status `ACTIVE`, or some active component's material (or any material anywhere in that material's subtree) has a `disclosure_status` of `NOT_REQUESTED`, `REQUESTED`, `INCOMPLETE` or `REFUSED`, or some listed chemical reachable from the active components has no exposure assessment for this product in status `FINAL`."

        Design: Corner/consistency_model/consistency_immediate_visibility_of_posture_and_counters_after_every_write
        """
        add_component(
            api,
            immediate["product"]["id"],
            immediate["material"]["id"],
            0.25,
            0.5,
        )

        product = read_product(api, immediate["product"]["id"])

        assert_load(product["total_listed_chemical_load_ug"], 200.000)
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)

    def test_the_draft_assessment_create_already_carries_its_numbers(
        self, api, immediate
    ):
        """The calculation runs inside the create response, not on a later pass.

        PRD: "A newly created assessment has `status` `DRAFT`, `submitted_by_user_id`, `reviewed_by_user_id` and `finalized_at` all null, `rejection_count` 0 and `review_note` null; its numbers are computed immediately from the product's active components."
        PRD: "Otherwise `margin_ratio` is `daily_exposure_ug` divided by `safe_harbor_level_ug_per_day`, rounded half up to four decimal places, and `result` is `AT_OR_ABOVE_SAFE_HARBOR` when `daily_exposure_ug` is greater than or equal to the level and `BELOW_SAFE_HARBOR` when it is strictly less."

        Design: Corner/consistency_model/consistency_immediate_visibility_of_posture_and_counters_after_every_write
        """
        add_component(
            api,
            immediate["product"]["id"],
            immediate["material"]["id"],
            0.25,
            0.5,
        )

        assessment = make_assessment(
            api,
            immediate["product"]["id"],
            immediate["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )

        assert_status(assessment, ASSESSMENT_DRAFT)
        assert_exposure(assessment["daily_exposure_ug"], 100.000)
        assert_margin(assessment["margin_ratio"], 15.6250)
        assert assessment["result"] == RESULT_AT_OR_ABOVE
        assert assessment["contribution_count"] == 1

    def test_the_posture_climbs_on_the_read_straight_after_finalize(
        self, api, immediate
    ):
        """Finalization alone moves the ladder to clause 4; no intervening call is
        needed.

        PRD: "4. **`WARNING_REQUIRED`** — clauses 1 through 3 do not apply, and some exposure assessment of this product in status `FINAL` has a `result` of `AT_OR_ABOVE_SAFE_HARBOR` or `NO_SAFE_HARBOR`."
        PRD: "Both arms carry exactly the same side-effect set: `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` are recomputed one final time, `finalized_at` is stamped with the current logical clock, any other assessment of the same product and chemical whose status is `FINAL` transitions `FINAL → SUPERSEDED`, and `compliance_posture` is recomputed."

        Design: Corner/consistency_model/consistency_immediate_visibility_of_posture_and_counters_after_every_write
        """
        add_component(
            api,
            immediate["product"]["id"],
            immediate["material"]["id"],
            0.25,
            0.5,
        )
        make_final_assessment(
            api,
            immediate["product"]["id"],
            immediate["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )

        product = read_product(api, immediate["product"]["id"])

        assert_posture(product, POSTURE_WARNING_REQUIRED)
        assert_load(product["total_listed_chemical_load_ug"], 200.000)

    def test_notice_intake_holds_the_product_on_the_next_read(self, api, immediate):
        """The intake response already carries the sixty-day deadline, and the product
        read that follows it already reads ENFORCEMENT_HOLD.

        PRD: "Intake computes `cure_deadline_at` as `served_at` plus a cure window of exactly sixty days, that is sixty times eighty-six thousand four hundred seconds, and the window is **inclusive** of that instant. `cure_eligible` stays null until the evaluation action runs, `cure_attempted` starts false, `cure_completed_at` starts null, `evaluation_note` starts null and `status` starts `RECEIVED`."
        PRD: "1. **`ENFORCEMENT_HOLD`** — `open_notice_count` is at least 1, meaning at least one notice of violation on this product is in one of the statuses `RECEIVED`, `UNDER_EVALUATION`, `CURE_ELECTED`, `CURE_FAILED`, `SETTLEMENT_NEGOTIATION` or `LITIGATION`."

        Design: Corner/consistency_model/consistency_immediate_visibility_of_posture_and_counters_after_every_write
        """
        add_component(
            api,
            immediate["product"]["id"],
            immediate["material"]["id"],
            0.25,
            0.5,
        )
        make_final_assessment(
            api,
            immediate["product"]["id"],
            immediate["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )

        notice = make_notice(
            api,
            immediate["product"]["id"],
            immediate["chemical"]["id"],
            earliest_violation_date=EARLIEST_VIOLATION,
            served_at=SERVED_AT,
            alleged_units=100,
        )

        assert_status(notice, NOTICE_RECEIVED)
        assert_instant(notice["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
        product = read_product(api, immediate["product"]["id"])
        assert product["open_notice_count"] == 1
        assert_posture(product, POSTURE_ENFORCEMENT_HOLD)

    def test_dismissal_releases_the_hold_on_the_next_read(self, api, immediate):
        """The ladder walks back down the instant the last open notice closes, and no
        penalty ever accrued on this branch.

        PRD: "The third branch dismisses the notice, taking it `UNDER_EVALUATION → DISMISSED`; that action requires `evaluation_note` in the payload, decrements the product's `open_notice_count` by 1 and recomputes `compliance_posture`, which leaves `ENFORCEMENT_HOLD` when the count reaches 0."
        PRD: "4. **`WARNING_REQUIRED`** — clauses 1 through 3 do not apply, and some exposure assessment of this product in status `FINAL` has a `result` of `AT_OR_ABOVE_SAFE_HARBOR` or `NO_SAFE_HARBOR`."
        PRD: "`accrued_penalty_cents` on a product is, by construction, the sum of `adjusted_penalty_cents` over every settlement in status `EXECUTED` whose `notice_id` points at a notice of that product, and `open_notice_count` is the number of notices of that product whose status is one of `RECEIVED`, `UNDER_EVALUATION`, `CURE_ELECTED`, `CURE_FAILED`, `SETTLEMENT_NEGOTIATION` or `LITIGATION`."

        Design: Corner/consistency_model/consistency_immediate_visibility_of_posture_and_counters_after_every_write
        """
        add_component(
            api,
            immediate["product"]["id"],
            immediate["material"]["id"],
            0.25,
            0.5,
        )
        make_final_assessment(
            api,
            immediate["product"]["id"],
            immediate["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )
        notice = make_notice(
            api,
            immediate["product"]["id"],
            immediate["chemical"]["id"],
            earliest_violation_date=EARLIEST_VIOLATION,
            served_at=SERVED_AT,
            alleged_units=100,
        )

        under_evaluation = _move_notice(api, notice["id"], "EVALUATE")
        assert_status(under_evaluation, NOTICE_UNDER_EVALUATION)

        dismissed = _move_notice(
            api,
            notice["id"],
            "DISMISS",
            evaluation_note=(
                "No listed-chemical exposure above safe harbor at the alleged dates"
            ),
        )

        assert_status(dismissed, NOTICE_DISMISSED)
        product = read_product(api, immediate["product"]["id"])
        assert product["open_notice_count"] == 0
        assert_posture(product, POSTURE_WARNING_REQUIRED)
        assert product["accrued_penalty_cents"] == 0
