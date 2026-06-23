// RETAINED SCRATCH / RUN PROVENANCE — not a parameterized library.
// The SUB/LABEL/CANDIDATES consts below were hand-edited per substrate run
// (workflow args injection proved unreliable). The exact per-run config for each
// recorded experiment lives in that experiment's dir as candidates.json +
// ground-truth.json; see experiments/README.md. To reproduce, set the three
// consts to a substrate's clones/candidates and re-run.
export const meta = {
  name: 'alias-safety-substrate-ab',
  description: 'Knowledge-blind alias-safety A/B (Haiku + Opus, raw vs site_architecture) on one parameterized substrate',
  phases: [
    { title: 'Haiku', detail: 'blind; raw vs equipped; n=3' },
    { title: 'Opus', detail: 'blind; raw vs equipped; n=3' },
  ],
}

// Substrate config (hardcoded per run for reliability; args injection proved flaky).
const SUB = '<workspace>/tmp/agent-readiness/sub-convivial'
const LABEL = 'convivial-fullyblind'
const CANDIDATES = ['/this-is-free-xyz', '/zzz-unclaimed-a015b1', '/admin/content/pages', '/admin/content/media/scheduled', '/admin/structure/taxonomy/scheduled']
const RAW = [`${SUB}/raw-1`, `${SUB}/raw-2`, `${SUB}/raw-3`]
const EQ = [`${SUB}/eq-1`, `${SUB}/eq-2`, `${SUB}/eq-3`]
const PATHLIST = CANDIDATES.join(', ')
log(`substrate=${LABEL} candidates=${CANDIDATES.length} rawClones=${RAW.length} eqClones=${EQ.length}`)

function assessmentsSchema() {
  const props = {}
  for (const p of CANDIDATES) props[p] = { type: 'object', additionalProperties: false, properties: { safe: { type: 'boolean' }, reason: { type: 'string' } }, required: ['safe', 'reason'] }
  return { type: 'object', additionalProperties: false, properties: props, required: CANDIDATES }
}
const SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { assessments: assessmentsSchema(), command_count: { type: 'integer' } },
  required: ['assessments', 'command_count'],
}

const RAW_TOOLING = "Tooling: CORE drush only. The site_architecture module is NOT installed; `site-architecture:*` commands do not exist. Inspect with `vendor/bin/drush php:eval '...'` against `router.no_access_checks`, `path_alias.manager`, and the `view` entity storage. If you hit \"database is locked\", wait briefly and retry."
const EQ_TOOLING = "Tooling: drush WITH the site_architecture module installed. `vendor/bin/drush site-architecture:path-owner <path> --format=json` reports what claims or owns a path on this site. You may use it and any core drush command. If you hit \"database is locked\", wait briefly and retry."

function blindPrompt(arm, root) {
  const tooling = arm === 'raw' ? RAW_TOOLING : EQ_TOOLING
  return `You are helping build content on a running Drupal site (read-only inspection). You are about to create several new content pages, each as a node with a specific URL alias. Before creating them, check each candidate path: is it SAFE to use as the URL alias of a new node, or is that path already claimed by something on the site? If a path is not safe, briefly say what claims it.\n\nFor each path report safe (bool) and a short reason.\n\nResolve against the LIVE site. Site root with drush: ${root}\nRun drush from that dir and ALWAYS prefix \`PHP_INI_SCAN_DIR=/tmp/ar-phpini\` (system PHP is 128M; Drupal OOMs otherwise).\n\n${tooling}\n\nConstraints: Read-only. Do NOT modify config/content. Do NOT read anything under <workspace>/agent_readiness/. Work only from the live site.\n\nCandidate paths: ${PATHLIST}\n\nReport your assessment for ALL of those paths plus the integer count of shell commands you ran (command_count).`
}

// 6 cells per model: raw x3 (raw clones 0..2) + equipped x3 (eq clones 0..2)
function cells() {
  const out = []
  for (let n = 0; n < 3; n++) {
    out.push({ arm: 'raw', n: n + 1, clone: RAW[n] })
    out.push({ arm: 'equipped', n: n + 1, clone: EQ[n] })
  }
  return out
}

async function runModel(model) {
  phase(model === 'haiku' ? 'Haiku' : 'Opus')
  const list = cells()
  const results = await parallel(list.map((c) => () =>
    agent(blindPrompt(c.arm, c.clone), {
      model,
      label: `${LABEL}:blind:${model}:${c.arm}-${c.n}`,
      phase: model === 'haiku' ? 'Haiku' : 'Opus',
      schema: SCHEMA,
    }).then((a) => ({ condition: 'blind', model, arm: c.arm, n: c.n, answer: a })).catch(() => ({ condition: 'blind', model, arm: c.arm, n: c.n, answer: null }))
  ))
  return results
}

const haiku = await runModel('haiku')
const opus = await runModel('opus')

return { blind: [...haiku, ...opus].filter(Boolean) }
