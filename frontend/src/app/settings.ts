import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from './api';
import { BrowserSession, Settings } from './models';

@Component({
  selector: 'app-settings',
  imports: [FormsModule, RouterLink],
  templateUrl: './settings.html',
})
export class SettingsPage {
  protected readonly api = inject(Api);
  protected readonly draft = signal<Settings | null>(null);
  protected readonly saved = signal(false);
  protected readonly canInvite = signal(false);
  protected readonly inviteMessage = signal('');
  protected readonly inviteTone = signal<'error' | 'ok'>('ok');
  protected inviteEmail = '';
  protected readonly sessions = signal<BrowserSession[] | null>(null);
  protected readonly confirmingSession = signal<string | null>(null);
  protected readonly zones = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Phoenix',
    'America/Anchorage',
    'Pacific/Honolulu',
    'UTC',
  ];

  constructor() {
    effect(() => {
      const settings = this.api.state()?.settings;
      if (settings && !this.draft()) {
        const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const copy = structuredClone(settings);
        if (!copy.timezone) {
          copy.timezone = browserZone;
        }
        this.draft.set(copy);
      }
    });
    if (!this.api.state()) {
      void this.api.refresh();
    }
    void this.api.canInvite().then((allowed) => this.canInvite.set(allowed));
    void this.loadSessions();
  }

  protected address(ip: string): string {
    return ip.replaceAll(':', ':\u200b');
  }

  protected when(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(date);
  }

  protected async signOutDevice(id: string): Promise<void> {
    const ok = await this.api.revokeSession(id);
    if (ok && this.api.signedIn()) {
      this.confirmingSession.set(null);
      await this.loadSessions();
    }
  }

  private async loadSessions(): Promise<void> {
    this.sessions.set((await this.api.listSessions()) ?? []);
  }

  protected zoneOptions(): string[] {
    const current = this.draft()?.timezone;
    if (current && !this.zones.includes(current)) {
      return [current, ...this.zones];
    }
    return this.zones;
  }

  protected async save(): Promise<void> {
    const draft = this.draft();
    if (!draft) {
      return;
    }
    this.saved.set(false);
    const ok = await this.api.mutate('PUT', '/api/settings', { ...draft });
    if (ok) {
      this.draft.set(structuredClone(this.api.state()?.settings ?? draft));
      this.saved.set(true);
    }
  }

  protected logout(): void {
    this.api.logout();
  }

  protected async invite(event: Event): Promise<void> {
    event.preventDefault();
    const result = await this.api.invite(this.inviteEmail);
    this.inviteTone.set(result.ok ? 'ok' : 'error');
    this.inviteMessage.set(result.message);
    if (result.ok) {
      this.inviteEmail = '';
    }
  }
}
