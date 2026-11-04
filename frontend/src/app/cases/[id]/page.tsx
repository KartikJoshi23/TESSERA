import { Theater } from "@/components/theater/Theater";

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ replay?: string }>;
}

export default async function CasePage({ params, searchParams }: Props) {
  const { id } = await params;
  const { replay } = await searchParams;
  const caseId = decodeURIComponent(id);
  return <Theater key={caseId} id={caseId} replay={replay === "1"} />;
}
