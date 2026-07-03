export default function JobPage({ params }: { params: { id: string } }) {
  return (
    <main>
      <h1>Job {params.id}</h1>
      <p>Rubric panel + ranked table + filter bar — coming soon.</p>
    </main>
  );
}
