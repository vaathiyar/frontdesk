/**
 * Formatting primitives. Every one of these is defensive: the record is
 * rendered from live telephony data where any field may be null, malformed or
 * unrecognised, and a record page that throws is worse than one that says
 * "unknown".
 */

/** Tokens that should not be sentence-cased when humanizing an identifier. */
const ACRONYMS = new Set(['sms', 'id', 'url', 'api', 'hvac', 'eta', 'ac', 'faq', 'ai', 'crm'])

/** Identifiers we are willing to rewrite: snake_case, kebab-case, dotted, camelCase. */
const MACHINE_IDENT = /^[a-z0-9]+(?:[_\-.][a-z0-9]+)*$/i
const CAMEL_BOUNDARY = /([a-z0-9])([A-Z])/g

/**
 * `booking_created` -> `Booking created`, `party_size` -> `Party size`,
 * `sms_sent` -> `SMS sent`, `calendar_event_id` -> `Calendar event ID`.
 *
 * Strings that are already prose ("no heat upstairs, second floor") are passed
 * through untouched so we never mangle real content.
 */
export function humanize(raw: string | null | undefined): string {
  const value = (raw ?? '').trim()
  if (!value) return ''
  if (!MACHINE_IDENT.test(value)) return value

  const tokens = value
    .replace(CAMEL_BOUNDARY, '$1 $2')
    .split(/[_\-.\s]+/)
    .filter(Boolean)
  if (tokens.length === 0) return value

  return tokens
    .map((token, index) => {
      const lower = token.toLowerCase()
      if (ACRONYMS.has(lower)) return lower.toUpperCase()
      if (index === 0) return lower.charAt(0).toUpperCase() + lower.slice(1)
      return lower
    })
    .join(' ')
}

/** Capitalise the first letter and leave the rest of the phrase alone. */
export function sentenceStart(raw: string | null | undefined): string {
  const value = (raw ?? '').trim()
  if (!value) return ''
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

const ISO_LIKE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/

export function looksLikeTimestamp(value: string): boolean {
  return ISO_LIKE.test(value) && parseDate(value) !== null
}

function fmt(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(undefined, options)
}

/** "Wed, Jul 29, 10:14 AM" in the reader's own zone. */
export function formatDateTime(iso: string | null | undefined): string {
  const date = parseDate(iso)
  if (!date) return '—'
  return fmt({
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

export function formatClock(iso: string | null | undefined): string {
  const date = parseDate(iso)
  if (!date) return '—'
  return fmt({ hour: 'numeric', minute: '2-digit' }).format(date)
}

export function formatDay(iso: string | null | undefined): string {
  const date = parseDate(iso)
  if (!date) return '—'
  return fmt({ weekday: 'long', month: 'long', day: 'numeric' }).format(date)
}

/**
 * "Wed, Jul 29, 10:00 – 11:00 AM" — Intl collapses the shared parts itself,
 * which is exactly the behaviour we want across day boundaries too.
 */
export function formatSpan(startIso: string | null, endIso: string | null): string {
  const start = parseDate(startIso)
  const end = parseDate(endIso)
  if (!start) return '—'
  const options: Intl.DateTimeFormatOptions = {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }
  if (!end) return fmt(options).format(start)
  try {
    return fmt(options).formatRange(start, end)
  } catch {
    return `${fmt(options).format(start)} – ${fmt(options).format(end)}`
  }
}

/** Short name of the reader's timezone, e.g. "PDT". Empty if unavailable. */
export function localZoneLabel(): string {
  try {
    const parts = fmt({ timeZoneName: 'short' }).formatToParts(new Date())
    return parts.find((part) => part.type === 'timeZoneName')?.value ?? ''
  } catch {
    return ''
  }
}

/** Elapsed wall-clock duration, e.g. "4m 12s" or "1h 04m". */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const total = Math.round(ms / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  return `${seconds}s`
}

/** Offset from the start of the call, as it would be read off a tape: "+1:07". */
export function formatOffset(ms: number): string {
  if (!Number.isFinite(ms)) return '—'
  const sign = ms < 0 ? '-' : '+'
  const total = Math.round(Math.abs(ms) / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const mm = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes)
  return `${sign}${hours > 0 ? `${hours}:` : ''}${mm}:${String(seconds).padStart(2, '0')}`
}

/** Where in the call this happened, read off the start: "+1:07". */
export function offsetFrom(startIso: string | null, ts: string | null): string | null {
  const start = parseDate(startIso)
  const at = parseDate(ts)
  if (!start || !at) return null
  return formatOffset(at.getTime() - start.getTime())
}

export function durationMs(startIso: string | null, endIso: string | null): number | null {
  const start = parseDate(startIso)
  const end = parseDate(endIso)
  if (!start || !end) return null
  return end.getTime() - start.getTime()
}

/**
 * E.164 -> a number a person can read aloud. North American numbers get the
 * familiar grouping; everything else is grouped loosely rather than guessed at.
 */
export function formatPhone(raw: string | null | undefined): string {
  const value = (raw ?? '').trim()
  if (!value) return '—'
  const digits = value.replace(/[^\d]/g, '')
  if (value.startsWith('+1') && digits.length === 11) {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`
  }
  if (digits.length === 10 && !value.startsWith('+')) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`
  }
  if (value.startsWith('+') && digits.length > 7) {
    return `+${digits.slice(0, digits.length - 10)} ${digits.slice(-10, -7)} ${digits.slice(-7, -4)} ${digits.slice(-4)}`.replace(
      /\s+/g,
      ' ',
    )
  }
  return value
}

export function telHref(raw: string | null | undefined): string | null {
  const value = (raw ?? '').trim()
  if (!value) return null
  const cleaned = value.replace(/[^\d+]/g, '')
  return cleaned.length >= 7 ? `tel:${cleaned}` : null
}

export type DetailValue =
  | { kind: 'empty' }
  | { kind: 'text'; text: string }
  | { kind: 'time'; text: string; iso: string }

/**
 * Renders one value out of a dynamic `details` map. The keys differ per
 * business, so the values do too: strings, numbers, booleans, nested objects
 * and arrays all have to land somewhere sensible.
 */
export function toDetailValue(value: unknown): DetailValue {
  if (value === null || value === undefined) return { kind: 'empty' }
  if (typeof value === 'boolean') return { kind: 'text', text: value ? 'Yes' : 'No' }
  if (typeof value === 'number') {
    return Number.isFinite(value)
      ? { kind: 'text', text: value.toLocaleString() }
      : { kind: 'empty' }
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return { kind: 'empty' }
    if (looksLikeTimestamp(trimmed)) {
      return { kind: 'time', text: formatDateTime(trimmed), iso: trimmed }
    }
    return { kind: 'text', text: trimmed }
  }
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => {
        const rendered = toDetailValue(item)
        return rendered.kind === 'empty' ? null : rendered.text
      })
      .filter((part): part is string => part !== null)
    return parts.length ? { kind: 'text', text: parts.join(', ') } : { kind: 'empty' }
  }
  if (typeof value === 'object') {
    const parts = Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => {
        const rendered = toDetailValue(nested)
        return rendered.kind === 'empty' ? null : `${humanize(key)}: ${rendered.text}`
      })
      .filter((part): part is string => part !== null)
    return parts.length ? { kind: 'text', text: parts.join(' · ') } : { kind: 'empty' }
  }
  return { kind: 'empty' }
}

/** Stable, non-empty entries of a dynamic map, in the order the API sent them. */
export function detailEntries(map: Record<string, unknown> | null | undefined): [string, unknown][] {
  if (!map || typeof map !== 'object') return []
  return Object.entries(map)
}
