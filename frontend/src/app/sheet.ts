import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from './api';
import { Entry, Outcome } from './models';

@Component({
  selector: 'app-sheet',
  imports: [FormsModule],
  templateUrl: './sheet.html',
})
export class SheetPage {
  protected readonly api = inject(Api);
  protected readonly editing = signal<Outcome | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly confirmId = signal<string | null>(null);

  protected readonly entries = computed(() => this.api.state()?.entries ?? []);
  protected readonly recent = computed(() => [...this.entries()].reverse());
  protected readonly days = computed(() => {
    const groups = new Map<string, { date: string; sits: number; voids: number; accidents: number; lastInterval: number; lastNote: string }>();
    for (const entry of this.entries()) {
      const current = groups.get(entry.date) ?? {
        date: entry.date,
        sits: 0,
        voids: 0,
        accidents: 0,
        lastInterval: entry.interval_minutes,
        lastNote: '',
      };
      current.sits += 1;
      if (entry.toilet_bm || entry.toilet_urine) {
        current.voids += 1;
      }
      if (entry.accident_wet || entry.accident_soiled) {
        current.accidents += 1;
      }
      current.lastInterval = entry.interval_minutes;
      current.lastNote = entry.decision_note;
      groups.set(entry.date, current);
    }
    return [...groups.values()];
  });

  constructor() {
    if (!this.api.state()) {
      void this.api.refresh();
    }
  }

  protected startNew(): void {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    this.editingId.set(null);
    this.editing.set({
      date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
      time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
      kind: 'manual',
      toilet_bm: false,
      toilet_urine: false,
      accident_soiled: false,
      accident_wet: false,
      comment: '',
    });
  }

  protected edit(entry: Entry): void {
    this.confirmId.set(null);
    this.editingId.set(entry.id);
    this.editing.set({
      date: entry.date,
      time: entry.time,
      kind: entry.kind,
      toilet_bm: entry.toilet_bm,
      toilet_urine: entry.toilet_urine,
      accident_soiled: entry.accident_soiled,
      accident_wet: entry.accident_wet,
      comment: entry.comment,
    });
    // The editor is rendered above the table. On a long sheet that puts it
    // outside the viewport, so the click looks like it did nothing.
    setTimeout(() => document.getElementById('row-editor')?.scrollIntoView({ block: 'start' }));
  }

  protected cancel(): void {
    this.editing.set(null);
    this.editingId.set(null);
  }

  protected async save(): Promise<void> {
    const draft = this.editing();
    if (!draft) {
      return;
    }
    const id = this.editingId();
    const ok = id
      ? await this.api.mutate('PUT', `/api/entries/${id}`, { ...draft })
      : await this.api.mutate('POST', '/api/entries', { ...draft });
    if (ok) {
      this.cancel();
    }
  }

  protected async remove(id: string): Promise<void> {
    const ok = await this.api.mutate('DELETE', `/api/entries/${id}`);
    if (ok) {
      this.confirmId.set(null);
    }
  }

  protected glance(entry: Entry): string {
    const marks: string[] = [];
    if (entry.toilet_urine) {
      marks.push('urine');
    }
    if (entry.toilet_bm) {
      marks.push('BM');
    }
    if (entry.accident_wet) {
      marks.push('wet');
    }
    if (entry.accident_soiled) {
      marks.push('soiled');
    }
    const result = marks.length ? marks.join(', ') : 'dry';
    return `${entry.interval_minutes} min · ${result}`;
  }

  protected kindLabel(kind: Entry['kind']): string {
    switch (kind) {
      case 'scheduled':
        return 'scheduled';
      case 'asked':
        return 'asked';
      case 'accident':
        return 'accident';
      default:
        return 'written in';
    }
  }
}
