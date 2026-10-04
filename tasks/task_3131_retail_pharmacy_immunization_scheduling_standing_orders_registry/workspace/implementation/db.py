"""In-memory data store and logical clock. Starts empty on every boot."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.stores = {}            # PharmacyStore
        self.state_protocols = {}   # StateProtocol
        self.vaccine_products = {}  # VaccineProduct
        self.patients = {}          # Patient
        self.insurance_plans = {}   # InsurancePlan
        self.lots = {}              # VaccineLot
        self.temperature_readings = {}  # TemperatureReading
        self.appointments = {}      # ImmunizationAppointment
        self.questionnaires = {}    # PrescreeningQuestionnaire (keyed by questionnaire id)
        self.immunization_records = {}  # ImmunizationRecord
        self.registry_submissions = {}  # RegistrySubmission
        self.observation_sessions = {}  # ObservationSession
        self.clinic_events = {}     # ClinicEvent
        # Logical clock — starts at 2026-09-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


DB = Store()
