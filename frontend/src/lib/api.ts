import type { Booking, CallEvent, CallRecord, TakenMessage, TranscriptTurn } from './types'

/**
 * Empty by default, which means same-origin. In dev, Vite proxies /api to the
 * FastAPI process on :8000 (see vite.config.ts) so the empty default is correct
 * there as well; set VITE_API_BASE_URL only when the SPA is hosted apart from
 * the API.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

export function callRecordUrl(id: string): string {
  return `${API_BASE}/api/calls/${encodeURIComponent(id)}`
}

export type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; record: CallRecord; source: 'api' | 'fixture' }
  | { status: 'missing' }
  | { status: 'failed'; reason: string }

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function normalizeBooking(value: unknown): Booking | null {
  const raw = asObject(value)
  if (!raw) return null
  return {
    service: asString(raw.service),
    starts_at: asString(raw.starts_at),
    ends_at: asString(raw.ends_at),
    calendar_event_id: asString(raw.calendar_event_id),
    details: asObject(raw.details),
  }
}

function normalizeMessage(value: unknown): TakenMessage | null {
  const raw = asObject(value)
  if (!raw) return null
  return raw as TakenMessage
}

function normalizeTranscript(value: unknown): TranscriptTurn[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => asObject(item))
    .filter((item): item is Record<string, unknown> => item !== null)
    .map((item) => ({
      ts: asString(item.ts),
      role: asString(item.role) ?? 'unknown',
      text: typeof item.text === 'string' ? item.text : '',
    }))
}

function normalizeEvents(value: unknown): CallEvent[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => asObject(item))
    .filter((item): item is Record<string, unknown> => item !== null)
    .map((item) => ({
      ts: asString(item.ts),
      type: asString(item.type) ?? 'unknown',
      summary: asString(item.summary),
    }))
}

/**
 * Coerce whatever the API returned into the shape the UI renders. Nothing here
 * rejects a record: a field we do not recognise is simply ignored, and a field
 * that is missing becomes null or an empty list.
 */
export function normalizeRecord(raw: unknown, fallbackId: string): CallRecord {
  const value = asObject(raw) ?? {}
  return {
    id: asString(value.id) ?? fallbackId,
    profile_id: asString(value.profile_id),
    business_name: asString(value.business_name),
    caller_number: asString(value.caller_number),
    called_number: asString(value.called_number),
    started_at: asString(value.started_at),
    ended_at: asString(value.ended_at),
    outcome: asString(value.outcome),
    booking: normalizeBooking(value.booking),
    message: normalizeMessage(value.message),
    transcript: normalizeTranscript(value.transcript),
    events: normalizeEvents(value.events),
  }
}

/**
 * The entire data layer: one GET, three outcomes. Any query string on the
 * current URL (including the `?t=` token some already-sent SMS links carry) is
 * irrelevant here and is never read or forwarded.
 */
export async function fetchCallRecord(id: string, signal: AbortSignal): Promise<LoadState> {
  let response: Response
  try {
    response = await fetch(callRecordUrl(id), {
      signal,
      headers: { Accept: 'application/json' },
    })
  } catch {
    return { status: 'failed', reason: 'network' }
  }

  if (response.status === 404) return { status: 'missing' }
  if (!response.ok) return { status: 'failed', reason: `http_${response.status}` }

  try {
    const payload: unknown = await response.json()
    return { status: 'ready', record: normalizeRecord(payload, id), source: 'api' }
  } catch {
    return { status: 'failed', reason: 'malformed' }
  }
}
