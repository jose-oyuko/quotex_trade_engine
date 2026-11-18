import { describe, expect, it } from 'vitest'
import { BROKER_LABEL, brokersShown } from './brokers'

describe('the brokers shown', () => {
  it('are the running engine’s, else Quotex alone as before', () => {
    expect(brokersShown(['quotex', 'deriv'])).toEqual(['quotex', 'deriv'])
    expect(brokersShown(['deriv'])).toEqual(['deriv'])
    expect(brokersShown([])).toEqual(['quotex'])
    expect(brokersShown(undefined)).toEqual(['quotex'])
    expect(BROKER_LABEL.deriv).toBe('Deriv')
  })
})
