import { Component, ElementRef, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, ChatStreamEvent } from './api';

type ChatBlock =
  | { kind: 'thought'; text: string }
  | { kind: 'text'; text: string }
  | { kind: 'tool'; name: string; detail: string };

type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
  blocks: ChatBlock[];
  pending?: boolean;
};

@Component({
  selector: 'app-chat',
  imports: [FormsModule],
  templateUrl: './chat.html',
})
export class ChatPanel {
  private readonly api = inject(Api);

  readonly open = signal(false);
  readonly draft = signal('');
  readonly messages = signal<ChatMessage[]>([]);
  readonly streaming = signal(false);
  readonly error = signal('');

  @ViewChild('scroller') private scroller?: ElementRef<HTMLElement>;

  toggle(): void {
    this.open.update((value) => !value);
  }

  close(): void {
    this.open.set(false);
  }

  async send(): Promise<void> {
    const text = this.draft().trim();
    if (!text || this.streaming()) {
      return;
    }
    this.draft.set('');
    this.error.set('');
    const history = this.messages()
      .filter((message) => message.text.trim())
      .map((message) => ({ role: message.role, content: message.text }));
    this.messages.update((list) => [
      ...list,
      { role: 'user', text, blocks: [] },
      { role: 'assistant', text: '', blocks: [], pending: true },
    ]);
    this.streaming.set(true);
    this.scrollSoon();

    try {
      await this.api.streamChat(text, history, (event) => this.onEvent(event));
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'The assistant failed.');
      this.messages.update((list) => {
        const copy = [...list];
        const last = copy[copy.length - 1];
        if (last?.role === 'assistant' && last.pending) {
          copy[copy.length - 1] = { ...last, pending: false, text: last.text || 'Something went wrong.' };
        }
        return copy;
      });
    } finally {
      this.streaming.set(false);
      this.scrollSoon();
      void this.api.refresh({ quiet: true, views: true });
    }
  }

  private onEvent(event: ChatStreamEvent): void {
    this.messages.update((list) => {
      const copy = [...list];
      const last = copy[copy.length - 1];
      if (!last || last.role !== 'assistant') {
        return list;
      }
      const next: ChatMessage = {
        ...last,
        blocks: [...last.blocks],
        text: last.text,
        pending: true,
      };
      if (event.type === 'thought' && event.text) {
        const prior = next.blocks[next.blocks.length - 1];
        if (prior?.kind === 'thought') {
          next.blocks[next.blocks.length - 1] = { kind: 'thought', text: prior.text + event.text };
        } else {
          next.blocks.push({ kind: 'thought', text: event.text });
        }
      } else if (event.type === 'text' && event.text) {
        next.text += event.text;
        const prior = next.blocks[next.blocks.length - 1];
        if (prior?.kind === 'text') {
          next.blocks[next.blocks.length - 1] = { kind: 'text', text: prior.text + event.text };
        } else {
          next.blocks.push({ kind: 'text', text: event.text });
        }
      } else if (event.type === 'tool' && event.name) {
        next.blocks.push({
          kind: 'tool',
          name: event.name,
          detail: event.input ? JSON.stringify(event.input) : '',
        });
      } else if (event.type === 'tool_result' && event.name) {
        next.blocks.push({
          kind: 'tool',
          name: `${event.name} ✓`,
          detail: (event.result || '').slice(0, 240),
        });
      } else if (event.type === 'error') {
        this.error.set(event.message || 'The assistant failed.');
      } else if (event.type === 'done') {
        next.pending = false;
      }
      copy[copy.length - 1] = next;
      return copy;
    });
    this.scrollSoon();
  }

  private scrollSoon(): void {
    queueMicrotask(() => {
      const node = this.scroller?.nativeElement;
      if (node) {
        node.scrollTop = node.scrollHeight;
      }
    });
  }
}
