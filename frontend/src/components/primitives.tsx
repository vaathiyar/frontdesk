import type { ReactNode } from 'react'
import { formatDateTime, formatPhone, humanize, telHref, toDetailValue } from '../lib/format'

export function Eyebrow({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`eyebrow text-ink/70 ${className}`}>{children}</span>
}

/**
 * Absolute time, always in the reader's own zone, always machine-readable.
 * The title attribute carries the full local timestamp for anyone who needs it.
 */
export function LocalTime({
  iso,
  children,
  className = '',
}: {
  iso: string | null
  children: ReactNode
  className?: string
}) {
  if (!iso) return <span className={className}>{children}</span>
  return (
    <time dateTime={iso} title={formatDateTime(iso)} className={className}>
      {children}
    </time>
  )
}

const PHONE_KEY = /(phone|mobile|cell|tel|contact_number)/i
const DIALABLE = /^\+?[\d][\d ()\-.]{6,}$/

/**
 * Renders a dynamic key/value map. The keys are chosen by the business profile,
 * not by this app: HVAC sends name/address/issue, the restaurant sends
 * name/party_size, and a new profile can send anything at all. So the key set
 * is never assumed — every key is humanized into a label and every value is
 * coerced to something printable.
 */
export function DetailList({
  entries,
  className = '',
}: {
  entries: [string, unknown][]
  className?: string
}) {
  if (entries.length === 0) return null
  return (
    <dl className={`grid gap-x-6 gap-y-3 sm:grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)] ${className}`}>
      {entries.map(([key, raw]) => {
        const value = toDetailValue(raw)
        const label = humanize(key) || key
        const dialable =
          value.kind === 'text' && PHONE_KEY.test(key) && DIALABLE.test(value.text)
            ? telHref(value.text)
            : null

        return (
          <div key={key} className="contents">
            <dt className="eyebrow pt-0.5 text-ink/70">{label}</dt>
            <dd className="min-w-0 text-pretty break-words text-ink sm:pt-px">
              {value.kind === 'empty' ? (
                <span className="text-ink/70" aria-label="Not provided">
                  —
                </span>
              ) : value.kind === 'time' ? (
                <time dateTime={value.iso} className="font-mono text-sm">
                  {value.text}
                </time>
              ) : dialable ? (
                <a
                  href={dialable}
                  className="font-mono text-sm underline decoration-rule decoration-1 underline-offset-4 hover:decoration-signal"
                >
                  {formatPhone(value.text)}
                </a>
              ) : (
                value.text
              )}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

/** A section heading with the hairline that separates every block on the page. */
export function SectionHeading({
  title,
  aside,
  id,
}: {
  title: string
  aside?: ReactNode
  id?: string
}) {
  return (
    <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-2">
      <h2 id={id} className="text-lg font-semibold wide-set">
        {title}
      </h2>
      {aside ? <div className="text-sm text-ink/70">{aside}</div> : null}
    </div>
  )
}
