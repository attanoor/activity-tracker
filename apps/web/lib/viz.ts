export const BUCKETS = ["productive", "meeting", "communication", "neutral", "non_work", "idle", "private", "break", "away"] as const;
export type Bucket = (typeof BUCKETS)[number];

export const BUCKET_LABEL: Record<Bucket, string> = {
  productive: "Productive", meeting: "Meetings/calls", communication: "Email & chat", neutral: "Neutral/admin",
  non_work: "Non-work", idle: "Idle at desk", private: "Private/paused", break: "Break", away: "Away/untracked",
};

export const bucketColor = (b: string) => `var(--b-${b})`;

/** Session class → bucket (locked = away, paused = private), matching the server's analysis. */
export function bucketOf(klass: string): Bucket {
  if (klass === "paused") return "private";
  if ((BUCKETS as readonly string[]).includes(klass)) return klass as Bucket;
  return "neutral";
}

export function hm(seconds: number): string {
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  return h ? `${h}h${String(m % 60).padStart(2, "0")}m` : `${m}m`;
}

export function clock(iso: string, tz: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz });
}

export function localDate(tz?: string): string {
  return new Date().toLocaleDateString("en-CA", tz ? { timeZone: tz } : undefined);
}

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function seqStep(value: number, max: number): string {
  if (value <= 0 || max <= 0) return "var(--seq-0)";
  return `var(--seq-${Math.min(5, Math.max(1, Math.ceil((value / max) * 5)))})`;
}
