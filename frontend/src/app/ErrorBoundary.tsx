import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '../components/Button'

interface State {
  error: Error | null
}

/**
 * Catches a crash while drawing part of the page, so one broken table does not blank the whole
 * dashboard (and the kill switch stays reachable). The message is shown; the details are in the
 * browser console.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('The dashboard crashed while drawing a page:', error, info.componentStack)
  }

  override render(): ReactNode {
    if (this.state.error === null) return this.props.children
    return (
      <div role="alert" className="state-error">
        <h2>This part of the page failed to draw</h2>
        <p>{this.state.error.message}</p>
        <Button
          onClick={() => {
            this.setState({ error: null })
          }}
        >
          Try again
        </Button>
      </div>
    )
  }
}
