import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from './api';
import {
  authMessage,
  confirmAuthenticator,
  confirmEmail,
  confirmNewPassword,
  finishPasswordReset,
  normalizeEmail,
  passwordProblem,
  resendEmailCode,
  sendPasswordReset,
  signInWithPassword,
  type AuthView,
} from './auth';

type Step = 'sign-in' | 'confirm-email' | 'new-password' | 'totp-setup' | 'totp-code' | 'forgot' | 'reset';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html',
})
export class LoginPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  protected step = signal<Step>('sign-in');
  protected email = '';
  protected password = '';
  protected code = '';
  protected rememberHere = false;
  protected secret = signal('');
  protected qr = signal('');
  protected readonly message = signal('');
  protected readonly tone = signal<'error' | 'ok'>('error');
  protected readonly busy = signal(false);

  protected go(step: Step): void {
    this.message.set('');
    this.code = '';
    this.rememberHere = false;
    this.step.set(step);
  }

  protected async submitSignIn(event: Event): Promise<void> {
    event.preventDefault();
    const email = normalizeEmail(this.email);
    if (!email || !this.password) {
      this.fail('Enter your email and password.');
      return;
    }
    await this.run(async () => this.applyView(await signInWithPassword(email, this.password)));
  }

  protected async submitNewPassword(event: Event): Promise<void> {
    event.preventDefault();
    const problem = passwordProblem(this.password);
    if (problem) {
      this.fail(problem);
      return;
    }
    await this.run(async () => this.applyView(await confirmNewPassword(this.password)));
  }

  protected async submitEmailCode(event: Event): Promise<void> {
    event.preventDefault();
    const code = this.code.trim();
    if (!code) {
      this.fail('Enter the code from the email.');
      return;
    }
    await this.run(async () => {
      const next = await confirmEmail(this.email, code);
      if (next === 'sign-in') {
        this.code = '';
        this.note('Email confirmed. Sign in.');
        this.step.set('sign-in');
        return;
      }
      await this.applyView(next);
    });
  }

  protected async resendCode(): Promise<void> {
    await this.run(async () => {
      await resendEmailCode(this.email);
      this.note('We sent another code.');
    });
  }

  protected async submitTotp(event: Event): Promise<void> {
    event.preventDefault();
    const code = this.code.trim();
    if (!code) {
      this.fail('Enter the 6-digit code from your authenticator.');
      return;
    }
    await this.run(async () => this.applyView(await confirmAuthenticator(code)));
  }

  protected async submitForgot(event: Event): Promise<void> {
    event.preventDefault();
    const email = normalizeEmail(this.email);
    if (!email.includes('@')) {
      this.fail('Enter the email address for this account.');
      return;
    }
    await this.run(async () => {
      await sendPasswordReset(email);
      this.email = email;
      this.code = '';
      this.password = '';
      this.note('If that email has an account, we sent a code.');
      this.step.set('reset');
    });
  }

  protected async submitReset(event: Event): Promise<void> {
    event.preventDefault();
    const problem = passwordProblem(this.password);
    if (!this.code.trim()) {
      this.fail('Enter the code from the email.');
      return;
    }
    if (problem) {
      this.fail(problem);
      return;
    }
    await this.run(async () => {
      await finishPasswordReset(this.email, this.code.trim(), this.password);
      this.code = '';
      this.password = '';
      this.note('Password updated. Sign in with the new password and your authenticator.');
      this.step.set('sign-in');
    });
  }

  private async applyView(view: AuthView): Promise<void> {
    if (view.kind === 'signed-in') {
      const opened = await this.api.openSession(this.rememberHere);
      if (!opened.ok) {
        this.fail('Signed in, but this browser could not be registered. Try again.');
        return;
      }
      await this.api.restore();
      await this.router.navigateByUrl('/now');
      if (this.rememberHere && !opened.remembered) {
        this.api.error.set('Signed in. This device was not remembered, so the next sign-in still needs an authenticator code.');
      }
      return;
    }
    if (view.kind === 'confirm-email') {
      this.note('Enter the code from your email.');
      this.step.set('confirm-email');
      return;
    }
    if (view.kind === 'new-password') {
      this.password = '';
      this.message.set('');
      this.step.set('new-password');
      return;
    }
    if (view.kind === 'totp-setup') {
      this.secret.set(view.secret);
      this.qr.set(view.qr);
      this.code = '';
      this.message.set('');
      this.step.set('totp-setup');
      return;
    }
    this.code = '';
    this.message.set('');
    this.step.set('totp-code');
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.message.set('');
    try {
      await action();
    } catch (error) {
      const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : '';
      if (name === 'UserNotConfirmedException') {
        this.step.set('confirm-email');
      }
      this.tone.set('error');
      this.message.set(authMessage(error, 'Could not sign in.'));
    } finally {
      this.busy.set(false);
    }
  }

  private note(text: string): void {
    this.tone.set('ok');
    this.message.set(text);
  }

  private fail(text: string): void {
    this.tone.set('error');
    this.message.set(text);
  }
}
