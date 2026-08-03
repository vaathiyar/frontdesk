import { useEffect } from 'react'
import { Link } from 'react-router'
import { ArrowUpRight } from 'lucide-react'
import { Page } from '../components/Shell'
import { Eyebrow } from '../components/primitives'
import { FIXTURE_LINKS } from '../lib/fixtures'
import { FIXTURES_ENABLED } from '../lib/useCallRecord'

interface DemoLine {
  vertical: string
  name: string
  /** Written out the way you would read it aloud, not E.164. */
  display: string
  dial: string
  blurb: string
  area?: string
}

const LINES: DemoLine[] = [
  {
    vertical: 'HVAC',
    name: 'Helpdesk Heating and Cooling',
    display: '+1 604 296 9870',
    dial: '+16042969870',
    blurb: 'Books service visits — furnace and AC repairs, and seasonal tune-ups.',
    area: 'Greater Vancouver Area',
  },
  {
    vertical: 'Restaurant',
    name: 'Helpdesk Kitchen',
    display: '+1 604 296 9871',
    dial: '+16042969871',
    blurb: 'Books dinner reservations, and answers questions about the room and the hours.',
  },
]

const STEPS = [
  {
    n: '01',
    title: 'You call',
    body: 'Dial either number from any phone. It picks up and asks what you need.',
  },
  {
    n: '02',
    title: 'It sorts it out',
    body: 'Book a table or a service visit, move one, cancel one, ask what time they close. If it is something it cannot do, it takes a message for the business.',
  },
  {
    n: '03',
    title: 'You get a text',
    body: 'A confirmation lands on your phone, with a link to the record.',
  },
]

export default function Landing() {
  useEffect(() => {
    document.title = 'Frontdesk — an AI receptionist that answers the phone'
  }, [])

  return (
    <Page>
      <section className="mx-auto w-full max-w-6xl px-4 pt-14 pb-14 sm:px-6 sm:pt-20 lg:px-8">
        <div className="grid gap-x-12 gap-y-7 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <Eyebrow>Work in progress · Live demo</Eyebrow>
            <h1 className="mt-4 max-w-[20ch] text-4xl font-semibold wide-set text-balance sm:text-5xl">
              It answers the phone, and books the job.
            </h1>
          </div>
          <div className="lg:col-span-5 lg:pt-9">
            <p className="max-w-[46ch] text-lg text-ink/70">
              Frontdesk answers your phone when you cannot get to it, works out what the caller
              needs, and books, moves or cancels the appointment before they hang up. Then it texts
              them a link to the call record.
            </p>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="numbers-heading"
        className="border-y border-line bg-sunken py-14 sm:py-16"
      >
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
          <h2 id="numbers-heading" className="text-xl font-semibold wide-set">
            Call one of these numbers
          </h2>
          <p className="mt-2 max-w-[58ch] text-ink/70">
            Standard call rates apply. Call audio is not retained. The transcript and call
            details are stored and accessible via the SMS link.
          </p>

          <ul className="mt-8 grid gap-4 md:grid-cols-2 md:gap-6">
            {LINES.map((line) => (
              <li key={line.dial}>
                <a
                  href={`tel:${line.dial}`}
                  className="plate group flex h-full flex-col p-5 transition-colors duration-150 hover:border-ink sm:p-6"
                >
                  <div className="flex items-start justify-between gap-3">
                    <Eyebrow className="text-signal-ink">{line.vertical}</Eyebrow>
                    <ArrowUpRight
                      aria-hidden="true"
                      className="size-4 shrink-0 text-ink/40 group-hover:text-signal-ink"
                      strokeWidth={2}
                    />
                  </div>

                  <p className="mt-3 text-lg font-semibold wide-set">{line.name}</p>

                  <p className="mt-5 font-mono text-[2rem] leading-none tracking-[-0.015em] text-ink sm:text-[2.4rem]">
                    {line.display}
                  </p>

                  <p className="mt-5 max-w-[46ch] text-sm text-ink/70">{line.blurb}</p>
                  {line.area && (
                    <p className="mt-2 font-mono text-xs text-ink/70">Service area: {line.area}</p>
                  )}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="steps-heading" className="py-16 sm:py-20">
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
          <h2 id="steps-heading" className="text-xl font-semibold wide-set">
            What happens after you call
          </h2>
          {/* Numbered because this genuinely is a sequence, not for decoration. */}
          <ol className="mt-8 grid gap-8 md:grid-cols-3 md:gap-10">
            {STEPS.map((step) => (
              <li key={step.n} className="border-t border-rule pt-4">
                <span className="eyebrow text-signal-ink">{step.n}</span>
                <h3 className="mt-2 text-lg font-semibold wide-set">{step.title}</h3>
                <p className="mt-2 max-w-[46ch] text-ink/70">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section
        aria-labelledby="record-heading"
        className="border-t border-line py-16 sm:py-20"
      >
        <div className="mx-auto grid w-full max-w-6xl gap-x-12 gap-y-10 px-4 sm:px-6 lg:grid-cols-12 lg:px-8">
          <div className="lg:col-span-5">
            <h2 id="record-heading" className="text-2xl font-semibold wide-set text-balance">
              Every call has a record
            </h2>
            <p className="mt-4 max-w-[40ch] text-pretty text-lg text-ink/70">
              Open it when you want to know how a call went.
            </p>
          </div>

          <dl className="grid gap-8 sm:grid-cols-2 sm:gap-10 lg:col-span-7">
            <div className="border-t border-rule pt-4">
              <dt className="text-lg font-semibold wide-set">What was said</dt>
              <dd className="mt-2 max-w-[40ch] text-ink/70">
                Every turn of the conversation, timed.
              </dd>
            </div>
            <div className="border-t border-signal pt-4">
              <dt className="text-lg font-semibold wide-set">What Frontdesk did</dt>
              <dd className="mt-2 max-w-[40ch] text-ink/70">
                The times it offered, the appointment it booked or moved, and whether the text went
                out.
              </dd>
            </div>
          </dl>
        </div>
      </section>

      {FIXTURES_ENABLED && <FixtureIndex />}
    </Page>
  )
}

/**
 * Dev-only index of the bundled sample records, including the ids that force
 * the loading, not-found and error states. Hidden in a production build unless
 * VITE_USE_FIXTURES=1.
 */
function FixtureIndex() {
  return (
    <section
      aria-labelledby="samples-heading"
      className="mx-auto w-full max-w-6xl px-4 pb-4 sm:px-6 lg:px-8"
    >
      <div className="rounded-xs border border-dashed border-rule p-5 sm:p-6">
        <h2 id="samples-heading" className="eyebrow text-ink/70">
          Sample records
        </h2>
        <ul className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          {FIXTURE_LINKS.map((link) => (
            <li key={link.id}>
              <Link
                to={`/c/${link.id}`}
                className="group flex min-h-11 items-baseline gap-2 py-1 text-sm"
              >
                <span className="font-medium group-hover:text-signal-ink">{link.label}</span>
                <span className="font-mono text-xs text-ink/70">{link.note}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
