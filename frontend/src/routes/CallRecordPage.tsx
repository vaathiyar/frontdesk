import { useEffect } from 'react'
import { useParams } from 'react-router'
import {
  durationMs,
  formatDateTime,
  formatDuration,
  formatPhone,
  localZoneLabel,
  telHref,
} from '../lib/format'
import { outcomeMeta } from '../lib/semantics'
import type { CallRecord } from '../lib/types'
import { useCallRecord } from '../lib/useCallRecord'
import { BookingPanel } from '../components/BookingPanel'
import { CallTape } from '../components/CallTape'
import { EventTimeline } from '../components/EventTimeline'
import { MessagePanel } from '../components/MessagePanel'
import { OutcomeChip } from '../components/OutcomeChip'
import { Page } from '../components/Shell'
import { RecordError, RecordLoading, RecordNotFound } from '../components/RecordStates'
import { Transcript } from '../components/Transcript'
import { Eyebrow, LocalTime, SectionHeading } from '../components/primitives'

/**
 * The page the caller opens from their text message.
 *
 * Any query string on this URL — including the `?t=` token on links that were
 * already sent — is deliberately never read. The id in the path is the only
 * input.
 */
export default function CallRecordPage() {
  const { id } = useParams<{ id: string }>()
  const { state, retry } = useCallRecord(id)

  useEffect(() => {
    const name = state.status === 'ready' ? state.record.business_name : null
    document.title = name ? `Call record · ${name} · Frontdesk` : 'Call record · Frontdesk'
  }, [state])

  const shortId = id ? `${id.slice(0, 8)}${id.length > 8 ? '…' : ''}` : ''

  return (
    <Page
      aside={
        id ? (
          <span
            title={id}
            className="font-mono text-xs whitespace-nowrap text-ink"
            aria-label={`Record id ${id}`}
          >
            <span className="text-ink/70">rec&nbsp;</span>
            {shortId}
          </span>
        ) : undefined
      }
    >
      {state.status === 'loading' && <RecordLoading />}
      {state.status === 'missing' && <RecordNotFound id={id} />}
      {state.status === 'failed' && (
        <RecordError id={id ?? ''} reason={state.reason} onRetry={retry} />
      )}
      {state.status === 'ready' && <Record record={state.record} fixture={state.source === 'fixture'} />}
    </Page>
  )
}

function Record({ record, fixture }: { record: CallRecord; fixture: boolean }) {
  const meta = outcomeMeta(record.outcome)
  const elapsed = durationMs(record.started_at, record.ended_at)
  const inProgress = record.ended_at === null
  const callerTel = telHref(record.caller_number)
  const zone = localZoneLabel()

  return (
    <article className="mx-auto w-full max-w-6xl px-4 pt-8 pb-4 sm:px-6 sm:pt-10 lg:px-8">
      {fixture && (
        <p className="mb-6 inline-flex items-center gap-2 rounded-xs border border-dashed border-rule px-2.5 py-1 font-mono text-xs text-ink/70">
          sample record — not from the API
        </p>
      )}

      <header>
        <Eyebrow>Call record</Eyebrow>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-3xl font-semibold wide-set text-balance sm:text-4xl">
            {record.business_name ?? 'Unnamed business'}
          </h1>
          {record.profile_id && (
            <code className="font-mono text-xs text-ink/70">{record.profile_id}</code>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <OutcomeChip outcome={record.outcome} />
          <p className="text-sm text-ink/70">{meta.blurb}</p>
        </div>

        {/* Facts about the call itself, kept in the machine face. */}
        <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-5 border-y border-line py-5 sm:grid-cols-4">
          <div>
            <dt className="eyebrow text-ink/70">Caller</dt>
            <dd className="mt-1 font-mono text-sm">
              {callerTel ? (
                <a
                  href={callerTel}
                  className="underline decoration-rule decoration-1 underline-offset-4 hover:decoration-signal"
                >
                  {formatPhone(record.caller_number)}
                </a>
              ) : (
                formatPhone(record.caller_number)
              )}
            </dd>
          </div>
          <div>
            <dt className="eyebrow text-ink/70">Line called</dt>
            <dd className="mt-1 font-mono text-sm">{formatPhone(record.called_number)}</dd>
          </div>
          <div>
            <dt className="eyebrow text-ink/70">Started</dt>
            <dd className="mt-1 font-mono text-sm">
              <LocalTime iso={record.started_at}>{formatDateTime(record.started_at)}</LocalTime>
            </dd>
          </div>
          <div>
            <dt className="eyebrow text-ink/70">Duration</dt>
            <dd className="mt-1 font-mono text-sm">
              {inProgress ? (
                <span className="inline-flex items-center gap-1.5 text-signal-ink">
                  <span aria-hidden="true" className="live-dot size-1.5 rounded-full bg-signal" />
                  In progress
                </span>
              ) : elapsed !== null ? (
                formatDuration(elapsed)
              ) : (
                <span className="text-ink/70">Unknown</span>
              )}
            </dd>
          </div>
        </dl>

        <div className="mt-6">
          <CallTape
            startedAt={record.started_at}
            endedAt={record.ended_at}
            events={record.events}
          />
          <p className="mt-2 font-mono text-xs text-ink/70">
            Times shown in your local time{zone ? ` (${zone})` : ''}
          </p>
        </div>
      </header>

      <div className="mt-12 grid gap-12 lg:grid-cols-[minmax(0,25rem)_minmax(0,1fr)] lg:gap-14">
        {/* What was actually done. Given the first column deliberately: it is
            the part of the record that is not a paraphrase of anything. */}
        <div className="space-y-12">
          <section aria-labelledby="result-heading">
            <SectionHeading id="result-heading" title="Result" />
            {record.booking ? (
              <BookingPanel booking={record.booking} />
            ) : record.message ? (
              <MessagePanel message={record.message} />
            ) : (
              <div className="plate bg-sunken px-4 py-5 sm:px-6">
                <p className="text-sm text-ink/70">
                  {record.outcome === 'cancelled'
                    ? 'The appointment was cancelled. Nothing is scheduled and no message was taken.'
                    : 'No appointment was made and no message was taken on this call.'}
                </p>
              </div>
            )}
          </section>

          <section aria-labelledby="timeline-heading">
            <SectionHeading
              id="timeline-heading"
              title="What the agent did"
              aside={
                <span className="font-mono text-xs">
                  {record.events.length} {record.events.length === 1 ? 'action' : 'actions'}
                </span>
              }
            />
            <p className="mb-5 max-w-[58ch] text-sm text-ink/70">
              Recorded by the system as each action happened, not written up afterwards.
            </p>
            <EventTimeline events={record.events} startedAt={record.started_at} />
          </section>
        </div>

        {/* What was said. */}
        <section aria-labelledby="transcript-heading">
          <SectionHeading
            id="transcript-heading"
            title="What was said"
            aside={
              <span className="font-mono text-xs">
                {record.transcript.length} {record.transcript.length === 1 ? 'turn' : 'turns'}
              </span>
            }
          />
          <Transcript turns={record.transcript} startedAt={record.started_at} />
        </section>
      </div>
    </article>
  )
}
