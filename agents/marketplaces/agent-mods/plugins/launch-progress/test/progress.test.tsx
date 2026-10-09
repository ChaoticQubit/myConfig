import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { bar, parseProgress, percentDone, tally } from '../hooks/model'

const FIXTURE = JSON.stringify({
  title: 'Demo beta',
  updated: '2026-10-08 18:50',
  target: '2026-10-30',
  areas: [
    {
      id: 'auth',
      name: 'Auth',
      items: [
        { id: 'SCH-1', title: 'Sign-up works', status: 'done' },
        { id: 'SCH-2', title: 'Refresh reply lost', status: 'todo', note: 'High' },
        { id: 'SCH-3', title: 'Windows keys', status: 'building' },
        { id: 'SCH-4', title: 'Linux hand test', status: 'owner' },
      ],
    },
    {
      id: 'infra',
      name: 'Infra',
      items: [{ id: 'SCH-5', title: 'Gateway config', status: 'ready' }],
    },
  ],
})

function standIn(on: On, file: string, paths: string[] = []): void {
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.root', () => ({ value: '/proj' }))
  on('command.register', (_$, e) => ({ value: { command: e.name } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('clock.every', () => ({ value: undefined }))
  on('fs.read', (_$, e) => {
    paths.push(e.path)
    return { value: file }
  })
}

const PANE = { component: 'Pane', props: { title: 'Beta progress', isFocused: true, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} } } as const

test('a bar has exactly the asked width and fills done cells first', () => {
  const counts = tally([
    { id: 'a', title: 'a', status: 'done' },
    { id: 'b', title: 'b', status: 'ready' },
    { id: 'c', title: 'c', status: 'building' },
    { id: 'd', title: 'd', status: 'todo' },
  ])
  expect(bar(counts, 8)).toBe('██▓▓▒▒░░')
  expect(percentDone(counts)).toBe(25)
  expect(bar(tally([]), 5)).toBe('░░░░░')
})

test('a malformed file is refused with the field named', () => {
  expect(parseProgress('{')).toEqual({ error: 'progress.json is not valid JSON' })
  const untitled = JSON.stringify({ updated: 'now', target: 'soon', areas: [{ id: 'x', name: 'X', items: [] }] })
  expect(parseProgress(untitled)).toEqual({ error: 'title must be a short string' })
  const badStatus = JSON.stringify({
    title: 'T', updated: 'now', target: 'soon',
    areas: [{ id: 'x', name: 'X', items: [{ id: 'i', title: 't', status: 'maybe' }] }],
  })
  expect(parseProgress(badStatus)).toEqual({ error: 'area x item 0 is malformed' })
  const reserved = JSON.stringify({ title: 'T', updated: 'now', target: 'soon', areas: [{ id: 'all', name: 'All', items: [] }] })
  expect(parseProgress(reserved)).toEqual({ error: 'area id all is repeated or reserved' })
})

test('the data is read from the session root, never from the plugin folder', async ($, on) => {
  const paths: string[] = []
  standIn(on, FIXTURE, paths)
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  expect(paths).toEqual(['/proj/.claude/launch-progress.json'])
  const ui = await $.ui.mount({ plugin: 'launch-progress', surface: 'terminal', requestId: 'launch-progress', ...PANE })
  expect(await ui.find({ type: 'Text', text: 'Demo beta' })).toBeDefined()
  await ui.unmount()
})

test('pressing an area bar opens its item list grouped by status, and Back returns', async ($, on) => {
  standIn(on, FIXTURE)
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'launch-progress', surface, requestId: 'launch-progress', ...PANE })
    expect((await ui.find({ key: 'area:auth' }))?.text).toMatch(/^Auth\s+█+.*1\/4$/)
    expect(await ui.find({ type: 'Text', text: '20% done' })).toBeDefined()
    await ui.press({ key: 'area:auth' })
    expect(await ui.find({ type: 'Text', text: 'Needs you (1)' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'SCH-4  Linux hand test' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'SCH-1  Sign-up works' })).toBeUndefined()
    await ui.press({ key: 'toggle-done' })
    expect(await ui.find({ type: 'Text', text: 'SCH-1  Sign-up works' })).toBeDefined()
    await ui.press({ key: 'toggle-done' })
    await ui.press({ key: 'back' })
    expect(await ui.find({ key: 'area:infra' })).toBeDefined()
    await ui.unmount()
  }
})

test('pressing the overall bar lists every area item with its area name', async ($, on) => {
  standIn(on, FIXTURE)
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'launch-progress', surface: 'terminal', requestId: 'launch-progress', ...PANE })
  await ui.press({ key: 'area:all' })
  expect(await ui.find({ type: 'Text', text: 'SCH-5  Gateway config' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '    Infra' })).toBeDefined()
  await ui.unmount()
})

test('a broken data file shows the reason instead of the bars', async ($, on) => {
  standIn(on, '{"title": "T", "updated": 1}')
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'launch-progress', surface: 'terminal', requestId: 'launch-progress', ...PANE })
  expect(await ui.find({ type: 'Text', text: 'updated must be a short string' })).toBeDefined()
  await ui.unmount()
})
