import type { ActiveModes, ModeId } from '../types'

export const MODE_IDS: readonly ModeId[] = ['adhd', 'caveman', 'superpowers', 'context-mode']

const BANNERS: Record<ModeId, string> = {
  adhd: 'ADHD MODE ACTIVE',
  caveman: 'CAVEMAN MODE ACTIVE',
  superpowers: 'You have superpowers',
  'context-mode': '<context_window_protection>',
}

const OFF_PHRASES: ReadonlyArray<{ phrase: string; modes: readonly ModeId[] }> = [
  { phrase: 'stop adhd mode', modes: ['adhd'] },
  { phrase: 'stop caveman', modes: ['caveman'] },
  { phrase: 'normal mode', modes: ['adhd', 'caveman'] },
]

const CAVEMAN_LEVEL = /CAVEMAN MODE ACTIVE\s*(?:[-–—]+\s*level:\s*|\()([a-z-]{1,24})/
const SCAN_LENGTH_MAX = 200_000
const PROMPT_LENGTH_MAX = 10_000
const BLOCKS_MAX = 64

invariant(new Set(MODE_IDS).size === MODE_IDS.length, 'MODE_IDS holds a duplicate')
invariant(OFF_PHRASES.every(rule => rule.modes.length > 0), 'an off phrase names no mode')

/**
 * Throws when a belief about the module's own state is false.
 * Input: the belief and what to say. Output: none; never recovers.
 */
function invariant(condition: boolean, message: string): asserts condition {
  if (!condition) throw new Error(`session-modes: ${message}`)
}

/**
 * Joins the text blocks of one transcript row.
 * Input: the row's content blocks, at most BLOCKS_MAX read. Output: their
 * texts joined by newlines, cut to SCAN_LENGTH_MAX characters.
 */
export function textOf(content: ReadonlyArray<{ type: string; [field: string]: unknown }>): string {
  const texts = content
    .slice(0, BLOCKS_MAX)
    .flatMap(block => (block.type === 'text' && typeof block.text === 'string' ? [block.text] : []))
  const joined = texts.join('\n').slice(0, SCAN_LENGTH_MAX)
  invariant(joined.length <= SCAN_LENGTH_MAX, 'joined text passed its bound')
  return joined
}

/**
 * Finds the mode banners in one hook row's text.
 * Input: the row's text. Output: each mode whose banner appears, mapped to the
 * label the hint shows (`caveman full` when the banner names a level).
 */
export function bannersIn(text: string): ActiveModes {
  const scanned = text.slice(0, SCAN_LENGTH_MAX)
  const found: ActiveModes = {}
  for (const id of MODE_IDS) {
    if (scanned.includes(BANNERS[id])) found[id] = label(id, scanned)
  }
  invariant(Object.keys(found).length <= MODE_IDS.length, 'found more modes than exist')
  return found
}

function label(id: ModeId, text: string): string {
  if (id !== 'caveman') return id
  const level = CAVEMAN_LEVEL.exec(text)?.[1]
  return level === undefined ? id : `${id} ${level}`
}

/**
 * Which modes a prompt the person typed switches off.
 * Input: the prompt's text. Output: the modes its off phrases name, in
 * MODE_IDS order; empty when it names none.
 */
export function switchedOff(prompt: string): ModeId[] {
  const said = prompt.slice(0, PROMPT_LENGTH_MAX).toLowerCase()
  const off = new Set<ModeId>()
  for (const rule of OFF_PHRASES) {
    if (said.includes(rule.phrase)) rule.modes.forEach(id => off.add(id))
  }
  const named = MODE_IDS.filter(id => off.has(id))
  invariant(named.length === off.size, 'an off phrase names an unknown mode')
  return named
}

/**
 * Removes modes from the active set.
 * Input: the active set and the modes to drop. Output: a new set without them.
 */
export function without(active: ActiveModes, off: readonly ModeId[]): ActiveModes {
  const kept: ActiveModes = { ...active }
  for (const id of off) delete kept[id]
  invariant(off.every(id => kept[id] === undefined), 'a dropped mode is still active')
  return kept
}

/**
 * The text drawn after the prompt hint line.
 * Input: the active set from state. Output: `on: adhd · caveman full`, modes in
 * MODE_IDS order, or undefined when none is on. Throws on a corrupt state.
 */
export function tail(active: ActiveModes): string | undefined {
  for (const [key, value] of Object.entries(active)) {
    invariant((MODE_IDS as readonly string[]).includes(key), `unknown mode ${key} in state`)
    invariant(typeof value === 'string' && value.length > 0, `empty label for ${key}`)
  }
  const labels = MODE_IDS.flatMap(id => {
    const shown = active[id]
    return shown === undefined ? [] : [shown]
  })
  if (labels.length === 0) return undefined
  return `on: ${labels.join(' · ')}`
}
