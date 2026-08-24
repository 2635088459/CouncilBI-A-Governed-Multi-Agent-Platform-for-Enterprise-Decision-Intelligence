import { bg, C, footer, hbar, metric, text, title } from "./theme.mjs";

export async function slide03(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  title(slide, "Stable load ran for 10 minutes with no failed requests.", "STEADY STATE");
  metric(slide, "480/480", "HTTP 200 responses", 68, 226, 230, C.green);
  metric(slide, "0.8 RPS", "sustained target throughput", 326, 226, 230, C.blue);
  metric(slide, "176.69ms", "P95 latency", 584, 226, 230, C.green);
  metric(slide, "262.55ms", "P99 latency", 842, 226, 230, C.amber);
  text(slide, "Latency distribution", 72, 372, 260, 30, { size: 18, bold: true });
  hbar(slide, "P50", "96.03ms", 0.36, 74, 430, 360, C.green);
  hbar(slide, "P95", "176.69ms", 0.67, 74, 476, 360, C.blue);
  hbar(slide, "P99", "262.55ms", 1.0, 74, 522, 360, C.amber);
  text(slide, "Interpretation", 850, 394, 180, 28, { size: 18, bold: true });
  text(slide, "This is the primary reliability number for the demo report: a controlled sustained workload below the configured rate limit, run against the public GKE endpoint for a full 600-second window.", 850, 432, 300, 116, { size: 18, valign: "top" });
  footer(slide, "Source: dist/report/gke-sustained-stable-benchmark.md", 3);
  return slide;
}
