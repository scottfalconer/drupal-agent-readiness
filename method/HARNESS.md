# alias-safety harness — reproducible, bring-your-own-agent

This is the harness behind the alias-safety finding (see
`../evidence/experiments/alias-safety-SYNTHESIS.md`). It is vendor-neutral: prepare a
substrate, run **any** agent against it through a documented contract, and score
the result against a core-only referee. The site clones are disposable; the
scripts and the per-run artifacts are what's retained.

## 1. Prepare a substrate

```bash
python3 agent_readiness/scripts/prepare_alias_safety.py \
  --base haven-clean-install \
  --out tmp/agent-readiness/sub-X \
  --n-raw 5 --n-eq 5 \
  --php-ini-scan-dir /tmp/ar-phpini   # a dir with a memory_limit .ini; drush OOMs at low limits
```

Produces `sub-X/` with `raw-1..5/` (no module), `eq-1..5/` (site_architecture
installed), `candidates.json` (agent-facing path list only),
`candidate-notes.json` (human/provenance notes), `ground-truth.json` (the
referee), and `substrate.json` (manifest). Different sites yield different
candidate paths — the harness does not hardcode them.

## 2. The agent contract

Each headline run: an agent is pointed at one clone and asked the
**fully-blind** question (no hint that disabled Views matter), and returns an
assessment for every candidate path. Output schema (`safe` + free-text `reason`
per path, plus `command_count`): see `prepare`'s `candidates.json` for the paths; the schema is
`{ "assessments": { "<path>": {"safe": bool, "reason": str}, ... }, "command_count": int }`.

Prompt (substitute the arm's tooling line). This is also captured in
`prompts/assess.alias_safety.fully_blind.md`:

> Inspect this running Drupal site (read-only). For each candidate path decide:
> is it SAFE to use as the URL alias of a new node, or is that path already
> claimed by something on the site? If not safe, say what claims it. Candidate
> paths: `<from candidates.json>`. Resolve against the LIVE site with drush here,
> always prefixed `PHP_INI_SCAN_DIR=...`. **[raw]** Use core drush only; the
> site_architecture module is not installed. **[equipped]** The site_architecture
> module is installed: `vendor/bin/drush site-architecture:path-owner <path>
> --format=json` reports what claims/owns a path. Read-only; do not read anything
> under `agent_readiness/`. Return `safe` + a short reason for every path, plus
> `command_count`.

The told/control variant is `prompts/assess.alias_safety.told.md`. It
intentionally tells the agent the hidden safety criterion and is not the
headline finding prompt.

### Example runners

- **Claude (workflow):** see `../repro/scripts/_n10_workflow.js` / `../repro/scripts/_substrate_ab_workflow.js`
  (retained run-specific scratch; set the clone/candidate consts and run via the
  Workflow tool).
- **Codex (OpenAI):** writes the schema'd answer straight to a file —
  ```bash
  codex exec -C <clone> --dangerously-bypass-approvals-and-sandbox \
    --output-schema tmp/agent-readiness/sub-X/alias_safety.schema.json \
    -o <out>/raw-N/answer.json "<prompt>"
  ```
  (If your Codex CLI profile is pinned to the default service tier, this codex-cli wants
  `fast`/`flex`; run with a `CODEX_HOME` pointing at a corrected config copy.)
- **Gemini:** `gemini -m <model> --yolo -p "<prompt that writes answer.json>"`.

## 3. Score

CLI-vendor runs assemble into the same shape the Claude workflow emits, then go
through one scorer:

```bash
python3 agent_readiness/scripts/assemble_cli_runs.py \
  --runs-dir tmp/agent-readiness/xvendor-runs/codex --model gpt-5.5-codex \
  --out /tmp/codex-wf.json

python3 agent_readiness/scripts/process_model_ab.py \
  --workflow-output /tmp/codex-wf.json \
  --state-json tmp/agent-readiness/sub-X/ground-truth.json \
  --out-dir agent_readiness/experiments/alias-safety-<name>
```

The scorer writes per-run `answer.json`/`evaluator.json`/`meta.json`, the raw
workflow output, ground truth, candidate paths, a results JSON (with model IDs +
timestamp), and a finding table. Metrics: **verdict** (flagged the latent path
unsafe — the actionable answer) and **reasoned** (supporting heuristic — did the
reason name the *disabled* nature). Read the synthesis, not the percentage alone.
