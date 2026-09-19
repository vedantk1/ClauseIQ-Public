/** Local delivery only: no API, persistence or provider calls. */
export async function copyReviewBrief(markdown: string): Promise<void> {
  if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
  await navigator.clipboard.writeText(markdown);
}

export function downloadReviewBrief(filename: string, markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  let link: HTMLAnchorElement | undefined;
  try {
    link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
  } finally {
    try {
      link?.remove();
    } finally {
      // Let the browser begin consuming the URL before revoking it.
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
}
