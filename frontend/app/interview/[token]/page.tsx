import InterviewRoom from "@/components/InterviewRoom";

export default function InterviewPage({ params }: { params: { token: string } }) {
  return (
    <main className="interview-page">
      <InterviewRoom token={params.token} />
    </main>
  );
}
