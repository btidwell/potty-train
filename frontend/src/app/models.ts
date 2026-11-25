export interface Settings {
  child_name: string;
  starting_interval_minutes: number;
  step_minutes: number;
  min_interval_minutes: number;
  max_interval_minutes: number;
  sit_minutes: number;
  drink_prompt_minutes: number;
  reinforcer_note: string;
  timezone: string;
}

export interface ActiveSit {
  started_at: string;
  kind: 'scheduled' | 'asked' | 'accident';
  preserved_next_sit_at: string | null;
  preserved_timer_interval_minutes: number | null;
}

export interface Schedule {
  running: boolean;
  next_sit_at: string | null;
  timer_interval_minutes: number | null;
  active_sit: ActiveSit | null;
}

export interface Entry {
  id: string;
  seq: number;
  date: string;
  time: string;
  kind: 'scheduled' | 'asked' | 'accident' | 'manual';
  toilet_bm: boolean;
  toilet_urine: boolean;
  accident_soiled: boolean;
  accident_wet: boolean;
  comment: string;
  created_at: string;
  recorded_by?: string;
  interval_minutes: number;
  decision: 'increase' | 'decrease' | 'same';
  decision_note: string;
}

export interface Derived {
  current_interval_minutes: number;
  dry_streak: number;
  dry_needed: number;
  dry_streak_has_void: boolean;
  accident_streak: number;
  accident_needed: number;
  rule_status: string;
  today: string;
  today_sits: number;
  today_voids: number;
  today_accidents: number;
  summary_label: string;
  summary_sits: number;
  summary_voids: number;
  summary_accidents: number;
  server_now: string;
}

export interface AppState {
  settings: Settings;
  schedule: Schedule;
  entries: Entry[];
  derived: Derived;
  push: {
    public_key: string;
    off_sent_for: string | null;
    sit_sent_for: string | null;
    off_scheduled_for: string | null;
    sit_scheduled_for: string | null;
  };
}

export interface BrowserSession {
  id: string;
  label: string;
  created_at: string;
  last_seen: string;
  ip: string;
  remembered: boolean;
}

export interface HouseholdUser {
  email: string;
  status: 'invited' | 'active' | 'reset' | 'disabled' | 'other';
  status_label: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  authenticator: boolean;
  owner: boolean;
  sessions: BrowserSession[];
}

export interface Outcome {
  toilet_bm: boolean;
  toilet_urine: boolean;
  accident_soiled: boolean;
  accident_wet: boolean;
  comment: string;
  date: string;
  time: string;
  kind: Entry['kind'];
}
