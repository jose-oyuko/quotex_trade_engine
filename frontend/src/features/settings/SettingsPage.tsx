import { useEngine, useSecrets, useSettings, useStatus, useTelegramLogin } from '../../api/queries'
import { DataState } from '../../components/DataState'
import { EnginePanel } from './EnginePanel'
import { SecretsPanel } from './SecretsPanel'
import { SettingsForm } from './SettingsForm'
import { TelegramPanel } from './TelegramPanel'

export default function SettingsPage() {
  const engine = useEngine()
  const status = useStatus()
  const telegram = useTelegramLogin()
  const settings = useSettings()
  const secrets = useSecrets()
  return (
    <section aria-labelledby="settings-heading">
      <h1 id="settings-heading">Settings</h1>
      <p className="lead">
        What used to be edited in <code>backend/.env</code> is changed here.
      </p>
      <DataState query={engine}>
        {(info) => <EnginePanel engine={info} account={status.data?.account_type ?? 'demo'} />}
      </DataState>
      <DataState query={telegram}>{(data) => <TelegramPanel status={data} />}</DataState>
      <DataState query={settings}>{(data) => <SettingsForm data={data} />}</DataState>
      <DataState query={secrets}>{(data) => <SecretsPanel data={data} />}</DataState>
    </section>
  )
}
