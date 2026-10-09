export type Status = 'building' | 'ready' | 'handtest' | 'owner' | 'todo' | 'done'

export type Item = { id: string; title: string; status: Status; note?: string }

export type Area = { id: string; name: string; items: Item[] }

export type ProgressData = { title: string; updated: string; target: string; areas: Area[] }

export type Tally = { counts: Record<Status, number>; total: number }

declare module 'claude-code' {
  interface PluginState {
    'launch-progress': {
      data: ProgressData | null
      error: string | null
      view: string
      showDone: boolean
    }
  }
}
