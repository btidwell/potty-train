import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import {
  accessToken,
  currentDeviceKey,
  deviceIsRemembered,
  deviceLabel,
  endSession,
  recordAuthenticator,
  rememberThisDevice,
  signedInAsOwner,
} from './auth';
import { AppState, BrowserSession, HouseholdUser } from './models';

const SESSION_COOKIE = 'potty-session';
const SESSION_MAX_AGE = 7 * 24 * 60 * 60;

export type ChatStreamEvent = {
  type: 'thought' | 'text' | 'tool' | 'tool_result' | 'error' | 'done';
  text?: string;
  name?: string;
  input?: unknown;
  result?: string;
  message?: string;
  toolUseId?: string;
};

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly router = inject(Router);
  readonly signedIn = signal(false);
  readonly state = signal<AppState | null>(null);
  readonly error = signal('');
  readonly busy = signal(false);
  // A refresh that started before a save finished must not paint the old log
  // back over the timer that save just stored.
  private commit = 0;
  private writes = 0;
  private viewReloads: Array<() => Promise<void>> = [];
  private ownerCheck: Promise<boolean> | null = null;

  clientNow(): string {
    const date = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    const offsetMinutes = -date.getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const absolute = Math.abs(offsetMinutes);
    const offset = `${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${offset}`;
  }

  canInvite(): Promise<boolean> {
    if (!this.ownerCheck) {
      this.ownerCheck = signedInAsOwner().then((allowed) => {
        if (!this.signedIn()) {
          this.ownerCheck = null;
        }
        return allowed;
      });
    }
    return this.ownerCheck;
  }

  async listUsers(): Promise<HouseholdUser[] | null> {
    const body = await this.send<{ users: HouseholdUser[] }>('GET', '/api/users');
    return body ? body.users : null;
  }

  async invite(email: string): Promise<{ ok: boolean; message: string }> {
    const response = await fetch('/api/invites', {
      method: 'POST',
      headers: { ...(await this.headers()), 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) {
      this.logout();
      return { ok: false, message: 'Sign in again.' };
    }
    if (!response.ok) {
      return { ok: false, message: body.error || 'Could not send the invitation.' };
    }
    return { ok: true, message: body.message || 'Invitation sent.' };
  }

  async restore(): Promise<boolean> {
    const token = await this.sessionToken();
    if (!token) {
      return false;
    }
    if (!readSessionId()) {
      const opened = await this.openSession(false);
      if (!opened.ok) {
        return false;
      }
    }
    this.error.set('');
    void recordAuthenticator();
    return true;
  }

  async openSession(remember: boolean): Promise<{ ok: boolean; remembered: boolean }> {
    let deviceKey = '';
    let remembered = false;
    try {
      if (remember) {
        deviceKey = await rememberThisDevice();
        remembered = Boolean(deviceKey);
      } else {
        deviceKey = await currentDeviceKey();
        remembered = await deviceIsRemembered(deviceKey);
      }
    } catch {
      deviceKey = '';
      remembered = false;
    }
    const payload = JSON.stringify({ label: deviceLabel(), device_key: deviceKey, remembered });
    const response = await fetch('/api/sessions', {
      method: 'POST',
      headers: {
        ...(await this.headers()),
        'Content-Type': 'application/json',
        'x-amz-content-sha256': await payloadHash(payload),
      },
      body: payload,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.session?.id) {
      return { ok: false, remembered: false };
    }
    writeSessionId(String(body.session.id));
    return { ok: true, remembered: Boolean(body.session.remembered) };
  }

  currentSessionId(): string {
    return readSessionId();
  }

  async listSessions(): Promise<BrowserSession[] | null> {
    const body = await this.send<{ sessions: BrowserSession[] }>('GET', '/api/sessions');
    return body ? body.sessions : null;
  }

  async revokeSession(id: string): Promise<boolean> {
    const current = readSessionId();
    const response = await fetch(`/api/sessions/${id}`, {
      method: 'DELETE',
      headers: await this.headers(),
    });
    if (response.status === 401) {
      this.logout();
      return false;
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      this.error.set(body.error || 'Could not sign that device out.');
      return false;
    }
    if (id === current) {
      await this.finishLogout();
    }
    return true;
  }

  logout(): void {
    this.ownerCheck = null;
    this.signedIn.set(false);
    this.state.set(null);
    const id = readSessionId();
    void this.revokeThenLeave(id);
  }

  private async revokeThenLeave(id: string): Promise<void> {
    if (id) {
      const token = await accessToken().catch(() => '');
      await fetch(`/api/sessions/${id}`, {
        method: 'DELETE',
        headers: {
          ...(token ? { 'X-Potty-Authorization': `Bearer ${token}` } : {}),
          'X-Potty-Session': id,
        },
      }).catch(() => undefined);
    }
    await this.finishLogout();
  }

  private async finishLogout(): Promise<void> {
    clearSessionId();
    this.ownerCheck = null;
    this.signedIn.set(false);
    this.state.set(null);
    await endSession().catch(() => undefined);
    await this.router.navigateByUrl('/login');
  }

  registerViewReload(reload: () => Promise<void>): () => void {
    this.viewReloads.push(reload);
    return () => {
      this.viewReloads = this.viewReloads.filter((item) => item !== reload);
    };
  }

  async refresh(options?: { views?: boolean; keepError?: boolean; quiet?: boolean }): Promise<void> {
    const seen = this.commit;
    const kept = options?.keepError ? this.error() : '';
    const next = await this.send<AppState>('GET', '/api/state', undefined, { quiet: options?.quiet === true });
    if (next && seen === this.commit && this.writes === 0) {
      this.state.set(next);
    }
    if (options?.keepError && kept && !this.error()) {
      this.error.set(kept);
    }
    if (options?.views && this.writes === 0) {
      await Promise.all(this.viewReloads.map((reload) => reload().catch(() => undefined)));
    }
  }

  async mutate(method: string, path: string, payload: Record<string, unknown> = {}): Promise<boolean> {
    this.writes++;
    let reload = false;
    try {
      const seen = this.commit;
      const next = await this.send<AppState>(method, path, { ...payload, now: this.clientNow() });
      if (!next) {
        reload = this.signedIn() && this.commit === seen && isLiveScheduleError(this.error());
        return false;
      }
      if (this.writes === 1 && this.commit === seen) {
        this.commit++;
        this.state.set(next);
      } else {
        reload = true;
      }
      return true;
    } finally {
      this.writes--;
      if (reload && this.writes === 0) {
        await this.refresh({ keepError: true });
      }
    }
  }

  async postQuiet(path: string, payload: Record<string, unknown>): Promise<boolean> {
    const seen = this.commit;
    const next = await this.send<AppState>('POST', path, payload, { quiet: true });
    if (!next) {
      return false;
    }
    if (seen === this.commit && this.writes === 0) {
      this.commit++;
      this.state.set(next);
    }
    return true;
  }

  downloadCsv(): Promise<void> {
    return this.downloadFile('/api/export.csv', 'potty-log.csv');
  }

  downloadPdf(): Promise<void> {
    return this.downloadFile('/api/export.pdf', 'potty-log.pdf');
  }

  async streamChat(
    message: string,
    history: Array<{ role: string; content: string }>,
    onEvent: (event: ChatStreamEvent) => void,
  ): Promise<void> {
    const payload = JSON.stringify({ message, history });
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        ...(await this.headers()),
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'x-amz-content-sha256': await payloadHash(payload),
      },
      body: payload,
    });
    if (response.status === 401) {
      this.logout();
      throw new Error('Sign in again.');
    }
    if (!response.ok || !response.body) {
      const raw = await response.text().catch(() => '');
      let body: { error?: string; message?: string } = {};
      try {
        body = raw ? (JSON.parse(raw) as { error?: string; message?: string }) : {};
      } catch {
        if (raw) {
          body = { error: raw.slice(0, 200) };
        }
      }
      throw new Error(
        body.error || body.message || `Could not reach the assistant (${response.status || 0}).`,
      );
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        const line = part
          .split('\n')
          .map((item) => item.trim())
          .find((item) => item.startsWith('data:'));
        if (!line) {
          continue;
        }
        const raw = line.slice(5).trim();
        if (!raw) {
          continue;
        }
        try {
          onEvent(JSON.parse(raw) as ChatStreamEvent);
        } catch {
          // Skip malformed chunks.
        }
      }
    }
  }

  private async downloadFile(path: string, filename: string): Promise<void> {
    const response = await fetch(path, { headers: await this.headers() });
    if (response.status === 401) {
      this.logout();
      return;
    }
    if (!response.ok) {
      this.error.set('Could not download the sheet.');
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  private async sessionToken(forceRefresh = false): Promise<string> {
    try {
      const token = await accessToken(forceRefresh);
      this.signedIn.set(Boolean(token));
      return token;
    } catch {
      this.signedIn.set(false);
      return '';
    }
  }

  private async headers(forceRefresh = false): Promise<Record<string, string>> {
    const headers: Record<string, string> = {};
    const token = await this.sessionToken(forceRefresh);
    if (token) {
      headers['X-Potty-Authorization'] = `Bearer ${token}`;
    }
    const sessionId = readSessionId();
    if (sessionId) {
      headers['X-Potty-Session'] = sessionId;
    }
    return headers;
  }

  private async send<T>(
    method: string,
    path: string,
    payload?: Record<string, unknown>,
    options?: { quiet?: boolean; retried?: boolean },
  ): Promise<T | null> {
    const quiet = options?.quiet === true;
    if (!quiet) {
      this.busy.set(true);
    }
    try {
      const bodyText = payload ? JSON.stringify(payload) : undefined;
      const response = await fetch(path, {
        method,
        headers: {
          ...(await this.headers()),
          ...(bodyText
            ? { 'Content-Type': 'application/json', 'x-amz-content-sha256': await payloadHash(bodyText) }
            : {}),
        },
        body: bodyText,
      });
      if (response.status === 401) {
        if (!options?.retried) {
          const refreshed = await this.sessionToken(true);
          if (refreshed) {
            return this.send(method, path, payload, { ...options, retried: true });
          }
        }
        if (!quiet) {
          this.error.set('');
        }
        this.logout();
        return null;
      }
      const body = (await response.json().catch(() => ({}))) as { error?: string; state?: unknown };
      if (!response.ok) {
        const message = body.error || 'Something went wrong.';
        if (!quiet && isAppState(body.state) && isLiveScheduleError(message)) {
          this.commit++;
          this.state.set(body.state);
        }
        if (!quiet) {
          this.error.set(message);
        }
        return null;
      }
      if (!quiet) {
        this.error.set('');
      }
      return body as T;
    } catch {
      if (!quiet) {
        this.error.set('Cannot reach the log. Check that the app is running.');
      }
      return null;
    } finally {
      if (!quiet) {
        this.busy.set(false);
      }
    }
  }
}

function isLiveScheduleError(message: string): boolean {
  const text = message.toLowerCase();
  return (
    text.includes('already in progress') ||
    text.includes('already running') ||
    text.includes('updated from another screen')
  );
}

function isAppState(value: unknown): value is AppState {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const state = value as AppState;
  return Boolean(state.settings && state.schedule && state.derived);
}

async function payloadHash(body: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function readSessionId(): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${SESSION_COOKIE}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

function writeSessionId(id: string): void {
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${SESSION_COOKIE}=${encodeURIComponent(id)}; Path=/; Max-Age=${SESSION_MAX_AGE}; SameSite=Strict${secure}`;
}

function clearSessionId(): void {
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Strict${secure}`;
}
