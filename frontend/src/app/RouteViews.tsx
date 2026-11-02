import { Link, useRouteError } from 'react-router-dom'

export function NotFound() {
  return (
    <section>
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the live page</Link>
      </p>
    </section>
  )
}

export function RouteError() {
  const error = useRouteError()
  return (
    <main>
      <div role="alert" className="state-error">
        <h1>Something went wrong</h1>
        <p>{error instanceof Error ? error.message : 'Unknown error'}</p>
        <p>
          <Link to="/">Back to the live page</Link>
        </p>
      </div>
    </main>
  )
}
