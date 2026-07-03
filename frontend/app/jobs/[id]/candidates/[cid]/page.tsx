export default function CandidatePage({
  params,
}: {
  params: { id: string; cid: string };
}) {
  return (
    <main>
      <h1>
        Candidate {params.cid} — Job {params.id}
      </h1>
      <p>Scores, evidence, transcripts — coming soon.</p>
    </main>
  );
}
