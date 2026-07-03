import ChatWindow from "@/components/ChatWindow";

export default function ChatPage({ params }: { params: { token: string } }) {
  return (
    <main>
      <h1>Screening chat</h1>
      <ChatWindow token={params.token} />
    </main>
  );
}
