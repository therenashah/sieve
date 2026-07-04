import ChatWindow from "@/components/ChatWindow";

export default function ChatPage({ params }: { params: { token: string } }) {
  return (
    <main className="chat-page">
      <ChatWindow token={params.token} />
    </main>
  );
}
