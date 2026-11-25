import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { Api } from './api';

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
  protected readonly owner = signal(false);
  protected readonly child = computed(() => this.api.state()?.settings.child_name || 'Potty Log');
  protected readonly interval = computed(() => this.api.state()?.derived.current_interval_minutes ?? null);

  constructor() {
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
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntilDestroyed(destroyRef),
      )
      .subscribe(() => this.url.set(this.router.url));
    void this.api.restore().then((ok) => {
      if (ok) {
        void this.api.refresh();
      }
    });
  }
}
