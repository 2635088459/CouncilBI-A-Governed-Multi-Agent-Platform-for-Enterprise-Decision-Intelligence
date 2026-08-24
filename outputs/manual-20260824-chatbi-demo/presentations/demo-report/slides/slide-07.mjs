import { bg, C, footer, metric, panel, text, title } from "./theme.mjs";

export async function slide07(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  title(slide, "The GKE deployment recovered quickly and stayed light on resources.", "OPERATIONS");
  panel(slide, 76, 220, 520, 270, C.white);
  text(slide, "Pod recovery drill", 100, 244, 260, 30, { size: 20, bold: true, fill: C.white });
  slide.shapes.add({ geometry: "rect", position: { left: 120, top: 322, width: 350, height: 3 }, fill: C.rule });
  slide.shapes.add({ geometry: "ellipse", position: { left: 112, top: 313, width: 20, height: 20 }, fill: C.red });
  slide.shapes.add({ geometry: "ellipse", position: { left: 285, top: 313, width: 20, height: 20 }, fill: C.amber });
  slide.shapes.add({ geometry: "ellipse", position: { left: 462, top: 313, width: 20, height: 20 }, fill: C.green });
  text(slide, "delete pod", 92, 344, 110, 28, { size: 14, fill: C.white });
  text(slide, "rollout", 258, 344, 110, 28, { size: 14, fill: C.white });
  text(slide, "HTTP 200", 442, 344, 110, 28, { size: 14, bold: true, fill: C.white });
  metric(slide, "21 sec", "backend pod recovery time", 102, 394, 220, C.green, C.white);
  panel(slide, 662, 220, 500, 306, C.white);
  text(slide, "After stable load", 688, 244, 260, 30, { size: 20, bold: true, fill: C.white });
  metric(slide, "6m / 115Mi", "backend pod A CPU / memory", 694, 306, 220, C.blue, C.white);
  metric(slide, "7m / 120Mi", "backend pod B CPU / memory", 934, 306, 220, C.blue, C.white);
  metric(slide, "2% CPU", "GKE node CPU", 694, 408, 180, C.green, C.white);
  metric(slide, "5%", "GKE node memory", 934, 408, 180, C.green, C.white);
  text(slide, "HPA stayed at 2 backend replicas with CPU far below the 70% target.", 160, 558, 860, 34, { size: 18 });
  footer(slide, "Sources: gke-pod-recovery-drill.md, gke-resource-utilization-after-stable-load.md", 7);
  return slide;
}
