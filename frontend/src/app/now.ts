import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from './api';

@Component({
  selector: 'app-now',
  imports: [FormsModule],
  templateUrl: './now.html',
})
export class NowPage {
  protected readonly api = inject(Api);
  protected readonly nowMs = signal(Date.now());
  protected readonly soundOn = signal(localStorage.getItem('potty_chime') !== 'off');
  protected readonly notifyPermission = signal<NotificationPermission | 'unsupported'>(this.currentPermission());
  protected readonly pushReady = signal(false);
  protected readonly pushFailure = signal('');
  protected urine = false;
  protected bm = false;
  protected wet = false;
  protected soiled = false;
  protected comment = '';
  private audio?: AudioContext;
  private announcedOff = false;
  private announcedSit = false;
  private notifiedOff = false;
  private notifiedSit = false;
  private workerReady?: Promise<ServiceWorkerRegistration>;
  private pushInflight?: Promise<void>;

  protected readonly state = computed(() => this.api.state());
  protected readonly sitting = computed(() => this.state()?.schedule.active_sit ?? null);
  protected readonly offLeft = computed(() => {
    const next = this.state()?.schedule.next_sit_at;
    if (!next) {
      return 0;
    }
    return new Date(next).getTime() - this.nowMs();
  });
  protected readonly sitLeft = computed(() => {
    const sit = this.sitting();
    const minutes = this.state()?.settings.sit_minutes ?? 5;
    if (!sit) {
      return 0;
    }
    return new Date(sit.started_at).getTime() + minutes * 60_000 - this.nowMs();
  });
  protected readonly drinkDue = computed(() => {
    const state = this.state();
    if (!state?.schedule.running || state.schedule.active_sit) {
      return false;
    }
    const every = state.settings.drink_prompt_minutes;
    if (!every) {
      return false;
    }
    const last = Number(localStorage.getItem('potty_drink_ack') || 0);
    return this.nowMs() - last >= every * 60_000;
  });

  constructor() {
    const destroyRef = inject(DestroyRef);
    const timer = window.setInterval(() => {
      this.nowMs.set(Date.now());
      this.maybeChime();
      this.maybeNotify();
    }, 250);
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        void this.api.refresh();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('pageshow', onVisible);
    destroyRef.onDestroy(() => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('pageshow', onVisible);
    });
    void this.start();
  }

  protected clock(ms: number): string {
    const total = Math.max(0, Math.ceil(ms / 1000));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  protected toggleSound(): void {
    const next = !this.soundOn();
    this.soundOn.set(next);
    localStorage.setItem('potty_chime', next ? 'on' : 'off');
    if (next) {
      this.prepareAudio();
    }
  }

  protected ackDrink(): void {
    localStorage.setItem('potty_drink_ack', String(Date.now()));
    this.nowMs.set(Date.now());
  }

  protected notifyLabel(): string {
    if (this.pushFailure()) {
      return this.pushFailure();
    }
    if (this.pushReady()) {
      return 'Notifications are on';
    }
    const permission = this.notifyPermission();
    if (permission === 'granted' && !this.api.state()?.push?.public_key) {
      return 'Notifications are on';
    }
    switch (permission) {
      case 'denied':
        return 'Notifications blocked';
      case 'unsupported':
        return 'Notifications unavailable';
      default:
        return 'Allow notifications';
    }
  }

  protected async enableNotifications(): Promise<void> {
    if (this.pushReady() || this.notifyPermission() === 'denied' || this.notifyPermission() === 'unsupported') {
      return;
    }
    if (typeof Notification === 'undefined' || !('serviceWorker' in navigator)) {
      this.notifyPermission.set('unsupported');
      return;
    }
    if (Notification.permission !== 'granted') {
      const permission = await Notification.requestPermission();
      this.notifyPermission.set(permission);
      if (permission !== 'granted') {
        return;
      }
    }
    await this.subscribeToPush();
  }

  protected async startTimer(): Promise<void> {
    this.prepareAudio();
    await this.api.mutate('POST', '/api/schedule/start-timer');
  }

  protected async stopTimer(): Promise<void> {
    await this.api.mutate('POST', '/api/schedule/stop-timer');
  }

  protected async beginSit(kind: 'scheduled' | 'asked' | 'accident'): Promise<void> {
    this.prepareAudio();
    this.announcedSit = false;
    this.notifiedSit = false;
    const ok = await this.api.mutate('POST', '/api/schedule/start-sit', { kind });
    if (ok) {
      this.clearOutcome();
    }
  }

  protected async cancelSit(): Promise<void> {
    await this.api.mutate('POST', '/api/schedule/cancel-sit');
    this.clearOutcome();
  }

  protected async saveSit(): Promise<void> {
    const sit = this.sitting();
    if (!sit) {
      return;
    }
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    const ok = await this.api.mutate('POST', '/api/entries', {
      kind: sit.kind,
      date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
      time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
      toilet_urine: this.urine,
      toilet_bm: this.bm,
      accident_wet: this.wet,
      accident_soiled: this.soiled,
      comment: this.comment,
    });
    if (ok) {
      this.clearOutcome();
    }
  }

  protected reward(): string {
    return this.state()?.settings.reinforcer_note || 'the special item he only gets for using the potty';
  }

  private clearOutcome(): void {
    this.urine = false;
    this.bm = false;
    this.wet = false;
    this.soiled = false;
    this.comment = '';
  }

  private currentPermission(): NotificationPermission | 'unsupported' {
    if (typeof Notification === 'undefined' || !('serviceWorker' in navigator)) {
      return 'unsupported';
    }
    return Notification.permission;
  }

  private async start(): Promise<void> {
    await this.api.refresh();
    if (this.notifyPermission() === 'granted') {
      await this.subscribeToPush();
    }
  }

  private subscribeToPush(): Promise<void> {
    this.pushInflight ??= this.subscribeToPushOnce().finally(() => {
      this.pushInflight = undefined;
    });
    return this.pushInflight;
  }

  private async subscribeToPushOnce(): Promise<void> {
    if (!this.api.state()) {
      await this.api.refresh();
    }
    const publicKey = this.api.state()?.push?.public_key ?? '';
    if (!publicKey) {
      return;
    }
    this.pushFailure.set('');
    try {
      const registration = await this.ensureWorker();
      await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeBase64Url(publicKey),
      });
      const saved = await this.api.postQuiet(
        '/api/push/subscribe',
        subscription.toJSON() as Record<string, unknown>,
      );
      if (!saved) {
        this.pushReady.set(false);
        this.pushFailure.set('Notifications failed');
        return;
      }
      this.pushReady.set(true);
    } catch {
      this.pushReady.set(false);
      this.workerReady = undefined;
      this.pushFailure.set(this.installedApp() ? 'Notifications failed' : 'Install to Home Screen first');
    }
  }

  private installedApp(): boolean {
    const nav = navigator as Navigator & { standalone?: boolean };
    return window.matchMedia('(display-mode: standalone)').matches || nav.standalone === true;
  }

  private ensureWorker(): Promise<ServiceWorkerRegistration> {
    this.workerReady ??= navigator.serviceWorker.register('/sw.js', {
      scope: '/',
      updateViaCache: 'none',
    });
    return this.workerReady;
  }

  private maybeNotify(): void {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
      return;
    }
    const state = this.state();
    if (!state) {
      return;
    }
    if (state.schedule.active_sit) {
      const started = state.schedule.active_sit.started_at;
      if (this.serverOwnsAlert(started, state.push?.sit_sent_for, state.push?.sit_scheduled_for)) {
        this.notifiedSit = true;
      } else if (this.sitLeft() <= 0 && !this.notifiedSit) {
        this.notifiedSit = true;
        const name = state.settings.child_name.trim();
        const length = `${state.settings.sit_minutes} min sit`;
        void this.showNotification(
          'Sit time is up',
          name ? `${name}. ${length}.` : `${length}.`,
          `sit:${started}`,
        );
      }
      return;
    }
    this.notifiedSit = false;
    const next = state.schedule.next_sit_at;
    const offOwned = this.serverOwnsAlert(next, state.push?.off_sent_for, state.push?.off_scheduled_for);
    if (offOwned) {
      this.notifiedOff = true;
    } else if (state.schedule.running && next && this.offLeft() <= 0 && !this.notifiedOff) {
      this.notifiedOff = true;
      const name = state.settings.child_name.trim();
      const minutes = state.schedule.timer_interval_minutes;
      const length = typeof minutes === 'number' ? `${minutes} min off potty` : 'Off-potty interval';
      void this.showNotification('Time to go potty', name ? `${name}. ${length}.` : `${length}.`, `off:${next}`);
    }
    if (this.offLeft() > 0 && !offOwned) {
      this.notifiedOff = false;
    }
  }

  private serverOwnsAlert(
    token: string | null | undefined,
    sent: string | null | undefined,
    scheduled: string | null | undefined,
  ): boolean {
    return !!token && (sent === token || scheduled === token);
  }

  private async showNotification(title: string, body: string, tag: string): Promise<void> {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted' || !('serviceWorker' in navigator)) {
      return;
    }
    try {
      const registration = await this.ensureWorker();
      await navigator.serviceWorker.ready;
      await registration.showNotification(title, { body, tag });
    } catch {
      this.workerReady = undefined;
    }
  }

  private maybeChime(): void {
    if (!this.soundOn()) {
      return;
    }
    const state = this.state();
    if (!state) {
      return;
    }
    if (state.schedule.active_sit) {
      if (this.sitLeft() <= 0 && !this.announcedSit) {
        this.announcedSit = true;
        this.chime();
      }
      return;
    }
    this.announcedSit = false;
    if (state.schedule.running && state.schedule.next_sit_at && this.offLeft() <= 0 && !this.announcedOff) {
      this.announcedOff = true;
      this.chime();
    }
    if (this.offLeft() > 0) {
      this.announcedOff = false;
    }
  }

  private prepareAudio(): void {
    const Ctx = window.AudioContext;
    if (!Ctx) {
      return;
    }
    this.audio ??= new Ctx();
    if (this.audio.state === 'suspended') {
      void this.audio.resume();
    }
  }

  private chime(): void {
    this.prepareAudio();
    const ctx = this.audio;
    if (!ctx) {
      return;
    }
    const start = ctx.currentTime;
    [523.25, 659.25].forEach((freq, index) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const at = start + index * 0.16;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.07, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.45);
      osc.connect(gain).connect(ctx.destination);
      osc.start(at);
      osc.stop(at + 0.5);
    });
  }
}

function decodeBase64Url(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}
