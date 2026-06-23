// RETAINED SCRATCH / RUN PROVENANCE — the Haven told+soft-blind model A/B run.
// Substrate config is hardcoded (RAW/EQ/PATHS). Recorded results + per-run
// artifacts are under experiments/alias-safety-haven-told-softblind-v0/.
export const meta = {
  name: 'alias-safety-model-ab',
  description: 'Alias-safety A/B across Haiku 4.5 and Opus 4.8: does site_architecture path-owner help weaker vs capable agents catch disabled-view latent claims?',
  phases: [
    { title: 'Told', detail: 'criterion given; raw vs equipped; haiku vs opus; n=3' },
    { title: 'Blind', detail: 'knowledge-blind; raw vs equipped; haiku vs opus; n=3' },
  ],
}

const BASE = '<workspace>/tmp/agent-readiness'
const RAW = [`${BASE}/inventory-deleaked-equipped/site`, `${BASE}/as-raw-2`, `${BASE}/as-raw-3`, `${BASE}/as-raw-4`, `${BASE}/as-raw-5`, `${BASE}/as-raw-6`]
const EQ = [`${BASE}/aliassafety-equipped/site`, `${BASE}/as-eq-2`, `${BASE}/as-eq-3`, `${BASE}/as-eq-4`, `${BASE}/as-eq-5`, `${BASE}/as-eq-6`]
const PATHS = ['/this-is-free-xyz', '/moderated-content', '/blog', '/search', '/admin/content/files', '/admin/content/media/scheduled']
const PATHLIST = PATHS.join(', ')

function assessmentsSchema(valueProps, required) {
  const props = {}
  for (const p of PATHS) props[p] = { type: 'object', additionalProperties: false, properties: valueProps, required }
  return { type: 'object', additionalProperties: false, properties: props, required: PATHS }
}
const TOLD_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    assessments: assessmentsSchema(
      { safe: { type: 'boolean' }, blocker_kind: { type: ['string', 'null'], enum: ['entity', 'view', 'route', 'latent_disabled_view', null] } },
      ['safe', 'blocker_kind']),
    command_count: { type: 'integer' },
  },
  required: ['assessments', 'command_count'],
}
const BLIND_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    assessments: assessmentsSchema({ safe: { type: 'boolean' }, reason: { type: 'string' } }, ['safe', 'reason']),
    command_count: { type: 'integer' },
  },
  required: ['assessments', 'command_count'],
}

const RAW_TOOLING = "Tooling: CORE drush only. The site_architecture module is NOT installed; `site-architecture:*` commands do not exist. Inspect with `vendor/bin/drush php:eval '...'` against `router.no_access_checks`, `path_alias.manager`, and the `view` entity storage. If you hit \"database is locked\", wait briefly and retry."
const EQ_TOOLING = "Tooling: drush WITH the site_architecture module installed. `vendor/bin/drush site-architecture:path-owner <path> --format=json` reports what claims or owns a path on this site. You may use it and any core drush command. If you hit \"database is locked\", wait briefly and retry."

function commonHead(root, tooling) {
  return `Resolve against the LIVE site. Site root with drush: ${root}\nRun drush from that dir and ALWAYS prefix \`PHP_INI_SCAN_DIR=/tmp/ar-phpini\` (system PHP is 128M; Drupal OOMs otherwise).\n\n${tooling}\n\nConstraints: Read-only. Do NOT modify config/content. Do NOT read anything under <workspace>/agent_readiness/. Work only from the live site.\n\nCandidate paths: ${PATHLIST}\n\nReport your assessment for ALL six paths plus the integer count of shell commands you ran (command_count).`
}
function toldPrompt(arm, root) {
  const tooling = arm === 'raw' ? RAW_TOOLING : EQ_TOOLING
  return `You are assessing a running Drupal CMS/Haven site (read-only). For each candidate path, decide if it is SAFE to claim with a NEW node's URL alias.\n\nA path is UNSAFE if ANY of these holds: an active route, an active Views page display, or an entity canonical page already responds there; OR a DISABLED view declares that path as a page-display path (a latent claim — enabling that view later would collide). Otherwise SAFE. Resolve against the router, alias system, and ALL views including DISABLED ones.\n\nFor each path report safe (bool) and blocker_kind: 'entity' (canonical entity page), 'view' (active Views page), 'route' (module route), 'latent_disabled_view' (a disabled view declares it), or null if safe.\n\n${commonHead(root, tooling)}`
}
function blindPrompt(arm, root) {
  const tooling = arm === 'raw' ? RAW_TOOLING : EQ_TOOLING
  return `You are helping build content on a running Drupal CMS/Haven site (read-only inspection). You are about to create several new content pages, each as a node with a specific URL alias. Before creating them, check each candidate path: is it SAFE to use as the URL alias of a new node, or would using it cause a conflict — either right now, or after routine site configuration changes? If a path is not safe, briefly say what would conflict.\n\nFor each path report safe (bool) and a short reason.\n\n${commonHead(root, tooling)}`
}

function cells() {
  // 12 cells per condition: model x arm x n, each pinned to its own clone.
  const out = []
  const models = ['haiku', 'opus']
  models.forEach((model, mi) => {
    for (let n = 0; n < 3; n++) {
      out.push({ model, arm: 'raw', n: n + 1, clone: RAW[mi * 3 + n] })
      out.push({ model, arm: 'equipped', n: n + 1, clone: EQ[mi * 3 + n] })
    }
  })
  return out
}

async function runCondition(condition, schema, promptFn) {
  phase(condition === 'told' ? 'Told' : 'Blind')
  const list = cells()
  const results = await parallel(list.map((c) => () =>
    agent(promptFn(c.arm, c.clone), {
      model: c.model,
      label: `${condition}:${c.model}:${c.arm}-${c.n}`,
      phase: condition === 'told' ? 'Told' : 'Blind',
      schema,
    }).then((a) => ({ condition, model: c.model, arm: c.arm, n: c.n, answer: a })).catch(() => ({ condition, model: c.model, arm: c.arm, n: c.n, answer: null }))
  ))
  return results
}

const told = await runCondition('told', TOLD_SCHEMA, toldPrompt)
const blind = await runCondition('blind', BLIND_SCHEMA, blindPrompt)

return { told: told.filter(Boolean), blind: blind.filter(Boolean) }
