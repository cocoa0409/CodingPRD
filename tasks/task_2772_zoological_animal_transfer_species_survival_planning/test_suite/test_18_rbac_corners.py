"""Role exclusivity, shared reads and the veterinary segregation of duties."""

from __future__ import annotations

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_SEGREGATION_OF_DUTIES,
                                     ERR_UNAUTHORIZED)
from test_helpers.test_users import (make_coordinator_headers,
                                     make_registrar_headers, make_vet_headers)


class TestRoleExclusiveOperations:
    """Some endpoints admit exactly one role."""

    def test_a_registrar_may_not_register_a_species_programme(self, api):
        """The role gate fires before the body is looked at at all.

        PRD: "A value outside that set of four, or a value inside the set that is
        not listed among the authorized roles for the endpoint being called, is
        refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/registrar_cannot_create_a_species_program
        """
        world = fx.register_institutions(api)
        response = api.create_species_program(
            f.species_program_payload(), make_registrar_headers(world.sender_id)
        )
        validate_error(response, ERR_UNAUTHORIZED)
        _, meta = validate_paginated(api.list_species_programs(world.admin))
        assert meta["total_count"] == 0

    def test_the_coordinating_body_may_not_endorse_its_own_directive(self, api):
        """Raising a directive and endorsing it are split across two roles.

        PRD: "A directive from the coordinating body has no effect on an animal
        until the institution responsible for that animal endorses it. Endorsement
        is a registrar's act, and which registrar is entitled to perform it depends
        on the directive"

        Design: Corner/rbac/program_coordinator_cannot_endorse_its_own_recommendation
        """
        world = fx.base_world(api)
        animal = fx.accession(world, world.sender_id, "CR-101", "MALE",
                              "2019-05-10", 12.45)
        world.m1_id = animal["id"]
        fx.propose_recommendation(world, recommendation_type="HOLD",
                                  paired_animal_id=None)
        response = api.endorse_recommendation(world.rec_id, world.coordinator)
        validate_error(response, ERR_UNAUTHORIZED)
        assert world.read_recommendation()["status"] == "PROPOSED"
        assert world.read_program()["open_recommendation_count"] == 1


class TestSharedReadOperations:
    """Every read endpoint admits all four roles and redacts nothing."""

    def test_all_four_roles_read_the_same_animal_row(self, api):
        """Admin, coordinator, registrar and veterinarian see identical fields.

        PRD: "The authorized roles for each endpoint are given in the §4 table;
        every read endpoint in the system admits all four roles."

        Design: Corner/rbac/every_role_can_read_the_animal_register
        """
        world = fx.base_world(api, publish=False)
        animal = fx.accession(world, world.sender_id, "CR-101", "MALE",
                              "2019-05-10", 12.45)
        vet = validate_success(
            api.create_veterinarian(
                f.veterinarian_payload(world.sender_id, full_name="Dr A Vance",
                                       license_number="CA-VET-0001"),
                make_registrar_headers(world.sender_id),
            ),
            201,
        )
        readers = [
            world.admin,
            make_coordinator_headers(world.program_id),
            make_registrar_headers(world.sender_id),
            make_vet_headers(vet["id"]),
        ]
        rows = [validate_success(api.get_animal(animal["id"], headers))
                for headers in readers]
        for row in rows:
            assert row["id"] == animal["id"]
            assert row["local_id"] == "CR-101"
            assert row["location_status"] == "HELD"
            assert row["version"] == 1
        assert all(row == rows[0] for row in rows)


class TestSegregationOfDuties:
    """The veterinarian who drew the blood may not sign the certificate."""

    def test_the_collecting_veterinarian_may_not_sign_the_certificate(self, api):
        """The signature is refused ahead of the licence and panel checks.

        PRD: "Duties are segregated: the veterinarian who collected any
        pre-shipment test for this agreement may not be the veterinarian who signs
        its certificate, and the attempt is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/collecting_vet_cannot_sign_the_same_agreements_health_certificate
        """
        world = fx.world_with_executed_agreement(api)
        fx.record_panel(world, codes=["TB"], collecting_vet_id=world.vet_a_id)
        world.set_clock(fx.CLOCK_DOCUMENTS)
        certificate = fx.open_certificate(world,
                                          issuing_veterinarian_id=world.vet_a_id)
        assert certificate["status"] == "DRAFT"

        response = api.decide_document(
            world.cvi_id,
            f.document_decision_payload(outcome="ISSUE",
                                        document_number="CA-CVI-2026-0001"),
            make_vet_headers(world.vet_a_id),
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)
        stored = world.read_document(world.cvi_id)
        assert stored["status"] == "DRAFT"
        assert stored["document_number"] is None
        assert stored["valid_until"] is None
        assert world.read_agreement()["status"] == "EXECUTED"
