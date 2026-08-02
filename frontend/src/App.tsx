import { BrowserRouter, Route, Routes } from 'react-router'
import Landing from './routes/Landing'
import CallRecordPage from './routes/CallRecordPage'
import NotFoundPage from './routes/NotFoundPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        {/* The URL sent by SMS. Trailing query strings such as ?t=<hex> are ignored. */}
        <Route path="/c/:id" element={<CallRecordPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
