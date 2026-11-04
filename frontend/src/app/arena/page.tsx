import { Suspense } from "react";
import { Arena } from "./Arena";

export default function ArenaPage() {
  return (
    <Suspense>
      <Arena />
    </Suspense>
  );
}
