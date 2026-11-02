import { QueryClient } from '@tanstack/react-query'

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // Lists are refreshed by the live feed when something relevant happens, so a short stale time
      // is enough; one retry covers a hiccup without hiding a real failure for long.
      queries: { staleTime: 10_000, retry: 1 },
    },
  })
}
