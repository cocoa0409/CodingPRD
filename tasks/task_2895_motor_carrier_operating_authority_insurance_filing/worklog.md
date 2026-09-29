## Step 1: Create task directory — 2026-09-05T13:04:16.327Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2895_motor_carrier_operating_authority_insurance_filing and its workspace/ subdirectory. Index 2895 was pre-assigned by the orchestrating invocation (no auto-allocation scan performed, per instruction, to avoid collisions with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T14:26:40.000Z

All three scaffold artifacts are complete and lint-clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2895_motor_carrier_operating_authority_insurance_filing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2895_motor_carrier_operating_authority_insurance_filing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2895_motor_carrier_operating_authority_insurance_filing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    37
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  907

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**ACTION FOR THE ORCHESTRATOR:** `SCAFFOLD.yaml` line 2 still carries the literal directive `Generate task harder than expert level!` inside the `scenario:` block (kept because the scenario was to be used verbatim). This is the known difficulty-directive leak that reaches PRD.md — strip that one line before Step 3.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2895_motor_carrier_operating_authority_insurance_filing/`)
- `SCAFFOLD.yaml` — 2631 lines, §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1957 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3695 lines, single key `scaffold_corner_design`
- scratch dir removed; `workspace/` is empty

**Counts**
- 12 entities (2 immutable: ProcessAgent, FeeLedgerEntry), 9 state machines (parallel authority/insurance dimensions), 13 calculations, 35 validations, 37 endpoints, 34 errors, 5 roles, 2 `concurrency_rules`, `api_prefix: ""`
- §1.8: 9 rules × 19 instances (one rule has 3)
- §1.9: 79 instances in 9 sections — entities 12, state_machines 15, calculations 13, validations 8, endpoints 4, errors 12, rbac 6, cross_cutting_complexity_layers 8, consistency_model 1; 56 full recipes + 23 `excluded_because` stubs
- Verified mechanically: no duplicate instance names across both design files, every stub's `difficulty_instance` exists by name in §1.8, zero unbound `${...}` placeholders, and all 34 error codes appear in at least one §1.8/§1.9 instance or stub.

**Design adjudications**
1. **SCAFFOLD.yaml self-consistency fix** (3 edits): `SUSPENDED -> ACTIVE` listed designation-create as a restore trigger while validation priority 10 forbade designation writes on SUSPENDED authorities, making a `DESIGNATION_GAP` suspension a dead end. Added a narrow repair exception (designation CREATE admitted when `authority_status == SUSPENDED and suspension_reason == DESIGNATION_GAP`), rewrote `ERR_AUTHORITY_INVALID_STATE`'s condition to match, and made the restore preconditions trigger-neutral.
2. **404 split**: priority 3 owns path segments (`ERR_APPLICATION_NOT_FOUND` / `ERR_FILING_NOT_FOUND` / `ERR_AUTHORITY_NOT_FOUND` / `ERR_CARRIER_NOT_FOUND`, with CustomerContract and Shipment falling through to `ERR_REFERENCE_NOT_FOUND`), priority 6 owns request-body FKs. Instances trigger each side separately, avoiding OCC-guarded endpoints that would need a version for a nonexistent parent.
3. **Zero-gap filing adjacency** is demonstrated against an explicitly CANCELLED filing, because an ACTIVE filing never carries a non-null `cancellation_effective_at`.
4. **`ERR_INSURANCE_BELOW_MINIMUM` on cure is unreachable** (priority 28 rejects a below-minimum filing at creation, so no such filing can exist to cure with); the cure corner instead asserts the admitted cure plus the `ERR_PROCEEDING_NOT_OPEN` replay. The catalog wording is over-broad but not contradictory — the filing-creation clause is the reachable one.
5. `ERR_PASSENGER_AUTHORITY_REQUIRED` is reached on a PENDING authority because priority 17 fires ahead of the priority-30 unified-registration gate (registration is minted only by activation); the converse (freight on a PASSENGER authority) is asserted in the same instance.
6. `ERR_CONTRACT_NOT_ACTIVE` and `ERR_PROCESS_AGENT_NOT_DESIGNATED` share one long chain, with the second tender deliberately routed OK->NM so only the contract-state check (priority 14) can fire.
7. Two small assert corrections made after checking §1.1/§1.4: cited priority 14 (not 11) for `ERR_CONTRACT_NOT_ACTIVE`, and used `submission_count == 0` since `AuthorityApplication` has no `submitted_at` field. RBAC grounds use `roles.*` (SCAFFOLD.yaml's actual top-level key) rather than `rbac.*`.

**Orchestrator post-step action taken:** stripped the two leading lines (`Generate task harder than expert level!` + blank) from `SCAFFOLD.yaml`'s `scenario:` block so the difficulty directive cannot reach PRD.md via Step 4. SCAFFOLD.yaml is now 2629 lines and re-validated as parseable YAML (13 top-level keys); `grep -c "harder than expert"` returns 0 across all three scaffold files.

## Step 3: Copy shared files — 2026-09-05T14:27:55.729Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T14:43:20.000Z

PRD complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2895_motor_carrier_operating_authority_insurance_filing/workspace/PRD.md` — 438 lines, 97,820 bytes.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles: 2.1 Users and RBAC · 2.2 API Response Structure (byte-verbatim from the skill) · 2.3 Pagination · 2.4 Common Resource Properties and Registry Identifiers · 2.5 The Logical Compliance Clock · 2.6 Version Guards on Authority Writes · 2.7 Money, Counts and Rounding · 2.8 The Order in Which Rejections Are Decided (all 31 precedence rungs) · 2.9 Path Resolution for Nested Addresses · 2.10 Cascade Discipline: Suspension, Restoration and Termination
- §3 Business Logic & Workflows, 9 subsections: 3.1 Enrolling the Regulated Parties and the Filing-Fee Ledger · 3.2 Drafting an Application: Track, Class, Minimums and Fee · 3.3 Submission, Vetting, and the Fee Round Trip · 3.4 The Published Authority and Its Jurisdictional Coverage · 3.5 Proof of Insurance: Filing, Supersession and Lapse · 3.6 Activation: The Waiting Period, the Gate, and the Handover · 3.7 Recording the New-Entrant Safety Audit · 3.8 Revocation Proceedings, Cure, and the Periodic Sweep · 3.9 Customer Contracts and Shipments in Transit
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Counts** — endpoints: 37 in the §4 table vs 37 in the scaffold (verified path-by-path against the scaffold's `path:` list; 9 creates flagged as 201, the other 28 as 200). Errors: 34 in §5 vs 34 in the scaffold, each with the scaffold's exact HTTP status.

**Hard Contract checks (reported here only, never written into the PRD)**
- Contract 1 Field-Name Coverage — **PASS.** Programmatic diff of all 124 distinct identifiers (every `entities[].fields[].name` plus every `request_body`/`input`/`query_params`/`path_params` key, trailing optional-markers stripped) against the PRD's backticked tokens: 0 missing.
- Contract 2 Rule Coverage — **PASS.** All 34 error IDs are also referenced in the §2/§3 prose that produces them (not only in the §5 table); all 9 state machines' states and every transition's from/to state appear; all 13 named calculations are prosified, including the two dual-variant ones (risk score `SELF_REPORTED`/`AUDITED`, liability `SUSPENSION_ESTIMATE`/`SETTLED_ACTUAL` with its six pinned steps and the inclusive $50,000 waiver tier) and both conservation identities (fee-ledger sum vs `fee_balance_cents`, and `active_contract_count` + `suspended_contract_count`).
- Contract 3 §3 Path Purity — **PASS.** 262 distinct backticked tokens in §3; zero start with `/`, zero are bare HTTP methods, zero combine method+path, and zero contain a slash at all. Paths appear only in §1/§2/§4 where permitted.

**Truncation check** — the last 40 lines are the closing rows of the §5 table, ending on `| ERR_FILING_FEE_OUTSTANDING | 402 |`. The document terminates at a completed final section with no audit footer.

**Scaffold self-contradictions resolved** (worth flagging to the implementer/test steps): `usdot_number` is written as `USDOT-` + 7 zero-padded digits per the entity constraint, not the endpoint side effect's "8-digit"; `required_jurisdictions` is the sorted distinct union of `requested_operating_states` and the carrier's `domicile_state` (2 sources agree vs 1); the activation fee gate is "zero or negative balance passes, strictly positive is rejected with `ERR_FILING_FEE_OUTSTANDING`"; `policy_number` uniqueness is attached to `ERR_INVALID_REQUEST` since the scaffold defines no dedicated code. One invented query filter (`transportation_type`) was caught and removed from §2.3.

No scratch directory was created, so nothing needed cleanup; `INSTRUCTION.md` was left untouched. Neither withheld design file was opened, and no sibling task directory was read.

**Orchestrator verification (independent of the subagent's claim):** re-checked the tail myself — PRD.md ends on the final `ERR_FILING_FEE_OUTSTANDING | 402` row of the closed §5 table, a real section boundary, not mid-sentence. `grep -cE "^\| *(GET|POST|PATCH|PUT|DELETE) "` = 37, matching the scaffold. `grep -in "harder than expert|expert level|SCAFFOLD"` over PRD.md returns nothing, so the Step 2 difficulty directive did not leak into the contract. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T15:32:10.000Z

Step 5 complete. Both directories are at the **task root** (`/home/ubuntu/github/CodingPRD/tasks/task_2895_motor_carrier_operating_authority_insurance_filing/test_helpers/` and `.../test_suite/`); `find .../workspace -maxdepth 2 -name "test_*"` returns nothing, and the scratch dir has been removed.

## test_helpers/ — 9 modules, 2,493 lines
`constants.py` 136 · `types.py` 307 · `api_errors.py` 87 (registers the 34-id → HTTP-status map with the framework validators on import) · `test_users.py` 117 · `api_client.py` 291 (one method per §4 endpoint; canonicalises response instants to 3-digit ms, with `raw_body()` as the on-the-wire escape hatch) · `factories.py` 309 · `assertions.py` 588 (per-entity shape checks, ledger/contract/shipment invariant checkers, Decimal ROUND_HALF_UP recomputations verified against every pre-computed literal in the indices) · `fixtures.py` 616 (atomic steps + 12 tiered composites) · `__init__.py` 43.

## test_suite/ — conftest.py + 18 files, 8,803 lines, 112 test functions (119 collected with parametrisation)
Queue A: `test_01` 6 · `test_02` 5 · `test_03` 6 · `test_04` 6 · `test_05` 6 · `test_06` 8 · `test_07` 6 · `test_08` 7 · `test_09` 6.
Queue B: `test_10` 12 · `test_11` 8 · `test_12` 5 · `test_13` 6 · `test_14` 4 · `test_15` 9 · `test_16` 6 · `test_17` 5 · `test_18` 1.

## Coverage
- **§1.8 queue A: 19/19 instances translated, none skipped**, every one with ≥2 tagged tests (56 tests).
- **§1.9 queue B: 56/56 non-stub instances translated, none skipped**, one test each. The 23 `excluded_because` stubs were not translated; all 23 `difficulty_instance` cross-references were verified to resolve to a real name under the cited `rule_id`.
- An AST audit confirmed: exactly one `Design:` line per test (0 untagged/dual-tagged/dangling), every docstring carries a ≥8-word verbatim PRD quote (whitespace-normalised literal match), no `skip`/`skipif`/`xfail`, no "scaffold" mention anywhere, and `pytest --collect-only` imports cleanly (119 tests).

## Skips — no whole instance was skipped; individual assertions dropped under the PRD-first filter
- *unstated representation / default-value*: `FeeLedgerEntry.docket_ref` value, `denied_reason` source (findings vs request field), draft `filing_fee_cents == 0` (PRD says the draft previews the fee).
- *computed-field / unobservable*: settled-actual intermediate subtotals, `embargoed_shipment_count` retention after cure, "no Carrier row exists" (no carrier list endpoint).
- *error-precedence*: cure naming a policy with no filing at all — PRD names no error id for that trigger, so durable state is asserted instead of an id.
- *applies_to-scope*: undocumented list filters (`status`, `entry_type`, `filing_type` on the nested lists) replaced by client-side filtering; I applied the same fix inside `fixtures.py`.
- *branch-asymmetry*: "authority version unchanged after a refused activate".

**Three design-index literals were adjudicated as contradicting the PRD and asserted per the PRD instead** (worth knowing before Step 7 blames the implementation): contract-create on a never-activated authority yields `ERR_BIENNIAL_UPDATE_DELINQUENT`, not `ERR_AUTHORITY_INVALID_STATE` (the state gate is proven on a genuinely SUSPENDED parent); `insurance_status` becomes `LAPSED`, not `PARTIAL`, after cancelling a required CARGO slot; designation counters read 2/false, not 3/true, after a rolled-back bulk write.

## One real bug found and fixed
Five of the six authoring agents independently flagged that `fixtures.setup_registry` called `create_carrier`/`create_process_agent`/`create_insurer` without the required leading `client` argument — which would have killed every composite builder and made Step 7 iteration 1 look like a total implementation failure. Fixed, then re-audited with an AST signature checker (0 remaining call-site problems across helpers and all 18 test files).

## Step 6: Generate implementation — 2026-09-05T15:32:10.000Z

(Launched concurrently with Step 5 in a single orchestrator message, so the impl generator was physically unable to read test_suite/ — the directory did not exist at its spawn time.)

Implementation complete and verified.

## Modules (`.../workspace/implementation/`, 2565 lines total, all `py_compile` clean)

| lines | file | role |
|---|---|---|
| 66 | `app.py` | app factory, 6 blueprints, envelope error handlers, `PORT` bind |
| 210 | `calc.py` | fee lines, minimums, risk scores, disruption liability (`Fraction` + round-half-up) |
| 93 | `clock.py` | logical compliance clock, ISO-ms format/parse, day/month arithmetic |
| 144 | `store.py` | 12 in-memory dict collections, id/USDOT/docket minting, ordering, serialisation |
| 47 | `envelope.py` | `meta`/`response_type`/`data`, pagination in `meta` |
| 93 | `errors.py` | 34-code catalogue with HTTP statuses |
| 265 | `validation.py` | auth, pagination, typed body field extraction |
| 364 | `domain.py` | coverage/insurance recomputation, proceedings, SUSPEND/RESTORE/TERMINATE cascades |
| 88 | `helpers.py` | reference resolution and ownership rungs |
| 159 | `routes_registry.py` | carriers, agents, insurers, biennial, payments, clock |
| 246 | `routes_applications.py` | application lifecycle, pricing, vetting |
| 260 | `routes_authorities.py` | authorities, 8-gate activation, designations |
| 145 | `routes_filings.py` | filings with supersession, cancellation |
| 175 | `routes_compliance.py` | cure, audit results, compliance sweep |
| 199 | `routes_commercial.py` | contracts, shipments, depart/deliver |

Plus `start.sh` (executable, reads `$PORT`, binds `0.0.0.0`, `exec`s in the foreground) and `requirements.txt`.

## Coverage
- **Endpoints: 37 / 37.** Flask's URL map matches the PRD §4 table exactly — no extras, no gaps.
- **Error codes: 34 / 34**, each mapped to the PRD-specified HTTP status; the 31-rung rejection ladder of §2.8 is honoured in order at every mutating endpoint.
- Storage is in-memory only; a fresh boot returns `total_count: 0` on every list endpoint (verified above), and nothing is seeded.

## Smoke tests: 2 suites, 0 failures
Suite 1 (51 checks) covered the happy path end to end: enrolment, fee preview/debit, publish, designations, filings, activation, contract/shipment/depart, lapse → proceeding → full suspension cascade → cure → restoration with counter round-trip, sweep idempotence, list filters, and the 401/403/404/409/412/422 paths.

Suite 2 (50 checks) covered the corners: `NOT_FILED → PARTIAL → FILED` slot accretion, supersede-or-reject (back-dated 409, duplicate policy number 400, incumbent cancelled exactly at the successor's `effective_at`), buffered designation interval conflict, hazmat and undesignated-endpoint tenders, the passenger rule both ways, designation-gap suspension → repair → restoration (`SETTLED_ACTUAL` liability, `embargo_days_accrued` = 2), failed safety-audit cascade, sweep steps 1–3 with strict `<` expiry, delinquency lockout at submit (but not at create), and denial reversing the filing fee to a zero balance.

Three initial suite-2 failures were all defects in my test script, not the implementation, and were corrected after checking PRD prose: the audited risk score is exactly `0.45·20 + 0.30·10 + 0.25·4 + 12 = 25.00` (§3.7); a re-`submit` of an already-PUBLISHED application correctly stops at rung 9 rather than rung 30; and `biennial_update_due_at` is `+730 days` (§3.1), not a calendar two years.

The smoke server was killed by port (21487 now free) and `scratch_step6/` plus `__pycache__/` are removed. `worklog.md` was not touched; `scratch_step5/` belongs to the concurrent test generator and was left alone.

**Orchestrator verification:** confirmed `test_helpers/` (9 files) and `test_suite/` (19 files) are at the task root with nothing stray under `workspace/`; implementation/ holds 15 modules + `start.sh` + `requirements.txt`. Also pre-wrote `workspace/sweep.sh` for Step 7 — a detached 8-round sweep script (one `round.$i.log` per round rather than a single interleaved sweep.log) so the fix agent never has to inline the loop, which is where the `$i` quoting bug injects literal quotes into `--start-command`.

## Step 7: Run tests and iterate — 2026-09-05T15:52:39.581Z

Clean. Final sweep is green across all 8 parallel rounds.

## Summary

**Iterations run:** 2 (sweep → single fix → sweep).

**Final sweep:** all 8 parallel rounds `119/119` passed, `failed=0`, `SWEEP_DONE` recorded once. The 8 `results.{1..8}.json` files are left in place in `workspace/implementation/`.

**Tests deleted:** none. No test failed the STEP 1 coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** one.
- `test_suite/test_08_temporal_slot_intervals.py`, shared setup helper `_authority_with_closed_designations` (line 227) — changed the setup-precondition assertion from `== THREE_STATES` to `== sorted(THREE_STATES)`, because PRD §3.4 states the field is *"the distinct union of the application's `requested_operating_states` and the owning carrier's `domicile_state`, **sorted ascending by state code**"*, not the order the applicant listed.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful.

### Key finding

All 24 failures (3 tests × 8 rounds) were the *same single line* in one shared setup helper — a textbook upstream-setup bug masquerading as three independent defects. The three tests (`test_successor_designation_on_the_buffered_upper_edge_is_rejected`, `test_predecessor_designation_on_the_buffered_lower_edge_is_rejected`, `test_successor_designation_one_day_past_the_buffer_is_accepted`) never reached their actual designation-buffer assertions; they died in setup.

The diagnosis was decisively confirmed rather than guessed: **two other tests in the same suite assert the identical field as `["NM","OK","TX"]` and were already passing** (`test_13_validation_rules.py:430`, whose own message reads "sorted ascending", and `test_14_endpoint_behaviours.py:212`), plus `test_13:501` asserting `["OK","TX","WY"]`. The suite therefore already agreed sorted-ascending was correct; `test_08:227` was the lone outlier comparing against the unsorted request-order constant. The server's `["NM","OK","TX"]` was right and the test was wrong — so the fix went to `test_suite/`, and made the assertion *more* faithful to PRD (it now actually exercises the sorted-ascending clause) rather than weakening it.

The failure signature was fully deterministic — identical 3 failures in all 8 rounds of the first sweep — so no flakiness, load-induced timeout, or concurrency race was involved, and no implementation check was touched or relaxed.

**Orchestrator verification (independent of the subagent's claim):** re-read all 8 `results.$i.json` directly — every round reports `{'total': 119, 'passed': 119, 'failed': 0, 'errors': 0, 'skipped': 0}`, and `grep -c SWEEP_DONE sweep.log` = 1, so the sweep genuinely ran to completion rather than being reaped. Also audited the suite for the forbidden escape hatches: zero `pytest.mark.skip` / `xfail` / `@skip` occurrences across `test_suite/` and `test_helpers/`; 112 test functions carry exactly 112 `Design:` tags (119 collected with parametrisation); the only `seed`/`preload` hits in `implementation/` are comments in `app.py`/`store.py` asserting that nothing is seeded. Scratch dirs from Steps 5 and 7 are gone.

**Step 8 gate:** Step 7 made 1 `test_suite/` fix, so the skip condition (which requires 0 fixes of every kind) is not met and Step 8 runs. Noting up front that the single fix was a pure test-side bug against a rule PRD §3.4 already pins verbatim ("sorted ascending by state code"), and there were 0 `implementation/` fixes — so a byte-identical `PRD_FINALIZED.md` is the legitimate expected outcome here, not evidence that Step 8 failed to run.

## Step 8: Finalize PRD — 2026-09-05T15:55:10.000Z

Step 8 complete. **`PRD_FINALIZED.md` is byte-identical to `PRD.md` — and that is the correct output for this task.**

## Line counts

| File | Lines | Bytes | md5 |
|---|---|---|---|
| `PRD.md` | 438 | 97820 | `bb8581aa78d6578e13c6981071184203` |
| `PRD_FINALIZED.md` | 438 | 97820 | `bb8581aa78d6578e13c6981071184203` |

%-delta: **0.00%** (0 lines changed, 0 inserted, 0 deleted).

## Changes

None. Zero edits were warranted.

## Pre-edit search log

The `<step_7_diff>` contained exactly one item (a `test_suite/` assertion change) and zero implementation fixes, so there was exactly one candidate subject to investigate. Per the method, I ran the mandatory enumeration for it before concluding no edit was needed.

**Candidate subject:** the ordering/contents of `OperatingAuthority.required_jurisdictions` at publication.

**(a) Subject identified:** how `required_jurisdictions` is derived from `requested_operating_states` + `domicile_state`, and in what order it is stored/returned.

**(b) Impl paths enumerated** (grepped `required_jurisdictions`, `requested_operating_states`, `domicile_state`, and `sorted(` across all of `implementation/*.py`):
- `routes_applications.py:183` — the **sole** write site, inside `_mint_authority`: `required = sorted(set(app["requested_operating_states"]) | {carrier["domicile_state"]})`, stored at line 195. `set(...) | {...}` = distinct union; `sorted(...)` = ascending by state code.
- `routes_applications.py:195` — assignment into the authority record; never reassigned or mutated anywhere afterwards (no other hit in the codebase).
- `domain.py:91-97` — `recompute_coverage`, the only read site: uses membership (`s in covered`) and `len(required)` only, so it is order-insensitive and cannot disagree with any ordering claim.
- `routes_applications.py:87` — `req_state_list("requested_operating_states", min_n=1, max_n=51)`, confirming the input list preserves applicant order (so sorting genuinely happens at mint time, not upstream).
- `calc.py:91,105,117,123` — the other consumers of `requested_operating_states` (multi-jurisdiction uplift threshold, per-state surcharge); both use `len(...)` only, so no ordering coupling.
- `routes_filings.py:66` and `routes_registry.py:25,34` — the other `domicile_state` touch points (insurer-authorization check, carrier enrollment); neither reorders or re-derives jurisdictions.
- `store.py:73` — the only other `sorted(` in the codebase (generic record listing); unrelated to this field.

**(c) Wording adjustment:** none needed. `PRD.md` §3.4 (line 250) already pins the behavior uniquely and verbatim: *"Its `required_jurisdictions` is the distinct union of the application's `requested_operating_states` and the owning carrier's `domicile_state`, sorted ascending by state code — note that the carrier's home state is always in scope even when the applicant forgot to list it."* Every enumerated path is consistent with that sentence as already written. There is no PRD silence and no PRD/impl mismatch, so any edit here would have been manufactured.

## Why identical is correct

The single Step 7 fix was a **test-side bug, not a PRD gap**: `test_08_temporal_slot_intervals.py:230` compared `required_jurisdictions` against the unsorted request-order constant `THREE_STATES = ["TX","OK","NM"]` (`test_helpers/constants.py:134`) instead of `sorted(THREE_STATES)`. The server correctly returned `["NM","OK","TX"]`. Three sibling assertions in the same suite (`test_13:430`, `test_13:501`, `test_14:212`) already asserted the sorted form and were passing — the suite itself corroborated that sorted-ascending was right and `test_08:227` was the lone outlier. Step 7's fix made that assertion *more* faithful to the PRD rather than weakening it, and touched no implementation check.

Because the rule was already stated uniquely in the PRD and the implementation already matched it, a fresh implementer reading `PRD_FINALIZED.md` alone would produce the same ordering behavior. No scratch files were created; nothing was written outside `workspace/PRD_FINALIZED.md`, and `worklog.md` was not touched.

**Orchestrator note:** byte-identity confirmed independently via md5sum. This is the sanctioned outcome when Step 7 applied 0 `implementation/` fixes — Step 8's mandate is only to patch PRD at sites where impl behaviour diverged from or outran the PRD, and there were none. Step 9, by contrast, does a full impl-vs-PRD scan and must NOT come back identical; to guard against the known failure where a single Step 9 agent silently skips the scan, I am running Step 9 as THREE sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md` (pass 1 does the `cp`; passes 2 and 3 must not).

## Step 9: Complete PRD — 2026-09-05T16:22:25.357Z

Run as THREE sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden from copying, so neither clobbered its predecessor). Rationale: a single agent asked to scan 15 modules and a 98KB PRD in one shot tends to skim or skip the scan entirely and return a near-identical file. Partitioning makes each pass exhaustive inside its slice.

**Net result:** source `PRD_FINALIZED.md` 438 lines / 97,820 chars → `PRD_COMPLETED.md` 469 lines / 139,343 chars (**+41,523 chars, +42.4%**; +31 lines). md5 `c8cf06ca7883140f0bcf82c260177b3a` vs the source's `bb8581aa78d6578e13c6981071184203` — decisively NOT identical, so the scan genuinely ran. Totals across the three passes: **44 ambiguity-pins, 9 mismatch-revisions (53 changes)**. No new sections were added by any pass (heading count held at 25) and the §4 endpoint table still lists exactly 37 endpoints.

### Pass 1 — infra + registry (app.py, envelope.py, errors.py, validation.py, clock.py, store.py, helpers.py, routes_registry.py)
97,820 → 106,490 chars (+8,670), 17 edits: 16 ambiguity-pins, 1 mismatch-revision.
- §2.1 — revise — ambiguity — whitespace-only header counts as absent (401); role match exact/case-sensitive, no trim or fold; `X-User-ID` shape never validated — `validation.py:35-43`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`, regenerated per request incl. errors — `envelope.py:12-13`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads real wall-clock UTC, not the logical clock; the only such instant in the system — `envelope.py:16-21`
- §2.2 — revise — ambiguity — error `meta` never carries pagination keys; error `data` is exactly `error_id` + `message`, no field echo; message wording non-contractual — `envelope.py:41-47`
- §2.3 — revise — ambiguity — limit/offset violations are **rejected, not clamped** (400), incl. empty-but-present and `2.0`; whitespace/leading `+` tolerated; offset unbounded; past-end page empty with full `total_count`, `has_more` false — `validation.py:48-81`
- §2.3 — revise — ambiguity — `created_at` ties break by write order, earliest first; the internal sequence is never a response field — `store.py:67-73,124-140`
- §2.3 — revise — ambiguity — filters are exact case-sensitive string compares, never enum-validated (unmatched → empty page, not an error); undocumented query params ignored — `helpers.py:74-84`
- §2.4 — revise — ambiguity — both human-facing counters are per-process and start at 1: `USDOT-0000001`, `MC-000001` — `store.py:36-41`
- §2.5 — revise — ambiguity — clock `data` holds exactly `current_utc`; microseconds truncated to ms, offsets converted to UTC; one process-global clock — `routes_registry.py:153-159`
- §2.8 rung 6 — revise — ambiguity — rung 6 inspects only present, string-typed FKs; absent/null/non-string fall through to rung 7's 400, not 404 — `helpers.py:46-51`
- §2.8 rung 7 — revise — ambiguity — full typing discipline: unknown keys ignored; explicit `null` == omitted; strings verbatim/untrimmed with inclusive bounds; ints reject bools/floats/numeric strings; bools reject `"true"`; enums exact; state arrays keep submitted order; instants accept `Z`/offset/naive/date-only, truncated to whole ms — `validation.py:102-254`
- §2.10 — revise — ambiguity — embargo-day rounding is a ceiling on the exact span; exact whole days not rounded further; same-instant release accrues 0 — `clock.py:80-93`
- §3.1 — insert — ambiguity — only `id` and `usdot_number` are unique; `legal_name`/`dba_name`/`domicile_state` may repeat — `routes_registry.py:19-54`
- §3.1 — insert — ambiguity — biennial update requires all three figures (no partial refresh), admitted in any posture, never moves `unified_registration_status`, bumps `updated_at`/`version`, returns the carrier — `routes_registry.py:77-95`
- §3.1 — revise — ambiguity — `naic_code` is a 5-char all-digit **string** (leading zeros significant); duplicate is `ERR_INVALID_REQUEST` 400, not a conflict code — `routes_registry.py:133-141`
- §3.1 — revise — ambiguity — `amount_cents` integer ≥ 1; default entry memo is the fixed text `Fee payment recorded.`; `docket_ref` null; no balance precondition; 201 + carrier version bump — `routes_registry.py:98-109`
- §4 intro — insert — ambiguity — trailing slash insignificant; unknown path AND method mismatch both answer 404 `ERR_REFERENCE_NOT_FOUND` (never 405), decided by routing so it precedes authentication — `app.py:24,39-46`
- §4 rows — revise — mismatch — safety-audits row gained its `status` filter, fee-ledger row its `entry_type` filter — `routes_registry.py:67,74`
Verified-no-change: all 34 codes and HTTP statuses in `errors.py` match §5 by programmatic diff; the 51 state codes and all five enum tuples match verbatim; clock default/ms-format/18-month clamp already pinned. Behaviours confirmed empirically against a live server on port 18921, stopped by pid.

### Pass 2 — applications + authorities + calculations (calc.py, routes_applications.py, routes_authorities.py)
106,490 → 112,913 chars (+6,423), 18 changes: 15 ambiguity-pins, 3 mismatch-revisions. All pass-1 markers verified intact first.
- §2.8 rung 7 — revise — mismatch — corrected pass 1's over-broad "body must parse as a JSON object": the rung applies only to endpoints that declare fields; submit/activate/designation-revoke ignore any body entirely — `routes_applications.py:155`, `routes_authorities.py:47,239`
- §3.2 — insert — ambiguity — draft opens with `vetting_findings`/`vetted_by_user_id`/`published_at`/`published_by_user_id`/`denied_reason` all null — `routes_applications.py:127`
- §3.2 — insert — ambiguity — `predecessor_authority_id` presence rule is 422 `ERR_PREDECESSOR_INVALID` not structural 400; non-string is 400; a string naming no authority is `ERR_REFERENCE_NOT_FOUND` at rung 6 even for `NEW` — `routes_applications.py:24-33,80,103`
- §3.2 — insert — ambiguity — both previews computed and stored at create, so a fresh draft carries populated limits, `filing_fee_cents` and a four-key breakdown (not zeros/`{}`) — `routes_applications.py:123-133`
- §3.3 — insert — ambiguity — debit ledger memo is exactly `Filing fee assessed on first submission.` — `routes_applications.py:176`
- §3.3 — insert — ambiguity — a refused submission writes nothing at all; success returns the application, the entry only via the ledger listing — `routes_applications.py:161-178`
- §3.3 — revise — mismatch — `findings` has no length bound (empty/whitespace accepted, stored verbatim); a submitted `denied_reason` is accepted, type-checked, then discarded — `denied_reason` is always the findings text — `routes_applications.py:222-224,242`
- §3.3 — insert — ambiguity — a refused review leaves previous `vetting_findings`/`vetted_by_user_id` untouched — `routes_applications.py:226-230`
- §3.3 — insert — ambiguity — reversal ledger memo is exactly `Filing fee reversed on denial.` — `routes_applications.py:244`
- §3.3 — revise — mismatch — added `SUBMITTED` to the statuses that refuse a re-submit — `routes_applications.py:161`
- §3.4 — insert — ambiguity — designation-create response is a 201 `array` envelope with no pagination keys; the authority is not in the payload — `routes_authorities.py:219`
- §3.4 — revise — mismatch — the two designation checks are not interleaved: interval conflict runs across all states first, then agent coverage, so a doubly-failing request reports `ERR_DESIGNATION_INTERVAL_CONFLICT` — `routes_authorities.py:192-200`
- §3.4 — insert — ambiguity — a second revoke of an already-`REVOKED` designation is 409 `ERR_AUTHORITY_INVALID_STATE`, tested after the authority gate, writing nothing; coverage recompute + authority version bump happen on every successful revoke even for a non-required state — `routes_authorities.py:249-257`
- §3.4 — insert — ambiguity — a `PENDING` authority is never suspended by a revoke; the response returns the designation row, never the authority — `routes_authorities.py:258-260`
- §3.6 — insert — ambiguity — activation tests existence of both primary filings (BIPD then CARGO) before any limit comparison, so missing-CARGO + below-minimum-BIPD reports `ERR_INSURANCE_NOT_ON_FILE` — `routes_authorities.py:67-81`
- §3.6 — insert — ambiguity — `unified_registration_status` and the risk rescore are unconditional on every activation (a later activation overwrites an `AUDITED` variant back to `SELF_REPORTED`); carrier version +1; response is the authority alone — `routes_authorities.py:106-110`
- §3.6 — insert — ambiguity — `compliance_risk_score` is served as a bare JSON number with no trailing-zero padding — `calc.py:74-80`
- §3.6 — insert — ambiguity — the successor handover re-checks no precondition: the predecessor is rescinded from whatever status it now holds, including `REVOKED` — `routes_authorities.py:133-136`
- §3.9 — insert — ambiguity — the suspension-estimate day count is a ceiling on the *signed* span with no zero floor, so a post-`term_end_at` suspension yields negative liability — `calc.py:177-180`
- §4 — revise ×3 — ambiguity — documented three undocumented-but-accepted list filters: `application_kind`, proceedings `status`, designations `status` — `routes_applications.py:147-152`, `routes_authorities.py:42,231-236`
Verified-no-change: all fee-line constants and per-line rounding, the three minimum-limit ladders and the uplift edge, both risk-score variants and the clamp-then-round-once order, the settled-actual six steps, the 21-day/18-month/30-day/730-day windows, and the closed-interval-plus-one-day-buffer comparison with its inclusive edges were all already pinned uniquely.

### Pass 3 — filings + compliance + commercial + cascades (domain.py, routes_filings.py, routes_compliance.py, routes_commercial.py)
112,913 → 139,343 chars (+26,430), 469 lines, 18 changes: 13 ambiguity-pins, 5 mismatch-revisions. Prior passes' markers and all headings verified intact first.
- §2.10 Suspension — insert — ambiguity — counter moves are relative with no floor at zero; a contract with no shipments still gets `embargoed_shipment_count` overwritten with 0; each distinct row's `version` advances exactly one per request however many cascade hops touched it — `domain.py:222-252,20-35`
- §2.10 Restoration — insert — ambiguity — what restoration deliberately does NOT undo: contract `suspended_at` and `embargoed_shipment_count` keep suspension-era values (the settlement reads them), shipment `embargoed_at` kept, liability rewritten not cleared; `resumed_at` written before the liability figure — `domain.py:255-289`
- §2.10 Restoration — insert — ambiguity — restoration is only ever a tail effect of another write and is skipped **in silence** unless all four guards hold, including `authority_status == SUSPENDED` — `domain.py:292-302`
- §2.10 Termination — revise — mismatch — counters are assigned zero rather than decremented; carrier `active_authority_count` is never adjusted even when the terminated authority was `ACTIVE`/`PENDING`; `pre_embargo_status` is NOT reset on the diverted path (unlike restoration) — `domain.py:305-335`
- §3.5 — insert — ambiguity — within rung 6, `authority_id` resolves before `insurer_id` — `routes_filings.py:29-33`
- §3.5 — insert — ambiguity — `policy_number` uniqueness spans every filing that insurer ever made including `CANCELLED`/superseded ones; filing create places no `authority_status` gate at all (a `REVOKED` authority accepts a filing) — `routes_filings.py:44-46`
- §3.5 — insert — ambiguity — `meets_required_minimum` is true on every persisted filing; a bond filing against a zero requirement is compared against zero and admitted at any limit — `routes_filings.py:70-72,90`
- §3.5 — insert — ambiguity — occupancy slots key on the exact `filing_type`, so `SURETY_BOND` and `TRUST_FUND` never supersede each other and may both sit `ACTIVE` with overlapping intervals while satisfying one required slot — `routes_filings.py:54`
- §3.5 — insert — ambiguity — supersession detail: incumbent's `cancellation_effective_at` takes the new filing's client-supplied `effective_at` while its `updated_at` takes current logical time, version +1; incumbent cancelled before insert; no back-pointer; response is the new filing alone — `routes_filings.py:74-95`
- §3.5 — insert — ambiguity — the exhaustive recomputation state table (incl. `FILED → LAPSED` regardless of surviving slots, `PARTIAL → NOT_FILED`, no-slots → `FILED`) plus the four clauses in evaluation order, noting it reads the value being replaced and so is not a pure function of the slots — `domain.py:170-185`
- §3.5 — insert — ambiguity — a recompute landing on the current value writes nothing, so such a create/cancel does not invalidate an outstanding `expected_authority_version` — `domain.py:182-184`
- §3.5 — insert — ambiguity — create/cancel asymmetry: a filing create never opens a proceeding and never suspends even when it drives `insurance_status` to `LAPSED` (reachable via a future-dated supersede) — `routes_filings.py:94`
- §3.5 Cancellation — revise — mismatch — the four conditions reordered to actual precedence (insurer identity → body → `ERR_FILING_NOT_ACTIVE` → `ERR_AUTHORITY_INVALID_STATE` → instant comparison), naming the previously-unnamed 409 and flagging that the 400 is deliberately evaluated after both 409s — `routes_filings.py:118-133`
- §3.5 Cancellation — insert — ambiguity — cancellation is immediate in status, merely recorded in the interval: no scheduled/grace state, a future-dated cancel vacates the slot at once, nothing revisits the date — `routes_filings.py:135-145`
- §3.5 Lapse — insert — ambiguity — a proceeding opens only on a transition INTO `LAPSED` (at most one per lapse episode); the cascade is separately conditioned on `ACTIVE`, so a `PENDING` authority gets a proceeding without a suspension and a `SUSPENDED` one keeps its original `suspension_reason` — `routes_filings.py:141-144`
- §3.7 — insert/revise — mismatch — a window failure at either edge reports the same `ERR_AUDIT_INVALID_STATE`; state checked before window, body validity before both; refused writes nothing; the affected set is chosen once before any write, walked twice, with proceeding+suspend interleaved per authority — `routes_compliance.py:73-113`
- §3.8 — revise — mismatch — `replacement_policy_number` is non-null on EVERY `CURED` proceeding whatever its `reason` — `routes_compliance.py:50-52`
- §3.8 Cure — insert — ambiguity — an expired `cure_deadline_at` reports `ERR_PROCEEDING_NOT_OPEN`; the policy search is unrestricted by `filing_type`, scoped to the authority, first match in `created_at` order; a missing qualifying filing reports `ERR_INSURANCE_BELOW_MINIMUM`, not a not-found; refused cure writes nothing — `routes_compliance.py:29-48`
- §3.8 Cure — revise — mismatch — `insurance_status` is SET to `FILED` outright, not recomputed, so a multi-slot authority can read `FILED` with only the cured slot covered; assignment conditional on the value changing — `routes_compliance.py:55-59`
- §3.8 Sweep — insert — ambiguity — the missed audit's carrier is left entirely untouched (no `entrant_status`, no score) — `routes_compliance.py:126-141`
- §3.8 Sweep — revise — mismatch — the cascade's only precondition is that the authority is not ALREADY `REVOKED`/`RESCINDED`, so `ACTIVE` and `PENDING` authorities are terminated straight from those statuses (previously written as `SUSPENDED → REVOKED`); an already-terminal authority still moves the proceeding and still counts with no cascade; `authorities_revoked_count` counts proceedings, not authorities — `routes_compliance.py:154-167`
- §3.8 Sweep — insert — ambiguity — a repeat sweep at a fixed instant writes nothing and advances no version; the sweep never recomputes coverage/insurance, never revisits a cancellation date, never restores; response `data` holds exactly five keys — `routes_compliance.py:169-175`
- §3.9 Contracts — insert — ambiguity — `active_contract_count` increments even on a `PENDING` authority; the coverage dimension is not gated; response is the contract alone and the create invalidates the caller's own `expected_authority_version` — `routes_commercial.py:39-75`
- §3.9 Tender — insert — ambiguity — no `authority_status` gate at tender; designations judged at the current logical time, not `tender_at`, and any current designation counts whether required or not; `origin_state` may equal `destination_state`; the tender writes nothing outside the new row — `routes_commercial.py:110-145`
- §3.9 Depart/deliver — insert — ambiguity — departure precedence is ownership → shipment status → contract status → authority status, so the cascade's own triple reports `ERR_SHIPMENT_INVALID_STATE`; names the two 409s §2.8 does not associate with this endpoint; refused transitions write nothing; depart stamps no instant, deliver stamps `delivered_at`; neither touches contract or authority — `routes_commercial.py:163-199`
- §4 — insert — ambiguity — nested contract listing is filterable by `status` — `routes_commercial.py:82`

**Orchestrator verification:** `wc`/`md5sum` confirm PRD_COMPLETED.md is 469 lines / 139,343 chars with a distinct md5, ends on the closed §5 table row `| ERR_FILING_FEE_OUTSTANDING | 402 |` (no truncation), retains all 37 §4 endpoint rows and 25 headings (no new sections), and contains no "harder than expert" / "SCAFFOLD" leakage. The 8 green `results.{1..8}.json` from Step 7 are still in place; no scratch dirs remain anywhere under workspace/, and worklog.md was never written by any subagent. Steps 8 and 9 touched only PRD documents, so the Step 7 sweep result stands as the implementation's verification of record.

**PIPELINE COMPLETE — Step 9 wrote workspace/PRD_COMPLETED.md.**

