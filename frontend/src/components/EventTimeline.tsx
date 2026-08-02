import { formatClock, humanize, offsetFrom } from '../lib/format'
import { KNOWN_EVENT_TYPES, type CallEvent } from '../lib/types'
import { eventTone, toneBorder, toneText, toneWash } from '../lib/semantics'
import { EventIcon } from './EventIcon'
import { LocalTime } from './primitives'

const KNOWN = new Set<string>(KNOWN_EVENT_TYPES)

/**
 * What the agent actually did, in order.
 *
 * Every entry here was emitted by application code at the moment the action
 * happened — none of it is written by the model. That is the whole point of
 * the section: the transcript is a claim, this is the receipt.
 */
export function EventTimeline({
  events,
  startedAt,
}: {
  events: CallEvent[]
  startedAt: string | null
}) {
  if (events.length === 0) {
    return (
      <p className="plate bg-sunken px-4 py-5 text-sm text-ink/70">
        No actions were recorded. The agent did not book, reschedule, cancel, or send anything on
        this call.
      </p>
    )
  }

  return (
    <ol className="space-y-0">
      {events.map((event, index) => {
        const tone = eventTone(event.type)
        const offset = offsetFrom(startedAt, event.ts)
        const isLast = index === events.length - 1

        return (
          <li key={`${event.type}-${event.ts}-${index}`} className="relative pb-6 pl-9 last:pb-0">
            {!isLast && (
              <span
                aria-hidden="true"
                className="absolute top-7 bottom-0 left-[13px] w-px bg-line"
              />
            )}
            <span
              className={`absolute top-0 left-0 flex size-7 items-center justify-center rounded-xs border ${toneBorder[tone]} ${toneWash[tone]} ${toneText[tone]}`}
            >
              <EventIcon type={event.type} className="size-3.5" />
            </span>

            <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <h3 className={`eyebrow ${toneText[tone]}`}>{humanize(event.type)}</h3>
              {!KNOWN.has(event.type) && (
                <code className="rounded-xs bg-ink/10 px-1 py-px font-mono text-xs text-ink/70">
                  {event.type}
                </code>
              )}
              {offset && (
                <LocalTime iso={event.ts} className="font-mono text-xs text-ink">
                  {offset}
                  <span className="text-ink/70"> · {formatClock(event.ts)}</span>
                </LocalTime>
              )}
            </div>

            {event.summary ? (
              <p className="mt-1 max-w-[58ch] text-pretty text-sm text-ink">{event.summary}</p>
            ) : (
              <p className="mt-1 text-sm text-ink/70">No detail recorded.</p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
