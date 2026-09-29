"""Cyclic state machines: their first move, their loops and their locked doors.

The registry's terminal withdrawal, the product's terminal discontinuation, the
two cycles on a material (disclosure and laboratory testing), the note that a
return for revision requires, the warranty that a live notice pins open, and the
one path that reaches the posture ladder's fallback.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PRODUCT_ON_ENFORCEMENT_HOLD,
    ERR_UNKNOWN_ACTION,
    ERR_WARRANTY_IN_USE,
)
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_concentration,
    assert_fields_null,
    assert_instant,
    assert_lifecycle,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    BASIS_LAB_TESTED,
    BASIS_SUPPLIER_DECLARED,
    CHEMICAL_STATUS_LISTED,
    CHEMICAL_STATUS_PROPOSED,
    CHEMICAL_STATUS_WITHDRAWN,
    COMPLETENESS_INCOMPLETE,
    DEFAULT_CLOCK,
    DETERMINATION_DRAFT,
    DETERMINATION_PENDING_APPROVAL,
    DISCLOSURE_INCOMPLETE,
    DISCLOSURE_NOT_REQUESTED,
    DISCLOSURE_REFUSED,
    DISCLOSURE_REQUESTED,
    LIFECYCLE_DEVELOPMENT,
    LIFECYCLE_DISCONTINUED,
    LIFECYCLE_MARKETED,
    LINK_STATUS_DISPUTED,
    LINK_STATUS_TEST_REPORTED,
    LINK_STATUS_TEST_REQUESTED,
    LISTING_EFFECTIVE_DATE,
    LISTING_WARNING_REQUIRED_FROM,
    METHOD_MODELED,
    NOTICE_DISMISSED,
    NOTICE_UNDER_EVALUATION,
    POSTURE_CLEAR,
    POSTURE_EXPOSURE_UNKNOWN,
    RESULT_BELOW,
    ROUTE_DERMAL,
    WARRANTY_STATUS_ACTIVE,
    WARRANTY_STATUS_REVOKED,
)
from test_helpers.fixtures import (
    add_component,
    dismiss_notice,
    evaluate_notice,
    link_chemical,
    make_bpa,
    make_determination,
    make_final_assessment,
    make_material,
    make_notice,
    make_product,
    make_product_with_component,
    make_supplier,
    make_warranted_supplier,
    peer_review_assessment,
    read_product,
    set_clock,
    submit_assessment,
    make_assessment,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    LS_1,
    REGISTRY_ADMIN,
    REGULATORY_COUNSEL,
    TOXICOLOGY_REVIEWER,
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    """Every machine in this file is driven from the same logical clock."""
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def proposed_chemical(api, clocked):
    """A registered but unlisted Bisphenol A, sitting in PROPOSED."""
    return make_bpa(api, list_it=False)


@pytest.fixture
def plain_material(api, clocked):
    """One supplier and one material whose disclosure has never been asked for."""
    supplier = make_supplier(api, "Northgate Polymers")
    return make_material(api, "RM-100", supplier["id"])


@pytest.fixture
def declared_link(api, clocked):
    """A LISTED chemical declared at 40.0 ppm on one material, still in DECLARED."""
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    link = link_chemical(api, material["id"], chemical["id"], 40.0)
    return {"chemical": chemical, "material": material, "link": link}


@pytest.fixture
def warranty_pinned_by_notice(api, clocked):
    """An ACTIVE open-ended warranty whose window covers a notice under evaluation."""
    chemical = make_bpa(api)
    supplier = make_warranted_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    product = make_product(
        api, "SKU-WW", product_name="Warranty Widget", annual_units=1000
    )
    add_component(api, product["id"], material["id"])
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-07-01T00:00:00Z",
        noticing_party_name="Coastal Watch Alliance",
    )
    notice = evaluate_notice(api, notice["id"])
    return {
        "chemical": chemical,
        "supplier": supplier,
        "product": product,
        "notice": notice,
    }


@pytest.fixture
def determination_awaiting_approval(api, clocked):
    """A determination prepared by ls_1 and parked in PENDING_APPROVAL.

    40.0 ppm x 0.25 g x 0.5 contact x 0.10 dermal x 1.0 uses = 0.500 ug/day,
    exactly the MADL, so the assessment finalizes AT_OR_ABOVE_SAFE_HARBOR and a
    warning determination is the correct next step.
    """
    chemical = make_bpa(api)
    base = make_product_with_component(
        api,
        chemical["id"],
        sku="SKU-RFR",
        product_overrides={"product_name": "Revision Cycle", "annual_units": 1000},
    )
    assessment = make_final_assessment(
        api, base["product"]["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    determination = make_determination(
        api, base["product"]["id"], assessment["id"]
    )
    determination = get_success_data(
        api.determination_transition(
            determination["id"],
            f.action_payload("SUBMIT_FOR_APPROVAL"),
            LABELING_SPECIALIST,
        )
    )
    base["chemical"] = chemical
    base["assessment"] = assessment
    base["determination"] = determination
    return base


@pytest.fixture
def clear_candidate(api, clocked):
    """A product one FINALIZE away from CLEAR: 0.250 ug/day against a 0.5 MADL.

    40.0 ppm x 0.25 g x 0.5 contact x 0.10 dermal x 0.5 uses = 0.250 ug/day,
    margin_ratio 0.5000, BELOW_SAFE_HARBOR. The assessment is left in
    PEER_REVIEWED so that clause 2 of the ladder still holds the product in
    EXPOSURE_UNKNOWN.
    """
    chemical = make_bpa(api)
    base = make_product_with_component(
        api,
        chemical["id"],
        sku="SKU-CLR",
        product_overrides={"product_name": "Clear Product", "annual_units": 1000},
    )
    assessment = make_assessment(
        api,
        base["product"]["id"],
        chemical["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        0.5,
    )
    submit_assessment(api, assessment["id"])
    base["assessment"] = peer_review_assessment(api, assessment["id"])
    base["chemical"] = chemical
    return base


def _chemical_action(api, chemical_id, payload):
    return api.listed_chemical_transition(chemical_id, payload, REGISTRY_ADMIN)


def _read_chemical(api, chemical_id):
    return get_success_data(api.get_listed_chemical(chemical_id, REGISTRY_ADMIN))


def _read_material(api, material_id):
    return get_success_data(api.get_material(material_id, COMPLIANCE_ANALYST))


def _read_link(api, link_id):
    return get_success_data(api.get_material_chemical(link_id, COMPLIANCE_ANALYST))


def _read_supplier(api, supplier_id):
    return get_success_data(api.get_supplier(supplier_id, COMPLIANCE_ANALYST))


def _read_determination(api, determination_id):
    return get_success_data(
        api.get_determination(determination_id, LABELING_SPECIALIST)
    )


def _read_notice(api, notice_id):
    return get_success_data(api.get_notice(notice_id, REGULATORY_COUNSEL))


def _disclose(api, material_id, payload):
    return api.material_disclosure(material_id, payload, COMPLIANCE_ANALYST)


def _link_action(api, link_id, payload, headers=COMPLIANCE_ANALYST):
    return api.material_chemical_transition(link_id, payload, headers)


# ─────────────────────────────────────────────────────────────────────────────
# The registry cycle and its one terminal state
# ─────────────────────────────────────────────────────────────────────────────


class TestListingStampsTheGraceDate:
    def test_listing_computes_the_grace_date_from_the_effective_date(
        self, api, proposed_chemical
    ):
        """2026-01-01 plus three hundred and sixty-five days is exactly 2027-01-01.

        PRD: "Listing a chemical takes it `PROPOSED → LISTED` and requires `listing_effective_date` in the payload; the server stores that date and computes `warning_required_from` as the effective date plus a one-year grace period of exactly three hundred and sixty-five days."

        Design: Corner/state_machines/sm_list_chemical_stamps_warning_required_from_grace_date
        """
        listed = get_success_data(
            _chemical_action(api, proposed_chemical["id"], f.list_action(LISTING_EFFECTIVE_DATE))
        )
        assert_status(listed, CHEMICAL_STATUS_LISTED)
        assert_instant(
            listed["listing_effective_date"],
            LISTING_EFFECTIVE_DATE,
            "listing_effective_date",
        )
        assert_instant(
            listed["warning_required_from"],
            LISTING_WARNING_REQUIRED_FROM,
            "warning_required_from",
        )
        assert listed["version"] == 2
        assert listed["revision_count"] == 0

    def test_the_grace_date_is_neither_the_listing_date_nor_the_clock(
        self, api, proposed_chemical, clocked
    ):
        """The read surface exposes a derived date that is not either input instant.

        PRD: "The single-chemical read returns `harm_class`, `warning_required_from` and `revision_count` alongside the input fields; the registry list accepts optional `status` and `harm_class` filters."

        Design: Corner/state_machines/sm_list_chemical_stamps_warning_required_from_grace_date
        """
        get_success_data(
            _chemical_action(api, proposed_chemical["id"], f.list_action(LISTING_EFFECTIVE_DATE))
        )
        stored = _read_chemical(api, proposed_chemical["id"])
        assert_instant(
            stored["warning_required_from"],
            LISTING_WARNING_REQUIRED_FROM,
            "warning_required_from",
        )
        assert stored["warning_required_from"] != stored["listing_effective_date"]
        assert stored["warning_required_from"] != clocked


class TestListingWithoutAnEffectiveDate:
    def test_the_action_is_refused_and_the_chemical_stays_proposed(
        self, api, proposed_chemical
    ):
        """listing_effective_date is required by LIST alone, so its absence is a 400.

        PRD: "Listing a chemical takes it `PROPOSED → LISTED` and requires `listing_effective_date` in the payload; the server stores that date and computes `warning_required_from` as the effective date plus a one-year grace period of exactly three hundred and sixty-five days."

        Design: Corner/state_machines/sm_list_chemical_without_effective_date_rejected
        """
        validate_error(
            _chemical_action(api, proposed_chemical["id"], f.action_payload("LIST")),
            ERR_INVALID_REQUEST,
            400,
        )
        stored = _read_chemical(api, proposed_chemical["id"])
        assert_status(stored, CHEMICAL_STATUS_PROPOSED)
        assert stored["version"] == 1

    def test_no_half_listed_row_is_left_behind(self, api, proposed_chemical):
        """A refused listing may not leave a LISTED row whose grace date is null.

        PRD: "`warning_required_from` stays null for as long as `listing_effective_date` is null."

        Design: Corner/state_machines/sm_list_chemical_without_effective_date_rejected
        """
        validate_error(
            _chemical_action(api, proposed_chemical["id"], f.action_payload("LIST")),
            ERR_INVALID_REQUEST,
            400,
        )
        stored = _read_chemical(api, proposed_chemical["id"])
        assert_fields_null(stored, ["listing_effective_date", "warning_required_from"])


class TestWithdrawalIsTerminal:
    def test_neither_listing_nor_delisting_survives_a_withdrawal(
        self, api, proposed_chemical
    ):
        """LIST was legal one call earlier; from WITHDRAWN both actions are illegal.

        PRD: "Withdrawing a proposal takes it `PROPOSED → WITHDRAWN`, which is terminal — a withdrawn proposal can never be listed, and every subsequent action against it fails as an illegal transition."

        Design: Corner/state_machines/sm_withdrawn_chemical_rejects_further_transitions
        """
        withdrawn = get_success_data(
            _chemical_action(api, proposed_chemical["id"], f.action_payload("WITHDRAW"))
        )
        assert_status(withdrawn, CHEMICAL_STATUS_WITHDRAWN)
        validate_error(
            _chemical_action(api, proposed_chemical["id"], f.list_action(LISTING_EFFECTIVE_DATE)),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            _chemical_action(api, proposed_chemical["id"], f.action_payload("DELIST")),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )

    def test_the_two_refused_calls_do_not_mutate_the_row(self, api, proposed_chemical):
        """Only the withdrawal bumped the version, so it still reads 2 afterwards.

        PRD: "**Layer 4 — state legality.** In order: (1) the requested action is not a declared transition out of the entity's current state — including every action attempted from a terminal state — → `ERR_INVALID_STATE_TRANSITION`; (2) a child write is attempted under a parent in a blocking state → `ERR_PARENT_STATE_FORBIDS_WRITE`; (3) an update targets a row that has become immutable → `ERR_ENTITY_IMMUTABLE`; (4) a request body supplies a field whose value the server computes or stamps → `ERR_FIELD_NOT_WRITABLE`; (5) a bill-of-materials write is attempted while the product is under enforcement hold → `ERR_ENFORCEMENT_HOLD_FREEZE`."

        Design: Corner/state_machines/sm_withdrawn_chemical_rejects_further_transitions
        """
        get_success_data(
            _chemical_action(api, proposed_chemical["id"], f.action_payload("WITHDRAW"))
        )
        validate_error(
            _chemical_action(api, proposed_chemical["id"], f.list_action(LISTING_EFFECTIVE_DATE)),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            _chemical_action(api, proposed_chemical["id"], f.action_payload("DELIST")),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )
        stored = _read_chemical(api, proposed_chemical["id"])
        assert_status(stored, CHEMICAL_STATUS_WITHDRAWN)
        assert stored["version"] == 2
        assert_fields_null(stored, ["listing_effective_date", "warning_required_from"])


# ─────────────────────────────────────────────────────────────────────────────
# The product's commercial line
# ─────────────────────────────────────────────────────────────────────────────


class TestDiscontinueIsNotIdempotent:
    def test_replaying_the_action_is_a_conflict_rather_than_a_no_op(self, api, clocked):
        """DISCONTINUED is terminal, so the second DISCONTINUE is a 409 and no version moves.

        PRD: "Marketing a product takes `lifecycle_state` from `DEVELOPMENT` to `MARKETED`; discontinuing it takes `lifecycle_state` from either `DEVELOPMENT` or `MARKETED` to `DISCONTINUED`, which is terminal."

        Design: Corner/state_machines/sm_second_discontinue_action_rejected_as_invalid_state
        """
        product = make_product(
            api, "SKU-IDEM", product_name="Once Only", annual_units=1000
        )
        first = get_success_data(
            api.product_transition(
                product["id"], f.action_payload("DISCONTINUE"), REGISTRY_ADMIN
            )
        )
        assert_lifecycle(first, LIFECYCLE_DISCONTINUED)
        assert first["version"] == 2

        validate_error(
            api.product_transition(
                product["id"], f.action_payload("DISCONTINUE"), REGISTRY_ADMIN
            ),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )
        stored = read_product(api, product["id"])
        assert_lifecycle(stored, LIFECYCLE_DISCONTINUED)
        assert stored["version"] == 2


class TestUnknownActionOutranksIllegalAction:
    def test_an_action_that_names_no_transition_is_a_four_hundred(self, api, clocked):
        """RELAUNCH is not a declared trigger at all, so the envelope layer decides it.

        PRD: "**Layer 1 — envelope, authorisation and shape.** In order: (1) the `X-User-Role` header is absent or is not one of the six declared roles → `ERR_UNAUTHORIZED`; (2) the caller's role is not among the roles the target endpoint authorises → `ERR_UNAUTHORIZED`; (3) on every create and every update, a required input field is absent, explicitly null, of the wrong JSON type, or carries an enum member that is not declared → `ERR_INVALID_REQUEST`; (4) on every list read, `limit` is below 1 or above 200, or `offset` is negative → `ERR_INVALID_PAGINATION`; (5) a numeric input is negative, or zero where the domain requires strictly positive → `ERR_VALUE_OUT_OF_RANGE`; (6) `contact_factor` falls outside the range from 0.0 through 1.0 inclusive, or `parent_mass_fraction` falls outside the range greater than 0.0 through 1.0 inclusive → `ERR_VALUE_OUT_OF_RANGE`; (7) `cas_number` does not match the CAS registry shape of two to seven digits, a hyphen, two digits, a hyphen and one final digit → `ERR_INVALID_CAS_NUMBER`; (8) the safe-harbor basis and level disagree → `ERR_SAFE_HARBOR_BASIS_MISMATCH`; (9) the safe-harbor basis contradicts the toxicological endpoint → `ERR_SAFE_HARBOR_BASIS_MISMATCH`; (10) an interval's end is not strictly after its start → `ERR_INVALID_INTERVAL`; (11) the `action` supplied to a transition surface or to the disclosure surface is not a declared trigger of that entity's state machine at all → `ERR_UNKNOWN_ACTION`; (12) `distribution_channels` is an empty array or contains a value outside the declared set → `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/sm_unknown_action_on_product_transitions_returns_unknown_action
        """
        product = make_product(
            api, "SKU-UNK", product_name="Unknown Action", annual_units=1000
        )
        validate_error(
            api.product_transition(
                product["id"], f.action_payload("RELAUNCH"), REGISTRY_ADMIN
            ),
            ERR_UNKNOWN_ACTION,
            400,
        )
        stored = read_product(api, product["id"])
        assert_lifecycle(stored, LIFECYCLE_DEVELOPMENT)
        assert stored["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# The disclosure cycle on a material
# ─────────────────────────────────────────────────────────────────────────────


class TestDisclosureStartsUnasked:
    def test_a_fresh_material_has_never_been_asked(self, api, plain_material):
        """NOT_REQUESTED with both instants null is the state a material is born in.

        PRD: "A newly created material starts with `disclosure_status` set to `NOT_REQUESTED`, `data_request_sent_at` null and `data_received_at` null."

        Design: Corner/state_machines/sm_material_disclosure_starts_not_requested
        """
        assert plain_material["disclosure_status"] == DISCLOSURE_NOT_REQUESTED
        assert_fields_null(plain_material, ["data_request_sent_at", "data_received_at"])
        assert plain_material["version"] == 1

    def test_request_is_the_only_legal_first_move(self, api, plain_material, clocked):
        """VERIFY has no edge out of NOT_REQUESTED; REQUEST does, and it stamps the clock.

        PRD: "A `ComplianceAnalyst` opens the process by requesting data, taking the material `NOT_REQUESTED → REQUESTED` and stamping `data_request_sent_at` with the current logical clock."

        Design: Corner/state_machines/sm_material_disclosure_starts_not_requested
        """
        validate_error(
            _disclose(api, plain_material["id"], f.action_payload("VERIFY")),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )
        requested = get_success_data(
            _disclose(api, plain_material["id"], f.action_payload("REQUEST"))
        )
        assert requested["disclosure_status"] == DISCLOSURE_REQUESTED
        assert_instant(
            requested["data_request_sent_at"], clocked, "data_request_sent_at"
        )
        assert requested["data_received_at"] is None


class TestDisclosureRefusalAndRerequest:
    def test_the_machine_loops_back_through_requested_twice(self, api, plain_material):
        """REQUESTED, REFUSED, REQUESTED, INCOMPLETE, REQUESTED are all accepted in turn.

        PRD: "The same request action also serves as the re-request after a bad outcome: it takes a material `REFUSED → REQUESTED` and `INCOMPLETE → REQUESTED`, re-stamping `data_request_sent_at` each time."

        Design: Corner/state_machines/sm_disclosure_refusal_and_rerequest_cycle
        """
        material_id = plain_material["id"]
        walk = [
            (f.action_payload("REQUEST"), DISCLOSURE_REQUESTED),
            (f.action_payload("MARK_REFUSED"), DISCLOSURE_REFUSED),
            (f.action_payload("REQUEST"), DISCLOSURE_REQUESTED),
            (f.record_response_action(COMPLETENESS_INCOMPLETE), DISCLOSURE_INCOMPLETE),
            (f.action_payload("REQUEST"), DISCLOSURE_REQUESTED),
        ]
        for payload, expected in walk:
            row = get_success_data(_disclose(api, material_id, payload))
            assert row["disclosure_status"] == expected, (
                f"{payload['action']} should have produced {expected}, "
                f"got {row['disclosure_status']!r}"
            )

    def test_only_recording_a_response_stamps_the_received_instant(
        self, api, plain_material, clocked
    ):
        """data_received_at stays null across the refusal loop and is set by the response.

        PRD: "Both stamp `data_received_at` with the current logical clock, and both may be filed either by the supplier itself acting as a `SupplierPortalUser` — in which case the caller's `X-User-ID` must equal the material's `supplier_id` — or transcribed by a `ComplianceAnalyst`."

        Design: Corner/state_machines/sm_disclosure_refusal_and_rerequest_cycle
        """
        material_id = plain_material["id"]
        get_success_data(_disclose(api, material_id, f.action_payload("REQUEST")))
        refused = get_success_data(
            _disclose(api, material_id, f.action_payload("MARK_REFUSED"))
        )
        assert refused["data_received_at"] is None
        rerequested = get_success_data(
            _disclose(api, material_id, f.action_payload("REQUEST"))
        )
        assert rerequested["data_received_at"] is None

        incomplete = get_success_data(
            _disclose(api, material_id, f.record_response_action(COMPLETENESS_INCOMPLETE))
        )
        assert incomplete["disclosure_status"] == DISCLOSURE_INCOMPLETE
        assert_instant(incomplete["data_received_at"], clocked, "data_received_at")

    def test_every_disclosure_action_costs_one_version(self, api, plain_material):
        """Five accepted actions on a version 1 row leave it at version 6.

        PRD: "Every one of these actions increments the material's `version` by 1 and recomputes `compliance_posture` for every product that holds this material, whether directly as a component or indirectly through the material tree."

        Design: Corner/state_machines/sm_disclosure_refusal_and_rerequest_cycle
        """
        material_id = plain_material["id"]
        for payload in (
            f.action_payload("REQUEST"),
            f.action_payload("MARK_REFUSED"),
            f.action_payload("REQUEST"),
            f.record_response_action(COMPLETENESS_INCOMPLETE),
            f.action_payload("REQUEST"),
        ):
            get_success_data(_disclose(api, material_id, payload))
        assert _read_material(api, material_id)["version"] == 6


# ─────────────────────────────────────────────────────────────────────────────
# The laboratory cycle on a material/chemical link
# ─────────────────────────────────────────────────────────────────────────────


class TestDisputeReturnsForRetesting:
    def test_the_laboratory_path_closes_back_on_test_requested(self, api, declared_link):
        """TEST_REQUESTED, TEST_REPORTED, DISPUTED and TEST_REQUESTED again, in order.

        PRD: "The `status` of a material/chemical link tracks that upgrade through five values — `DECLARED`, `TEST_REQUESTED`, `TEST_REPORTED`, `DISPUTED` and `VERIFIED` — and the path through them is a cycle, because a disputed result must be able to go back for re-testing."

        Design: Corner/state_machines/sm_material_chemical_dispute_returns_to_test_requested
        """
        link_id = declared_link["link"]["id"]
        walk = [
            (f.action_payload("REQUEST_TEST"), COMPLIANCE_ANALYST, LINK_STATUS_TEST_REQUESTED),
            (
                f.report_result_action("Harbor Analytical", 36.0, 1.0),
                COMPLIANCE_ANALYST,
                LINK_STATUS_TEST_REPORTED,
            ),
            (
                f.action_payload("DISPUTE", dispute_note="Sample chain of custody incomplete"),
                TOXICOLOGY_REVIEWER,
                LINK_STATUS_DISPUTED,
            ),
            (f.action_payload("REQUEST_TEST"), COMPLIANCE_ANALYST, LINK_STATUS_TEST_REQUESTED),
        ]
        for payload, headers, expected in walk:
            row = get_success_data(_link_action(api, link_id, payload, headers))
            assert_status(row, expected)

    def test_reporting_a_result_flips_the_measurement_basis(self, api, declared_link):
        """The reported figure, its limit of quantitation and the clock all land together.

        PRD: "Reporting stores all three, stamps `lab_reported_at` with the current logical clock, and flips `measurement_basis` from `SUPPLIER_DECLARED` to `LAB_TESTED`, which is what makes this link admissible under the laboratory exposure method."

        Design: Corner/state_machines/sm_material_chemical_dispute_returns_to_test_requested
        """
        link_id = declared_link["link"]["id"]
        assert declared_link["link"]["measurement_basis"] == BASIS_SUPPLIER_DECLARED
        get_success_data(
            _link_action(api, link_id, f.action_payload("REQUEST_TEST"))
        )
        reported = get_success_data(
            _link_action(
                api, link_id, f.report_result_action("Harbor Analytical", 36.0, 1.0)
            )
        )
        assert reported["measurement_basis"] == BASIS_LAB_TESTED
        assert_concentration(reported["lab_result_ppm"], 36.0, "lab_result_ppm")
        assert_concentration(reported["lab_loq_ppm"], 1.0, "lab_loq_ppm")
        assert_instant(reported["lab_reported_at"], DEFAULT_CLOCK, "lab_reported_at")
        assert reported["lab_name"] == "Harbor Analytical"

    def test_disputing_stores_the_note_and_retracts_the_evidence(
        self, api, declared_link
    ):
        """The disputed laboratory figures stop influencing anything, but the declaration stands.

        PRD: "Disputing takes the link `TEST_REPORTED → DISPUTED` and requires `dispute_note` in the payload; disputing stores the note, resets `measurement_basis` to `SUPPLIER_DECLARED`, and clears `lab_name`, `lab_result_ppm`, `lab_loq_ppm` and `lab_reported_at` all back to null, so the disputed evidence stops influencing any calculation."

        Design: Corner/state_machines/sm_material_chemical_dispute_returns_to_test_requested
        """
        link_id = declared_link["link"]["id"]
        get_success_data(_link_action(api, link_id, f.action_payload("REQUEST_TEST")))
        get_success_data(
            _link_action(
                api, link_id, f.report_result_action("Harbor Analytical", 36.0, 1.0)
            )
        )
        disputed = get_success_data(
            _link_action(
                api,
                link_id,
                f.action_payload(
                    "DISPUTE", dispute_note="Sample chain of custody incomplete"
                ),
                TOXICOLOGY_REVIEWER,
            )
        )
        assert_status(disputed, LINK_STATUS_DISPUTED)
        assert disputed["dispute_note"] == "Sample chain of custody incomplete"
        assert disputed["measurement_basis"] == BASIS_SUPPLIER_DECLARED
        assert_fields_null(
            disputed, ["lab_name", "lab_result_ppm", "lab_loq_ppm", "lab_reported_at"]
        )
        assert_concentration(
            disputed["declared_concentration_ppm"], 40.0, "declared_concentration_ppm"
        )

    def test_the_declared_figure_survives_the_whole_cycle(self, api, declared_link):
        """Four transitions later the supplier's own assertion is still 40.0 ppm.

        PRD: "A supplier's declared figure is an assertion; a laboratory result is evidence."

        Design: Corner/state_machines/sm_material_chemical_dispute_returns_to_test_requested
        """
        link_id = declared_link["link"]["id"]
        get_success_data(_link_action(api, link_id, f.action_payload("REQUEST_TEST")))
        get_success_data(
            _link_action(
                api, link_id, f.report_result_action("Harbor Analytical", 36.0, 1.0)
            )
        )
        get_success_data(
            _link_action(
                api,
                link_id,
                f.action_payload("DISPUTE", dispute_note="Sample chain of custody incomplete"),
                TOXICOLOGY_REVIEWER,
            )
        )
        get_success_data(_link_action(api, link_id, f.action_payload("REQUEST_TEST")))
        stored = _read_link(api, link_id)
        assert_status(stored, LINK_STATUS_TEST_REQUESTED)
        assert_concentration(
            stored["declared_concentration_ppm"], 40.0, "declared_concentration_ppm"
        )


# ─────────────────────────────────────────────────────────────────────────────
# A warranty a live notice is leaning on
# ─────────────────────────────────────────────────────────────────────────────


class TestWarrantyRevocationIsBlockedWhileInUse:
    def test_a_notice_under_evaluation_pins_the_warranty_open(
        self, api, warranty_pinned_by_notice
    ):
        """The warranty window covers the notice's served_at, so revocation is refused.

        PRD: "Revocation is blocked while the warranty is doing live defensive work: if the supplier's warranty window currently covers the `served_at` instant of at least one notice of violation whose status is `UNDER_EVALUATION` or `SETTLEMENT_NEGOTIATION`, the request is refused with `ERR_WARRANTY_IN_USE`."

        Design: Corner/state_machines/sm_supplier_warranty_revoke_blocked_while_notice_in_window
        """
        bundle = warranty_pinned_by_notice
        assert_status(bundle["notice"], NOTICE_UNDER_EVALUATION)
        validate_error(
            api.supplier_transition(
                bundle["supplier"]["id"],
                f.action_payload("REVOKE_WARRANTY"),
                REGULATORY_COUNSEL,
            ),
            ERR_WARRANTY_IN_USE,
            409,
        )
        stored = _read_supplier(api, bundle["supplier"]["id"])
        assert stored["warranty_status"] == WARRANTY_STATUS_ACTIVE
        assert stored["warranty_effective_to"] is None

    def test_dismissing_the_notice_releases_the_warranty(
        self, api, warranty_pinned_by_notice
    ):
        """Once nothing is leaning on it the same call succeeds and closes the window.

        PRD: "When revocation succeeds and `warranty_effective_to` was null, the server stamps it with the current logical clock, closing the open-ended window; from that instant the warranty mitigation factor no longer applies to settlements created afterwards."

        Design: Corner/state_machines/sm_supplier_warranty_revoke_blocked_while_notice_in_window
        """
        bundle = warranty_pinned_by_notice
        validate_error(
            api.supplier_transition(
                bundle["supplier"]["id"],
                f.action_payload("REVOKE_WARRANTY"),
                REGULATORY_COUNSEL,
            ),
            ERR_WARRANTY_IN_USE,
            409,
        )
        dismissed = dismiss_notice(api, bundle["notice"]["id"])
        assert_status(dismissed, NOTICE_DISMISSED)
        assert read_product(api, bundle["product"]["id"])["open_notice_count"] == 0

        revoked = get_success_data(
            api.supplier_transition(
                bundle["supplier"]["id"],
                f.action_payload("REVOKE_WARRANTY"),
                REGULATORY_COUNSEL,
            )
        )
        assert revoked["warranty_status"] == WARRANTY_STATUS_REVOKED
        assert_instant(
            revoked["warranty_effective_to"], DEFAULT_CLOCK, "warranty_effective_to"
        )


# ─────────────────────────────────────────────────────────────────────────────
# The approval cycle's one required note
# ─────────────────────────────────────────────────────────────────────────────


class TestReturnForRevisionRequiresANote:
    def test_without_a_note_the_determination_does_not_move(
        self, api, determination_awaiting_approval
    ):
        """review_note is conditionally required by this action, so its absence is a 400.

        PRD: "A `RegulatoryCounsel` may return it for revision, taking it `PENDING_APPROVAL → DRAFT` and closing that cycle; that action requires `review_note` in the payload, and `review_note` is ignored on every other action on this surface."

        Design: Corner/state_machines/sm_determination_return_for_revision_without_note_rejected
        """
        determination = determination_awaiting_approval["determination"]
        assert_status(determination, DETERMINATION_PENDING_APPROVAL)
        validate_error(
            api.determination_transition(
                determination["id"],
                f.action_payload("RETURN_FOR_REVISION"),
                REGULATORY_COUNSEL,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        stored = _read_determination(api, determination["id"])
        assert_status(stored, DETERMINATION_PENDING_APPROVAL)
        assert stored["review_note"] is None

    def test_with_a_note_the_cycle_closes_back_on_draft(
        self, api, determination_awaiting_approval
    ):
        """The same call carrying the note returns the determination to its preparer.

        PRD: "**The approval cycle.** A determination's `status` moves through `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REVOKED` and `SUPERSEDED`, with the last two terminal."

        Design: Corner/state_machines/sm_determination_return_for_revision_without_note_rejected
        """
        determination = determination_awaiting_approval["determination"]
        validate_error(
            api.determination_transition(
                determination["id"],
                f.action_payload("RETURN_FOR_REVISION"),
                REGULATORY_COUNSEL,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        returned = get_success_data(
            api.determination_transition(
                determination["id"],
                f.action_payload(
                    "RETURN_FOR_REVISION", review_note="Name the CANCER chemical first"
                ),
                REGULATORY_COUNSEL,
            )
        )
        assert_status(returned, DETERMINATION_DRAFT)
        assert returned["review_note"] == "Name the CANCER chemical first"
        assert returned["approved_by_user_id"] is None
        assert returned["prepared_by_user_id"] == LS_1


# ─────────────────────────────────────────────────────────────────────────────
# The bottom of the posture ladder, and the gate that reads it
# ─────────────────────────────────────────────────────────────────────────────


class TestClearIsReachableAndUnlocksMarketing:
    def test_marketing_is_refused_while_the_exposure_picture_is_open(
        self, api, clear_candidate
    ):
        """A PEER_REVIEWED assessment is not FINAL, so clause 2 still holds the product.

        PRD: "Marketing is refused with `ERR_PRODUCT_ON_ENFORCEMENT_HOLD` while `compliance_posture` is `ENFORCEMENT_HOLD` or `EXPOSURE_UNKNOWN`; a product may only go to market once its exposure picture is settled and no enforcement is live."

        Design: Corner/state_machines/sm_posture_reaches_clear_then_market_succeeds
        """
        bundle = clear_candidate
        assert_posture(
            read_product(api, bundle["product"]["id"]), POSTURE_EXPOSURE_UNKNOWN
        )
        validate_error(
            api.product_transition(
                bundle["product"]["id"], f.action_payload("MARKET"), REGISTRY_ADMIN
            ),
            ERR_PRODUCT_ON_ENFORCEMENT_HOLD,
            409,
        )
        assert_lifecycle(
            read_product(api, bundle["product"]["id"]), LIFECYCLE_DEVELOPMENT
        )

    def test_finalizing_a_below_safe_harbor_assessment_reaches_the_fallback(
        self, api, clear_candidate
    ):
        """No clause of the ladder applies once the only assessment is FINAL and BELOW.

        PRD: "5. **`CLEAR`** — no earlier clause applies. This is the fallback."

        Design: Corner/state_machines/sm_posture_reaches_clear_then_market_succeeds
        """
        bundle = clear_candidate
        finalized = get_success_data(
            api.assessment_transition(
                bundle["assessment"]["id"],
                f.action_payload("FINALIZE"),
                TOXICOLOGY_REVIEWER,
            )
        )
        assert_assessment_verdict(finalized, 0.25, 0.5, RESULT_BELOW, 1)

        product = read_product(api, bundle["product"]["id"])
        assert_posture(product, POSTURE_CLEAR)
        assert_lifecycle(product, LIFECYCLE_DEVELOPMENT)

    def test_the_gate_is_a_posture_test_and_not_a_lifecycle_test(
        self, api, clear_candidate
    ):
        """The identical MARKET call that failed now succeeds, and CLEAR survives it.

        PRD: "Both actions are reserved to a `RegistryAdmin`, both increment the product's `version` by 1, and neither touches `compliance_posture` — the two dimensions are genuinely independent."

        Design: Corner/state_machines/sm_posture_reaches_clear_then_market_succeeds
        """
        bundle = clear_candidate
        validate_error(
            api.product_transition(
                bundle["product"]["id"], f.action_payload("MARKET"), REGISTRY_ADMIN
            ),
            ERR_PRODUCT_ON_ENFORCEMENT_HOLD,
            409,
        )
        get_success_data(
            api.assessment_transition(
                bundle["assessment"]["id"],
                f.action_payload("FINALIZE"),
                TOXICOLOGY_REVIEWER,
            )
        )
        marketed = get_success_data(
            api.product_transition(
                bundle["product"]["id"], f.action_payload("MARKET"), REGISTRY_ADMIN
            )
        )
        assert_lifecycle(marketed, LIFECYCLE_MARKETED)
        assert_posture(marketed, POSTURE_CLEAR)
