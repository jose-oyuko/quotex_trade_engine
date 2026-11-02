// Names for the shapes the backend sends and accepts. They all come from the generated
// `schema.d.ts` (which comes from the backend's models), so nothing here can drift from the API.
import type { components } from './schema'

type Schemas = components['schemas']

export type Health = Schemas['HealthResponse']
export type Snapshot = Schemas['SnapshotOut']
export type Group = Schemas['GroupOut']
export type GroupCreate = Schemas['GroupCreateIn']
export type GroupUpdate = Schemas['GroupUpdateIn']
export type GroupSettingsInput = Schemas['GroupSettingsIn']
export type Chain = Schemas['ChainOut']
export type ChainDetail = Schemas['ChainDetailOut']
export type Trade = Schemas['TradeOut']
export type Signal = Schemas['SignalOut']
export type RiskEvent = Schemas['RiskEventOut']
export type Risk = Schemas['RiskOut']
export type RiskLimits = Schemas['RiskLimitsOut']
export type RiskLimitsInput = Schemas['RiskLimitsIn']
export type GroupRiskLimits = Schemas['GroupRiskLimitsOut']
export type GroupRiskLimitsInput = Schemas['GroupRiskLimitsIn']
export type Controls = Schemas['ControlsOut']
export type Account = Schemas['AccountOut']
export type ChainControl = Schemas['ChainControlOut']
export type Balance = Schemas['BalanceOut']

export type ReportSummary = Schemas['SummaryOut']
export type ReportBreakdown = Schemas['BreakdownOut']
export type ReportBreakdownRow = Schemas['BreakdownRowOut']
export type ReportEquity = Schemas['EquityOut']
export type ReportDepth = Schemas['DepthOut']
export type ReportMetrics = Schemas['MetricsOut']
export type BreakdownKind = ReportBreakdown['by']

export type AccountType = Schemas['AccountType']
export type ChainStatus = Schemas['ChainStatus']
export type TradeStatus = Schemas['TradeStatus']
export type SignalStatus = Schemas['SignalStatus']
export type Strategy = Schemas['Strategy']

export type Page<T> = { items: T[]; total: number; limit: number; offset: number }

/** Everything the server can send on /ws, discriminated by `type`. */
export type ServerMessage = Schemas['ServerMessage']
export type SnapshotMessage = Schemas['SnapshotMessage']
export type ClientMessage = Schemas['ClientMessage']
