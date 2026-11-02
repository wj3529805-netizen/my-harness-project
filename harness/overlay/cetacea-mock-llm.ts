// Keyless scripted "model" for the CETACEA <-> deepseek-harness integration tests.
// Reads a JSON script from $CETACEA_MOCK_SCRIPT: {"steps":[{"tool":"mcp__cetacea__photo_get_task","args":{"task_id":"$last.task_id"}}], "final":"done"}
// Each step is one tool call; "$last.<key>" is replaced by a field of the previous tool result JSON.
// An empty "steps" array = a model that makes NO tool call (text only).
// Appends one JSON line per request to $CETACEA_MOCK_LOG (offered tool names, step index). MOCK ONLY.
import { appendFileSync, readFileSync } from 'node:fs'
import type { Context } from '@deepseek-ai/cordis'
import { ToolCallId, LlmAdapter, type GenerateOptions, type LlmResolvedModelInfo, type StreamChunk } from '@deepseek-ai/dsh-llm'
import type {} from '@deepseek-ai/dsh-tools'

interface Step { tool: string, args?: Record<string, unknown> }
interface Script { steps: Step[], final?: string }

function textOf(content: readonly { type: string, text?: string }[]): string {
  return content.filter(b => b.type === 'text').map(b => b.text ?? '').join('')
}

function resolveArgs(args: Record<string, unknown>, last: unknown): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(args)) {
    if (typeof value === 'string' && value.startsWith('$last.')) {
      const field = value.slice('$last.'.length)
      out[key] = (last as Record<string, unknown> | undefined)?.[field]
    } else out[key] = value
  }
  return out
}

class CetaceaMockAdapter extends LlmAdapter {
  override async resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    return { provider, id: model, name: model }
  }

  async * stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const script = JSON.parse(readFileSync(process.env.CETACEA_MOCK_SCRIPT as string, 'utf8')) as Script
    const toolMessages = options.messages.filter(m => m.role === 'tool')
    const index = toolMessages.length
    const log = process.env.CETACEA_MOCK_LOG
    if (log !== undefined) {
      appendFileSync(log, `${JSON.stringify({ step: index, tools: (options.tools ?? []).map(t => t.name) })}\n`)
    }
    if (index < script.steps.length) {
      let last: unknown
      const prev = toolMessages.at(-1)
      if (prev !== undefined) {
        try { last = JSON.parse(textOf(prev.content as never)) } catch { last = undefined }
      }
      const step = script.steps[index] as Step
      const args = JSON.stringify(resolveArgs(step.args ?? {}, last))
      const id = ToolCallId(`cetacea-mock-${index}`)
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id, name: step.tool, argumentsDelta: args }
      yield { type: 'block-end', index: 0, block: { type: 'tool-call', id, name: step.tool, arguments: args } }
      yield { type: 'usage', usage: { inputTokens: 1, outputTokens: 1 } }
      yield { type: 'finish', reason: { kind: 'tool-calls' } }
      return
    }
    const reply = script.final ?? 'MOCK model finished'
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text: reply }
    yield { type: 'block-end', index: 0, block: { type: 'text', text: reply } }
    yield { type: 'usage', usage: { inputTokens: 1, outputTokens: 1 } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

export const name = 'cetacea-mock-llm'
export const inject = ['llm', 'tools']

export function apply(ctx: Context): void {
  ctx.llm.registerAdapter(['cetacea-mock'], new CetaceaMockAdapter())
}
