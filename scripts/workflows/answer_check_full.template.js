// 全量答案核验 workflow 模板。由 scripts/answer_check_full.py 填入标准答案映射与批次数后生成 workflow.js。
// 阶段：Haiku 盲答 → 不一致的题由两名 Haiku 核查 → Haiku 判有问题的题由两名默认模型复查。
export const meta = {
  name: 'teleqna-answer-check-full',
  description: 'Two-stage answer verification of the cleaned TeleQnA set: Haiku blind solve and investigation, default-model review of Haiku-flagged items',
  phases: [
    { title: 'Blind solve', model: 'haiku', detail: 'Haiku answers without seeing the gold answer' },
    { title: 'Screen', model: 'haiku', detail: 'two Haiku investigators per disagreement' },
    { title: 'Review', detail: 'two default-model investigators per Haiku-flagged item' },
  ],
}

const GOLD = __GOLD__
const N_BATCHES = __N_BATCHES__
const DIR = '/Users/qianqiu/Desktop/project/Telecom_OM_LLM_Evaluation/results/audit/answer_check_full'
const BATCHES = Array.from({ length: N_BATCHES }, (_, i) => `batch_${String(i).padStart(3, '0')}.jsonl`)
const CHUNK = 5

const SOLVE_SCHEMA = {
  type: 'object',
  properties: {
    answers: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          choice: { type: 'integer' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
        required: ['id', 'choice', 'confidence'],
      },
    },
  },
  required: ['answers'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          verdict: { type: 'string', enum: ['correct', 'wrong', 'ambiguous', 'unverifiable'] },
          correct_option: { type: ['integer', 'null'] },
          evidence: { type: 'string' },
          source: { type: 'string' },
        },
        required: ['id', 'verdict', 'correct_option', 'evidence', 'source'],
      },
    },
  },
  required: ['verdicts'],
}

const solvePrompt = batch => `Read ${DIR}/blind_batches/${batch} with the Read tool. Each line is a multiple-choice question about telecommunications standards (3GPP, IEEE, ETSI, IETF) with numbered options.

Answer every question in that file. Read ONLY that one file — do not open any other file under ${DIR} (other files contain answer keys; looking at them would invalidate this blind test). Do not search the web; answer from your own knowledge.

For each question pick exactly one option number and give your confidence (high / medium / low). Copy each "id" exactly as written in the file. Return all answers via the structured output.`

const investigatePrompt = items => `You are verifying the answer key of a telecom multiple-choice benchmark (TeleQnA). For each question below, decide whether the MARKED correct answer is actually correct.

Read ${DIR}/items.json with the Read tool and look up these question ids (fields: question, options, gold = 1-based index of the marked answer):
${items.map(it => `- ${it.id}  (marked answer: option ${it.gold}; ${it.notes})`).join('\n')}

Any other answers mentioned are unverified hints about where the doubt is; they may be wrong. Work independently.

Verdicts:
- "correct": the marked option is right and clearly the best option.
- "wrong": the marked option is incorrect; give the correct option number in correct_option (null if none of the options is correct).
- "ambiguous": more than one option is defensible, or the question is underspecified/flawed so the marked answer can't be called uniquely right.
- "unverifiable": you cannot establish the answer with reasonable confidence.

Prefer primary sources: use WebSearch / WebFetch to check the relevant 3GPP TS/TR, IEEE standard, ETSI document or RFC when your own knowledge is not certain. Put a short justification in "evidence" and the document / URL you relied on in "source" (write "own knowledge" if you did not consult a source). Return one verdict per question id via the structured output, copying ids exactly.`

const chunk = (arr, n) => Array.from({ length: Math.ceil(arr.length / n) }, (_, i) => arr.slice(i * n, i * n + n))
const tag = b => b.replace('.jsonl', '')

const investigate = (items, phase, model, batch) => parallel(chunk(items, CHUNK).flatMap((c, ci) =>
  ['inv1', 'inv2'].map(inv => () => agent(investigatePrompt(c) + `\n\n(Investigator id: ${inv}. Work independently.)`, {
    label: `${phase.toLowerCase()}:${tag(batch)}:${ci}:${inv}`, phase, schema: VERDICT_SCHEMA, ...(model ? { model } : {}),
  }).then(r => r ? r.verdicts.map(v => ({ ...v, investigator: inv, stage: phase })) : null))))
  .then(rs => rs.filter(Boolean).flat())

const results = await pipeline(
  BATCHES,
  batch => agent(solvePrompt(batch), { label: `solve:${tag(batch)}`, phase: 'Blind solve', schema: SOLVE_SCHEMA, model: 'haiku' }),
  async (solved, batch) => {
    if (!solved) { log(`Blind solve failed for ${batch}`); return { batch, solves: null } }
    const flagged = solved.answers
      .filter(a => GOLD[a.id.split(' ').pop()] !== undefined && a.choice !== GOLD[a.id.split(' ').pop()])
      .map(a => ({ id: a.id, gold: GOLD[a.id.split(' ').pop()], notes: `a blind solver chose option ${a.choice}` }))
    const screen = flagged.length ? await investigate(flagged, 'Screen', 'haiku', batch) : []
    // Haiku 两名核查者都判 correct 的题视为通过；其余（含核查缺失）交默认模型复查
    const toReview = flagged.filter(f => {
      const vs = screen.filter(v => v.id === f.id)
      return !(vs.length >= 2 && vs.every(v => v.verdict === 'correct'))
    }).map(f => ({ ...f, notes: 'an earlier screening raised doubts about this item' }))
    const review = toReview.length ? await investigate(toReview, 'Review', null, batch) : []
    return { batch, solves: solved.answers, flagged: flagged.map(f => f.id), reviewed: toReview.map(f => f.id), verdicts: [...screen, ...review] }
  },
)

const ok = results.filter(r => r && r.solves)
const failed = results.filter(r => !r || !r.solves).map(r => r && r.batch)
log(`batches ok ${ok.length}/${BATCHES.length}; flagged ${ok.reduce((s, r) => s + r.flagged.length, 0)}; reviewed ${ok.reduce((s, r) => s + r.reviewed.length, 0)}`)
return { results: ok, failed }
