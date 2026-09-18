import type { AvailableModel } from "@clauseiq/shared-types";

// A saved legacy choice stays visible without making it a new recommendation.
export function getSelectableModels(models: AvailableModel[], selectedId: string): AvailableModel[] {
  return models.filter((model) => !model.legacy || model.id === selectedId);
}

export function getModelSelectionError(models: AvailableModel[], reviewId: string, queryId: string): string | null {
  if (!models.some((model) => model.id === reviewId)) {
    return "The saved review model is not in the current catalog. Choose an available review model before saving.";
  }
  if (!models.some((model) => model.id === queryId)) {
    return "The saved chat query classification model is not in the current catalog. Choose an available model under Advanced before saving.";
  }
  return null;
}

export function formatModelRate(rate: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 3,
  }).format(rate);
}
