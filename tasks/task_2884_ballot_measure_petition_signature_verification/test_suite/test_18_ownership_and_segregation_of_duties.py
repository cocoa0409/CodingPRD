"""Peer-level identity rules: ownership scoping and segregation of duties.

Every refusal here comes from an actor that holds the right role. Two counties
give two `CountyClerk` identities, two circulators give two `CirculatorAgent`
identities, and two proponents give two petition owners, so a 403 can only be
about who is acting. Each denial is followed by the same call from the rightful
owner, which also pins the ordering: ownership (priority 7) is reached before
the state gate (priority 10). The last two tests cover the other identity bar,
segregation of duties, which is checked against a recorded identifier rather
than a role, alongside the referral stage gate that shares its neighbourhood.
"""
from test_helpers import (
    api_client,
    create_voter_record_payload,
    make_circulator_agent_headers,
    make_county_clerk_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    paid_disclosure_payload,
    read_batch,
    read_circulator,
    read_line,
    read_petition,
    read_referral,
    registration_status_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import (
    adjudicate_payload,
    create_batch_payload,
    determination_payload,
    training_payload,
    verify_affidavit_payload,
)
from test_helpers.fixtures import (
    add_line,
    add_voter,
    create_assignment,
    create_cleared_petition,
    create_registered_circulator,
    file_batch,
    file_batch_with_lines,
    file_petition,
    open_referral,
    register_circulator,
    register_county,
    register_standard,
    run_verification_round,
    set_clock,
    setup_circulation_ready,
)

TALLY_CLOCK = "2026-08-10T00:00:00Z"


def _ownership_world():
    """ALPHA and BETA counties (two clerk identities), circulators c1 and c2 (two
    agent identities), petition p1 owned by prop-1 and still DRAFT, petition p2
    owned by prop-2 and cleared with an ALPHA assignment for c1 carrying one
    filed batch and one line. Every refused call below is therefore legal in
    every respect except the identity of its actor."""
    set_clock(CLOCK_EPOCH)
    standard = register_standard(jurisdiction_code="SOS-O")
    alpha = register_county("ALPHA", 20)
    beta = register_county("BETA", 20)
    voter = add_voter(
        alpha["id"], "VA1", full_name="Ada Adams", registration_status="ACTIVE"
    )
    p1 = file_petition(
        standard["id"],
        proponent_user_id="prop-1",
        measure_subject_codes=("TAX",),
        proponent_name="Owner One",
        submitted_title="Owner Measure One",
    )
    p2 = create_cleared_petition(
        standard["id"],
        proponent_user_id="prop-2",
        measure_subject_codes=("ENVIRONMENT",),
        proponent_name="Owner Two",
        submitted_title="Owner Measure Two",
    )
    c1 = create_registered_circulator(
        full_name="Cora Carter", is_paid=True, employer_name="Signature Co"
    )
    c2 = register_circulator(full_name="Dana Doyle")
    create_assignment(p2["id"], c1["id"], assigned_county_codes=("ALPHA",))
    batch = file_batch(p2["id"], c1["id"], alpha["id"], proponent_user_id="prop-2")
    line = add_line(
        batch["id"],
        line_number=1,
        claimed_voter_id_number="VA1",
        signed_on="2026-08-05T00:00:00Z",
        signer_name="Ada Adams",
        proponent_user_id="prop-2",
    )
    assert p1["status"] == "DRAFT"
    assert batch["status"] == "RECEIVED"
    return {
        "standard": standard,
        "alpha": alpha,
        "beta": beta,
        "voter": voter,
        "p1": p1,
        "p2": p2,
        "c1": c1,
        "c2": c2,
        "batch": batch,
        "line": line,
    }


class TestOwnerScopedWritesDeniedToPeersOfTheSameRole:
    """A clerk, an agent and a proponent are each refused a peer's resource, and
    the rightful owner then makes the identical call succeed."""

    def test_a_clerk_holding_the_role_is_still_confined_to_its_own_county(self):
        """BETA's clerk is refused ALPHA's batch, ALPHA's voter roll — both the
        status write and a fresh creation — and a line whose county comes from the
        owning batch; ALPHA's clerk then verifies and validates the same records.

        PRD §2.1: "Concretely, a `CountyClerk` may only act on a
        `SignatureBatch` whose `county_id` equals `X-User-ID`, on a
        `SignatureRecord` whose owning batch has a `county_id` equal to
        `X-User-ID`, and on a `VoterRecord` whose `county_id` equals `X-User-ID`."

        Design: Corner/rbac/entity_backed_and_owner_scoped_writes_denied_to_non_owners
        """
        world = _ownership_world()
        beta_clerk = make_county_clerk_headers(world["beta"]["id"])
        alpha_clerk = make_county_clerk_headers(world["alpha"]["id"])

        validate_error(
            api_client.verify_affidavit(
                world["batch"]["id"], verify_affidavit_payload("NOT-B"), beta_clerk
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.set_voter_registration_status(
                world["voter"]["id"], registration_status_payload("CANCELLED"), beta_clerk
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.create_voter_record(
                create_voter_record_payload(
                    world["alpha"]["id"],
                    voter_id_number="VB9",
                    full_name="Beta Intruder",
                    signature_on_file_hash="H-VB9",
                    registration_date="2021-01-01T00:00:00Z",
                ),
                beta_clerk,
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.validate_signature_record(world["line"]["id"], beta_clerk),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )

        verified = validate_success(
            api_client.verify_affidavit(
                world["batch"]["id"], verify_affidavit_payload("NOT-A"), alpha_clerk
            )
        )
        assert verified["status"] == "AFFIDAVIT_VERIFIED", (
            "the identical call from ALPHA's clerk succeeds"
        )
        assert verified["affidavit_notary_id"] == "NOT-A"

        # The line can only be adjudicated inside an open round's sample, so
        # circulation is closed and a round opened before the owner validates.
        validate_success(
            api_client.file_signatures(
                world["p2"]["id"], make_proponent_headers("prop-2")
            )
        )
        validate_success(
            api_client.create_verification_round(
                world["p2"]["id"],
                {"round_type": "RANDOM_SAMPLE"},
                make_examiner_headers("exam-1"),
            ),
            201,
        )
        validated = validate_success(
            api_client.validate_signature_record(world["line"]["id"], alpha_clerk)
        )
        assert validated["validation_status"] == "VALID"
        assert validated["matched_voter_record_id"] == world["voter"]["id"]

        untouched_voter = validate_success(
            api_client.get_voter_record(world["voter"]["id"], make_sos_admin_headers())
        )
        assert untouched_voter["registration_status"] == "ACTIVE", (
            "the refused status write left no trace"
        )
        rows, meta = validate_paginated(
            api_client.list_voter_records(make_sos_admin_headers())
        )
        assert meta["total_count"] == 1
        assert {row["voter_id_number"] for row in rows} == {"VA1"}

    def test_a_proponent_may_act_only_on_its_own_petition(self):
        """prop-2 cannot advance prop-1's petition even though that petition is
        legitimately submittable, prop-1 cannot close prop-2's circulation, and
        prop-1 cannot file a batch naming prop-2's petition.

        PRD §2.1: "a `Proponent` may act on a `Petition` only when the petition's
        `proponent_user_id` equals `X-User-ID`"

        PRD §2.11: "authorisation always precedes shape, shape always precedes
        existence, existence always precedes ownership, ownership precedes
        concurrency, concurrency precedes state, and state precedes every
        business rule."

        Design: Corner/rbac/entity_backed_and_owner_scoped_writes_denied_to_non_owners
        """
        world = _ownership_world()

        validate_error(
            api_client.submit_petition(
                world["p1"]["id"], make_proponent_headers("prop-2")
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )  # not ERR_INVALID_PETITION_STATE: ownership at 7 precedes state at 10
        validate_error(
            api_client.file_signatures(
                world["p2"]["id"], make_proponent_headers("prop-1")
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.create_signature_batch(
                create_batch_payload(
                    world["p2"]["id"], world["c1"]["id"], world["alpha"]["id"]
                ),
                make_proponent_headers("prop-1"),
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )  # body-level ownership: prop-1 names prop-2's petition

        submitted = validate_success(
            api_client.submit_petition(
                world["p1"]["id"], make_proponent_headers("prop-1")
            )
        )
        assert submitted["status"] == "FORMAT_REVIEW", (
            "the rightful owner's identical call succeeds"
        )
        assert read_petition(world["p2"]["id"])["status"] == "CLEARED", (
            "the refused file-signatures left prop-2's petition circulating"
        )
        batches, meta = validate_paginated(
            api_client.list_signature_batches(make_sos_admin_headers())
        )
        assert {row["id"] for row in batches} == {world["batch"]["id"]}
        assert meta["total_count"] == 1

    def test_a_circulator_agent_may_act_only_for_itself(self):
        """c2's agent is refused a batch naming c1 and all three of c1's own
        registration writes; c1 keeps the disclosure and course it already had.

        PRD §2.1: "A `CirculatorAgent` may act on a `Circulator` only when that
        circulator's `id` equals `X-User-ID`, and may create a `SignatureBatch`
        only when the submitted `circulator_id` equals `X-User-ID`."

        Design: Corner/rbac/entity_backed_and_owner_scoped_writes_denied_to_non_owners
        """
        world = _ownership_world()
        intruder = make_circulator_agent_headers(world["c2"]["id"])

        validate_error(
            api_client.create_signature_batch(
                create_batch_payload(
                    world["p2"]["id"], world["c1"]["id"], world["alpha"]["id"]
                ),
                intruder,
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.record_training(
                world["c1"]["id"], training_payload("SOS-CIRC-201"), intruder
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.file_paid_disclosure(
                world["c1"]["id"], paid_disclosure_payload("DISC-INTRUDER"), intruder
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.file_affidavit(world["c1"]["id"], {"sworn": True}, intruder),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )

        unchanged = read_circulator(world["c1"]["id"])
        assert unchanged["disclosure_document_id"] == "DISC-1"
        assert unchanged["training_course_code"] == "SOS-CIRC-101"
        assert unchanged["registration_status"] == "REGISTERED"
        assert unchanged["version"] == world["c1"]["version"] + 1, (
            "only the assignment created in setup bumped c1"
        )

        batches, meta = validate_paginated(
            api_client.list_signature_batches(make_sos_admin_headers())
        )
        assert {row["id"] for row in batches} == {world["batch"]["id"]}
        assert meta["total_count"] == 1
        assert read_batch(world["batch"]["id"])["raw_count"] == 1
        assert read_line(world["line"]["id"])["validation_status"] == "PENDING"


def _duties_world():
    """Standard `SOS-S` needs exactly one valid signature and sets the upper gate
    at that same one, so a single census-validated line tallies `SUFFICIENT` and
    leaves the petition in `PENDING_CERTIFICATION`. exam-1 opens the round and
    tallies it, so exam-1 is both the round's `tallied_by_examiner_id` and — once
    it opens one — a referral's `opened_by_examiner_id`."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": "SOS-S",
            "signature_pct_bps": 100,
            "sufficiency_upper_bps": 10000,
        },
        counties=[("ALPHA", 20)],
        voters=["VA1"],
    )
    file_batch_with_lines(world, ["VA1"])
    set_clock(TALLY_CLOCK)
    closed = run_verification_round(world, examiner_id="exam-1")
    assert closed["determination"] == "SUFFICIENT"
    assert closed["tallied_by_examiner_id"] == "exam-1"
    assert world["petition"]["status"] == "PENDING_CERTIFICATION"
    return world


class TestSegregationOfDutiesAndTheReferralStageGate:
    """Two independent separation rules share one code, and each is probed
    against an actor that is otherwise perfectly entitled to act."""

    def test_the_examiner_who_opened_a_referral_cannot_adjudicate_it(self):
        """The stage gate answers on both sides of the adjudication window, and
        between them the opener is barred while a different identity is not.

        PRD §3.9: "Adjudication is possible only from `REFERRED_TO_AG` —
        adjudicating a referral still merely `OPENED`, or one already adjudicated,
        is refused with `ERR_REFERRAL_NOT_WITH_AG` — and the adjudicating
        `X-User-ID` must differ from the referral's `opened_by_examiner_id`, else
        the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_and_referral_stage_gates
        """
        world = _duties_world()
        petition_id = world["petition"]["id"]
        circulator = world["circulator"]

        referral = open_referral(
            petition_id,
            circulator["id"],
            referral_type="CIRCULATOR_MISCONDUCT",
            opened_by="exam-1",
        )
        assert referral["status"] == "OPENED"
        assert referral["opened_by_examiner_id"] == "exam-1"
        assert referral["referred_to_ag"] is False
        assert referral["finding"] is None

        validate_error(
            api_client.adjudicate_referral(
                referral["id"],
                adjudicate_payload("UNSUBSTANTIATED"),
                make_examiner_headers("exam-2"),
            ),
            "ERR_REFERRAL_NOT_WITH_AG",
            409,
        )  # still OPENED, and exam-2 would be a legitimate adjudicator

        referred = validate_success(
            api_client.refer_to_ag(referral["id"], make_examiner_headers("exam-1"))
        )
        assert referred["status"] == "REFERRED_TO_AG"
        assert referred["referred_to_ag"] is True

        validate_error(
            api_client.adjudicate_referral(
                referral["id"],
                adjudicate_payload("UNSUBSTANTIATED"),
                make_examiner_headers("exam-1"),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )  # the stage gate is satisfied, so only the identity bar can explain it

        adjudicated = validate_success(
            api_client.adjudicate_referral(
                referral["id"], adjudicate_payload("UNSUBSTANTIATED"), make_sos_admin_headers()
            )
        )
        assert adjudicated["finding"] == "UNSUBSTANTIATED"
        assert adjudicated["status"] == "UNSUBSTANTIATED"
        assert adjudicated["adjudicated_by_examiner_id"] == "admin-1"
        assert adjudicated["voided_signature_count"] == 0

        validate_error(
            api_client.adjudicate_referral(
                referral["id"],
                adjudicate_payload("SUBSTANTIATED"),
                make_examiner_headers("exam-2"),
            ),
            "ERR_REFERRAL_NOT_WITH_AG",
            409,
        )  # an adjudicated referral has left the AG stage

        settled = read_referral(referral["id"])
        assert settled["finding"] == "UNSUBSTANTIATED", "the replay changed nothing"
        after = read_circulator(circulator["id"])
        assert after["registration_status"] == "REGISTERED"
        assert after["misconduct_strike_count"] == 0
        petition = read_petition(petition_id)
        assert petition["voided_signature_count"] == 0
        assert petition["status"] == "PENDING_CERTIFICATION", (
            "an unsubstantiated referral voids nothing and leaves certification open"
        )

    def test_the_examiner_who_tallied_the_deciding_round_cannot_certify(self):
        """exam-1 tallied the latest closed round, so exam-1's determination is
        refused; the administrator's identical determination certifies.

        PRD §2.12: "Issuing a petition's determination compares the acting
        `X-User-ID` against the `tallied_by_examiner_id` of that petition's latest
        closed verification round. If they are equal, the determination is refused
        with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403 — the examiner who counted
        may not be the examiner who certifies or fails."

        PRD §2.12: "Both bars apply to `SosAdmin` and `ElectionsExaminer` alike,
        because both roles may reach both operations; the bar is on the
        identifier, not on the role."

        Design: Corner/rbac/segregation_of_duties_and_referral_stage_gates
        """
        world = _duties_world()
        petition_id = world["petition"]["id"]

        validate_error(
            api_client.issue_determination(
                petition_id, determination_payload("CERTIFY"), make_examiner_headers("exam-1")
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        held = read_petition(petition_id)
        assert held["status"] == "PENDING_CERTIFICATION", "the refusal is not a failure"

        certified = validate_success(
            api_client.issue_determination(
                petition_id, determination_payload("CERTIFY"), make_sos_admin_headers()
            )
        )
        assert certified["status"] == "CERTIFIED", (
            "the identical determination from a different identity succeeds, so the "
            "refusal was about who tallied and not about the petition's readiness"
        )
