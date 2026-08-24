import { bg, C, footer, panel, text, title } from "./theme.mjs";

export async function slide05(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  title(slide, "Correctness and governance are measured as separate gates.", "QUALITY GATES");
  const rows = [
    ["Expanded correctness", "12/12", "complex golden cases passed"],
    ["Dangerous SQL detection", "100%", "DROP/DELETE unsafe SQL denied"],
    ["Benign SQL allow rate", "100%", "valid read-only SQL allowed"],
    ["Guardrail P95", "168.55ms", "safety check latency"],
    ["Agent step success", "100%", "planned steps completed"],
    ["Multi-agent collaboration", "100%", "orchestrator, SQL, verifier, synthesis"],
  ];
  let y = 214;
  for (const [label, value, note] of rows) {
    panel(slide, 84, y, 1080, 56, C.white);
    text(slide, label, 104, y + 12, 330, 26, { size: 17, bold: true, fill: C.white });
    text(slide, value, 462, y + 8, 160, 30, { size: 22, bold: true, color: value.includes("ms") ? C.blue : C.green, fill: C.white, align: "right" });
    text(slide, note, 660, y + 12, 430, 26, { size: 16, color: C.muted, fill: C.white });
    y += 62;
  }
  text(slide, "Report framing: quality is not one score. It is answer correctness plus guardrail safety plus execution traceability.", 86, 608, 940, 34, { size: 18, color: C.ink });
  footer(slide, "Sources: gke-extended-correctness.md, gke-staging-metrics.md", 5);
  return slide;
}
