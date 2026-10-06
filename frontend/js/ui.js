/** Shared UI helpers for text, loading, empty, and error states. */

export function setText(element, value) {
  if (element) {
    element.textContent = value;
  }
}

export function showError(element, message) {
  if (!element) return;
  setText(element, message || "");
  element.hidden = !message;
}

/**
 * Render a loading / empty / error callout into a container.
 * @param {HTMLElement | null} container
 * @param {{
 *   variant?: "loading" | "empty" | "error",
 *   title: string,
 *   body?: string,
 *   actionHref?: string,
 *   actionLabel?: string,
 *   onAction?: () => void,
 * }} options
 */
export function renderState(container, options) {
  if (!container) return;
  const variant = options.variant || "empty";
  container.replaceChildren();
  container.hidden = false;

  const block = document.createElement("div");
  block.className = `state-block is-${variant}`;
  block.setAttribute("role", variant === "error" ? "alert" : "status");

  const title = document.createElement("p");
  title.className = "state-title";
  if (variant === "loading") {
    const pulse = document.createElement("span");
    pulse.className = "loading-pulse";
    pulse.setAttribute("aria-hidden", "true");
    title.append(pulse, document.createTextNode(options.title));
  } else {
    title.textContent = options.title;
  }

  block.append(title);

  if (options.body) {
    const body = document.createElement("p");
    body.className = "state-body";
    body.textContent = options.body;
    block.append(body);
  }

  if (options.actionHref || options.onAction || options.actionLabel) {
    const actions = document.createElement("div");
    actions.className = "state-actions button-row";
    if (options.actionHref) {
      const link = document.createElement("a");
      link.className = "button-primary";
      link.href = options.actionHref;
      link.textContent = options.actionLabel || "Continue";
      actions.append(link);
    } else if (options.onAction) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "button-primary";
      btn.textContent = options.actionLabel || "Retry";
      btn.addEventListener("click", options.onAction);
      actions.append(btn);
    }
    block.append(actions);
  }

  container.append(block);
}

export function clearState(container) {
  if (!container) return;
  container.replaceChildren();
}
