import { Component, ElementRef, HostListener, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, ChatStreamEvent } from './api';
import { MarkdownPipe } from './markdown.pipe';

type DetailItem =
  | { kind: 'thought'; text: string }
  | { kind: 'tool'; name: string; status: 'running' | 'done'; note: string; toolUseId: string };

type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
  details: DetailItem[];
  pending?: boolean;
  activeTool?: string;
};

@Component({
  selector: 'app-chat',
  imports: [FormsModule, MarkdownPipe],
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

  onComposeKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.ctrlKey || event.metaKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    void this.send();
  }

  @HostListener('document:keydown', ['$event'])
  onDocumentKeydown(event: KeyboardEvent): void {
    if (!this.open() || event.key !== 'Escape' || event.isComposing) {
      return;
    }
    event.preventDefault();
    this.close();
  }

  detailsHeading(message: ChatMessage): string {
    if (!message.pending) {
      return 'Details';
    }
    if (message.activeTool) {
      return `Calling ${message.activeTool}`;
    }
    return 'Thinking';
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
      { role: 'user', text, details: [] },
      { role: 'assistant', text: '', details: [], pending: true },
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
          copy[copy.length - 1] = {
            ...last,
            pending: false,
            activeTool: undefined,
            text: last.text || 'Something went wrong.',
          };
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
        details: [...last.details],
        text: last.text,
        pending: true,
        activeTool: last.activeTool,
      };
      if (event.type === 'thought' && event.text) {
        next.activeTool = undefined;
        const prior = next.details[next.details.length - 1];
        if (prior?.kind === 'thought') {
          next.details[next.details.length - 1] = {
            kind: 'thought',
            text: prior.text + event.text,
          };
        } else {
          next.details.push({ kind: 'thought', text: event.text });
        }
      } else if (event.type === 'text' && event.text) {
        next.activeTool = undefined;
        next.text += event.text;
      } else if (event.type === 'tool' && event.name) {
        const toolUseId = String(event.toolUseId || event.name);
        next.activeTool = event.name;
        const index = next.details.findIndex(
          (item) => item.kind === 'tool' && item.toolUseId === toolUseId && item.status === 'running',
        );
        if (index >= 0) {
          const current = next.details[index];
          if (current.kind === 'tool') {
            next.details[index] = { ...current, name: event.name };
          }
        } else {
          next.details.push({
            kind: 'tool',
            name: event.name,
            status: 'running',
            note: '',
            toolUseId,
          });
        }
      } else if (event.type === 'tool_result' && event.name) {
        next.activeTool = undefined;
        const index = [...next.details]
          .map((item, at) => ({ item, at }))
          .reverse()
          .find(({ item }) => item.kind === 'tool' && item.name === event.name && item.status === 'running')
          ?.at;
        const note = summarizeToolResult(event.result || '');
        if (index !== undefined) {
          const current = next.details[index];
          if (current.kind === 'tool') {
            next.details[index] = { ...current, status: 'done', note };
          }
        } else {
          next.details.push({
            kind: 'tool',
            name: event.name,
            status: 'done',
            note,
            toolUseId: event.name,
          });
        }
      } else if (event.type === 'error') {
        this.error.set(event.message || 'The assistant failed.');
      } else if (event.type === 'done') {
        next.pending = false;
        next.activeTool = undefined;
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

function summarizeToolResult(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) {
    return 'Done';
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed && typeof parsed === 'object') {
      const record = parsed as Record<string, unknown>;
      if (typeof record['ok'] === 'boolean') {
        return record['ok']
          ? 'Updated the log.'
          : String(record['error'] || record['message'] || 'Tool returned an error.');
      }
      if (typeof record['error'] === 'string') {
        return record['error'];
      }
      if (typeof record['message'] === 'string') {
        return record['message'];
      }
    }
  } catch {
    // Not JSON; fall through to a short plain snippet.
  }
  return trimmed.length > 120 ? `${trimmed.slice(0, 117)}…` : trimmed;
}
