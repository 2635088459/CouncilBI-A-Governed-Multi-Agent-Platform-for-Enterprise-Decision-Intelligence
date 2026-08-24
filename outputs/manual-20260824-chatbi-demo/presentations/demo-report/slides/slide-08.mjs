import { bg, C, footer, panel, text, title } from "./theme.mjs";

export async function slide08(presentation) {
  const slide = presentation.slides.add();
  bg(slide, C.ink);
  title(slide, "The demo story is defensible because every claim has a measurement boundary.", "CLOSE", true);
  const rows = [
    ["Say", "GKE staging handled stable load with 100% success."],
    ["Show", "Live URL, chat query, trace_id, report-evaluation-summary.md."],
    ["Prove", "Latency, correctness, guardrail, recovery, token-efficiency artifacts."],
    ["Be explicit", "Mock LLM provider means cloud runtime proof, not real OpenAI billing proof."],
  ];
  let y = 238;
  for (const [label, copy] of rows) {
    panel(slide, 86, y, 1080, 64, "#223028");
    text(slide, label, 112, y + 18, 120, 26, { size: 18, bold: true, color: C.paleAmber, fill: "#223028" });
    text(slide, copy, 254, y + 17, 830, 28, { size: 20, color: C.paper, fill: "#223028" });
    y += 78;
  }
  text(slide, "Recommended final line", 92, 568, 240, 26, { size: 16, bold: true, color: C.paleAmber, fill: C.ink });
  text(slide, "InsightOps AI demonstrates governed enterprise decision intelligence: measured cloud reliability, bounded model context, auditable SQL/RAG execution, and safety controls that fail closed.", 92, 602, 990, 52, { size: 21, color: C.paper, fill: C.ink, valign: "top" });
  footer(slide, "Source: dist/report/report-evaluation-summary.md", 8, true);
  return slide;
}
