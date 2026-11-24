import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from './api';
import { Settings } from './models';

@Component({
  selector: 'app-settings',
  imports: [FormsModule],
  templateUrl: './settings.html',
})
export class SettingsPage {
  protected readonly api = inject(Api);
  protected readonly draft = signal<Settings | null>(null);
  protected readonly saved = signal(false);
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
}
