/**
 * Shape of GET /api/calls/{id}.
 *
 * Deliberately loose where the contract is loose. `outcome`, `role` and
 * `event.type` are typed as plain strings, not unions: the backend is allowed
 * to grow new values and the UI must humanize and render anything it is given
 * rather than crash or leak snake_case. The KNOWN_* consts below exist for
 * tailored treatment only, never for validation.
 */

export interface BookingDetails {
  [key: string]: unknown
}

export interface Booking {
  service: string | null
  starts_at: string | null
  ends_at: string | null
  calendar_event_id: string | null
  details: BookingDetails | null
}

export interface TakenMessage {
  name?: string | null
  reason?: string | null
  [key: string]: unknown
}

export interface TranscriptTurn {
  ts: string | null
  /** In practice "caller" | "agent", but treated as a free string. */
  role: string
  text: string
}

export interface CallEvent {
  ts: string | null
  /** Emitted by application code, never by the model. Free string. */
  type: string
  summary: string | null
}

export interface CallRecord {
  id: string
  profile_id: string | null
  business_name: string | null
  caller_number: string | null
  called_number: string | null
  started_at: string | null
  /** Null while the call is still in progress. */
  ended_at: string | null
  /** One of KNOWN_OUTCOMES, some other string, or null. */
  outcome: string | null
  booking: Booking | null
  message: TakenMessage | null
  transcript: TranscriptTurn[]
  events: CallEvent[]
}

export const KNOWN_OUTCOMES = [
  'booked',
  'rescheduled',
  'cancelled',
  'answered',
  'message_taken',
  'abandoned',
] as const

export const KNOWN_EVENT_TYPES = [
  'availability_checked',
  'slot_declined',
  'booking_created',
  'booking_rescheduled',
  'booking_cancelled',
  'question_answered',
  'message_taken',
  'call_ended',
  'sms_sent',
  'sms_failed',
  'sms_skipped',
] as const
