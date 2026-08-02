import { useEffect } from 'react'
import { Page } from '../components/Shell'
import { PageNotFound } from '../components/RecordStates'

export default function NotFoundPage() {
  useEffect(() => {
    document.title = 'Not found · Frontdesk'
  }, [])

  return (
    <Page>
      <PageNotFound />
    </Page>
  )
}
