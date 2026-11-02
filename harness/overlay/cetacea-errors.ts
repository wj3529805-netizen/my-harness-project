// Error-only diagnostics. Never serialize request objects, headers or stacks.
export function safeError(error: unknown, secret = process.env.DEEPSEEK_API_KEY ?? '', depth = 0): unknown {
  const clean = (value: unknown): string => {
    let text = String(value)
    if (secret) for (const variant of [secret, encodeURIComponent(secret), JSON.stringify(secret).slice(1, -1)]) {
      text = text.split(variant).join('[REDACTED]')
    }
    return text.replace(/sk-[A-Za-z0-9_-]{16,}/g, '[REDACTED]')
      .replace(/\b(Bearer|Basic)\s+\S+/gi, '$1 [REDACTED]')
      .replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 1500)
  }
  if (depth >= 4) return '[cause depth limit]'
  if (error === null || typeof error !== 'object') return { message: clean(error) }
  const item = error as Record<string, unknown>
  const result: Record<string, unknown> = {}
  for (const key of ['name', 'code', 'message', 'status']) {
    if (typeof item[key] === 'string' || typeof item[key] === 'number') result[key] = clean(item[key])
  }
  if (item.cause !== undefined) result.cause = safeError(item.cause, secret, depth + 1)
  return result
}

export function reportError(source: string, error: unknown): void {
  process.stderr.write(`${JSON.stringify({ type: 'cetacea_error', source, error: safeError(error) })}\n`)
}
