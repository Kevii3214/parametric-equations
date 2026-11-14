import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dispatch from './pages/Dispatch'
import Medic from './pages/Medic'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/dispatch" element={<Dispatch />} />
          <Route path="/medic" element={<Medic />} />
          <Route path="*" element={<Navigate to="/dispatch" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
