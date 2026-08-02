import { humanize } from './format'

/**
 * Colour in this app carries exactly four meanings and never anything else:
 *
 *   signal  (amber) — the agent took an action, recorded by code
 *   confirm (pine)  — it landed on the business's real calendar
 *   alert   (rust)  — declined, cancelled or failed
 *   neutral / muted — everything a human said, and everything unclassified
 *
 * Every tone is always paired with a text label and an icon, so nothing here
 * is the only carrier of meaning.
 */
export type Tone = 'neutral' | 'signal' | 'confirm' | 'alert' | 'muted'

export const toneText: Record<Tone, string> = {
  neutral: 'text-ink',
  signal: 'text-signal-ink',
  confirm: 'text-confirm',
  alert: 'text-alert',
  muted: 'text-ink/70',
}

export const toneMark: Record<Tone, string> = {
  neutral: 'bg-rule',
  signal: 'bg-signal',
  confirm: 'bg-confirm-mark',
  alert: 'bg-alert-mark',
  muted: 'bg-ink/45',
}

export const toneBorder: Record<Tone, string> = {
  neutral: 'border-rule',
  signal: 'border-signal',
  confirm: 'border-confirm-mark',
  alert: 'border-alert-mark',
  muted: 'border-line',
}

export const toneWash: Record<Tone, string> = {
  neutral: 'bg-sunken',
  signal: 'bg-signal-wash',
  confirm: 'bg-confirm-wash',
  alert: 'bg-alert-wash',
  muted: 'bg-sunken',
}

export interface OutcomeMeta {
  label: string
  tone: Tone
  /** One plain sentence for people who have never seen this product before. */
  blurb: string
  known: boolean
}

const OUTCOMES: Record<string, Omit<OutcomeMeta, 'known'>> = {
  booked: {
    label: 'Booked',
    tone: 'confirm',
    blurb: 'A new appointment was created during the call.',
  },
  rescheduled: {
    label: 'Rescheduled',
    tone: 'signal',
    blurb: 'An existing appointment was moved to a new time.',
  },
  cancelled: {
    label: 'Cancelled',
    tone: 'alert',
    blurb: 'An existing appointment was cancelled.',
  },
  answered: {
    label: 'Answered',
    tone: 'neutral',
    blurb: 'The caller asked questions and got answers. Nothing was scheduled.',
  },
  message_taken: {
    label: 'Message taken',
    tone: 'signal',
    blurb: 'The caller left a message for the business instead of booking.',
  },
  abandoned: {
    label: 'Abandoned',
    tone: 'muted',
    blurb: 'The call ended before anything was settled.',
  },
}

export function outcomeMeta(outcome: string | null | undefined): OutcomeMeta {
  if (!outcome) {
    return {
      label: 'No outcome yet',
      tone: 'muted',
      blurb: 'This call has not been classified.',
      known: false,
    }
  }
  const known = OUTCOMES[outcome]
  if (known) return { ...known, known: true }
  return {
    label: humanize(outcome),
    tone: 'neutral',
    blurb: 'Recorded by the agent as the result of this call.',
    known: false,
  }
}

const ALERT_EVENTS = new Set(['slot_declined', 'booking_cancelled', 'sms_failed'])
const CONFIRM_EVENTS = new Set(['booking_created'])
const MUTED_EVENTS = new Set(['sms_skipped'])

export function eventTone(type: string): Tone {
  if (ALERT_EVENTS.has(type)) return 'alert'
  if (CONFIRM_EVENTS.has(type)) return 'confirm'
  if (MUTED_EVENTS.has(type)) return 'muted'
  return 'signal'
}

/** "caller" and "agent" get proper names; anything else is humanized. */
export function roleLabel(role: string): string {
  const normalized = role.trim().toLowerCase()
  if (normalized === 'agent') return 'Agent'
  if (normalized === 'caller') return 'Caller'
  return humanize(role) || 'Unknown'
}

export function isAgentRole(role: string): boolean {
  return role.trim().toLowerCase() === 'agent'
}
