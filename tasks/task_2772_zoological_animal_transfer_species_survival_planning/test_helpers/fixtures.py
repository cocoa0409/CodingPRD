"""Composite setup helpers.

The server is restarted before every test, so each helper builds its
preconditions from scratch through published endpoints only. The helpers are
layered: every later stage takes the object returned by the earlier one, so a
test asks for exactly the depth of world it needs.

Canonical timeline used by the journey helpers:

  2026-08-01T00:00:00Z  the logical clock's opening value: institutions,
                        programme, animals, veterinarians, recommendation,
                        agreement, offer and accept
  2026-08-10T09:00:00Z  execute
  2026-08-20T09:00:00Z  health certificate and permit, exam date 2026-08-20
  2026-08-25T09:00:00Z  crate-training sessions, booking, quarantine, confirm
  2026-09-01T08:00:00Z  departure
  2026-09-01T20:00:00Z  arrival
  2026-10-01T09:00:00Z  quarantine clearance on the thirtieth day
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .assertions import days_after
from .test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_registrar_headers,
    make_vet_headers,
)

CLOCK_EXECUTE = "2026-08-10T09:00:00Z"
CLOCK_DOCUMENTS = "2026-08-20T09:00:00Z"
CLOCK_PRESHIPMENT = "2026-08-25T09:00:00Z"
CLOCK_DEPARTURE = "2026-09-01T08:00:00Z"
CLOCK_ARRIVAL = "2026-09-01T20:00:00Z"
CLOCK_CLEARANCE = "2026-10-01T09:00:00Z"

EXAM_DATE = "2026-08-20"
COLLECTED_ON = "2026-08-05"
CRATE_SESSION_DATES = ("2026-08-21", "2026-08-22", "2026-08-23", "2026-08-24",
                       "2026-08-25")
DEPARTURE_UTC = "2026-09-01T08:00:00Z"
ARRIVAL_UTC = "2026-09-01T20:00:00Z"
QUARANTINE_START = "2026-09-01"
QUARANTINE_END = "2026-10-05"


@dataclass
class World:
    """Everything a test needs to address the world it just built."""

    api: Any
    sender_id: str = ""
    receiver_id: str = ""
    outsider_id: str = ""
    program_id: str = ""
    program_type: str = "SSP_RED"
    m1_id: str = ""
    m1_version: int = 0
    f1_id: str = ""
    f1_version: int = 0
    vet_a_id: str = ""
    vet_b_id: str = ""
    vet_c_id: str = ""
    vet_d_id: str = ""
    vet_e_id: str = ""
    rec_id: str = ""
    ta_id: str = ""
    ta_version: int = 0
    booking_id: str = ""
    occupancy_id: str = ""
    protocol_id: str = ""
    cvi_id: str = ""
    permit_id: str = ""
    test_ids: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    # ----------------------------------------------------------- headers
    @property
    def admin(self) -> Dict[str, str]:
        return make_admin_headers()

    @property
    def coordinator(self) -> Dict[str, str]:
        return make_coordinator_headers(self.program_id)

    @property
    def sender(self) -> Dict[str, str]:
        return make_registrar_headers(self.sender_id)

    @property
    def receiver(self) -> Dict[str, str]:
        return make_registrar_headers(self.receiver_id)

    @property
    def outsider(self) -> Dict[str, str]:
        return make_registrar_headers(self.outsider_id)

    @property
    def vet_a(self) -> Dict[str, str]:
        return make_vet_headers(self.vet_a_id)

    @property
    def vet_b(self) -> Dict[str, str]:
        return make_vet_headers(self.vet_b_id)

    @property
    def vet_c(self) -> Dict[str, str]:
        return make_vet_headers(self.vet_c_id)

    @property
    def vet_d(self) -> Dict[str, str]:
        return make_vet_headers(self.vet_d_id)

    @property
    def vet_e(self) -> Dict[str, str]:
        return make_vet_headers(self.vet_e_id)

    # ------------------------------------------------------------ reads
    def read_institution(self, institution_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_institution(institution_id, self.admin)
        )

    def read_program(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_species_program(self.program_id, self.admin)
        )

    def read_animal(self, animal_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_animal(animal_id or self.m1_id, self.admin)
        )

    def read_recommendation(self, rec_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_recommendation(rec_id or self.rec_id, self.admin)
        )

    def read_agreement(self, ta_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_agreement(ta_id or self.ta_id, self.admin)
        )

    def read_document(self, document_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_document(document_id, self.admin))

    def read_booking(self, booking_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_booking(booking_id or self.booking_id, self.admin)
        )

    def read_occupancy(self, occupancy_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_quarantine_occupancy(
                occupancy_id or self.occupancy_id, self.admin
            )
        )

    def read_protocol(self, protocol_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_protocol(protocol_id or self.protocol_id, self.admin)
        )

    def read_submission(self, submission_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_studbook_submission(submission_id, self.admin)
        )

    # ------------------------------------------------------------ clock
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, self.admin))


# ------------------------------------------------------------------ stage 1
def register_institutions(api, sender_overrides: Optional[Dict] = None,
                          receiver_overrides: Optional[Dict] = None,
                          with_outsider: bool = False) -> World:
    """Register the sending and receiving institutions (and a third if asked)."""
    world = World(api=api)
    admin = make_admin_headers()
    sender = get_success_data(
        api.create_institution(
            f.sender_institution_payload(**(sender_overrides or {})), admin
        )
    )
    world.sender_id = sender["id"]
    receiver = get_success_data(
        api.create_institution(
            f.receiver_institution_payload(**(receiver_overrides or {})), admin
        )
    )
    world.receiver_id = receiver["id"]
    if with_outsider:
        outsider = get_success_data(
            api.create_institution(f.outsider_institution_payload(), admin)
        )
        world.outsider_id = outsider["id"]
    return world


def base_world(api, program_type: str = "SSP_RED", publish: bool = True,
               sender_overrides: Optional[Dict] = None,
               receiver_overrides: Optional[Dict] = None,
               program_overrides: Optional[Dict] = None,
               with_outsider: bool = False) -> World:
    """Two institutions plus a species programme, published by default."""
    world = register_institutions(api, sender_overrides, receiver_overrides,
                                  with_outsider)
    program = get_success_data(
        api.create_species_program(
            f.species_program_payload(program_type=program_type,
                                      **(program_overrides or {})),
            world.admin,
        )
    )
    world.program_id = program["id"]
    world.program_type = program.get("program_type", program_type)
    if publish:
        get_success_data(api.publish_plan(world.program_id, world.coordinator))
    return world


def accession(world: World, holder_id: str, local_id: str, sex: str,
              birth_date: str, founder_representation_pct: float,
              **overrides: Any) -> Dict[str, Any]:
    """Accession one animal into the named holder's collection."""
    return get_success_data(
        world.api.create_animal(
            f.animal_payload(
                world.program_id, holder_id, local_id=local_id, sex=sex,
                birth_date=birth_date,
                founder_representation_pct=founder_representation_pct,
                **overrides,
            ),
            make_registrar_headers(holder_id),
        )
    )


def base_pair(api, **kwargs: Any) -> World:
    """The canonical pair: M1 held by the sender, F1 held by the receiver."""
    world = base_world(api, **kwargs)
    m1 = accession(world, world.sender_id, "CR-101", "MALE", "2019-05-10", 12.45)
    world.m1_id, world.m1_version = m1["id"], m1["version"]
    f1 = accession(world, world.receiver_id, "HB-201", "FEMALE", "2020-03-15", 30.00)
    world.f1_id, world.f1_version = f1["id"], f1["version"]
    return world


def register_veterinarians(world: World) -> World:
    """Five veterinarians: four at the sender, one at the receiver.

    Dr A Vega and Dr B Sund both hold active Californian licences, and only
    Dr B Sund carries the federal category a certificate for an international
    transfer must be signed under. Dr C Iyer holds an active Texan licence at
    the receiving institution, Dr D Fell's Californian licence has lapsed, and
    Dr E Marsh is employed by the sender under a Nevadan licence.
    """
    api = world.api
    vet_a = get_success_data(
        api.create_veterinarian(
            f.veterinarian_payload(world.sender_id, full_name="Dr A Vega",
                                   license_number="CA-VET-1001",
                                   license_jurisdiction="US-CA",
                                   license_status="ACTIVE",
                                   usda_accreditation_category="CATEGORY_I"),
            world.sender,
        )
    )
    world.vet_a_id = vet_a["id"]
    vet_b = get_success_data(
        api.create_veterinarian(
            f.veterinarian_payload(world.sender_id, full_name="Dr B Sund",
                                   license_number="CA-VET-1002",
                                   license_jurisdiction="US-CA",
                                   license_status="ACTIVE",
                                   usda_accreditation_category="CATEGORY_II"),
            world.sender,
        )
    )
    world.vet_b_id = vet_b["id"]
    vet_c = get_success_data(
        api.create_veterinarian(
            f.veterinarian_payload(world.receiver_id, full_name="Dr C Iyer",
                                   license_number="TX-VET-2001",
                                   license_jurisdiction="US-TX",
                                   license_status="ACTIVE",
                                   usda_accreditation_category="CATEGORY_I"),
            world.receiver,
        )
    )
    world.vet_c_id = vet_c["id"]
    vet_d = get_success_data(
        api.create_veterinarian(
            f.veterinarian_payload(world.sender_id, full_name="Dr D Fell",
                                   license_number="CA-VET-1003",
                                   license_jurisdiction="US-CA",
                                   license_status="LAPSED",
                                   usda_accreditation_category="CATEGORY_II"),
            world.sender,
        )
    )
    world.vet_d_id = vet_d["id"]
    vet_e = get_success_data(
        api.create_veterinarian(
            f.veterinarian_payload(world.sender_id, full_name="Dr E Marsh",
                                   license_number="NV-VET-3001",
                                   license_jurisdiction="US-NV",
                                   license_status="ACTIVE",
                                   usda_accreditation_category="CATEGORY_II"),
            world.sender,
        )
    )
    world.vet_e_id = vet_e["id"]
    return world


# ------------------------------------------------------------------ stage 2
def propose_recommendation(world: World, analysis_mode: str = "PEDIGREE_ONLY",
                           recommendation_type: str = "BREED_WITH",
                           subject_animal_id: Optional[str] = None,
                           paired_animal_id: Optional[str] = "__default__",
                           **overrides: Any) -> Dict[str, Any]:
    """Raise one recommendation against the published plan."""
    subject = subject_animal_id or world.m1_id
    subject_row = world.read_animal(subject)
    paired = world.f1_id if paired_animal_id == "__default__" else paired_animal_id
    payload = f.recommendation_payload(
        world.program_id,
        subject,
        subject_row["version"],
        recommendation_type=recommendation_type,
        paired_animal_id=paired,
        sending_institution_id=world.sender_id if paired else None,
        receiving_institution_id=world.receiver_id if paired else None,
        analysis_mode=analysis_mode,
        **overrides,
    )
    data = get_success_data(
        world.api.create_recommendation(payload, world.coordinator)
    )
    world.rec_id = data["id"]
    return data


def endorsed_recommendation(world: World, analysis_mode: str = "PEDIGREE_ONLY",
                            **overrides: Any) -> Dict[str, Any]:
    """Raise the recommendation and have the sending institution endorse it."""
    propose_recommendation(world, analysis_mode=analysis_mode, **overrides)
    return get_success_data(
        world.api.endorse_recommendation(world.rec_id, world.sender)
    )


def draft_agreement(world: World, **overrides: Any) -> Dict[str, Any]:
    """Open the transfer agreement in DRAFT against the endorsed recommendation."""
    data = get_success_data(
        world.api.create_agreement(
            f.agreement_payload(world.rec_id, world.m1_id, world.sender_id,
                                world.receiver_id, **overrides),
            world.sender,
        )
    )
    world.ta_id, world.ta_version = data["id"], data["version"]
    return data


def offered_agreement(world: World, transport_cost_share_pct: float = 51.0,
                      **overrides: Any) -> Dict[str, Any]:
    """Put the opening offer on the table."""
    data = get_success_data(
        world.api.offer_agreement(
            world.ta_id, world.sender,
            f.terms_payload(transport_cost_share_pct, **overrides),
        )
    )
    world.ta_version = data["version"]
    return data


def accepted_agreement(world: World) -> Dict[str, Any]:
    """The receiving institution accepts the standing offer."""
    data = get_success_data(world.api.accept_agreement(world.ta_id, world.receiver))
    world.ta_version = data["version"]
    return data


def executed_agreement(world: World,
                       execute_clock: Optional[str] = CLOCK_EXECUTE,
                       execution_note: str = "Executed") -> Dict[str, Any]:
    """Execute the accepted agreement, optionally moving the clock first."""
    if execute_clock:
        world.set_clock(execute_clock)
    data = get_success_data(
        world.api.execute_agreement(world.ta_id, world.sender,
                                    {"execution_note": execution_note})
    )
    world.ta_version = data["version"]
    return data


def world_with_accepted_agreement(api, analysis_mode: str = "PEDIGREE_ONLY",
                                  agreement_overrides: Optional[Dict] = None,
                                  **kwargs: Any) -> World:
    """Institutions, programme, pair, veterinarians and an ACCEPTED agreement."""
    world = base_pair(api, **kwargs)
    register_veterinarians(world)
    endorsed_recommendation(world, analysis_mode=analysis_mode)
    draft_agreement(world, **(agreement_overrides or {}))
    offered_agreement(world)
    accepted_agreement(world)
    return world


def world_with_executed_agreement(api, analysis_mode: str = "PEDIGREE_ONLY",
                                  agreement_overrides: Optional[Dict] = None,
                                  execute_clock: Optional[str] = CLOCK_EXECUTE,
                                  **kwargs: Any) -> World:
    """The same world, carried through execution."""
    world = world_with_accepted_agreement(
        api, analysis_mode=analysis_mode,
        agreement_overrides=agreement_overrides, **kwargs
    )
    executed_agreement(world, execute_clock=execute_clock)
    return world


# ------------------------------------------------------------------ stage 3
def record_panel(world: World, codes: Optional[List[str]] = None,
                 collecting_vet_id: Optional[str] = None,
                 collected_on: str = COLLECTED_ON,
                 result: str = "NEGATIVE") -> Dict[str, str]:
    """Record pre-shipment tests, collected by a veterinarian of the sender.

    Dr A Vega collects by default so that Dr B Sund remains free to sign the
    health certificate.
    """
    vet_id = collecting_vet_id or world.vet_a_id
    panel = codes if codes is not None else ["TB", "BRUCELLA"]
    for index, code in enumerate(panel):
        data = get_success_data(
            world.api.create_pre_shipment_test(
                f.pre_shipment_test_payload(
                    world.ta_id, world.m1_id, vet_id, test_code=code,
                    collected_on=collected_on, result=result,
                    lab_reference=f"LAB-{code}-{index + 1:04d}",
                ),
                make_vet_headers(vet_id),
            )
        )
        world.test_ids[code] = data["id"]
    return world.test_ids


def open_certificate(world: World, issuing_veterinarian_id: Optional[str] = None,
                     exam_date: str = EXAM_DATE, **overrides: Any) -> Dict[str, Any]:
    """Open a DRAFT health certificate naming its signing veterinarian."""
    data = get_success_data(
        world.api.create_document(
            f.cvi_payload(world.ta_id,
                          issuing_veterinarian_id or world.vet_b_id,
                          exam_date=exam_date, **overrides),
            world.sender,
        )
    )
    world.cvi_id = data["id"]
    return data


def issue_certificate(world: World, issuing_veterinarian_id: Optional[str] = None,
                      exam_date: str = EXAM_DATE,
                      document_number: str = "CA-CVI-2026-0001") -> Dict[str, Any]:
    """Open the health certificate and have its named veterinarian sign it."""
    vet_id = issuing_veterinarian_id or world.vet_b_id
    open_certificate(world, issuing_veterinarian_id=vet_id, exam_date=exam_date)
    return get_success_data(
        world.api.decide_document(
            world.cvi_id,
            f.document_decision_payload(outcome="ISSUE",
                                        document_number=document_number),
            make_vet_headers(vet_id),
        )
    )


def issue_permit(world: World, document_type: str = "STATE_IMPORT_PERMIT",
                 issuing_authority_name: str = "Texas Animal Health Commission",
                 document_number: str = "TX-IMP-2026-0001",
                 valid_until: str = "2026-12-31") -> Dict[str, Any]:
    """Open a permit application and have the accrediting body issue it."""
    data = get_success_data(
        world.api.create_document(
            f.permit_payload(world.ta_id, document_type=document_type,
                             issuing_authority_name=issuing_authority_name),
            world.sender,
        )
    )
    world.permit_id = data["id"]
    return get_success_data(
        world.api.decide_document(
            world.permit_id,
            f.document_decision_payload(outcome="ISSUE",
                                        document_number=document_number,
                                        valid_until=valid_until),
            world.admin,
        )
    )


def crate_train(world: World, animal_id: Optional[str] = None,
                session_dates: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Record crate-training sessions for the animal."""
    target = animal_id or world.m1_id
    dates = list(session_dates if session_dates is not None else CRATE_SESSION_DATES)
    rows = []
    for index, session_date in enumerate(dates):
        rows.append(
            get_success_data(
                world.api.create_crate_training_session(
                    target,
                    f.crate_training_session_payload(
                        session_date=session_date,
                        trainer_name="T Rios",
                        duration_minutes=25 + index,
                    ),
                    make_registrar_headers(world.sender_id),
                )
            )
        )
    return rows


def schedule_quarantine(world: World, quarantine_room_code: str = "Q-ROOM-1",
                        scheduled_start_date: str = QUARANTINE_START,
                        scheduled_end_date: str = QUARANTINE_END,
                        institution_id: Optional[str] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """Reserve a quarantine room at the receiving institution."""
    holder = institution_id or world.receiver_id
    data = get_success_data(
        world.api.create_quarantine_occupancy(
            f.quarantine_payload(world.ta_id, holder, world.m1_id,
                                 quarantine_room_code=quarantine_room_code,
                                 scheduled_start_date=scheduled_start_date,
                                 scheduled_end_date=scheduled_end_date,
                                 **overrides),
            make_registrar_headers(holder),
        )
    )
    world.occupancy_id = data["id"]
    return data


def book_transport(world: World, departure_utc: str = DEPARTURE_UTC,
                   arrival_utc: str = ARRIVAL_UTC,
                   carrier_code: str = "AVI-CARGO-7",
                   crate_serial: str = "CR-CRATE-001",
                   temp_min_c: float = 10.0, temp_max_c: float = 24.0,
                   agreement_id: Optional[str] = None,
                   expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Book temperature-controlled transport for the executed agreement."""
    ta_id = agreement_id or world.ta_id
    version = (expected_version if expected_version is not None
               else world.read_agreement(ta_id)["version"])
    data = get_success_data(
        world.api.create_booking(
            f.booking_payload(ta_id, version, carrier_code=carrier_code,
                              crate_serial=crate_serial,
                              departure_utc=departure_utc,
                              arrival_utc=arrival_utc,
                              temp_min_c=temp_min_c, temp_max_c=temp_max_c),
            world.sender,
        )
    )
    if ta_id == world.ta_id:
        world.booking_id = data["id"]
    return data


def world_ready_to_confirm(api, exam_date: str = EXAM_DATE,
                           collected_on: str = COLLECTED_ON,
                           panel: Optional[List[str]] = None,
                           with_permit: bool = True,
                           with_quarantine: bool = True,
                           crate_session_dates: Optional[List[str]] = None,
                           departure_utc: str = DEPARTURE_UTC,
                           arrival_utc: str = ARRIVAL_UTC,
                           **kwargs: Any) -> World:
    """An executed interstate agreement with every confirmation condition met.

    The panel is complete and negative, the health certificate and the state
    import permit are issued, five crate-training sessions have been logged
    within a fortnight of departure, transport is booked and a quarantine room
    is reserved at the receiver for the arrival window.
    """
    world = world_with_executed_agreement(api, **kwargs)
    record_panel(world, codes=panel, collected_on=collected_on)
    world.set_clock(CLOCK_DOCUMENTS)
    issue_certificate(world, exam_date=exam_date)
    if with_permit:
        issue_permit(world)
    world.set_clock(CLOCK_PRESHIPMENT)
    crate_train(world, session_dates=crate_session_dates)
    book_transport(world, departure_utc=departure_utc, arrival_utc=arrival_utc)
    if with_quarantine:
        schedule_quarantine(world)
    return world


def confirm_transport(world: World) -> Dict[str, Any]:
    """Confirm the booking."""
    return get_success_data(
        world.api.confirm_booking(world.booking_id, world.sender)
    )


def depart(world: World, clock: Optional[str] = CLOCK_DEPARTURE) -> Dict[str, Any]:
    """Record departure, optionally moving the clock to the departure instant."""
    if clock:
        world.set_clock(clock)
    return get_success_data(world.api.depart_booking(world.booking_id, world.sender))


def deliver(world: World, temperature_samples: Optional[List[float]] = None,
            clock: Optional[str] = CLOCK_ARRIVAL) -> Dict[str, Any]:
    """Record arrival with the journey's temperature log."""
    if clock:
        world.set_clock(clock)
    return get_success_data(
        world.api.deliver_booking(
            world.booking_id,
            f.delivery_payload(temperature_samples),
            world.receiver,
        )
    )


def world_delivered(api, temperature_samples: Optional[List[float]] = None,
                    **kwargs: Any) -> World:
    """Carry the journey all the way to a delivered animal in active quarantine."""
    world = world_ready_to_confirm(api, **kwargs)
    confirm_transport(world)
    depart(world)
    deliver(world, temperature_samples=temperature_samples)
    return world


def clear_quarantine(world: World, clock: Optional[str] = CLOCK_CLEARANCE,
                     clearing_vet_id: Optional[str] = None) -> Dict[str, Any]:
    """Release the animal from quarantine, signed off by a receiver's vet."""
    if clock:
        world.set_clock(clock)
    vet_id = clearing_vet_id or world.vet_c_id
    return get_success_data(
        world.api.clear_quarantine(world.occupancy_id, make_vet_headers(vet_id),
                                   f.quarantine_clear_payload())
    )


def world_cleared(api, **kwargs: Any) -> World:
    """A delivered animal whose quarantine has been cleared on its thirtieth day."""
    world = world_delivered(api, **kwargs)
    clear_quarantine(world)
    return world


def open_protocol(world: World, resident_group_code: str = "SNOW-LEOPARD-A",
                  **overrides: Any) -> Dict[str, Any]:
    """Open a behavioural introduction protocol at the receiving institution."""
    data = get_success_data(
        world.api.create_protocol(
            f.protocol_payload(world.ta_id, world.m1_id, world.receiver_id,
                               resident_group_code=resident_group_code,
                               **overrides),
            world.receiver,
        )
    )
    world.protocol_id = data["id"]
    return data


def world_with_protocol(api, **kwargs: Any) -> World:
    """A cleared animal with an open introduction protocol at HOWDY."""
    world = world_cleared(api, **kwargs)
    open_protocol(world)
    return world


def observe(world: World, aggression_level: str = "CALM",
            protocol_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """Record one behavioural observation against the protocol."""
    return get_success_data(
        world.api.create_observation(
            protocol_id or world.protocol_id,
            f.observation_payload(aggression_level=aggression_level, **overrides),
            world.receiver,
        )
    )


def advance_one_stage(world: World) -> Dict[str, Any]:
    """Three calm sessions at the current stage, which advances the protocol."""
    observe(world, "CALM")
    observe(world, "CALM")
    return observe(world, "CALM")


def file_studbook_submission(world: World, submission_type: str = "BIRTH",
                             reporting_period_end: str = "2026-07-15",
                             **overrides: Any) -> Dict[str, Any]:
    """File one studbook submission for the sending institution."""
    return get_success_data(
        world.api.create_studbook_submission(
            f.studbook_submission_payload(
                world.program_id, world.sender_id,
                submission_type=submission_type,
                reporting_period_end=reporting_period_end, **overrides,
            ),
            world.sender,
        )
    )


def review_studbook_submission(world: World, submission_id: str,
                               outcome: str = "ACCEPT",
                               review_note: str = "clean") -> Dict[str, Any]:
    """The coordinating body reviews the submission."""
    return get_success_data(
        world.api.review_studbook_submission(
            submission_id,
            f.studbook_review_payload(outcome=outcome, review_note=review_note),
            world.coordinator,
        )
    )


def world_with_parallel_agreements(api, count: int = 3,
                                   execute_clock: Optional[str] = CLOCK_EXECUTE,
                                   **kwargs: Any) -> World:
    """Several fully independent agreements, all EXECUTED in one plan cycle.

    Every agreement gets its own pair of animals and its own recommendation, so
    none of them supersedes another. All the recommendations are raised before
    any of the executions run, which keeps the programme published throughout.
    """
    world = base_world(api, **kwargs)
    register_veterinarians(world)
    pairs = []
    for index in range(count):
        male = accession(world, world.sender_id, f"CR-10{index + 1}", "MALE",
                         "2019-05-10", 12.45)
        female = accession(world, world.receiver_id, f"HB-20{index + 1}",
                           "FEMALE", "2020-03-15", 30.00)
        pairs.append((male, female))

    recommendations = []
    for male, female in pairs:
        current = get_success_data(api.get_animal(male["id"], world.admin))
        rec = get_success_data(
            api.create_recommendation(
                f.recommendation_payload(
                    world.program_id, male["id"], current["version"],
                    paired_animal_id=female["id"],
                    sending_institution_id=world.sender_id,
                    receiving_institution_id=world.receiver_id,
                ),
                world.coordinator,
            )
        )
        get_success_data(api.endorse_recommendation(rec["id"], world.sender))
        recommendations.append(rec)

    agreements = []
    for (male, _female), rec in zip(pairs, recommendations):
        agreement = get_success_data(
            api.create_agreement(
                f.agreement_payload(rec["id"], male["id"], world.sender_id,
                                    world.receiver_id),
                world.sender,
            )
        )
        get_success_data(api.offer_agreement(agreement["id"], world.sender,
                                             f.terms_payload(51.0)))
        get_success_data(api.accept_agreement(agreement["id"], world.receiver))
        agreements.append(agreement)

    if execute_clock:
        world.set_clock(execute_clock)
    executed = []
    for agreement in agreements:
        executed.append(
            get_success_data(
                api.execute_agreement(agreement["id"], world.sender,
                                      {"execution_note": "Executed"})
            )
        )

    world.m1_id, world.m1_version = pairs[0][0]["id"], pairs[0][0]["version"]
    world.f1_id, world.f1_version = pairs[0][1]["id"], pairs[0][1]["version"]
    world.rec_id = recommendations[0]["id"]
    world.ta_id = executed[0]["id"]
    world.ta_version = executed[0]["version"]
    world.extra["pairs"] = pairs
    world.extra["recommendations"] = recommendations
    world.extra["agreements"] = executed
    return world


def reopen_cycle_with_open_recommendation(world: World) -> Dict[str, Any]:
    """Reopen the closed cycle and leave one open BREED_WITH directive standing.

    Publishing a programme that has reached CYCLE_CLOSED reopens it as the next
    cycle, and a fresh directive raised in that cycle keeps the open count at
    one until something declines it.
    """
    api = world.api
    get_success_data(api.publish_plan(world.program_id, world.coordinator))
    current = world.read_animal(world.m1_id)
    rec = get_success_data(
        api.create_recommendation(
            f.recommendation_payload(
                world.program_id, world.m1_id, current["version"],
                paired_animal_id=world.f1_id,
                sending_institution_id=world.sender_id,
                receiving_institution_id=world.receiver_id,
            ),
            world.coordinator,
        )
    )
    world.extra["reopened_rec"] = rec
    return rec


__all__ = [name for name in dir() if not name.startswith("_")]
