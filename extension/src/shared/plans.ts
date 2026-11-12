/** Plan listings shown in the settings window. Mirrors backend/app/plans.py so they are visible before anyone signs in. */
export const PREMIUM_NAME = "Churnce Premium";
export const FREE_FEATURES = [
  "Consent-based friction capture on authorised sites",
  "Review gate, RAG window and Digest classification",
  "Evidence-linked recommendations and approved win-back emails",
  "Connected sites, roles and live activity",
];
export const PREMIUM_FEATURES: { title: string; text: string }[] = [
  { title: "Liquidity engine", text: "Live cash position across banks and currencies, converted to KES, with runway and coverage." },
  { title: "Multi-horizon forecasts and stress tests", text: "7 to 90 day income and cashflow forecasts with confidence bands, plus scenario stress tests." },
  { title: "Working capital and pooling", text: "Receivables, payables and inventory cycles, with cash pooling and sweeping rules." },
  { title: "Compliance ratios", text: "Current ratio, quick ratio and liquidity coverage ratio, checked against thresholds." },
  { title: "Cents AI analyst", text: "A virtual financial analyst that summarises your metrics, offers advice and answers questions." },
  { title: "Transaction capture", text: "Amounts, currency, status, bank label and failure reason. Never card numbers, account numbers or payer identity." },
];
/** Roles selectable with a website id. Administrator is deliberately absent: it needs a named administrator account. */
export const SITE_ROLES: [string, string][] = [["data_analyst", "Data Analyst"], ["developer", "Developer"], ["website_owner", "Website Owner"]];
export const PRICES = { free: 0, premium: 333, currency: "KES" } as const;
export const TRIAL_HOURS = 72;
