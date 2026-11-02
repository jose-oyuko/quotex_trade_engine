import { formatMoney, moneySign } from '../lib/format'

/** An amount, as text. `signed` colours it by profit or loss (and a profit shows its plus). */
export function Money({
  value,
  signed = false,
}: {
  value: string | null | undefined
  signed?: boolean
}) {
  const kind = signed ? moneySign(value) : 'flat'
  const text = formatMoney(value)
  const shown = signed && kind === 'profit' && !text.startsWith('+') ? `+${text}` : text
  return <span className={`money money-${kind}`}>{shown}</span>
}
