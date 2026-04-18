import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { NodeSDK } from "@opentelemetry/sdk-node";

let sdk: NodeSDK | null = null;

export async function startOtelSdk(): Promise<void> {
  if (process.env.SYNAPS_OTEL_ENABLED !== "1") {
    return;
  }

  if (sdk !== null) {
    return;
  }

  const traceExporter = new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
  });

  sdk = new NodeSDK({
    traceExporter,
  });

  await sdk.start();
}

export async function shutdownOtelSdk(): Promise<void> {
  if (sdk === null) {
    return;
  }

  await sdk.shutdown();
  sdk = null;
}
