import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { invalidateSessions, useSessionRuns, useSessions, useStatus } from '../../api/queries'
import type { Session, SessionRun } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Countdown } from '../../components/Countdown'
import { DataState } from '../../components/DataState'
import { Money } from '../../components/Money'
import { Pagination } from '../../components/Pagination'
import { errorMessage } from '../../lib/errors'
import { formatDateTime, titleCase } from '../../lib/format'
import { ChainsPanel } from '../live/ChainsPanel'
import { repeatText, runStateText, spacingText } from './runText'
import { fromSession, toInput } from './sessionSchema'

/** The run that is going now: what it has done, how it stands against its targets, and its chains. */
function RunPanel({
  session,
  run,
  onStop,
}: {
  session: Session
  run: SessionRun
  onStop: () => void
}) {
  const { data: status } = useStatus()
  const chains = (status?.open_chains ?? []).filter((c) => c.session_run_id === run.id)
  return (
    <section className="run-panel" aria-labelledby="run-heading">
      <div className="page-head">
        <h2 id="run-heading">Running now: {session.name}</h2>
        <Button variant="danger" onClick={onStop} aria-label={`Stop ${session.name}`}>
          Stop…
        </Button>
      </div>
      <p>
        <Badge tone={run.state === 'running' ? 'good' : 'warn'}>{runStateText(run)}</Badge>{' '}
        {run.started_by === 'manual' ? 'Started by you' : 'Started by its schedule'} at{' '}
        {formatDateTime(run.started_at)}. Window ends {formatDateTime(run.window_end)} (
        <Countdown until={run.window_end} /> left).
      </p>
      <dl className="facts">
        <div>
          <dt>Profit so far</dt>
          <dd>
            <Money value={run.profit} signed />
            {session.profit_target !== null && (
              <small> of a target of {session.profit_target}</small>
            )}
            {session.loss_limit !== null && <small> · loss limit {session.loss_limit}</small>}
          </dd>
        </div>
        <div>
          <dt>Pairs opened</dt>
          <dd>
            {run.pairs_opened}
            {session.max_pairs !== null && <small> of at most {session.max_pairs}</small>}
          </dd>
        </div>
        <div>
          <dt>Rounds skipped</dt>
          <dd>{run.rounds_skipped}</dd>
        </div>
        {run.lopsided_pairs > 0 && (
          <div>
            <dt>Pairs with one leg only</dt>
            <dd>{run.lopsided_pairs}</dd>
          </div>
        )}
      </dl>
      {run.note !== null && <p className="help">Last note: {run.note}</p>}
      <h3>Its chains</h3>
      <ChainsPanel chains={chains} />
    </section>
  )
}

function SessionRow({
  session,
  onDelete,
  onStop,
}: {
  session: Session
  onDelete: (session: Session) => void
  onStop: (session: Session) => void
}) {
  const client = useQueryClient()
  const change = useMutation({
    mutationFn: async (action: 'toggle' | 'start') => {
      if (action === 'start') return api.sessions.start(session.id)
      const values = fromSession(session)
      return api.sessions.update(session.id, toInput({ ...values, enabled: !session.enabled }))
    },
    onSuccess: () => invalidateSessions(client),
  })
  const running = session.active_run !== null
  const strategy = session.strategy
  return (
    <>
      <tr>
        <td>
          <strong>{session.name}</strong>
          <br />
          <small>
            {session.asset} · {String(session.duration_s / 60)} min
          </small>
        </td>
        <td>
          {session.start_time.slice(0, 5)}–{session.end_time.slice(0, 5)}
          <br />
          <small>
            {session.timezone} · {repeatText(session)}
          </small>
        </td>
        <td>
          {strategy ? titleCase(strategy.strategy) : '—'}
          <br />
          <small>
            {spacingText(session)}
            {strategy ? ` · base ${strategy.base_stake}` : ''}
          </small>
        </td>
        <td>
          {session.profit_target !== null || session.loss_limit !== null ? (
            <>
              {session.profit_target !== null && <div>Profit {session.profit_target}</div>}
              {session.loss_limit !== null && <div>Loss {session.loss_limit}</div>}
            </>
          ) : (
            'None'
          )}
        </td>
        <td>
          {session.next_window_start !== null ? formatDateTime(session.next_window_start) : '—'}
        </td>
        <td>
          <Badge tone={session.enabled ? 'good' : 'muted'}>
            {session.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
          {running && <Badge tone="warn">Running</Badge>}
        </td>
        <td className="actions">
          <Link
            className="btn btn-default"
            to={`/sessions/${String(session.id)}/edit`}
            aria-label={`Edit ${session.name}`}
          >
            Edit
          </Link>
          {running ? (
            <Button
              variant="danger"
              onClick={() => {
                onStop(session)
              }}
              aria-label={`Stop ${session.name}`}
            >
              Stop…
            </Button>
          ) : (
            <Button
              onClick={() => {
                change.mutate('start')
              }}
              disabled={change.isPending || !session.enabled}
              aria-label={`Start ${session.name} now`}
            >
              Start now
            </Button>
          )}
          <Button
            onClick={() => {
              change.mutate('toggle')
            }}
            disabled={change.isPending || running}
            aria-label={`${session.enabled ? 'Disable' : 'Enable'} ${session.name}`}
          >
            {session.enabled ? 'Disable' : 'Enable'}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              onDelete(session)
            }}
            disabled={running}
            aria-label={`Delete ${session.name}`}
          >
            Delete…
          </Button>
        </td>
      </tr>
      {session.warnings.length > 0 && (
        <tr>
          <td colSpan={7}>
            {session.warnings.map((warning) => (
              <p key={warning} role="note" className="form-warning">
                {session.name}: {warning}
              </p>
            ))}
          </td>
        </tr>
      )}
      {change.isError && (
        <tr>
          <td colSpan={7}>
            <p role="alert" className="form-error">
              {session.name}: {errorMessage(change.error)}
            </p>
          </td>
        </tr>
      )}
    </>
  )
}

function History({ sessions }: { sessions: Session[] }) {
  const [paging, setPaging] = useState({ limit: 10, offset: 0 })
  const runs = useSessionRuns(paging)
  const names = new Map(sessions.map((s) => [s.id, s.name]))
  return (
    <section aria-labelledby="runs-heading">
      <h2 id="runs-heading">Past runs</h2>
      <DataState query={runs} isEmpty={(page) => page.total === 0} empty="No session has run yet.">
        {(page) => (
          <>
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Runs of the trading sessions, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Session</th>
                    <th scope="col">Started</th>
                    <th scope="col">Ended</th>
                    <th scope="col">How it ended</th>
                    <th scope="col">Pairs</th>
                    <th scope="col">Skipped</th>
                    <th scope="col">Profit</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((run) => (
                    <tr key={run.id}>
                      <td>{names.get(run.session_id) ?? `Session ${String(run.session_id)}`}</td>
                      <td>{formatDateTime(run.started_at)}</td>
                      <td>{run.ended_at === null ? '—' : formatDateTime(run.ended_at)}</td>
                      <td>
                        {runStateText(run)}
                        {run.note !== null && run.state === 'ended' && (
                          <>
                            <br />
                            <small>{run.note}</small>
                          </>
                        )}
                      </td>
                      <td>{run.pairs_opened}</td>
                      <td>{run.rounds_skipped}</td>
                      <td>
                        <Money value={run.profit} signed />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              offset={page.offset}
              limit={page.limit}
              total={page.total}
              onChange={(offset) => {
                setPaging((old) => ({ ...old, offset }))
              }}
            />
          </>
        )}
      </DataState>
    </section>
  )
}

export default function SessionsPage() {
  const sessions = useSessions()
  const client = useQueryClient()
  const [deleting, setDeleting] = useState<Session | null>(null)
  const [stopping, setStopping] = useState<Session | null>(null)
  const remove = useMutation({
    mutationFn: (session: Session) => api.sessions.remove(session.id),
    onSuccess: async () => {
      setDeleting(null)
      await invalidateSessions(client)
    },
  })
  const stop = useMutation({
    mutationFn: (session: Session) => api.sessions.stop(session.id),
    onSuccess: async () => {
      setStopping(null)
      await invalidateSessions(client)
    },
  })

  return (
    <section aria-labelledby="sessions-heading">
      <div className="page-head">
        <h1 id="sessions-heading">Sessions</h1>
        <Link className="btn btn-primary" to="/sessions/new">
          Add a session
        </Link>
      </div>
      <p className="lead">
        A session trades by the clock, with no Telegram signal: in its window it opens pairs (a CALL
        and a PUT together) on one asset. Only one session runs at a time. When a session stops (the
        window ends, a target is reached, you press Stop) no new pair opens, but the chains already
        running always finish. Signals from your Telegram groups are not affected.
      </p>
      <DataState
        query={sessions}
        isEmpty={(page) => page.total === 0}
        empty="No sessions yet. Add one to trade by a schedule."
      >
        {(page) => {
          const active = page.items.find((s) => s.active_run !== null)
          return (
            <>
              {active?.active_run != null && (
                <RunPanel
                  session={active}
                  run={active.active_run}
                  onStop={() => {
                    setStopping(active)
                  }}
                />
              )}
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">Trading sessions</caption>
                  <thead>
                    <tr>
                      <th scope="col">Session</th>
                      <th scope="col">Window</th>
                      <th scope="col">Strategy</th>
                      <th scope="col">Stops at</th>
                      <th scope="col">Next start</th>
                      <th scope="col">Status</th>
                      <th scope="col">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((session) => (
                      <SessionRow
                        key={session.id}
                        session={session}
                        onDelete={setDeleting}
                        onStop={setStopping}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              <History sessions={page.items} />
            </>
          )
        }}
      </DataState>

      {stopping !== null && (
        <ConfirmDialog
          title="Stop this session?"
          confirmLabel="Stop the session"
          danger
          busy={stop.isPending}
          error={stop.isError ? errorMessage(stop.error) : null}
          onConfirm={() => {
            stop.mutate(stopping)
          }}
          onCancel={() => {
            setStopping(null)
            stop.reset()
          }}
        >
          <p>
            <strong>{stopping.name}</strong> will open no new pair. The chains that are running are{' '}
            <strong>not</strong> cut off: a trade that lost still recovers, so the result can still
            change.
          </p>
        </ConfirmDialog>
      )}

      {deleting !== null && (
        <ConfirmDialog
          title="Delete this session?"
          confirmLabel="Delete session"
          danger
          busy={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => {
            remove.mutate(deleting)
          }}
          onCancel={() => {
            setDeleting(null)
            remove.reset()
          }}
        >
          <p>
            Delete <strong>{deleting.name}</strong> and its settings. This only works for a session
            that has never run; otherwise disable it instead.
          </p>
        </ConfirmDialog>
      )}
    </section>
  )
}
