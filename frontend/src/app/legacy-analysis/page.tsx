import { redirect } from "next/navigation";

/** Keep old bookmarks useful without retaining the retired paid uploader. */
export default function LegacyAnalysis() {
  redirect("/import");
}
