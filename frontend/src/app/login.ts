import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from './api';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html',
})
export class LoginPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected password = '';
  protected readonly message = signal('');
  protected readonly busy = signal(false);

  async submit(event: Event): Promise<void> {
    const form = event.target;
    const password = form instanceof HTMLFormElement ? String(new FormData(form).get('password') ?? '') : this.password;
    this.busy.set(true);
    this.message.set('');
    const error = await this.api.login(password);
    this.busy.set(false);
    if (error) {
      this.message.set(error);
      return;
    }
    await this.router.navigateByUrl('/now');
  }
}
