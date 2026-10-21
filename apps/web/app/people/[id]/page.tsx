"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense } from "react";

import DayView from "@/components/DayView";
import Shell from "@/components/Shell";

export default function PersonDayPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Shell>
      <p className="mb-4 text-sm"><Link href="/team" className="underline underline-offset-2">← Team</Link>
        <span className="ml-2 text-muted">Read-only. Viewing someone&apos;s day is recorded in the audit log.</span></p>
      <Suspense>
        <DayView personId={Number(id)} />
      </Suspense>
    </Shell>
  );
}
