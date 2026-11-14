import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import Arrival from './pages/Arrival'
import PreArrival from './pages/PreArrival'

/** Old links (/dispatch, /medic, /) go to Pre-arrival, keeping ?incident= / ?demo= / ?building=. */
function ToPreArrival() {
  const { search } = useLocation()
  return <Navigate to={{ pathname: '/pre-arrival', search }} replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/pre-arrival" element={<PreArrival />} />
          <Route path="/arrival" element={<Arrival />} />
          <Route path="*" element={<ToPreArrival />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
