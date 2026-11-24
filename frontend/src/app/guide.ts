import { Component, computed, inject } from '@angular/core';
import { Api } from './api';

@Component({
  selector: 'app-guide',
  templateUrl: './guide.html',
})
export class GuidePage {
  private readonly api = inject(Api);
  protected readonly step = computed(() => this.api.state()?.settings.step_minutes ?? 5);
  protected readonly sit = computed(() => this.api.state()?.settings.sit_minutes ?? 5);
  protected readonly reward = computed(() => this.api.state()?.settings.reinforcer_note || 'one highly preferred item');
}
