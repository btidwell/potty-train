import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from './api';
import { Entry, HouseholdUser } from './models';

@Component({
  selector: 'app-people',
  imports: [RouterLink],
  templateUrl: './people.html',
})
export class PeoplePage {
  protected readonly api = inject(Api);
  protected readonly phase = signal<'loading' | 'ready' | 'denied' | 'error'>('loading');
  protected readonly users = signal<HouseholdUser[]>([]);

  protected readonly activity = computed(() => [...(this.api.state()?.entries ?? [])].reverse());

  constructor() {
    const destroyRef = inject(DestroyRef);
    destroyRef.onDestroy(this.api.registerViewReload(() => this.load(true)));
    void this.load();
  }

  protected rowsFor(email: string): number {
    const name = email.toLowerCase();
    return this.activity().filter((entry) => (entry.recorded_by || '').toLowerCase() === name).length;
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

  protected kindLabel(kind: Entry['kind']): string {
    switch (kind) {
      case 'scheduled':
        return 'Scheduled sit';
      case 'asked':
        return 'Child asked';
      case 'accident':
        return 'Accident';
      default:
        return 'Written in';
    }
  }

  protected outcome(entry: Entry): string {
    const parts: string[] = [];
    if (entry.toilet_urine) {
      parts.push('urine');
    }
    if (entry.toilet_bm) {
      parts.push('BM');
    }
    if (entry.accident_wet) {
      parts.push('wet');
    }
    if (entry.accident_soiled) {
      parts.push('soiled');
    }
    return parts.length ? parts.join(', ') : 'dry';
  }

  private async load(silent = false): Promise<void> {
    if (!silent) {
      this.phase.set('loading');
    }
    const allowed = await this.api.canInvite();
    if (!allowed) {
      this.phase.set('denied');
      return;
    }
    const users = await this.api.listUsers();
    if (!users) {
      this.phase.set('error');
      return;
    }
    if (!silent && !this.api.state()) {
      await this.api.refresh();
    }
    this.users.set(users);
    this.phase.set('ready');
  }
}
