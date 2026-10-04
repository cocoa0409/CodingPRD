# Federal-Aid Highway Project Authorization & Reimbursement API — Product Requirements Document

## 1. Introduction

Under the Federal-Aid Highway Program, federal dollars do not flow to states as grants paid in advance; they are apportioned by funding category, obligated project-by-project against executed federal-aid agreements, and reimbursed only after a state certifies eligible expenditures and federal reviewers confirm them. This API operationalizes that reimbursement lifecycle end to end: a state builds its Statewide Transportation Improvement Program (STIP) under fiscal-constraint and public-involvement rules, nominates projects into it, obtains federal eligibility determinations whose cost-share percentages vary by program, highway system, safety activity, and federal land ownership, clears environmental review and right-of-way certification, and only then receives a project authorization that obligates federal funds.

From authorization onward, the system enforces competitive-bidding discipline with Disadvantaged Business Enterprise (DBE) goals, progress billing through vouchers with per-line eligibility review, cost-overrun change orders subject to a statutory federal participation cap, and a closeout audit that can claw back ineligible reimbursements before deobligating the remaining balance. Duties are deliberately segregated: state programming staff, state engineering staff, the FHWA division administrator, and FHWA review staff each own distinct steps, and several transitions refuse to let one operator perform both sides of a check. All statutory waiting periods — public comment windows, advertisement periods, audit response windows — are measured against a controllable logical clock rather than wall-clock time, so that every temporal gate in the program is deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's capacity. The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `StateDOTPlanner`, `StateDOTEngineer`, `FHWADivisionAdmin`, and `FHWAReviewer`. A request whose `X-User-Role` header is missing or does not name one of these five roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

All five roles are opaque identities. When `X-User-Role` is `PlatformAdmin`, `StateDOTPlanner`, `StateDOTEngineer`, `FHWADivisionAdmin`, or `FHWAReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires an attribution trail — for example `submitted_by_user_id` and `decided_by_user_id` on a Voucher, `decided_by_user_id` on a ProjectClearance, `requested_by_user_id` and `state_concurred_by_user_id` on a ChangeOrder, and `auditor_user_id` on an Audit — and the segregation-of-duties checks described later compare those recorded identifiers for inequality. The server never compares `X-User-ID` against any resource's `id` for ownership purposes.

The `PlatformAdmin` is the benchmark operator: it alone drives the logical clock and registers funding program configuration. The `StateDOTPlanner` builds the STIP, shepherds public involvement, and nominates and patches projects. The `StateDOTEngineer` opens clearances, advertises projects and opens bids, runs progress billing, and requests change orders. The `FHWADivisionAdmin` records apportionments, decides STIP approvals, determines project eligibility, and authorizes projects. The `FHWAReviewer` decides clearances, concurs on awards with DBE review, decides vouchers and change orders at the federal level, and conducts audits through closeout. All five roles may use every read endpoint and may record public comments on a STIP.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Every list response is sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock, the Federal Fiscal Year, and Timestamp Rendering

The system never consults wall-clock time. A logical clock governs every duration gate in the program — comment windows, the advertisement period, the audit response window, and the fiscal-year cell an authorization draws against. Before any operator advances it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin`-only capability advances the clock by supplying a `current_utc` instant; once set, all subsequent gate evaluations read the new time. All business endpoints are mounted under `/federal-aid`; the clock capability is the sole platform endpoint mounted outside that prefix.

Two timestamp rendering families exist, and the distinction is contractual. System-managed bookkeeping timestamps — `created_at`, `updated_at`, and the envelope's `api_request_timestamp` — always render as ISO 8601 UTC with exactly three fractional digits, for example `2026-09-01T00:00:00.000Z`. Domain timestamps whose value is copied from the logical clock — `comment_period_opened_at`, `advertised_on_date`, `findings_issued_at`, and the `closed_at` fields — render exactly as the logical clock reads at the moment they are stamped, for example `2026-09-01T00:00:00Z`. Client-supplied domain datetimes such as a voucher's `period_start_date` and `period_end_date` are stored and returned as supplied.

The federal fiscal year (FFY) runs from October 1 through September 30. A calendar date falling in October through December of year Y belongs to FFY Y+1; a date falling in January through September of year Y belongs to FFY Y. Every `federal_fiscal_year` field in the system is an integer interpreted by this rule, and the server uses the same rule to derive the FFY of the current logical clock when selecting an apportionment cell.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix; clients never supply it. The `created_at` and `updated_at` timestamps follow the three-fractional-digit rendering rule of §2.4; `updated_at` refreshes on every mutation of the resource, including mutations caused by a cascaded side effect originating on another resource. The `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation, again including cascaded ones. The PublicComment resource is the single exception: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.6. Money, Cost Shares, and Rounding Discipline

All monetary quantities are integer cents — `apportioned_cents`, `obligated_cents`, `available_cents`, `total_estimated_cost_cents`, `initial_obligated_cents`, `reimbursed_cents`, `repaid_cents`, `bid_amount_cents`, `delta_cost_cents`, `claimed_amount_cents`, `eligible_amount_cents`, `federal_reimbursable_cents`, `federal_participation_cents`, `cumulative_change_order_federal_cents`, `ineligible_amount_cents`, `final_eligible_federal_share_cents`, `repayment_due_cents`, `provisional_federal_estimate_cents`, and `total_programmed_federal_cents` are all whole-cent integers, never decimals.

Federal cost shares are fractions between 0 and 1. A determined or provisional share is rounded half-up to four decimal places. Wherever a share is applied to a cents amount, the product is rounded half-up to whole cents. One rounding-order rule is pinned because the two plausible orders disagree: voucher reimbursement rounds each line to whole cents first and only then sums. Summing first and rounding once is forbidden — at a share of 0.90 applied to two lines of 105 cents each, the mandated per-line order yields 95 + 95 = 190 cents, while sum-then-round would yield 189.

### 2.7. Validation Order and Error Selection

Every request is evaluated against a fixed succession of checks. When several checks would fail on the same request, the check earliest in this succession produces the response; later failures are masked, not reported alongside. The succession is:

1. Authentication: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED` (401).
2. Authorization: an authenticated role outside the endpoint's role list yields `ERR_FORBIDDEN` (403).
3. Existence: resource identifiers in the URL path must resolve, validated left to right; the first unresolvable identifier yields `ERR_NOT_FOUND` (404). Foreign-key fields inside request bodies follow §2.9's placement rule.
4. Body well-formedness: required fields present, enums in range, amounts positive where required, voucher `line_items` non-empty, `period_end_date` strictly after `period_start_date`, and the clearance conditional-field rule — any violation yields `ERR_INVALID_REQUEST` (400).
5. Optimistic concurrency: a stale `expected_project_version` on a project update yields `ERR_STALE_VERSION` (412).
6. State gate: the target resource must be in a valid from-state for the requested action, else `ERR_INVALID_STATE` (409).
7. Cross-entity program state: the owning STIP must be `APPROVED` for eligibility determination and authorization, else `ERR_STIP_NOT_APPROVED` (409).
8. Project eligibility at authorization, else `ERR_PROJECT_NOT_ELIGIBLE` (409).
9. Authorization obligation status for voucher and change-order intake, else `ERR_AUTHORIZATION_NOT_OBLIGATED` (409).
10. The environmental clearance leg of the authorization gate, else `ERR_ENVIRONMENTAL_NOT_CLEARED` (409).
11. The right-of-way certification leg, at authorization and again at final-voucher approval, else `ERR_ROW_NOT_CERTIFIED` (409).
12. Segregation of duties on change-order concurrence and audit creation, else `ERR_SEGREGATION_OF_DUTIES` (422).
13. Voucher documentation certification, else `ERR_DOCUMENTATION_INCOMPLETE` (422).
14. The DBE goal at award, else `ERR_DBE_GOAL_NOT_MET` (422).
15. Public involvement sufficiency at STIP submission, else `ERR_PUBLIC_INVOLVEMENT_INCOMPLETE` (422).
16. The STIP comment window and the EIS comment window, else `ERR_COMMENT_PERIOD_OPEN` (409).
17. The advertisement window, else `ERR_ADVERTISEMENT_PERIOD_SHORT` (409).
18. The audit findings response window, else `ERR_AUDIT_RESPONSE_WINDOW_OPEN` (409).
19. Billing period overlap, else `ERR_BILLING_PERIOD_OVERLAP` (409).
20. STIP coverage overlap, else `ERR_STIP_PERIOD_OVERLAP` (409).
21. Apportionment cell uniqueness, else `ERR_DUPLICATE_APPORTIONMENT` (409).
22. Clearance-kind uniqueness, else `ERR_CLEARANCE_KIND_EXISTS` (409).
23. Final-voucher uniqueness, else `ERR_FINAL_VOUCHER_EXISTS` (409).
24. Open change orders blocking a final voucher, else `ERR_OPEN_CHANGE_ORDERS` (409).
25. The responsive-bid pool must be non-empty, else `ERR_NO_RESPONSIVE_BIDS` (422).
26. The named bid must belong to the project and be responsive, else `ERR_BID_NOT_RESPONSIVE` (422).
27. The named bid must be the lowest responsive bid, else `ERR_AWARD_NOT_LOWEST_RESPONSIVE` (422).
28. Activity eligibility under the funding program, else `ERR_INELIGIBLE_ACTIVITY` (422).
29. An apportionment cell must exist for the current FFY at authorization, else `ERR_NO_APPORTIONMENT_FOR_FFY` (422).
30. Cell availability must cover an obligation or change-order draw, else `ERR_APPORTIONMENT_EXCEEDED` (422).
31. Forward-looking fiscal constraint at STIP approval, else `ERR_FISCAL_CONSTRAINT_VIOLATED` (422).
32. A repayment may not exceed the outstanding amount due, else `ERR_REPAYMENT_EXCEEDS_DUE` (422).

Two consequences of this ordering deserve emphasis because they decide which error a multi-defect request returns. At STIP submission, the participation check (15) outranks the window check (16): a submission made too early that also has too few comments reports `ERR_PUBLIC_INVOLVEMENT_INCOMPLETE`. At award, the DBE check (14) outranks the entire bid-pool family (25–27): a payload with a DBE shortfall and a defective named bid reports `ERR_DBE_GOAL_NOT_MET`.

### 2.8. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: the project update operation requires a non-optional `expected_project_version` field carrying the client's last observed `version` of the Project. If that value does not equal the Project's current `version` — for instance because another writer patched the estimate, or an award or change-order cascade advanced the version since the client last read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.9. Nested Resource Retrieval and Foreign-Key Placement

When an endpoint path contains resource identifiers — a STIP id on its comment collection, a project id on its clearances, bids, or audits listings, an authorization id on its vouchers or change-orders listings — the identifiers are validated from left to right, and the first one that does not resolve to an existing resource yields `ERR_NOT_FOUND` (404) before any further processing.

Foreign-key fields inside request bodies are placed deliberately in the validation succession. On action endpoints (operations that drive a state transition on a path-addressed resource), body foreign keys are validated after the target resource's state gate: a wrong-state action reports `ERR_INVALID_STATE`, not a body foreign-key 404. On plain creation endpoints, body foreign keys are validated before all business rules, so an unresolvable `project_id`, `stip_id`, `funding_program_id`, or `authorization_id` in a creation payload yields `ERR_NOT_FOUND` ahead of any domain check.

### 2.10. The Apportionment Ledger and Cross-Aggregate Invariants

The Apportionment is the system's ledger cell: one row per (funding program, state, federal fiscal year) triple, holding the `apportioned_cents` Congress has made available and the `obligated_cents` the agency has committed against it. One invariant holds at all times and is auditable: `available_cents` always equals `apportioned_cents` minus `obligated_cents`. The cell is recomputed on every obligation, on every approved change-order draw, and on every closeout deobligation.

A second invariant governs closeout: when an authorization closes, its `reimbursed_cents` minus its `repaid_cents` equals the audit's `final_eligible_federal_share_cents`, so the ledger's net federal outlay always reconciles to the audited eligible share. Cascades that mutate several resources in one operation — a voucher approval touching its authorization and project, an audit close touching the authorization, the apportionment, and the project — refresh `updated_at` and increment `version` on every resource they mutate.

## 3. Business Logic & Workflows

### 3.1. Funding Programs and Apportionment Cells

A `PlatformAdmin` registers each federal-aid funding category as a FundingProgram, supplying a `code`, a human-readable `name`, and the `eligible_activity_codes` array enumerating which work types the program may fund. The `code` is one of `NHPP`, `STBG`, `HSIP`, `CMAQ`, or `TAP`. Every entry in `eligible_activity_codes` must be one of the six recognized activity codes — `ROAD_RESURFACING`, `BRIDGE_REPLACEMENT`, `SIGNAGE_LIGHTING`, `GUARDRAIL_INSTALL`, `PEDESTRIAN_CROSSING`, or `TRANSIT_EXPANSION` — and an out-of-range entry fails body validation with `ERR_INVALID_REQUEST`. The server, not the client, fixes each program's statutory base share: `base_federal_share_pct` is computed from the program code as 0.80 for `NHPP`, 0.80 for `STBG`, 0.90 for `HSIP`, 0.80 for `CMAQ`, and 0.80 for `TAP`; any share value the client supplies is ignored.

With programs registered, an `FHWADivisionAdmin` records annual apportionments. Each Apportionment names its `funding_program_id`, the two-letter `state_code` receiving the funds, the `federal_fiscal_year` of the cell (an integer interpreted per the FFY rule of §2.4), and the `apportioned_cents` made available, which may be zero but never negative. A system-enforced `uniqueness` constraint permits at most one Apportionment per (program, state, FFY) triple: a second create for an existing cell is rejected with `ERR_DUPLICATE_APPORTIONMENT` (409). On creation `obligated_cents` is 0 and `available_cents` equals `apportioned_cents`; thereafter both are computed fields under the invariant of §2.10, `obligated_cents` accumulating authorizations and change-order draws that are not yet closed and `available_cents` refreshing on every obligation, draw, and deobligation. The apportionments listing accepts optional `funding_program_id`, `state_code`, and `federal_fiscal_year` filters alongside the standard pagination parameters.

### 3.2. Programming the STIP and the Public Involvement Cycle

A `StateDOTPlanner` opens a StateProgram — the STIP — by supplying the `state_code`, the `state_federal_land_pct` (the fraction of the state's land area under federal ownership, a value from 0 to 1 inclusive on both ends, which later drives the sliding-scale share adjustment of §3.3), the `start_federal_fiscal_year` of the program, and a narrative `description`. The STIP spans four federal fiscal years: `end_federal_fiscal_year` is computed as the start year plus three. Coverage windows are closed intervals that include both their first and last fiscal years, and two STIPs for the same `state_code` may not intersect: a new STIP whose window shares even a single boundary fiscal year with an existing STIP of the same state is rejected with `ERR_STIP_PERIOD_OVERLAP` (409), while strictly disjoint windows are allowed.

A new STIP opens directly in `PUBLIC_INVOLVEMENT`, with `comment_period_opened_at` stamped from the logical clock and `amendment_count` at 0. While in this status, any authenticated role may record a PublicComment carrying an `author_name` and free-text `comment_text`; the comment's `stip_id` comes from the collection it is posted under, and its `created_at` is taken from the logical clock. Commenting on a STIP that is no longer in `PUBLIC_INVOLVEMENT` is rejected with `ERR_INVALID_STATE`.

Submission moves the STIP from `PUBLIC_INVOLVEMENT` to `SUBMITTED` and is gated by two checks, evaluated in the priority order of §2.7 — participation first, then the window. The public record must contain at least 1 comment whose `created_at` is on or after `comment_period_opened_at`, else `ERR_PUBLIC_INVOLVEMENT_INCOMPLETE` (422). And the logical clock must have reached at least 30 days after the window opened — a submission at exactly 30 days elapsed passes — else `ERR_COMMENT_PERIOD_OPEN` (409).

An `FHWADivisionAdmin` then decides the `SUBMITTED` STIP by supplying a `decision`. A `decision` of `REJECT` returns the STIP to `PUBLIC_INVOLVEMENT` without resetting `comment_period_opened_at` and preserving existing comments, so a window that had already elapsed permits immediate resubmission. A `decision` of `APPROVE` runs the forward-looking fiscal-constraint check before allowing `SUBMITTED` to become `APPROVED`. For each funding program used by the STIP's counted projects — those with `status` in `NOMINATED`, `ELIGIBLE`, `AUTHORIZED`, `BIDDING`, `BIDS_OPENED`, `UNDER_CONSTRUCTION`, or `COMPLETE` — the check sums those projects' `provisional_federal_estimate_cents` into a programmed total, and compares it against the program's remaining capacity: the sum, over every Apportionment row for that program and this STIP's `state_code` whose fiscal year falls within the STIP's four-year span (missing cells contribute 0), of `apportioned_cents` minus `obligated_cents`. Programmed must not exceed capacity, with equality passing; if any single program fails, the whole approval is rejected with `ERR_FISCAL_CONSTRAINT_VIOLATED` (422). The same counted-project sum is exposed on the STIP as `total_programmed_federal_cents`. Note the deliberate asymmetry with the authorization-time check of §3.5: the approval check is forward-looking across the full four-year span and all programmed projects, so it can fail on Apportionment rows that still show room for a single current-year obligation.

The STIP lifecycle is cyclic, forming the amendment loop `APPROVED` → `PUBLIC_INVOLVEMENT` → `SUBMITTED` → `APPROVED`. A `StateDOTPlanner` may reopen an `APPROVED` STIP for amendment explicitly; additionally, the system cascades the same reopening automatically whenever a new project is nominated into an `APPROVED` STIP (§3.3). Either path sets the status back to `PUBLIC_INVOLVEMENT`, restamps `comment_period_opened_at` from the current logical clock so a fresh comment window opens, and increments `amendment_count` by 1. While the STIP sits in `PUBLIC_INVOLVEMENT`, eligibility determination and authorization on its projects fail with `ERR_STIP_NOT_APPROVED` until the loop closes again.

### 3.3. Project Nomination, Estimate Maintenance, and the Two Federal-Share Variants

A `StateDOTPlanner` nominates a Project into a STIP with a payload carrying the `stip_id` and `funding_program_id` it belongs under, a `route_name`, a `description`, the `activity_code` (one of the six activity codes of §3.1), an `is_interstate_system` flag, the `dbe_goal_pct` contract goal as a fraction from 0 to 1 inclusive, and the `total_estimated_cost_cents`, which must be strictly greater than zero. Nomination is accepted regardless of STIP status; however, when the target STIP is `APPROVED`, the nomination cascades the amendment reopening of §3.2 — the STIP returns to `PUBLIC_INVOLVEMENT` with a fresh comment window and an incremented `amendment_count`. The new Project starts in `NOMINATED` with `advertised_on_date`, `awarded_bid_id`, and `determined_federal_share_pct` all null. The projects listing accepts optional `stip_id`, `funding_program_id`, and `status` filters.

Two federal-share values live on every Project, computed by two pinned variants of one determination algorithm. The **statutory-base variant** runs at creation and on every cost-changing patch: `provisional_federal_share_pct` is exactly the program's base share — 0.80 for `NHPP`, `STBG`, `CMAQ`, and `TAP`; 0.90 for `HSIP` — with no interstate bump, no safety override, and no land adjustment; `provisional_federal_estimate_cents` is the product of `total_estimated_cost_cents` and that share, rounded half-up to whole cents. The **adjusted-full variant** runs once, at eligibility determination, and pins `determined_federal_share_pct`. Its branch chain has a fixed evaluation order — interstate bump first, safety override second, land sliding scale third only when the override does not fire:

- Begin with the program's base share (0.80 for `NHPP`, `STBG`, `CMAQ`, `TAP`; 0.90 for `HSIP`).
- If `is_interstate_system` is true, add a bump of 0.10, capping the result at 0.90 — so every Interstate System project lands at exactly 0.90, including `HSIP` projects whose 0.90 base cannot rise past the cap.
- If the program is `HSIP` and the `activity_code` is one of `SIGNAGE_LIGHTING`, `GUARDRAIL_INSTALL`, or `PEDESTRIAN_CROSSING`, the share is 1.00 in full. This safety override wins outright: the land adjustment below is discarded entirely.
- Otherwise, when the owning STIP's `state_federal_land_pct` is strictly greater than 0.05 (a state at exactly 0.05 receives no adjustment), the base slides toward the 0.95 cap: it becomes the lesser of 0.95 and the base plus the product of (0.95 minus the base) and `state_federal_land_pct`.

The resulting share is rounded half-up to four decimal places. Because the provisional variant ignores every adjustment, the provisional and determined shares diverge whenever any of the bump, override, or sliding scale applies — and it is the provisional value alone that feeds the STIP fiscal-constraint check of §3.2.

While a Project is `NOMINATED` or `ELIGIBLE`, the `StateDOTPlanner` may patch its `description`, `total_estimated_cost_cents`, or `dbe_goal_pct`. This is the one OCC-guarded write in the system (§2.8): the payload must carry `expected_project_version`, and a mismatch with the Project's current `version` is rejected with `ERR_STALE_VERSION` (412). A successful patch increments `version` by 1, and a change to `total_estimated_cost_cents` recomputes `provisional_federal_estimate_cents` through the statutory-base variant. Patching a Project in any other status is rejected with `ERR_INVALID_STATE`.

Eligibility determination belongs to the `FHWADivisionAdmin`, acts only on a `NOMINATED` Project (any other status yields `ERR_INVALID_STATE`), and first requires the owning STIP to be `APPROVED`, else `ERR_STIP_NOT_APPROVED` (409). A `determination` of `INELIGIBLE` moves the Project to the terminal `INELIGIBLE` status with no further checks. A `determination` of `ELIGIBLE` additionally requires the `activity_code` to be a member of the funding program's `eligible_activity_codes`, else `ERR_INELIGIBLE_ACTIVITY` (422); on success it pins `determined_federal_share_pct` from the adjusted-full variant and moves the Project to `ELIGIBLE`.

### 3.4. Environmental Review and Right-of-Way Certification

Before federal funds can be obligated, a Project must hold two regulatory clearances, each opened by a `StateDOTEngineer` as a ProjectClearance while the Project is `ELIGIBLE` — opening one against a Project in any other status is rejected with `ERR_INVALID_STATE`. The payload carries the `project_id`, a `kind` of `ENVIRONMENTAL` or `RIGHT_OF_WAY`, and, for the environmental leg only, a `nepa_class` of `CE`, `EA`, or `EIS`. The conditional-field rule is strict: `nepa_class` is required when `kind` is `ENVIRONMENTAL` and must be null when `kind` is `RIGHT_OF_WAY`; either violation is a body-shape failure rejected with `ERR_INVALID_REQUEST`. Only one non-`REJECTED` clearance may exist per (project, kind) pair: a second open or cleared clearance of the same kind is rejected with `ERR_CLEARANCE_KIND_EXISTS` (409). A clearance opens in `SUBMITTED`.

An `FHWAReviewer` decides a `SUBMITTED` clearance by supplying a `decision`. A `decision` of `REJECT` moves the clearance to the terminal `REJECTED` status; because the uniqueness rule counts only non-`REJECTED` rows, a replacement clearance of the same kind may then be created. A `decision` of `CLEARED` carries two kind-specific gates. For an environmental clearance whose `nepa_class` is `EIS`, the logical clock must have reached at least 45 days after the clearance's `created_at` — exactly 45 days passes — else `ERR_COMMENT_PERIOD_OPEN` (409); `CE` and `EA` classes carry no waiting period. For a right-of-way clearance, the decide payload must include a `row_cert_level` of `LEVEL_1_FULL` or `LEVEL_2_CONDITIONAL`, and its absence is a body-shape failure with `ERR_INVALID_REQUEST`; on success the level is recorded on the clearance. Either decision stamps `decided_by_user_id` with the caller's `X-User-ID`, and `CLEARED` is terminal alongside `REJECTED`. For right-of-way clearances, `CLEARED` means certified; the `row_cert_level` recorded at that point later decides whether a final voucher may be approved (§3.7).

### 3.5. Authorization: Obligating Federal Funds Against the Current-Year Cell

Authorization is the fiscal heart of the program: an `FHWADivisionAdmin` supplies the `project_id`, the `agreement_number` to be recorded in the project agreement, and the `initial_obligated_cents`, strictly greater than zero. The checks fire in the §2.7 succession — the owning STIP must be `APPROVED` (`ERR_STIP_NOT_APPROVED`), the Project must be `ELIGIBLE` (`ERR_PROJECT_NOT_ELIGIBLE`, which also locks out the terminal `INELIGIBLE` status), the Project must hold a `CLEARED` environmental clearance (`ERR_ENVIRONMENTAL_NOT_CLEARED`, 409), and a `CLEARED` right-of-way certification (`ERR_ROW_NOT_CERTIFIED`, 409). Because authorization requires `ELIGIBLE` and the first successful authorization moves the Project to `AUTHORIZED`, a second authorization against the same Project fails with `ERR_PROJECT_NOT_ELIGIBLE` — at most one active Authorization per Project, enforced structurally.

The fiscal leg then resolves the apportionment cell: the server selects the unique Apportionment matching the Project's funding program, the owning STIP's `state_code`, and the FFY of the current logical clock, and records it as the Authorization's `apportionment_id`. If no such row exists, the authorization is rejected with `ERR_NO_APPORTIONMENT_FOR_FFY` (422). This is the chronological-committed availability check: only posted obligations count. The cell's `available_cents` — `apportioned_cents` minus `obligated_cents` — must cover `initial_obligated_cents`, with equality passing; a shortfall is rejected with `ERR_APPORTIONMENT_EXCEEDED` (422). Planned but unauthorized projects are ignored here, in deliberate contrast to the STIP-approval check of §3.2.

On success, the Authorization is created in `OBLIGATED` status. The agreement terms pin `federal_share_pct` as a snapshot of the Project's `determined_federal_share_pct` at this instant; later program or project changes never alter it. `obligated_cents` starts at `initial_obligated_cents`; `reimbursed_cents`, `repaid_cents`, and `cumulative_change_order_federal_cents` start at 0; `closed_at` is null. The same operation draws on the ledger — the cell's `obligated_cents` grows by `initial_obligated_cents` and `available_cents` is recomputed — and advances the Project from `ELIGIBLE` to `AUTHORIZED`. The authorizations listing accepts optional `project_id`, `status`, and `apportionment_id` filters.

The Authorization has one non-obvious cyclic edge. When a voucher approval raises `reimbursed_cents` to exactly `obligated_cents`, the system moves the Authorization from `OBLIGATED` to `FULLY_DRAWN`, and from that point voucher creation and submission against it fail with `ERR_AUTHORIZATION_NOT_OBLIGATED`. A later change-order approval that raises `obligated_cents` above `reimbursed_cents` returns it from `FULLY_DRAWN` to `OBLIGATED`, reopening billing. The terminal `CLOSED` status arrives only through the closeout cascade of §3.9.

### 3.6. Advertisement, Bid Opening, and Award with DBE Review

Once `AUTHORIZED`, a `StateDOTEngineer` advertises the Project, which stamps `advertised_on_date` from the logical clock and moves the Project from `AUTHORIZED` to `BIDDING`. Sealed bids may be opened only after the statutory advertisement window: the logical clock must have reached at least 21 days after `advertised_on_date` — exactly 21 days passes — else `ERR_ADVERTISEMENT_PERIOD_SHORT` (409).

The open-bids call carries a `bids` payload: a non-empty array, since an empty array fails body validation with `ERR_INVALID_REQUEST`. Each entry supplies a `contractor_name`, a `bid_amount_cents` strictly greater than zero, and an `is_responsive` flag. The server creates one Bid per entry, in `SUBMITTED` status, with `project_id` taken from the path and `submission_seq` set to the entry's 0-based position in the payload array — a value that matters, because it is the only tie-break the award knows. The Project moves from `BIDDING` to `BIDS_OPENED`, and its bids listing returns the Bid rows in `submission_seq` order.

Award belongs to the `FHWAReviewer`, whose payload names a `bid_id`, declares a `dbe_commitment_pct`, and may set `good_faith_effort_documented`. The winner is determined by a pinned selection rule: among this project's Bid rows that are responsive and still `SUBMITTED`, order by `bid_amount_cents` ascending, breaking ties by `submission_seq` ascending — the earlier array position wins, and resource ids are never consulted. The validation succession of §2.7 gives the award its distinctive ordering: the DBE check (priority 14) outranks the bid family, so a payload failing both reports `ERR_DBE_GOAL_NOT_MET`. Within the bid family, the checks fire in this order — the pool must contain at least one responsive bid, else `ERR_NO_RESPONSIVE_BIDS` (422), a check evaluated before the named bid is inspected; the named `bid_id` must reference a Bid of this project with `is_responsive` true, else `ERR_BID_NOT_RESPONSIVE` (422); and the named bid must be the winner under the selection rule, else `ERR_AWARD_NOT_LOWEST_RESPONSIVE` (422). Independently, the declared `dbe_commitment_pct` must be at least the Project's `dbe_goal_pct` — equality passes — unless `good_faith_effort_documented` is true, which excuses any shortfall; otherwise the award is rejected with `ERR_DBE_GOAL_NOT_MET` (422).

A successful award moves the winning Bid from `SUBMITTED` to `AWARDED`, moves every other Bid of the project to `NOT_AWARDED` (both terminal statuses for a Bid), records the winner on the Project's `awarded_bid_id`, and moves the Project from `BIDS_OPENED` to `UNDER_CONSTRUCTION`.

### 3.7. Progress Billing: Vouchers, Review, and Reimbursement

Progress billing runs through Vouchers created by a `StateDOTEngineer` against an authorization of an `UNDER_CONSTRUCTION` Project. The creation payload carries the `authorization_id`, the `period_start_date` and `period_end_date` bounding the billing period, a `line_items` array, a `documentation_complete` certification flag, and an `is_final` flag marking the voucher that closes construction billing. The period is half-open: it includes its start instant and excludes its end instant, so `period_end_date` must be strictly after `period_start_date`. `line_items` must be a non-empty array whose entries each carry a `description` and an `eligible_amount_cents` strictly greater than zero. Creation requires the Project to be `UNDER_CONSTRUCTION`, else `ERR_INVALID_STATE`, and the Authorization to be `OBLIGATED`, else `ERR_AUTHORIZATION_NOT_OBLIGATED` — a `FULLY_DRAWN` or `CLOSED` authorization takes no new vouchers. At most one non-`REJECTED` final voucher may exist per authorization: creating a second with `is_final` true is rejected with `ERR_FINAL_VOUCHER_EXISTS` (409). A new Voucher starts in `DRAFT` with `claimed_amount_cents` computed as the sum of the lines' `eligible_amount_cents`, `resubmission_count` at 0, and `eligible_amount_cents`, `federal_reimbursable_cents`, `ineligible_line_indexes`, and `decided_by_user_id` all null until review. An authorization's vouchers listing returns them under the standard pagination rules.

Submission moves a `DRAFT` voucher to `UNDER_REVIEW`; the same action also resubmits a `REJECTED` voucher, in which case the payload may carry revised `period_start_date`, `period_end_date`, `line_items`, or `documentation_complete` values that replace the stored ones, with `claimed_amount_cents` recomputed and `resubmission_count` incremented by 1. Either way, `submitted_by_user_id` is restamped with the caller's `X-User-ID`, and the same four checks run against the (possibly revised) values, in §2.7 order: the voucher must be in a submittable state and the Project `UNDER_CONSTRUCTION` (`ERR_INVALID_STATE`); the Authorization must be `OBLIGATED` (`ERR_AUTHORIZATION_NOT_OBLIGATED`); `documentation_complete` must be true, the state's certification that supporting documentation is complete, else `ERR_DOCUMENTATION_INCOMPLETE` (422); and the half-open period must not intersect the period of any non-`REJECTED` sibling voucher on the same authorization, else `ERR_BILLING_PERIOD_OVERLAP` (409) — adjacency is allowed, so one voucher's period ending exactly where the next begins is not an overlap.

An `FHWAReviewer` decides an `UNDER_REVIEW` voucher with a `decision` of `APPROVE` or `REJECT`. Rejection moves the voucher to `REJECTED`, stamps `decided_by_user_id`, posts no reimbursement, and leaves the resubmission path above open — `REJECTED` is not terminal for a voucher; `APPROVED` is. Approval accepts an optional `ineligible_line_indexes` array striking individual lines; each entry must be a valid 0-based index into `line_items`, else `ERR_INVALID_REQUEST`. Two extra gates guard approval of a voucher whose `is_final` is true: the Project's right-of-way clearance must be `CLEARED` with `row_cert_level` equal to `LEVEL_1_FULL` — a final voucher under a `LEVEL_2_CONDITIONAL` certification is rejected with `ERR_ROW_NOT_CERTIFIED` (409) — and no ChangeOrder of the same authorization may sit in `REQUESTED` or `STATE_CONCURRED`, else `ERR_OPEN_CHANGE_ORDERS` (409); per §2.7 the certification check outranks the change-order check when both fail.

Approval computes the reimbursement with the pinned rounding order of §2.6. The approved lines are `line_items` with the struck indexes removed; the voucher's `eligible_amount_cents` becomes the sum of the approved lines' `eligible_amount_cents`. Each approved line contributes its own federal share — the line's `eligible_amount_cents` multiplied by the Authorization's pinned `federal_share_pct`, rounded half-up to whole cents — and `federal_reimbursable_cents` is the lesser of that per-line sum and the Authorization's remaining obligation (`obligated_cents` minus `reimbursed_cents`), so a voucher can never overdraw the agreement. The cascade then fires in three links: the Authorization's `reimbursed_cents` grows by `federal_reimbursable_cents`; if that raises `reimbursed_cents` to exactly `obligated_cents`, the Authorization moves from `OBLIGATED` to `FULLY_DRAWN`; and if the voucher's `is_final` is true, the Project moves from `UNDER_CONSTRUCTION` to `COMPLETE`. The voucher itself lands in `APPROVED` with `decided_by_user_id` recorded.

### 3.8. Cost Overruns and Change Orders

When field conditions push costs beyond the agreement, a `StateDOTEngineer` requests a ChangeOrder against an authorization of an `UNDER_CONSTRUCTION` Project — a wrong project state yields `ERR_INVALID_STATE` — supplying the `authorization_id`, a `description`, and the `delta_cost_cents` increase, strictly greater than zero. Unlike voucher intake, change-order creation accepts an authorization in either `OBLIGATED` or `FULLY_DRAWN` status, precisely so that a fully drawn agreement can be reopened; a `CLOSED` authorization is rejected with `ERR_AUTHORIZATION_NOT_OBLIGATED`. The new ChangeOrder starts in `REQUESTED` with `requested_by_user_id` stamped from the caller and `federal_participation_cents` null until federal approval.

Segregation of duties governs the next step: a `StateDOTEngineer` provides state concurrence, moving the ChangeOrder from `REQUESTED` to `STATE_CONCURRED`, but the concurring operator's `X-User-ID` must differ from `requested_by_user_id` — the same operator on both sides is rejected with `ERR_SEGREGATION_OF_DUTIES` (422). The concurrence stamps `state_concurred_by_user_id`.

The federal decision belongs to the `FHWAReviewer`. A `decision` of `REJECT` moves the ChangeOrder to the terminal `FEDERAL_REJECTED` status and posts nothing. A `decision` of `APPROVE` computes the federal participation in four pinned steps, because each approved order bounds the next one's room and orders must therefore be resolved in approval order (earliest created first whenever approval order matters to a reader): first, the eligible amount is the `delta_cost_cents` multiplied by the Authorization's pinned `federal_share_pct`, rounded half-up to whole cents; second, the program-wide overrun cap is the Authorization's `initial_obligated_cents` multiplied by 0.20, rounded half-up to whole cents; third, the room remaining under that cap is the cap minus the Authorization's `cumulative_change_order_federal_cents`, which excludes this order; fourth, `federal_participation_cents` is the eligible amount clamped to that room — the lesser of the two, floored at zero. The draw must then fit the apportionment cell: the cell's `available_cents` must cover the computed participation, with equality passing, else `ERR_APPORTIONMENT_EXCEEDED` (422).

Approval cascades widely. The ChangeOrder moves to the terminal `FEDERAL_APPROVED` status with `federal_participation_cents` recorded. The Authorization's `obligated_cents` grows by the participation, and its `cumulative_change_order_federal_cents` grows by the same amount; if the Authorization was `FULLY_DRAWN`, the new headroom returns it to `OBLIGATED`. The apportionment cell's `obligated_cents` grows by the participation and `available_cents` is recomputed per the §2.10 invariant. Finally, the Project's `total_estimated_cost_cents` grows by `delta_cost_cents` — a mutation that refreshes the Project's `updated_at` and increments its `version`, which is exactly the sort of advance the project-patch OCC guard of §2.8 exists to catch.

### 3.9. Closeout: Audit, Repayment, and Deobligation

Once the final voucher's approval has moved a Project to `COMPLETE`, an `FHWAReviewer` initiates the closeout Audit by supplying the `project_id`. Audit creation is the second segregation-of-duties checkpoint: the auditor's `X-User-ID`, recorded as `auditor_user_id`, must differ from the `decided_by_user_id` of the project's final voucher, else `ERR_SEGREGATION_OF_DUTIES` (422). A Project hosts exactly one audit — initiating a second is rejected with `ERR_INVALID_STATE`, as is initiating against a Project not yet `COMPLETE`. The Audit opens in `INITIATED` with `repaid_cents` at 0 and `findings_text`, `ineligible_amount_cents`, `findings_issued_at`, `final_eligible_federal_share_cents`, `repayment_due_cents`, and `closed_at` unset.

The auditor issues findings by supplying the `findings_text` narrative and the `ineligible_amount_cents` of state expenditures found ineligible, zero or greater; the clock stamps `findings_issued_at` and the Audit moves from `INITIATED` to `FINDINGS_ISSUED`. Finalization then waits out the state's response window: the logical clock must have reached at least 30 days after `findings_issued_at` — exactly 30 days passes — else `ERR_AUDIT_RESPONSE_WINDOW_OPEN` (409).

Finalization reconciles the ledger. The approved eligible total is the sum of `eligible_amount_cents` over the authorization's `APPROVED` vouchers. `final_eligible_federal_share_cents` is zero if that total minus the audit's `ineligible_amount_cents` would push the product negative, and otherwise that difference multiplied by the Authorization's pinned `federal_share_pct`, rounded half-up to whole cents. `repayment_due_cents` is the excess of the Authorization's `reimbursed_cents` over `final_eligible_federal_share_cents`, floored at zero. The Audit moves from `FINDINGS_ISSUED` to `FINAL` — and when `repayment_due_cents` is zero it continues immediately to `CLOSED` in the same operation, firing the closeout cascade below without any repayment step.

When a repayment is due, the auditor records state repayments, each supplying an `amount_cents` no greater than the outstanding balance — `repayment_due_cents` minus the `repaid_cents` already recorded — with equality allowed; an overpayment is rejected with `ERR_REPAYMENT_EXCEEDS_DUE` (422). Each recording adds to `repaid_cents`, and the recording that brings `repaid_cents` to exactly `repayment_due_cents` moves the Audit from `FINAL` to the terminal `CLOSED` status.

Closing the audit fires the three-link closeout cascade. First, the Authorization deobligates: the net federal outlay is `reimbursed_cents` minus `repaid_cents`; the deobligation is `obligated_cents` minus that net; `obligated_cents` is set to the net (satisfying the §2.10 net-share invariant), `closed_at` is stamped from the logical clock, and the Authorization moves from `OBLIGATED` or `FULLY_DRAWN` to `CLOSED`. Second, the drawn apportionment cell's `obligated_cents` is reduced by the deobligation and `available_cents` is recomputed. Third, the Project moves from `COMPLETE` to the terminal `CLOSED_OUT` status, closing the program lifecycle that began with its nomination.

## 4. Endpoint Definitions

Operations that create a new resource — registering a funding program, recording an apportionment, creating a STIP, recording a comment, nominating a project, opening a clearance, creating an authorization, creating a voucher, requesting a change order, or initiating an audit — return `201 Created`. Operations that act on an existing resource (submissions, decisions, amendments, advertisements, bid openings, awards, concurrence, findings, finalization, repayments, and the project patch) return `200 OK`, as do all reads and the clock-advance capability.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/federal-aid/funding-programs` | Register a funding category and its eligible activity set | PlatformAdmin |
| POST | `/federal-aid/apportionments` | Record an annual apportionment for a (program, state, FFY) cell | FHWADivisionAdmin |
| GET | `/federal-aid/apportionments/{id}` | Get one Apportionment | All roles |
| GET | `/federal-aid/apportionments` | List apportionments with optional filters | All roles |
| POST | `/federal-aid/stips` | Create a STIP; opens in `PUBLIC_INVOLVEMENT` with the comment window starting now | StateDOTPlanner |
| GET | `/federal-aid/stips/{id}` | Get one STIP | All roles |
| POST | `/federal-aid/stips/{id}/submit` | Submit the STIP for federal approval after the comment window | StateDOTPlanner |
| POST | `/federal-aid/stips/{id}/decide` | Federal approval decision on a `SUBMITTED` STIP | FHWADivisionAdmin |
| POST | `/federal-aid/stips/{id}/open-amendment` | Reopen an `APPROVED` STIP for amendment with a fresh comment window | StateDOTPlanner |
| POST | `/federal-aid/stips/{id}/comments` | Record a public comment while the STIP is in `PUBLIC_INVOLVEMENT` | All roles |
| GET | `/federal-aid/stips/{id}/comments` | List a STIP's public comments | All roles |
| POST | `/federal-aid/projects` | Nominate a project into a STIP | StateDOTPlanner |
| GET | `/federal-aid/projects/{id}` | Get one Project | All roles |
| GET | `/federal-aid/projects` | List projects with optional filters | All roles |
| PATCH | `/federal-aid/projects/{id}` | Update description, estimate, or DBE goal while `NOMINATED` or `ELIGIBLE`; OCC-guarded | StateDOTPlanner |
| POST | `/federal-aid/projects/{id}/determine-eligibility` | Federal eligibility determination; pins the adjusted share or terminates `INELIGIBLE` | FHWADivisionAdmin |
| POST | `/federal-aid/projects/{id}/advertise` | Advertise an `AUTHORIZED` project for bids | StateDOTEngineer |
| POST | `/federal-aid/projects/{id}/open-bids` | Open sealed bids after the advertisement window | StateDOTEngineer |
| POST | `/federal-aid/projects/{id}/award` | Award the contract with DBE review | FHWAReviewer |
| POST | `/federal-aid/clearances` | Open an environmental review or right-of-way certification | StateDOTEngineer |
| POST | `/federal-aid/clearances/{id}/decide` | Federal decision on a clearance | FHWAReviewer |
| GET | `/federal-aid/projects/{id}/clearances` | List a project's clearances | All roles |
| POST | `/federal-aid/authorizations` | Authorize a project and obligate funds against the current-FFY cell | FHWADivisionAdmin |
| GET | `/federal-aid/authorizations/{id}` | Get one Authorization | All roles |
| GET | `/federal-aid/authorizations` | List authorizations with optional filters | All roles |
| GET | `/federal-aid/projects/{id}/bids` | List a project's bids in submission order | All roles |
| POST | `/federal-aid/vouchers` | Create a draft progress billing | StateDOTEngineer |
| POST | `/federal-aid/vouchers/{id}/submit` | Submit a draft voucher or resubmit a rejected one | StateDOTEngineer |
| POST | `/federal-aid/vouchers/{id}/decide` | Federal review of a voucher | FHWAReviewer |
| GET | `/federal-aid/authorizations/{id}/vouchers` | List an authorization's vouchers | All roles |
| POST | `/federal-aid/change-orders` | Request a cost-overrun change order | StateDOTEngineer |
| POST | `/federal-aid/change-orders/{id}/state-concur` | State concurrence on a change order | StateDOTEngineer |
| POST | `/federal-aid/change-orders/{id}/federal-decide` | Federal decision on a change order | FHWAReviewer |
| GET | `/federal-aid/authorizations/{id}/change-orders` | List an authorization's change orders | All roles |
| POST | `/federal-aid/audits` | Initiate the closeout audit of a `COMPLETE` project | FHWAReviewer |
| POST | `/federal-aid/audits/{id}/issue-findings` | Issue audit findings including ineligible expenditures | FHWAReviewer |
| POST | `/federal-aid/audits/{id}/finalize` | Finalize the audit after the response window | FHWAReviewer |
| POST | `/federal-aid/audits/{id}/record-repayment` | Record a state repayment of ineligible costs | FHWAReviewer |
| GET | `/federal-aid/projects/{id}/audits` | List a project's audits | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STIP_NOT_APPROVED` | 409 Conflict |
| `ERR_PROJECT_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_ENVIRONMENTAL_NOT_CLEARED` | 409 Conflict |
| `ERR_ROW_NOT_CERTIFIED` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_OBLIGATED` | 409 Conflict |
| `ERR_OPEN_CHANGE_ORDERS` | 409 Conflict |
| `ERR_DOCUMENTATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DBE_GOAL_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PUBLIC_INVOLVEMENT_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_COMMENT_PERIOD_OPEN` | 409 Conflict |
| `ERR_ADVERTISEMENT_PERIOD_SHORT` | 409 Conflict |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_STIP_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_RESPONSE_WINDOW_OPEN` | 409 Conflict |
| `ERR_AWARD_NOT_LOWEST_RESPONSIVE` | 422 Unprocessable Entity |
| `ERR_BID_NOT_RESPONSIVE` | 422 Unprocessable Entity |
| `ERR_NO_RESPONSIVE_BIDS` | 422 Unprocessable Entity |
| `ERR_CLEARANCE_KIND_EXISTS` | 409 Conflict |
| `ERR_FINAL_VOUCHER_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_APPORTIONMENT` | 409 Conflict |
| `ERR_APPORTIONMENT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FISCAL_CONSTRAINT_VIOLATED` | 422 Unprocessable Entity |
| `ERR_NO_APPORTIONMENT_FOR_FFY` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_INELIGIBLE_ACTIVITY` | 422 Unprocessable Entity |
| `ERR_REPAYMENT_EXCEEDS_DUE` | 422 Unprocessable Entity |
