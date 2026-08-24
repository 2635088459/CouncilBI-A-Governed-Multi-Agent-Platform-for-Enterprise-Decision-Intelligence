import { bg, C, footer, metric, rule, text } from "./theme.mjs";

export async function slide01(presentation) {
  const slide = presentation.slides.add();
  bg(slide, C.ink);
  text(slide, "INSIGHTOPS AI", 58, 44, 280, 28, { size: 14, bold: true, color: C.paleAmber, fill: C.ink });
  text(slide, "Governed ChatBI is now measured on GKE, not just described in code.", 58, 104, 790, 150, {
    size: 48,
    bold: true,
    typeface: "Georgia",
    color: C.paper,
    fill: C.ink,
    valign: "top",
  });
  text(slide, "Demo report for a governed multi-agent BI platform with SQL guardrails, RAG evidence, cloud deployment metrics, and token-efficiency evaluation.", 62, 272, 710, 70, {
    size: 21,
    color: "#D8D2C5",
    fill: C.ink,
    valign: "top",
  });
  rule(slide, 62, 388, 640, "#6E766E");
  metric(slide, "100%", "stable 10-minute success rate", 62, 420, 250, C.green, C.ink);
  metric(slide, "176.69ms", "stable-load P95 latency", 332, 420, 240, C.paleAmber, C.ink);
  metric(slide, "98.01%", "estimated token reduction", 602, 420, 260, C.paleBlue, C.ink);
  metric(slide, "12/12", "complex correctness cases passed", 872, 420, 260, C.paleAmber, C.ink);
  text(slide, "Live staging: http://136.69.23.39", 62, 604, 520, 32, { size: 16, color: C.paper, fill: C.ink });
  text(slide, "Scope: GKE Autopilot staging, mock LLM provider, reproducible benchmark artifacts.", 62, 642, 720, 24, { size: 12, color: "#AAB4AA", fill: C.ink });
  footer(slide, "Sources: dist/report/report-evaluation-summary.md, token-savings-report.md", 1, true);
  return slide;
}
