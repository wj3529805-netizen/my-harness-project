#!/usr/bin/env node
import { readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { createInterface } from 'node:readline'
import type { Context } from '@deepseek-ai/cordis'
import { resolveConfigPath } from '@deepseek-ai/dsh-app-boot'
import { runFixtureTurn } from '@deepseek-ai/dsh-loader-smoke'
import type { SessionEvent } from '@deepseek-ai/dsh-session'
import { bootProductionProfile } from '../production-profile.ts'

// request/header is a model request snapshot (config and tool schemas), not HTTP
// headers. Drop it entirely so future header fields cannot disclose credentials.
export function redactEvent(event: SessionEvent): unknown {
  return event.type === 'request/header' ? { ...event, data: '[redacted]' } : event
}

const emit = (value: unknown): void => { process.stdout.write(`${JSON.stringify(value)}\n`) }
const ledger = process.env.CETACEA_REQUEST_LEDGER
const max = Number(process.env.CETACEA_MAX_MODEL_REQUESTS ?? '30')
let count = 0
let ctx: Context | undefined
let surface: string[] | null = null
try {
  if (!Number.isSafeInteger(max) || max < 0) throw new Error('invalid request limit')
  if (ledger) {
    try {
      const saved = JSON.parse(readFileSync(ledger, 'utf8')) as { count: number }
      if (!Number.isSafeInteger(saved.count) || saved.count < 0) throw new Error('invalid ledger')
      count = saved.count
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    }
  }
  const config = process.argv[2]
  if (!config) throw new Error('missing overlay config')
  ctx = await bootProductionProfile({ binName: 'cetacea-session', profile: 'headless', overlayPaths: [resolveConfigPath(config, undefined)] })
  let turn = 0
  for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
    turn++
    let task: unknown
    try {
      const parsed = JSON.parse(line)
      task = parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed.task : undefined
      if (typeof task !== 'string') throw new Error('invalid task')
    } catch {
      emit({ type: 'error', turn, message: 'expected JSON object with string task' })
      process.exitCode = 2
      break
    }
    if (count >= max) {
      emit({ type: 'budget_exceeded', count, max })
      process.exitCode = 4
      break
    }
    let requests = 0
    let exceeded = false
    let pendingSurface = false
    const emitSurface = (): void => {
      if (pendingSurface) { emit({ type: 'tool_surface', turn, tools: surface }); pendingSurface = false }
    }
    const result = await runFixtureTurn(ctx, { task, onEvent: (sessionId, event) => {
      if (event.type === 'step/start') {
        emitSurface()
        count++
        requests++
        if (ledger) {
          const temp = `${ledger}.${process.pid}.tmp`
          try { writeFileSync(temp, JSON.stringify({ count }), { flag: 'wx', mode: 0o600 }); renameSync(temp, ledger) }
          finally { try { unlinkSync(temp) } catch {} }
        }
        // The event fires as a step starts, so cancellation can race its request:
        // at most one request may overshoot the cap.
        if (count > max) {
          exceeded = true
          emit({ type: 'budget_exceeded', count, max })
          ctx?.get('agents')?.roots()[0]?.cancel({ kind: 'user' })
          return
        }
        pendingSurface = true
      }
      if (event.type === 'request/header') {
        const tools = event.data.header.tools
        surface = Array.isArray(tools) && tools.every(tool => typeof tool.name === 'string')
          ? tools.map(tool => tool.name).sort() : null
      }
      if (event.type === 'step/end') emitSurface()
      if (!exceeded) emit({ type: 'session_event', turn, sessionId, event: redactEvent(event) })
    } })
    if (exceeded) { process.exitCode = 4; break }
    emitSurface()
    emit({ type: 'turn_done', turn, output: result.output, usage: result.usage ?? null, requests })
  }
} catch {
  // Errors may contain provider details or credentials; never print them.
  emit({ type: 'error', message: 'session failed' })
  process.exitCode = 1
} finally {
  try { await ctx?.fiber.dispose() } catch { process.exitCode ||= 1 }
}
