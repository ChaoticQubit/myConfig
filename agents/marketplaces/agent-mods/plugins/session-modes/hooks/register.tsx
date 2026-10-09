import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import { bannersIn, switchedOff, tail, textOf, without } from './modes'

const active = atom({ plugin: 'session-modes', key: 'active' } as const, {})

const PERSON_ORIGINS: ReadonlySet<string> = new Set(['composer', 'bridge', 'sdk'])

export const register: Register = on => {
  on('session.append', async ($, e, next) => {
    const stored = await next(e)
    if (e.origin.kind !== 'hook') return stored
    const found = bannersIn(textOf(e.message.content))
    if (Object.keys(found).length > 0) {
      await update($, active, current => ({ ...current, ...found }))
    }
    return stored
  }).catch(($, e, next) => next(e))

  on('prompt.submit', async ($, e, next) => {
    const off = PERSON_ORIGINS.has(e.origin.kind) ? switchedOff(e.text) : []
    if (off.length > 0) await update($, active, current => without(current, off))
    return next(e)
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') await update($, active, () => ({}))
    return next(e)
  })

  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    const line = tail(await read($, active))
    if (line === undefined) return next(e)
    const joined = e.props.tail === undefined ? line : `${e.props.tail}  ${line}`
    return next({ ...e, props: { ...e.props, tail: joined } })
  })
}
