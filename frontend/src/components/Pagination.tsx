import { Button } from './Button'
import { PAGE_SIZES } from './pageSizes'

/** Page controls for a server-paged list. `offset`/`limit`/`total` come straight from the API. */
export function Pagination({
  offset,
  limit,
  total,
  onChange,
  onLimitChange,
}: {
  offset: number
  limit: number
  total: number
  onChange: (offset: number) => void
  onLimitChange?: (limit: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / limit))
  const page = Math.floor(offset / limit) + 1
  const first = total === 0 ? 0 : offset + 1
  const last = Math.min(total, offset + limit)
  return (
    <nav className="pagination" aria-label="Pages">
      <span aria-live="polite">
        {first}–{last} of {total.toLocaleString('en-US')}
      </span>
      <Button
        onClick={() => {
          onChange(Math.max(0, offset - limit))
        }}
        disabled={offset === 0}
      >
        Previous
      </Button>
      <span>
        Page {page} of {pages}
      </span>
      <Button
        onClick={() => {
          onChange(offset + limit)
        }}
        disabled={offset + limit >= total}
      >
        Next
      </Button>
      {onLimitChange && (
        <label>
          Rows per page{' '}
          <select
            value={limit}
            onChange={(event) => {
              onLimitChange(Number(event.target.value))
            }}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      )}
    </nav>
  )
}
