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
