class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

// jsdom has no visualViewport; Vuetify's overlay positioning (v-menu) reads it.
if (!("visualViewport" in globalThis)) {
  Object.defineProperty(globalThis, "visualViewport", {
    configurable: true,
    value: Object.assign(new EventTarget(), { width: 1024, height: 768, offsetLeft: 0, offsetTop: 0, pageLeft: 0, pageTop: 0, scale: 1 }),
  });
}
// Same for elementsFromPoint (used by the overlay's click-outside handling).
document.elementsFromPoint ??= () => [];

// CodeMirror measures text through Range rects, which jsdom does not implement.
const emptyRects = () => Object.assign([], { item: () => null }) as unknown as DOMRectList;
Range.prototype.getClientRects ??= emptyRects;
Range.prototype.getBoundingClientRect ??= () => new DOMRect();

// Vuetify's v-textarea auto-grow calls getComputedStyle on every input; with the Vuetify CSS loaded
// (css.include) jsdom resolves the full cascade each time, which costs seconds per call and made the
// textarea tests time out under load. jsdom has no layout, so the values are empty/NaN anyway: answer
// those two lookups with an empty style instead.
const realGetComputedStyle = window.getComputedStyle.bind(window);
const emptyStyle = { lineHeight: "", getPropertyValue: () => "" } as unknown as CSSStyleDeclaration;
window.getComputedStyle = ((el: Element, pseudo?: string | null) =>
  el.classList?.contains("v-textarea__sizer") || el.classList?.contains("v-field")
    ? emptyStyle
    : realGetComputedStyle(el, pseudo)) as typeof window.getComputedStyle;
