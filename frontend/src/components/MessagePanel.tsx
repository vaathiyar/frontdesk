import type { TakenMessage } from '../lib/types'
import { detailEntries } from '../lib/format'
import { DetailList, Eyebrow } from './primitives'

const HANDLED_KEYS = new Set(['name', 'reason'])

/**
 * A message taken instead of a booking. `name` and `reason` lead because that
 * is what the business reads first; any other key the backend sends still
 * appears below rather than being dropped.
 */
export function MessagePanel({ message }: { message: TakenMessage }) {
  const name = typeof message.name === 'string' ? message.name.trim() : ''
  const reason = typeof message.reason === 'string' ? message.reason.trim() : ''
  const extras = detailEntries(message).filter(([key]) => !HANDLED_KEYS.has(key))

  return (
    <div className="plate">
      <div className="px-4 py-4 sm:px-6 sm:py-5">
        <Eyebrow>Message for the business</Eyebrow>
        <p className="mt-2 text-xl font-semibold wide-set">{name || 'Caller left a message'}</p>
        {reason ? (
          <blockquote className="mt-3 border-l-2 border-signal pl-4 text-pretty text-ink">
            {reason}
          </blockquote>
        ) : (
          <p className="mt-3 text-sm text-ink/70">No reason was recorded.</p>
        )}
      </div>

      {extras.length > 0 && (
        <div className="border-t border-line px-4 py-4 sm:px-6 sm:py-5">
          <DetailList entries={extras} />
        </div>
      )}
    </div>
  )
}
