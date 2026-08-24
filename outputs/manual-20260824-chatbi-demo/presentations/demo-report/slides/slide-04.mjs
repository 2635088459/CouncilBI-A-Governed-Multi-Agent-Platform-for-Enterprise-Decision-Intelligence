import { bg, C, footer, metric, text, title } from "./theme.mjs";

export async function slide04(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  title(slide, "At 20 RPS, the platform fails closed through rate limiting.", "OVERLOAD");
  const x = 96;
  const y = 300;
  slide.shapes.add({ geometry: "rect", position: { left: x, top: y, width: 620, height: 46 }, fill: C.green });
  slide.shapes.add({ geometry: "rect", position: { left: x + 620, top: y, width: 510, height: 46 }, fill: C.amber });
  text(slide, "1,200 accepted", x + 18, y + 7, 220, 28, { size: 17, bold: true, color: C.white, fill: C.green });
  text(slide, "429 rate-limited: 10,799", x + 638, y + 7, 260, 28, { size: 17, bold: true, color: C.white, fill: C.amber });
  text(slide, "502: 1", x + 1036, y + 7, 76, 28, { size: 15, bold: true, color: C.white, fill: C.amber });
  metric(slide, "12,000", "requests over 600 seconds", 102, 404, 220, C.ink);
  metric(slide, "19.997", "observed throughput RPS", 358, 404, 230, C.blue);
  metric(slide, "90.0%", "requests intentionally rejected", 626, 404, 250, C.amber);
  text(slide, "Why this matters", 920, 408, 200, 28, { size: 18, bold: true });
  text(slide, "The rate limiter prevents unbounded model/tool execution. In the report, frame this as overload governance, not as steady-state capacity.", 920, 448, 270, 92, { size: 18, valign: "top" });
  footer(slide, "Source: dist/report/gke-sustained-rate-limit-stress.md", 4);
  return slide;
}
