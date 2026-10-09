import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import { bannersIn, switchedOff, tail } from '../hooks/modes'

const ADHD = 'SessionStart:startup hook success: ADHD MODE ACTIVE (always-on). The ruleset below applies.'
const CAVEMAN_START = 'CAVEMAN MODE ACTIVE — level: full\n\nRespond terse like smart caveman.'
const CAVEMAN_PROMPT = 'CAVEMAN MODE ACTIVE (lite). Drop articles/filler/pleasantries/hedging.'
const SUPERPOWERS = '<EXTREMELY_IMPORTANT>\nYou have superpowers.\n\n**Below is the full content'
const CONTEXT_MODE = '<context_window_protection>\n  <priority_instructions>\n'
const EVERY_BANNER = [ADHD, CAVEMAN_START, SUPERPOWERS, CONTEXT_MODE].join('\n\n')

const HINT = { component: 'PromptHint', props: { isDraft: false, isWorking: false, hint: '? for shortcuts' } } as const

let rows = 0

function hookRow(text: string, origin: { kind: 'hook'; event: string } | { kind: 'plugin'; event: string }) {
  rows += 1
  return {
    message: { type: 'attachment' as const, name: 'hook_additional_context', content: [{ type: 'text', text }] },
    door: 'hook-context' as const,
    origin,
    uuid: `row-${rows}`,
  }
}

function standIn(on: On): void {
  on('ui.render', { component: 'PromptHint' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>{`${e.props.hint}|${e.props.tail ?? 'none'}`}</Text>
  })
  on('prompt.submit', (_$, e) => ({ text: e.text }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
}

async function hintText($: Engine, surface: 'terminal' | 'desktop'): Promise<string> {
  const ui = await $.ui.mount({ plugin: 'session-modes', surface, ...HINT })
  const drawn = await ui.drawn()
  await ui.unmount()
  if (drawn.type !== 'Text') throw new Error(`hint drew a ${drawn.type}, not a Text`)
  return (drawn.children ?? []).join('')
}

test('each banner turns on its mode, with the caveman level in either spelling', () => {
  expect(bannersIn(EVERY_BANNER)).toEqual({
    adhd: 'adhd', caveman: 'caveman full', superpowers: 'superpowers', 'context-mode': 'context-mode',
  })
  expect(bannersIn(CAVEMAN_PROMPT)).toEqual({ caveman: 'caveman lite' })
  expect(bannersIn('Entire CLI is enabled. gh-axi wrapper.')).toEqual({})
})

test('typed off phrases name the modes they stop', () => {
  expect(switchedOff('ok, Stop Caveman please')).toEqual(['caveman'])
  expect(switchedOff('stop adhd mode')).toEqual(['adhd'])
  expect(switchedOff('normal mode')).toEqual(['adhd', 'caveman'])
  expect(switchedOff('fix the build')).toEqual([])
})

test('the tail lists modes in a fixed order and refuses a corrupt state', () => {
  expect(tail({})).toBeUndefined()
  expect(tail({ 'context-mode': 'context-mode', adhd: 'adhd' })).toBe('on: adhd · context-mode')
  expect(() => tail({ bogus: 'x' } as never)).toThrow('session-modes: unknown mode bogus in state')
  expect(() => tail({ adhd: '' })).toThrow('session-modes: empty label for adhd')
})

test('settings-hook banners fill the hint tail; a plugin row with the same text does not', async ($, on) => {
  standIn(on)
  for (const surface of ['terminal', 'desktop'] as const) {
    expect(await hintText($, surface)).toBe('? for shortcuts|none')
  }
  await $.session.append(hookRow(CONTEXT_MODE + ADHD, { kind: 'plugin', event: 'prompt.submit' }))
  expect(await hintText($, 'terminal')).toBe('? for shortcuts|none')
  await $.session.append(hookRow(EVERY_BANNER, { kind: 'hook', event: 'SessionStart' }))
  for (const surface of ['terminal', 'desktop'] as const) {
    expect(await hintText($, surface)).toBe(
      '? for shortcuts|on: adhd · caveman full · superpowers · context-mode',
    )
  }
  await $.session.append(hookRow(CAVEMAN_PROMPT, { kind: 'hook', event: 'UserPromptSubmit' }))
  expect(await hintText($, 'desktop')).toBe(
    '? for shortcuts|on: adhd · caveman lite · superpowers · context-mode',
  )
})

test('a typed off phrase drops modes, a notification does not, and /clear empties the list', async ($, on) => {
  standIn(on)
  await $.session.append(hookRow(EVERY_BANNER, { kind: 'hook', event: 'SessionStart' }))
  await $.prompt.submit({ text: 'normal mode', wait: false, origin: { kind: 'task-notification' } })
  expect(await hintText($, 'terminal')).toBe(
    '? for shortcuts|on: adhd · caveman full · superpowers · context-mode',
  )
  await $.prompt.submit({ text: 'stop caveman', wait: false, origin: { kind: 'composer' } })
  expect(await hintText($, 'terminal')).toBe('? for shortcuts|on: adhd · superpowers · context-mode')
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  expect(await hintText($, 'terminal')).toBe('? for shortcuts|none')
})
