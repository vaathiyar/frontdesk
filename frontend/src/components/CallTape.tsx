import { formatClock, formatDuration, humanize, parseDate } from '../lib/format'
import { eventTone, toneMark } from '../lib/semantics'
import type { CallEvent } from '../lib/types'

/**
 * The call, drawn to scale.
 *
 * A record is a pile of ISO timestamps; this turns it into a picture — where in
 * the call the agent checked availability, where the caller turned a slot down,
 * where the booking was written, where the text went out. The ruler along the
 * bottom is one tick per minute. A call still in progress has no right-hand
 * edge: it runs into hatching and a live marker rather than inventing a
 * duration.
 *
 * Decorative by construction: the strip is aria-hidden, and every mark on it is
 * also an item in the ordered timeline further down the page.
 */
export function CallTape({
  startedAt,
  endedAt,
  events,
}: {
  startedAt: string | null
  endedAt: string | null
  events: CallEvent[]
}) {
  const start = parseDate(startedAt)
  if (!start) return null

  const startMs = start.getTime()
  const endedMs = parseDate(endedAt)?.getTime() ?? null
  const inProgress = endedMs === null

  const marks = events
    .map((event) => ({ event, ms: parseDate(event.ts)?.getTime() ?? null }))
    .filter((entry): entry is { event: CallEvent; ms: number } => entry.ms !== null)

  const lastKnown = marks.length ? Math.max(...marks.map((entry) => entry.ms)) : startMs
  const provisionalEnd = endedMs ?? Math.max(Date.now(), lastKnown, startMs + 60_000)
  const span = Math.max(provisionalEnd - startMs, 1000)

  // In-progress tapes stop short of the right edge so the hatching has room.
  const usable = inProgress ? 86 : 100
  const at = (ms: number) => Math.min(Math.max(((ms - startMs) / span) * usable, 0), usable)

  const minutes = Math.floor(span / 60_000)
  const ticks = minutes > 0 && minutes <= 40 ? Array.from({ length: minutes }, (_, i) => i + 1) : []

  return (
    <figure className="plate bg-sunken px-3 pt-2.5 pb-2 sm:px-4">
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="eyebrow text-ink/70">Call, to scale</span>
        <span className={`font-mono text-xs ${inProgress ? 'text-signal-ink' : 'text-ink/70'}`}>
          {inProgress ? 'running' : formatDuration(provisionalEnd - startMs)}
        </span>
      </figcaption>

      <div aria-hidden="true" className="relative mt-2 h-11 bg-plate ring-1 ring-line">
        {/* one tick per minute, rising off the bottom edge like a ruler */}
        {ticks.map((minute) => (
          <div
            key={`tick-${minute}`}
            className="absolute bottom-0 h-1.5 w-px bg-ink/25"
            style={{ left: `${at(startMs + minute * 60_000)}%` }}
          />
        ))}

        {/* the two ends of the call */}
        <div className="absolute inset-y-0 left-0 w-0.5 bg-rule" />
        {!inProgress && <div className="absolute inset-y-0 right-0 w-0.5 bg-rule" />}

        {/* one mark per code-emitted event */}
        {marks.map((entry, index) => (
          <div
            key={`${entry.event.type}-${entry.event.ts}-${index}`}
            title={`${humanize(entry.event.type)} — ${formatClock(entry.event.ts)}`}
            className={`absolute top-0 bottom-2.5 w-0.5 -translate-x-1/2 ${toneMark[eventTone(entry.event.type)]}`}
            style={{ left: `${at(entry.ms)}%` }}
          />
        ))}

        {inProgress && (
          <>
            <div className="hatched absolute inset-y-0 right-0 w-[14%]" />
            <div
              className="live-dot absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-signal"
              style={{ left: `${usable}%` }}
            />
          </>
        )}
      </div>

      <div className="mt-1.5 flex items-baseline justify-between font-mono text-xs text-ink/70">
        <span>{formatClock(startedAt)}</span>
        <span>{inProgress ? 'in progress' : formatClock(endedAt)}</span>
      </div>
    </figure>
  )
}
