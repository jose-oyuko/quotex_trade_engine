import { useSecrets, useSettings } from '../../api/queries'
import { DataState } from '../../components/DataState'
import { SecretsPanel } from './SecretsPanel'
import { SettingsForm } from './SettingsForm'

export default function SettingsPage() {
  const settings = useSettings()
  const secrets = useSecrets()
  return (
    <section aria-labelledby="settings-heading">
      <h1 id="settings-heading">Settings</h1>
      <p className="lead">
        What used to be edited in <code>backend/.env</code> is changed here.
      </p>
      <DataState query={settings}>{(data) => <SettingsForm data={data} />}</DataState>
      <DataState query={secrets}>{(data) => <SecretsPanel data={data} />}</DataState>
    </section>
  )
}
