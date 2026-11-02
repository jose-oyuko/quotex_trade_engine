import { useGroups } from '../../api/queries'
import type { AccountType, Strategy } from '../../api/types'
import type { DateRange, RangePreset } from '../../lib/dates'

export interface ReportControls {
  account: AccountType
  range: DateRange
  groupId: number | undefined
  strategy: Strategy | undefined
  asset: string
}

const PRESETS: { value: RangePreset; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: 'today', label: 'Today' },
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: 'custom', label: 'Custom dates' },
]

const STRATEGIES: { value: Strategy; label: string }[] = [
  { value: 'no_martingale', label: 'No martingale' },
  { value: 'martingale', label: 'Martingale' },
  { value: 'flip_every_loss', label: 'Flip every loss' },
  { value: 'two_step_flip', label: 'Two-step flip' },
]

/** What every report below is about. Demo and real are always one or the other, never mixed. */
export function FilterBar({
  value,
  onChange,
  rangeError,
}: {
  value: ReportControls
  onChange: (next: ReportControls) => void
  rangeError: string | null
}) {
  const groups = useGroups()
  const set = (patch: Partial<ReportControls>) => {
    onChange({ ...value, ...patch })
  }
  return (
    <form
      className="filters report-filters"
      aria-label="Report filters"
      onSubmit={(e) => {
        e.preventDefault()
      }}
    >
      <label>
        Account{' '}
        <select
          value={value.account}
          onChange={(event) => {
            set({ account: event.target.value as AccountType })
          }}
        >
          <option value="demo">Demo</option>
          <option value="real">Real money</option>
        </select>
      </label>
      <label>
        Period{' '}
        <select
          value={value.range.preset}
          onChange={(event) => {
            set({ range: { ...value.range, preset: event.target.value as RangePreset } })
          }}
        >
          {PRESETS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      {value.range.preset === 'custom' && (
        <>
          <label>
            From{' '}
            <input
              type="date"
              value={value.range.from ?? ''}
              onChange={(event) => {
                set({ range: { ...value.range, from: event.target.value } })
              }}
            />
          </label>
          <label>
            To (inclusive){' '}
            <input
              type="date"
              value={value.range.to ?? ''}
              onChange={(event) => {
                set({ range: { ...value.range, to: event.target.value } })
              }}
            />
          </label>
        </>
      )}
      <label>
        Group{' '}
        <select
          value={value.groupId ?? ''}
          onChange={(event) => {
            set({ groupId: event.target.value === '' ? undefined : Number(event.target.value) })
          }}
        >
          <option value="">All groups</option>
          {(groups.data?.items ?? []).map((group) => (
            <option key={group.id} value={group.id}>
              {group.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Strategy{' '}
        <select
          value={value.strategy ?? ''}
          onChange={(event) => {
            set({
              strategy: event.target.value === '' ? undefined : (event.target.value as Strategy),
            })
          }}
        >
          <option value="">All strategies</option>
          {STRATEGIES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Asset{' '}
        <input
          value={value.asset}
          placeholder="any"
          maxLength={32}
          onChange={(event) => {
            set({ asset: event.target.value.trim().toUpperCase() })
          }}
        />
      </label>
      {rangeError !== null && (
        <p role="alert" className="form-error">
          {rangeError}
        </p>
      )}
    </form>
  )
}
