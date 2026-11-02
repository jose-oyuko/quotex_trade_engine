// Generates src/api/schema.d.ts from docs/openapi.json (which the backend writes).
//
//   node scripts/api-types.mjs           write the file
//   node scripts/api-types.mjs --check   fail if the committed file is out of date
//
// The file is generated: never edit it by hand. Run `npm run api:generate` from the repository root
// after changing the backend API.
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const source = new URL('../../docs/openapi.json', import.meta.url)
const target = new URL('../src/api/schema.d.ts', import.meta.url)
const header =
  '// GENERATED from docs/openapi.json by scripts/api-types.mjs. Do not edit: run `npm run api:generate`.\n\n'

const text = header + astToString(await openapiTS(source))

if (process.argv.includes('--check')) {
  const current = await readFile(target, 'utf8').catch(() => '')
  if (current.replace(/\r\n/g, '\n') !== text) {
    console.error(`${fileURLToPath(target)} is out of date: run \`npm run api:generate\`.`)
    process.exit(1)
  }
  console.log('src/api/schema.d.ts is up to date.')
} else {
  await writeFile(target, text, 'utf8')
  console.log(`wrote ${fileURLToPath(target)}`)
}
