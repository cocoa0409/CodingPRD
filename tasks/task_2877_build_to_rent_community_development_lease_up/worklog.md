# Worklog — task_2877_build_to_rent_community_development_lease_up

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up` and its `workspace/` subdirectory. Index 2877 was pre-assigned by the orchestrating command (no ./tasks/ scan performed, per instruction, to avoid collisions with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T02:00:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts for task 2877 are complete and lint-clean.

Verbatim final lint verdict block:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     9
  §1.8 instances scanned:     20
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1176

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all `yaml.safe_load`-valid; `worklog.md` and `workspace/` untouched):
- `SCAFFOLD.yaml` — 131 KB. Entities 9, state_machines 9, concurrency_rules 2, calculations 10, validations 37, endpoints 49, errors 53, roles 7. `api_prefix: ""`, role_model `segregation_of_duties`, consistency_model `immediate`, complexity_layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Contains no `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 152 KB, single key `scaffold_difficulty_design`: 9 rule_id groups, 20 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5085 lines / 304 KB, single key `scaffold_corner_design`: 79 instances across all 9 legal sections — entities 10, state_machines 14, calculations 11, validations 27, errors 4, endpoints 3, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1. 66 of those carry full `test_recipe`s; 13 are `excluded_because` stubs pointing at real §1.8 instance names.

Verification performed beyond lint: instance `name` uniqueness across §1.8 ∪ §1.9 (0 duplicates); all 53 declared error_ids appear in at least one design recipe (0 unreferenced); and an audit that every instance performing `POST /phases/{id}/section-releases` or `POST /leases` first publishes a `MarketRentSchedule` for the relevant product_type (four §1.9 instances were repaired for this earlier — Pemberly, Quillhaven, Rookwood, Jessamine chains).

One item for the orchestrator: `SCAFFOLD.yaml` line 2 still contains the literal directive line `Generate task harder than expert level!` inside `scenario:`. Per the known leak path (scenario -> PRD.md) that line should be stripped before Step 3; I left the scenario byte-identical to what was handed to me rather than editing a file outside my three deliverables.

**Orchestrator action taken:** stripped lines 2-3 (`Generate task harder than expert level!` + blank) from `SCAFFOLD.yaml`'s `scenario:` block per the known difficulty-directive leak path, then re-validated with `yaml.safe_load` (13 top-level keys, OK) and confirmed `grep "harder than expert" SCAFFOLD.yaml` is now empty. The difficulty directive was delivered to the Step 2 subagent only and will not be forwarded to the doc / test / implementation generators.

## Step 3: Copy shared files — 2026-09-05T02:05:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T02:20:00.000Z

Subagent summary (verbatim):

PRD generated and verified. All three hard contracts pass mechanically.

**Output:** `workspace/PRD.md` — **456 lines, 13,159 words, 96 KB**

**Section list (28 headings):**
- §1 Introduction (4 paragraphs: domain framing, system scope, the posture gate as organising idea, root mount)
- §2 Global Specifications — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Record Versioning · 2.5 Path Resolution and Referential Integrity · 2.6 The Community Posture Gate · 2.7 Optimistic Concurrency on Community Writes · 2.8 Cents, Basis Points and Rounding Discipline · 2.9 The Logical Clock · 2.10 Rejection Precedence · 2.11 Cascades, Compensation and the Concession Ledger Invariant
- §3 Business Logic (11 subsections, chronological-lifecycle grouping) — 3.1 Standing Up a Community and Its Product Mix · 3.2 Entitlement, Platting and the Revision Loop · 3.3 Construction Phasing, Section Releases and Amenity Delivery · 3.4 Halting Construction and the Freeze Cascade · 3.5 Absorption Pacing, Published Rents and Indexed Rent Growth · 3.6 Concession Programs and Amortization Mode · 3.7 Households, Lease Drafting and the Price Frozen at Creation · 3.8 The Concession Ledger · 3.9 Submission, Signature, Activation and the Cancellation Compensation · 3.10 Notice, the Turn Loop and Maintenance Capacity · 3.11 Stabilization, the Management Transition, and Portfolio Financing
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Coverage counts:**
- **Endpoints: 49/49** — table rows match scaffold `(method, path)` pairs exactly; 0 missing, 0 extra.
- **Error IDs: 53/53** in the §5 table, and **53/53 also mentioned in §1–§4 narrative** (0 orphan codes).

**Contract 1 — Field-Name Coverage: PASS**
```
- entities[].fields: 116 required, 116 present, 0 missing
- endpoints[].request_body: 62 required, 62 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
(union incl. valuation/clock output keys: 137 required, 137 present, 0 missing)
```

**Contract 2 — Rule Coverage: PASS**
```
- validations[] with priority: 37 checked, 37 expressed (priority chain rendered explicitly as §2.10's 17 ordered groups), 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write_endpoint + expected_community_version + ERR_STALE_COMMUNITY_VERSION/412 all named), 0 missing
- state_machines[].transitions: 50 checked, 50 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed as precise prose, 0 missing
- validations[] conditions: 37 checked, 37 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, expressed (incl. the 5-hop halt cascade, the 5-hop signature cascade, both compensating actions), 0 missing
- entities[].fields[] structured content: 116 checked, reconstructible (defaults/initials stated per entity; AbsorptionReview's absent updated_at/version called out), 0 missing
- sibling-branch symmetry: 8 groups checked (3 plat decisions, 2 phase-completion kinds, 2 halt entries, 2 resume branches, 2 amortization modes, 2 pm-transition branches, 2 valuation bases, 3 cancellation branches), 8 with equal density, 0 asymmetric
```

**Contract 3 — §3 Path Purity: PASS**
```
- backtick tokens scanned: 1006 (299 distinct)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
```

**Other checks:** §2.2 diffs byte-identical against `section-2.2-response-structure.md` (only a trailing blank separator line added). Fuzzy-word scan clean; OCC prose uses stale-version framing only, no "simultaneous"/"first-writer-wins". File ends at the final §5 table row, no audit footer. Nothing else in the task dir was touched; scratch files went to `/tmp/task_2877_prd/`.

**Two judgement calls worth flagging** (scaffold left the error mapping under-determined; I picked the only coherent option): a lease signature blocked by a `RESTRICTED` posture without an approved restricted-posture-eligible concession is specified as `ERR_COMMUNITY_POSTURE_RESTRICTED`, and lease drafting against a community whose `lifecycle_status` is `PLANNING`/`CONSTRUCTION` is specified as `ERR_INVALID_LIFECYCLE_STATE` (with the homesite/phase half of that rule kept on `ERR_HOMESITE_NOT_LEASABLE`). Also, `Phase.sequence_index` uniqueness is stated as a rule but the scaffold nominates no error id for it, so the PRD states the constraint without naming a code.

**Orchestrator truncation check (the known doc-generator failure mode):** `tail` of `workspace/PRD.md` ends on a complete final table row of §5 (`| ERR_LTV_COVENANT_BREACH | 409 |` plus trailing newline), i.e. a real section boundary, not mid-sentence. Mechanically re-counted from the file: §5 has 53 `ERR_*` rows and §4 has 49 method rows, matching the subagent's claim. `grep -i "harder than expert|expert level|SCAFFOLD"` over PRD.md returns nothing — the difficulty directive did not leak. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T02:55:00.000Z

Subagent summary (verbatim):

Stage 2 complete and verified. Both output directories sit at the task root; nothing was written under `workspace/`.

## Files written

`test_helpers/` — 2217 lines, 9 files (Stage 1)
- `types.py` 377, `api_client.py` 197 (49 endpoint methods), `api_errors.py` 121 (54 error ids + status map registration), `constants.py` 82, `factories.py` 279, `assertions.py` 406, `fixtures.py` 601 (40 single-step wrappers + 11 scenario composites), `test_users.py` 100, `__init__.py` 54

`test_suite/` — 7401 lines, 12 files (Stage 2)
- `conftest.py` 48 · `test_01_community_and_homesite_registry.py` 528 · `test_02_plat_entitlement_and_revision_loop.py` 480 · `test_03_construction_phasing_and_section_releases.py` 1008 · `test_04_posture_gates_and_halt_cascade.py` 377 · `test_05_rent_schedules_and_absorption_pacing.py` 883 · `test_06_lease_pricing_and_services_fee.py` 478 · `test_07_concession_programs_and_amortization.py` 852 · `test_08_lease_execution_signature_and_cancellation.py` 735 · `test_09_turn_operations_and_maintenance_capacity.py` 861 · `test_10_stabilization_management_and_financing.py` 618 · `test_11_access_control_and_ownership.py` 533

## Coverage

**126 tests**, 86 distinct `Design:` tags = exactly the 86 translatable instances.
- Queue A (difficulty index): **20 / 20 instances translated, 0 skipped**, 47 tests — every instance has >=2 tests.
- Queue B (corner index): **66 / 66 non-stub instances translated, 0 skipped**, 79 tests. The 13 `excluded_because:` stubs were not translated; all 13 `difficulty_instance` cross-references resolve (12 to a real instance `name:`, one — `priority_ordering_between_the_authorisation_and_state_bands` — to the rule id `priority_pair_validation_conflict`, whose three instances are all covered).

## Verification run

- `python3 -m py_compile` clean on all 21 .py files; all 11 test modules import successfully against the frozen helpers barrel.
- AST scan: every test has exactly one `Design:` line, always the last docstring line; every tag resolves to a real instance name with a matching rule_id/section; no stub-tagged tests, no duplicate test names, no classes. 0 problems.
- Grep scans clean for: `["data"]` double-unwrap on validator results, whitespace-only header values, money-as-string, date-only instants in instant fields, `skip`/`xfail`, and any scaffold/yaml/design-index reference outside the tag lines.
- `__pycache__` removed; `worklog.md`, `SCAFFOLD*.yaml`, `PRD.md`, `INSTRUCTION.md` untouched.

## Judgement calls worth relaying to the implementation/fix steps

1. **Status codes: PRD beats design.** Several design instances pin HTTP 200 for transition-creating POSTs (plat submissions/decisions, section releases, construction start, signature, notice). PRD §4 mandates 201, so those assert 201. Where PRD §4's 201 list does not clearly settle the endpoint (`pm-transitions`, `facility-conversions`, `phases/{id}/completion`, `phases/{id}/resume`) the tests accept any 2xx and assert state instead.
2. **`community_services_fee_cents`** is asserted throughout; the design prose's `services_fee_cents` abbreviation was never used.
3. Three sub-claims were dropped as not PRD-derivable while their instances stayed covered: `construction_started_at` (field absent from the PRD `Phase`), `blended_market_rent_cents` (absent from the PRD valuation response), and `GET /households/{other}` -> `ERR_OWNERSHIP_VIOLATION` (PRD §2.1 says the ownership check guards exactly three lease operations, contradicting its own household-read sentence).
4. Two design-recipe defects were repaired without touching pinned literals: a turn-completion recipe whose October window contradicted its own `last_turn_ready_at` literal was shifted to the equivalent 48-hour August window, and a `cancellation_reason` free-text literal was replaced with the PRD enum member `APPLICANT_WITHDREW`.

**Orchestrator verification:** `test_helpers/` (9 .py) and `test_suite/` (12 .py) confirmed at the TASK ROOT; `workspace/test_helpers` and `workspace/test_suite` both confirmed absent (the known "test dirs land under workspace/" failure mode did not occur).

## Step 6: Generate implementation — 2026-09-05T02:55:00.000Z

Launched concurrently with Step 5 in a single assistant message, so the implementation subagent started before `test_suite/` existed on disk (physical isolation). Subagent summary (verbatim):

Implementation is complete, compiles clean, and passed a 45-call end-to-end smoke run with zero unexpected responses. Server stopped by its recorded PID (2425843); port 39877 confirmed free, no broad pkill used.

**Location:** `workspace/implementation/` — nothing was written at the task root (git shows only the untracked task dir itself; no test_helpers/, test_suite/, worklog.md or SCAFFOLD*.yaml touched).

**Modules (3052 lines of Python across 23 files, plus `start.sh` + `requirements.txt`):**

| file | lines | file | lines |
|---|---|---|---|
| app.py | 77 | routes/reads.py | 211 |
| calc.py | 103 | routes/communities.py | 266 |
| errors.py | 89 | routes/phases.py | 269 |
| db.py | 147 | routes/homesites.py | 95 |
| response.py | 115 | routes/households.py | 47 |
| middleware.py | 60 | routes/pricing_routes.py | 159 |
| validation.py | 126 | routes/leases.py | 327 |
| repo.py | 122 | routes/turns.py | 127 |
| serializers.py | 119 | routes/clock.py | 31 |
| services/community.py | 146 | services/turn.py | 91 |
| services/pricing.py | 95 | services/valuation.py | 92 |
| services/concession.py | 96 | services/absorption.py | 42 |

**Coverage, machine-verified against PRD.md:**
- Endpoints: **49/49**. A diff of the PRD §4 method+path table against the `@bp.get/@bp.post` decorators is empty (`ROUTES_MATCH`).
- Error ids: **53/53**. A diff of every `ERR_*` token in the PRD against `errors.py` is empty (`ERRORS_MATCH`).
- Storage is in-memory dicts only; nothing is seeded, and no file/SQLite/JSON persistence exists.

**Smoke test (`PORT=39877 bash start.sh`, 45 assertions, 0 failures)** — the flow created a community (posture `FROZEN` at birth, `OPEN` after plat approval, version bumping once per request), housing + amenity phases, 4 homesites with COs, 3 published rent schedules under optimistic concurrency, a section release (posture -> `RESTRICTED`, lifecycle -> `LEASE_UP`, facility -> `ADVANCE_ELIGIBLE`), then a full lease lifecycle. Notable verified numbers: fee tier 350 bps + DETACHED surcharge -> `gross 363250`; concession 4 free weeks -> `total 335308`, 12 straight-line periods summing exactly to the total; ledger `committed_concession_cents 335308` matching the lease remainder; turn order 24 h x 2 techs at 6500 -> `labor 312000`, waterfall `324345/0/0`; `pacing_index 0.375` (raw 0.5 x supply factor clamped to 0.75 x 1.00 penalty) -> `AGGRESSIVE` / `-150 bps`, which the indexed reprice applied as `344750`; `FORWARD_STABILIZED` valuation `value_cents 156140914`, `ltv 6 bps`, covenant satisfied.

Negative paths exercised and correct: `ERR_COMMUNITY_POSTURE_RESTRICTED`, `ERR_SEGREGATION_OF_DUTIES` (403), `ERR_OWNERSHIP_VIOLATION` (403), `ERR_CLOCK_REWIND`, `ERR_CONCESSION_PERIOD_OUT_OF_ORDER`, `ERR_TURN_WINDOW_OVERLAP`, `ERR_LEASE_UP_THRESHOLD_NOT_MET`, `ERR_COMMUNITY_POSTURE_FROZEN` after the halt cascade (available count 0, restored to 4 on resume), `ERR_INVALID_REQUEST` for `limit=0` and a bad `basis`, `ERR_UNAUTHENTICATED` (401) and `ERR_UNAUTHORIZED` (403).

Two judgment calls worth flagging to whoever runs Step 7: an unmet `plat_status == APPROVED` precondition on resume returns `ERR_INVALID_PLAT_STATE` (the scaffold declares no id for it, and it is unreachable in practice since an unapproved plat freezes the community); and a `TRAILING_ACTUAL` valuation with zero value but a positive commitment reports `loan_to_value_bps 999999999` with `covenant_satisfied false` rather than dividing by zero.

## Step 7: Run tests and iterate — 2026-09-05T03:15:00.000Z

Subagent summary (verbatim):

Clean 8-round sweep achieved. `worklog.md` untouched.

## Summary

**Iterations run:** 2 (iteration 1 = baseline sweep, 3 deterministic failures; iteration 2 = verification sweep, clean).

**Tests deleted (1):**
- `test_construction_start_is_rejected_while_the_plat_is_only_submitted` (`test_suite/test_03_construction_phasing_and_section_releases.py`) — **unique-derivability collapse (ERROR-CODE SILENCE on the pathway)**. It asserted `ERR_INVALID_PLAT_STATE` when construction-start is attempted on a community whose `plat_status` is `SUBMITTED`. PRD §3.3 says only *"The community's `plat_status` must be `APPROVED` and its `posture` must not be `FROZEN` … that attempt is `ERR_COMMUNITY_POSTURE_FROZEN`"* — the sole error_id it names for this gate is `ERR_COMMUNITY_POSTURE_FROZEN`, and PRD never assigns `ERR_INVALID_PLAT_STATE` to this endpoint (§3.2 assigns it only to plat submissions/decisions). Two PRD-faithful implementations exist: (a) a separate plat gate emitting `ERR_INVALID_PLAT_STATE`, or (b) recognising that §2.6 branch 1 makes a non-`APPROVED` plat *definitionally* a `FROZEN` posture, so the posture gate fires — reading (b) is what the implementation does and is the better-supported one.

**Fixes applied to `test_helpers/`:** none — no fixture, factory or header builder was at fault.

**Fixes applied to `test_suite/` (2, both making the test more PRD-faithful):**
- `test_03_construction_phasing_and_section_releases.py` — `test_same_kind_phases_closer_than_48_hours_cannot_both_start`: reordered setup so each candidate phase is created immediately before its own start attempt. Previously all three phases were created up front, then phase 1 was started — but PRD §3.3 scopes the gap rule to *"any phase of the same community with the same `kind`"* with **no** status qualifier (in deliberate contrast to the adjacent concurrency cap, which does enumerate `UNDER_CONSTRUCTION`/`SECTIONS_RELEASED`/`CONSTRUCTION_HALTED`). A merely-`PLANNED` sibling 24 h away therefore correctly refused phase 1's start, failing the test in setup. The reordered test exercises the identical rule with the identical error_id and the identical 48 h boundary, and now passes under either reading of the scope question. Verified end-to-end against a live server on port 39877 before the sweep.
- `test_07_concession_programs_and_amortization.py` — `test_a_concession_program_that_does_not_list_the_product_type_is_rejected`: `KeyError: 'product_type'`. Partial-coverage split (STEP 1c): the incidental `assert lease["product_type"] == "DETACHED"` asserted a response field PRD never declares on a lease (§3.7 enumerates the lease's fields without it; §2.3 omits it from lease filters), while PRD declares `product_type` on the **homesite** (§3.1). Moved the precondition assertion onto the homesite; the test's covered assertion (`ERR_PRODUCT_TYPE_NOT_ELIGIBLE` per §3.8) is untouched.

**Fixes applied to `implementation/`:** none — no implementation defect was found. All three baseline failures traced to the test artifact.

**Final counts:** rounds 1–8 all `125/125` passed, 0 failed, 0 errors. (Total is 125, not 126, because of the one deletion.)

**Orchestrator verification of the sweep artifacts** (the known "Step 7 claims a clean sweep with no results.*.json behind it" failure mode): all 8 `workspace/implementation/results.{1..8}.json` exist (~41 KB each, same mtime 13:11) and were re-parsed independently — every round reports `passed=125 failed=0 total=125 errors=0`. `grep -c '^def test_'` over `test_suite/` totals exactly 125, matching the reported total after the single deletion. No `skip`/`xfail` markers anywhere in `test_suite/` or `test_helpers/`. The sweep ran via the orchestrator-supplied `workspace/sweep.sh` (setsid nohup, script file rather than an inline one-liner, per the known quoting bug).

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 1 deletion and 2 `test_suite/` fixes, so the skip condition (zero deletions AND zero test_suite AND zero test_helpers AND zero implementation fixes) does not hold. Note for Step 8: there were **0 implementation fixes**, so a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here if none of the three Step 7 items turns out to be a PRD silence — the deletion and both test fixes were adjudicated as test-artifact defects, not PRD/impl divergences.

## Step 8: Finalize PRD — 2026-09-05T03:35:00.000Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` is in place at `workspace/PRD_FINALIZED.md`.

## Size
- PRD.md: 456 lines / 95,985 bytes. PRD_FINALIZED.md: 456 lines / 96,581 bytes.
- Line delta: 0 (0.00%); byte delta: +596 (+0.62%). Both edits are inline within §3.3's construction-start paragraph (line 214).

## Changes
- **§3.3 (construction-start gates) — revise — the plat requirement is pinned as being enforced *through* the posture check rather than as a separate plat gate; explicitly states that a non-`APPROVED` plat, a false `single_ownership_covenant`, and a halted housing phase all surface as `ERR_COMMUNITY_POSTURE_FROZEN`, and that this endpoint never reports `ERR_INVALID_PLAT_STATE`** — `implementation/routes/phases.py:103-107`.
- **§3.3 (same-kind 48 h gap rule) — insert — one clause pinning that the gap rule has no status qualifier: a same-`kind` sibling is weighed whatever its `status` (`PLANNED`, in flight, halted, `COMPLETE`)** — `implementation/routes/phases.py:124-132`.
- **Step 7 item 3 (`product_type` on a lease) — no edit.** PRD already determines this: §3.7 enumerates lease fields without `product_type` and §2.3 omits it from lease filters, matching `serializers.py:47-58` (`LEASE_FIELDS` has no `product_type`) and `routes/reads.py` lease filter map. That failure was a test artifact, not a PRD silence.

## Per-edit pre-edit search log

**Edit 1 — subject: the plat/posture gate on `POST /phases/{id}/construction-start`, and every use of `ERR_INVALID_PLAT_STATE`.**
- (b) Enumerated: `grep -rn "plat_status\|INVALID_PLAT_STATE\|require_not_frozen\|require_open"` over all impl modules. Hits read: `routes/phases.py:103-107` (start: `require_not_frozen` only, no plat branch), `phases.py:159` (section-release uses `require_open`), `phases.py:255-256` (resume *does* raise `ERR_INVALID_PLAT_STATE`), `routes/communities.py:110-111,132-133` (plat submission/decision raise it), `communities.py:219` (pm-transition `require_not_frozen`), `routes/pricing_routes.py:69,131`, `routes/leases.py:53,188,211`, and `services/community.py:94-118` (posture branch 1 + the two gate helpers).
- (c) Adjustment: wording was deliberately scoped with "enforced **here**" / "**this endpoint** never reports `ERR_INVALID_PLAT_STATE`" rather than any global claim, because `phases.py:255` (resume) and `communities.py:110/132` do emit that code — a universal sentence would have contradicted three live paths. Also widened the enumerated freeze causes to include `single_ownership_covenant` false, since `services/community.py:94-96` makes that an equally valid trigger of the same rejection at this gate; and left the original first clause verbatim so §2.6's own plat->FROZEN derivation is not weakened.

**Edit 2 — subject: the `ERR_PHASE_GAP_VIOLATION` sibling-scope predicate.**
- (b) Enumerated: `grep -rn "PHASE_GAP"` (single site, `phases.py:132`); read `phases.py:111` (`siblings` = all phases of the community minus self, **no** status filter), `phases.py:124-132` (loop filters on `kind` and on non-overlap only), `phases.py:26-34` (`_windows_overlap` closed-interval, `_window_gap`), and `phases.py:117-123` (the adjacent concurrency cap, which *does* filter on `IN_FLIGHT_PHASE_STATUSES` at line 20). Also confirmed `repo.phases_of_community` applies no status filter.
- (c) Adjustment: phrased as "no status qualifier at all … whatever its `status`" and enumerated the statuses illustratively rather than as a closed set, so the sentence cannot be read as a new whitelist; and explicitly contrasted it with the concurrency cap so a fresh implementer does not transplant that cap's status filter onto the gap rule.

**Orchestrator verification:** `PRD_FINALIZED.md` exists, 456 lines / 96,581 bytes; `diff` against `PRD.md` shows exactly one changed line (456 in, 456 out — both edits are inline within the §3.3 construction-start paragraph). Not byte-identical, consistent with the two adjudicated PRD silences.

## Step 9: Complete PRD — 2026-09-05T04:05:00.000Z

Run as **three sequential passes** over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not clobber earlier edits). Partition: pass 1 = cross-cutting infrastructure (`app.py`, `middleware.py`, `response.py`, `errors.py`, `validation.py`, `db.py`, `repo.py`, `serializers.py`, `calc.py`); pass 2 = community / entitlement / phasing / homesite / listing (`routes/communities.py`, `routes/phases.py`, `routes/homesites.py`, `routes/reads.py`, `services/community.py`, `services/absorption.py`); pass 3 = household / leasing / pricing / concession / turn / valuation / clock (`routes/households.py`, `routes/leases.py`, `routes/pricing_routes.py`, `routes/turns.py`, `routes/clock.py`, `services/pricing.py`, `services/concession.py`, `services/turn.py`, `services/valuation.py`). Every one of the 25 .py modules was audited by exactly one pass.

### Pass 1 — infrastructure slice (subagent summary, verbatim)

- Setup: `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` done.
- Size: `PRD_FINALIZED.md` 456 lines / 96,581 chars -> `PRD_COMPLETED.md` 456 lines / 101,435 chars (+4,854; all in-paragraph). Not byte-identical (verified with `cmp`).
- Counts: 13 changes — 11 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.1 — insert — ambiguity — role header matched exactly (case/whitespace differences are outside the catalogue); `X-User-ID` missing/blank is not an auth failure for the six operator roles — `middleware.py:24-33`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `response.py:19-20`
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock time, the one instant not from the logical clock — `response.py:23-29`
- §2.2 — insert — ambiguity — `decision_note` / `halt_reason` are validated but never persisted, so appear in no payload — `serializers.py:4-74`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST`; whitespace and a leading sign tolerated — `response.py:110-115`
- §2.3 — insert — ambiguity — `created_at` ties broken by ascending server creation sequence — `db.py:80-86`
- §2.3 — insert — ambiguity — `offset` at/beyond `total_count` is legal: empty `data`, `has_more` false, full `total_count` — `response.py:47-90`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read the logical clock; version settles once per request, no-op writes don't bump, records created by the request stay at version 1 — `db.py:63-76,94-115,137-141`
- §2.4 — insert — ambiguity — request instants parsed leniently (bare date = midnight, `T`/`t`/space separator, optional seconds, 1-9 fractional digits, `Z` / ±HH:MM / ±HHMM / no zone = UTC) and normalised to the 3-digit response form — `calc.py:36-82`, `validation.py:99-104`
- §2.5 — insert — ambiguity — trailing slash ignored in path matching — `app.py:27`
- §2.8 — insert — ambiguity — the three four-decimal ratios travel as JSON numbers — `calc.py:16-27`
- §2.10 items 6/7 — insert — ambiguity — absent/null/blank/non-string identifier is not a resolution failure; absent/empty body = empty object; string bounds measured as supplied; integers reject booleans; explicit null fails numeric/boolean options but equals omission for free-text notes — `validation.py:16-126`, `repo.py:8-12`
- §4 header — revise — mismatch — every `POST` returns 201, the clock endpoint being the only `POST` at 200 — verified across all `routes/*.py` plus `response.py:69-90`
- §5 intro — revise — mismatch — unrouted path / disallowed method answer `ERR_INVALID_REQUEST` at 404/405 (not 400), unexpected fault `ERR_INTERNAL_SERVER_ERROR` at 500; table untouched — `app.py:59-67`

Already uniquely pinned (no change): envelope shape and `response_type` values; pagination `meta` only on lists; `limit` default 10 / 1-100, `offset` default 0; `total_count` before the window; UUID `id`, never client-supplied; `version` 1 + `updated_at == created_at` on creation; `AbsorptionReview` carrying no `updated_at`/`version`; unset fields rendered null; 3-fractional-digit instants; clock epoch `2026-08-01T00:00:00Z` with no wall-clock fallback (`db.py:17`); half-up rounding away from zero; per-entity response field sets (all nine serializers); path/body 404 code families; and the error catalogue itself — `errors.py` and the §5 table match exactly in both directions, 53 identifiers with identical status codes.

### Pass 2 — community / phasing slice (subagent summary, verbatim)

- Size: 456 lines / 101,435 chars at entry -> 456 lines / 104,763 chars at exit (+3,328; all in-paragraph).
- Counts: 12 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.1 — insert — ambiguity — segregation-of-duties only fires when an actor was actually recorded: a null `plat_submitted_by_user_id` / `concession_requested_by_user_id` lets any decider through — `routes/communities.py:126` (identical at `routes/leases.py:150`)
- §2.3 — insert — ambiguity — a list filter is an exact string comparison; an unrecognised/wrong-case/empty value matches nothing rather than erroring; an unoffered query parameter is ignored — `routes/reads.py:25-33` (pass 1's explicit handoff item, confirmed)
- §3.1 — revise — ambiguity — `market_code` is "2-8 characters carrying no lowercase letter" rather than "2-8 uppercase characters" — `routes/communities.py:56`
- §3.1 — insert — ambiguity — a duplicate phase `sequence_index` is `ERR_DUPLICATE_RESOURCE` (PRD stated the rule with no code) — `routes/phases.py:69`
- §3.1 — revise — mismatch — PRD claimed a self-predecessor yields `ERR_INVALID_PHASE_PREDECESSOR`; no such check exists. Revised to: the link must resolve to an already-persisted phase (`ERR_PHASE_NOT_FOUND` otherwise, so self-reference is unrepresentable) and only the same-community requirement produces `ERR_INVALID_PHASE_PREDECESSOR` — `routes/phases.py:44-48,71`
- §3.1 — insert — ambiguity — homesite creation consults neither the phase's construction status nor the community's `plat_status`/posture, and has no `kind` check: targeting an `AMENITY` phase always trips `ERR_PRODUCT_MIX_EXCEEDED` — `routes/homesites.py:26-57`
- §3.2 — insert — ambiguity — `plat_package_reference` required, non-blank, no upper length bound — `routes/communities.py:109`
- §3.2 — insert — ambiguity — `decision_note`, when supplied, must be non-blank, otherwise unbounded — `routes/communities.py:131`
- §3.3 — insert — ambiguity — `occupancy_certificate_number` required/non-blank/unbounded; because `PLANNED` is the only gate, a second certificate on a still-`PLANNED` home legally overwrites both stored values — `routes/homesites.py:88-93`
- §3.3 — insert — mismatch + ambiguity — `homesite_ids` members that are null/blank/non-string give `ERR_HOMESITE_NOT_FOUND`; the empty array is legal and tests none of the per-home gates, so an empty first release still drives `UNDER_CONSTRUCTION -> SECTIONS_RELEASED` while leaving all counters, `lifecycle_status` and `facility_status` untouched; a repeated member is released once — `routes/phases.py:147-180`
- §3.4 — insert — ambiguity — `halt_reason` required, non-blank, any length — `routes/phases.py:206`
- §3.4 — insert — ambiguity — resume's `plat_status` gate is checked after the phase's own status and reported as `ERR_INVALID_PLAT_STATE`; resume takes no payload — `routes/phases.py:253-256`
- §3.11 — insert — ambiguity — `pm_company_name` is 1-120 characters and not blank — `routes/communities.py:215`
- §3.11 — insert — ambiguity — valuation's `basis` comes from the query parameter, falling back to a body field only when the parameter is absent; unrecognised/empty/absent-everywhere is `ERR_INVALID_REQUEST` — `routes/reads.py:60-65`

Already uniquely pinned (no change): community registration defaults and derived-field initials; `product_mix` key-set/sum validation; name+market_code duplicate rule; phase `HOUSING`/`AMENITY` field pairings and window ordering; the plat state machine, revision-round cap and `ERR_SINGLE_OWNERSHIP_COVENANT_REQUIRED`; the posture three-way decision, strict 0.5000 amenity gate, all five counters and the no-amenity-phase 1.0000 rule; construction-start's four gates incl. the `ERR_PHASE_CONCURRENCY_LIMIT`-for-predecessor quirk and the status-agnostic 48h same-kind gap; section-release gates and the `PUBLISHED`-regardless-of-`effective_from` schedule check; first-release lifecycle/facility moves; both completion branches; the full five-hop halt cascade incl. unconditional 7,500c ACTIVE-lease credits, `POSTURE_FREEZE` delisting, lease cancellation + concession revocation and program-ledger settlement; resume's conditional relist and never-rewritten `released_at`; the entire absorption pacing formula, clamps, posture penalty and tier bands; `created_at`-ascending cascade/list ordering; pm-transition's four gates and both effective-from branches; facility resize and conversion preconditions; and every row of the §4 role table for these 32 endpoints.

No pass-1 edit judged wrong; none reverted.

### Pass 3 — leasing / pricing / turn / valuation slice (subagent summary, verbatim)

- Size: 456 lines / 104,763 chars at entry -> 456 lines / 109,936 chars at exit (+5,173; all in-paragraph — one interim edit that created a new §2.7 paragraph was merged back into the existing one).
- Counts: 19 ambiguity-pins, 6 mismatch-revisions (25 changes).

Mismatch revisions:
- §2.9 — revise — "Any role may drive it" was false: the clock endpoint is authorised for the six operator roles only; a `Household` caller gets `ERR_UNAUTHORIZED` (matching the §4 row) — `routes/clock.py:18`, `middleware.py:14`
- §3.7 — revise — `active_lease_count` "rising when a lease is signed" was wrong; `DRAFT` is already in the open set, so it rises at drafting and falls on cancellation or on reaching `ENDED` — `services/community.py:18,33`
- §3.9 — revise — signature hop zero's "the household's `active_lease_count` reflects the new open lease" now says it is refreshed and comes out unchanged — `routes/leases.py:229`
- §3.8 — revise — a concession request against a lease outside `DRAFT`/`PENDING_SIGNATURE` reports `ERR_CONCESSION_PROGRAM_NOT_ACTIVE`, not `ERR_INVALID_LEASE_STATE`; lease-state, program-status and program-community are one combined gate — `routes/leases.py:127-130`
- §3.8 — revise — under `UPFRONT_FREE_RENT`, `monthly_concession_credit_cents` is a full month of gross only when the total reaches one month, and `first_period_charge_cents` is 0 only then; `free_weeks` 0 leaves the schedule empty so the concession never reaches `EXHAUSTED` — `services/concession.py:32-43,64-67`
- §3.8 — revise — `period_index` is schema-checked first (integer, >= 1); a below-1 or non-integer value is `ERR_INVALID_REQUEST`, not `ERR_CONCESSION_PERIOD_OUT_OF_ORDER` — `routes/leases.py:263`

Ambiguity pins:
- §2.7 — `expected_community_version` must be a present, non-negative integer; a bad one is `ERR_INVALID_REQUEST`, not 412 — `routes/pricing_routes.py:28`
- §3.5 — the indexed derivation (`ERR_RENT_SCHEDULE_NOT_FOUND` / `ERR_SCHEDULE_ALREADY_SUPERSEDED` / `ERR_ABSORPTION_REVIEW_NOT_FOUND`) runs after the version check but before the posture gate and the duplicate-triple test; the below-one-cent rejection is last — `routes/pricing_routes.py:50-76`
- §3.5 x2 — baseline ranking and latest-review ranking each carry a third tiebreak of descending server creation order — `services/pricing.py:42,85`
- §3.6 — `amortization_mode` is a required field; `eligible_product_types` is a required non-empty array stored verbatim, duplicates neither refused nor de-duplicated — `routes/pricing_routes.py:116-125,144`
- §3.7 — `email` is a non-blank string with no upper bound; uniqueness is an exact comparison — `routes/households.py:26,33-35`
- §3.7 — the four draft gates fire in §2.10 order (lifecycle, posture, home, household), not the order the prose lists them — `routes/leases.py:51-59`
- §3.7 — `end_date` carries the time of day and clamps the day of month down to the target month's last day — `calc.py:add_months` via `routes/leases.py:69`
- §3.7 — pricing-schedule selection's residual `created_at` tie goes to the last-persisted schedule — `services/pricing.py:42,56`
- §3.8 — building the schedule also zeroes `credits_applied_count` — `services/concession.py:76`
- §3.8 — `decision_note` must be non-blank when supplied, otherwise unbounded — `routes/leases.py:155`
- §3.8 — a `REJECT` does not wind back `net_effective_rent_cents` — `services/concession.py:79-86`
- §3.8 — revocation rewrites nothing on the lease; totals drop purely because `REVOKED` leaves the committed status set — `services/concession.py:89-96`
- §3.9 — `signed_by_name` is a required non-blank string of 1-120 chars — `routes/leases.py:203`
- §3.10 — the overlap test weighs every earlier order on the home whatever its `status` — `routes/turns.py:50-53`
- §3.10 — the rework buffer is forward-only and status-agnostic; exactly 48 h is acceptable; a window wholly before a prior same-scope order is not tested — `routes/turns.py:58-63`
- §3.10 — the capacity cap counts only orders still `SCHEDULED`; completion releases the technicians — `services/turn.py:76-78`
- §3.10 — completing before the clock reaches `window_start` is the same `ERR_INVALID_TURN_STATE` — `routes/turns.py:112`
- §3.10 — recoverable-cap ranking's third tiebreak — `services/turn.py:41-46`
- §3.11 — the division-by-zero case: when `value_cents` <= 0, a zero commitment reports `loan_to_value_bps` 0 and any positive commitment reports the sentinel `999999999`, which fails every covenant test — `services/valuation.py:61-68`

Already uniquely pinned (no change): fee bracket thresholds/surcharges and the four-step order; `total_concession_cents` rounded exactly once; both amortization layouts' sum invariant and the residual-in-final-period rule; mode-independent `net_effective_rent_cents`; both budget tests on approval; credit posting arithmetic and the `AMORTIZING -> EXHAUSTED` exit; the segregation check on concession decisions (pass 2's §2.1 clause covers the null-requester case, not duplicated); income qualification at 3x; the five signature hops incl. the 0.7500 stabilization and `facility_status` hop; activation's posture-conditional 7,500-cent credit; the `EXECUTED` cancellation branch and its revert; notice leaving occupancy untouched; turn cost buckets, scope rates and the 80,000-cent opex cap; window well-formedness (whole hours, <= 240 h, not in the past); publication supersession, `published_by_user_id` and the community `version` bump; `MANUAL` vs indexed rent handling incl. ignoring `asking_rent_cents`; the step's round-then-clamp order and ±20,000-cent clamp; program supersession and `program_code` uniqueness; both valuation bases' income assembly, blended market rent, vacancy/opex/cap-rate chain and `covenant_satisfied` threshold; the clock's rewind rule and single PM-transition side effect.

Table checks: §4 = 49 endpoint rows, §5 = 53 error rows, file still ends at the last §5 row. No pass-1 or pass-2 edit reverted or contradicted.

### Orchestrator verification of Step 9

Independently re-measured: `PRD.md` 456 lines / 95,985 chars -> `PRD_FINALIZED.md` 456 lines / 96,581 -> `PRD_COMPLETED.md` 456 lines / **109,936** (+13,355 chars / +13.9% over `PRD.md`; 47 lines changed relative to `PRD_FINALIZED.md`). `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — i.e. the scan genuinely ran, which is the known failure signature to guard against. Structural integrity re-checked from the file: §4 still has exactly 49 endpoint rows, §5 exactly 53 `ERR_*` rows, the file still ends on the complete final table row `| ERR_LTV_COVENANT_BREACH | 409 |`, and `grep -ci "scaffold|harder than expert"` returns 0 (no scaffold or difficulty-directive leakage). Totals across the three passes: 42 ambiguity-pins, 10 mismatch-revisions, 52 edits, zero new sections and zero net new lines.

No sweep re-run was needed after Steps 8 and 9 — both steps touch only PRD derivative documents (`PRD_FINALIZED.md`, `PRD_COMPLETED.md`) and left `implementation/`, `test_suite/` and `test_helpers/` untouched, so the Step 7 clean 8-round sweep (8/8 rounds at 125/125) remains the valid final test evidence.

## Pipeline complete — 2026-09-05T04:10:00.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml` + `SCAFFOLD_DIFFICULTY_DESIGN.yaml` + `SCAFFOLD_CORNER_DESIGN.yaml`; `test_helpers/` (9 modules) + `test_suite/` (12 modules, 125 tests); `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`; `workspace/implementation/` (25 Python modules + `start.sh` + `requirements.txt`) with `results.{1..8}.json` from the clean final sweep. `workspace/sweep.sh` is retained as the reproducible setsid sweep launcher.
