import type { Broker } from '../api/types'

/** The brokers, in the order they are shown (decision D-75). */
export const BROKERS: Broker[] = ['quotex', 'deriv']

export const BROKER_LABEL: Record<Broker, string> = { quotex: 'Quotex', deriv: 'Deriv' }

/** The brokers to show for a snapshot: the running engine's, else Quotex alone (as before). */
export function brokersShown(brokers: Broker[] | undefined): Broker[] {
  return brokers !== undefined && brokers.length > 0 ? brokers : ['quotex']
}
