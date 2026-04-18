import { buildControlPlaneApp } from "./app";
import { shutdownOtelSdk, startOtelSdk } from "./otel";

async function main(): Promise<void> {
  await startOtelSdk();
  const app = buildControlPlaneApp({ logger: true });
  const port = Number(process.env.PORT ?? 3000);
  const host = process.env.HOST ?? "127.0.0.1";

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