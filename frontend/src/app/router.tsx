import type { RouteObject } from 'react-router-dom'
import { Layout } from './Layout'
import { NotFound, RouteError } from './RouteViews'

/** Each page is its own chunk: the browser downloads a page's code when it is first opened. */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import('../features/live/LivePage')).default }),
      },
      {
        path: 'signals',
        lazy: async () => ({
          Component: (await import('../features/signals/SignalsPage')).default,
        }),
      },
      {
        path: 'groups',
        lazy: async () => ({ Component: (await import('../features/groups/GroupsPage')).default }),
      },
      {
        path: 'groups/new',
        lazy: async () => ({
          Component: (await import('../features/groups/GroupFormPage')).default,
        }),
      },
      {
        path: 'groups/:id/edit',
        lazy: async () => ({
          Component: (await import('../features/groups/GroupFormPage')).default,
        }),
      },
      {
        path: 'history',
        lazy: async () => ({
          Component: (await import('../features/history/HistoryPage')).default,
        }),
      },
      {
        path: 'reports',
        lazy: async () => ({
          Component: (await import('../features/reports/ReportsPage')).default,
        }),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]
