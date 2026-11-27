import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { Api } from './api';
import { Theme } from './theme';

const POLL_MS = 30_000;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
})
export class App {
  protected readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly url = signal(this.router.url);

  protected readonly showNav = computed(() => this.api.signedIn() && !this.url().startsWith('/login'));
  protected readonly refreshing = signal(false);
  protected readonly owner = signal(false);
  protected readonly child = computed(() => this.api.state()?.settings.child_name || 'Potty Log');
  protected readonly interval = computed(() => this.api.state()?.derived.current_interval_minutes ?? null);
  private pollTimer = 0;
  private wakeTimer = 0;
  private hidden = document.visibilityState === 'hidden';

  constructor() {
    inject(Theme);
    effect(() => {
      if (!this.api.signedIn()) {
        this.owner.set(false);
        return;
      }
      void this.api.canInvite().then((allowed) => {
        if (this.api.signedIn()) {
          this.owner.set(allowed);
        }
      });
    });
    const destroyRef = inject(DestroyRef);
    effect(() => {
      if (this.api.signedIn() && !this.url().startsWith('/login')) {
        this.startPoll();
      } else {
        this.stopPoll();
      }
    });
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        this.hidden = true;
        this.stopPoll();
        return;
      }
      const woke = this.hidden;
      this.hidden = false;
      this.startPoll();
      if (woke) {
        this.refreshAfterWake();
      }
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) {
        return;
      }
      this.hidden = true;
      onVisibility();
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pageshow', onPageShow);
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntilDestroyed(destroyRef),
      )
      .subscribe(() => this.url.set(this.router.url));
    destroyRef.onDestroy(() => {
      this.stopPoll();
      window.clearTimeout(this.wakeTimer);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pageshow', onPageShow);
    });
    void this.api.restore().then((ok) => {
      if (ok) {
        void this.api.refresh();
      }
    });
  }

  private startPoll(): void {
    if (this.pollTimer || !this.api.signedIn() || document.visibilityState !== 'visible') {
      return;
    }
    this.pollTimer = window.setInterval(() => {
      if (!this.api.signedIn() || document.visibilityState !== 'visible') {
        this.stopPoll();
        return;
      }
      void this.api.refresh({ quiet: true });
    }, POLL_MS);
  }

  private stopPoll(): void {
    if (!this.pollTimer) {
      return;
    }
    window.clearInterval(this.pollTimer);
    this.pollTimer = 0;
  }

  private refreshAfterWake(): void {
    window.clearTimeout(this.wakeTimer);
    this.wakeTimer = window.setTimeout(() => {
      if (this.api.signedIn() && document.visibilityState === 'visible' && !this.url().startsWith('/login')) {
        void this.api.refresh({ quiet: true });
      }
    }, 50);
  }

  protected async refresh(): Promise<void> {
    this.refreshing.set(true);
    try {
      await this.api.refresh({ views: true });
    } finally {
      this.refreshing.set(false);
    }
  }
}
