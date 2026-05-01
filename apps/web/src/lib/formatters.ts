import { CONDITION_LABELS } from "./constants";

export function formatJPY(amount: number): string {
  return `¥${amount.toLocaleString("ja-JP")}`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatCondition(condition: string): string {
  return CONDITION_LABELS[condition] ?? condition;
}

export function normalizeCondition(condition: string): string {
  return condition === "A-" ? "B" : condition;
}
