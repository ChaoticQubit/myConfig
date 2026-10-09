export type ModeId = 'adhd' | 'caveman' | 'superpowers' | 'context-mode'

export type ActiveModes = Partial<Record<ModeId, string>>

declare module 'claude-code' {
  interface PluginState {
    'session-modes': { active: ActiveModes }
  }
}
