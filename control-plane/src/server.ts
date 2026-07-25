import { buildControlPlaneApp } from "./app";
import { shutdownOtelSdk, startOtelSdk } from "./otel";

async function main(): Promise<void> {
  await startOtelSdk();

  const host = process.env.HOST ?? "127.0.0.1";
  const normalizedHost = host.trim().toLowerCase();
  const isLoopback =
    normalizedHost === "127.0.0.1" ||
    normalizedHost === "localhost" ||
    normalizedHost === "::1";
  const hasApiKey = Boolean(process.env.SYNAPS_CONTROL_PLANE_API_KEY?.trim());
  const allowAnonymous = process.env.SYNAPS_CONTROL_PLANE_ALLOW_ANONYMOUS === "1";

  if (!isLoopback && !hasApiKey && !allowAnonymous) {
    throw new Error(
      "Refusing to bind SynAPS control-plane beyond loopback without " +
        "SYNAPS_CONTROL_PLANE_API_KEY (or SYNAPS_CONTROL_PLANE_ALLOW_ANONYMOUS=1)",
    );
  }

  const app = buildControlPlaneApp({ logger: true });
  const port = Number(process.env.PORT ?? 3000);

  const gracefulShutdown = async (): Promise<void> => {
    await app.close();
    await shutdownOtelSdk();
  };

  process.once("SIGINT", () => {
    void gracefulShutdown();
  });
  process.once("SIGTERM", () => {
    void gracefulShutdown();
  });

  try {
    await app.listen({ port, host });
  } catch (error) {
    app.log.error(error);
    await shutdownOtelSdk();
    process.exitCode = 1;
  }
}

void main();