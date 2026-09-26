function formatJPY(amount: number): string {
  return `¥${amount.toLocaleString("ja-JP")}`;
}

const EUR_FORMAT = new Intl.NumberFormat("en-IE", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Native-EUR amounts (Cardmarket). Not currency-converted; bypasses the toggle. */
export function formatEUR(amount: number): string {
  return `€${EUR_FORMAT.format(amount)}`;
}

export function formatPrice(
  jpy: number,
  currency: "JPY" | "USD" | "EUR" | "VND",
  rates: { USD: number; EUR: number; VND: number }
): string {
  if (currency === "USD") {
    return `$${(jpy * rates.USD).toFixed(2)}`;
  }
  if (currency === "EUR") {
    return formatEUR(jpy * rates.EUR);
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

