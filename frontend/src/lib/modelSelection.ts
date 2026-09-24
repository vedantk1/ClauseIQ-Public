import type { AvailableModel } from "@clauseiq/shared-types";

// A saved legacy choice stays visible without making it a new recommendation.
export function getSelectableModels(models: AvailableModel[], selectedId: string): AvailableModel[] {
  return models.filter((model) => !model.legacy || model.id === selectedId);
}

export function getModelSelectionError(models: AvailableModel[], reviewId: string, queryId: string, effort?: string): string | null {
  if (!models.some((model) => model.id === reviewId)) {
    return "The saved review model is not in the current catalog. Choose an available review model before saving.";
  }
  if (!models.some((model) => model.id === queryId)) {
    return "The saved chat query classification model is not in the current catalog. Choose an available model under Advanced before saving.";
  }
  if (effort !== undefined && !models.find(model => model.id === reviewId)?.reasoning_efforts.includes(effort)) {
    return "Choose a supported reasoning effort for the review model before saving.";
  }
  return null;
}

export function effortForModel(model: AvailableModel, current: string): string {
  return model.reasoning_efforts.includes(current) ? current : model.default_reasoning_effort;
}

export function reasoningLabel(effort: string): string {
  return ({ none: "None", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Maximum" } as Record<string, string>)[effort] ?? effort;
}

export function formatModelRate(rate: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 3,
  }).format(rate);
}
