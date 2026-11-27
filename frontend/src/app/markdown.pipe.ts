import { Pipe, PipeTransform } from '@angular/core';
import { marked } from 'marked';

marked.setOptions({
  breaks: true,
  gfm: true,
});

@Pipe({ name: 'markdown' })
export class MarkdownPipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    const text = (value ?? '').trim();
    if (!text) {
      return '';
    }
    return marked.parse(text, { async: false }) as string;
  }
}
