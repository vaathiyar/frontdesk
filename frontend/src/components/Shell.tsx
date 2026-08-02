import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'

/** The wordmark echoes the call tape: two boundary bars, marks in between. */
function Mark() {
  return (
    <svg viewBox="0 0 28 16" className="h-4 w-7 shrink-0" aria-hidden="true" focusable="false">
      <path d="M1 3v10M27 3v10" stroke="currentColor" strokeWidth="1.5" opacity="0.45" />
      <path d="M1 8h26" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      <path d="M9 5v6M17 5v6" className="stroke-signal" strokeWidth="2" />
    </svg>
  )
}

export function SiteHeader({ aside }: { aside?: ReactNode }) {
  return (
    <header className="border-b border-line">
      {/* The amber rule that tops every page, like the header band on a work order. */}
      <div aria-hidden="true" className="h-0.5 bg-signal" />
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6 lg:px-8">
        <Link
          to="/"
          className="flex items-center gap-2.5 text-ink transition-colors duration-150 hover:text-signal-ink"
          aria-label="Frontdesk home"
        >
          <Mark />
          <span className="text-lg font-semibold wide-set tracking-tight">Frontdesk</span>
        </Link>
        {aside ? <div className="min-w-0 text-right">{aside}</div> : null}
      </div>
    </header>
  )
}

export function SiteFooter() {
  const onLanding = useLocation().pathname === '/'
  return (
    <footer className="mt-20 border-t border-line">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-ink/70 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p className="max-w-[60ch]">
          Frontdesk is a working demo. Calls to the numbers listed are answered by the agent and
          recorded, and the caller is texted a link to the record.
        </p>
        {!onLanding && (
          <Link to="/" className="shrink-0 font-medium text-ink hover:text-signal-ink">
            Back to the demo
          </Link>
        )}
      </div>
    </footer>
  )
}

export function Page({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-xs focus:bg-plate focus:px-3 focus:py-2 focus:text-ink focus:outline-2 focus:outline-signal-ink"
      >
        Skip to content
      </a>
      <SiteHeader aside={aside} />
      <main id="main" className="flex-1">
        {children}
      </main>
      <SiteFooter />
    </div>
  )
}
