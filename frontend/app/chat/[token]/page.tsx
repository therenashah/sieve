export default function ChatPage({ params }: { params: { token: string } }) {
  return (
    <main>
      <h1>Screening chat</h1>
      <p>Session token: {params.token}</p>
      <p>Candidate-facing chat + countdown — coming soon.</p>
    </main>
  );
}
