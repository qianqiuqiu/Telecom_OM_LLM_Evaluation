export const meta = {
  name: 'teleqna-relevance-relabel-v3',
  description: 'Relabel the 936 questions whose v2 label cited rule 2, with Haiku and rubric v3',
  phases: [{ title: 'Label', model: 'haiku', detail: '38 batches of up to 25 questions' }],
}

const ROOT = '/Users/qianqiu/Desktop/project/Telecom_OM_LLM_Evaluation'
const BATCHES = Array.from({ length: 38 }, (_, i) => `batch_${String(i).padStart(3, '0')}.jsonl`)

const SCHEMA = {
  type: 'object',
  properties: {
    labels: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          relevance: { type: 'integer', enum: [0, 1, 2, 3] },
          dimension: { type: 'string', enum: ['RAN', 'CORE', 'TRANSPORT', 'OAM', 'SERVICE', 'SECURITY', 'OTHER'] },
          reason: { type: 'string' },
        },
        required: ['id', 'relevance', 'dimension', 'reason'],
      },
    },
  },
  required: ['labels'],
}

const prompt = batch => `You are labeling telecom multiple-choice questions for an evaluation project.

1. Read the labeling guideline ${ROOT}/docs/rubrics/ops_relevance_v3.md (written in Chinese) and follow it exactly, applying the numbered boundary rules in order.
2. Read ${ROOT}/results/audit/relevance/v3_batches/${batch}. Each line is one question with its options and correct answer.
3. For EVERY question in that file (there are up to 25 lines; label all of them, none skipped) give: relevance (0-3), dimension (one primary capability dimension), and a one-sentence reason citing the rule you applied.

Copy each "id" EXACTLY as written in the file (e.g. "question 1234") — do not retype numbers from memory. Do not open any other files. Return all labels via the structured output.`

const results = await parallel(BATCHES.map(b => () =>
  agent(prompt(b), { label: `label:${b.replace('.jsonl', '')}`, phase: 'Label', schema: SCHEMA, model: 'haiku' })
    .then(r => r ? { batch: b, labels: r.labels } : { batch: b, labels: null })))

const failed = results.filter(r => !r || !r.labels).map(r => r && r.batch)
if (failed.length) log(`Failed batches: ${failed.join(', ')}`)
return { results: results.filter(r => r && r.labels), failed }
