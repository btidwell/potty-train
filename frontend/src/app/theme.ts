import { Injectable, signal } from '@angular/core';

export type ThemeId = 'light' | 'dark';

const STORAGE_KEY = 'potty-theme';
const THEME_COLORS: Record<ThemeId, string> = {
  light: '#efe6d4',
  dark: '#1a221c',
};

@Injectable({ providedIn: 'root' })
export class Theme {
  readonly theme = signal<ThemeId>(readStoredTheme());

  constructor() {
    this.apply(this.theme());
  }

  set(theme: ThemeId): void {
    if (theme !== 'light' && theme !== 'dark') {
      return;
    }
    this.theme.set(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Private browsing can block storage; the in-memory choice still applies.
    }
    this.apply(theme);
  }

  private apply(theme: ThemeId): void {
    document.documentElement.dataset['theme'] = theme;
    document.documentElement.style.colorScheme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content', THEME_COLORS[theme]);
    }
  }
}

export function readStoredTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') {
      return stored;
    }
  } catch {
    // Ignore storage errors and fall back to light.
  }
  return 'light';
}
