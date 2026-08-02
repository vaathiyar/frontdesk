import { CalendarCheck, CircleSlash } from 'lucide-react'
import { detailEntries, formatSpan, sentenceStart } from '../lib/format'
import type { Booking } from '../lib/types'
import { DetailList, Eyebrow } from './primitives'

/**
 * The appointment, if there is one. `details` is whatever the business profile
 * collects — never a fixed set of fields — so it is rendered by iterating the
 * map rather than by naming keys.
 */
export function BookingPanel({ booking }: { booking: Booking }) {
  const entries = detailEntries(booking.details)
  const onCalendar = Boolean(booking.calendar_event_id)

  return (
    <div className="plate">
      <div className="border-b border-line px-4 py-4 sm:px-6 sm:py-5">
        <Eyebrow>Appointment</Eyebrow>
        <p className="mt-2 text-2xl font-semibold wide-set text-balance">
          {sentenceStart(booking.service) || 'Appointment'}
        </p>
        <p className="mt-1.5 font-mono text-sm text-ink">
          {formatSpan(booking.starts_at, booking.ends_at)}
        </p>
      </div>

      {entries.length > 0 && (
        <div className="px-4 py-4 sm:px-6 sm:py-5">
          <DetailList entries={entries} />
        </div>
      )}

      <div
        className={`flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line px-4 py-3 text-sm sm:px-6 ${
          onCalendar ? 'text-confirm' : 'text-ink/70'
        }`}
      >
        {onCalendar ? (
          <>
            <CalendarCheck aria-hidden="true" className="size-4 shrink-0" strokeWidth={2} />
            <span className="font-medium">On the business calendar</span>
            <code className="font-mono text-xs text-ink/70">{booking.calendar_event_id}</code>
          </>
        ) : (
          <>
            <CircleSlash aria-hidden="true" className="size-4 shrink-0" strokeWidth={2} />
            <span>Not written to the business calendar</span>
          </>
        )}
      </div>
    </div>
  )
}
