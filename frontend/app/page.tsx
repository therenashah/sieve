import { getHealth } from "@/lib/api";

export default async function HomePage() {
  let apiStatus = "unreachable";
  try {
    const health = await getHealth();
    apiStatus = `${health.status} (${health.app_env})`;
  } catch {
    apiStatus = "unreachable";
  }

  return (
    <main>
      <h1>Hello, Sieve 👋</h1>
      <p>AI-powered resume screening and L1 interview agent.</p>
      <p>Backend API status: <strong>{apiStatus}</strong></p>
    </main>
  );
}
