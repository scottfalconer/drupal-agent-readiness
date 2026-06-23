// RETAINED SCRATCH / RUN PROVENANCE — n=10 fully-blind rerun on stock Haven to
// firm up the verdict-gap headline (n=3 was noisy). 5 raw + 5 eq clones; each
// (model, arm) runs n=10 via two sequential waves of 5 (1:1 with the clone pool,
// so no two concurrent agents share a SQLite DB). Recorded results:
// experiments/alias-safety-haven-n10-fullyblind-v0/.
export const meta = {
  name: 'alias-safety-n10-fullyblind',
  description: 'n=10 fully-blind alias-safety A/B on stock Haven (Haiku + Opus, raw vs site_architecture)',
  phases: [
    { title: 'haiku-A' }, { title: 'haiku-B' }, { title: 'opus-A' }, { title: 'opus-B' },
  ],
}

const SUB = '<workspace>/tmp/agent-readiness/sub-haven-n10'
const CANDIDATES = ['/this-is-free-xyz', '/moderated-content', '/blog', '/search', '/admin/content/files', '/admin/content/media/scheduled']
const RAW = [1, 2, 3, 4, 5].map((i) => `${SUB}/raw-${i}`)
const EQ = [1, 2, 3, 4, 5].map((i) => `${SUB}/eq-${i}`)
const PATHLIST = CANDIDATES.join(', ')
log(`n10 fully-blind: candidates=${CANDIDATES.length} rawClones=${RAW.length} eqClones=${EQ.length}`)

const props = {}
for (const p of CANDIDATES) props[p] = { type: 'object', additionalProperties: false, properties: { safe: { type: 'boolean' }, reason: { type: 'string' } }, required: ['safe', 'reason'] }
const SCHEMA = { type: 'object', additionalProperties: false, properties: { assessments: { type: 'object', additionalProperties: false, properties: props, required: CANDIDATES }, command_count: { type: 'integer' } }, required: ['assessments', 'command_count'] }

const RAW_TOOLING = "Tooling: CORE drush only. The site_architecture module is NOT installed; `site-architecture:*` commands do not exist. Inspect with `vendor/bin/drush php:eval '...'` against `router.no_access_checks`, `path_alias.manager`, and the `view` entity storage. If you hit \"database is locked\", wait briefly and retry."
const EQ_TOOLING = "Tooling: drush WITH the site_architecture module installed. `vendor/bin/drush site-architecture:path-owner <path> --format=json` reports what claims or owns a path on this site. You may use it and any core drush command. If you hit \"database is locked\", wait briefly and retry."

function blindPrompt(arm, root) {
  const tooling = arm === 'raw' ? RAW_TOOLING : EQ_TOOLING
  return `You are helping build content on a running Drupal site (read-only inspection). You are about to create several new content pages, each as a node with a specific URL alias. Before creating them, check each candidate path: is it SAFE to use as the URL alias of a new node, or is that path already claimed by something on the site? If a path is not safe, briefly say what claims it.\n\nFor each path report safe (bool) and a short reason.\n\nResolve against the LIVE site. Site root with drush: ${root}\nRun drush from that dir and ALWAYS prefix \`PHP_INI_SCAN_DIR=/tmp/ar-phpini\` (system PHP is 128M; Drupal OOMs otherwise).\n\n${tooling}\n\nConstraints: Read-only. Do NOT modify config/content. Do NOT read anything under <workspace>/agent_readiness/. Work only from the live site.\n\nCandidate paths: ${PATHLIST}\n\nReport your assessment for ALL of those paths plus the integer count of shell commands you ran (command_count).`
}

async function runWave(model, wave, baseN) {
  const title = `${model}-${wave}`
  phase(title)
  const tasks = []
  for (let i = 0; i < 5; i++) {
    tasks.push({ arm: 'raw', n: baseN + i, clone: RAW[i] })
    tasks.push({ arm: 'equipped', n: baseN + i, clone: EQ[i] })
  }
  return parallel(tasks.map((t) => () =>
    agent(blindPrompt(t.arm, t.clone), { model, label: `n10:${model}:${t.arm}-${t.n}`, phase: title, schema: SCHEMA })
      .then((a) => ({ condition: 'blind', model, arm: t.arm, n: t.n, answer: a }))
      .catch(() => ({ condition: 'blind', model, arm: t.arm, n: t.n, answer: null }))
  ))
}

const hA = await runWave('haiku', 'A', 1)
const hB = await runWave('haiku', 'B', 6)
const oA = await runWave('opus', 'A', 1)
const oB = await runWave('opus', 'B', 6)

return { blind: [...hA, ...hB, ...oA, ...oB] }
