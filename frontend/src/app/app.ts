import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
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

  protected readonly showNav = computed(() => !!this.api.token() && !this.url().startsWith('/login'));
  protected readonly child = computed(() => this.api.state()?.settings.child_name || 'Potty Log');
  protected readonly interval = computed(() => this.api.state()?.derived.current_interval_minutes ?? null);

  constructor() {
    const destroyRef = inject(DestroyRef);
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntilDestroyed(destroyRef),
      )
      .subscribe(() => this.url.set(this.router.url));
    if (this.api.token()) {
      void this.api.refresh();
    }
  }
}
