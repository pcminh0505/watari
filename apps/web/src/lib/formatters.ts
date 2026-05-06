import { CONDITION_LABELS } from "./constants";

export function formatJPY(amount: number): string {
  return `¥${amount.toLocaleString("ja-JP")}`;
}

export function formatPrice(
  jpy: number,
  currency: "JPY" | "USD" | "VND",
  rates: { USD: number; VND: number }
): string {
  if (currency === "USD") {
    return `$${(jpy * rates.USD).toFixed(2)}`;
  }
  if (currency === "VND") {
    return `₫${Math.round(jpy * rates.VND).toLocaleString("vi-VN")}`;
  }
  return formatJPY(jpy);
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
