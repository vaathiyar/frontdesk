import {
  CalendarCheck,
  CalendarClock,
  CalendarOff,
  CalendarSearch,
  CalendarX,
  CircleDot,
  MessageCircleQuestion,
  NotebookPen,
  PhoneOff,
  Send,
  SkipForward,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'

/**
 * Known event types get an icon that says what happened at a glance. Anything
 * unrecognised falls back to a neutral mark rather than being hidden — a new
 * backend event type should still show up on the timeline.
 */
const ICONS: Record<string, LucideIcon> = {
  availability_checked: CalendarSearch,
  slot_declined: CalendarX,
  booking_created: CalendarCheck,
  booking_rescheduled: CalendarClock,
  booking_cancelled: CalendarOff,
  question_answered: MessageCircleQuestion,
  message_taken: NotebookPen,
  call_ended: PhoneOff,
  sms_sent: Send,
  sms_failed: TriangleAlert,
  sms_skipped: SkipForward,
}

export function EventIcon({ type, className }: { type: string; className?: string }) {
  const Icon = ICONS[type] ?? CircleDot
  return <Icon aria-hidden="true" className={className} strokeWidth={1.75} />
}
