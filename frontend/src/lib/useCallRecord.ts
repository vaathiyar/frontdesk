import { useCallback, useEffect, useState } from 'react'
import { fetchCallRecord, type LoadState } from './api'
import { FIXTURES, STATE_FIXTURES, isFixtureId } from './fixtures'

/**
 * Fixtures stand in for the API on ids beginning with `demo-`. Always on in
 * dev; opt in for a built bundle with VITE_USE_FIXTURES=1. Real ids are UUIDs,
 * so this can never shadow a live record.
 */
export const FIXTURES_ENABLED: boolean =
  import.meta.env.DEV || import.meta.env.VITE_USE_FIXTURES === '1'

/**
 * The whole data layer: one GET per id, on mount, plus an explicit retry for
 * when the network was the problem. No cache and no polling — a finished call
 * record does not change while you are reading it.
 */
export function useCallRecord(id: string | undefined): {
  state: LoadState
  retry: () => void
} {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    void attempt // re-runs the fetch when retry() bumps this

    if (!id) {
      setState({ status: 'missing' })
      return
    }

    setState({ status: 'loading' })

    if (FIXTURES_ENABLED && isFixtureId(id)) {
      if (id === STATE_FIXTURES.loading) return
      if (id === STATE_FIXTURES.missing) {
        setState({ status: 'missing' })
        return
      }
      if (id === STATE_FIXTURES.failed) {
        setState({ status: 'failed', reason: 'network' })
        return
      }
      const build = FIXTURES[id]
      setState(build ? { status: 'ready', record: build(), source: 'fixture' } : { status: 'missing' })
      return
    }

    const controller = new AbortController()
    void fetchCallRecord(id, controller.signal).then((next) => {
      if (!controller.signal.aborted) setState(next)
    })
    return () => controller.abort()
  }, [id, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  return { state, retry }
}
