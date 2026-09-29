"""Requests carrying two defects at once, where §2.11 fixes which one is
reported.

Each pair is checked twice: once with both defects present, to prove the
higher-priority check wins, and once with only the lower-priority defect, to
prove the masked code is genuinely reachable.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_batch_payload,
    create_cleared_petition,
    file_batch_with_lines,
    create_round_payload,
    file_petition,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    open_followup_round,
    read_circulator,
    read_petition,
    read_round,
    record_training,
    register_circulator,
    register_standard,
    run_verification_round,
    setup_circulation_ready,
    setup_program,
    tally_round,
    validate_error,
    validate_open_sample,
    close_circulation_and_open_round,
    file_circulator_affidavit,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

SAMPLING_STANDARD = {
    "jurisdiction_code": "SOS-POOL",
    "stratification_mode": "POOLED",
    "sample_pct_bps": 5000,
    "sample_min_count": 2,
}


class TestRoleDenialOutranksMissingPath:
    """§2.11 step 3 (role authorised, 403) precedes step 5 (path identifiers
    resolve, 404)."""

    def _program_with_draft(self):
        set_clock(CLOCK_EPOCH)
        standard = register_standard()
        return file_petition(standard["id"])

    def test_an_unauthorised_role_is_denied_before_the_missing_petition_is_looked_up(self):
        """A Proponent calling a SosAdmin-only clearance endpoint on an id that
        does not exist sees the 403, never the 404.

        PRD §2.11: "3. Role authorised. The acting role appears in the
        endpoint's authorised-role list, else ERR_UNAUTHORIZED (403) ... 5. Path
        identifiers resolve. Left to right, as described in §2.8, each failure
        yielding that type's not-found code (404)."

        Design: Difficulty/priority_pair_validation_conflict/role_denial_outranks_missing_petition_on_clearance
        """
        petition = self._program_with_draft()

        validate_error(
            api_client.clear_for_circulation(NON_EXISTENT_UUID, make_proponent_headers()),
            "ERR_UNAUTHORIZED",
            403,
        )

        assert read_petition(petition["id"])["status"] == "DRAFT", (
            "the refused call touched nothing"
        )

    def test_the_missing_petition_surfaces_once_the_role_is_authorised(self):
        """The same unresolvable id, presented by the authorised SosAdmin, gets
        as far as the path lookup and reports 404.

        PRD §2.11: "5. Path identifiers resolve. Left to right, as described in
        §2.8, each failure yielding that type's not-found code (404). Applies to
        every endpoint carrying a path parameter."

        Design: Difficulty/priority_pair_validation_conflict/role_denial_outranks_missing_petition_on_clearance
        """
        petition = self._program_with_draft()

        validate_error(
            api_client.clear_for_circulation(NON_EXISTENT_UUID, make_sos_admin_headers()),
            "ERR_PETITION_NOT_FOUND",
            404,
        )

        assert read_petition(petition["id"])["status"] == "DRAFT"


class TestOpenRoundStateOutranksEmptyPool:
    """§2.11 step 10 (entity state, ERR_ROUND_ALREADY_OPEN) precedes step 15
    (counting and quota gates, ERR_EMPTY_ELIGIBLE_POOL)."""

    def test_an_open_round_masks_a_pool_that_is_also_empty(self):
        """The second round is still OPEN and has already consumed every
        remaining line, so a third round attempt carries both defects — and the
        state conflict is what the caller sees.

        PRD §2.11: "10. State preconditions. The target resource is in a state
        that admits the requested transition — ... round status gates and the
        one-open-round-per-petition rule ... The signals are ...
        ERR_ROUND_ALREADY_OPEN ... 15. Counting and quota gates, evaluated last.
        ... the eligible pool non-empty at round creation ... The signals are ...
        ERR_EMPTY_ELIGIBLE_POOL ... all HTTP 409."

        Design: Difficulty/priority_pair_validation_conflict/open_round_state_outranks_empty_pool_quota
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides=SAMPLING_STANDARD,
            counties=[("ALPHA", 20)],
            voters=[
                {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
                {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
                # VA3 is drawn into the sample (positions 0 and 2 of the four-line
                # pool) and is off the roll, so the round's validity_rate_bps is
                # 5000 and the pooled projection floor(4 * 5000 / 10000) == 2 lands
                # strictly between lower_gate 1 and upper_gate 3.
                {"voter_id_number": "VA3", "registration_status": "INACTIVE"},
                {"voter_id_number": "VA4", "registration_status": "ACTIVE"},
            ],
        )
        file_batch_with_lines(world, ["VA1", "VA2", "VA3", "VA4"], batch_key="b1")
        close_circulation_and_open_round(world, round_type="RANDOM_SAMPLE")
        validate_open_sample(world)
        first = tally_round(world["round"]["id"])
        assert first["sample_size"] == 2, "max(2, ceil(4 * 5000 / 10000))"
        assert first["validity_rate_bps"] == 5000, "one of the two drawn lines is valid"
        assert first["projected_valid_count"] == 2, "floor(4 * 5000 / 10000)"
        assert first["determination"] == "FULL_CHECK_REQUIRED"

        second = open_followup_round(world, round_type="FULL_CHECK")
        assert second["eligible_pool_size"] == 2
        assert second["status"] == "OPEN"

        validate_error(
            api_client.create_verification_round(
                world["petition"]["id"],
                create_round_payload("FULL_CHECK"),
                make_examiner_headers(),
            ),
            "ERR_ROUND_ALREADY_OPEN",
            409,
        )

        assert read_round(second["id"])["status"] == "OPEN"
        assert read_petition(world["petition"]["id"])["status"] == "FULL_CHECK"

    def test_the_empty_pool_gate_fires_when_no_round_is_open(self):
        """With every line already examined and the previous round closed, the
        lower-priority quota gate is what refuses the round.

        PRD §3.5: "Whatever the type, an empty pool refuses the round with
        ERR_EMPTY_ELIGIBLE_POOL, and the pool's size is recorded on the round as
        eligible_pool_size."

        Design: Difficulty/priority_pair_validation_conflict/open_round_state_outranks_empty_pool_quota
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)],
            voters=[
                {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
                {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
            ],
        )
        file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
        closed = run_verification_round(world)
        assert closed["determination"] == "FULL_CHECK_REQUIRED"
        assert read_petition(world["petition"]["id"])["status"] == "FULL_CHECK", (
            "a state the round-creation endpoint accepts, so no state gate fires"
        )

        validate_error(
            api_client.create_verification_round(
                world["petition"]["id"],
                create_round_payload("FULL_CHECK"),
                make_examiner_headers(),
            ),
            "ERR_EMPTY_ELIGIBLE_POOL",
            409,
        )


class TestRegistrationGateOutranksMissingAssignment:
    """§2.11 step 12 (statutory eligibility, 422) precedes step 13 (cross-entity
    linkage, 409) on batch filing."""

    def _program_with_unregistered_circulator(self):
        """A cleared petition, one county, and a circulator that stopped at
        TRAINED — with no CirculationAssignment anywhere in the system."""
        set_clock(CLOCK_EPOCH)
        world = setup_program(counties=[("ALPHA", 20)], voters=["VA1"])
        world["petition"] = create_cleared_petition(world["standard"]["id"])
        circulator = register_circulator(full_name="Cora Trainee")
        world["circulators"]["c1"] = record_training(circulator["id"])
        assert world["circulators"]["c1"]["registration_status"] == "TRAINED"
        return world

    def test_the_registration_gate_masks_the_absent_assignment(self):
        """The circulator is both unregistered and unassigned; the 422
        eligibility signal is the one returned.

        PRD §3.4: "The named circulator's registration_status must be exactly
        REGISTERED; anything else — still PENDING_TRAINING, merely TRAINED, or
        SUSPENDED — is refused with ERR_CIRCULATOR_NOT_REGISTERED ... That
        circulator must hold an ACTIVE CirculationAssignment for this petition;
        if none was ever created, or the only one is SUSPENDED or TERMINATED, the
        filing is refused with ERR_NO_ACTIVE_ASSIGNMENT."

        Design: Difficulty/priority_pair_validation_conflict/circulator_registration_gate_outranks_missing_assignment
        """
        world = self._program_with_unregistered_circulator()

        validate_error(
            api_client.create_signature_batch(
                create_batch_payload(
                    world["petition"]["id"],
                    world["circulators"]["c1"]["id"],
                    world["counties"]["ALPHA"]["id"],
                ),
                make_proponent_headers(),
            ),
            "ERR_CIRCULATOR_NOT_REGISTERED",
            422,
        )

        assert read_circulator(world["circulators"]["c1"]["id"])["registration_status"] == (
            "TRAINED"
        )
        assert read_petition(world["petition"]["id"])["raw_signature_count"] == 0

    def test_the_absent_assignment_surfaces_once_the_circulator_is_registered(self):
        """Swearing the affidavit clears the eligibility gate, and the linkage
        gate underneath it is then reachable.

        PRD §3.4: "That circulator must hold an ACTIVE CirculationAssignment for
        this petition; if none was ever created, or the only one is SUSPENDED or
        TERMINATED, the filing is refused with ERR_NO_ACTIVE_ASSIGNMENT."

        Design: Difficulty/priority_pair_validation_conflict/circulator_registration_gate_outranks_missing_assignment
        """
        world = self._program_with_unregistered_circulator()
        registered = file_circulator_affidavit(world["circulators"]["c1"]["id"])
        assert registered["registration_status"] == "REGISTERED"

        validate_error(
            api_client.create_signature_batch(
                create_batch_payload(
                    world["petition"]["id"],
                    registered["id"],
                    world["counties"]["ALPHA"]["id"],
                ),
                make_proponent_headers(),
            ),
            "ERR_NO_ACTIVE_ASSIGNMENT",
            409,
        )

        assert read_petition(world["petition"]["id"])["raw_signature_count"] == 0
