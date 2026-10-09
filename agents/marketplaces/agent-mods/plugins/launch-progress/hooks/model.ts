import type { Area, Item, ProgressData, Status, Tally } from '../types'

export const STATUSES: readonly Status[] = ['building', 'ready', 'handtest', 'owner', 'todo', 'done']

export const STATUS_LABEL: Record<Status, string> = {
  building: 'Building now',
  ready: 'Built, ready to ship',
  handtest: 'Built, waiting for your hand test',
  owner: 'Needs you',
  todo: 'Not started',
  done: 'Done',
}

export const STATUS_COLOR: Record<Status, string> = {
  building: 'claude',
  ready: 'suggestion',
  handtest: 'warning',
  owner: 'error',
  todo: 'inactive',
  done: 'success',
}

const AREAS_MAX = 20
const ITEMS_PER_AREA_MAX = 400
const TEXT_LENGTH_MAX = 300

export type Parsed = { data: ProgressData } | { error: string }

/**
 * Parses and validates the text of .claude/launch-progress.json.
 * Input: the file's text, untrusted. Output: the data, or an error saying
 * which field is wrong. Bounds every list and string so a bad file cannot
 * blow up the pane.
 */
export function parseProgress(text: string): Parsed {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return { error: 'progress.json is not valid JSON' }
  }
  if (!isRecord(raw)) return { error: 'progress.json must hold an object' }
  if (!isText(raw.title)) return { error: 'title must be a short string' }
  if (!isText(raw.updated)) return { error: 'updated must be a short string' }
  if (!isText(raw.target)) return { error: 'target must be a short string' }
  if (!Array.isArray(raw.areas)) return { error: 'areas must be a list' }
  if (raw.areas.length === 0 || raw.areas.length > AREAS_MAX) {
    return { error: `areas must hold 1 to ${AREAS_MAX} entries` }
  }
  const areas: Area[] = []
  const seen = new Set<string>()
  for (const [index, entry] of raw.areas.entries()) {
    const area = parseArea(entry, index)
    if ('error' in area) return area
    if (seen.has(area.area.id) || area.area.id === 'all') {
      return { error: `area id ${area.area.id} is repeated or reserved` }
    }
    seen.add(area.area.id)
    areas.push(area.area)
  }
  return { data: { title: raw.title, updated: raw.updated, target: raw.target, areas } }
}

function parseArea(entry: unknown, index: number): { area: Area } | { error: string } {
  if (!isRecord(entry)) return { error: `area ${index} must be an object` }
  if (!isText(entry.id) || !isText(entry.name)) {
    return { error: `area ${index} needs a short id and name` }
  }
  if (!Array.isArray(entry.items) || entry.items.length > ITEMS_PER_AREA_MAX) {
    return { error: `area ${entry.id} items must be a list of at most ${ITEMS_PER_AREA_MAX}` }
  }
  const items: Item[] = []
  for (const [position, value] of entry.items.entries()) {
    const item = parseItem(value)
    if (item === undefined) return { error: `area ${entry.id} item ${position} is malformed` }
    items.push(item)
  }
  return { area: { id: entry.id, name: entry.name, items } }
}

function parseItem(value: unknown): Item | undefined {
  if (!isRecord(value)) return undefined
  if (!isText(value.id) || !isText(value.title) || !isStatus(value.status)) return undefined
  if (value.note !== undefined && !isText(value.note)) return undefined
  const item: Item = { id: value.id, title: value.title, status: value.status }
  if (value.note !== undefined) item.note = value.note
  return item
}

/**
 * Counts items per status.
 * Input: any list of items. Output: the count of each status and the total.
 * Throws if the counts do not add up, which no valid input can cause.
 */
export function tally(items: readonly Item[]): Tally {
  const counts: Record<Status, number> = {
    building: 0, ready: 0, handtest: 0, owner: 0, todo: 0, done: 0,
  }
  for (const item of items) counts[item.status] += 1
  const sum = STATUSES.reduce((total, status) => total + counts[status], 0)
  if (sum !== items.length) throw new Error('tally: status counts do not add up to the item count')
  return { counts, total: items.length }
}

/**
 * Draws a progress bar of exactly `width` cells.
 * Input: a tally and a width of 1 or more. Output: done cells, then cells
 * built and waiting (ship or hand test), then building, then the rest.
 */
export function bar(counts: Tally, width: number): string {
  if (!Number.isInteger(width) || width < 1) throw new Error('bar: width must be a positive integer')
  if (counts.total === 0) return '░'.repeat(width)
  const share = (n: number) => Math.round((n / counts.total) * width)
  const done = Math.min(width, share(counts.counts.done))
  const waiting = Math.min(width - done, share(counts.counts.ready + counts.counts.handtest))
  const building = Math.min(width - done - waiting, share(counts.counts.building))
  const rest = width - done - waiting - building
  const drawn = '█'.repeat(done) + '▓'.repeat(waiting) + '▒'.repeat(building) + '░'.repeat(rest)
  if (drawn.length !== width) throw new Error('bar: drawn width does not match the asked width')
  return drawn
}

/**
 * The whole-number percentage of items done.
 * Input: a tally. Output: 0 to 100; 0 when there are no items.
 */
export function percentDone(counts: Tally): number {
  if (counts.total === 0) return 0
  const percent = Math.round((counts.counts.done / counts.total) * 100)
  if (percent < 0 || percent > 100) throw new Error('percentDone: percent outside 0 to 100')
  return percent
}

/**
 * Every item of every area, each with its area's name.
 * Input: parsed data. Output: the items in area order.
 */
export function allItems(data: ProgressData): Array<Item & { area: string }> {
  return data.areas.flatMap(area => area.items.map(item => ({ ...item, area: area.name })))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= TEXT_LENGTH_MAX
}

function isStatus(value: unknown): value is Status {
  return typeof value === 'string' && (STATUSES as readonly string[]).includes(value)
}
