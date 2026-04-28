import { CONDITION_LABELS } from "./constants";

export function formatJPY(amount: number): string {
  return `¥${amount.toLocaleString("ja-JP")}`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatCondition(condition: string): string {
  return CONDITION_LABELS[condition] ?? condition;
}
