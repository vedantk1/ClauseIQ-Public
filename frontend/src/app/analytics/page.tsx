import { redirect } from "next/navigation";

/** Preserve old bookmarks without retaining the retired dashboard. */
export default function RetiredAnalytics() {
  redirect("/documents");
}
