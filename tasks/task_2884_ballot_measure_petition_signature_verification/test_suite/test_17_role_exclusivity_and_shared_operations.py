"""The role matrix from both sides: exclusive denials and shared acceptances.

Priority 3 sits above shape and above existence, so every denial probe below
names an identifier the API never issued and must still answer
`ERR_UNAUTHORIZED` (403) rather than 400 or 404. `SosAdmin` is not a superuser
in this program: format review, round opening and tallying, title drafting,
petition filing, affidavit verification and challenge escalation are all closed
to it. Reads are role-scoped too. The mirror-image tests then show that every
role listed for a shared operation can actually perform it.
"""
from test_helpers import (
    api_client,
    create_petition_payload,
    create_voter_record_payload,
    make_challenger_headers,
    make_circulator_agent_headers,
    make_county_clerk_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    make_title_examiner_headers,
    minimal_verification_standard_payload,
    paid_disclosure_payload,
    read_petition,
    registration_status_payload,
    title_summary_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import clock_payload
from test_helpers.fixtures import (
    file_petition,
    register_county,
    register_standard,
    set_clock,
)

# An identifier the API never issues.
MISSING = "00000000-0000-0000-0000-000000009999"


def _role_probe_world():
    """A standard and a DRAFT petition, created only so the title-summary probe
    can carry a server-issued version. Neither is ever named in a probe path."""
    set_clock(CLOCK_EPOCH)
    standard = register_standard(jurisdiction_code="SOS-Y")
    petition = file_petition(
        standard["id"],
        measure_subject_codes=("TAX",),
        proponent_name="Role Probe",
        submitted_title="Role Probe Measure",
    )
    return {"standard": standard, "petition": petition}


class TestExclusiveOperationsDeniedToEveryOtherRole:
    """Every operation the specification gives to exactly one role refuses every
    other role with 403, before any identifier is resolved."""

    def test_no_role_can_reach_another_roles_exclusive_write(self):
        """Nine writes reserved to a single role are refused to a role that holds
        a different mandate, each on a path that does not resolve.

        PRD §2.1: "Only once the role is recognised does the server ask whether
        that role is listed among the acting endpoint's authorised roles in §4; a
        recognised role attempting an operation it is not authorised for is
        refused with `ERR_UNAUTHORIZED` and HTTP 403."

        Design: Corner/rbac/exclusive_operations_denied_to_every_other_role
        """
        set_clock(CLOCK_EPOCH)

        validate_error(
            api_client.create_verification_standard(
                minimal_verification_standard_payload(jurisdiction_code="SOS-Z"),
                make_examiner_headers(),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_county(
                {"county_code": "ZULU", "name": "Zulu County", "registered_voter_count": 10},
                make_county_clerk_headers(MISSING),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.set_clock(clock_payload(CLOCK_EPOCH), make_examiner_headers()),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.clear_for_circulation(MISSING, make_examiner_headers()),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_cure_period(MISSING, make_examiner_headers()),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.invalidate_batch(
                MISSING, {"invalidation_reason": "not my call"}, make_county_clerk_headers(MISSING)
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.void_round(
                MISSING, {"voided_reason": "not my call"}, make_examiner_headers()
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.revoke_circulator(MISSING, make_proponent_headers("prop-1")),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.rule_on_challenge(
                MISSING, {"ruling": "AFFIRM"}, make_challenger_headers("chal-1")
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

    def test_the_administrator_is_not_a_superuser(self):
        """Eleven probes: nine operations closed to `SosAdmin`, plus line
        validation closed to the examiner and challenge filing closed to the
        proponent.

        PRD §2.1: "A `TitleExaminer` sits in the Attorney General's office and is
        the only role permitted to write a petition's official title and summary."

        PRD §2.1: "A `Challenger` is any elector or party contesting a pending
        determination. It files a challenge and escalates it to court review."

        Design: Corner/rbac/exclusive_operations_denied_to_every_other_role
        """
        world = _role_probe_world()
        admin = make_sos_admin_headers()

        validate_error(
            api_client.format_decision(MISSING, {"decision": "APPROVE"}, admin),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_verification_round(
                MISSING, {"round_type": "RANDOM_SAMPLE"}, admin
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(api_client.tally_round(MISSING, admin), "ERR_UNAUTHORIZED", 403)
        validate_error(
            api_client.put_title_summary(
                MISSING,
                title_summary_payload(
                    world["petition"]["version"],
                    official_title="Not Mine",
                    official_summary="Not mine either.",
                ),
                admin,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_petition(
                create_petition_payload(
                    MISSING,
                    proponent_name="Wrong Role",
                    submitted_title="Wrong Role",
                    measure_subject_codes=["TAX"],
                ),
                admin,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(api_client.submit_petition(MISSING, admin), "ERR_UNAUTHORIZED", 403)
        validate_error(api_client.file_signatures(MISSING, admin), "ERR_UNAUTHORIZED", 403)
        validate_error(
            api_client.verify_affidavit(MISSING, {"affidavit_notary_id": "NOT-9"}, admin),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.escalate_challenge(
                MISSING, {"court_docket_number": "CV-2026-7777"}, admin
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.validate_signature_record(MISSING, make_examiner_headers()),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_challenge(
                MISSING,
                {
                    "challenger_name": "Wrong Role",
                    "grounds": "COUNT_ERROR",
                    "statement": "Wrong role.",
                },
                make_proponent_headers("prop-1"),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        untouched = read_petition(world["petition"]["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["official_title"] is None
        assert untouched["version"] == world["petition"]["version"], (
            "no refused probe mutated the petition"
        )

    def test_read_endpoints_are_role_scoped_too(self):
        """The voter roll is closed to a `Proponent`, the invoice to a
        `Challenger`, the distribution report to a `TitleExaminer` and the
        circulator list to a `Challenger`.

        PRD §2.1: "Every request to every endpoint — reads included — must carry
        two headers."

        Design: Corner/rbac/exclusive_operations_denied_to_every_other_role
        """
        world = _role_probe_world()

        validate_error(
            api_client.list_voter_records(make_proponent_headers("prop-1")),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.get_verification_invoice(MISSING, make_challenger_headers("chal-1")),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.get_distribution_report(MISSING, make_title_examiner_headers()),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.list_circulators(make_challenger_headers("chal-1")),
            "ERR_UNAUTHORIZED",
            403,
        )

        counties, county_meta = validate_paginated(
            api_client.list_counties(make_sos_admin_headers())
        )
        assert counties == [], "no probe created anything"
        assert county_meta["total_count"] == 0
        petitions, petition_meta = validate_paginated(
            api_client.list_petitions(make_sos_admin_headers())
        )
        assert {row["id"] for row in petitions} == {world["petition"]["id"]}
        assert petition_meta["total_count"] == 1


class TestSharedOperationsAcceptEveryListedRole:
    """Where §4 lists two roles for one operation, both of them succeed."""

    def test_the_circulator_registration_steps_accept_every_listed_role(self):
        """Registration is exercised from `SosAdmin` and `Proponent`, training and
        the affidavit from the administrator and from the circulator's own agent,
        and the paid disclosure from the agent.

        PRD §3.3: "Registering a circulator is open to a `SosAdmin` and to a
        `Proponent`."

        PRD §3.3: "Filing the disclosure is a dedicated write available to a
        `SosAdmin` and to the `CirculatorAgent` acting for itself: it supplies the
        `disclosure_document_id` identifying the filed paid-circulator disclosure
        document and may supply an `employer_name` at the same time, and it
        recomputes `paid_disclosure_on_file` immediately."

        Design: Corner/rbac/shared_operations_accept_every_listed_role
        """
        set_clock(CLOCK_EPOCH)

        by_admin = validate_success(
            api_client.create_circulator(
                {"full_name": "Admin Registered", "residency_state_code": "CA"},
                make_sos_admin_headers(),
            ),
            201,
        )
        by_proponent = validate_success(
            api_client.create_circulator(
                {
                    "full_name": "Proponent Registered",
                    "residency_state_code": "CA",
                    "is_paid": True,
                    "employer_name": "Signature Co",
                },
                make_proponent_headers("prop-1"),
            ),
            201,
        )
        assert by_admin["registration_status"] == "PENDING_TRAINING"
        assert by_proponent["is_paid"] is True
        assert by_proponent["paid_disclosure_on_file"] is False

        trained_by_agent = validate_success(
            api_client.record_training(
                by_admin["id"],
                {"training_course_code": "SOS-CIRC-101"},
                make_circulator_agent_headers(by_admin["id"]),
            )
        )
        assert trained_by_agent["training_course_code"] == "SOS-CIRC-101"
        assert trained_by_agent["registration_status"] == "TRAINED"

        trained_by_admin = validate_success(
            api_client.record_training(
                by_proponent["id"],
                {"training_course_code": "SOS-CIRC-201"},
                make_sos_admin_headers(),
            )
        )
        assert trained_by_admin["training_course_code"] == "SOS-CIRC-201", (
            "both codes are on the approved pair"
        )
        assert trained_by_admin["registration_status"] == "TRAINED"

        disclosed = validate_success(
            api_client.file_paid_disclosure(
                by_proponent["id"],
                paid_disclosure_payload("DISC-2", employer_name="Signature Co"),
                make_circulator_agent_headers(by_proponent["id"]),
            )
        )
        assert disclosed["paid_disclosure_on_file"] is True

        sworn_by_agent = validate_success(
            api_client.file_affidavit(
                by_admin["id"],
                {"sworn": True},
                make_circulator_agent_headers(by_admin["id"]),
            )
        )
        assert sworn_by_agent["registration_status"] == "REGISTERED"

        sworn_by_admin = validate_success(
            api_client.file_affidavit(
                by_proponent["id"], {"sworn": True}, make_sos_admin_headers()
            )
        )
        assert sworn_by_admin["registration_status"] == "REGISTERED", (
            "the paid circulator needed its disclosure first"
        )

    def test_the_voter_roll_writes_accept_the_administrator_and_the_owning_clerk(self):
        """A clerk-created record takes the declared `ACTIVE` default exactly as
        an admin-created one does, and the shared `PUT` is open to that clerk.

        PRD §3.1: "A `VoterRecord` is added by a `SosAdmin` or by the
        `CountyClerk` whose county it belongs to" and "A voter's
        `registration_status` may be supplied at creation and accepts `ACTIVE`
        when omitted".

        PRD §3.1: "Moving a voter between the four registration states is
        therefore a dedicated write, taking a single `registration_status`,
        available to a `SosAdmin` and to the owning `CountyClerk`."

        Design: Corner/rbac/shared_operations_accept_every_listed_role
        """
        set_clock(CLOCK_EPOCH)
        alpha = register_county("ALPHA", 20)
        clerk = make_county_clerk_headers(alpha["id"])

        by_admin = validate_success(
            api_client.create_voter_record(
                create_voter_record_payload(
                    alpha["id"],
                    voter_id_number="VA1",
                    full_name="Ada Adams",
                    signature_on_file_hash="H-VA1",
                    registration_date="2020-01-01T00:00:00Z",
                    registration_status="ACTIVE",
                ),
                make_sos_admin_headers(),
            ),
            201,
        )
        by_clerk = validate_success(
            api_client.create_voter_record(
                create_voter_record_payload(
                    alpha["id"],
                    voter_id_number="VA2",
                    full_name="Ben Baker",
                    signature_on_file_hash="H-VA2",
                    registration_date="2021-01-01T00:00:00Z",
                ),
                clerk,
            ),
            201,
        )
        assert by_clerk["registration_status"] == "ACTIVE", (
            "PRD §3.1: registration_status accepts ACTIVE when omitted"
        )
        assert by_clerk["county_id"] == alpha["id"]

        moved = validate_success(
            api_client.set_voter_registration_status(
                by_admin["id"], registration_status_payload("INACTIVE"), clerk
            )
        )
        assert moved["registration_status"] == "INACTIVE"

        rows, meta = validate_paginated(
            api_client.list_voter_records(clerk, params={"county_id": alpha["id"]})
        )
        assert {row["id"] for row in rows} == {by_admin["id"], by_clerk["id"]}
        assert meta["total_count"] == 2
