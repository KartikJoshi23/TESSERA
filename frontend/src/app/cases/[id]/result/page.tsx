import { Dossier } from "@/components/dossier/Dossier";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ResultPage({ params }: Props) {
  const { id } = await params;
  const caseId = decodeURIComponent(id);
  return <Dossier key={caseId} id={caseId} />;
}
