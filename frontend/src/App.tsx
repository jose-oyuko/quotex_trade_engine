import { useState } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { AppProviders } from './app/providers'
import { routes } from './app/router'

export default function App() {
  const [router] = useState(() => createBrowserRouter(routes))
  return (
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  )
}
