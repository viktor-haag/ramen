/** Duration (ms) a pointer must stay down to count as a long press. */
export const LONG_PRESS_MS = 500;

/** Pointer drift (px) that turns a pending long press into a scroll/drag gesture. */
export const LONG_PRESS_MOVE_TOLERANCE = 10;

/** Fallback delay (ms) after the finger is lifted: open the menu even if no follow-up click arrives. */
export const LONG_PRESS_FALLBACK_MS = 300;

/**
 * Pointer handlers that call `onLongPress` after the pointer has been held for `ms`.
 * Mouse pointers are ignored (they use the right-click `contextmenu` event instead).
 *
 * The callback does not run when the timer fires but once the gesture is over: after the follow-up
 * click (which `onClickCapture` swallows) or, if none arrives, `LONG_PRESS_FALLBACK_MS` after the
 * pointer was lifted. Opening an overlay while the finger is still down would let its capture-phase
 * click-outside handler close it again on that very click. `cancel` (e.g. a drag started) aborts
 * a pending long press so the callback never runs.
 */
export function useLongPress(onLongPress: (e: PointerEvent) => void, ms = LONG_PRESS_MS) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let fallback: ReturnType<typeof setTimeout> | undefined;
  let pending: PointerEvent | undefined; // long press recognised, callback not yet run
  let released = false;
  let suppressClick = false;
  let startX = 0;
  let startY = 0;

  function cancel() {
    clearTimeout(timer);
    clearTimeout(fallback);
    timer = fallback = undefined;
    pending = undefined;
    suppressClick = false;
  }

  function fire() {
    clearTimeout(fallback);
    fallback = undefined;
    const e = pending;
    pending = undefined;
    if (e) onLongPress(e);
  }

  function onPointerdown(e: PointerEvent) {
    cancel();
    released = false;
    if (e.pointerType === "mouse") return;
    startX = e.clientX;
    startY = e.clientY;
    timer = setTimeout(() => {
      timer = undefined;
      suppressClick = true;
      pending = e;
    }, ms);
  }

  function onPointermove(e: PointerEvent) {
    if (timer === undefined && !(pending && !released)) return;
    if (Math.hypot(e.clientX - startX, e.clientY - startY) > LONG_PRESS_MOVE_TOLERANCE) cancel();
  }

  function onPointerup() {
    released = true;
    clearTimeout(timer);
    timer = undefined;
    if (pending) fallback = setTimeout(fire, LONG_PRESS_FALLBACK_MS);
  }

  function onPointerleave() {
    // Lifting a finger also fires pointerleave: only a pointer that left while still down aborts.
    if (!released) cancel();
  }

  function onClickCapture(e: Event) {
    if (!suppressClick) return;
    suppressClick = false;
    e.stopPropagation();
    e.stopImmediatePropagation();
    e.preventDefault();
    if (pending) {
      clearTimeout(fallback);
      fallback = setTimeout(fire, 0); // after the click finished dispatching
    }
  }

  return { onPointerdown, onPointermove, onPointerup, onPointercancel: cancel, onPointerleave, onClickCapture, cancel };
}
