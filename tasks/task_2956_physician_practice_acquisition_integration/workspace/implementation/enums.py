"""Enumerated input domains (PRD section 3)."""

SPECIALTIES = ("PRIMARY_CARE", "CARDIOLOGY", "ORTHOPEDICS", "ONCOLOGY")
STRUCTURES = ("ASSET", "EQUITY")
POLICY_FORMS = ("CLAIMS_MADE", "OCCURRENCE")
READINESS_POSTURES = ("BLOCKED", "AT_RISK", "READY")
EMPLOYMENT_STATUSES = ("PROSPECTIVE", "OFFERED", "EMPLOYED", "DECLINED")

OPINION_TYPES = ("FMV", "COMMERCIAL_REASONABLENESS")
VALUATION_METHODS = ("INCOME_APPROACH", "MARKET_APPROACH", "NARRATIVE")
CR_CONCLUSIONS = ("REASONABLE", "NOT_REASONABLE")

MODEL_TYPES = ("STRAIGHT_SALARY", "WRVU_PRODUCTIVITY", "BASE_PLUS_INCENTIVE")
STARK_EXCEPTIONS = ("BONA_FIDE_EMPLOYMENT", "PERSONAL_SERVICE_ARRANGEMENT",
                    "NONE")
BENCHMARK_BASES = ("TOTAL_CASH_COMP", "COMP_PER_WRVU")

PAYER_TYPES = ("COMMERCIAL", "MANAGED_MEDICARE", "MEDICARE", "MEDICAID")
CONTRACT_FORMS = ("ASSIGNABLE", "CONSENT_REQUIRED", "NON_ASSIGNABLE")

SOURCE_SYSTEMS = ("ATHENA", "ECLINICALWORKS", "PAPER_CHART")
CHART_TYPES = ("STRUCTURED", "IMAGING", "SCANNED_DOCUMENT")

ROLE_CODES = ("MA", "RN", "FRONT_DESK", "BILLER", "PRACTICE_MANAGER")

CONVERSION_TYPES = ("PROVIDER_BASED_DEPARTMENT", "FREESTANDING_CLINIC")

TASK_CODES = ("HR_STAFFING_PLAN", "PAYER_CREDENTIALING", "IT_DATA_MIGRATION",
              "REVENUE_CYCLE_GO_LIVE", "COMPLIANCE_TRAINING",
              "PATIENT_NOTIFICATION")
TASK_DOMAINS = ("HR", "REVENUE_CYCLE", "IT", "COMPLIANCE", "CLINICAL")

LIABILITY_CATEGORIES = ("MALPRACTICE_TAIL", "PAYER_REFUND_EXPOSURE",
                        "EQUIPMENT_LEASE", "UNPAID_PTO",
                        "STARK_SELF_DISCLOSURE")

# Role lists per endpoint group (PRD section 4 endpoint table).
ROLES_ACQUISITION_READ = ("DealLead", "ValuationAnalyst", "ComplianceOfficer",
                          "CompensationDesigner", "IntegrationManager")
ROLES_PHYSICIAN_READ = ("DealLead", "ValuationAnalyst", "ComplianceOfficer",
                        "CompensationDesigner", "IntegrationManager",
                        "PracticePhysician")
ROLES_OPINION_READ = ("ValuationAnalyst", "ComplianceOfficer", "DealLead")
ROLES_PLAN_READ = ("CompensationDesigner", "ComplianceOfficer", "DealLead",
                   "PracticePhysician")
ROLES_INTEGRATION_READ = ("IntegrationManager", "DealLead", "ComplianceOfficer")
ROLES_PACKAGE_READ = ("IntegrationManager", "DealLead", "ComplianceOfficer",
                      "PracticePhysician")
ROLES_LIABILITY_READ = ("DealLead", "ComplianceOfficer", "IntegrationManager")
ROLES_REPORT_READ = ("IntegrationManager", "ComplianceOfficer", "DealLead",
                     "PracticePhysician")

ROLES_CLOCK = ("IntegrationManager", "DealLead", "ComplianceOfficer")
ROLES_DEAL_LEAD = ("DealLead",)
ROLES_COMPLIANCE = ("ComplianceOfficer",)
ROLES_ANALYST = ("ValuationAnalyst",)
ROLES_DESIGNER = ("CompensationDesigner",)
ROLES_MANAGER = ("IntegrationManager",)
ROLES_OPINION_ACTION = ("ValuationAnalyst", "ComplianceOfficer")
ROLES_PLAN_ACTION = ("CompensationDesigner", "ComplianceOfficer",
                     "PracticePhysician")
ROLES_TASK_CREATE = ("IntegrationManager", "DealLead")
ROLES_TASK_ACTION = ("IntegrationManager", "ComplianceOfficer")
