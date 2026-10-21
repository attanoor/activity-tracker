"use client";

import { Suspense } from "react";

import DayView from "@/components/DayView";
import Shell from "@/components/Shell";

export default function MyDayPage() {
  return (
    <Shell>
      <Suspense>
        <DayView />
      </Suspense>
    </Shell>
  );
}
