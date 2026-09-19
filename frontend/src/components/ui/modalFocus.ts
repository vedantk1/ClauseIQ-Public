type ModalEntry = {
  element: HTMLElement;
  onEscape: () => void;
  returnFocus: HTMLElement | null;
};

type ModalStack = {
  entries: ModalEntry[];
  overflow: string;
  overflowPriority: string;
  keydown: (event: KeyboardEvent) => void;
  focusin: (event: FocusEvent) => void;
};

const stacks = new WeakMap<Document, ModalStack>();
const focusableSelector = "a[href], area[href], button, input, select, textarea, summary, iframe, [tabindex], [contenteditable]";

function focusableElements(element: HTMLElement): HTMLElement[] {
  return Array.from(element.querySelectorAll<HTMLElement>(focusableSelector))
    .filter(candidate => candidate.tabIndex >= 0 && !candidate.matches(":disabled") &&
      !candidate.closest("[hidden], [inert]") && candidate.getClientRects().length > 0 &&
      candidate.ownerDocument.defaultView?.getComputedStyle(candidate).visibility !== "hidden")
    // Native tab order puts positive tab indexes ahead of zero, preserving DOM order for ties.
    .sort((a, b) => (a.tabIndex || Infinity) - (b.tabIndex || Infinity));
}

function focusInside(element: HTMLElement) {
  (focusableElements(element)[0] || element).focus({ preventScroll: true });
}

export function isTopModal(element: HTMLElement | null): boolean {
  if (!element) return false;
  return stacks.get(element.ownerDocument)?.entries.at(-1)?.element === element;
}

/** One scroll lock and keyboard/focus boundary per document, shared by open dialogs only. */
export function mountModal(element: HTMLElement, onEscape: () => void): () => void {
  const document = element.ownerDocument;
  let stack = stacks.get(document);
  if (!stack) {
    stack = {
      entries: [],
      overflow: document.body.style.getPropertyValue("overflow"),
      overflowPriority: document.body.style.getPropertyPriority("overflow"),
      keydown: event => {
        const top = stacks.get(document)?.entries.at(-1);
        if (!top) return;
        if (event.key === "Escape") {
          // Do not let a background dialog or page shortcut also handle dismissal.
          event.preventDefault();
          event.stopImmediatePropagation();
          top.onEscape();
        } else if (event.key === "Tab") {
          const focusable = focusableElements(top.element);
          const first = focusable[0];
          const last = focusable.at(-1);
          const active = document.activeElement;
          if (!first || !top.element.contains(active) || active === top.element ||
            (event.shiftKey ? active === first : active === last)) {
            event.preventDefault();
            (event.shiftKey ? last || top.element : first || top.element).focus({ preventScroll: true });
          }
        }
      },
      focusin: event => {
        const top = stacks.get(document)?.entries.at(-1);
        if (top && !top.element.contains(event.target as Node | null)) focusInside(top.element);
      },
    };
    stacks.set(document, stack);
    document.body.style.setProperty("overflow", "hidden");
    document.addEventListener("keydown", stack.keydown, true);
    document.addEventListener("focusin", stack.focusin, true);
  }
  const active = document.activeElement;
  const entry: ModalEntry = { element, onEscape, returnFocus: active instanceof HTMLElement ? active : null };
  stack.entries.push(entry);
  // Begin at the dialog so its heading/context is announced, not a destructive action.
  element.focus({ preventScroll: true });

  return () => {
    const current = stacks.get(document);
    if (!current || !current.entries.includes(entry)) return;
    const wasTop = current.entries.at(-1) === entry;
    current.entries = current.entries.filter(item => item !== entry);
    // If a parent unmounts before its child, do not later restore into the removed parent.
    for (const remaining of current.entries) {
      if (remaining.returnFocus && element.contains(remaining.returnFocus)) remaining.returnFocus = entry.returnFocus;
    }
    if (!current.entries.length) {
      document.removeEventListener("keydown", current.keydown, true);
      document.removeEventListener("focusin", current.focusin, true);
      if (current.overflow) document.body.style.setProperty("overflow", current.overflow, current.overflowPriority);
      else document.body.style.removeProperty("overflow");
      stacks.delete(document);
    }
    if (wasTop) {
      const next = current.entries.at(-1);
      if (entry.returnFocus?.isConnected && (!next || next.element.contains(entry.returnFocus))) {
        entry.returnFocus.focus({ preventScroll: true });
        if (next && !next.element.contains(document.activeElement)) focusInside(next.element);
      } else if (next) focusInside(next.element);
    }
  };
}
