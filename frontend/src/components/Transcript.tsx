import { offsetFrom } from '../lib/format'
import { isAgentRole, roleLabel } from '../lib/semantics'
import type { TranscriptTurn } from '../lib/types'
import { LocalTime } from './primitives'

/**
 * What was said.
 *
 * The speaker is named in words on every single turn — the amber rule and the
 * label colour only reinforce it. Set in the sans face throughout, against the
 * mono of the timeline, so the two halves of the record never read as the same
 * kind of evidence.
 */
export function Transcript({
  turns,
  startedAt,
}: {
  turns: TranscriptTurn[]
  startedAt: string | null
}) {
  if (turns.length === 0) {
    return (
      <p className="plate bg-sunken px-4 py-5 text-sm text-ink/70">
        No transcript. Either the call is still open, or it ended before anyone spoke.
      </p>
    )
  }

  return (
    <ol className="space-y-4">
      {turns.map((turn, index) => {
        const agent = isAgentRole(turn.role)
        const offset = offsetFrom(startedAt, turn.ts)

        return (
          <li
            key={`${turn.role}-${turn.ts}-${index}`}
            className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-2 sm:grid-cols-[4.25rem_minmax(0,1fr)] sm:gap-x-4"
          >
            <LocalTime
              iso={turn.ts}
              className="pt-0.5 text-right font-mono text-xs text-ink/70 tabular-nums"
            >
              {offset ?? '—'}
            </LocalTime>

            <div className={`border-l-2 pl-3 sm:pl-4 ${agent ? 'border-signal' : 'border-line'}`}>
              <span className={`eyebrow ${agent ? 'text-signal-ink' : 'text-ink/70'}`}>
                {roleLabel(turn.role)}
              </span>
              <p className="mt-1 max-w-[60ch] text-pretty text-ink">
                {turn.text || <span className="text-ink/70">(nothing transcribed)</span>}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
