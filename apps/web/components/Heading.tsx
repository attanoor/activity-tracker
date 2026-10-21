export default function Heading({ level = 2, id, children }: { level?: 1 | 2; id?: string; children: React.ReactNode }) {
  return level === 1
    ? <h1 id={id} className="text-2xl font-semibold">{children}</h1>
    : <h2 id={id} className="text-lg font-semibold">{children}</h2>;
}
