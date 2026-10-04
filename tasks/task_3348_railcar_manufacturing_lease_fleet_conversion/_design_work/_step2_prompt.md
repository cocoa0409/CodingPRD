# Step 2 task spec — scaffold generation

You are the **scaffold generator** for a PRD benchmark task. Your job: read the skill
specification, then produce three YAML artifacts on disk.

## 1. Read the specification

Read `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/SKILL.md` in full to
understand the generation specification. It defines the exact section layout (§1.0–§1.9), the
required keys, the difficulty rules, the corner-design index format, and the lint validator.

## 2. Scenario (verbatim — do not modify, do not summarize)

Railcar Manufacturing & Lease Fleet Conversion (Trinity Industries): order backlog management
across car types with production line configuration and changeover planning, component supply for
wheelsets, castings and coatings with lead times exceeding order-to-delivery windows, lease fleet
decisions where manufactured cars are retained for leasing rather than sold with capital
allocation implications, lease structures across full-service and net leases with maintenance
responsibility differences, regulatory retrofit requirements driving fleet modification programs
with shop capacity scheduling, car assignment to lessees with per-diem, mileage and utilization
accounting, secondary market sales of lease fleet cars with portfolio management, scrapping
decisions at end of regulatory life

## 3. Difficulty target

The caller's instruction is **"Generate task much harder than expert level!"**. This applies to
you, the scaffold generator, as the depth/breadth target. Aim ABOVE the skill's default expert
level: more entities, deeper and more cross-coupled state machines, more interacting calculations,
more ordered-validation interactions, and more cross-entity constraints. Ensure §1.8 instantiates
every difficulty rule with multiple executable structured test recipes and §1.9 covers the
remaining testable breadth.

## 4. Output files (all three required)

Write to `/home/ubuntu/github/CodingPRD/tasks/task_3348_railcar_manufacturing_lease_fleet_conversion/`:

1. `SCAFFOLD.yaml` — sections §1.0–§1.7. Must contain NEITHER a `scaffold_difficulty_design` NOR a
   `scaffold_corner_design` key.
2. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8).
3. `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9).

The task directory already exists and its `workspace/` subdirectory is pre-created. Do NOT create
any other `task_*` directory and do NOT compute a task index.

## 5. Output budget — CRITICAL

This model endpoint caps output per message and **silently truncates oversized tool calls**. Write
files INCREMENTALLY, exactly ONE tool call per assistant message:

- Message 1: `Write` SCAFFOLD.yaml with §1.0–§1.3.
- Message 2+: append §1.4–§1.7 (use `Edit` to replace a trailing sentinel comment such as
  `# END_OF_SECTION_1_3`, or rewrite the file with accumulated content — whichever is safe for you).
- Then write `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), then `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9),
  each possibly across multiple messages.

Never batch two tool calls into one message. The endpoint duplicates parallel calls, so a batched
message returns copies of the first call.

## 6. Verification before you finish

For each of the three files run:

```
python3 -c "import yaml;d=yaml.safe_load(open('PATH'));print('PATH', list(d.keys())[:5])"
```

Confirm: SCAFFOLD.yaml parses with no `scaffold_difficulty_design` / `scaffold_corner_design` key;
the other two each parse with exactly their single required top-level key. If the skill ships a
`scaffold_lint.py`, run it and resolve reported problems.

## 7. Hard constraints

- **Do NOT look at any sibling task** under `/home/ubuntu/github/CodingPRD/tasks/` (no `ls`, glob,
  `grep`, or read of other `task_*/` directories, their `SCAFFOLD.yaml`,
  `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `PRD.md`, tests, or
  implementation). Generate purely from the scenario above plus the skill's own specification.
  Peeking biases the output toward prior designs and defeats the purpose of a fresh scaffold.
- **PROCESS SAFETY**: many other pipelines run concurrently on this host. Never use broad kill
  patterns (`pkill -f`, `killall`, or `pgrep ... | xargs kill`) — they kill other tasks' servers
  and can kill your own orchestrator process. Only kill PIDs you started yourself (save `$!` and
  kill exactly that PID), or rely on `prd-bench-local-run` to manage servers.

## 8. Report on exit

Return a concise summary: the three file paths written, their line counts, the
entity / state-machine / endpoint / error counts, and the depth/breadth instance counts in
§1.8 / §1.9.