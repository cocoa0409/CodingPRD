"""Reachability of the authentication, scope, party and existence errors."""

from __future__ import annotations

from prd_bench_local_runner.testing import (NON_EXISTENT_UUID,
                                            build_user_headers, validate_error,
                                            validate_paginated)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_ACTOR_SCOPE_VIOLATION,
                                     ERR_INSTITUTION_NOT_FOUND,
                                     ERR_NOT_A_PARTY_TO_AGREEMENT,
                                     ERR_UNAUTHENTICATED)
from test_helpers.assertions import assert_slot_counts
from test_helpers.constants import ROLE_REGISTRAR
from test_helpers.test_users import make_registrar_headers


class TestAuthenticationGate:
    """An empty identity header is treated exactly as an absent one."""

    def test_an_empty_user_id_is_refused_before_anything_else_is_examined(
            self, api):
        """A listing that would have returned a row is refused with 401 instead.

        PRD: "If either header is absent or present but empty, the request is
        refused with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about
        the request is examined — including whether the target resource exists."

        Design: Corner/errors/empty_x_user_id_header_returns_unauthenticated
        """
        fx.register_institutions(api)
        response = api.list_institutions(build_user_headers("", ROLE_REGISTRAR))
        validate_error(response, ERR_UNAUTHENTICATED)
        body = response.json()
        assert body["response_type"] == "error"
        assert "id" not in body["data"]


class TestActorScope:
    """A registrar's reach stops at its own collection."""

    def test_a_registrar_may_not_accession_into_another_institution(self, api):
        """Cedar Ridge's registrar cannot accession an animal held at Harbor Bay.

        PRD: "a registrar accessions animals only into its own collection, files
        studbook submissions only under its own `institution_id`, and acts on a
        transfer agreement only when its `X-User-ID` is one of that agreement's
        two parties."

        Design: Corner/errors/registrar_cannot_accession_an_animal_for_another_institution
        """
        world = fx.base_world(api, publish=False)
        response = api.create_animal(
            f.animal_payload(world.program_id, world.receiver_id,
                             local_id="HB-201", sex="FEMALE",
                             birth_date="2020-03-15",
                             founder_representation_pct=30.00),
            make_registrar_headers(world.sender_id),
        )
        validate_error(response, ERR_ACTOR_SCOPE_VIOLATION)
        _, meta = validate_paginated(api.list_animals(world.admin))
        assert meta["total_count"] == 0
        assert_slot_counts(world.read_institution(world.receiver_id), 0, 0)


class TestPartyToTheAgreement:
    """A stranger to the agreement cannot negotiate on it."""

    def test_a_third_institution_may_not_open_the_offer(self, api):
        """Northgate's registrar is refused although it is accredited and in role.

        PRD: "An institution that is party to neither side hears
        `ERR_NOT_A_PARTY_TO_AGREEMENT` (HTTP 403) instead, and so does a receiving
        institution that tries to make the opening offer out of `DRAFT`, which is
        reserved to the sender."

        Design: Corner/errors/outside_registrar_cannot_offer_an_agreement_it_is_not_party_to
        """
        world = fx.base_pair(api, with_outsider=True)
        fx.endorsed_recommendation(world)
        fx.draft_agreement(world)
        response = api.offer_agreement(world.ta_id, world.outsider,
                                       f.terms_payload(10.0))
        validate_error(response, ERR_NOT_A_PARTY_TO_AGREEMENT)
        agreement = world.read_agreement()
        assert agreement["status"] == "DRAFT"
        assert agreement["round_number"] == 0
        assert float(agreement["transport_cost_share_pct"]) == 51.0


class TestExistenceOfBodyForeignKeys:
    """A body key naming no row is a 404 for that kind."""

    def test_an_unknown_owning_institution_is_reported_as_institution_not_found(
            self, api):
        """The existence rung fires ahead of the scope rule the same body breaks.

        PRD: "Each miss produces the 404 that names the missing kind:
        `ERR_SPECIES_PROGRAM_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`,
        `ERR_VETERINARIAN_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`"

        Design: Corner/errors/unknown_institution_in_the_animal_body_returns_institution_not_found
        """
        world = fx.base_world(api, publish=False)
        response = api.create_animal(
            f.animal_payload(world.program_id, world.sender_id,
                             owning_institution_id=NON_EXISTENT_UUID),
            make_registrar_headers(world.sender_id),
        )
        validate_error(response, ERR_INSTITUTION_NOT_FOUND)
        _, meta = validate_paginated(api.list_animals(world.admin))
        assert meta["total_count"] == 0
