import { bg, C, footer, metric, text, title } from "./theme.mjs";

export async function slide06(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  title(slide, "SQL plus RAG turns long-context analysis into bounded prompts.", "TOKEN EFFICIENCY");
  text(slide, "Complex executive-analysis benchmark", 72, 202, 360, 28, { size: 18, bold: true });
  const baseX = 110;
  const baseY = 340;
  const scale = 760 / 326696;
  slide.shapes.add({ geometry: "rect", position: { left: baseX, top: baseY, width: 6508 * scale, height: 58 }, fill: C.green });
  slide.shapes.add({ geometry: "rect", position: { left: baseX, top: baseY + 100, width: 326696 * scale, height: 58 }, fill: C.amber });
  text(slide, "Optimized SQL/RAG", baseX, baseY - 34, 220, 28, { size: 16, bold: true });
  text(slide, "6,508 tokens", baseX + 82, baseY + 13, 180, 30, { size: 18, bold: true, color: C.ink, fill: C.paper });
  text(slide, "Naive full context", baseX, baseY + 66, 220, 28, { size: 16, bold: true });
  text(slide, "326,696 tokens", baseX + 520, baseY + 113, 180, 30, { size: 18, bold: true, color: C.white, fill: C.amber });
  metric(slide, "98.01%", "estimated token reduction", 920, 270, 250, C.green);
  metric(slide, "53,365", "avg tokens saved per complex question", 920, 400, 260, C.blue);
  text(slide, "Meaning", 74, 540, 120, 28, { size: 18, bold: true });
  text(slide, "The platform does not stuff multi-year database rows and broad enterprise documents into the model. SQL filters structured data; RAG injects only top evidence snippets.", 214, 536, 796, 54, { size: 18, valign: "top" });
  footer(slide, "Source: dist/report/token-savings-report.md. Estimator-based; exact billing requires OpenAI usage fields.", 6);
  return slide;
}
