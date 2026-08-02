import {
  CalendarCheck,
  CalendarClock,
  CalendarOff,
  CircleDot,
  MessageCircleQuestion,
  NotebookPen,
  PhoneOff,
  type LucideIcon,
} from 'lucide-react'
import { outcomeMeta, toneBorder, toneText, toneWash } from '../lib/semantics'

const OUTCOME_ICONS: Record<string, LucideIcon> = {
  booked: CalendarCheck,
  rescheduled: CalendarClock,
  cancelled: CalendarOff,
  answered: MessageCircleQuestion,
  message_taken: NotebookPen,
  abandoned: PhoneOff,
}

/**
 * The headline classification of the call. Icon + label + tone, so it is never
 * colour alone. When the value is one this build has not seen before, the raw
 * string is shown next to the humanized label rather than hidden.
 */
export function OutcomeChip({ outcome, size = 'md' }: { outcome: string | null; size?: 'sm' | 'md' }) {
  const meta = outcomeMeta(outcome)
  const Icon = (outcome && OUTCOME_ICONS[outcome]) || CircleDot
  const pad = size === 'sm' ? 'gap-1.5 px-2 py-0.5 text-sm' : 'gap-2 px-2.5 py-1 text-base'

  return (
    <span
      className={`inline-flex items-center rounded-xs border ${pad} ${toneWash[meta.tone]} ${toneBorder[meta.tone]} ${toneText[meta.tone]}`}
    >
      <Icon aria-hidden="true" className={size === 'sm' ? 'size-3.5' : 'size-4'} strokeWidth={2} />
      <span className="font-medium wide-set">{meta.label}</span>
      {outcome && !meta.known ? (
        <code className="ml-0.5 rounded-xs bg-ink/10 px-1 py-px font-mono text-xs text-ink/70">
          {outcome}
        </code>
      ) : null}
    </span>
  )
}
