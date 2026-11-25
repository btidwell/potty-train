import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AppState } from './models';

function readSavedToken(): string {
  const token = localStorage.getItem('potty_token') ?? sessionStorage.getItem('potty_token') ?? '';
  if (token) {
    localStorage.setItem('potty_token', token);
  }
  sessionStorage.removeItem('potty_token');
  return token;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly router = inject(Router);
  readonly token = signal(readSavedToken());
  readonly state = signal<AppState | null>(null);
  readonly error = signal('');
  readonly busy = signal(false);
  private writeVersion = 0;

  clientNow(): string {
    const date = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    const offsetMinutes = -date.getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const absolute = Math.abs(offsetMinutes);
    const offset = `${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${offset}`;
  }

  async login(password: string): Promise<string> {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, now: this.clientNow() }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      return body.error || 'Could not sign in.';
    }
    this.token.set(body.token);
    localStorage.setItem('potty_token', body.token);
    sessionStorage.removeItem('potty_token');
    this.error.set('');
    await this.refresh();
    return '';
  }

  logout(): void {
    this.token.set('');
    this.state.set(null);
    localStorage.removeItem('potty_token');
    sessionStorage.removeItem('potty_token');
    void this.router.navigateByUrl('/login');
  }

  async refresh(): Promise<void> {
    const version = this.writeVersion;
    const next = await this.send<AppState>('GET', '/api/state');
    if (next && version === this.writeVersion) {
      this.state.set(next);
    }
  }

  async mutate(method: string, path: string, payload: Record<string, unknown> = {}): Promise<boolean> {
    const version = ++this.writeVersion;
    const next = await this.send<AppState>(method, path, { ...payload, now: this.clientNow() });
    if (!next) {
      return false;
    }
    if (version === this.writeVersion) {
      this.state.set(next);
    }
    return true;
  }

  async postQuiet(path: string, payload: Record<string, unknown>): Promise<boolean> {
    const version = this.writeVersion;
    const next = await this.send<AppState>('POST', path, payload, { quiet: true });
    if (!next) {
      return false;
    }
    if (version === this.writeVersion) {
      this.state.set(next);
    }
    return true;
  }

  async downloadCsv(): Promise<void> {
    const response = await fetch('/api/export.csv', { headers: this.headers() });
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
    link.download = 'potty-log.csv';
    link.click();
    URL.revokeObjectURL(url);
  }

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {};
    const token = this.token();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
  }

  private async send<T>(
    method: string,
    path: string,
    payload?: Record<string, unknown>,
    options?: { quiet?: boolean },
  ): Promise<T | null> {
    const quiet = options?.quiet === true;
    if (!quiet) {
      this.busy.set(true);
    }
    try {
      const response = await fetch(path, {
        method,
        headers: { ...this.headers(), ...(payload ? { 'Content-Type': 'application/json' } : {}) },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      if (response.status === 401) {
        if (!quiet) {
          this.error.set('');
        }
        this.logout();
        return null;
      }
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (!quiet) {
          this.error.set(body.error || 'Something went wrong.');
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
