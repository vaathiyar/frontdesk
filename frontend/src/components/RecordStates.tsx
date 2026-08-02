import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { RefreshCw, SearchX, TriangleAlert } from 'lucide-react'
import { callRecordUrl } from '../lib/api'
import { Eyebrow } from './primitives'

/** Shared frame so the three states read as siblings, not as three designs. */
function StateFrame({
  tone,
  icon,
  eyebrow,
  title,
  children,
  actions,
}: {
  tone: 'neutral' | 'alert'
  icon: ReactNode
  eyebrow: string
  title: string
  children: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <div className="plate max-w-[46rem] overflow-hidden">
        <div
          aria-hidden="true"
          className={`h-0.5 ${tone === 'alert' ? 'bg-alert-mark' : 'bg-rule'}`}
        />
        <div className="px-5 py-6 sm:px-8 sm:py-8">
          <div
            className={`flex items-center gap-2 ${tone === 'alert' ? 'text-alert' : 'text-ink/70'}`}
          >
            {icon}
            <Eyebrow className={tone === 'alert' ? 'text-alert' : ''}>{eyebrow}</Eyebrow>
          </div>
          <h1 className="mt-3 text-2xl font-semibold wide-set text-balance sm:text-3xl">{title}</h1>
          <div className="mt-3 max-w-[58ch] space-y-3 text-ink/70">{children}</div>
          {actions ? <div className="mt-7 flex flex-wrap gap-3">{actions}</div> : null}
        </div>
      </div>
    </div>
  )
}

const primaryButton =
  'inline-flex min-h-11 items-center gap-2 rounded-xs border border-ink bg-ink px-4 py-2 text-sm font-medium text-paper transition-colors duration-150 hover:bg-ink/85'
const secondaryButton =
  'inline-flex min-h-11 items-center gap-2 rounded-xs border border-rule bg-plate px-4 py-2 text-sm font-medium text-ink transition-colors duration-150 hover:border-ink'

/** A skeleton of the real layout, so the page does not jump when data lands. */
export function RecordLoading() {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <p className="eyebrow text-ink/70" role="status">
        Loading call record…
      </p>
      <div className="mt-6 space-y-3">
        <div className="skeleton h-9 w-3/4 max-w-sm" />
        <div className="skeleton h-5 w-1/2 max-w-xs" />
      </div>
      <div className="skeleton mt-10 h-8 w-full" />
      <div className="mt-12 grid gap-10 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:gap-14">
        <div className="space-y-4">
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-40 w-full" />
          <div className="skeleton h-28 w-full" />
        </div>
        <div className="space-y-4">
          <div className="skeleton h-4 w-32" />
          {[0, 1, 2, 3, 4].map((row) => (
            <div key={row} className="space-y-2">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton h-4 w-full" />
              <div className="skeleton h-4 w-4/5" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function RecordNotFound({ id }: { id?: string }) {
  return (
    <StateFrame
      tone="neutral"
      icon={<SearchX aria-hidden="true" className="size-4" strokeWidth={2} />}
      eyebrow="Not found"
      title="No record for this link"
      actions={
        <Link to="/" className={primaryButton}>
          Go to the demo
        </Link>
      }
    >
      <p>
        This link does not match a call we hold. Long links are often cut short by messaging apps —
        check that the whole address was copied, including the part after the last slash.
      </p>
      {id ? (
        <p className="font-mono text-sm break-all text-ink">
          <span className="text-ink/70">id&nbsp;</span>
          {id}
        </p>
      ) : null}
    </StateFrame>
  )
}

export function RecordError({
  id,
  reason,
  onRetry,
}: {
  id: string
  reason: string
  onRetry: () => void
}) {
  const explanation =
    reason === 'network'
      ? 'The server did not respond. You may be offline, or the API may not be running.'
      : reason === 'malformed'
        ? 'The server replied with something this page could not read.'
        : `The server returned an error (${reason.replace('http_', 'HTTP ')}).`

  return (
    <StateFrame
      tone="alert"
      icon={<TriangleAlert aria-hidden="true" className="size-4" strokeWidth={2} />}
      eyebrow="Could not load"
      title="This record did not load"
      actions={
        <>
          <button type="button" onClick={onRetry} className={primaryButton}>
            <RefreshCw aria-hidden="true" className="size-4" strokeWidth={2} />
            Try again
          </button>
          <Link to="/" className={secondaryButton}>
            Go to the demo
          </Link>
        </>
      }
    >
      <p>{explanation}</p>
      <p className="font-mono text-sm break-all text-ink">
        <span className="text-ink/70">GET&nbsp;</span>
        {callRecordUrl(id)}
      </p>
    </StateFrame>
  )
}

/** The `*` route. Same calm treatment as a 404 from the API, different words. */
export function PageNotFound() {
  return (
    <StateFrame
      tone="neutral"
      icon={<SearchX aria-hidden="true" className="size-4" strokeWidth={2} />}
      eyebrow="Not found"
      title="No page at this address"
      actions={
        <Link to="/" className={primaryButton}>
          Go to the demo
        </Link>
      }
    >
      <p>
        Frontdesk has two pages: the demo, and the record for a single call. A call record link
        looks like <code className="font-mono text-sm text-ink">/c/</code> followed by the call id
        from your text message.
      </p>
    </StateFrame>
  )
}
