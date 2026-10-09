import { atom, read, update } from 'claude-code'
import type { Elements, EngineInterface, Register } from 'claude-code'

import type { Item, ProgressData, Status } from '../types'
import { STATUSES, STATUS_COLOR, STATUS_LABEL, allItems, bar, parseProgress, percentDone, tally } from './model'

const PANE = 'launch-progress'
const TITLE = 'Beta progress'
const POLL_MS = 30_000
const NAME_COLUMNS = 13
const DATA_FILE = '.claude/launch-progress.json'

const SHORT: Record<Status, string> = {
  building: 'building',
  ready: 'ready',
  handtest: 'hand test',
  owner: 'need you',
  todo: 'to do',
  done: 'done',
}

const data = atom({ plugin: 'launch-progress', key: 'data' } as const, null)
const error = atom({ plugin: 'launch-progress', key: 'error' } as const, null)
const view = atom({ plugin: 'launch-progress', key: 'view' } as const, 'summary')
const showDone = atom({ plugin: 'launch-progress', key: 'showDone' } as const, false)

type Els = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'>

/**
 * Reads .claude/launch-progress.json under the session root and stores it for the pane.
 * Input: the engine. Output: none; a read or parse failure is stored as the
 * error the pane shows, and the last good data stays on screen.
 */
async function load($: EngineInterface): Promise<void> {
  const root = await $.session.root()
  let text: string
  try {
    text = await $.fs.read(`${root}/${DATA_FILE}`)
  } catch {
    await update($, error, () => `Cannot read ${DATA_FILE} in ${root}`)
    return
  }
  const parsed = parseProgress(text)
  if ('error' in parsed) {
    await update($, error, () => parsed.error)
    return
  }
  await update($, error, () => null)
  await update($, data, () => parsed.data)
}

function line(name: string, items: readonly Item[], columns: number): string {
  const counts = tally(items)
  const width = Math.min(40, Math.max(6, columns - NAME_COLUMNS - 14))
  const label = name.length > NAME_COLUMNS - 1 ? `${name.slice(0, NAME_COLUMNS - 2)}.` : name
  return `${label.padEnd(NAME_COLUMNS)}${bar(counts, width)} ${counts.counts.done}/${counts.total}`
}

function summary(els: Els, $: EngineInterface, progress: ProgressData, columns: number) {
  const { Box, Text, Button } = els
  const everything = allItems(progress)
  const counts = tally(everything)
  const open = (id: string) => () => void update($, view, () => id)
  return (
    <Box flexDirection="column">
      <Text bold>{progress.title}</Text>
      <Text dimColor>{`Target ${progress.target}. Updated ${progress.updated}.`}</Text>
      <Box marginTop={1} flexDirection="column">
        <Button key="area:all" plain hotkey="a" label={line('Everything', everything, columns)} onPress={open('all')} />
        <Text>{`${percentDone(counts)}% done`}</Text>
      </Box>
      <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
        {STATUSES.map(status => (
          <Text color={STATUS_COLOR[status]}>{`${counts.counts[status]} ${SHORT[status]}`}</Text>
        ))}
      </Box>
      <Box marginTop={1} flexDirection="column">
        {progress.areas.map((area, index) => (
          <Button
            key={`area:${area.id}`}
            plain
            {...(index < 9 ? { hotkey: String(index + 1) } : {})}
            label={line(area.name, area.items, columns)}
            onPress={open(area.id)}
          />
        ))}
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text dimColor>Click a bar, or press its key, for the item list.</Text>
        <Text dimColor>█ done  ▓ built, waiting  ▒ building  ░ not started or needs you</Text>
        <Button key="refresh" plain hotkey="r" dimColor label="Refresh" onPress={() => void load($)} />
      </Box>
    </Box>
  )
}

function group(els: Els, status: Status, items: ReadonlyArray<Item & { area?: string }>) {
  const { Box, Text } = els
  const members = items.filter(item => item.status === status)
  return (
    <Box key={`group:${status}`} flexDirection="column" marginTop={1}>
      <Text bold color={STATUS_COLOR[status]}>{`${STATUS_LABEL[status]} (${members.length})`}</Text>
      {members.map((item, index) => {
        const detail = [item.area, item.note].filter(part => part !== undefined).join('. ')
        return (
          <Box key={`item:${status}:${index}`} flexDirection="column">
            <Text>{`${item.id}  ${item.title}`}</Text>
            {detail.length > 0 && <Text dimColor>{`    ${detail}`}</Text>}
          </Box>
        )
      })}
    </Box>
  )
}

function detail(els: Els, $: EngineInterface, progress: ProgressData, where: string, isDoneShown: boolean, columns: number) {
  const { Box, Text, Button } = els
  const area = progress.areas.find(candidate => candidate.id === where)
  const items = area === undefined ? allItems(progress) : area.items
  const name = area === undefined ? 'Everything' : area.name
  const counts = tally(items)
  const width = Math.min(40, Math.max(6, columns - 22))
  return (
    <Box flexDirection="column">
      <Button key="back" plain hotkey="b" label="Back to all areas" onPress={() => void update($, view, () => 'summary')} />
      <Box marginTop={1} flexDirection="column">
        <Text bold>{name}</Text>
        <Text>{`${bar(counts, width)} ${percentDone(counts)}%  ${counts.counts.done}/${counts.total} done`}</Text>
      </Box>
      {STATUSES.filter(status => status !== 'done' && counts.counts[status] > 0).map(status => group(els, status, items))}
      {counts.counts.done > 0 && isDoneShown && group(els, 'done', items)}
      {counts.counts.done > 0 && (
        <Box marginTop={1}>
          <Button
            key="toggle-done"
            plain
            hotkey="d"
            label={isDoneShown ? 'Hide done items' : `Show ${counts.counts.done} done items`}
            onPress={() => void update($, showDone, shown => !shown)}
          />
        </Box>
      )}
    </Box>
  )
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await load($)
    await $.command.register({ name: 'progress', description: 'Show launch progress in a side pane' })
    $.clock.every(POLL_MS, () => void load($))
    void $.ui.open({ id: PANE, title: TITLE })
    return next(e)
  })

  on('command.run', { command: 'progress' }, async $ => {
    await update($, view, () => 'summary')
    await load($)
    const opened = await $.ui.open({ id: PANE, title: TITLE })
    return { text: opened.isPlaced ? 'Beta progress pane opened.' : 'Widen the terminal to see the beta progress pane.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els: Els = $.ui.resolve(e)
    const { Box, Text } = els
    const progress = await read($, data)
    const failure = await read($, error)
    const where = await read($, view)
    const isDoneShown = await read($, showDone)
    const columns = Math.max(24, e.props.bodyColumns)
    if (progress === null) {
      return <Text color={failure === null ? 'inactive' : 'error'}>{failure ?? 'Loading progress...'}</Text>
    }
    const body = where === 'summary'
      ? summary(els, $, progress, columns)
      : detail(els, $, progress, where, isDoneShown, columns)
    return (
      <Box flexDirection="column">
        {failure !== null && <Text color="error">{`Data not refreshed: ${failure}`}</Text>}
        {body}
      </Box>
    )
  })
}
