import MarkdownIt from "markdown-it";

// html: false makes markdown-it escape raw HTML, so the result is safe for v-html.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

// Links open in a new tab without handing over window.opener or the referrer.
const defaultLinkOpen =
  md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx]!.attrSet("target", "_blank");
  tokens[idx]!.attrSet("rel", "noopener noreferrer");
  return defaultLinkOpen(tokens, idx, options, env, self);
};

// Never load remote images from the preview (tracking pixels): show the alt text, linked when the URL is valid.
md.renderer.rules.image = (tokens, idx) => {
  const token = tokens[idx]!;
  const src = token.attrGet("src") ?? "";
  const alt = md.utils.escapeHtml(token.content || src);
  if (!src || !md.validateLink(src)) return alt;
  return `<a href="${md.utils.escapeHtml(md.normalizeLink(src))}" target="_blank" rel="noopener noreferrer">${alt}</a>`;
};

/** Render Markdown to HTML. Raw HTML in the source is escaped; `javascript:` links are not rendered as links. */
export function renderMarkdown(source: string): string {
  return md.render(source);
}
